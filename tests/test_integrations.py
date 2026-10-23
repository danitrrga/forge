#!/usr/bin/env python3
"""T4 of docs/portable-design.md: forge/hooks.py reads config/forge.json. An integration that is off
drops forge's own entries from the user-scope files (by exact command, never by marker), `user_hooks`
rows come from the file and follow the code's rows, `user_settings` come from the file, and the codex
writer says NOT RUN, NOT ARMED.

Everything runs against a toy forge.json (lib.SETTINGS) and a toy HOME; nothing real is written.

Seen failing on 947b2e4 (hooks.py with every row in code; the file run in a copy of that tree), 17 of
20 checks red, the other 3 are controls that pass there:
  off integrations: the exact commands go -- the hindsight entries were all still in
    UserPromptSubmit, and the gsd ones in Stop and PostToolUse
  off integrations: a foreign `coding-agents` entry stays -- it was gone (the old reconcile drops every
    entry carrying the marker that is not the row's exact command)
  off integrations: no row of an off integration is written -- USER_HOOKS still holds the markers
    ['coding-agents', 'gsd-prompt-guard.js', ...]
  integrations on: ROW_INTEGRATION names the owner of each gated marker -- ROW_INTEGRATION = None
  user_hooks: the row is appended after the code's rows -- the last row was the codex Stop row of
    `coding-agents`; written for the agents it names only, and "on": false, were red the same way
  no user_hooks: the code holds none of the rows that moved out -- rows
    ['<moved row>.py', ...]
  this machine's forge.json: 15 rows, the two after the code's (the Hindsight rows are written per project)
  user_settings: model and env come from the file -- wrote model 'sonnet' advisorModel 'opus' env
    {'MEM_NO_AUTO_ADOPT': '1', ...}, want haiku, no advisorModel and {'TOY_FLAG': '1'}
  codex off: the writer says NOT RUN, NOT ARMED -- the line was "~/.codex/hooks.json -> appended
    UserPromptSubmit <moved row>.py; ..." and the file was written
Negative controls on the finished code, each put back from a copy of the file (the checks that went red):
  off rows matched by marker, not exact command -- the foreign `coding-agents` entry stays (1)
  integration gate ignored (every row live) -- 5: exact commands go, foreign stays, no row written, codex
    rows go, ...rows are in the table
  codex gate removed -- codex off: the writer says NOT RUN (1)
  user_settings hard-coded again -- user_settings: model and env come from the file (1)
  user_hooks put before the code's rows -- "on": false and the 17-rows check (2)
Stranger's table (section 10), seen failing on 8c4a9c3 before the gates, 11 of 30 red (the full-config check is the control and passed):
  stranger: none of the six rows is written -- USER_HOOKS holds ['gsd-prompt-guard.js',
    'gsd-read-injection-scanner.js', 'gsd_output_discipline.py', 'memory_doctor.py', 'omarchy_notify.py',
    'ref_corpus_router.py']
  stranger: GSD's own entries stay -- PreToolUse [('node <forge>/hooks/gsd-prompt-guard.js', 'Write|Edit', 10)]: replaced
  stranger: forge's own old copy goes by its exact command, GSD's entry stays -- GSD's entry gone
  gsd_patches true / house_hooks absent, house_hooks true / gsd_patches false, house_hooks "yes", hindsight off:
    each still held all of the markers above
Not written here, run by `forge test`'s other suites: the byte-identity of the real files (gate.py)."""
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

REPO = sandbox.FORGE
TOY = sandbox.mkdtemp("integrations-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.path.insert(0, REPO)
from forge import lib  # noqa: E402
# hooks reads the settings file when it is imported, and this checkout's config/forge.json is
# private data a stranger's copy lacks (red there before, M1: "! config/forge.json missing -- run
# bin/forge init" at the import).
lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {"codex": True, "gsd": True, "hindsight": True}}, fh)
from forge import hooks  # noqa: E402

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
    """Write toy config/forge.json number n, point lib at it and reload hooks over it."""
    doc = {"integrations": {"codex": True, "gsd": True, "hindsight": True},
           "gsd_patches": True, "house_hooks": True, "user_settings": {}, "user_hooks": []}
    doc.update(over)
    doc = {k: v for k, v in doc.items() if v is not None}  # an override of None drops the key
    path = os.path.join(TOY, "forge-%d.json" % n)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()
    importlib.reload(hooks)
    hooks.USER_SETTINGS = os.path.join(HOME, ".claude", "settings.json")
    hooks.CODEX_HOOKS = os.path.join(HOME, ".codex", "hooks.json")
    return hooks


def entries(doc, event):
    return [(h.get("command"), g.get("matcher"), h.get("timeout")) for g in doc.get("hooks", {}).get(event, [])
            for h in g.get("hooks", [])]


def group(cmd, timeout=None, matcher=None):
    h = {"type": "command", "command": cmd}
    if timeout is not None:
        h["timeout"] = timeout
    return dict({"matcher": matcher} if matcher else {}, hooks=[h])


def commands(rows):
    return [r[1] for r in rows]


# 1. Off integrations. Entries holding forge's exact command go, whatever their matcher or timeout;
# a foreign entry under the same marker stays; the rows of an integration that is off are not written.
h = toy_settings(1, integrations={"codex": True, "gsd": False, "hindsight": False})
hs_up = 'node "%s/claude-hook.js"' % h.HINDSIGHT_DIST
hs_stop = 'node "%s/claude-stop-hook.js"' % h.HINDSIGHT_DIST
foreign = 'node /somewhere/else/.hindsight/coding-agents/dist/claude-hook.js'
gsd_cmd = "python3 %s/gsd_output_discipline.py" % h.HOOK_DIR
doc = {"hooks": {"UserPromptSubmit": [group(hs_up, 99, "Odd"), group(foreign, 30)],
                 "Stop": [group(hs_stop, 60), group(gsd_cmd, 10)],
                 "PostToolUse": [group(gsd_cmd, 10, "Write|Edit")]}}
notes = attempt(h.reconcile, doc, h.CLAUDE)
ups, stops, posts = (entries(doc, e) for e in ("UserPromptSubmit", "Stop", "PostToolUse"))
check("off integrations: the exact commands go, whatever the matcher and timeout",
      not any(c == hs_up for c, _, _ in ups) and not any(c in (hs_stop, gsd_cmd) for c, _, _ in stops)
      and not any(c == gsd_cmd for c, _, _ in posts),
      "UserPromptSubmit %r, Stop %r, PostToolUse %r, notes %r" % (ups, stops, posts, notes))
check("off integrations: a foreign `coding-agents` entry stays (nothing removes by marker)",
      (foreign, None, 30) in ups, "UserPromptSubmit %r" % (ups,))
# gsd-core's own hooks (forge/hooks.py GSD_CORE_ROWS): wired from ~/.claude/hooks, with gsd on and gsd_patches true
CORE_MARKERS = ["gsd-session-state.sh", "gsd-context-monitor.js", "gsd-graphify-update.sh", "gsd-phase-boundary.sh",
                "gsd-workflow-guard.js", "gsd-worktree-path-guard.js", "gsd-agent-isolation-guard.js",
                "gsd-write-guard.js", "gsd-validate-commit.sh", "gsd-config-reload.js"]
off_markers = {"claude-hook.js", "coding-agents", "gsd_output_discipline.py", "gsd-prompt-guard.js",
               "gsd-read-injection-scanner.js"} | set(CORE_MARKERS)
written = sorted({r[3] for r in h.USER_HOOKS} & off_markers)
check("off integrations: no row of an off integration is written", not written,
      "USER_HOOKS still holds the markers %r" % (written,))
check("off integrations: forge's other rows still are (omarchy, session sync), the memory gate follows hindsight",
      {"omarchy_notify.py", "forge session-start"} <= {r[3] for r in h.USER_HOOKS}
      and "memory_doctor.py" not in {r[3] for r in h.USER_HOOKS},
      "markers %r" % sorted(r[3] for r in h.USER_HOOKS))
# the codex rows go from codex's file whether or not their integration is on (it is off here)
cdoc = {"hooks": {"UserPromptSubmit": [group('node "%s/codex-hook.js"' % h.HINDSIGHT_DIST, 30)]}}
attempt(h.drop_codex_entries, cdoc)
check("off integrations: the codex rows go from codex's file too",
      not entries(cdoc, "UserPromptSubmit") or all("codex-hook.js" not in c for c, _, _ in entries(cdoc, "UserPromptSubmit")),
      "%r" % (entries(cdoc, "UserPromptSubmit"),))

# 2. The same file with the integrations on writes those rows, from the code, after the table's start.
h = toy_settings(2)
markers = [r[3] for r in h.USER_HOOKS]
check("integrations on: gsd and hindsight rows are in the table",
      {"gsd-prompt-guard.js", "gsd_output_discipline.py", "coding-agents"} <= set(markers),
      "markers %r" % (markers,))
check("integrations on: ROW_INTEGRATION names the owner of each gated marker",
      getattr(h, "ROW_INTEGRATION", {}) == {"gsd-prompt-guard.js": "gsd", "gsd-read-injection-scanner.js": "gsd",
                                           "gsd_output_discipline.py": "gsd",
                                           "coding-agents": "hindsight", "memory_doctor.py": "hindsight",
                                           **{m: "gsd" for m in CORE_MARKERS}},
      "ROW_INTEGRATION = %r" % (getattr(h, "ROW_INTEGRATION", None),))

# 3. Rows that are not forge's come from `user_hooks`, appended after the code's, <ROOT> expanded.
row = {"event": "UserPromptSubmit", "command": "python3 <ROOT>/toy/curfew.py", "timeout": 7, "marker": "curfew.py",
       "matcher": "Bash", "agents": ["claude"]}
h = toy_settings(3, user_hooks=[row])
last = h.USER_HOOKS[-1] if h.USER_HOOKS else None
check("user_hooks: the row is appended after the code's rows, <ROOT> expanded",
      last == ("UserPromptSubmit", "python3 %s/toy/curfew.py" % h.ROOT, 7, "curfew.py", "Bash", ("claude",)),
      "last row %r of %d" % (last, len(h.USER_HOOKS)))
doc = {}
attempt(h.reconcile, doc, h.CLAUDE)
check("user_hooks: written for Claude, and not a command forge takes out of Codex's file",
      ("python3 %s/toy/curfew.py" % h.ROOT, "Bash", 7) in entries(doc, "UserPromptSubmit")
      and "python3 %s/toy/curfew.py" % h.ROOT not in h.codex_commands(),
      "claude %r, codex commands %r" % (entries(doc, "UserPromptSubmit"), sorted(h.codex_commands())))
h = toy_settings(4, user_hooks=[dict(row, on=False)])
doc = {"hooks": {"UserPromptSubmit": [group("python3 %s/toy/curfew.py" % h.ROOT, 99, "Other")]}}
attempt(h.reconcile, doc, h.CLAUDE)
check("user_hooks: \"on\": false drops its exact command and writes nothing",
      not any("curfew.py" in c for c, _, _ in entries(doc, "UserPromptSubmit")) and not any("curfew.py" in r[1] for r in h.USER_HOOKS),
      "UserPromptSubmit %r" % (entries(doc, "UserPromptSubmit"),))

# 4. With no user_hooks the code holds none of the rows that moved out of it. Their markers are this
# checkout's own user_hooks (config/forge.json); a checkout that has none checks the toy row of case 3.
def moved_markers():
    try:
        with open(os.path.join(sandbox.FORGE, "config", "forge.json"), encoding="utf-8") as fh:
            return [r["marker"] for r in json.load(fh).get("user_hooks", [])] or [row["marker"]]
    except (OSError, ValueError, KeyError):
        return [row["marker"]]


MOVED = moved_markers()
h = toy_settings(5)
check("no user_hooks: the code holds none of the rows that moved out",
      not [r for r in h.USER_HOOKS if r[3] in MOVED],
      "rows %r" % ([r[3] for r in h.USER_HOOKS if r[3] in MOVED],))

# 5. Two user_hooks rows come after the code's rows, in file order. The code holds 25 rows with every
# integration on, so 14 with the two that moved out of the code (the curfew and the injection audit,
# here under toy names).
two = [{"event": "UserPromptSubmit", "command": "python3 /opt/toy/prompt_guard.py", "timeout": 10,
        "marker": "prompt_guard.py", "matcher": None, "agents": ["claude", "codex"]},
       {"event": "SessionStart", "command": "python3 %s/scripts/toy_audit.py" % lib.ROOT, "timeout": 10,
        "marker": "toy_audit.py", "matcher": None, "agents": ["claude"]}]
code_rows = len(toy_settings(10).USER_HOOKS)
h = toy_settings(11, user_hooks=two)
real = [(r[0], r[3]) for r in h.USER_HOOKS]
check("a settings file with two user_hooks rows: the code's rows, then the two in file order",
      len(real) == code_rows + 2 and real[-2:] == [("UserPromptSubmit", "prompt_guard.py"), ("SessionStart", "toy_audit.py")]
      and not [m for _, m in real[:-2] if m in ("prompt_guard.py", "toy_audit.py")],
      "%d rows (code %d), last two %r" % (len(real), code_rows, real[-2:]))
h = toy_settings(12, user_hooks=two, integrations={n: True for n in lib.INTEGRATIONS})
real = [(r[0], r[3]) for r in h.USER_HOOKS]
check("all integrations on and two user_hooks rows: 25 rows (12 and gsd-core's 13; the two Hindsight rows are written per project), the two after the code's",
      len(real) == 25 and real[-2:] == [("UserPromptSubmit", "prompt_guard.py"), ("SessionStart", "toy_audit.py")],
      "%d rows, last two %r" % (len(real), real[-2:]))

# 6. user_settings come from the file: its keys and nothing else.
h = toy_settings(6, user_settings={"model": "haiku", "env": {"TOY_FLAG": "1"}})
ctx = lib.Ctx(True, None, True)
buf = attempt(h.write_user_settings, ctx)
with open(h.USER_SETTINGS, encoding="utf-8") as fh:
    written = json.load(fh)
check("user_settings: model and env come from the file, and no other key of the old code",
      written.get("model") == "haiku" and written.get("env") == {"TOY_FLAG": "1"} and "advisorModel" not in written,
      "wrote model %r advisorModel %r env %r; return %r" % (written.get("model"), written.get("advisorModel"),
                                                           written.get("env"), buf))
os.remove(h.USER_SETTINGS)

# 7. Codex off: the writer says so and writes no file.
h = toy_settings(7, integrations={"codex": False, "gsd": True, "hindsight": True})
line = attempt(h.write_codex_hooks, ctx)
check("codex off: the writer says NOT RUN, NOT ARMED and writes no file",
      isinstance(line, str) and "NOT RUN, NOT ARMED" in line and "codex" in line and not os.path.exists(h.CODEX_HOOKS),
      "line %r, hooks.json exists %s" % (line, os.path.exists(h.CODEX_HOOKS)))

# 7b. Codex gets no hooks from forge. With codex on the writer writes no row, takes out only the entries
# whose command is exactly one forge wrote (a user_hooks row that lists codex among its agents included),
# leaves every other entry, event and key as it was, and leaves a file that is absent absent. Red before
# (the writer mirrored the shared rows into the file): "codex on, no file: the writer writes none: line
# '... -> appended SessionStart <forge row>.py; ...', hooks.json exists True"; "every entry holding
# a command forge wrote is gone: left [... 'python3 .../<forge row>.py' ...]"; "a file with no
# entry of forge's is not rewritten" (the rows were appended to it).
cfg_row = {"event": "UserPromptSubmit", "command": "python3 <ROOT>/toy_codex_row.py", "timeout": 10,
           "marker": "toy_codex_row.py", "matcher": None, "agents": ["claude", "codex"]}
h = toy_settings(8, user_hooks=[cfg_row])
line = attempt(h.write_codex_hooks, ctx)
check("codex on, no file: the writer writes none and says nothing changed",
      isinstance(line, str) and "already current" in line and not os.path.exists(h.CODEX_HOOKS),
      "line %r, hooks.json exists %s" % (line, os.path.exists(h.CODEX_HOOKS)))
if os.path.exists(h.CODEX_HOOKS):
    os.remove(h.CODEX_HOOKS)
forge_cmds = {"PostToolUse": [("python3 %s/gsd_output_discipline.py" % h.HOOK_DIR, "Write|Edit", 10)],
              "UserPromptSubmit": [('node "%s/codex-hook.js"' % h.HINDSIGHT_DIST, None, 30),
                                   ("python3 %s/toy_codex_row.py" % h.ROOT, None, 10)],
              "PreToolUse": [("node %s/gsd-prompt-guard.js" % h.HOOK_DIR, "Write|Edit", 10)],
              "Stop": [('node "%s/codex-stop-hook.js"' % h.HINDSIGHT_DIST, None, 60)]}
foreign_cmds = {"UserPromptSubmit": [("node /opt/herdr/notify.js", None, 5), ("node /other/codex-hook.js", None, 30)],
                "Notification": [("python3 /x/omarchy_notify.py", None, 5)]}
doc = {"theme": "toy", "hooks": {}}
for src in (forge_cmds, foreign_cmds):
    for event, rows in src.items():
        doc["hooks"].setdefault(event, []).extend(group(c, t, m) for c, m, t in rows)
# the forge command again under another timeout and matcher: it goes too, whatever those say
doc["hooks"]["Stop"].append(group(forge_cmds["Stop"][0][0], 5, "Bash"))
os.makedirs(os.path.dirname(h.CODEX_HOOKS), exist_ok=True)
with open(h.CODEX_HOOKS, "w", encoding="utf-8") as fh:
    json.dump(doc, fh)
before = open(h.CODEX_HOOKS, "rb").read()
line = attempt(h.write_codex_hooks, lib.Ctx(False, None, True))
check("codex on, dry-run: the writer says what it would take out and writes nothing",
      isinstance(line, str) and "would write" in line and open(h.CODEX_HOOKS, "rb").read() == before, "line %r" % (line,))
line = attempt(h.write_codex_hooks, ctx)
with open(h.CODEX_HOOKS, encoding="utf-8") as fh:
    after = json.load(fh)
left = sorted(c for ev in after.get("hooks", {}) for c, _, _ in entries(after, ev))
check("codex on: every entry holding a command forge wrote is gone, and nothing else",
      left == ["node /opt/herdr/notify.js", "node /other/codex-hook.js", "python3 /x/omarchy_notify.py"],
      "left %r; line %r" % (left, line))
check("codex on: an event that held only forge's entries is gone, a foreign event and key stay",
      sorted(after.get("hooks", {})) == ["Notification", "UserPromptSubmit"] and after.get("theme") == "toy",
      "events %r, theme %r" % (sorted(after.get("hooks", {})), after.get("theme")))
check("codex on: the line says what was dropped", isinstance(line, str) and "dropped" in line, "line %r" % (line,))
before = open(h.CODEX_HOOKS, "rb").read()
line = attempt(h.write_codex_hooks, ctx)
check("codex on: a second run is already current and leaves the bytes",
      isinstance(line, str) and "already current" in line and open(h.CODEX_HOOKS, "rb").read() == before, "line %r" % (line,))
os.remove(h.CODEX_HOOKS)
if os.path.exists(h.CODEX_HOOKS + ".bak"):
    os.remove(h.CODEX_HOOKS + ".bak")
with open(h.CODEX_HOOKS, "w", encoding="utf-8") as fh:
    json.dump({"hooks": {"UserPromptSubmit": [group("node /opt/herdr/notify.js", 5)]}}, fh)
before = open(h.CODEX_HOOKS, "rb").read()
line = attempt(h.write_codex_hooks, ctx)
check("codex on: a file with no entry of forge's is not rewritten, and gets no .bak",
      open(h.CODEX_HOOKS, "rb").read() == before and not os.path.exists(h.CODEX_HOOKS + ".bak"), "line %r" % (line,))
os.remove(h.CODEX_HOOKS)

# 8. write_user_settings settles: the second run is already current, and its line carries no proxy fragment.
h = toy_settings(9)
dry = lib.Ctx(False, None, True)
attempt(h.write_user_settings, ctx)
line = attempt(h.write_user_settings, dry)
check("write_user_settings settles (the second run is already current, no proxy fragment)",
      isinstance(line, str) and "already current" in line and "direct to Anthropic" not in line and "proxy" not in line,
      "returned %r" % (line,))

# 10. A stranger's table. The gsd rows are forge's GSD patches: written only with gsd on AND gsd_patches
# true. ref_corpus_router.py and omarchy_notify.py are this machine's own: written only with house_hooks
# true (absent is false). memory_doctor.py --hook follows hindsight. A stranger's GSD entries under the
# same file names (GSD's own installer writes them into ~/.claude/settings.json, other commands) are
# never replaced and never removed.
GSD_ROWS = {"gsd-prompt-guard.js", "gsd-read-injection-scanner.js", "gsd_output_discipline.py"} | set(CORE_MARKERS)
HOUSE_ROWS = {"ref_corpus_router.py", "omarchy_notify.py"}
SIX = GSD_ROWS | HOUSE_ROWS | {"memory_doctor.py"}
stranger = {"codex": False, "gsd": True, "hindsight": False}
h = toy_settings(20, integrations=stranger, gsd_patches=False, house_hooks=None)
check("stranger (gsd on, gsd_patches false, no house_hooks, hindsight off): none of the six rows is written",
      not (SIX & {r[3] for r in h.USER_HOOKS}), "USER_HOOKS holds %r" % (sorted(SIX & {r[3] for r in h.USER_HOOKS}),))
own = "node /x/.claude/hooks/gsd-prompt-guard.js"
scan = "node /x/.claude/hooks/gsd-read-injection-scanner.js"
doc = {"hooks": {"PreToolUse": [group(own, 5, "Write|Edit")], "PostToolUse": [group(scan, 5, "Read")]}}
cdoc = {"hooks": {"PreToolUse": [group(own, 5, "Write|Edit")]}}
attempt(h.reconcile, doc, h.CLAUDE)
attempt(h.drop_codex_entries, cdoc)
check("stranger: GSD's own gsd-prompt-guard.js and scanner entries stay as they are",
      entries(doc, "PreToolUse") == [(own, "Write|Edit", 5)] and entries(doc, "PostToolUse") == [(scan, "Read", 5)],
      "PreToolUse %r, PostToolUse %r" % (entries(doc, "PreToolUse"), entries(doc, "PostToolUse")))
check("stranger: codex's file keeps the GSD entry too", entries(cdoc, "PreToolUse") == [(own, "Write|Edit", 5)],
      "%r" % (entries(cdoc, "PreToolUse"),))
check("stranger: no forge row of the six lands in the file",
      not [c for ev in doc["hooks"] for c, _, _ in entries(doc, ev) if h.HOOK_DIR in c or "memory_doctor" in c],
      "commands %r" % (sorted({c for ev in doc["hooks"] for c, _, _ in entries(doc, ev)}),))
# forge's own copy written by an earlier run (gsd_patches was true) goes by its exact command; GSD's stays.
fg = "node %s/gsd-prompt-guard.js" % h.HOOK_DIR
doc = {"hooks": {"PreToolUse": [group(fg, 10, "Write|Edit"), group(own, 5, "Write|Edit")]}}
attempt(h.reconcile, doc, h.CLAUDE)
check("stranger: forge's own old copy goes by its exact command, GSD's entry stays",
      entries(doc, "PreToolUse") == [(own, "Write|Edit", 5)], "PreToolUse %r" % (entries(doc, "PreToolUse"),))

h = toy_settings(21, gsd_patches=True, house_hooks=None)
m = {r[3] for r in h.USER_HOOKS}
check("gsd_patches true, house_hooks absent: the gsd rows are written, ref_corpus_router and omarchy are not",
      GSD_ROWS <= m and not (HOUSE_ROWS & m), "markers %r" % (sorted(m),))
h = toy_settings(22, gsd_patches=False)
m = {r[3] for r in h.USER_HOOKS}
check("house_hooks true, gsd_patches false: ref_corpus_router and omarchy are written, the gsd rows are not",
      HOUSE_ROWS <= m and not (GSD_ROWS & m), "markers %r" % (sorted(m),))
h = toy_settings(23, house_hooks="yes")
check("house_hooks: only the JSON true switches the house rows on",
      not (HOUSE_ROWS & {r[3] for r in h.USER_HOOKS}), "markers %r" % (sorted(r[3] for r in h.USER_HOOKS),))
h = toy_settings(24, integrations={"codex": True, "gsd": True, "hindsight": False})
check("hindsight off: memory_doctor.py --hook is not written", "memory_doctor.py" not in {r[3] for r in h.USER_HOOKS},
      "markers %r" % (sorted(r[3] for r in h.USER_HOOKS),))

# The full config (gsd_patches true, house_hooks true, hindsight on) writes the table that was written
# before the gates existed, in the same order.
h = toy_settings(25)
got = [(r[0], r[3], r[2], r[4], r[5], r[1].replace(h.ROOT, "<R>")) for r in h.USER_HOOKS]
BOTH_A = ("claude", "codex")
want = [
    ("UserPromptSubmit", "ref_corpus_router.py", 10, None, BOTH_A, "python3 <R>/hooks/ref_corpus_router.py"),
    ("PreToolUse", "gsd-prompt-guard.js", 10, "Write|Edit", BOTH_A, "node <R>/hooks/gsd-prompt-guard.js"),
    ("PostToolUse", "gsd-read-injection-scanner.js", 10, "Read", BOTH_A, "node <R>/hooks/gsd-read-injection-scanner.js"),
    ("PostToolUse", "gsd_output_discipline.py", 10, "Write|Edit", BOTH_A, "python3 <R>/hooks/gsd_output_discipline.py"),
    ("Stop", "gsd_output_discipline.py", 10, None, BOTH_A, "python3 <R>/hooks/gsd_output_discipline.py"),
    ("Notification", "omarchy_notify.py", 10, None, ("claude",), "python3 <R>/hooks/omarchy_notify.py"),
    ("SessionStart", "memory_doctor.py", 15, None, ("claude",), "python3 <R>/scripts/sync/memory_doctor.py --hook"),
]
# The two Claude coding-agents rows are written per project (tests/test_hindsight_project_hooks.py);
# the two Codex ones stay here.
# gsd-core's hooks (no cap on GSD): every hook its installer registers, less the two forge keeps its own
# file of (above) and four it leaves out, each judged on its own: read-guard (Claude Code enforces read-before-edit itself),
# secret-read-guard (a hard block on .env reads in every project, not gated to GSD ones: the owner's call), check-update and
# update-banner (forge update replaces them; the banner needs GSD's statusline). Claude only: Codex has none of them.
CLAUDE_A = ("claude",)
D = h.GSD_HOOK_DIR
core = [
    ("SessionStart", "gsd-session-state.sh", 10, None, CLAUDE_A, "bash %s/gsd-session-state.sh" % D),
    ("PostToolUse", "gsd-context-monitor.js", 10, "Bash|Edit|Write|MultiEdit|Agent|Task", CLAUDE_A, "node %s/gsd-context-monitor.js" % D),
    ("SubagentStop", "gsd-context-monitor.js", 10, None, CLAUDE_A, "node %s/gsd-context-monitor.js" % D),
    ("Stop", "gsd-context-monitor.js", 10, None, CLAUDE_A, "node %s/gsd-context-monitor.js" % D),
    ("PreCompact", "gsd-context-monitor.js", 10, None, CLAUDE_A, "node %s/gsd-context-monitor.js" % D),
    ("PostToolUse", "gsd-graphify-update.sh", 5, "Bash", CLAUDE_A, "bash %s/gsd-graphify-update.sh" % D),
    ("PostToolUse", "gsd-phase-boundary.sh", 5, "Write|Edit", CLAUDE_A, "bash %s/gsd-phase-boundary.sh" % D),
    ("PreToolUse", "gsd-workflow-guard.js", 120, "Bash|Edit|Write|MultiEdit", CLAUDE_A, "node %s/gsd-workflow-guard.js" % D),
    ("PreToolUse", "gsd-worktree-path-guard.js", 120, "Write|Edit|MultiEdit", CLAUDE_A, "node %s/gsd-worktree-path-guard.js" % D),
    ("PreToolUse", "gsd-agent-isolation-guard.js", 120, "Agent|Task", CLAUDE_A, "node %s/gsd-agent-isolation-guard.js" % D),
    ("PreToolUse", "gsd-write-guard.js", 120, "Write", CLAUDE_A, "node %s/gsd-write-guard.js" % D),
    ("PreToolUse", "gsd-validate-commit.sh", 120, "Bash", CLAUDE_A, "bash %s/gsd-validate-commit.sh" % D),
    ("FileChanged", "gsd-config-reload.js", 8, "config.json", CLAUDE_A, "node %s/gsd-config-reload.js" % D),
]
check("full config: today's rows, in today's order (six named, session sync, memory gate, the two codex coding-agents rows, then gsd-core's)",
      [g for g in got if g[1] not in ("forge session-start", "coding-agents") and g[5] not in {c[5] for c in core}] == want
      and [g[1] for g in got] == [w[1] for w in want[:6]] + ["forge session-start", "memory_doctor.py"] + ["coding-agents"] * 2 + [c[1] for c in core]
      and [g[4] for g in got if g[1] == "coding-agents"] == [("codex",)] * 2
      and [g for g in got if g[5] in {c[5] for c in core}] == core,
      "got %r" % (got,))

# 11. An event list that forge's own removal empties goes with its key; one that was empty before, or
# that holds anything not forge's, stays as it is. Switching an integration off used to leave
# "Stop": [] and "PostToolUse": [] behind in the user-scope file.
def empty_keys(doc):
    return sorted(e for e, g in (doc.get("hooks") or {}).items() if g == [])


def read_json_file(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


ON = {"codex": True, "gsd": True, "hindsight": False}
OFF = dict(ON, gsd=False)
foreign_stop = "node /elsewhere/own-stop.js"
os.makedirs(os.path.join(HOME, ".claude"), exist_ok=True)
with open(os.path.join(HOME, ".claude", "settings.json"), "w", encoding="utf-8") as fh:
    json.dump({"hooks": {"SessionEnd": [], "PostCompact": [{"hooks": []}], "Stop": [group(foreign_stop, 5)]}, "theme": "toy"}, fh)
h = toy_settings(30, integrations=ON)
attempt(h.write_user_settings, ctx)
on_doc = read_json_file(h.USER_SETTINGS)
check("gsd on: its Stop and PostToolUse rows are written beside the foreign Stop entry",
      any(c.endswith("gsd_output_discipline.py") for c, _, _ in entries(on_doc, "Stop"))
      and (foreign_stop, None, 5) in entries(on_doc, "Stop") and entries(on_doc, "PostToolUse"),
      "Stop %r, PostToolUse %r" % (entries(on_doc, "Stop"), entries(on_doc, "PostToolUse")))
h = toy_settings(31, integrations=OFF)
line = attempt(h.write_user_settings, ctx)
off_doc = read_json_file(h.USER_SETTINGS)
check("on, apply, off, apply: no event key left empty by forge",
      "PostToolUse" not in off_doc["hooks"] and empty_keys(off_doc) == ["SessionEnd"],
      "empty keys %r, events %r, line %r" % (empty_keys(off_doc), sorted(off_doc["hooks"]), line))
check("on, apply, off, apply: the user's own empty list and empty group stay, a foreign entry keeps its event",
      off_doc["hooks"].get("SessionEnd") == [] and off_doc["hooks"].get("PostCompact") == [{"hooks": []}]
      and entries(off_doc, "Stop") == [(foreign_stop, None, 5)] and off_doc.get("theme") == "toy",
      "hooks %r" % (off_doc["hooks"],))
lone = {"hooks": {"Stop": [], "PostToolUse": [{"hooks": []}]}}
attempt(h.reconcile, lone, h.CLAUDE)
check("off from the start: a list that was already empty, and an empty group, are not touched",
      lone["hooks"].get("Stop") == [] and lone["hooks"].get("PostToolUse") == [{"hooks": []}],
      "hooks %r" % (lone["hooks"],))
beside = {"hooks": {"Stop": [{"hooks": []}, group("python3 %s/gsd_output_discipline.py" % h.HOOK_DIR, 10)]}}
attempt(h.reconcile, beside, h.CLAUDE)
check("an event forge takes an entry out of keeps the user's empty group, and so its key",
      beside["hooks"].get("Stop") == [{"hooks": []}], "hooks %r" % (beside["hooks"],))
# the marker passes: a warded entry alone in its event
warded = {"hooks": {"Odd": [group("node /x/claude-sessionstart-hook.js", 5)], "Elsewhere": []}}
attempt(h.reconcile, warded, h.CLAUDE)
check("a warded entry alone in its event: the event goes, an unrelated empty one stays",
      "Odd" not in warded["hooks"] and warded["hooks"].get("Elsewhere") == [],
      "hooks %r" % (warded["hooks"],))
# an entry of the row-less-event pass (a row deleted or moved): the owned event it sits on is the one
# that is not in the marker's rows
moved = {"hooks": {"Odd": [group("python3 %s/gsd_output_discipline.py" % h.HOOK_DIR, 5)]}}
h = toy_settings(32, integrations=ON)
attempt(h.reconcile, moved, h.CLAUDE)
check("a row's entry on an event the row no longer lives on: the event goes with it",
      "Odd" not in moved["hooks"], "hooks %r" % (moved["hooks"],))
# controls that already held: the codex file's drop and a project's settings.local.json
cx = {"hooks": {"Stop": [group(next(iter(sorted(h.codex_commands()))), 5)], "Own": []}}
attempt(h.drop_codex_entries, cx)
check("codex file: an event emptied by the drop goes, an empty one of the user's stays",
      "Stop" not in cx["hooks"] and cx["hooks"].get("Own") == [], "hooks %r" % (cx["hooks"],))
from forge import skills  # noqa: E402
sl = {"hooks": {"PreToolUse": [group("python3 /x/guard.py", 10)], "Own": []}}
skills._own_hook(sl, {}, lambda cmd: "guard.py" in (cmd or ""), "PreToolUse", {"type": "command", "command": "python3 /x/guard.py"},
                 None, False, "label", "short")
check("project settings.local.json: an event emptied by the removal goes, an empty one of the user's stays",
      "PreToolUse" not in sl.get("hooks", {}) and sl.get("hooks", {}).get("Own") == [], "file %r" % (sl,))

sandbox.cleanup(bool(failures))
if failures:
    print("%d of %d checks failed" % (len(failures), n_cases[0]))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % n_cases[0])
