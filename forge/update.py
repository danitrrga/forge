"""forge update: move the entries of config/toolchain.json that follow upstream (docs/toolchain-design.md sections 4, 5).

Every entry is pinned to an exact version; `track` says whether this command may move it (`latest`, the default) or
leaves it (`frozen`, the why says why). What "latest" means depends on the entry:

  tool          `mise latest NAME`, asked from HOME (a project's mise.toml must not answer) and with
                MISE_MINIMUM_RELEASE_AGE=0 (the user's release-age guard would hide a version released today;
                this command only shows and records it, and the pin is installed by `forge toolchain --fix`)
  http: tool    the archive of a repository at a commit (an online skill's source): the newest commit of the
                repository (`git ls-remote REPO HEAD`), its archive downloaded for the new sha256 and read for
                the path of every skill that names it, so a skill that moved upstream is held, not broken
  pip library   the newest release on PyPI, only when it has a wheel for the python minor the manifest pins
                (a library that would not install leaves a new python with none: docs/toolchain-design.md section 5)

A dry-run prints one line per entry and writes nothing. --apply writes config/toolchain.json and then runs what makes
the machine match it, stopping at the first step that fails and saying what to run from there:
`forge toolchain --fix`, the install of each changed pip library (--fix never upgrades one that is present),
`forge skills --apply` when an archive changed, `forge lock --apply`.
"""
import argparse
import concurrent.futures
import contextlib
import hashlib
import io
import json
import os
import platform
import re
import shutil
import sys
import tarfile
import urllib.parse
import urllib.request

from forge import lib, lockfile, skillpins, toolchain

LATEST_TIMEOUT, FETCH_TIMEOUT, MAX_BYTES, WORKERS = 120, 60, 256 * 1024 * 1024, 6
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]*$")
SHA = re.compile(r"^([0-9a-f]{40})\s+HEAD$", re.M)
ARCHIVE_URL = re.compile(r"^(https://github\.com/[^/]+/[^/]+)/archive/\{\{ version \}\}\.tar\.gz$")
PYPI = "https://pypi.org/pypi/%s/json"
NEWER = "held: pin %s is newer than upstream's latest %s"  # never a downgrade; an archive's commit has no order, so it has none of this
ARCH = platform.machine()


class Row:
    """One entry's answer. status: "update" (latest differs), "same", "skip" (not asked, or held: `note` says why) or
    "error" (asked and could not be answered)."""

    def __init__(self, label, section, entry, status, latest=None, note="", checksum=None):
        self.label, self.section, self.entry = label, section, entry
        self.status, self.latest, self.note, self.checksum = status, latest, note, checksum


def fetch(url):
    """The bytes at an https URL. The one place this module reaches the network besides mise and git."""
    req = urllib.request.Request(url, headers={"User-Agent": "forge-update"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("%s is larger than %d MB" % (url, MAX_BYTES // 2**20))
    return data


def valid_version(v):
    """Whether `v` can be an exact pin in config/toolchain.json: a string of version characters that is not `latest`
    (the manifest refuses that one, and an answer that fails here is an error row, never a line that is written)."""
    return isinstance(v, str) and bool(VERSION.fullmatch(v)) and v.lower() != "latest"


def short(version):
    """A 40-character commit is shown as 12."""
    return version[:12] if re.fullmatch(r"[0-9a-f]{40}", version) else version


def wheel_ok(filename, minor, arch=None):
    """Whether the wheel `filename` installs on CPython 3.<minor> on this machine: a python tag of py3 or an older
    py3N with no ABI, or cp3<minor> (its own ABI, abi3 or none), or an older cp3N built for abi3; and a platform of
    `any` or a manylinux/linux build for this CPU. Nothing else (musllinux, a free-threaded cp315t, another CPU)."""
    parts = filename[:-len(".whl")].split("-") if filename.endswith(".whl") else []
    if len(parts) < 5:
        return False
    pys, abis, plats = (p.split(".") for p in parts[-3:])
    arch = arch or ARCH
    plat_ok = "any" in plats or any(p.startswith(("manylinux", "linux")) and arch in p for p in plats)
    for py in pys:
        m = re.fullmatch(r"(py|cp)3(\d*)", py)
        if not m:
            continue
        n = int(m.group(2)) if m.group(2) else None
        if m.group(1) == "py" and "none" in abis and (n is None or n <= minor):
            return plat_ok
        if m.group(1) == "cp" and n is not None and ((n == minor and set(abis) & {"cp3%d" % n, "abi3", "none"}) or (n < minor and "abi3" in abis)):
            return plat_ok
    return False


def requires_python_ok(spec, target):
    """Whether CPython `target`, (3, minor, micro), satisfies a PEP 440 `requires_python` specifier. No specifier is
    satisfied; one this cannot read is not (a release that would not install is held, never written)."""
    if not spec or not isinstance(spec, str):
        return True
    for raw in spec.split(","):
        clause = raw.strip()
        if not clause:
            continue
        m = re.fullmatch(r"(===|==|!=|<=|>=|~=|<|>)\s*(\d+(?:\.\d+)*)(\.\*)?", clause)
        if not m:
            return False
        op, ver_s, star = m.groups()
        ver = tuple(int(p) for p in ver_s.split("."))
        n = max(len(target), len(ver))
        tp, vp = target + (0,) * (n - len(target)), ver + (0,) * (n - len(ver))
        if op == "~=":
            if star or len(ver) < 2 or tp < vp or target[:len(ver) - 1] != ver[:-1]:
                return False
        elif op in ("==", "==="):
            if (target[:len(ver)] != ver) if star else (tp != vp):
                return False
        elif op == "!=":
            if (target[:len(ver)] == ver) if star else (tp == vp):
                return False
        elif (op == ">=" and tp < vp) or (op == "<=" and tp > vp) or (op == ">" and tp <= vp) or (op == "<" and tp >= vp):
            return False
    return True


def vkey(version):
    """A sortable key: the numbers of a version as numbers, its words (rc, a, beta) as text below every number, so a
    pre-release is older than its release; zeros that end a run of numbers do not count (1.0 is 1.0.0, and 1.0.0-rc.1
    is below 1.0)."""
    out = []
    for t in re.findall(r"\d+|[A-Za-z]+", version):
        if not t.isdigit():
            while out and out[-1] == (1, 0):
                out.pop()
        out.append((1, int(t)) if t.isdigit() else (0, t.lower()))
    while out and out[-1] == (1, 0):
        out.pop()
    return out + [(1, 0)]


def older(a, b):
    """Whether version `a` is older than version `b`."""
    return vkey(a) < vkey(b)


def resolve_tool(e):
    name = e["name"]
    if not shutil.which("mise"):
        return Row(name, "tools", e, "error", note=lib.NOT_ARMED + "mise is not on PATH -- install it (https://mise.jdx.dev)")
    if "checksum" in (e.get("options") or {}):
        return Row(name, "tools", e, "skip", note="has a checksum option that forge update cannot recompute for a mise tool")
    env = dict(os.environ, MISE_MINIMUM_RELEASE_AGE="0")
    code, out, err = toolchain.tool_run(["mise", "latest", name], LATEST_TIMEOUT, cwd=lib.HOME, env=env)
    latest = out.strip()
    if code != 0 or not valid_version(latest):
        return Row(name, "tools", e, "error", note="`mise latest %s` %s" % (name, "failed (exit %s): %s" % (code, err) if code != 0
                                                                          else "printed %r, not a version" % latest[:60]))
    if older(latest, e["version"]):
        return Row(name, "tools", e, "skip", note=NEWER % (e["version"], latest))
    return Row(name, "tools", e, "same" if latest == e["version"] else "update", latest)


def resolve_archive(e, skills):
    """An `http:` tool: the newest commit of its repository, the archive's new checksum, and the paths of `skills`
    (the skills entries that name this tool) inside it."""
    name, opts = e["name"], e.get("options") or {}
    m = ARCHIVE_URL.match(opts.get("url", ""))
    if not m:
        return Row(name, "tools", e, "skip", note="its url is not a GitHub archive of {{ version }}, so its newest commit cannot be found")
    code, out, err = toolchain.tool_run(["git", "ls-remote", m.group(1), "HEAD"], LATEST_TIMEOUT, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    found = SHA.search(out)
    if code != 0 or not found:
        return Row(name, "tools", e, "error", note="`git ls-remote %s HEAD` %s" % (m.group(1), "failed (exit %s): %s" % (code, err) if code != 0
                                                                                 else "printed no commit"))
    sha = found.group(1)
    if sha == e["version"]:
        return Row(name, "tools", e, "same", sha)
    url = opts["url"].replace("{{ version }}", sha)
    try:
        data = fetch(url)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = tar.getnames()
    except (OSError, ValueError, tarfile.TarError) as ex:
        return Row(name, "tools", e, "error", note="%s could not be downloaded and read (%s: %s)" % (url, type(ex).__name__, ex))
    top = members[0].split("/")[0] if members else ""
    missing = []
    for s in skills:
        for rel in (s.get("path", "").strip("/"), s.get("license_file")):
            if rel is not None:
                prefix = "%s/%s" % (top, rel) if rel else top
                if not any(n == prefix or n.startswith(prefix + "/") for n in members):
                    missing.append("%s (%s)" % (rel or "the whole repository", s["name"]))
    if missing:
        return Row(name, "tools", e, "skip", note="held at %s: %s no longer in commit %s -- a skill moved upstream" % (
            short(e["version"]), ", ".join(missing), short(sha)))
    return Row(name, "tools", e, "update", sha, checksum="sha256:" + hashlib.sha256(data).hexdigest())


def resolve_pip(e, target):
    """`target` is (3, minor, micro) of the python the libraries must install on. A release counts only with a wheel
    built for that minor (by its filename) whose `requires_python` (the file's, else the release's) the python meets."""
    label, minor = "pip:" + e["name"], target[1]
    try:
        doc = json.loads(fetch(PYPI % urllib.parse.quote(e["name"])))
        latest = doc["info"]["version"]
        release_req = doc["info"].get("requires_python")
        wheels = [(f["filename"], f.get("requires_python") or release_req)
                  for f in doc.get("urls", []) if f.get("packagetype") == "bdist_wheel" and not f.get("yanked")]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as ex:
        return Row(label, "pip", e, "error", note="PyPI answered no release for %s (%s: %s)" % (e["name"], type(ex).__name__, ex))
    if not valid_version(latest):
        return Row(label, "pip", e, "error", note="PyPI answered %r for %s, not a version" % (latest, e["name"]))
    if latest == e["version"]:
        return Row(label, "pip", e, "same", latest)
    if older(latest, e["version"]):
        return Row(label, "pip", e, "skip", note=NEWER % (e["version"], latest))
    fit = [(w, req) for w, req in wheels if wheel_ok(w, minor)]
    if not fit:
        return Row(label, "pip", e, "skip", note="held at %s: %s has no wheel for python 3.%d on %s (%d wheel(s))" % (
            e["version"], latest, minor, ARCH, len(wheels)))
    if not any(requires_python_ok(req, target) for _, req in fit):
        return Row(label, "pip", e, "skip", note="held at %s: %s requires python %s, and this is %s" % (
            e["version"], latest, " or ".join(sorted({str(req) for _, req in fit})), ".".join(map(str, target))))
    return Row(label, "pip", e, "update", latest)


def python_version(rows, doc):
    """(3, minor, micro) that the libraries must install on: the python the manifest will pin after this run, else the
    interpreter that is running."""
    new = next((r.latest for r in rows if r.label == "python" and r.status == "update"), None)
    pin = new or next((e["version"] for e in doc["tools"] if e["name"] == "python"), None)
    m = re.match(r"3\.(\d+)(?:\.(\d+))?", pin or "")
    return (3, int(m.group(1)), int(m.group(2) or 0)) if m else tuple(sys.version_info[:3])


def pmap(fn, items):
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(fn, items))


def select(doc, names):
    """([(label, section, entry)] in the manifest's order, the names that match no entry). A pip library answers to
    `pip:NAME`, or to NAME when no tool has that name."""
    every = [(e["name"], "tools", e) for e in doc["tools"]] + [("pip:" + e["name"], "pip", e) for e in doc["pip"]]
    if not names:
        return every, []
    tool_names = {e["name"] for e in doc["tools"]}
    keys = lambda label, sec: {label} | ({label[len("pip:"):]} - tool_names if sec == "pip" else set())  # noqa: E731
    chosen = [x for x in every if keys(x[0], x[1]) & set(names)]
    known = set().union(*(keys(l, s) for l, s, _ in every))
    return chosen, sorted(set(names) - known)


def resolve(doc, skills, chosen):
    """One Row per chosen entry: frozen, or switched off by a `when`, is a skip that says why; the rest are asked,
    tools and archives first (the python they resolve to decides which wheels a library needs), then libraries."""
    rows, ask = {}, []
    for label, sec, e in chosen:
        if e.get("track", "latest") == "frozen":
            rows[label] = Row(label, sec, e, "skip", note="frozen: " + e["why"])
        elif sec == "tools" and not toolchain.wanted(e)[0]:
            rows[label] = Row(label, sec, e, "skip", note=toolchain.wanted(e)[1])
        else:
            ask.append((label, sec, e))
    by_source = {}
    for s in skills:
        by_source.setdefault(s["source"], []).append(s)
    first = [x for x in ask if x[1] == "tools"]
    for (label, _, _), row in zip(first, pmap(lambda x: resolve_archive(x[2], by_source.get(x[0], [])) if x[0].startswith("http:")
                                              else resolve_tool(x[2]), first)):
        rows[label] = row
    target = python_version(list(rows.values()), doc)
    second = [x for x in ask if x[1] == "pip"]
    for (label, _, _), row in zip(second, pmap(lambda x: resolve_pip(x[2], target), second)):
        rows[label] = row
    return [rows[label] for label, _, _ in chosen]


def show(rows):
    width = max([len(r.label) for r in rows] + [0]) + 2
    for r in rows:
        if r.status in ("update", "same"):
            print("%-*s%s -> %s  %s%s" % (width, r.label, short(r.entry["version"]), short(r.latest), r.entry.get("track", "latest"),
                                         "  (up to date)" if r.status == "same" else ""))
        elif r.status == "skip":
            print("%-*sskipped, %s" % (width, r.label, r.note))
        else:
            print("! %-*s%s" % (width - 2, r.label, r.note))


def write_manifest(rows):
    """config/toolchain.json with the new version of each updated entry (and the new checksum of an archive), the rest
    of the file as it was."""
    with open(toolchain.MANIFEST, encoding="utf-8") as fh:
        doc = json.load(fh)
    for r in rows:
        entry = next(e for e in doc[r.section] if e["name"] == r.entry["name"])
        entry["version"] = r.latest
        if r.checksum:
            entry["options"]["checksum"] = r.checksum
    lib.write_text(toolchain.MANIFEST, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    lib.record("wrote", toolchain.MANIFEST)


def step_toolchain():
    return toolchain.cmd(argparse.Namespace(fix=True))


@contextlib.contextmanager
def with_python(version):
    """While it runs, the bin directory of mise's python@<version> is first on PATH, so that pip and the check ask the
    python that `forge toolchain --fix` just installed and not the one this process started with. Yields why not (the
    directory could not be found) or None; no version: nothing changes."""
    if not version:
        yield None
        return
    code, out, err = toolchain.tool_run(["mise", "where", "python@" + version], toolchain.LIST_TIMEOUT, cwd=lib.HOME)
    bindir = os.path.join(out.strip(), "bin") if code == 0 and out.strip() else ""
    if not bindir or not os.path.isfile(os.path.join(bindir, "python3")):
        yield "`mise where python@%s` gave no bin/python3 (%s)" % (version, err or out.strip() or "no path")
        return
    old = os.environ.get("PATH")
    os.environ["PATH"] = bindir + (os.pathsep + old if old else "")
    try:
        yield None
    finally:
        if old is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old


def step_pips(pips, python_ver=None):
    """Install each changed library at its new pin (`forge toolchain --fix` leaves a library that is present at
    another version alone), then check the manifest again: the verdict is the check, and a library that is
    still at its old version is a failure the check only calls a WARN. With `python_ver` (python itself moved) both run
    in that python, and the check runs even when no library changed: the new python must hold every pin."""
    with with_python(python_ver) as why:
        if why:
            print("! " + why)
            return 1
        ran = toolchain.install({"tools": [], "pip": pips}) if pips else {}
        results, _, where = toolchain.check()
    print(where)
    code = lib.report(results)
    stuck = [r for r in results if r.name in ran and r.level != "PASS"]
    for r in stuck:
        print("! %s: %s; %s" % (r.name, r.detail, ran[r.name]))
    return 1 if code or stuck else 0


def step_skills():
    from forge import cli  # cli imports this module
    return cli.cmd_skills(argparse.Namespace(apply=True))


def step_lock():
    return lockfile.cmd_lock(argparse.Namespace(apply=True))


def cmd(a):
    """forge update [NAME... | --all] [--apply]: see the module docstring. Exit 1 when an entry could not be asked, a
    NAME is unknown, an --apply names no scope, or a step failed."""
    names = list(a.names or [])
    if not os.path.exists(toolchain.MANIFEST):
        print(lib.NOT_ARMED + "no config/toolchain.json, so nothing is pinned to update (examples/toolchain.json is the template)")
        return 0
    doc, why = toolchain.entries()
    skills, why2 = skillpins.entries() if not why else ([], None)
    if why or why2:
        print("! %s" % (why or why2))
        return 1
    if names and a.all:
        print("! forge update: NAME... and --all together: give one or the other")
        return 1
    if a.apply and not (names or a.all):
        print("! forge update --apply: name the entries to update, or pass --all (a dry-run with no name lists every entry)")
        return 1
    if a.apply:
        ok, refusal = lib.may_write()
        if not ok:
            print(refusal)
            return 1
    chosen, unknown = select(doc, names)
    if unknown:
        print("! forge update: unknown %s (known: %s)" % (", ".join(unknown), ", ".join(l for l, _, _ in select(doc, [])[0])))
        return 1
    rows = resolve(doc, skills, chosen)
    show(rows)
    updates = [r for r in rows if r.status == "update"]
    errors = [r for r in rows if r.status == "error"]
    count = lambda s: sum(r.status == s for r in rows)  # noqa: E731
    print("%d to update, %d up to date, %d skipped, %d could not be asked" % (len(updates), count("same"), count("skip"), len(errors)))
    if not a.apply:
        if updates:
            print("nothing written; pass --apply with NAME... or --all to write config/toolchain.json and install them")
        return 1 if errors else 0
    if not updates:
        return 1 if errors else 0
    write_manifest(updates)
    print("wrote config/toolchain.json (%d entr%s)" % (len(updates), "y" if len(updates) == 1 else "ies"))
    steps = [("forge toolchain --fix", step_toolchain)]
    pips = [(r.entry["name"], r.latest) for r in updates if r.section == "pip"]
    new_python = next((r.latest for r in updates if r.label == "python"), None)
    if pips:
        steps.append(("pip install " + " ".join("%s==%s" % p for p in pips), lambda: step_pips(pips, new_python)))
    elif new_python:
        steps.append(("check the pip libraries in python@" + new_python, lambda: step_pips([], new_python)))
    if any(r.entry["name"].startswith("http:") for r in updates):
        steps.append(("forge skills --apply", step_skills))
    steps.append(("forge lock --apply", step_lock))
    for i, (name, fn) in enumerate(steps):
        print("\n== forge update: %s ==" % name, flush=True)
        code = fn()
        if code:
            print("\nforge update: stopped at `%s` (exit %s). config/toolchain.json already holds the new pins (restore it from its history "
                  "to go back). Fix that, then run: %s" % (name, code, "; ".join(n for n, _ in steps[i:])))
            return 1
    return 1 if errors else 0
