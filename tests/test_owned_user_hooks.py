#!/usr/bin/env python3
"""forge/hooks.py with the ownership record (increment I2 of step 10, task T3): a hook row deleted from
the code used to leave its entry in ~/.claude/settings.json firing forever, because reconcile() never
touches an entry no row owns. Now write_user_settings and write_codex_hooks claim (forge/owned.py) every
entry they leave in place for a row, kind "hook", at [event, matcher, command], owner "core" or the row's
integration. The next run takes out the entry of a claim no row wants any more when it is still exactly
what forge wrote; an edited one stays and is named on one "!" line; an entry forge never claimed is never
touched, and with no record nothing is taken out. The record is written only with --apply, after the file.
`forge doctor` has an `owned` row (cli.owned_row): SKIP while no record exists, PASS with how many files and
claims it looked at, WARN naming each claimed hook that changed (file and `at`, never a value), FAIL when
the record cannot be read.

Everything runs in-process against a toy HOME and a toy config/forge.json; lib.may_write is stubbed to
allow (this checkout may be a linked worktree, which never writes).

Seen failing on bcab228 (no claims, nothing taken out; this file run against that commit's forge/hooks.py and
forge/cli.py): 30 of 62 checks red, for each of the Claude and the Codex file:
  "deleted row's entry still there: True" (the row deleted, the run applied: the entry stays)
  "an apply writes the record: registry exists False", and every check that reads the record after it
  (one claim per row, the owner, the replaced unreadable record)
  the dry-run, the note and the '!' line checks, whose line says "(already current)" there
  the doctor checks: "cli has no owned_row"
The controls that pass there on purpose: no record leaves the entry, a hand-added entry stays, a dry-run
writes no record.
Negative controls on the finished code, each mutation put back from a copy of the file (checks red): the
removal not asking owned.removable (6: an edited entry is taken out); the stale loop off (12); the record
written in a dry-run (2); the owner always core (2); the group matcher ignored in the removal (2: the claimed
entry's twin under another matcher goes); the doctor never comparing (1); never SKIPping (1); not FAILing on an
unreadable record (1); every claimed file gone not a WARN (1); the false branch of write_codex_hooks keeping
the claims (2: a taken-out entry is then called a hand edit by the doctor)."""
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("owned-user-hooks-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, sandbox.FORGE)
from forge import lib, owned  # noqa: E402
lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
from forge import cli, hooks  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
CODEX = os.path.join(HOME, ".codex", "hooks.json")
REGISTRY = os.path.join(HOME, ".local", "state", "forge", "owned.json")

failures, n_cases = [], [0]


def check(label, ok, detail=""):
    n_cases[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:700]))


KEEP = {"event": "UserPromptSubmit", "command": "python3 <ROOT>/toy/keep_row.py", "timeout": 10,
        "marker": "keep_row.py", "matcher": None, "agents": ["claude", "codex"]}
GONE = {"event": "PreToolUse", "command": "python3 <ROOT>/hooks/retired_router.py", "timeout": 10,
       "marker": "retired_router.py", "matcher": "Write|Edit", "agents": ["claude", "codex"]}
GONE_CMD = GONE["command"].replace("<ROOT>", lib.ROOT)
KEEP_CMD = KEEP["command"].replace("<ROOT>", lib.ROOT)
_n = [0]


def world(harness=True, keep=False):
    """A toy forge.json (hindsight on so a code row has an integration owner, codex on, two config rows),
    hooks reloaded over it (its rows are computed at import), and none of the files a run leaves."""
    _n[0] += 1
    doc = {"integrations": {"codex": True, "gsd": False, "hindsight": True},
           "user_settings": {}, "user_hooks": [KEEP, GONE], "codex_harness": harness}
    lib.SETTINGS = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.settings.cache_clear()
    importlib.reload(hooks)
    hooks.USER_SETTINGS, hooks.CODEX_HOOKS = SETTINGS, CODEX
    for p in () if keep else (SETTINGS, SETTINGS + ".bak", CODEX, CODEX + ".bak", REGISTRY):
        if os.path.exists(p):
            os.remove(p)
    return hooks


def delete_row(h, marker="retired_router.py"):
    """The row is gone from the code: the table forgets it, nothing else does."""
    h.USER_HOOKS = [r for r in h.USER_HOOKS if r[3] != marker]
    assert not any(r[3] == marker for r in h.USER_HOOKS) and not any(r[3] == marker for r in h.OFF_HOOKS)


def run(h, which="claude", apply=True):
    try:
        ctx = lib.Ctx(apply, None, True)
        return (h.write_user_settings if which == "claude" else h.write_codex_hooks)(ctx)
    except Exception as e:  # a crash is a red check, not a traceback
        return "raised %s: %s" % (type(e).__name__, e)


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def cmds(p):
    doc = load(p)
    return [h.get("command") for groups in doc.get("hooks", {}).values() for g in groups for h in g.get("hooks", [])]


def registry(p):
    if not os.path.exists(REGISTRY):
        return None
    try:
        return load(REGISTRY)["claims"].get(p)
    except ValueError:
        return None


def break_registry():
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    with open(REGISTRY, "w", encoding="utf-8") as fh:
        fh.write("{not json")


def edit(p, fn):
    doc = load(p)
    for groups in doc["hooks"].values():
        for g in groups:
            for h in g["hooks"]:
                fn(h)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def add_entry(p, event, cmd, matcher=None, timeout=None):
    doc = load(p)
    g = {"hooks": [dict({"type": "command", "command": cmd}, **({"timeout": timeout} if timeout else {}))]}
    if matcher:
        g["matcher"] = matcher
    doc.setdefault("hooks", {}).setdefault(event, []).append(g)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def doctor():
    try:
        return cli.owned_row()
    except Exception as e:
        return lib.Result("FAIL", "owned", "cli has no owned_row" if isinstance(e, AttributeError) else repr(e))


for which, path in (("claude", SETTINGS), ("codex", CODEX)):
    tag = which
    # 1. an apply writes the file and the record: one claim per row of this agent, owner core or the integration.
    h = world()
    line = run(h, which)
    rows = [r for r in h.USER_HOOKS if which in r[5]]
    check("%s: control: the toy rows are in the table" % tag, any(r[1] == GONE_CMD for r in rows) and any(r[1] == KEEP_CMD for r in rows), rows)
    got = registry(path)
    check("%s: an apply writes the record: registry exists %s" % (tag, os.path.exists(REGISTRY)), got is not None, line)
    claims = got or []
    check("%s: one hook claim per row, at [event, matcher, command]" % tag,
          sorted(json.dumps(c["at"]) for c in claims if c["kind"] == "hook")
          == sorted(json.dumps([r[0], r[4], r[1]]) for r in rows), claims)
    owners = {c["at"][2]: c["owner"] for c in claims}
    check("%s: owner is core, or the row's integration" % tag,
          owners.get(GONE_CMD) == "core" and any(o == "hindsight" for o in owners.values()), owners)
    check("%s: the record holds no command text beyond `at` and no entry body" % tag,
          all(set(c) == {"kind", "at", "sum", "owner"} for c in claims), claims)
    line = run(h, which)
    check("%s: a second apply is already current" % tag, "already current" in str(line), line)

    # 2. the row is deleted from the code: the entry goes, with a note, and the claim with it.
    delete_row(h)
    line = run(h, which)
    check("%s: deleted row's entry still there: %s" % (tag, GONE_CMD in cmds(path)), GONE_CMD not in cmds(path), line)
    check("%s: the note says what went" % tag, "retired_router.py" in str(line) and "dropped" in str(line), line)
    check("%s: the other row's entry stays" % tag, KEEP_CMD in cmds(path), cmds(path))
    check("%s: the claim goes with the entry" % tag,
          not any(c["at"][2] == GONE_CMD for c in registry(path) or []), registry(path))
    check("%s: no PreToolUse key is left behind by the emptied event" % tag, "PreToolUse" not in load(path)["hooks"], load(path))
    line = run(h, which)
    check("%s: and the next run is already current" % tag, "already current" in str(line), line)

    # 3. no record: nothing is taken out, whatever the code says.
    h = world()
    run(h, which)
    if os.path.exists(REGISTRY):
        os.remove(REGISTRY)
    delete_row(h)
    line = run(h, which)
    check("%s: no record: the deleted row's entry stays" % tag, GONE_CMD in cmds(path), line)

    # 4. a hand-added entry stays, and so does one that shares the deleted row's script under another command.
    h = world()
    run(h, which)
    add_entry(path, "PreToolUse", "python3 /opt/toy/own_hook.py", "Write|Edit")
    add_entry(path, "PreToolUse", "python3 /elsewhere/retired_router.py")  # same marker as the row, another command
    add_entry(path, "PreToolUse", GONE_CMD, timeout=10)  # byte for byte the claimed entry, under another matcher
    delete_row(h)
    run(h, which)
    check("%s: a hand-added entry stays" % tag, "python3 /opt/toy/own_hook.py" in cmds(path), cmds(path))
    check("%s: the row's command under another matcher stays, the claimed one (its matcher) goes" % tag,
          cmds(path).count(GONE_CMD) == 1 and not any(
              g.get("matcher") == "Write|Edit" and h.get("command") == GONE_CMD
              for g in load(path)["hooks"].get("PreToolUse", []) for h in g["hooks"]), load(path)["hooks"].get("PreToolUse"))
    check("%s: an entry of the row's script under another command stays (forge never claimed it)" % tag,
          "python3 /elsewhere/retired_router.py" in cmds(path), cmds(path))

    # 5. an edited claimed entry stays, is named on one "!" line, and is not claimed after the run.
    h = world()
    run(h, which)
    edit(path, lambda e: e.update(statusMessage="mine") if e.get("command") == GONE_CMD else None)
    delete_row(h)
    line = str(run(h, which))
    bang = [l for l in line.splitlines() if l.strip().startswith("!")]
    check("%s: deleted row's entry still there: %s (it was edited, so it stays)" % (tag, GONE_CMD in cmds(path)),
          GONE_CMD in cmds(path), line)
    check("%s: the edited entry is named on one '!' line" % tag,
          len(bang) == 1 and "retired_router.py" in bang[0] and "mine" not in line, line)
    check("%s: the edit is the user's now: no longer claimed" % tag,
          not any(c["at"][2] == GONE_CMD for c in registry(path) or []), registry(path))
    line = str(run(h, which))
    check("%s: and it is not named again" % tag, "!" not in line and GONE_CMD in cmds(path), line)

    # 6. a dry-run says what it would take out and writes neither file nor record.
    h = world()
    run(h, which)
    delete_row(h)
    reg_before = open(REGISTRY, "rb").read() if os.path.exists(REGISTRY) else None
    file_before = open(path, "rb").read()
    line = str(run(h, which, apply=False))
    check("%s: dry-run: says it would take the entry out" % tag, "would write" in line and "retired_router.py" in line, line)
    check("%s: dry-run: the file and the record are byte-identical" % tag,
          open(path, "rb").read() == file_before
          and (open(REGISTRY, "rb").read() if os.path.exists(REGISTRY) else None) == reg_before, line)
    check("%s: dry-run: deleted row's entry still there: %s (until an apply)" % (tag, GONE_CMD in cmds(path)), GONE_CMD in cmds(path))
    h = world()
    run(h, which, apply=False)
    check("%s: a dry-run from nothing writes no record: registry exists %s" % (tag, os.path.exists(REGISTRY)),
          not os.path.exists(REGISTRY))

    # 7. a record that cannot be read: said, nothing taken out, and an apply replaces it.
    h = world()
    run(h, which)
    break_registry()
    delete_row(h)
    line = str(run(h, which))
    check("%s: an unreadable record is said on a '!' line, and nothing is taken out" % tag,
          "could not read" in line and "!" in line and GONE_CMD in cmds(path), line)
    check("%s: and the apply replaced it with one that reads" % tag, registry(path) is not None, line)

# 8. the Codex file with codex_harness off: no record is made, and one that exists for the file is emptied
# with the entries (else the doctor would call every taken-out entry a hand edit).
h = world(harness=False)
run(h, "codex")
check("codex_harness false: no record is written: registry exists %s" % os.path.exists(REGISTRY), not os.path.exists(REGISTRY))
h = world(harness=True)
run(h, "codex")
run(h, "claude")
check("control: codex_harness true claims the Codex file", bool(registry(CODEX)), registry(CODEX))
h = world(harness=False, keep=True)
line = run(h, "codex")
check("true -> false: the entries are out", KEEP_CMD not in cmds(CODEX), line)
check("true -> false: the Codex claims go with them: %r" % (registry(CODEX),), not registry(CODEX), line)
check("true -> false: the Claude file's claims stay", bool(registry(SETTINGS)), registry(SETTINGS))
r = doctor()
check("true -> false: the doctor does not call the taken-out entries a hand edit -- %r" % (r,), r.level == "PASS", r)

# 9. HOOK_WARDS keeps working beside the record: a warded entry is dropped with no claim behind it.
h = world()
run(h)
add_entry(SETTINGS, "SessionStart", "node /x/claude-sessionstart-hook.js")
line = run(h)
check("a warded entry still goes without any claim", "node /x/claude-sessionstart-hook.js" not in cmds(SETTINGS), line)

# 10. the doctor row.
h = world()
r = doctor()
check("doctor, no record: SKIP with NOT RUN, NOT ARMED -- %r" % (r,),
      r.level == "SKIP" and "NOT RUN, NOT ARMED" in r.detail and "no ownership record yet" in r.detail, r)
run(h)
run(h, "codex")
r = doctor()
n_claims = sum(len(v) for v in load(REGISTRY)["claims"].values()) if os.path.exists(REGISTRY) else 0
check("doctor after an apply: PASS saying how many files and claims it looked at -- %r" % (r,),
      r.level == "PASS" and "2 file" in r.detail and "%d claim" % n_claims in r.detail and n_claims > 0, r)
edit(SETTINGS, lambda e: e.update(timeout=99) if e.get("command") == GONE_CMD else None)
r = doctor()
check("doctor after a hand edit: WARN naming the file and `at`, no value -- %r" % (r,),
      r.level == "WARN" and "settings.json" in r.detail and GONE_CMD in r.detail and "99" not in r.detail
      and "PreToolUse" in r.detail, r)
break_registry()
r = doctor()
check("doctor over a record that does not read: FAIL, reading it as the cause -- %r" % (r,),
      r.level == "FAIL" and "could not read" in r.detail, r)
run(h)
r = doctor()
check("doctor after an apply that replaced the record: PASS again -- %r" % (r,), r.level == "PASS", r)
check("doctor is a row of CHECKS, with the fix that rewrites the record",
      any(name == "owned" and cmd is cli.owned_row and "forge sync --apply" in fix for name, cmd, fix in cli.CHECKS), "")

# 11. a claimed file that is gone or does not parse is said. Both files are claimed here; one gone is a PASS that
# says so (a missing file is not a hand edit), every one gone is a WARN (nothing was compared), one that does not
# parse is a WARN naming it.
h = world()
run(h)
run(h, "codex")
os.remove(SETTINGS)
r = doctor()
check("doctor: one claimed file gone, the other compared: PASS that says it is not there -- %r" % (r,),
      r.level == "PASS" and "not there" in r.detail and "settings.json" in r.detail and "in 1 file(s)" in r.detail, r)
os.remove(CODEX)
r = doctor()
check("doctor: every claimed file gone: WARN, nothing was looked at -- %r" % (r,),
      r.level == "WARN" and "not there" in r.detail and "0 claim(s) in 0 file(s)" in r.detail, r)
with open(SETTINGS, "w", encoding="utf-8") as fh:
    fh.write("{not json")
r = doctor()
check("doctor: a claimed file that does not parse is a WARN naming it -- %r" % (r,),
      r.level == "WARN" and "settings.json" in r.detail and "could not read" in r.detail, r)

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL", f)
print("%d checks, %d failures" % (n_cases[0], len(failures)))
sys.exit(1 if failures else 0)
