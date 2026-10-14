#!/usr/bin/env python3
"""config/toolchain.json and `forge toolchain` (toolchain-doctor). Once mise moved
its `latest` node and python; the global npm and pip packages stayed with the old versions, so the new
toolchain had none, and three forge tests failed with nothing in forge naming the cause.

1. The file itself (every case reads the real config/toolchain.json). Seen failing on the code before
   it existed: "toolchain.json = ('unreadable', \"[Errno 2] No such file or directory: '.../config/
   toolchain.json'\"), want a readable file". The file with a blank why, a duplicate name, cramjam and npm
   added fails four cases: "npm: every entry has a name, a pinned version and a why = [{'name':
   'get-shit-done-cc', ...'why': ' '}], want []", "pip: a name once = ['PyYAML', 'PyYAML'], want []", "pip:
   nothing that does not build on python 3.15 = ['cramjam'], want []", "npm does not list npm = ['npm'],
   want []".

2. `forge toolchain [--fix]`, against a fake npm and a fake python3 on PATH (see NPM_STUB). Seen failing
   on the code before it, 21 cases, every one on argparse: "everything present = (exit, levels) = (2, {}),
   want (0, {'npm:pnpm': 'PASS', ...})" with "forge: error: argument cmd: invalid choice: 'toolchain'
   (choose from 'sync', 'doctor', 'metrics', 'test', 'session-start')". Each mutation of the new code
   fails a case: a WARN taken for a missing one "--fix over a wrong version = (0, ['npm install -g
   pnpm@10.32.1', 'python3 -m pip install ... PyYAML==6.0.3'], '10.32.1'), want (0, [], '11.0.0')"; zero
   entries a pass "empty lists = (0, []), want (1, ['FAIL'])"; the recheck replaced by trusting the
   installer "an install that wrote nothing = (0, 'PASS'), want (1, 'FAIL')"; pip install --upgrade
   "--fix = (1, [... '--upgrade PyYAML==6.0.3']), want (0, [...])" (the fake python3 exits 99 on it);
   pip names compared raw "pip names normalised = (1, ['FAIL', 'FAIL', 'PASS', 'PASS']), want (0, ...)";
   one pip call per package "--fix over nothing = (0, [..., 'python3 -m pip install ... PyYAML==6.0.3',
   'python3 -m pip install ... google-api-...']), want (0, [...one call...])"; a failing `npm root -g`
   not checked "npm root -g fails = (1, {...}, ['npm install -g pnpm@10.32.1', ...]), want (..., [])".

3. The `toolchain` row of forge doctor (the check, never --fix; one result that says how many it checked;
   zero is a FAIL, non-negotiable 7). Seen failing on the code before it, 11 cases: "the row is registered =
   [], want [(None, 'forge toolchain --fix (installs what is missing; ...)')]", and every row case on
   "row, missing = (exit, lines, installs) = (0, [''], []), want (1, ['FAIL toolchain 2 missing: npm:pnpm,
   pip:PyYAML (checked 2 npm + 2 pip) -- forge toolchain --fix ...'], [])" (no row, so doctor printed none).
   Each mutation of the new code fails a case: the row running the install "row, a missing one and a wrong
   version = (1, ['npm install -g @scope/tool@1.2.3', 'python3 -m pip install ...']), want (1, [])"; an empty
   list a pass "row, empty lists = (0, ['PASS'], []), want (1, ['FAIL'], [])"; a WARN returned as FAIL "row,
   wrong version = (1, ['FAIL toolchain 1 present at another version ...']), want (0, ['WARN ...'])"; the row
   not registered "the row is registered = [], want [(<function toolchain_row ...>, ...)]"; a tool that could
   not be asked ignored "row, npm root -g fails = (0, 'PASS'), want (1, 'FAIL')".
"""
import contextlib
import io
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import cli, lib  # noqa: E402
import sandbox  # noqa: E402

failures = []
# The file the cases read is the fixture's, so a copy_engine copy (which has no config/toolchain.json) runs
# them: red there before (M1), "FileNotFoundError: .../config/toolchain.json" at REAL's open. This
# machine's own file is read too where it exists, by the same cases, so a bad pin of it is still red.
FIXTURE = os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "toolchain.json")
REAL = os.path.join(sandbox.FORGE, "config", "toolchain.json")
# Does not build on python 3.15: a pin of it would fail the install on every upgrade.
NOT_ON_315 = {"cramjam"}


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def file_cases(path, label):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        want("%s toolchain.json" % label, ("unreadable", str(e)), "a readable file")
        return
    for kind in ("npm", "pip"):
        entries = doc.get(kind)
        want("%s %s entries" % (label, kind), isinstance(entries, list) and len(entries) > 0, True)
        names = [e.get("name") for e in entries or []]
        want("%s %s: every entry has a name, a pinned version and a why" % (label, kind),
             [e for e in entries or [] if not all(isinstance(e.get(k), str) and e[k].strip() for k in ("name", "version", "why"))], [])
        want("%s %s: a name once" % (label, kind), sorted(n for n in names if names.count(n) > 1), [])
        want("%s %s: nothing that does not build on python 3.15" % (label, kind),
             sorted(set(n.lower() for n in names) & NOT_ON_315), [])
    # npm itself is not pinned here: it comes with node, and `npm install -g npm@x` would fight mise.
    want("%s npm does not list npm" % label, [e["name"] for e in doc.get("npm", []) if e.get("name") == "npm"], [])


# The fake machine: an `npm` and a `python3` on PATH, both Python scripts under the real interpreter.
# Each logs every argv to FAKE_LOG and exits 99 on one it does not expect, so a build that asks for
# something else (an upgrade, a downgrade, `npm ls`) is red, not silently served. npm's root is
# FAKE_NPM_ROOT; pip's installed set is the JSON list in FAKE_PIP_STATE. FAKE_NOOP makes an install
# exit 0 and write nothing (the wrong-root bug in one switch); FAKE_NPM_ROOT_FAIL breaks
# `npm root -g`. PIP_REQUIRE_VIRTUALENV and npm_config_prefix are the nets under the stubs: a build
# that reached the real pip or npm would be refused or land in the scratch dir, never in HOME.
NPM_STUB = """#!%(py)s
import json, os, sys
a = sys.argv[1:]
root = os.environ["FAKE_NPM_ROOT"]
open(os.environ["FAKE_LOG"], "a").write("npm " + " ".join(a) + "\\n")
if a == ["root", "-g"]:
    if os.environ.get("FAKE_NPM_ROOT_FAIL"):
        sys.stderr.write("npm error the prefix is gone\\n")
        sys.exit(1)
    print(root)
    sys.exit(0)
if a[:2] == ["install", "-g"] and len(a) == 3:
    if not os.environ.get("FAKE_NOOP"):
        name, ver = a[2].rsplit("@", 1)
        os.makedirs(os.path.join(root, name), exist_ok=True)
        json.dump({"name": name, "version": ver}, open(os.path.join(root, name, "package.json"), "w"))
    sys.exit(0)
sys.stderr.write("fake npm: unexpected argv %%r\\n" %% (a,))
sys.exit(99)
"""
PY_STUB = """#!%(py)s
import json, os, sys
a = sys.argv[1:]
state = os.environ["FAKE_PIP_STATE"]
open(os.environ["FAKE_LOG"], "a").write("python3 " + " ".join(a) + "\\n")
if a == ["-m", "pip", "list", "--format=json", "--disable-pip-version-check"]:
    sys.stdout.write(open(state).read())
    sys.stderr.write("WARNING: a pip notice that is not JSON\\n")
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


class World:
    """A fake machine under `base`: the stubs, a toolchain.json (or none), what npm and pip hold."""

    def __init__(self, base, doc, npm_have=None, pip_have=None):
        self.base = base
        os.makedirs(os.path.join(base, "bin"), exist_ok=True)
        for name, body in (("npm", NPM_STUB), ("python3", PY_STUB)):
            p = os.path.join(base, "bin", name)
            with open(p, "w") as fh:
                fh.write(body % {"py": sys.executable})
            os.chmod(p, 0o755)
        self.root = os.path.join(base, "npm-root")
        os.makedirs(self.root)
        self.log = os.path.join(base, "calls.log")
        open(self.log, "w").close()
        self.state = os.path.join(base, "pip-state.json")
        with open(self.state, "w") as fh:
            json.dump([{"name": n, "version": v} for n, v in (pip_have or {}).items()], fh)
        for n, v in (npm_have or {}).items():
            os.makedirs(os.path.join(self.root, n))
            with open(os.path.join(self.root, n, "package.json"), "w") as fh:
                json.dump({"name": n, "version": v}, fh)
        self.config = os.path.join(base, "toolchain.json")
        if doc is not None:
            with open(self.config, "w") as fh:
                fh.write(doc if isinstance(doc, str) else json.dumps(doc))

    def env(self, **extra):
        e = {"PATH": os.path.join(self.base, "bin") + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
             "FAKE_LOG": self.log, "FAKE_NPM_ROOT": self.root, "FAKE_PIP_STATE": self.state,
             "PIP_REQUIRE_VIRTUALENV": "1", "npm_config_prefix": os.path.join(self.base, "prefix")}
        e.update(extra)
        return e

    def run(self, *argv, only_row=None, **extra):
        """(exit code, the output's lines) of cli.main(argv) in this process, on this world's PATH.
        With `only_row`, forge doctor runs that CHECKS row alone: the others would ask the real machine."""
        env = self.env(**extra)
        saved, real_config, real_checks = {k: os.environ.get(k) for k in env}, getattr(cli, "TOOLCHAIN", None), cli.CHECKS
        cli.TOOLCHAIN = self.config
        if only_row:
            cli.CHECKS = [r for r in cli.CHECKS if r[0] == only_row]
        os.environ.update(env)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = cli.main(list(argv))
        except SystemExit as e:  # argparse: an unknown command
            code = e.code
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            cli.TOOLCHAIN, cli.CHECKS = real_config, real_checks
        return code, out.getvalue().splitlines()

    def installs(self):
        with open(self.log) as fh:
            return [l.rstrip("\n") for l in fh if " install " in l]

    def npm_version(self, name):
        with open(os.path.join(self.root, name, "package.json")) as fh:
            return json.load(fh)["version"]


def levels(lines):
    """{entry name: level} of a check's lines."""
    return {l.split()[1]: l.split()[0] for l in lines if l[:4] in ("PASS", "WARN", "FAIL")}


def line_of(lines, name):
    return ([l for l in lines if l.split()[1:2] == [name]] or [""])[0]


DOC = {"npm": [{"name": "pnpm", "version": "10.32.1", "why": "w"},
               {"name": "@scope/tool", "version": "1.2.3", "why": "w"}],
       "pip": [{"name": "PyYAML", "version": "6.0.3", "why": "w"},
               {"name": "google-api-python-client", "version": "2.200.0", "why": "w"}]}
ALL_NPM = {"pnpm": "10.32.1", "@scope/tool": "1.2.3"}
ALL_PIP = {"PyYAML": "6.0.3", "google-api-python-client": "2.200.0"}


def check_cases(tmp):
    n = [0]

    def world(*a, **k):
        n[0] += 1
        return World(os.path.join(tmp, "w%d" % n[0]), *a, **k)

    # Present: every line PASS, exit 0, and not one install, with --fix too.
    w = world(DOC, ALL_NPM, ALL_PIP)
    code, lines = w.run("toolchain")
    want("everything present = (exit, levels)", (code, levels(lines)),
         (0, {"npm:pnpm": "PASS", "npm:@scope/tool": "PASS", "pip:PyYAML": "PASS", "pip:google-api-python-client": "PASS"}))
    want("everything present: the summary says how many it checked", lines[-1:], ["SUMMARY: 4 passed, 0 warnings, 0 failures"])
    code, lines = w.run("toolchain", "--fix")
    want("--fix over everything present = (exit, installs)", (code, w.installs()), (0, []))

    # Missing: FAIL and exit 1, and without --fix nothing is installed.
    w = world(DOC, {"@scope/tool": "1.2.3"}, {"google-api-python-client": "2.200.0"})
    code, lines = w.run("toolchain")
    want("missing = (exit, levels)", (code, levels(lines)),
         (1, {"npm:pnpm": "FAIL", "npm:@scope/tool": "PASS", "pip:PyYAML": "FAIL", "pip:google-api-python-client": "PASS"}))
    want("missing: the detail names the pin", line_of(lines, "npm:pnpm").endswith("missing, pinned 10.32.1"), True)
    want("missing, no --fix: nothing installed", w.installs(), [])
    # --fix: exactly the missing ones, at the pin, in one pip call, no --upgrade; then green.
    code, lines = w.run("toolchain", "--fix")
    want("--fix = (exit, installs)", (code, w.installs()),
         (0, ["npm install -g pnpm@10.32.1", "python3 -m pip install --disable-pip-version-check PyYAML==6.0.3"]))
    want("--fix: levels after", levels(lines), {"npm:pnpm": "PASS", "npm:@scope/tool": "PASS", "pip:PyYAML": "PASS",
                                                "pip:google-api-python-client": "PASS"})

    # Nothing present: one npm call each, and ONE pip call for both pip entries.
    w = world(DOC, {}, {})
    code, lines = w.run("toolchain", "--fix")
    want("--fix over nothing = (exit, installs)", (code, w.installs()),
         (0, ["npm install -g pnpm@10.32.1", "npm install -g @scope/tool@1.2.3",
              "python3 -m pip install --disable-pip-version-check PyYAML==6.0.3 google-api-python-client==2.200.0"]))

    # Wrong version: a WARN, exit 0, and --fix never touches it (no downgrade, no upgrade).
    w = world(DOC, {"pnpm": "11.0.0", "@scope/tool": "1.2.3"}, {"PyYAML": "7.0", "google-api-python-client": "2.200.0"})
    code, lines = w.run("toolchain")
    want("wrong version = (exit, levels)", (code, levels(lines)),
         (0, {"npm:pnpm": "WARN", "npm:@scope/tool": "PASS", "pip:PyYAML": "WARN", "pip:google-api-python-client": "PASS"}))
    want("wrong version: the detail says both versions",
         line_of(lines, "npm:pnpm").endswith("present at 11.0.0, pinned 10.32.1; left as it is"), True)
    code, lines = w.run("toolchain", "--fix")
    want("--fix over a wrong version = (exit, installs, version)", (code, w.installs(), w.npm_version("pnpm")), (0, [], "11.0.0"))

    # pip names are compared the way pip does: case, - _ . alike.
    w = world(DOC, ALL_NPM, {"pyyaml": "6.0.3", "Google_Api.Python_Client": "2.200.0"})
    code, lines = w.run("toolchain")
    want("pip names normalised = (exit, levels)", (code, sorted(levels(lines).values())), (0, ["PASS"] * 4))

    # An empty list sees nothing, and seeing nothing is a FAIL (non-negotiable 7); so is no file, and a bad one.
    for label, doc in (("empty lists", {"npm": [], "pip": []}), ("no keys", {}), ("no file", None),
                       ("not JSON", "{npm: ["), ("a list", [1]), ("an entry without a version", {"npm": [{"name": "x"}]}),
                       # Red before: "a misspelled section = (exit, levels) = (0, ['PASS', 'PASS']), want (1,
                       # ['FAIL'])" and, for the doctor row, "(0, ['PASS'], []), want (1, ['FAIL'], [])".
                       # A misspelled section is an error, not a section that is not there: with "pips"
                       # the pip entries went unchecked and a missing PyYAML passed (round 10).
                       ("a misspelled section", {"npm": DOC["npm"], "pips": DOC["pip"]})):
        w = world(doc, ALL_NPM, ALL_PIP)
        code, lines = w.run("toolchain", "--fix")
        want("%s = (exit, levels)" % label, (code, list(levels(lines).values())), (1, ["FAIL"]))
        want("%s: nothing installed" % label, w.installs(), [])

    # Install exits 0 and writes nothing (the wrong-root bug): the recheck is the verdict.
    w = world(DOC, {}, ALL_PIP)
    code, lines = w.run("toolchain", "--fix", FAKE_NOOP="1")
    want("an install that wrote nothing = (exit, level)", (code, levels(lines).get("npm:pnpm")), (1, "FAIL"))
    want("an install that wrote nothing: the detail", line_of(lines, "npm:pnpm").endswith(
        "missing, pinned 10.32.1; still missing after `npm install -g pnpm@10.32.1`"), True)

    # npm root -g fails: every npm entry FAILs, and --fix tries nothing (there is no root to install into).
    w = world(DOC, ALL_NPM, ALL_PIP)
    code, lines = w.run("toolchain", "--fix", FAKE_NPM_ROOT_FAIL="1")
    want("npm root -g fails = (exit, levels, installs)", (code, levels(lines), w.installs()),
         (1, {"npm:pnpm": "FAIL", "npm:@scope/tool": "FAIL", "pip:PyYAML": "PASS", "pip:google-api-python-client": "PASS"}, []))

    # The real binary on a file of the real shape: a copy of the engine whose config/toolchain.json is the
    # fixture, and a fake machine that holds exactly what it pins.
    root = os.path.join(tmp, "engine")
    sandbox.copy_engine(root)
    sandbox.seed(root)
    with open(os.path.join(root, "config", "toolchain.json"), encoding="utf-8") as fh:
        real = json.load(fh)
    w = world(real, {e["name"]: e["version"] for e in real["npm"]}, {e["name"]: e["version"] for e in real["pip"]})
    r = subprocess.run([sys.executable, os.path.join(root, "bin", "forge"), "toolchain"], capture_output=True, text=True,
                       env={**w.env(), "HOME": os.path.join(w.base, "home"), "PYTHONDONTWRITEBYTECODE": "1"})
    count = len(real["npm"]) + len(real["pip"])
    want("bin/forge toolchain over a machine that holds the pins = (exit, summary)",
         (r.returncode, (r.stdout.splitlines() or [""])[-1], r.stderr), (0, "SUMMARY: %d passed, 0 warnings, 0 failures" % count, ""))


def row_cases(tmp):
    """The `toolchain` row of forge doctor: the check without --fix, how many it checked, the fix named."""
    n = [0]

    def world(*a, **k):
        n[0] += 1
        return World(os.path.join(tmp, "r%d" % n[0]), *a, **k)

    fix = " -- forge toolchain --fix (installs what is missing; a version that differs is only reported)"
    want("the row is registered", [(c, f) for n_, c, f in cli.CHECKS if n_ == "toolchain"],
         [(getattr(cli, "toolchain_row", None), fix[4:])])

    def doctor(w, **extra):
        code, lines = w.run("doctor", only_row="toolchain", **extra)
        return code, [" ".join(l.split()) for l in lines if l[:4] in ("PASS", "WARN", "FAIL")] or [""], w.installs()

    w = world(DOC, ALL_NPM, ALL_PIP)
    want("row, everything present = (exit, lines, installs)", doctor(w),
         (0, ["PASS toolchain checked 2 npm + 2 pip package(s), all present at their pin"], []))
    w = world(DOC, {"@scope/tool": "1.2.3"}, {"google-api-python-client": "2.200.0"})
    want("row, missing = (exit, lines, installs): the check never fixes", doctor(w),
         (1, ["FAIL toolchain 2 missing: npm:pnpm, pip:PyYAML (checked 2 npm + 2 pip)" + fix], []))
    w = world(DOC, {"pnpm": "11.0.0", "@scope/tool": "1.2.3"}, ALL_PIP)
    want("row, wrong version = (exit, lines, installs)", doctor(w),
         (0, ["WARN toolchain 1 present at another version, left as it is: npm:pnpm (checked 2 npm + 2 pip)" + fix], []))
    w = world(DOC, {"pnpm": "11.0.0"}, {})
    code, lines, installs = doctor(w)
    want("row, a missing one and a wrong version = (exit, installs)", (code, installs), (1, []))
    want("row, a missing one and a wrong version: the missing leads, the wrong one follows", lines[0].startswith(
        "FAIL toolchain 3 missing: npm:@scope/tool, pip:PyYAML, pip:google-api-python-client (checked 2 npm + 2 pip); "
        "also at another version: npm:pnpm"), True)
    for label, doc in (("empty lists", {"npm": [], "pip": []}), ("no file", None)):
        w = world(doc, ALL_NPM, ALL_PIP)
        code, lines, installs = doctor(w)
        want("row, %s = (exit, level, installs)" % label, (code, [l[:4] for l in lines], installs), (1, ["FAIL"], []))
        want("row, %s: names the fix" % label, lines[0].endswith(fix), True)
    # The row too: a misspelled section with pip empty on the machine is a FAIL, not a PASS over npm alone.
    w = world({"npm": DOC["npm"], "pips": DOC["pip"]}, ALL_NPM, {})
    code, lines, installs = doctor(w)
    want("row, a misspelled section = (exit, level, installs)", (code, [l[:4] for l in lines], installs), (1, ["FAIL"], []))
    # "_doc" and any other underscore key is a comment, as in the real file.
    w = world(dict(DOC, _doc="x", _why="y"), ALL_NPM, ALL_PIP)
    code, lines, installs = doctor(w)
    want("row, underscore keys are comments = (exit, level)", (code, [l[:4] for l in lines]), (0, ["PASS"]))
    w = world(DOC, ALL_NPM, ALL_PIP)
    code, lines, installs = doctor(w, FAKE_NPM_ROOT_FAIL="1")
    want("row, npm root -g fails = (exit, level)", (code, lines[0][:4]), (1, "FAIL"))


def toy_settings(tmp):
    """On a checkout with no config/forge.json (a pure engine clone) the "no file" cases read no
    settings, so GSD reads as off and a missing config/toolchain.json is a SKIP, not the FAIL they
    expect. Red there before: "no file = (exit, levels) = (0, []), want (1, ['FAIL'])", and the same
    for the doctor row. The toy file is the fixture's with GSD patched on, which is the machine this
    suite is written for; where the checkout has its own file it is read as before."""
    if os.path.exists(lib.SETTINGS):
        return
    with open(os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "forge.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["integrations"]["gsd"], doc["gsd_patches"] = True, True
    lib.SETTINGS = os.path.join(tmp, "forge.json")
    with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.settings.cache_clear()


def main():
    tmp = sandbox.mkdtemp("toolchain-test-")
    toy_settings(tmp)
    file_cases(FIXTURE, "the fixture's")
    if os.path.exists(REAL):
        file_cases(REAL, "this machine's")
    check_cases(tmp)
    row_cases(tmp)
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
