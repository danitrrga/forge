#!/usr/bin/env python3
"""The `local_plugins` step of the generator (forge/marketplace.py, called from forge/sync.py) and its `local plugins`
row of `forge doctor` (forge/cli.py local_plugins_row).

`local_plugins` in config/forge.json is a list of forge-owned plugin folders (absolute or ~/...), each a directory
marketplace. The plugin's name is the `name` of <folder>/.claude-plugin/marketplace.json, which must list a plugin of
that name (the fixtures use `toylocal`, so a generator with a fixed name fails the first case). The step is one
machine action per folder, `claude plugin marketplace add <folder> --scope local`, while
~/.claude/plugins/known_marketplaces.json does not hold the marketplace at that path. Measured on Claude Code 2.1.308
(a probe in a toy HOME with a fresh, empty folder as cwd): the registry entry is what loads the plugin, and a local
scope run writes only <cwd>/.claude/settings.local.json besides it; so the add runs in a temporary folder that is
removed afterwards, which leaves no file of any project or of forge changed.

  * key absent or empty: nothing printed, nothing run, `forge doctor` row a SKIP that says NOT RUN, NOT ARMED.
  * unregistered: a dry-run prints the line and runs nothing; --apply runs the add once; a second run prints nothing and
    runs nothing.
  * one `!` line, exit 1 and no call for: a folder that is not there, one without marketplace.json, a marketplace that
    lists no plugin of its name, a `local_plugins` that is not a list of strings, a relative path, two folders with the
    same name. `claude` not on PATH, a timeout and a non-zero exit are `!` lines too, naming the command to run by hand.
  * `claude plugin install` and `claude plugin list` are never called (install writes enabledPlugins in the user's
    settings and breaks the per-project trim; list shows nothing for a plugin loaded without install).
  * the doctor row: PASS (how many it looked at, each registered at its path), FAIL naming `forge sync --apply` when a
    plugin is not registered or the registry holds it at another path, SKIP when off.

Everything runs in-process against a toy HOME, a toy forge.json and a toy config/. `claude` is a fake on PATH, PATH being
the fake directory alone (python3 and git linked in), never the system's behind it: the real `claude` is unreachable
(the first check proves it). tempfile's directory is the toy's, so a folder the step leaves behind is seen.

Seen failing on 77065e8 (master, before the step; this file as it is): every check about the step red, the controls
(key absent writes nothing, `install`/`list` never called) green. First messages:
  (a) "(a) dry-run: the line names the command it would run -- ['MODE: DRY-RUN ...']" (no line at all)
  (a) "(a) apply: one `claude plugin marketplace add <folder> --scope local` call -- []"
  (c) "(c) missing folder: one `!` line, exit 1 -- exit 0, []"
  (d) "(d) no claude on PATH: a `!` line holding the command as the fix, exit 1 -- exit 0, []"
  (f) "(f) the doctor has a `local plugins` row -- None" (cli.local_plugins_row does not exist)
Negative controls on the finished code, each mutation put back: see the commit message.
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("localplug-test-")
HOME = os.path.join(TOY, "home")
BIN = os.path.join(TOY, "bin")
TMP = os.path.join(TOY, "tmp")
for d in (HOME, BIN, TMP):
    os.makedirs(d)
tempfile.tempdir = TMP  # a folder the step makes and leaves behind is then in TMP, where the checks look
for tool in ("python3", "git"):
    os.symlink(shutil.which(tool), os.path.join(BIN, tool))
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
os.environ["PATH"] = BIN
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, sandbox.FORGE)
from forge import lib  # noqa: E402

BASE_SETTINGS = os.path.join(TOY, "forge-base.json")
with open(BASE_SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
lib.SETTINGS = BASE_SETTINGS
from forge import cli, hooks, sync  # noqa: E402
try:
    from forge import marketplace  # noqa: E402
except ImportError:  # master, before the step: every check about it goes red instead of the file crashing
    marketplace = None

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")  # this checkout may be a linked worktree, which never writes
hooks.USER_SETTINGS = os.path.join(HOME, ".claude", "settings.json")

failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:600]))


check("control: `claude` is not reachable but through the fake directory (PATH is %s)" % os.environ["PATH"],
      shutil.which("claude") is None and os.environ["PATH"] == BIN, shutil.which("claude"))

_n = [0]


def forge_json(local_plugins="ABSENT"):
    """Point lib at a toy forge.json with every integration off and `local_plugins` as given (the string "ABSENT" leaves the key out)."""
    _n[0] += 1
    doc = {"integrations": {k: False for k in lib.INTEGRATIONS}}
    if local_plugins != "ABSENT":
        doc["local_plugins"] = local_plugins
    path = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()
    return doc


def plugin_dir(name="toylocal", listed="toylocal", marketplace=True):
    """HOME/plug/<name>: a folder whose marketplace is called `name` and lists a plugin called `listed`."""
    d = os.path.join(HOME, "plug", name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, ".claude-plugin"))
    if marketplace:
        with open(os.path.join(d, ".claude-plugin", "marketplace.json"), "w") as f:
            json.dump({"name": name, "owner": {"name": "toy"},
                       "plugins": [] if listed is None else [{"name": listed, "source": "./"}]}, f)
        with open(os.path.join(d, ".claude-plugin", "plugin.json"), "w") as f:
            json.dump({"name": name, "version": "0.0.1", "description": "toy"}, f)
    return d


# The fake records argv and cwd, writes what the real one writes (the registry entry keyed by the marketplace's own name,
# and <cwd>/.claude/settings.local.json), and exits as told.
FAKE = '''#!%s
import json, os, sys, time
log = os.path.join(%r, "claude-calls.jsonl")
with open(log, "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
reg = os.path.join(%r, ".claude", "plugins", "known_marketplaces.json")
if sys.argv[1:4] == ["plugin", "marketplace", "add"]:
    path = sys.argv[4]
    name = json.load(open(os.path.join(path, ".claude-plugin", "marketplace.json")))["name"]
    os.makedirs(os.path.join(os.getcwd(), ".claude"), exist_ok=True)
    json.dump({"extraKnownMarketplaces": {name: {}}}, open(os.path.join(os.getcwd(), ".claude", "settings.local.json"), "w"))
    os.makedirs(os.path.dirname(reg), exist_ok=True)
    doc = json.load(open(reg)) if os.path.exists(reg) else {}
    doc[name] = {"source": {"source": "directory", "path": path}, "installLocation": path}
    json.dump(doc, open(reg, "w"))
    print("Successfully added marketplace")
'''
CALLS = os.path.join(TOY, "claude-calls.jsonl")
REGISTRY_FILE = os.path.join(HOME, ".claude", "plugins", "known_marketplaces.json")


def install_fake(exit_code=0, sleep=0):
    p = os.path.join(BIN, "claude")
    with open(p, "w") as f:
        f.write(FAKE % (sys.executable, TOY, HOME) + ("time.sleep(%d)\n" % sleep if sleep else "")
                + ("sys.stderr.write('toy failure\\n')\nsys.exit(%d)\n" % exit_code if exit_code else ""))
    os.chmod(p, 0o755)


def calls():
    return [json.loads(l) for l in open(CALLS) if l.strip()] if os.path.exists(CALLS) else []


def reset():
    for f in (CALLS, REGISTRY_FILE):
        if os.path.exists(f):
            os.remove(f)


def registry():
    try:
        with open(REGISTRY_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


_w = [0]


class World:
    """A toy config/ with no project (the step is machine-wide), and a run in the scope of `forge sync` / `--all`
    (user-scope files included), which is where the step belongs."""

    def __init__(self):
        _w[0] += 1
        self.base = os.path.join(TOY, "world%d" % _w[0])
        self.cfg = os.path.join(self.base, "config")
        self.pdir = os.path.join(self.cfg, "projects")
        os.makedirs(self.pdir)
        with open(os.path.join(self.cfg, "mcp-registry.json"), "w") as f:
            f.write('{"servers": {}}')
        with open(os.path.join(self.base, "secrets.json"), "w") as f:
            f.write("{}")
        os.symlink(os.path.join(self.base, "secrets.json"), os.path.join(self.cfg, "secrets.json"))
        with open(os.path.join(self.cfg, "project-relocations.json"), "w") as f:
            f.write('{"relocations": []}')

    def run(self, apply=True):
        """(exit code, everything the run printed)."""
        sync.CFG, lib.PROJECTS = self.cfg, self.pdir
        real = lib.context
        lib.context = lambda argv: lib.Ctx(bool(argv), None, True)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = sync.agent_config(["--apply"] if apply else [])
        finally:
            lib.context = real
        left = os.listdir(TMP)
        check("control: no temporary folder is left in tempfile's directory after the run (%s)" % left, left == [], left)
        return code, out.getvalue() + err.getvalue()


def bang(text):
    return [l for l in text.splitlines() if l.lstrip().startswith("!")]


def lplines(text):
    """The lines the step prints: `   local plugin X -> ...` and `   ! local plugin X -> ...`."""
    return [l for l in text.splitlines() if "local plugin" in l and "->" in l]


def only_adds(cs):
    """Every call is `plugin marketplace add ...`: nothing else, so never `install` and never `plugin list`."""
    return all(c["argv"][:3] == ["plugin", "marketplace", "add"] for c in cs)


# The check of (e) is itself seen able to fail: a recorded `install` or `list` makes only_adds False.
check("control (e): the only-adds check fails on a recorded `plugin install`",
      not only_adds([{"argv": ["plugin", "marketplace", "add", "/x", "--scope", "local"]}, {"argv": ["plugin", "install", "x@x"]}]), "")
check("control (e): the only-adds check fails on a recorded `plugin list`", not only_adds([{"argv": ["plugin", "list", "--json"]}]), "")

all_calls = []  # every call of the file, for (e)
install_fake()

# ---------------------------------------------------------------------------------------------- (g) key absent: no change
# Dry-runs first, all in the same state (the toy HOME's user settings are written by the first apply, which changes
# the text of the user-scope lines: a dry-run before and one after are not comparable).
forge_json()
folder = plugin_dir()
w = World()
absent_dry = w.run(apply=False)
forge_json([])
empty_dry = w.run(apply=False)
forge_json(["~/plug/toylocal"])
present_dry = w.run(apply=False)
forge_json()
absent_apply = w.run()
absent_dry_after = w.run(apply=False)
check("(g) key absent: no line about local plugins in a dry-run or an apply, no call",
      not lplines(absent_dry[1]) and not lplines(absent_apply[1]) and calls() == [], (lplines(absent_dry[1]), calls()))
check("(g) key absent: exit 0 and no `!` line", absent_dry[0] == 0 and absent_apply[0] == 0 and not bang(absent_dry[1] + absent_apply[1]),
      (absent_dry[0], absent_apply[0], bang(absent_dry[1])))
check("(g) an empty list prints exactly what an absent key prints (a dry-run, byte for byte)", empty_dry == absent_dry, (empty_dry, absent_dry))
check("(g) key absent: no `local plugins` heading in the output", "local plugins" not in absent_dry[1], absent_dry[1][-300:])

# ------------------------------------------------------------------------------------------- (a) unregistered, then (b)
reset()
forge_json(["~/plug/toylocal"])
w = World()
code, dry = present_dry
check("(a) dry-run: the line names the command it would run, `would`, the absolute folder and --scope local -- %s" % lplines(dry),
      any("would run" in l and "claude plugin marketplace add %s --scope local" % folder in l for l in lplines(dry)), dry)
check("(a) dry-run: exit 0, no `!` line, no call to claude", code == 0 and not bang(dry) and calls() == [], (code, bang(dry), calls()))
check("(a) dry-run: the registry is not written", registry() == {}, registry())
# With the key present the dry-run changes exactly the new lines: the heading and the one line.
fresh = [l for l in dry.splitlines() if l not in absent_dry[1].splitlines()]
check("(a) dry-run: against the key absent it adds exactly the heading and the line -- %s" % fresh,
      len([l for l in fresh if l.strip()]) == 2 and any("local plugins" in l for l in fresh) and len(lplines(dry)) == 1
      and [l for l in absent_dry[1].splitlines() if l not in dry.splitlines()] == [], fresh)
code, out = w.run()
cs = calls()
check("(a) apply: one `claude plugin marketplace add <folder> --scope local` call -- %s" % cs,
      [c["argv"] for c in cs] == [["plugin", "marketplace", "add", folder, "--scope", "local"]], cs)
cwd = cs[0]["cwd"] if cs else ""
check("(a) apply: the add ran in a temporary folder that is gone, not in the plugin folder, forge or HOME -- %s" % cwd,
      cs and os.path.dirname(os.path.realpath(cwd)) == os.path.realpath(TMP) and not os.path.exists(cwd), cwd)
check("(a) apply: exit 0, no `!` line, a line that says it registered", code == 0 and not bang(out)
      and any("registered" in l for l in lplines(out)), (code, lplines(out)))
check("(a) apply: the registry holds the marketplace at the folder", registry().get("toylocal", {}).get("source", {}).get("path") == folder, registry())
all_calls += calls()

code, again = w.run()
check("(b) registered: a second apply prints no line about local plugins and runs nothing -- %s" % lplines(again),
      lplines(again) == [] and "local plugins" not in again and len(calls()) == 1 and code == 0, (code, again[-300:]))
code, again_dry = w.run(apply=False)
check("(b) registered: a dry-run prints nothing about local plugins either", lplines(again_dry) == [] and "local plugins" not in again_dry, lplines(again_dry))
check("(b) registered: the output is the one of an absent key in the same state (a dry-run, byte for byte)",
      (code, again_dry) == absent_dry_after, (again_dry, absent_dry_after))

# ---------------------------------------------------------------------------------------- (c) one `!` line per bad folder
bad_cases = []
reset()
missing = os.path.join(HOME, "plug", "nowhere")
bad_cases.append(("missing folder", [missing], "not a directory"))
nomk = plugin_dir("nomarket", marketplace=False)
bad_cases.append(("marketplace.json missing", [nomk], "marketplace.json"))
mismatch = plugin_dir("mismatch", listed="another")
bad_cases.append(("name mismatch", [mismatch], "lists no plugin called mismatch"))
bad_cases.append(("not a list", "~/plug/toylocal", "local_plugins"))
bad_cases.append(("a relative path", ["plug/toylocal"], "not absolute"))
bad_cases.append(("an item that is not a string", [5], "local_plugins"))
dup_a = plugin_dir("toylocal")
dup_b = os.path.join(HOME, "plug", "copy")
shutil.rmtree(dup_b, ignore_errors=True)
shutil.copytree(dup_a, dup_b)
bad_cases.append(("two folders, one name", [dup_a, dup_b], "toylocal"))
for label, value, word in bad_cases:
    reset()
    forge_json(value)
    w = World()
    for apply in (False, True):
        code, out = w.run(apply=apply)
        b = bang(out)
        check("(c) %s (%s): exit 1, and a `!` line that names %r -- %s" % (label, "apply" if apply else "dry-run", word, b),
              code == 1 and len(b) >= 1 and any(word in l for l in b), (code, b))
        check("(c) %s (%s): no call to claude" % (label, "apply" if apply else "dry-run"), calls() == [] or label == "two folders, one name", calls())
    if label != "two folders, one name":
        check("(c) %s: exactly one `!` line" % label, len(b) == 1, b)
    all_calls += calls()
# Two folders, one name: the first is registered, the second named on a `!` line.
check("(c) two folders, one name: the first is registered and the second is the `!` line -- %s" % calls(),
      len(calls()) == 1 and calls()[0]["argv"][3:4] == [dup_a] and len(bang(out)) == 1 and lib.short(dup_b) in bang(out)[0], (calls(), bang(out)))

# One bad folder does not stop the good one.
reset()
forge_json([missing, folder])
w = World()
code, out = w.run()
check("(c) a bad folder beside a good one: exit 1, one `!` line, the good one registered -- %s" % calls(),
      code == 1 and len(bang(out)) == 1 and [c["argv"][3:4] for c in calls()] == [[folder]], (code, bang(out), calls()))
all_calls += calls()

# ------------------------------------------------------------------------------------------ (d) claude missing or failing
reset()
forge_json([folder])
w = World()
os.remove(os.path.join(BIN, "claude"))
code, out = w.run()
b = bang(out)
check("(d) no claude on PATH, apply: a `!` line that holds the command as the fix, exit 1 -- %s" % b,
      code == 1 and len(b) == 1 and "not on PATH" in b[0] and "claude plugin marketplace add %s --scope local" % folder in b[0], (code, b))
code, out = w.run(apply=False)
check("(d) no claude on PATH, dry-run: the would-run line, exit 0 (nothing runs, so nothing to miss)", code == 0 and not bang(out) and any("would run" in l for l in lplines(out)), (code, out[-300:]))
install_fake(exit_code=3)
reset()
code, out = w.run()
b = bang(out)
check("(d) claude exits 3: a `!` line with the exit code and the last line it said, exit 1 -- %s" % b,
      code == 1 and len(b) == 1 and "exited 3" in b[0] and "toy failure" in b[0], (code, b))
all_calls += calls()
install_fake(sleep=4)
reset()
real_timeout = marketplace.ADD_TIMEOUT if marketplace else None
if marketplace:
    marketplace.ADD_TIMEOUT = 1
try:
    code, out = w.run()
finally:
    if marketplace:
        marketplace.ADD_TIMEOUT = real_timeout
b = bang(out)
check("(d) claude does not finish in time: a `!` line that says it, exit 1 -- %s" % b, code == 1 and len(b) == 1 and "did not finish" in b[0], (code, b))
all_calls += calls()
install_fake()
reset()

# ------------------------------------------------------------------------------------------- (e) install and list are never called
check("(e) over every run of this file (%d calls) only `plugin marketplace add` was called" % len(all_calls), len(all_calls) >= 4 and only_adds(all_calls), all_calls)

# --------------------------------------------------------------------------------------------- (f) the doctor row
doctor_ok = hasattr(cli, "local_plugins_row")
check("(f) the doctor has a `local plugins` row (cli.local_plugins_row) -- %s" % doctor_ok, doctor_ok, None)
check("(f) the row is in CHECKS", any(n == "local plugins" for n, _, _ in cli.CHECKS), [n for n, _, _ in cli.CHECKS])


def row():
    res = cli.local_plugins_row()
    return res if isinstance(res, list) else [res]


if doctor_ok:
    forge_json()
    r = row()
    check("(f) key absent: one SKIP line that says NOT RUN, NOT ARMED -- %s" % r,
          len(r) == 1 and r[0].level == "SKIP" and r[0].detail.startswith(lib.NOT_ARMED) and "local_plugins" in r[0].detail, r)
    forge_json([])
    r = row()
    check("(f) empty list: the same SKIP", len(r) == 1 and r[0].level == "SKIP" and r[0].detail.startswith(lib.NOT_ARMED), r)
    reset()
    forge_json(["~/plug/toylocal", "~/plug/second"])
    plugin_dir("second", "second")
    r = row()
    check("(f) on, nothing registered: a FAIL that names both plugins and `python3 bin/forge sync --apply` -- %s" % r,
          len(r) == 1 and r[0].level == "FAIL" and "toylocal" in r[0].detail and "second" in r[0].detail and "python3 bin/forge sync --apply" in r[0].detail, r)
    w = World()
    w.run()
    r = row()
    check("(f) on, after the apply: a PASS that says it looked at 2 local plugins, each registered at its path -- %s" % r,
          len(r) == 1 and r[0].level == "PASS" and "2 local plugin" in r[0].detail and "toylocal" in r[0].detail and "second" in r[0].detail, r)
    # The path moved: the folder is renamed and the config follows, the registry still holds the old path.
    moved = os.path.join(HOME, "plug", "moved")
    shutil.rmtree(moved, ignore_errors=True)
    shutil.copytree(folder, moved)
    forge_json([moved, "~/plug/second"])
    r = row()
    check("(f) the registry holds the plugin at another path: a FAIL naming both paths and the fix -- %s" % r,
          len(r) == 1 and r[0].level == "FAIL" and lib.short(folder) in r[0].detail and lib.short(moved) in r[0].detail and "python3 bin/forge sync --apply" in r[0].detail, r)
    # The registered folder is gone.
    forge_json(["~/plug/toylocal", "~/plug/second"])
    shutil.rmtree(folder)
    r = row()
    check("(f) a configured folder that is gone: a FAIL that says so -- %s" % r,
          len(r) == 1 and r[0].level == "FAIL" and "not a directory" in r[0].detail, r)
    # And the doctor runs it as a row (cmd_doctor calls the callable).
    check("(f) cmd_doctor's rows include a callable for it", any(n == "local plugins" and callable(c) for n, c, _ in cli.CHECKS), "")
    # The row looks at nothing without the registry file: unregistered, not a crash.
    reset()
    plugin_dir()
    forge_json(["~/plug/toylocal"])
    r = row()
    check("(f) no registry file at all: a FAIL, not an exception", len(r) == 1 and r[0].level == "FAIL", r)

# ------------------------------------------------------------------------- (g) the framework's own step is unchanged
# tests/test_framework_sync.py runs unchanged; here only that the two share the one helper.
import forge.framework as fw  # noqa: E402
check("(g) framework's registry check and its add are the shared helpers' (no copy) -- %s" % getattr(fw, "marketplace", None),
      getattr(fw, "marketplace", None) is marketplace, None)

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL", f)
print("%d checks, %d failed" % (n_checks[0], len(failures)))
if failures:
    sys.exit(1)
