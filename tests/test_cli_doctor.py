#!/usr/bin/env python3
"""`forge cli [NAME]`, `forge cli --probe [NAME]` and the `cli built-ins` doctor row: forge notices when Claude
Code's own menu drifts from forge/cli_extras.py's registry, and shows a user their choice.

Runs in-process against a toy HOME, toy projects, a toy forge.json and a FAKE `claude` on PATH (a shell script that
prints a canned init line for `-p` and a version for `--version`; the real claude is never started).

  (a) `forge cli NAME`: one line per registry name, `kept` or `hidden` with why (cli_common, cli_keep, not kept), then
      the count of always-on built-ins; feature off: one line saying so and where to turn it on; a refused choice.
  (b) `forge cli --probe NAME`: runs claude -p with the documented flags in the project directory, compares the init
      line's slash_commands with what forge knows; an unknown name is `unknown: <name>` and exit 1; a fully known
      list says how many entries it looked at and exits 0; skill_keep.cli_known is honoured; zero entries is a
      failure; claude missing is `NOT RUN, NOT ARMED` and exit 0.
  (c) the doctor row: SKIP when the feature is off everywhere, PASS when each project's settings.local.json is what
      the generator would write, FAIL naming `python3 bin/forge sync --apply` after the file is edited by hand, WARN
      naming `forge cli --probe` when `claude --version` is not the registry's captured one.

Seen failing on the code before this change (`forge cli` is not a subcommand, and forge.cli_extras has no CAPTURED
and no listing, known_names or unknown):
  25 of 25 checks red, among them
  FAIL a: forge cli lists simplify as kept by cli_common -- exit 2, row None  (argparse: invalid choice: 'cli')
  FAIL b: --probe reports unknown: some-new-builtin -- (2, "...forge: error: argument cmd: invalid choice: 'cli'...")
  FAIL c: the row is registered in CHECKS -- ['skill refs', 'skill keep', ...]
  FAIL c: settings match: PASS naming how many projects and names it looked at -- [Result(level='FAIL', name='raised',
       detail="AttributeError: module 'forge.cli' has no attribute 'cli_builtins_row'")]
Negative controls, one wrong behaviour planted in the finished code per group and put back from a copy:
  a  the why of a cli_common name always cli_keep (cli_common ignored): "FAIL a: forge cli lists simplify as kept by
     cli_common -- exit 0, row ('hidden', 'not kept')" (2 red; the wrong row shown is the planted one)
  b  unknown() always empty (every listed name taken as known): "FAIL b: --probe reports unknown: some-new-builtin",
     "FAIL b: a global skill the project does not keep is unknown too" and "FAIL b: skill_keep.cli_known is honoured"
  c  the settings comparison skipped (`if wanted is not None` made `if False`): "FAIL c: after a hand edit the row is a
     FAIL naming the fix and the project -- [Result(level='PASS', name='cli built-ins', detail='looked at 2 project(s)
     against 30 registry name(s), each settings.local.json is what forge would write; ...')]"""
import contextlib
import io
import json
import os
import re
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("cli-doctor-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
from forge import lib  # noqa: E402


def forge_json(name, skill_keep):
    f = os.path.join(TOY, name)
    with open(f, "w", encoding="utf-8") as fh:
        json.dump({"integrations": {}, "skill_keep": skill_keep}, fh)
    return f


SETTINGS_ON = forge_json("forge-on.json", {"cli_common": ["simplify"]})
SETTINGS_OFF = forge_json("forge-off.json", {})
SETTINGS_KNOWN = forge_json("forge-known.json", {"cli_common": ["simplify"], "cli_known": ["some-new-builtin"]})
lib.SETTINGS = SETTINGS_ON
from forge import cli, cli_extras, hooks, mcp, skills  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")
APPLY = lib.Ctx(True, None, False)
# cli.settings_forge_would_write reads config/mcp-registry.json under lib.ROOT: a toy root with an empty registry.
ROOT = os.path.join(TOY, "root")
os.makedirs(os.path.join(ROOT, "config"))
lib.write_json(os.path.join(ROOT, "config", "mcp-registry.json"), {"servers": {}})
lib.ROOT = ROOT

failures, n_checks, n_world = [], [0], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", detail)


def use(settings, profiles):
    """Point forge at a toy forge.json and a fresh profile directory; `profiles` is {name: dict of keys} (project
    and project_path are added). Returns {name: project path}."""
    n_world[0] += 1
    lib.SETTINGS = settings
    lib.PROFILES = os.path.join(TOY, "profiles-%d" % n_world[0])
    os.makedirs(lib.PROFILES)
    paths = {}
    for name, keys in profiles.items():
        p = os.path.join(TOY, "proj-%d-%s" % (n_world[0], name))
        os.makedirs(os.path.join(p, ".claude"))
        paths[name] = p
        lib.write_json(os.path.join(lib.PROFILES, name + ".claude.json"), dict({"project": name, "project_path": p}, **keys))
    return paths


def reset_globals(*names):
    d = os.path.join(HOME, ".claude", "skills")
    for n in names:
        os.makedirs(os.path.join(d, n))
    skills.global_skills.cache_clear()


reset_globals("g1", "g2")

BIN = os.path.join(TOY, "bin")
EMPTY = os.path.join(TOY, "empty-path")
os.makedirs(BIN)
os.makedirs(EMPTY)
LOG = os.path.join(TOY, "claude-argv.log")
REAL_PATH = os.environ["PATH"]


def fake_claude(version="2.1.308", commands=(), before=()):
    """A `claude` first on PATH that answers --version, and for -p logs the directory it ran in and its argv,
    prints each object of `before`, the init line carrying `commands` as slash_commands, and one line after it."""
    init = json.dumps({"type": "system", "subtype": "init", "slash_commands": list(commands)})
    lines = "".join("printf '%%s\\n' '%s'\n" % json.dumps(b) for b in before)
    script = ("#!/bin/sh\n"
              "case \"$1\" in\n"
              "  --version) echo '%s (Claude Code)'; exit 0;;\n"
              "  -p) echo \"$PWD $*\" >> '%s'\n%s"
              "      printf '%%s\\n' '%s'\n"
              "      printf '%%s\\n' '{\"type\":\"result\"}';;\n"
              "esac\n") % (version, LOG, lines, init)
    f = os.path.join(BIN, "claude")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(script)
    os.chmod(f, os.stat(f).st_mode | stat.S_IXUSR)
    os.environ["PATH"] = BIN + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
    if os.path.exists(LOG):
        os.remove(LOG)


def no_claude():
    f = os.path.join(BIN, "claude")
    if os.path.exists(f):
        os.remove(f)
    os.environ["PATH"] = EMPTY


def forge_cli(*args):
    """(exit code, stdout) of `forge cli ...` through the real parser."""
    out, code = io.StringIO(), None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["cli"] + list(args))
    except SystemExit as e:
        code = e.code
    return code, out.getvalue()


def table(text):
    """{name: (state, why)} from the kept/hidden lines of `forge cli`."""
    rows = {}
    for l in text.splitlines():
        m = re.match(r"^(kept|hidden)\s+(\S+)\s+\((.*)\)$", l)
        if m:
            rows[m.group(2)] = (m.group(1), m.group(3))
    return rows


# ---- (a) forge cli NAME
paths = use(SETTINGS_ON, {"common": {"skills_keep": []},
                          "keeper": {"skills_keep": [], "cli_keep": ["team-onboarding", "login"]},
                          "star": {"skills_keep": [], "cli_keep": ["*"]},
                          "bad": {"skills_keep": [], "cli_keep": ["nope"]}})
HIDEABLE = getattr(cli_extras, "HIDEABLE", {})
code, out = forge_cli("common")
rows = table(out)
check("a: forge cli lists simplify as kept by cli_common", code == 0 and rows.get("simplify") == ("kept", "cli_common"),
      "exit %s, row %s" % (code, rows.get("simplify")))
check("a: ... and loop as hidden, not kept", rows.get("loop") == ("hidden", "not kept"), rows.get("loop"))
check("a: one line per registry name", len(HIDEABLE) == 30 and sorted(rows) == sorted(HIDEABLE), "%d rows" % len(rows))
check("a: the count of always-on built-ins and that they have no switch",
      any(str(len(cli_extras.ALWAYS)) in l and "no switch" in l for l in out.splitlines()), out.splitlines()[-1:])
code, out = forge_cli("keeper")
rows = table(out)
check("a: cli_keep names are kept, why cli_keep", rows.get("team-onboarding") == ("kept", "cli_keep")
      and rows.get("login") == ("kept", "cli_keep"), (rows.get("team-onboarding"), rows.get("login")))
check("a: cli_common is still kept beside cli_keep", rows.get("simplify") == ("kept", "cli_common"), rows.get("simplify"))
check("a: another name stays hidden", rows.get("loop") == ("hidden", "not kept"), rows.get("loop"))
code, out = forge_cli("star")
rows = table(out)
check("a: cli_keep ['*'] keeps every name", rows and all(s == "kept" for s, _ in rows.values()), out[:200])
code, out = forge_cli("bad")
check("a: a refused choice names the name and exits 1", code == 1 and "nope" in out, (code, out[:200]))
code, out = forge_cli("no-such-project")
check("a: an unknown project exits 1 and names the known ones", code == 1 and "common" in out, (code, out[:200]))
os.environ["CLAUDE_PROJECT_DIR"] = paths["keeper"]
code, out = forge_cli()
os.environ.pop("CLAUDE_PROJECT_DIR")
check("a: no NAME: the current project", code == 0 and table(out).get("login") == ("kept", "cli_keep"), (code, out[:120]))

use(SETTINGS_OFF, {"plain": {"skills_keep": []}})
code, out = forge_cli("plain")
check("a: feature off: one line saying so and how to turn it on",
      code == 0 and len(out.strip().splitlines()) == 1 and "off" in out and "cli_common" in out and "cli_keep" in out
      and "Choose which built-ins a project shows" in out, (code, out))

# ---- (b) forge cli --probe NAME
paths = use(SETTINGS_ON, {"p": {"skills_keep": ["g1"]}})
proj = paths["p"]
os.makedirs(os.path.join(proj, ".claude", "skills", "mine"))
os.makedirs(os.path.join(proj, ".claude", "commands"))
open(os.path.join(proj, ".claude", "commands", "mycmd.md"), "w").close()
os.makedirs(os.path.join(proj, ".claude", "workflows"))
open(os.path.join(proj, ".claude", "workflows", "myflow.js"), "w").close()
known = ["help", "model", "simplify", "login", "g1", "mine", "mycmd", "myflow", "heapdump", "design-consent",
         "__remote-workflow", "plugin:thing", "agents"]
fake_claude(commands=known, before=[{"type": "system", "subtype": "hook_started"}])
code, out = forge_cli("--probe", "p")
check("b: a fully known list: exit 0, nothing unknown, says how many it looked at",
      code == 0 and "unknown:" not in out and ("looked at %d" % len(known)) in out, (code, out[-300:]))
argv = open(LOG).read() if os.path.exists(LOG) else ""
check("b: claude ran with the documented flags in the project directory",
      argv.startswith(os.path.realpath(proj) + " ") and "-p ok --model haiku --output-format stream-json --verbose "
      "--no-session-persistence --max-turns 1" in argv, argv)
fake_claude(commands=known + ["some-new-builtin", "g2"])
code, out = forge_cli("--probe", "p")
check("b: --probe reports unknown: some-new-builtin", code == 1 and "unknown: some-new-builtin" in out, (code, out[-300:]))
check("b: a global skill the project does not keep is unknown too", "unknown: g2" in out, out[-300:])
lib.SETTINGS = SETTINGS_KNOWN
code, out = forge_cli("--probe", "p")
check("b: skill_keep.cli_known is honoured", "unknown: some-new-builtin" not in out and "unknown: g2" in out, out[-300:])
lib.SETTINGS = SETTINGS_ON
fake_claude(commands=[])
code, out = forge_cli("--probe", "p")
check("b: zero entries is a failure", code == 1 and "0 entries" in out, (code, out[-300:]))
no_claude()
code, out = forge_cli("--probe", "p")
check("b: claude missing: NOT RUN, NOT ARMED and exit 0", code == 0 and "NOT RUN, NOT ARMED: claude is not on PATH" in out,
      (code, out[-300:]))


# ---- (c) the doctor row
def row():
    try:
        res = cli.cli_builtins_row()
    except Exception as e:  # the code before this change: no such row
        return [lib.Result("FAIL", "raised", "%s: %s" % (type(e).__name__, e))]
    return res if isinstance(res, list) else [res]


def regenerate(name):
    prof = lib.profiles()[name]
    skills.write_settings_local(APPLY, mcp.with_denied_tools(prof, [], {}), None, None, hooks.project_hooks(prof),
                                cli_extras.common_setting())


check("c: the row is registered in CHECKS", any(name == "cli built-ins" for name, _, _ in cli.CHECKS),
      [name for name, _, _ in cli.CHECKS])
use(SETTINGS_OFF, {"plain": {"skills_keep": []}})
fake_claude()
res = row()
check("c: feature off everywhere: SKIP with the switched-off wording",
      len(res) == 1 and res[0].level == "SKIP" and res[0].detail.startswith(lib.NOT_ARMED) and "off" in res[0].detail, res)

paths = use(SETTINGS_ON, {"a": {"skills_keep": []}, "b": {"skills_keep": [], "cli_keep": ["login"]}})
for name in paths:
    regenerate(name)
fake_claude(version=getattr(cli_extras, "CAPTURED", "0"))
res = row()
check("c: settings match: PASS naming how many projects and names it looked at",
      len(res) == 1 and res[0].level == "PASS" and "2 project" in res[0].detail and "%d registry name" % len(HIDEABLE) in res[0].detail,
      res)
slp = os.path.join(paths["a"], ".claude", "settings.local.json")
doc = lib.read_json(slp)
doc["env"].pop("DISABLE_LOGOUT_COMMAND")  # a hand edit of one of forge's entries
lib.write_json(slp, doc)
res = row()
check("c: after a hand edit the row is a FAIL naming the fix and the project",
      res[0].level == "FAIL" and " in a -- python3 bin/forge sync --apply" in res[0].detail, res)
regenerate("a")
fake_claude(version="9.9.9")
res = row()
check("c: a version that is not the captured one: WARN naming forge cli --probe",
      any(r.level == "WARN" and "forge cli --probe" in r.detail and "9.9.9" in r.detail for r in res), res)
no_claude()
res = row()
check("c: claude missing: a NOT RUN, NOT ARMED line, the settings result still there",
      any(r.level == "SKIP" and r.detail.startswith(lib.NOT_ARMED) and "claude" in r.detail for r in res)
      and any(r.level == "PASS" for r in res), res)

print("%d failure(s) over %d checks" % (len(failures), n_checks[0]))
os.environ["PATH"] = REAL_PATH
sandbox.cleanup(failures)
sys.exit(1 if failures else 0)
