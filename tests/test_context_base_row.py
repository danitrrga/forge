#!/usr/bin/env python3
"""Part 2.5 (base context), unit U8: the `context base` row of `forge doctor` (forge/cli.py context_base_row).

The row runs fwx's `context-base check` and `context-base audit` for each target: every ~/.claude/settings.json entry
whose command runs `subagent_context.py --file F [--source S]`, and every profile with `framework: true`. One result
per target: any exit other than 0 and 77 is a FAIL (naming the target, what fwx printed and the `python3 <fwx>/bin/fwx
context-base ...` command that reproduces it), 77 is a SKIP that starts `NOT RUN, NOT ARMED`, 0 is a PASS with fwx's
last line. No fwx, or no target: a SKIP, NOT RUN, NOT ARMED.

A toy world per case: a toy forge root, HOME with a settings.json, profiles, a forge.json whose framework.plugin_source
points at a toy plugin directory whose `bin/fwx` is a fake (a python script that logs its argv and answers from a plan
file), and a PATH holding only the fake's directory with python3 linked in (standing order 10: no real program behind it).

Seen failing, before the row existed (54 cases then, 39 failures, exit 1): every row case came back CRASH with AttributeError:
module 'forge.cli' has no attribute 'context_base_row'; "the row is registered" listed CHECKS without it.
Negative control (a copy of the checkout with the row mutated, this file run against it): with `elif code == lib.NOT_RUN:`
made `elif code != 0 and code is not None:` every non-zero exit of fwx falls to the 77 branch, and 11 of the 56 cases went
red, among them "FAIL swallowed as SKIP: every step of the target exits 1: SKIP, want FAIL", "exit 1 of a hook check is a
FAIL: PASS, want FAIL" and "exit 2 (usage) is a FAIL, not swallowed: PASS, want FAIL"."""
import json
import os
import shlex
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

REPO = sandbox.FORGE
TOY = sandbox.mkdtemp("context-base-row-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, REPO)
from forge import lib  # noqa: E402

lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
from forge import cli, hooks  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
hooks.USER_SETTINGS = SETTINGS
REAL_PATH, REAL_ROOT, REAL_PROFILES = os.environ.get("PATH", ""), lib.ROOT, lib.PROFILES
failures, n_cases, _n = [], [0], [0]
FILE, SOURCE = "/toy/forge/framework-discuss/context-base.md", "/toy/forge/framework-discuss/plan/CONTEXTO-AGENTES.md"
CMD = "python3 /toy/forge/plugins/fwx/hooks/subagent_context.py --file %s --source %s" % (FILE, SOURCE)

# The fake `fwx`: logs its argv, then answers with the first plan rule whose `match` is in the arguments.
FAKE = '''#!/usr/bin/env python3
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
open(os.path.join(here, "calls.log"), "a").write(json.dumps(args) + "\\n")
text = " ".join(args)
for rule in json.load(open(os.path.join(here, "plan.json"))):
    if rule["match"] in text:
        time.sleep(rule.get("sleep", 0))
        sys.stdout.write(rule.get("out", ""))
        sys.stderr.write(rule.get("err", ""))
        sys.exit(rule["rc"])
sys.exit(0)
'''


def check(label, ok, detail=""):
    n_cases[0] += 1
    if not ok:
        failures.append("%s: %s" % (label, str(detail)[:600]))


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)


def world(plan=(), commands=(CMD,), profiles=None, fwx=True, section=True):
    """A toy forge root, HOME and PATH for one case; returns the fake's directory. `commands`: the SubagentStart hook
    commands in settings.json; `profiles`: {name: extra profile fields}; `fwx` False: a plugin directory without bin/fwx;
    `section` False: no `framework` table in forge.json."""
    _n[0] += 1
    top = os.path.join(TOY, "case-%d" % _n[0])
    root, plugin = os.path.join(top, "forge"), os.path.join(top, "plugin")
    os.makedirs(os.path.join(root, "config", "profiles"))
    os.makedirs(os.path.join(plugin, "bin"))
    if fwx:
        write(os.path.join(plugin, "bin", "fwx"), FAKE, stat.S_IRWXU)
        write(os.path.join(plugin, "bin", "plan.json"), json.dumps(list(plan)))
    for name, extra in (profiles or {}).items():
        project = os.path.join(top, name)
        os.makedirs(project)
        write(os.path.join(root, "config", "profiles", name + ".claude.json"),
              json.dumps(dict({"project": name, "project_path": project}, **extra)))
    groups = {"SubagentStart": [{"hooks": [{"type": "command", "command": c}]} for c in commands]} if commands else {}
    groups["SessionStart"] = [{"hooks": [{"type": "command", "command": "python3 /toy/forge/bin/forge session-start"}]}]
    if os.path.exists(SETTINGS):
        os.remove(SETTINGS)
    write(SETTINGS, json.dumps({"hooks": groups}))
    bindir = os.path.join(top, "bin")
    os.makedirs(bindir)
    os.symlink(sys.executable, os.path.join(bindir, "python3"))
    os.environ["PATH"] = bindir  # only the fake directory (standing order 10)
    lib.ROOT, lib.PROFILES = root, os.path.join(root, "config", "profiles")
    lib.SETTINGS = os.path.join(top, "forge.json")
    doc = {"integrations": {k: False for k in lib.INTEGRATIONS}, "user_settings": {}, "user_hooks": []}
    if section:
        doc["framework"] = {"plugin_source": {"source": "directory", "path": plugin}}
    write(lib.SETTINGS, json.dumps(doc))
    lib.settings.cache_clear()
    return os.path.join(plugin, "bin")


def rows():
    try:
        got = cli.context_base_row()
        return got if isinstance(got, list) else [got]
    except BaseException as e:  # a crash is a red check, not a traceback
        return [lib.Result("CRASH", "context base", "%s: %s" % (type(e).__name__, e))]
    finally:
        os.environ["PATH"] = REAL_PATH
        lib.ROOT, lib.PROFILES = REAL_ROOT, REAL_PROFILES
        lib.settings.cache_clear()


def calls(fakedir):
    log = os.path.join(fakedir, "calls.log")
    return [json.loads(l) for l in open(log)] if os.path.exists(log) else []


def one(label, got, level):
    """The single result of a case, which must have `level`."""
    check("%s: one result" % label, len(got) == 1, got)
    r = got[0] if got else lib.Result("NONE", "", "")
    check("%s: %s, want %s" % (label, r.level, level), r.level == level, r)
    return r


# ---- registered, and never a PASS over nothing
check("the row is registered", any(c[0] == "context base" and c[1] is getattr(cli, "context_base_row", 0) for c in cli.CHECKS),
      [c[0] for c in cli.CHECKS])
d = world(commands=(), profiles={"plain": {}})
r = one("no hook entry, no framework profile", rows(), "SKIP")
check("no target: says NOT RUN, NOT ARMED", r.detail.startswith(cli.NOT_ARMED), r)
check("no target: fwx was not run", calls(d) == [], calls(d))
d = world(fwx=False)
r = one("no bin/fwx", rows(), "SKIP")
check("no fwx: says NOT RUN, NOT ARMED and names bin/fwx", r.detail.startswith(cli.NOT_ARMED) and "bin/fwx" in r.detail, r)
d = world(section=False)
r = one("no framework.plugin_source", rows(), "SKIP")
check("no plugin_source: says NOT RUN, NOT ARMED", r.detail.startswith(cli.NOT_ARMED), r)

# ---- a hook entry: what fwx is asked, and each exit code
d = world(plan=[{"match": "check", "rc": 0, "out": "checked 1 file, 5 units, sources current\n"},
                {"match": "audit", "rc": 0, "out": "audited 3 subagent(s) in 1 session(s): 3 ok, 0 stale, 0 not armed\n"}])
r = one("both exit 0", rows(), "PASS")
check("PASS carries both last lines", "sources current" in r.detail and "audited 3 subagent(s)" in r.detail, r)
asked = calls(d)
check("check gets the file, the source and the hook's whole command",
      ["context-base", "check", "--file", FILE, "--source", SOURCE, "--hook-command", CMD] in asked, asked)
check("audit gets forge, the last 3 sessions and the file",
      len(asked) == 2 and asked[1][:3] == ["context-base", "audit", "--project"] and asked[1][4:] == ["--last", "3", "--file", FILE], asked)
check("audit's project is forge's own root (the toy one)", len(asked) == 2 and asked[1][3].endswith("/forge") and "/case-" in asked[1][3], asked)

world(plan=[{"match": "check", "rc": 1, "out": "checked 1 file, 5 units, 1 problem(s)\n", "err": "context-base: stale: the source moved on\n"}])
r = one("exit 1 of a hook check is a FAIL", rows(), "FAIL")
check("FAIL names the target", "context-base.md" in r.detail, r)
check("FAIL quotes what fwx said", "stale: the source moved on" in r.detail and "1 problem(s)" in r.detail, r)
check("FAIL names the command that reproduces it",
      "python3 " in r.detail and "/bin/fwx context-base check --file %s" % FILE in r.detail and shlex.quote(CMD) in r.detail, r)

world(plan=[{"match": "context-base", "rc": 1, "out": "FAIL a1 general-purpose: missing\n"}])
one("FAIL swallowed as SKIP: every step of the target exits 1", rows(), "FAIL")

world(plan=[{"match": "check", "rc": 2, "err": "fwx context-base: bad usage\n"}])
r = one("exit 2 (usage) is a FAIL, not swallowed", rows(), "FAIL")
check("exit 2: says what fwx said and the exit code", "bad usage" in r.detail and "exit 2" in r.detail, r)

world(plan=[{"match": "audit", "rc": 1, "out": "FAIL a1b2c3 general-purpose: missing\nFAIL d4e5f6 Plan: wrong\n"
             "audited 2 subagent(s) in 3 session(s): 0 ok, 0 stale, 0 not armed\n"}])
r = one("exit 1 of the audit is a FAIL", rows(), "FAIL")
check("the audit's FAIL names each agent and its type",
      all(w in r.detail for w in ("a1b2c3", "general-purpose", "missing", "d4e5f6", "Plan", "wrong")), r)
check("the audit's FAIL names the reproducing command", "/bin/fwx context-base audit --project" in r.detail and "--last 3" in r.detail, r)

world(plan=[{"match": "check", "rc": 77, "out": "NOT RUN, NOT ARMED: no open phase\n"}, {"match": "audit", "rc": 77, "out": "NOT RUN, NOT ARMED: no subagent transcript\n"}])
r = one("both exit 77", rows(), "SKIP")
check("77: the SKIP starts NOT RUN, NOT ARMED and carries fwx's line", r.detail.startswith(cli.NOT_ARMED) and "no open phase" in r.detail, r)

world(plan=[{"match": "audit", "rc": 77, "out": "audit: no subagent transcript found\n"}, {"match": "check", "rc": 0, "out": "checked 1 file, 5 units, sources current\n"}])
r = one("check 0, audit 77", rows(), "PASS")
check("the PASS says the audit did not run", "sources current" in r.detail and "NOT RUN, NOT ARMED" in r.detail and "no subagent transcript" in r.detail, r)

world(plan=[{"match": "check", "rc": 0, "out": "ok\n"}, {"match": "audit", "rc": 1, "out": "FAIL zz9 Explore: double\n"}])
r = one("check 0, audit 1: the failure is not hidden by the pass", rows(), "FAIL")

# ---- a command without --file cannot be checked; two entries are two results
world(commands=("python3 /toy/forge/plugins/fwx/hooks/subagent_context.py",))
r = one("an entry without --file", rows(), "FAIL")
check("it says --file is missing", "--file" in r.detail, r)
d = world(commands=(CMD, CMD.replace("context-base.md", "other.md")))
got = rows()
check("two entries, two results", [x.level for x in got] == ["PASS", "PASS"], got)
check("each result names its own file", "context-base.md" in got[0].detail and "other.md" in got[1].detail, got)

# ---- profiles
d = world(commands=(), profiles={"app": {"framework": True}, "off": {"framework": False}, "plain": {}},
          plan=[{"match": "audit", "rc": 0, "out": "audited 1 subagent(s) in 1 session(s): 1 ok, 0 stale, 0 not armed\n"},
                {"match": "check", "rc": 0, "out": "checked 1 file, 4 units, sources current\n"}])
r = one("one framework profile", rows(), "PASS")
check("the profile is named", "app" in r.detail, r)
asked = calls(d)
check("check --project P, then audit --project P --last 3, on the project's path (and only that profile)",
      len(asked) == 2 and asked[0][:2] == ["context-base", "check"] and asked[0][2] == "--project" and asked[0][3].endswith("/app") and
      asked[1][:2] == ["context-base", "audit"] and asked[1][2:3] == ["--project"] and asked[1][3] == asked[0][3] and
      asked[1][4:] == ["--last", "3"], asked)
world(commands=(), profiles={"app": {"framework": True}}, plan=[{"match": "audit", "rc": 1, "out": "FAIL q1 general-purpose: missing\n"}])
r = one("a framework profile whose audit fails", rows(), "FAIL")
check("it names the profile, the agent and its type", all(w in r.detail for w in ("app", "q1", "general-purpose")), r)
d = world(profiles={"app": {"framework": True}})
check("a hook entry and a profile: two results, entry first", [("hook" in x.detail, "app" in x.detail) for x in rows()] == [(True, False), (False, True)],
      rows())

# ---- fwx that never returns
saved = getattr(cli, "CONTEXT_BASE_TIMEOUT", None)
cli.CONTEXT_BASE_TIMEOUT = 1
world(plan=[{"match": "check", "rc": 0, "sleep": 30}])
r = one("fwx that does not answer", rows(), "FAIL")
check("the timeout is named", "1 s" in r.detail, r)
cli.CONTEXT_BASE_TIMEOUT = saved
check("the default timeout is 120 s", saved == 120, saved)

print("%d cases, %d failure(s)" % (n_cases[0], len(failures)))
for f in failures:
    print("FAIL", f)
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
