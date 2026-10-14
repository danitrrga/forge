#!/usr/bin/env python3
"""Each project uses one memory system, so Hindsight's Claude Code hooks are written only where a
project uses Hindsight. A profile uses it when its `servers` list holds `hindsight-coding-agents`
(derived, no profile field). With the `hindsight` integration on, the two rows (UserPromptSubmit
claude-hook.js, Stop claude-stop-hook.js) and every config/forge.json `user_hooks` row with
`"scope": "hindsight"` land in that project's .claude/settings.local.json, through
skills.write_settings_local, and never at user scope: the exact-command reconcile takes forge's old
entries out of ~/.claude/settings.json and leaves a foreign hook. A project that does not use
Hindsight, or every project while the integration is off, loses the entries a run wrote before. The
Codex rows stay at user scope: Codex has no per-project hooks file forge writes.

Runs in-process against a toy forge.json (lib.SETTINGS), a toy HOME and toy projects; nothing real
is written.

Seen failing on d2e7df0 (the rows at user scope), 19 of 27 checks red; the 8 that passed are controls
true before as after (the non-Hindsight profile, the foreign hook, the Codex rows, no scope = user row,
and the integration-off and "on": false cases, where the old code wrote nothing either):
  on: a Hindsight profile's settings.local.json gains the two rows, the line says so, a second run is
    already current, a profile that declares nothing else is still written, and off: the line counts
    what it took out -- each ('raised', 'TypeError', 'write_settings_local() takes from 2 to 4 positional
    arguments but 5 were given')
  on: USER_HOOKS holds no Claude coding-agents row -- markers [('UserPromptSubmit', 'claude'), ('Stop', 'claude')]
  on: ~/.claude/settings.json loses forge's two rows -- claude-hook.js still in UserPromptSubmit
  on: the note says the rows are written per project -- notes ['appended SessionStart caveman_house_rules.py', ...]
  on: the doctor's would-write matches the file after the run -- would write {'permissions': {'allow': ['Bash(ls)']}}
  on: the doctor's would-write for a Hindsight project not yet written holds the two rows -- would write None
  a profile `hooks` entry with the same command is never taken out -- Stop []
  off: nobody gets them, the seeded rows go / a profile that declared only the server loses them too /
    server dropped: the rows a run wrote before go -- the seeded file kept both rows
  scope hindsight: the user_hooks row is not a user-scope row -- it was the last USER_HOOKS row
  scope hindsight: lands only in the Hindsight profile -- hs [], plain []
  scope hindsight: its old user-scope entry goes -- the entry stayed
  scope "elsewhere" / scope hindsight with codex in agents: refused -- reload gave <module 'forge.hooks' ...>
Negative controls on the finished code, each put back from a copy of the file:
  `wanted` forced False in write_settings_local -- 4 red (gains the two rows, the line, declares
    nothing else, scope hindsight lands only in the Hindsight profile)
  project rows not added to OFF_HOOKS -- 4 red (user scope loses the two rows, the note, off: user
    scope, the scoped row's old user-scope entry)
  early return blind to an owned command -- 1 red: a profile that declared only the server loses them too
  a wanted row not counted as declared -- 1 red: a profile that declares nothing else is still written
  cli.settings_forge_would_write passing no rows -- 1 red: would write None for a project not yet written
  scope not validated -- 1 red: ValueError "unknown integration 'elsewhere'" instead of a "!" line
  codex allowed on a scoped row -- 1 red; scope ignored -- 3 red (the three scope hindsight checks).
Two cases from a Codex review, seen failing on the code before their fix (the other 28 passed):
  scope not a string: refused with a "!" line -- reload gave ('raised', 'TypeError', "cannot use 'list'
    as a dict key (unhashable type: 'list')")
  doctor: a scoped row with its integration off is a SKIP -- rows [Result(level='FAIL', ..., detail='user_hooks
    row toy_injection_audit.py (SessionStart): ... does not exist, so the hook cannot start ...')]
  (its control, the same row with the integration on, is a FAIL before and after)."""
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

REPO = sandbox.FORGE
TOY = sandbox.mkdtemp("hindsight-project-hooks-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.path.insert(0, REPO)
from forge import lib  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
INTEGRATIONS = {"codex": True, "gsd": True, "jev": False, "hindsight": True, "caveman": True}
lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": INTEGRATIONS}, fh)
from forge import cli, hooks, skills  # noqa: E402

APPLY = lib.Ctx(True, None, False)
SERVER = "hindsight-coding-agents"
failures, n_cases = [], [0]


def check(label, ok, detail=""):
    n_cases[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))


def attempt(fn, *a, **k):
    try:
        return fn(*a, **k)
    except SystemExit as e:
        return ("exit", str(e))
    except Exception as e:  # a missing feature is a red check, not a traceback
        return ("raised", type(e).__name__, str(e))


def toy_settings(n, **over):
    doc = {"integrations": dict(INTEGRATIONS), "gsd_patches": True, "house_hooks": True, "user_settings": {},
           "user_hooks": []}
    doc.update(over)
    path = os.path.join(TOY, "forge-%d.json" % n)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()
    return attempt(importlib.reload, hooks)


def project(name, servers, **extra):
    p = os.path.join(TOY, "projects", name)
    os.makedirs(os.path.join(p, ".claude"), exist_ok=True)
    return dict({"project": name, "project_path": p, "servers": servers}, **extra)


def slp(prof):
    return os.path.join(prof["project_path"], ".claude", "settings.local.json")


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def write(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def entries(doc, event):
    return [(h.get("command"), g.get("matcher"), h.get("timeout")) for g in ((doc or {}).get("hooks") or {}).get(event, [])
            for h in g.get("hooks", [])]


def all_commands(doc):
    return {c for ev in ((doc or {}).get("hooks") or {}) for c, _, _ in entries(doc, ev)}


def run(prof):
    """write_settings_local with the rows forge/sync.py hands it."""
    rows = attempt(hooks.project_hooks, prof) if hasattr(hooks, "project_hooks") else ()
    if isinstance(rows, tuple) and rows and rows[0] in ("raised", "exit"):
        return rows
    return attempt(skills.write_settings_local, APPLY, prof, None, None, rows)


def group(cmd, timeout):
    return {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}


UP = 'node "%s/claude-hook.js"' % os.path.join(HOME, ".hindsight", "coding-agents", "dist")
STOP = 'node "%s/claude-stop-hook.js"' % os.path.join(HOME, ".hindsight", "coding-agents", "dist")
CODEX_UP = 'node "%s/codex-hook.js"' % os.path.join(HOME, ".hindsight", "coding-agents", "dist")
FOREIGN = "node /opt/herdr/notify.js"
AUDIT = {"event": "SessionStart", "command": "python3 <ROOT>/scripts/toy_injection_audit.py", "timeout": 10,
         "marker": "toy_injection_audit.py", "matcher": None, "agents": ["claude"]}
AUDIT_CMD = AUDIT["command"].replace("<ROOT>", lib.ROOT)

# 1. Integration on. A Hindsight profile's file gains the two rows, a second run leaves it as it is,
# a profile without the server gets none, and one that declares nothing else is still written.
toy_settings(1)
hs = project("hs", [SERVER, "other"], permissions={"allow": ["Bash(ls)"]})
bare = project("bare", [SERVER])
plain = project("plain", ["other"], permissions={"allow": ["Bash(ls)"]})
line = run(hs)
doc = read(slp(hs))
check("on: a Hindsight profile's settings.local.json gains the two rows",
      entries(doc, "UserPromptSubmit") == [(UP, None, 30)] and entries(doc, "Stop") == [(STOP, None, 60)],
      "UserPromptSubmit %r, Stop %r; line %r" % (entries(doc, "UserPromptSubmit"), entries(doc, "Stop"), line))
check("on: the Hindsight project's line says so",
      isinstance(line, str) and "coding-agents UserPromptSubmit on" in line and "coding-agents Stop on" in line, "line %r" % (line,))
before = open(slp(hs), "rb").read() if os.path.exists(slp(hs)) else b""
again = run(hs)
check("on: a second run is already current",
      isinstance(again, str) and "already current" in again and open(slp(hs), "rb").read() == before, "line %r" % (again,))
line = run(bare)
check("on: a Hindsight profile that declares nothing else is still written",
      entries(read(slp(bare)), "Stop") == [(STOP, None, 60)], "line %r, file %r" % (line, read(slp(bare))))
line = run(plain)
check("on: a profile without the server gets none (control)",
      not ({UP, STOP} & all_commands(read(slp(plain)))), "file %r" % (read(slp(plain)),))
claude_rows = [(r[0], "claude") for r in hooks.USER_HOOKS if r[3] == "coding-agents" and hooks.CLAUDE in r[5]]
check("on: USER_HOOKS holds no Claude coding-agents row", not claude_rows, "markers %r" % (claude_rows,))
check("on: the Codex coding-agents rows stay at user scope (control)",
      [r[0] for r in hooks.USER_HOOKS if r[3] == "coding-agents" and hooks.CODEX in r[5]] == ["UserPromptSubmit", "Stop"],
      "rows %r" % ([r for r in hooks.USER_HOOKS if r[3] == "coding-agents"],))
user = {"hooks": {"UserPromptSubmit": [group(UP, 30), group(FOREIGN, 5)], "Stop": [group(STOP, 60)]}}
notes = attempt(hooks.reconcile, user, hooks.CLAUDE)
check("on: ~/.claude/settings.json loses forge's two rows",
      not ({UP, STOP} & all_commands(user)), "UserPromptSubmit %r, Stop %r, notes %r"
      % (entries(user, "UserPromptSubmit"), entries(user, "Stop"), notes))
check("on: a foreign hook in ~/.claude/settings.json stays (control)", (FOREIGN, None, 5) in entries(user, "UserPromptSubmit"),
      "UserPromptSubmit %r" % (entries(user, "UserPromptSubmit"),))
check("on: the note says the rows are written per project",
      isinstance(notes, list) and any("per project" in n for n in notes), "notes %r" % (notes,))
cdoc = {}
attempt(hooks.reconcile, cdoc, hooks.CODEX)
check("on: ~/.codex/hooks.json still gets the codex row (control)", (CODEX_UP, None, 30) in entries(cdoc, "UserPromptSubmit"),
      "%r" % (entries(cdoc, "UserPromptSubmit"),))
# The doctor's drift row computes what the generator would write with the same rows.
want = attempt(cli.settings_forge_would_write, "hs", hs, {})
check("on: the doctor's would-write matches the file after the run (None: nothing to write)", want is None, "would write %r" % (want,))
unwritten = project("unwritten", [SERVER])
want = attempt(cli.settings_forge_would_write, "unwritten", unwritten, {})
check("on: the doctor's would-write for a Hindsight project not yet written holds the two rows",
      isinstance(want, dict) and entries(want, "UserPromptSubmit") == [(UP, None, 30)] and entries(want, "Stop") == [(STOP, None, 60)]
      and not os.path.exists(slp(unwritten)), "would write %r" % (want,))

# 2. A profile's own `hooks` that names the same command keeps it, whatever the integration says.
declared = project("declared", ["other"], hooks={"Stop": [group(STOP, 60)]})
run(declared)
toy_settings(2, integrations=dict(INTEGRATIONS, hindsight=False))
run(declared)
check("a profile `hooks` entry with the same command is never taken out",
      entries(read(slp(declared)), "Stop") == [(STOP, None, 60)], "Stop %r" % (entries(read(slp(declared)), "Stop"),))

# 3. Integration off: nobody gets them, the entries an earlier run wrote go (seeded here as that run
# leaves them), and user scope loses them too.
SEEDED = {"permissions": {"allow": ["Bash(ls)"]},
          "hooks": {"UserPromptSubmit": [group(UP, 30)], "Stop": [group(STOP, 60)]}}
write(slp(hs), SEEDED)
write(slp(bare), {"hooks": SEEDED["hooks"]})
line = run(hs)
doc = read(slp(hs))
check("off: nobody gets them, the seeded rows go",
      not ({UP, STOP} & all_commands(doc)) and (doc or {}).get("permissions"), "file %r, line %r" % (doc, line))
check("off: the line counts what it took out", isinstance(line, str) and line.count("coding-agents entries removed 1") == 2, "line %r" % (line,))
line = run(bare)
check("off: a profile that declared only the server loses them too", not ({UP, STOP} & all_commands(read(slp(bare)))),
      "file %r, line %r" % (read(slp(bare)), line))
user = {"hooks": {"UserPromptSubmit": [group(UP, 30), group(FOREIGN, 5)], "Stop": [group(STOP, 60)]}}
attempt(hooks.reconcile, user, hooks.CLAUDE)
check("off: user scope loses them too, the foreign hook stays",
      not ({UP, STOP} & all_commands(user)) and FOREIGN in all_commands(user), "%r" % (user,))

# 4. On again, then the profile drops the server: what the earlier run wrote goes.
toy_settings(3)
write(slp(hs), SEEDED)
dropped = dict(hs, servers=["other"])
line = run(dropped)
check("server dropped: the rows a run wrote before go", not ({UP, STOP} & all_commands(read(slp(hs)))),
      "file %r, line %r" % (read(slp(hs)), line))

# 5. A user_hooks row with "scope": "hindsight" is written per project, to Hindsight profiles only.
toy_settings(4, user_hooks=[AUDIT])
check("no scope: the user_hooks row is a user-scope row (control)", AUDIT_CMD in [r[1] for r in hooks.USER_HOOKS],
      "USER_HOOKS commands %r" % ([r[1] for r in hooks.USER_HOOKS][-3:],))
toy_settings(5, user_hooks=[dict(AUDIT, scope="hindsight")])
check("scope hindsight: the user_hooks row is not a user-scope row", AUDIT_CMD not in [r[1] for r in hooks.USER_HOOKS],
      "USER_HOOKS commands %r" % ([r[1] for r in hooks.USER_HOOKS][-3:],))
run(hs)
run(plain)
check("scope hindsight: lands only in the Hindsight profile",
      entries(read(slp(hs)), "SessionStart") == [(AUDIT_CMD, None, 10)] and AUDIT_CMD not in all_commands(read(slp(plain))),
      "hs %r, plain %r" % (entries(read(slp(hs)), "SessionStart"), entries(read(slp(plain)), "SessionStart")))
user = {"hooks": {"SessionStart": [group(AUDIT_CMD, 10), group(FOREIGN, 5)]}}
attempt(hooks.reconcile, user, hooks.CLAUDE)
check("scope hindsight: its old user-scope entry goes, the foreign one stays",
      AUDIT_CMD not in all_commands(user) and FOREIGN in all_commands(user), "SessionStart %r" % (entries(user, "SessionStart"),))
got = toy_settings(6, user_hooks=[dict(AUDIT, scope="elsewhere")])
check("scope \"elsewhere\": refused with a \"!\" line",
      isinstance(got, tuple) and got[0] == "exit" and "scope" in got[1] and got[1].startswith("!"), "reload gave %r" % (got,))
got = toy_settings(7, user_hooks=[dict(AUDIT, scope="hindsight", agents=["claude", "codex"])])
check("scope hindsight with codex in agents: refused with a \"!\" line",
      isinstance(got, tuple) and got[0] == "exit" and "codex" in got[1], "reload gave %r" % (got,))
got = toy_settings(10, user_hooks=[dict(AUDIT, scope=[])])
check("scope not a string: refused with a \"!\" line, not a traceback",
      isinstance(got, tuple) and got[0] == "exit" and "scope" in got[1], "reload gave %r" % (got,))
# The doctor's integrations row reads the same rows: a scoped row whose integration is off is not armed,
# so its missing script is a SKIP, as an "on": false row's is; with the integration on, a FAIL (control).
toy_settings(11, user_hooks=[dict(AUDIT, scope="hindsight")], integrations=dict(INTEGRATIONS, hindsight=False))
rows = [r for r in (attempt(cli.integrations_row) or []) if "toy_injection_audit.py" in getattr(r, "detail", str(r))]
check("doctor: a scoped row with its integration off is a SKIP, not a FAIL",
      rows and all(r.level == "SKIP" for r in rows), "rows %r" % (rows,))
toy_settings(12, user_hooks=[dict(AUDIT, scope="hindsight")])
rows = [r for r in (attempt(cli.integrations_row) or []) if "toy_injection_audit.py" in getattr(r, "detail", str(r))]
check("doctor: a scoped row with its integration on and its script missing is a FAIL (control)",
      rows and all(r.level == "FAIL" for r in rows), "rows %r" % (rows,))
toy_settings(8, user_hooks=[dict(AUDIT, scope="hindsight")], integrations=dict(INTEGRATIONS, hindsight=False))
run(hs)
check("scope hindsight off: no project gets it, the earlier entry goes", AUDIT_CMD not in all_commands(read(slp(hs))),
      "SessionStart %r" % (entries(read(slp(hs)), "SessionStart"),))
toy_settings(9, user_hooks=[dict(AUDIT, scope="hindsight", on=False)])
run(hs)
check("scope hindsight \"on\": false: no project gets it", AUDIT_CMD not in all_commands(read(slp(hs))),
      "SessionStart %r" % (entries(read(slp(hs)), "SessionStart"),))

sandbox.cleanup(bool(failures))
if failures:
    print("%d of %d checks failed" % (len(failures), n_cases[0]))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % n_cases[0])
