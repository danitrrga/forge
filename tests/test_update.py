#!/usr/bin/env python3
"""Step 6 of docs/toolchain-design.md: `forge update [NAME... | --all] [--apply]` (forge/update.py) moves the
`track: latest` entries of config/toolchain.json, then installs, relinks and relocks.

The world is a toy under /tmp and nothing of this machine is reachable (DTC-57: `forge toolchain --fix` in a toy world
once replaced the owner's real mise file through XDG_CONFIG_HOME): HOME, every XDG_* and MISE_* directory and
MISE_PYTHON_DEFAULT_PACKAGES_FILE point inside it, PATH holds only the toy `bin/` (a fake `mise`, `git` and `python3`,
each logging its argv and exiting 99 on one it does not expect), PyPI and the archives are a dict behind `update.fetch`,
and urllib's urlopen raises, so a build that reached the network fails. `world()` refuses to start when a path
forge would write is outside the toy. `forge skills` is a recorder (its real steps are scripts run from the checkout).

Written first and run against a forge/update.py that did not exist: "forge: error: argument command: invalid choice:
'update'" (every case). Each behaviour below was then broken once in the finished code and seen failing (13 mutations,
each put back):
  release-age guard dropped        "every mise latest ran with MISE_MINIMUM_RELEASE_AGE=0 from HOME = {('age=None', ...)}, want {('age=0', ...)}"
  not asked from HOME              the same case: "cwd=<the checkout>, want cwd=<the toy home>"
  frozen not skipped               "a frozen tool is skipped with its why = (False, True), want (True, False)"
  wheel check always true          "a pip library whose latest has no wheel for python 3.15 is held ... = (False, True), want (True, True)"
  python minor ignores new python  "python moving to 3.16: a cp316 wheel is enough ... = (['pip:native', 'skipped,', ...], False), want (['pip:native', '1.0.0', '->', '2.0.0'], True)"
  skills step always               "apply of a tool only: (exit, skills runs, lock written)" and the ordering case
  no stop at the first failure     "a failing toolchain --fix: exit 1 = 0, want 1"
  --apply with no scope allowed    "--apply with no NAME and no --all: (exit, manifest unchanged, nothing asked) = (0, False, ['mise latest ..."
  may_write ignored                "--apply where may_write refuses: (exit, manifest unchanged, nothing asked) = (1, False, ['mise latest python ..."
  pip verdict ignored              "a pip install that exits 0 and changes nothing is a failure, not a pass = (0, False, True), want (1, True, False)"
  archive path check removed       "a skill that moved upstream: held ... = (0, False, 'bbbb...', False), want (0, True, 'aaaa...', True)"
  checksum not written             "apply: the manifest is the old one with exactly those versions and that checksum, in the same format = ..."
  same commit downloads anyway     "archive at its newest commit: up to date, nothing downloaded = (1, False, ['https://github.com/o/toy-skills/archive/aaaa...tar.gz']), want (0, True, [])"
"""
import contextlib
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import cli, lib, toolchain, update  # noqa: E402
import sandbox  # noqa: E402

failures = []
OLD, NEW = "a" * 40, "b" * 40
TOY_URL = "https://github.com/o/toy-skills/archive/{{ version }}.tar.gz"
OLD_SUM = "sha256:" + "0" * 64

MISE = """#!%(py)s
import json, os, sys
a = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write("mise %%s | age=%%s | cwd=%%s\\n" %% (" ".join(a), os.environ.get("MISE_MINIMUM_RELEASE_AGE"), os.getcwd()))
state = os.environ["FAKE_MISE_STATE"]
if a[:1] == ["latest"] and len(a) == 2:
    got = json.loads(os.environ["FAKE_LATEST"]).get(a[1])
    if got is None:
        sys.stderr.write("mise ERROR no latest for %%s\\n" %% a[1])
        sys.exit(1)
    print(got)
    sys.exit(0)
if a == ["ls", "--json"]:
    out = {}
    for h in json.load(open(state)):
        out.setdefault(h["name"], []).append({"version": h["version"], "installed": True, "active": False})
    print(json.dumps(out))
    sys.exit(0)
if a[:1] == ["install"] and len(a) > 1 and all("@" in x for x in a[1:]):
    if os.environ.get("FAKE_MISE_INSTALL_FAIL"):
        sys.stderr.write("mise ERROR Failed to install tools: %%s\\n" %% " ".join(a[1:]))
        sys.exit(1)
    have = json.load(open(state))
    for spec in a[1:]:
        name, ver = spec.rsplit("@", 1)
        have.append({"name": name, "version": ver})
    json.dump(have, open(state, "w"))
    sys.exit(0)
sys.stderr.write("fake mise: unexpected argv %%r\\n" %% (a,))
sys.exit(99)
"""
GIT = """#!%(py)s
import json, os, sys
a = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write("git " + " ".join(a) + "\\n")
if len(a) == 3 and a[0] == "ls-remote" and a[2] == "HEAD":
    sha = json.loads(os.environ["FAKE_LS"]).get(a[1])
    if sha:
        print(sha + "\\tHEAD")
        sys.exit(0)
    sys.stderr.write("fatal: repository not found\\n")
    sys.exit(128)
sys.stderr.write("fake git: unexpected argv %%r\\n" %% (a,))
sys.exit(99)
"""
PY = """#!%(py)s
import json, os, sys
a = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write("python3 " + " ".join(a) + "\\n")
state = os.environ["FAKE_PIP_STATE"]
if a == ["-m", "pip", "list", "--format=json", "--disable-pip-version-check"]:
    sys.stdout.write(open(state).read())
    sys.exit(0)
if a[:3] == ["-m", "pip", "install"] and "--upgrade" not in a and "-U" not in a:
    if not os.environ.get("FAKE_NOOP"):
        have = json.load(open(state))
        for spec in (x for x in a[3:] if not x.startswith("-")):
            name, ver = spec.split("==")
            have = [h for h in have if h["name"].lower() != name.lower()] + [{"name": name, "version": ver}]
        json.dump(have, open(state, "w"))
    sys.exit(0)
sys.stderr.write("fake python3: unexpected argv %%r\\n" %% (a,))
sys.exit(99)
"""


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def tool(name, version, **k):
    return dict({"name": name, "version": version, "why": "toy " + name}, **k)


def doc_base():
    return {
        "tools": [
            tool("node", "26.0.0"),
            tool("python", "3.15.2"),
            tool("npm:frozen-tool", "1.0.0", track="frozen", why="the build that ships a skill, so it moves with that skill and not with forge update"),
            tool("npm:same-tool", "1.0.0"),
            tool("aqua:toy/browser", "0.1.0", when={"integration": "agent_browser"}),
            tool("http:toy-skills", OLD, track="latest", options={"url": TOY_URL, "checksum": OLD_SUM}),
        ],
        "pip": [tool("PyYAML", "6.0.0"), tool("native", "1.0.0"), tool("requests", "2.0.0")],
        "skills": [{"name": "alpha", "source": "http:toy-skills", "path": "skills/eng/alpha", "repo": "https://github.com/o/toy-skills",
                    "license_file": "LICENSE", "why": "toy"}],
    }


LATEST = {"node": "26.1.0", "python": "3.15.3", "npm:same-tool": "1.0.0", "npm:frozen-tool": "9.9.9"}


def archive(sha, paths=("skills/eng/alpha/SKILL.md", "LICENSE")):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in paths:
            data = ("content of %s at %s" % (p, sha)).encode()
            info = tarfile.TarInfo("toy-skills-%s/%s" % (sha, p))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def pypi(version, *files):
    return json.dumps({"info": {"version": version}, "urls": [{"filename": f, "packagetype": "bdist_wheel" if f.endswith(".whl") else "sdist"}
                                                              for f in files]}).encode()


def web(sha=NEW, paths=("skills/eng/alpha/SKILL.md", "LICENSE")):
    return {update.PYPI % "PyYAML": pypi("6.0.1", "PyYAML-6.0.1-py3-none-any.whl", "PyYAML-6.0.1.tar.gz"),
            update.PYPI % "native": pypi("2.0.0", "native-2.0.0-cp314-cp314-manylinux_2_28_%s.whl" % update.ARCH, "native-2.0.0.tar.gz"),
            update.PYPI % "requests": pypi("2.0.0", "requests-2.0.0-py3-none-any.whl"),
            TOY_URL.replace("{{ version }}", sha): archive(sha, paths)}


class World:
    n = 0

    def __init__(self, tmp, name, doc=None, with_mise=True):
        World.n += 1
        self.base = os.path.join(tmp, "%s-%d" % (name, World.n))
        b = self.base
        for d in ("home", "bin", "root/config", "xdg/config", "xdg/data", "xdg/state", "xdg/cache", "mise-config", "mise-data", "mise-cache", "mise-state"):
            os.makedirs(os.path.join(b, d), exist_ok=True)
        for n, body in (("mise", MISE), ("git", GIT), ("python3", PY)):
            if n == "mise" and not with_mise:
                continue
            with open(os.path.join(b, "bin", n), "w") as fh:
                fh.write(body % {"py": sys.executable})
            os.chmod(os.path.join(b, "bin", n), 0o755)
        self.home, self.root = os.path.join(b, "home"), os.path.join(b, "root")
        self.manifest = os.path.join(self.root, "config", "toolchain.json")
        self.log = os.path.join(b, "calls.log")
        self.mise_state, self.pip_state = os.path.join(b, "mise-state.json"), os.path.join(b, "pip-state.json")
        self.doc = doc if doc is not None else doc_base()
        self.write_manifest(self.doc)
        open(self.log, "w").close()
        json.dump([{"name": e["name"], "version": e["version"]} for e in self.doc["tools"] if "when" not in e], open(self.mise_state, "w"))
        json.dump([{"name": e["name"], "version": e["version"]} for e in self.doc["pip"]], open(self.pip_state, "w"))
        self.mise_file = os.path.join(b, "mise-config", "conf.d", "forge.toml")
        self.pip_file = os.path.join(b, "default-python-packages")
        for p, text in ((self.mise_file, toolchain.render_mise([e for e in self.doc["tools"] if "when" not in e])),
                        (self.pip_file, toolchain.render_pips(self.doc["pip"]))):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(text)
        os.makedirs(os.path.join(self.home, ".claude", "plugins"))
        with open(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json"), "w") as fh:
            json.dump({"plugins": {"toy@market": [{"version": "1.2.3", "lastUpdated": "t1"}]}}, fh)
        with open(os.path.join(b, "forge.json"), "w") as fh:
            json.dump({"integrations": {"agent_browser": False}}, fh)
        self.lock_file = os.path.join(self.root, "config", "forge.lock.json")
        self.env = {"HOME": self.home, "PATH": os.path.join(b, "bin"), "XDG_CONFIG_HOME": os.path.join(b, "xdg/config"),
                    "XDG_DATA_HOME": os.path.join(b, "xdg/data"), "XDG_STATE_HOME": os.path.join(b, "xdg/state"),
                    "XDG_CACHE_HOME": os.path.join(b, "xdg/cache"), "MISE_CONFIG_DIR": os.path.join(b, "mise-config"),
                    "MISE_DATA_DIR": os.path.join(b, "mise-data"), "MISE_CACHE_DIR": os.path.join(b, "mise-cache"),
                    "MISE_STATE_DIR": os.path.join(b, "mise-state"), "MISE_PYTHON_DEFAULT_PACKAGES_FILE": self.pip_file,
                    "PIP_REQUIRE_VIRTUALENV": "1", "FAKE_LOG": self.log, "FAKE_MISE_STATE": self.mise_state,
                    "FAKE_PIP_STATE": self.pip_state, "FAKE_LATEST": json.dumps(LATEST), "FAKE_LS": json.dumps({"https://github.com/o/toy-skills": NEW})}

    def write_manifest(self, doc):
        with open(self.manifest, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")

    def read(self, p):
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    def calls(self):
        return self.read(self.log).splitlines()

    def run(self, *argv, may_write=(True, ""), web_pages=None, skills_exit=0, **env):
        """(exit code, output, {"fetched": urls, "skills": [what a `forge skills --apply` saw]}) of cli.main(argv) in this process, in this world."""
        e = dict(self.env, **env)
        saved = {k: os.environ.get(k) for k in e}
        keep = (lib.ROOT, lib.HOME, lib.SETTINGS, lib.may_write, toolchain.MANIFEST, update.fetch, cli.cmd_skills, urllib.request.urlopen)
        pages = web() if web_pages is None else web_pages
        seen = {"fetched": [], "skills": []}

        def fake_fetch(url):
            seen["fetched"].append(url)
            if url not in pages:
                raise OSError("no network in tests: %s" % url)
            return pages[url]

        def fake_skills(a):
            seen["skills"].append({"apply": a.apply, "installed": any(" install " in " %s " % l for l in self.calls()), "locked": os.path.exists(self.lock_file)})
            return skills_exit

        def no_network(*a, **k):
            raise AssertionError("urlopen reached in a test: %r" % (a,))

        lib.ROOT, lib.HOME, lib.SETTINGS, toolchain.MANIFEST = self.root, self.home, os.path.join(self.base, "forge.json"), self.manifest
        lib.settings.cache_clear()
        lib.may_write = lambda: may_write
        update.fetch, cli.cmd_skills, urllib.request.urlopen = fake_fetch, fake_skills, no_network
        os.environ.update(e)
        out = io.StringIO()
        try:
            # DTC-57: refuse to start when a path forge would write is outside the toy world
            for p in (toolchain.mise_file(), toolchain.pip_file(), toolchain.MANIFEST, lockfile_path()):
                if not os.path.realpath(p).startswith(os.path.realpath(self.base) + os.sep):
                    raise SystemExit("test world escapes: %s is outside %s" % (p, self.base))
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    code = cli.main(list(argv))
                except SystemExit as ex:
                    code = ex.code
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            lib.ROOT, lib.HOME, lib.SETTINGS, lib.may_write, toolchain.MANIFEST, update.fetch, cli.cmd_skills, urllib.request.urlopen = keep
            lib.settings.cache_clear()
        return code, out.getvalue(), seen


def lockfile_path():
    from forge import lockfile
    return lockfile.path()


def line(out, label):
    return next((l for l in out.splitlines() if l.lstrip("! ").startswith(label + " ")), "")


def wheel_cases():
    ok = update.wheel_ok
    arch = "x86_64"
    for name, minor, good in (("a-1-py3-none-any.whl", 15, True), ("a-1-py2.py3-none-any.whl", 15, True), ("a-1-py312-none-any.whl", 15, True),
                              ("a-1-py316-none-any.whl", 15, False), ("a-1-cp315-cp315-manylinux_2_28_x86_64.whl", 15, True),
                              ("a-1-cp314-cp314-manylinux_2_28_x86_64.whl", 15, False),
                              ("a-1-cp39-abi3-manylinux2014_x86_64.whl", 15, True), ("a-1-cp316-abi3-manylinux2014_x86_64.whl", 15, False),
                              ("a-1-cp315-cp315t-manylinux_2_28_x86_64.whl", 15, False),
                              ("a-1-cp315-cp315-musllinux_1_2_x86_64.whl", 15, False),
                              ("a-1-cp315-cp315-manylinux_2_28_aarch64.whl", 15, False), ("a-1-cp315-cp315-win_amd64.whl", 15, False),
                              ("a-1.tar.gz", 15, False), ("a-1-py3-none-any.whl.metadata", 15, False)):
        want("wheel_ok(%s, 3.%d)" % (name, minor), ok(name, minor, arch), good)


def cases(tmp):
    # no manifest: NOT RUN, NOT ARMED, exit 0 (a checkout that pins nothing)
    w = World(tmp, "none")
    os.remove(w.manifest)
    code, out, _ = w.run("update")
    want("no config/toolchain.json: (exit, NOT RUN line)", (code, "NOT RUN, NOT ARMED" in out), (0, True))

    # dry-run: one line per entry, nothing written, nothing installed
    w = World(tmp, "dry")
    before = w.read(w.manifest)
    code, out, seen = w.run("update")
    want("dry-run: exit 0", code, 0)
    want("dry-run: a changed tool", line(out, "node").split(), ["node", "26.0.0", "->", "26.1.0", "latest"])
    want("dry-run: an unchanged tool says so", "(up to date)" in line(out, "npm:same-tool"), True)
    want("dry-run: a frozen tool is skipped with its why", ("skipped, frozen: the build that ships a skill" in line(out, "npm:frozen-tool"), "9.9.9" in out), (True, False))
    want("dry-run: a tool whose integration is off is skipped with the reason", "skipped, the integration agent_browser is not on" in line(out, "aqua:toy/browser"), True)
    want("dry-run: an archive moves to the newest commit", line(out, "http:toy-skills").split()[:5], ["http:toy-skills", "aaaaaaaaaaaa", "->", "bbbbbbbbbbbb", "latest"])
    want("dry-run: a pip library with a wheel moves", line(out, "pip:PyYAML").split()[:4], ["pip:PyYAML", "6.0.0", "->", "6.0.1"])
    want("dry-run: a pip library whose latest has no wheel for python 3.15 is held, naming the reason",
         ("skipped, held at 1.0.0: 2.0.0 has no wheel for python 3.15" in line(out, "pip:native"), "pip:native" in out), (True, True))
    want("dry-run: summary", "4 to update, 2 up to date, 3 skipped, 0 could not be asked" in out, True)
    want("dry-run: manifest, files and installs untouched", (w.read(w.manifest) == before, [l for l in w.calls() if " install " in l], os.path.exists(w.lock_file)), (True, [], False))
    # mise latest is asked from HOME with the release-age guard off; git only for ls-remote
    latest = [l for l in w.calls() if l.startswith("mise latest")]
    want("dry-run: mise latest asked for node, python and the same/frozen-free tools only",
         sorted(l.split(" | ")[0] for l in latest), ["mise latest node", "mise latest npm:same-tool", "mise latest python"])
    want("dry-run: every mise latest ran with MISE_MINIMUM_RELEASE_AGE=0 from HOME",
         {tuple(l.split(" | ")[1:]) for l in latest}, {("age=0", "cwd=%s" % os.path.realpath(w.home))})
    want("dry-run: git ls-remote asked for the repository's HEAD", [l for l in w.calls() if l.startswith("git")], ["git ls-remote https://github.com/o/toy-skills HEAD"])
    want("dry-run: the archive was downloaded once, PyPI asked for the three libraries",
         sorted(seen["fetched"]), sorted([TOY_URL.replace("{{ version }}", NEW)] + [update.PYPI % n for n in ("PyYAML", "native", "requests")]))

    # scoping
    code, out, _ = w.run("update", "node")
    want("NAME: only that entry", [l.split()[0] for l in out.splitlines() if "->" in l], ["node"])
    for given in ("pip:PyYAML", "PyYAML"):
        code, out, _ = w.run("update", given)
        want("NAME %s: the pip library" % given, [l.split()[0] for l in out.splitlines() if "->" in l], ["pip:PyYAML"])
    code, out, _ = w.run("update", "npm:frozen-tool")
    want("a frozen entry named is still skipped", (code, "skipped, frozen" in out, "->" in out), (0, True, False))
    code, out, _ = w.run("update", "nope", "node")
    want("an unknown NAME: exit 1 naming it and the known ones", (code, "unknown nope" in out, "known: node" in out), (1, True, True))
    code, out, _ = w.run("update", "node", "--all")
    want("NAME with --all is refused", code, 1)

    # --apply needs a scope, and may_write: both refuse before anything is asked or written
    for label, argv, kw in (("--apply with no NAME and no --all", ("update", "--apply"), {}),
                            ("--apply where may_write refuses", ("update", "--all", "--apply"), {"may_write": (False, "forge: toy refusal -- nothing written")})):
        w = World(tmp, "refused")
        before = w.read(w.manifest)
        code, out, seen = w.run(*argv, **kw)
        want("%s: (exit, manifest unchanged, nothing asked)" % label, (code, w.read(w.manifest) == before, w.calls(), seen["fetched"]), (1, True, [], []))
        want("%s: says why" % label, ("name the entries" in out) or ("toy refusal" in out), True)

    # --apply --all: the file, then toolchain --fix (ONE mise install), the pip install, skills, lock, in that order
    w = World(tmp, "apply")
    code, out, seen = w.run("update", "--all", "--apply")
    want("apply: exit 0", (code, out[-300:]) if code else code, 0)
    want_doc = doc_base()
    want_doc["tools"][0]["version"], want_doc["tools"][1]["version"] = "26.1.0", "3.15.3"
    want_doc["tools"][5]["version"] = NEW
    want_doc["tools"][5]["options"]["checksum"] = "sha256:" + hashlib.sha256(archive(NEW)).hexdigest()
    want_doc["pip"][0]["version"] = "6.0.1"
    want("apply: the manifest is the old one with exactly those versions and that checksum, in the same format",
         w.read(w.manifest), json.dumps(want_doc, indent=2, ensure_ascii=False) + "\n")
    installs = [l for l in w.calls() if l.startswith("mise install")]
    want("apply: ONE mise install of the three moved tools", installs and [l.split(" | ")[0] for l in installs], ["mise install node@26.1.0 python@3.15.3 http:toy-skills@" + NEW])
    want("apply: the pip library installed at its exact pin, no --upgrade",
         [l for l in w.calls() if l.startswith("python3 -m pip install")], ["python3 -m pip install --disable-pip-version-check PyYAML==6.0.1"])
    want("apply: the files forge writes follow the new manifest",
         (w.read(w.mise_file), w.read(w.pip_file)), (toolchain.render_mise([e for e in want_doc["tools"] if "when" not in e]), toolchain.render_pips(want_doc["pip"])))
    want("apply: skills --apply ran once, after the install and before the lock", seen["skills"], [{"apply": True, "installed": True, "locked": False}])
    want("apply: the lock was written", os.path.exists(w.lock_file) and json.loads(w.read(w.lock_file)).get("plugins"), {"toy@market": {"version": "1.2.3"}})

    # no archive moved: forge skills is not run
    w = World(tmp, "noarchive")
    code, out, seen = w.run("update", "node", "--apply")
    want("apply of a tool only: (exit, skills runs, lock written)", (code, seen["skills"], os.path.exists(w.lock_file)), (0, [], True))
    want("apply of one tool: the other pins are untouched", json.loads(w.read(w.manifest))["tools"][1]["version"], "3.15.2")

    # the first failing step stops the run, the file is already written, the rest is named
    w = World(tmp, "stop")
    code, out, seen = w.run("update", "--all", "--apply", FAKE_MISE_INSTALL_FAIL="1")
    want("a failing toolchain --fix: exit 1", code, 1)
    want("a failing toolchain --fix: skills and lock did not run", (seen["skills"], os.path.exists(w.lock_file)), ([], False))
    want("a failing toolchain --fix: says where it stopped and what to run from there",
         ("stopped at `forge toolchain --fix`" in out, "forge skills --apply; forge lock --apply" in out, "already holds the new pins" in out), (True, True, True))
    want("a failing toolchain --fix: the manifest holds the new pins", json.loads(w.read(w.manifest))["tools"][0]["version"], "26.1.0")
    w = World(tmp, "pipstuck")
    code, out, seen = w.run("update", "pip:PyYAML", "--apply", FAKE_NOOP="1")
    want("a pip install that exits 0 and changes nothing is a failure, not a pass", (code, "stopped at `pip install PyYAML==6.0.1`" in out, os.path.exists(w.lock_file)), (1, True, False))
    w = World(tmp, "skillsfail")
    code, out, seen = w.run("update", "--all", "--apply", skills_exit=1)
    want("a failing forge skills: exit 1, lock not run, named", (code, os.path.exists(w.lock_file), "stopped at `forge skills --apply`" in out), (1, False, True))

    # an entry that cannot be asked is a `!` line and exit 1, the others are still answered
    w = World(tmp, "error")
    code, out, _ = w.run("update", FAKE_LATEST=json.dumps(dict(LATEST, **{"npm:same-tool": "not a version"})))
    want("a bad mise latest: exit 1, a `!` line, the rest answered", (code, line(out, "npm:same-tool").startswith("!"), "26.1.0" in out), (1, True, True))
    code, out, _ = w.run("update", FAKE_LATEST=json.dumps({"node": "26.1.0"}))
    want("mise latest failing for an entry: its stderr is named", (code, "`mise latest python` failed (exit 1)" in out), (1, True))
    code, out, _ = w.run("update", web_pages={})
    want("no PyPI answer: exit 1, a `!` line for the library", (code, line(out, "pip:PyYAML").startswith("!")), (1, True))

    # archives: the same commit downloads nothing; a skill that moved upstream is held and the manifest keeps its pin
    w = World(tmp, "samecommit")
    code, out, seen = w.run("update", "http:toy-skills", FAKE_LS=json.dumps({"https://github.com/o/toy-skills": OLD}))
    want("archive at its newest commit: up to date, nothing downloaded", (code, "(up to date)" in out, seen["fetched"]), (0, True, []))
    code, out, seen = w.run("update", "http:toy-skills", "--apply", web_pages=web(paths=("skills/eng/other/SKILL.md", "LICENSE")))
    want("a skill that moved upstream: held with its name, exit 0, nothing written",
         (code, "skipped, held at aaaaaaaaaaaa: skills/eng/alpha (alpha) no longer in commit bbbbbbbbbbbb" in out, json.loads(w.read(w.manifest))["tools"][5]["version"], w.calls()[-1].startswith("git")),
         (0, True, OLD, True))
    code, out, _ = w.run("update", "http:toy-skills", FAKE_LS=json.dumps({}))
    want("git ls-remote failing: exit 1 naming it", (code, "`git ls-remote https://github.com/o/toy-skills HEAD` failed (exit 128)" in out), (1, True))

    # a python minor bump decides which wheels a library needs
    doc = doc_base()
    doc["pip"].append(tool("two", "1.0.0"))
    w = World(tmp, "minor", doc)
    pages = web()
    pages[update.PYPI % "native"] = pypi("2.0.0", "native-2.0.0-cp316-cp316-manylinux_2_28_%s.whl" % update.ARCH)
    pages[update.PYPI % "two"] = pypi("2.0.0", "two-2.0.0-cp315-cp315-manylinux_2_28_%s.whl" % update.ARCH)
    code, out, _ = w.run("update", web_pages=pages, FAKE_LATEST=json.dumps(dict(LATEST, python="3.16.0")))
    want("python moving to 3.16: a cp316 wheel is enough, a cp315 one is held",
         (line(out, "pip:native").split()[:4], "held at 1.0.0: 2.0.0 has no wheel for python 3.16" in line(out, "pip:two")),
         (["pip:native", "1.0.0", "->", "2.0.0"], True))
    code, out, _ = w.run("update", "pip:native", "pip:two", web_pages=pages, FAKE_LATEST=json.dumps(dict(LATEST, python="3.16.0")))
    want("python not in the scope: the pinned 3.15 decides", (line(out, "pip:native").startswith("pip:native") and "held" in line(out, "pip:native"), "->" in line(out, "pip:two")), (True, True))

    # no mise on PATH: the tool rows say NOT RUN, NOT ARMED and the exit is 1, never a pass
    w = World(tmp, "nomise", with_mise=False)
    code, out, _ = w.run("update")
    want("no mise: exit 1 and NOT RUN, NOT ARMED on the tools", (code, "NOT RUN, NOT ARMED: mise is not on PATH" in line(out, "node")), (1, True))


def main():
    tmp = sandbox.mkdtemp("update-test-")
    wheel_cases()
    cases(tmp)
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
