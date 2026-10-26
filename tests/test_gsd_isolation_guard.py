#!/usr/bin/env python3
"""config/forge.json's `gsd_isolation_guard`: the one GSD core row `gsd-agent-isolation-guard.js` (PreToolUse,
Agent|Task) can be switched off on a machine. Absent or true: written as it always was. The JSON false: not
written, and reconcile() takes forge's entry out by its exact command (never by file name, so GSD's own
differently-commanded hook of the same file stays). Any other value stays on, and `forge doctor`'s
`gsd isolation guard` row FAILs naming the key. With the switch off that row is a SKIP (NOT RUN, NOT ARMED)
naming the switch and how to turn it on; with it on and the entry missing from ~/.claude/settings.json it is a FAIL.

Everything runs against a toy forge.json (lib.SETTINGS) and a toy HOME; nothing real is written.

Seen failing on the code before the change (hooks.py without the gate, cli.py without the row), the cases as
they printed:
21 of 31 checks red, the other 10 are controls that pass on the old code (key absent or true writes the row, any
other value stays on):
  key false: the row is not written -- rows [('PreToolUse', 'node <HOME>/.claude/hooks/gsd-agent-isolation-guard.js',
    120, 'gsd-agent-isolation-guard.js', 'Agent|Task', ('claude',))]
  key false: the row is on the take-out list, by its exact command -- OFF_HOOKS []
  key false: forge's entry is taken out by its exact command -- the entry was still in PreToolUse
  key false: a foreign hook of the same file name under another command is kept, forge's goes -- the entry was
    still there (the row on, the old reconcile also drops a foreign one by marker)
  the row is registered in forge doctor's CHECKS -- CHECKS names ['skill refs', ..., 'doctor_extra']
  every doctor case on ('raised', 'AttributeError', "module 'forge.cli' has no attribute 'gsd_isolation_guard_row'")
Mutants on the finished code, each put back from a copy of the file:
  reconcile's exact-command removal of off rows replaced by `removed = 0` -- 4 red: "key false: forge's entry is
    taken out by its exact command -- PreToolUse [('node <HOME>/.claude/hooks/gsd-agent-isolation-guard.js',
    'Agent|Task', 120), ...", "key false: the entry goes whatever its matcher and timeout", "key false: a foreign
    hook of the same file name ... is kept, forge's goes", "key false after true: the same file loses exactly
    that entry"
  the doctor's missing-entry FAIL disabled -- 1 red: "doctor, key true, entry missing: FAIL naming the command's
    file and the fix -- got Result(level='PASS', name='gsd isolation guard', detail='0
    gsd-agent-isolation-guard.js entries under PreToolUse in ~/.claude/settings.json')"
Not written here: the byte-identity of `forge sync`'s dry-run with the key absent or true (compared with cmp on a
toy world, in the commit message).
"""
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

REPO = sandbox.FORGE
TOY = sandbox.mkdtemp("isolation-guard-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(os.path.join(HOME, ".claude"))
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.path.insert(0, REPO)
from forge import lib  # noqa: E402
# hooks reads the settings file when it is imported; this checkout's config/forge.json is private data a
# stranger's copy lacks.
lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {"codex": False, "gsd": True, "hindsight": False}}, fh)
from forge import hooks  # noqa: E402
from forge import cli  # noqa: E402

failures, n_cases = [], [0]
GUARD = "gsd-agent-isolation-guard.js"
OTHER = "gsd-write-guard.js"
SETTINGS_FILE = os.path.join(HOME, ".claude", "settings.json")


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


_n = [0]
class _Null:
    """Stands for the key present with the JSON value null."""
    def __repr__(self):
        return "null"


NULL = _Null()


def world(**over):
    """A toy forge.json (gsd on, gsd_patches true, the rest off) plus `over`, with hooks reloaded over it
    (its rows are computed at import). An override of None drops the key."""
    _n[0] += 1
    doc = {"integrations": {"codex": False, "gsd": True, "hindsight": False}, "gsd_patches": True,
           "user_settings": {}, "user_hooks": []}
    doc.update(over)
    doc = {k: (None if v is NULL else v) for k, v in doc.items() if v is not None}
    path = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()
    importlib.reload(hooks)
    hooks.USER_SETTINGS = SETTINGS_FILE
    return hooks


def entries(doc, event):
    return [(h.get("command"), g.get("matcher"), h.get("timeout")) for g in doc.get("hooks", {}).get(event, [])
            for h in g.get("hooks", [])]


def group(cmd, timeout=None, matcher=None):
    h = {"type": "command", "command": cmd}
    if timeout is not None:
        h["timeout"] = timeout
    return dict({"matcher": matcher} if matcher else {}, hooks=[h])


def rows(h, marker=GUARD):
    return [r for r in h.USER_HOOKS if r[3] == marker]


def off_rows(h, marker=GUARD):
    return [r for r in h.OFF_HOOKS if r[3] == marker]


def gsd_dir_cmd(h, script=GUARD):
    return "node %s/%s" % (h.GSD_HOOK_DIR, script)


# 1. The row is written with the key absent or true: the same table, the same row, as before the key.
h = world(gsd_isolation_guard=None)
absent_table = list(h.USER_HOOKS)
check("key absent: the row is written", len(rows(h)) == 1 and rows(h)[0][1] == gsd_dir_cmd(h) and rows(h)[0][2] == 120
      and rows(h)[0][4] == "Agent|Task" and rows(h)[0][0] == "PreToolUse",
      "rows %r" % (rows(h),))
check("key absent: nothing of the row is in the take-out list", not off_rows(h), "OFF_HOOKS %r" % (off_rows(h),))
h = world(gsd_isolation_guard=True)
check("key true: the table is the one written with the key absent (same rows, same order)",
      h.USER_HOOKS == absent_table, "differs: %r" % ([r for r in h.USER_HOOKS if r not in absent_table],))
check("key true: the row is written", len(rows(h)) == 1, "rows %r" % (rows(h),))

# 2. The JSON false: the row is not written, it is on the take-out list, and the other core rows are untouched.
h = world(gsd_isolation_guard=False)
check("key false: the row is not written", not rows(h), "rows %r" % (rows(h),))
check("key false: the row is on the take-out list, by its exact command", [r[1] for r in off_rows(h)] == [gsd_dir_cmd(h)],
      "OFF_HOOKS %r" % (off_rows(h),))
check("key false: every other row is still written, in the same order",
      h.USER_HOOKS == [r for r in absent_table if r[3] != GUARD],
      "got %r" % ([r[3] for r in h.USER_HOOKS],))

# 3. Any other value stays on (only the JSON false switches it off).
for bad in ("false", "no", 0, NULL):
    h = world(gsd_isolation_guard=bad)
    check("key %r: not the JSON false, so the row is still written" % (bad,), len(rows(h)) == 1,
          "rows %r" % (rows(h),))

# 4. reconcile with the key false: forge's entry goes by its exact command, whatever its matcher, timeout or event
# neighbours; the other core rows stay.
h = world(gsd_isolation_guard=False)
mine = gsd_dir_cmd(h)
other = gsd_dir_cmd(h, OTHER)
doc = {"hooks": {"PreToolUse": [group(mine, 120, "Agent|Task"), group(other, 120, "Write")]}}
notes = attempt(h.reconcile, doc, h.CLAUDE)
pre = entries(doc, "PreToolUse")
check("key false: forge's entry is taken out by its exact command", mine not in [c for c, _, _ in pre],
      "PreToolUse %r, notes %r" % (pre, notes))
check("key false: forge's other core entry stays", (other, "Write", 120) in pre, "PreToolUse %r" % (pre,))
doc = {"hooks": {"PreToolUse": [group(mine, 7, "Odd")]}}
attempt(h.reconcile, doc, h.CLAUDE)
check("key false: the entry goes whatever its matcher and timeout", mine not in [c for c, _, _ in entries(doc, "PreToolUse")],
      "PreToolUse %r" % (entries(doc, "PreToolUse"),))

# 5. A foreign hook with the same file name and another command is kept (GSD's own installer writes one).
gsd_own = "node /x/.claude/hooks/%s" % GUARD
gsd_own_cmd = "node /elsewhere/hooks/%s --flag" % GUARD
doc = {"hooks": {"PreToolUse": [group(mine, 120, "Agent|Task"), group(gsd_own, 10, "Agent"), group(gsd_own_cmd, 5, "Task")]}}
attempt(h.reconcile, doc, h.CLAUDE)
check("key false: a foreign hook of the same file name under another command is kept, forge's goes",
      [e for e in entries(doc, "PreToolUse") if GUARD in e[0]] == [(gsd_own, "Agent", 10), (gsd_own_cmd, "Task", 5)],
      "PreToolUse %r" % (entries(doc, "PreToolUse"),))

# 6. With the key on, reconcile writes the entry (the control for 4: the entry is there to be taken out).
h = world(gsd_isolation_guard=True)
doc = {}
attempt(h.reconcile, doc, h.CLAUDE)
check("key true: reconcile writes the entry", (gsd_dir_cmd(h), "Agent|Task", 120) in entries(doc, "PreToolUse"),
      "PreToolUse %r" % (entries(doc, "PreToolUse"),))
h = world(gsd_isolation_guard=False)
attempt(h.reconcile, doc, h.CLAUDE)
check("key false after true: the same file loses exactly that entry",
      (gsd_dir_cmd(h), "Agent|Task", 120) not in entries(doc, "PreToolUse")
      and (gsd_dir_cmd(h, OTHER), "Write", 120) in entries(doc, "PreToolUse"),
      "PreToolUse %r" % (entries(doc, "PreToolUse"),))

# 7. The doctor row.


def call_row():
    """cli.gsd_isolation_guard_row(), or ('raised', ...) when it is not there or raises."""
    return attempt(lambda: cli.gsd_isolation_guard_row())


def row(**over):
    h = world(**over)
    cli.hooks = h
    return call_row()


def write_settings(doc):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def settings_with_guard(h):
    doc = {}
    h.reconcile(doc, h.CLAUDE)
    return doc


check("the row is registered in forge doctor's CHECKS", {n: c for n, c, _ in cli.CHECKS}.get("gsd isolation guard")
      is getattr(cli, "gsd_isolation_guard_row", 0), "CHECKS names %r" % ([n for n, _, _ in cli.CHECKS],))

r = row(gsd_isolation_guard=False)
check("doctor, key false: a SKIP that did not look, naming the switch and how to turn it on",
      getattr(r, "level", None) == "SKIP" and "NOT RUN, NOT ARMED" in r.detail and "gsd_isolation_guard" in r.detail
      and "true" in r.detail and "forge sync --apply" in r.detail, "got %r" % (r,))

h = world(gsd_isolation_guard=True)
cli.hooks = h
if os.path.exists(SETTINGS_FILE):
    os.remove(SETTINGS_FILE)
r = call_row()
check("doctor, key true, no settings.json: FAIL naming the fix", getattr(r, "level", None) == "FAIL"
      and "forge sync --apply" in r.detail, "got %r" % (r,))
write_settings({"hooks": {"PreToolUse": [group(gsd_dir_cmd(h, OTHER), 120, "Write")]}})
r = call_row()
check("doctor, key true, entry missing: FAIL naming the command's file and the fix",
      getattr(r, "level", None) == "FAIL" and GUARD in r.detail and "forge sync --apply" in r.detail, "got %r" % (r,))
write_settings(settings_with_guard(h))
r = call_row()
check("doctor, key true, entry present: PASS", getattr(r, "level", None) == "PASS", "got %r" % (r,))
check("doctor, key true, entry present: the line says what it looked at",
      getattr(r, "detail", "") and "1" in r.detail and GUARD in r.detail, "got %r" % (r,))
r = row(gsd_isolation_guard=None)
check("doctor, key absent, entry present: PASS (absent is on)", getattr(r, "level", None) == "PASS", "got %r" % (r,))
os.remove(SETTINGS_FILE)
r = call_row()
check("doctor, key absent, no settings.json: FAIL (absent is on)", getattr(r, "level", None) == "FAIL", "got %r" % (r,))
for bad in ("no", 0, "false", NULL):
    r = row(gsd_isolation_guard=bad)
    check("doctor, key %r: FAIL naming the key and saying it is read as true" % (bad,),
          getattr(r, "level", None) == "FAIL" and "gsd_isolation_guard" in r.detail and "true or false" in r.detail,
          "got %r" % (r,))
r = row(integrations={"codex": False, "gsd": False, "hindsight": False}, gsd_isolation_guard=True)
check("doctor, gsd off: SKIP (forge writes no GSD row)", getattr(r, "level", None) == "SKIP" and "NOT RUN, NOT ARMED" in r.detail
      and "gsd" in r.detail, "got %r" % (r,))
r = row(gsd_patches=False, gsd_isolation_guard=True)
check("doctor, gsd_patches false: SKIP (forge writes no GSD row)", getattr(r, "level", None) == "SKIP"
      and "gsd_patches" in r.detail, "got %r" % (r,))

sandbox.cleanup(bool(failures))
if failures:
    print("%d of %d checks FAILED:" % (len(failures), n_cases[0]))
    for f in failures:
        print("FAIL %s" % f)
    sys.exit(1)
print("ok: %d checks" % n_cases[0])
