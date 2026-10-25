#!/usr/bin/env python3
"""A profile's `hooks` reach <project>/.claude/settings.local.json through skills.write_settings_local
(T4 of docs/archive/designs/hooks-phase-design.md): the hooked app's guard, audit and skill-tracking hooks were written by
hand into a git-ignored file, so a fresh machine never got them. The merge only appends -- a
hand-written hook is never removed -- and a second run leaves the file byte-identical.

Runs write_settings_local in-process against a toy HOME and toy projects; nothing real is touched.
Seen failing on c7869b3 (skills.py without `hooks`), 9 of 20 checks red:
  declares hooks: written -- 'hooks' is not in the file: keys ['permissions']
  declares hooks: counted in the line -- the line ends "perms allow 2)", no ", hooks 3"
  hand-written: PostToolUse order / PreToolUse added -- PostToolUse holds only the two refreshers,
    PreToolUse was None
  partial: the missing command only -- PostToolUse held audit and the todoist refresher, no tracker
  only hooks declared: written -- no file, or no hooks in it
  not an object: said -- the line has no "not merged"
  real profile: declares hooks -- hooked-app.claude.json declares no hooks
  real profile: the three, as the hooked app has them -- hooks were None
Negative controls, each run once on the finished code and put back from a copy:
  dedupe removed (`if True`) -- 4 red: again: byte-identical, again: already current, partial: the
    missing command only, real profile over today's file: byte-identical
  whole-key overwrite of `hooks` -- 5 red: hand-written: PostToolUse order, an event the profile
    does not name ("Stop was None"), partial x2, real profile over today's file: byte-identical
  `hooks` left out of `declared` -- 1 red: only hooks declared: written
  object guard removed -- AttributeError: 'list' object has no attribute 'get' (skills.py:187)
Round 8 cases (case 8b), seen failing on a00252c, 7 of 34 red:
  event value a string: the line names the event as not merged -- line was '... (untrimmed
    (pass-through only), perms allow 1, hooks 3)' (counted as merged), and the count is the merged ones
  group hooks null -- TypeError: 'NoneType' object is not iterable
  group hooks a string / hook entry a string / group a string -- AttributeError: 'str' object has no
    attribute 'get'
  group null -- AttributeError: 'NoneType' object has no attribute 'get'
Case 10 (`command_guard`, T2 of docs/command-guard-design.md), seen failing on df813da, 17 of 92 red:
  guard on: exactly the canonical entry -- PreToolUse was None
  guard on: the line says so -- the line ends "perms allow 2)", no ", command guard on"
  guard on over the legacy entry: another event's copy goes -- the argument-less entry stayed in PostToolUse
  guard off over a legacy entry the profile does not declare -- the entry stayed
  no declaration, a guard entry in the file: removed -- the early return left the file as it was
  guard on, hooks not an object: the line says not merged -- the line had no "guard not merged"
  (and test_lib.py: "profile_error(command_guard 1) = None, want 'command_guard is not a boolean'", x3)
Passing already on the old code, as controls: no line / false -> no guard entry, hand hooks untouched.
Negative controls on the finished code, each put back from a copy:
  profile-declared entries not protected -- 1 red: guard off, entry declared in the profile's hooks
  every command taken for forge's guard -- 18 red (hand-written hooks removed)
  `on = True` -- 20 red (a profile without the line gets the entry)
  early return blind to a guard entry -- 1 red: no declaration, a guard entry in the file
  no duplicate collapse -- 1 red; a relative path or another project's copy counted as forge's -- 5 red
  an emptied `hooks` left behind -- 2 red: guard off after on, no declaration
Case 6 now holds the audit hook, not the guard: a guard entry in the file is forge's to remove.
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("profile-hooks-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from forge import lib, skills  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"

APPLY = lib.Ctx(True, None, False)
DRY = lib.Ctx(False, None, False)
FORGE_HOOKS = "/opt/toy-forge/hooks"  # what tests/fixtures/config/profiles/hooked-app.claude.json names too
HOOKED_SCRIPTS = "/opt/toy-app/scripts/sync"
GUARD = {"type": "command", "command": "python3 %s/guard_tool_use.py" % FORGE_HOOKS, "timeout": 10}
AUDIT = {"type": "command", "command": "python3 %s/audit_tool_use.py" % FORGE_HOOKS, "timeout": 10}
TRACK = {"type": "command", "command": "python3 %s/track_skill_usage.py" % FORGE_HOOKS, "timeout": 10}
# The three entries as the hooked app's settings.local.json holds them: same command strings, timeout 10, no matcher.
DECLARED = {"PreToolUse": [{"hooks": [GUARD]}], "PostToolUse": [{"hooks": [AUDIT, TRACK]}]}
# the hooked app's own two scripts, hand-written beside them: not forge's to own or remove.
TODOIST = {"matcher": "mcp__todoist__todoist_task_create",
           "hooks": [{"type": "command", "command": "python3 %s/refresh_todoist_cache.py" % HOOKED_SCRIPTS, "timeout": 15}]}
CALENDAR = {"matcher": "mcp__google__google_calendar_create_event",
            "hooks": [{"type": "command", "command": "python3 %s/refresh_calendar_cache.py" % HOOKED_SCRIPTS, "timeout": 15}]}

failures = []
n_cases = 0
n_proj = 0


def check(label, ok, detail=""):
    global n_cases
    n_cases += 1
    if not ok:
        failures.append("%s: %s" % (label, detail))
        print("FAIL", label, detail)


def project(settings=None):
    """A toy project dir, with settings.local.json holding `settings` when given."""
    global n_proj
    n_proj += 1
    p = os.path.join(TOY, "proj%d" % n_proj)
    os.makedirs(os.path.join(p, ".claude"))
    if settings is not None:
        lib.write_json(os.path.join(p, ".claude", "settings.local.json"), settings)
    return p


def slp(p):
    return os.path.join(p, ".claude", "settings.local.json")


def read(p):
    with open(slp(p), "rb") as f:
        return f.read()


def run(p, hooks=None, ctx=APPLY, **extra):
    prof = {"project": "toy", "project_path": p, "permissions": {"allow": ["Bash(true)"]}}
    if hooks is not None:
        prof["hooks"] = copy.deepcopy(hooks)
    prof.update(extra)
    return skills.write_settings_local(ctx, prof)


def commands(doc, event):
    return [h["command"] for g in (doc.get("hooks") or {}).get(event, []) for h in g["hooks"]]


# 1. A profile that declares hooks, over a file with none: they arrive, and the line counts them.
p = project({"permissions": {"allow": ["Edit"]}})
line = run(p, DECLARED)
doc = json.loads(read(p))
check("declares hooks: written", doc.get("hooks") == DECLARED,
      "'hooks' is not in the file: keys %s" % sorted(doc))
check("declares hooks: counted in the line", ", hooks 3)" in (line or ""), "line was %r" % line)
check("declares hooks: permissions kept", doc.get("permissions", {}).get("allow") == ["Edit", "Bash(true)"],
      "permissions were %r" % doc.get("permissions"))

# 2. Same profile again: byte-identical, and the line says so. (Mutating the dedupe out of the merge
#    turns this red: the second run appends the three again.)
first = read(p)
line = run(p, DECLARED)
check("again: byte-identical", read(p) == first, "the second run changed the file")
check("again: already current", (line or "").endswith("(already current)"), "line was %r" % line)

# 3. A dry run writes nothing.
p = project({"permissions": {"allow": ["Edit"]}})
before = read(p)
line = run(p, DECLARED, ctx=DRY)
check("dry run: file untouched", read(p) == before, "a dry run wrote")
check("dry run: says would write", (line or "").lstrip().startswith("would write"), "line was %r" % line)

# 4. Hand-written hooks in the same event survive, in place, and the declared ones come after them.
#    (Whole-key overwrite of `hooks` turns this red: TODOIST and CALENDAR are gone.)
p = project({"hooks": {"PostToolUse": [TODOIST, CALENDAR], "Stop": [{"hooks": [{"type": "command", "command": "true"}]}]}})
run(p, DECLARED)
doc = json.loads(read(p))
check("hand-written: PostToolUse order", (doc.get("hooks") or {}).get("PostToolUse") == [TODOIST, CALENDAR, {"hooks": [AUDIT, TRACK]}],
      "PostToolUse was %r" % (doc.get("hooks") or {}).get("PostToolUse"))
check("hand-written: an event the profile does not name", (doc.get("hooks") or {}).get("Stop") == [{"hooks": [{"type": "command", "command": "true"}]}],
      "Stop was %r" % (doc.get("hooks") or {}).get("Stop"))
check("hand-written: PreToolUse added", commands(doc, "PreToolUse") == [GUARD["command"]], "PreToolUse was %r" % (doc.get("hooks") or {}).get("PreToolUse"))

# 5. A command the file already holds is not appended again, even when the profile's group is wider:
#    only the missing one comes, with the group's own matcher; and nothing already there is removed.
p = project({"hooks": {"PostToolUse": [{"hooks": [AUDIT]}, TODOIST]}})
run(p, DECLARED)
doc = json.loads(read(p))
check("partial: the missing command only", commands(doc, "PostToolUse") ==
      [AUDIT["command"], TODOIST["hooks"][0]["command"], TRACK["command"]], "PostToolUse was %r" % commands(doc, "PostToolUse"))
check("partial: no removal", ((doc.get("hooks") or {}).get("PostToolUse") or [])[:2] == [{"hooks": [AUDIT]}, TODOIST], "the existing groups moved or changed")

# 6. A profile without `hooks` leaves the key exactly as it is, hand-written or not.
hand = {"PostToolUse": [TODOIST], "PreToolUse": [{"hooks": [AUDIT]}]}   # not a guard entry: those are forge's (case 10)
p = project({"hooks": hand, "permissions": {"allow": ["Edit"]}})
line = run(p)
check("no hooks key: untouched", json.loads(read(p)).get("hooks") == hand, "hooks became %r" % json.loads(read(p)).get("hooks"))
check("no hooks key: line does not mention hooks", ", hooks " not in (line or ""), "line was %r" % line)

# 7. A profile whose only declaration is `hooks` still writes (it is a declaration, like permissions).
p = project()
run(p, DECLARED, permissions=None)
check("only hooks declared: written", os.path.exists(slp(p)) and json.loads(read(p)).get("hooks") == DECLARED,
      "no file, or no hooks in it")

# 8. A `hooks` that is not an object in the file is left alone and the line says so.
p = project({"hooks": ["not", "an", "object"]})
line = run(p, DECLARED)
check("not an object: left alone", json.loads(read(p)).get("hooks") == ["not", "an", "object"], "hooks was rewritten")
check("not an object: said", "not merged" in (line or ""), "line was %r" % line)

# 8b. Round 8, profile-hooks: a file whose event value is not a list, whose group has `hooks: null`,
#     or whose event holds non-dict items is hand-corrupted input. The event is left as it is, the
#     line names it "not merged", and nothing raises. Each case runs write_settings_local under
#     try/except so a crash is a red line and not a traceback that hides the other cases.
def run_safely(p):
    try:
        return run(p, DECLARED), None
    except Exception as e:  # noqa: BLE001 -- the point is to see which one
        return None, "%s: %s" % (type(e).__name__, e)


for label, bad, event in (
        ("event value a string", "not a list", "PreToolUse"),
        ("group hooks null", [{"hooks": None}], "PostToolUse"),
        ("group hooks a string", [{"hooks": "x"}], "PostToolUse"),
        ("hook entry a string", [{"hooks": ["x"]}], "PostToolUse"),
        ("group a string", ["x"], "PostToolUse"),
        ("group null", [None], "PostToolUse")):
    p = project({"hooks": {event: bad}})
    line, err = run_safely(p)
    check("malformed file (%s): does not raise" % label, err is None, err or "")
    if err:
        continue
    doc = json.loads(read(p))
    check("malformed file (%s): the event is left alone" % label, (doc.get("hooks") or {}).get(event) == bad,
          "%s was %r" % (event, (doc.get("hooks") or {}).get(event)))
    check("malformed file (%s): the line names the event as not merged" % label,
          "%s not merged" % event in (line or ""), "line was %r" % line)
    other = "PostToolUse" if event == "PreToolUse" else "PreToolUse"
    check("malformed file (%s): the other event is still merged" % label,
          commands(doc, other) == [c["command"] for g in DECLARED[other] for c in g["hooks"]],
          "%s was %r" % (other, commands(doc, other)))
    # Not counted as merged: the declared hooks of the other event only.
    merged = sum(len(g["hooks"]) for g in DECLARED[other])
    check("malformed file (%s): the count is the merged ones" % label, ", hooks %d," % merged in (line or ""),
          "line was %r" % line)

# A well-formed file says nothing of the kind (negative control for the "not merged" wording).
p = project({"hooks": {"PreToolUse": []}})
line, err = run_safely(p)
check("well-formed file: nothing is reported as not merged", err is None and "not merged" not in (line or ""),
      err or "line was %r" % line)

# 9. A profile that declares hooks and turns the command guard on: tests/fixtures/config/profiles/
#    hooked-app.claude.json, the shape of the one a real project had (this case read that profile, private data
#    a copy_engine copy lacks: red there before, M1: "FileNotFoundError: .../config/profiles/
#    hooked-app.claude.json" at test_profile_hooks.py:242). Its guard moved to the `command_guard` line (T4 of
#    docs/command-guard-design.md), so its `hooks` block holds the audit and the tracker only. Over
#    a file as it was before T4 (the argument-less guard, the audit and tracker, the two
#    refreshers) the run swaps the guard for the canonical entry and touches nothing else.
#    Seen failing on 56eb61d with the profile moved and this case unchanged:
#    "real profile: the three, as the hooked app has them hooks were {'PostToolUse': [...]}".
with open(os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "profiles", "hooked-app.claude.json")) as f:
    hooked = json.load(f)
HOOKED_HOOKS = {"PostToolUse": [{"hooks": [AUDIT, TRACK]}]}
check("fixture profile: declares hooks", bool(hooked.get("hooks")), "hooked-app.claude.json declares no hooks")
check("fixture profile: the audit and the tracker, no guard", hooked.get("hooks") == HOOKED_HOOKS, "hooks were %r" % hooked.get("hooks"))
check("fixture profile: command_guard is on", hooked.get("command_guard") is True, "command_guard was %r" % hooked.get("command_guard"))
# Where this checkout has the real profile, the checks it used to get run on it too, by script name: its hooks
# block holds the audit and the tracker only, its command_guard is on, and each script is in forge's hooks/.
REAL_PROFILE = os.path.join(lib.PROFILES, "life" + "os.claude.json")
if os.path.exists(REAL_PROFILE):
    with open(REAL_PROFILE) as f:
        real = json.load(f)
    names = lambda hooks: [[os.path.basename(h["command"].split(" ", 1)[1]) for g in gs for h in g["hooks"]]
                           for gs in (hooks or {}).values()]
    check("real profile: declares hooks", bool(real.get("hooks")), "the real profile declares no hooks")
    check("real profile: the audit and the tracker, no guard", names(real.get("hooks")) == [["audit_tool_use.py", "track_skill_usage.py"]]
          and list(real.get("hooks") or {}) == ["PostToolUse"], "hooks were %r" % real.get("hooks"))
    check("real profile: command_guard is on", real.get("command_guard") is True, "command_guard was %r" % real.get("command_guard"))
    for event, groups in (real.get("hooks") or {}).items():
        for g in groups:
            for h in g["hooks"]:
                script = h["command"].split(" ", 1)[1]
                check("real profile: %s exists in forge's hooks/" % os.path.basename(script),
                      os.path.isfile(os.path.join(lib.ROOT, "hooks", os.path.basename(script))), script)
else:
    print("NOT RUN: the real profile's hooks block (four cases) -- no such profile in this checkout")
live_guard = os.path.join(lib.ROOT, "hooks", "guard_tool_use.py")
before_t4 = {"type": "command", "command": "python3 %s" % live_guard, "timeout": 10}
today = {"permissions": {"allow": ["Edit"]},
         "hooks": {"PreToolUse": [{"hooks": [before_t4]}], "PostToolUse": [{"hooks": [AUDIT, TRACK]}, TODOIST, CALENDAR]}}
p = project(today)
# Only its hooks and the line: the trim keys would add skillOverrides, which is not what this case asks about.
hooked_profile = {"project": "hooked-app", "project_path": p, "hooks": hooked.get("hooks"), "command_guard": hooked.get("command_guard")}
skills.write_settings_local(APPLY, hooked_profile)
got = json.loads(read(p)).get("hooks") or {}
want_guard = [{"hooks": [{"type": "command", "command": "python3 %s --project hooked-app" % live_guard, "timeout": 10}]}]
check("fixture profile over its pre-T4 file: the guard is the canonical entry only", got.get("PreToolUse") == want_guard,
      "PreToolUse was %r" % got.get("PreToolUse"))
check("fixture profile over its pre-T4 file: the rest is untouched", got.get("PostToolUse") == today["hooks"]["PostToolUse"],
      "PostToolUse was %r" % got.get("PostToolUse"))
settled = read(p)
skills.write_settings_local(APPLY, hooked_profile)
check("fixture profile, again: byte-identical", read(p) == settled, "the second run changed the file")

# 10. `command_guard` (T2 of docs/command-guard-design.md): a profile's "command_guard": true makes
#     write_settings_local own the guard's PreToolUse entry -- exactly one, canonical, with the
#     profile's name in --project -- and every other entry that runs forge's hooks/guard_tool_use.py
#     goes, in every event. Without the line they all go (except what the profile's own `hooks`
#     declares: the hooked app's hand-declared guard stays until T4). Any other hook is untouched.
GUARD_PY = os.path.join(lib.ROOT, "hooks", "guard_tool_use.py")


def canon(name="toy"):
    return {"type": "command", "command": "python3 %s --project %s" % (GUARD_PY, name), "timeout": 10}


LEGACY = {"type": "command", "command": "python3 %s" % GUARD_PY, "timeout": 10}   # the hooked app's today: no argument
HAND = {"type": "command", "command": "true", "timeout": 5}
DECLARED_LEGACY = {"PreToolUse": [{"hooks": [LEGACY]}]}
# Not forge's guard: a project's own copy under its .claude/hooks (a frozen project has one), never ours.
PORTAL_COPY = {"type": "command", "command": "python3 /somewhere/frozen-app/.claude/hooks/guard_tool_use.py", "timeout": 10}
RELATIVE = {"type": "command", "command": "python3 hooks/guard_tool_use.py", "timeout": 10}


def hooks_of(p):
    return json.loads(read(p)).get("hooks")


p = project({"permissions": {"allow": ["Edit"]}})
run(p)
original = read(p)    # after one plain run, which merges the toy profile's own permission
line = run(p, command_guard=True)
check("guard on: exactly the canonical entry, no matcher, timeout 10",
      (hooks_of(p) or {}).get("PreToolUse") == [{"hooks": [canon()]}], "PreToolUse was %r" % (hooks_of(p) or {}).get("PreToolUse"))
check("guard on: the line says so", ", command guard on" in (line or ""), "line was %r" % line)
check("guard on: no other event written", sorted(hooks_of(p) or {}) == ["PreToolUse"], "events were %r" % sorted(hooks_of(p) or {}))
first = read(p)
line = run(p, command_guard=True)
check("guard on, again: byte-identical", read(p) == first, "the second run changed the file")
check("guard on, again: already current", (line or "").endswith("(already current)"), "line was %r" % line)
# Negative control, same file, the line dropped: forge's entry goes and the file is what it was.
line = run(p)
check("guard off after on: the file is what it was before", read(p) == original, "file was %r" % read(p))
check("guard off after on: the line says it was removed", "guard" in (line or "") and "removed" in (line or ""),
      "line was %r" % line)
line = run(p)
check("guard off, again: already current", (line or "").endswith("(already current)"), "line was %r" % line)

# A profile without the line gets no guard entry; `false` is the same as no line.
for label, extra in (("no line", {}), ("false", {"command_guard": False})):
    p = project({"permissions": {"allow": ["Edit"]}})
    run(p, **extra)
    check("guard %s: no entry and no hooks key" % label, hooks_of(p) is None, "hooks were %r" % hooks_of(p))
    p = project({"hooks": {"PreToolUse": [{"hooks": [HAND]}]}})
    run(p, **extra)
    check("guard %s: hand hook untouched" % label, hooks_of(p) == {"PreToolUse": [{"hooks": [HAND]}]}, "hooks were %r" % hooks_of(p))

# The name in --project is the profile's.
p = project()
run(p, command_guard=True, project="app")
check("guard on: --project is the profile's name", commands(json.loads(read(p)), "PreToolUse") == [canon("app")["command"]],
      "PreToolUse was %r" % commands(json.loads(read(p)), "PreToolUse"))

# Hand-written hooks beside it, in the same and in other events, survive in place; ours is appended.
mixed = {"PreToolUse": [{"matcher": "Bash", "hooks": [HAND]}], "PostToolUse": [TODOIST], "Stop": [{"hooks": [HAND]}]}
p = project({"hooks": copy.deepcopy(mixed)})
run(p, command_guard=True)
expect = copy.deepcopy(mixed)
expect["PreToolUse"].append({"hooks": [canon()]})
check("guard on beside hand hooks: theirs in place, ours appended", hooks_of(p) == expect, "hooks were %r" % hooks_of(p))
run(p)
check("guard off beside hand hooks: only ours goes", hooks_of(p) == mixed, "hooks were %r" % hooks_of(p))

# the hooked app's argument-less entry is replaced by the canonical one; a hand hook in its group stays.
p = project({"hooks": {"PreToolUse": [{"hooks": [LEGACY, HAND]}], "PostToolUse": [{"hooks": [LEGACY]}]}})
run(p, command_guard=True)
check("guard on over the legacy entry: PreToolUse is the hand hook, then the canonical",
      (hooks_of(p) or {}).get("PreToolUse") == [{"hooks": [HAND]}, {"hooks": [canon()]}],
      "PreToolUse was %r" % (hooks_of(p) or {}).get("PreToolUse"))
check("guard on over the legacy entry: another event's copy goes, and the event with it",
      "PostToolUse" not in (hooks_of(p) or {}), "hooks were %r" % hooks_of(p))

# Dropping the line removes a legacy entry the profile does not declare, and only that.
p = project({"hooks": {"PreToolUse": [{"hooks": [LEGACY, HAND]}]}})
run(p)
check("guard off over a legacy entry the profile does not declare: removed, the hand hook stays",
      hooks_of(p) == {"PreToolUse": [{"hooks": [HAND]}]}, "hooks were %r" % hooks_of(p))
# ...and one the profile's own `hooks` block declares stays (the hooked app until T4), as case 9 has it.
p = project({"hooks": {"PreToolUse": [{"hooks": [LEGACY, HAND]}]}})
run(p, DECLARED_LEGACY)
check("guard off, entry declared in the profile's hooks: kept in place",
      hooks_of(p) == {"PreToolUse": [{"hooks": [LEGACY, HAND]}]}, "hooks were %r" % hooks_of(p))
# A profile that does both is in conflict (a doctor FAIL, T3): forge still leaves exactly the canonical one.
p = project()
run(p, DECLARED_LEGACY, command_guard=True)
check("guard on and declared in hooks: exactly the canonical one",
      commands(json.loads(read(p)), "PreToolUse") == [canon()["command"]],
      "PreToolUse was %r" % commands(json.loads(read(p)), "PreToolUse"))

# A profile that declares nothing at all still owns the guard entry in its file.
p = project({"hooks": {"PreToolUse": [{"hooks": [LEGACY]}]}})
skills.write_settings_local(APPLY, {"project": "toy", "project_path": p})
check("no declaration, a guard entry in the file: removed", hooks_of(p) is None, "file was %r" % read(p))
p = project({"hooks": {"PreToolUse": [{"hooks": [HAND]}]}})
before = read(p)
line = skills.write_settings_local(APPLY, {"project": "toy", "project_path": p})
check("no declaration, no guard entry: nothing happens (None, file untouched)", line is None and read(p) == before,
      "line %r" % line)
# Only command_guard declared: written (it is a declaration, like hooks).
p = project()
run(p, permissions=None, command_guard=True)
check("only command_guard declared: written",
      os.path.exists(slp(p)) and commands(json.loads(read(p)), "PreToolUse") == [canon()["command"]],
      "no file, or no guard in it")

# Other copies of a guard are not forge's: a project's own under .claude/hooks, a relative path.
for label, other in (("a project's own copy", PORTAL_COPY), ("a relative path", RELATIVE)):
    for state, extra in (("on", {"command_guard": True}), ("off", {})):
        p = project({"hooks": {"PreToolUse": [{"hooks": [other]}]}})
        run(p, **extra)
        check("%s (%s): not removed" % (label, state), other["command"] in commands(json.loads(read(p)), "PreToolUse"),
              "PreToolUse was %r" % commands(json.loads(read(p)), "PreToolUse"))

# Two canonical entries (hand-duplicated) become one; a canonical one in another event goes.
p = project({"hooks": {"PreToolUse": [{"hooks": [canon()]}, {"hooks": [canon()]}], "PostToolUse": [{"hooks": [canon()]}]}})
run(p, command_guard=True)
check("guard on: duplicates collapse to the one in PreToolUse",
      hooks_of(p) == {"PreToolUse": [{"hooks": [canon()]}]}, "hooks were %r" % hooks_of(p))

# A dry run writes nothing.
p = project({"permissions": {"allow": ["Edit"]}})
before = read(p)
line = run(p, ctx=DRY, command_guard=True)
check("guard on, dry run: file untouched, says would write",
      read(p) == before and (line or "").lstrip().startswith("would write"), "line was %r" % line)

# A hand-corrupted file is left as it is, with the line saying so, and nothing raises.
for label, bad in (("hooks not an object", ["x"]), ("PreToolUse not a list", {"PreToolUse": "x"}),
                   ("a group null", {"PreToolUse": [None]})):
    p = project({"hooks": bad})
    line, err = None, None
    try:
        line = run(p, command_guard=True)
    except Exception as e:  # noqa: BLE001
        err = "%s: %s" % (type(e).__name__, e)
    check("guard on, %s: does not raise" % label, err is None, err or "")
    if err:
        continue
    check("guard on, %s: left as it is" % label, hooks_of(p) == bad, "hooks were %r" % hooks_of(p))
    check("guard on, %s: the line says not merged" % label, "guard not merged" in (line or ""), "line was %r" % line)

# 11. `worktree_guard` (W2 of research/21-para-forge/04-guarda-de-worktrees.md): the same ownership
#     as the command guard, through one table of two rows. Its canonical entry is a PreToolUse group
#     WITH the matcher, so a group running the right command behind another matcher (Bash
#     unguarded) is not the canonical one. `true` or an object turns it on; an object's
#     `"on": false` declares the parameters with the guard off (forge's own profile).
WT_PY = os.path.join(lib.ROOT, "hooks", "worktree_guard.py")
WT_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|Bash"


def wt_canon(name="toy"):
    return {"matcher": WT_MATCHER,
            "hooks": [{"type": "command", "command": "python3 %s --project %s" % (WT_PY, name), "timeout": 10}]}


WT_PARAMS = {"write_roots": [{"path": "~/notes", "why": "w"}], "worktree_dirs": [{"path": "/x", "why": "w"}]}
for label, value in (("true", True), ("an object", WT_PARAMS), ("an object with on true", dict(WT_PARAMS, on=True))):
    p = project({"permissions": {"allow": ["Edit"]}})
    run(p)
    original = read(p)
    line = run(p, worktree_guard=copy.deepcopy(value))
    check("worktree guard %s: exactly the canonical group, matcher and all" % label,
          hooks_of(p) == {"PreToolUse": [wt_canon()]}, "hooks were %r" % hooks_of(p))
    check("worktree guard %s: the line says so" % label, ", worktree guard on" in (line or ""), "line was %r" % line)
    first = read(p)
    line = run(p, worktree_guard=copy.deepcopy(value))
    check("worktree guard %s, again: byte-identical and already current" % label,
          read(p) == first and (line or "").endswith("(already current)"), "line was %r" % line)
    line = run(p)
    check("worktree guard %s, then no line: the file is what it was" % label, read(p) == original, "file was %r" % read(p))
    check("worktree guard %s, then no line: the line says removed" % label,
          ", worktree guard entries removed 1" in (line or ""), "line was %r" % line)

for label, value in (("false", False), ("on false, parameters declared", dict(WT_PARAMS, on=False))):
    p = project({"hooks": {"PreToolUse": [wt_canon()]}})
    line = run(p, worktree_guard=copy.deepcopy(value))
    check("worktree guard %s: no entry, the stale one removed" % label, hooks_of(p) is None, "hooks were %r" % hooks_of(p))
    check("worktree guard %s: the line does not say on" % label, "worktree guard on" not in (line or ""), "line was %r" % line)

# Both guards on: the command guard's entry first, untouched in shape, the worktree guard's after it.
p = project()
line = run(p, command_guard=True, worktree_guard=True)
check("both guards: the two canonical groups, command guard first",
      (hooks_of(p) or {}).get("PreToolUse") == [{"hooks": [canon()]}, wt_canon()], "PreToolUse was %r" % (hooks_of(p) or {}).get("PreToolUse"))
check("both guards: the line names both", ", command guard on, worktree guard on" in (line or ""), "line was %r" % line)
line = run(p, command_guard=True)
check("both, then the worktree guard off: the command guard's entry stays alone",
      hooks_of(p) == {"PreToolUse": [{"hooks": [canon()]}]}, "hooks were %r" % hooks_of(p))

# The right command behind the wrong matcher, or none, is not the canonical entry: replaced. A copy
# in another event goes; a hand hook in the same group stays.
for label, group in (("matcher Write", {"matcher": "Write", "hooks": [wt_canon()["hooks"][0], HAND]}),
                     ("no matcher", {"hooks": [wt_canon()["hooks"][0], HAND]})):
    p = project({"hooks": {"PreToolUse": [group], "PostToolUse": [wt_canon()]}})
    run(p, worktree_guard=True)
    check("worktree guard on over the command behind %s: replaced by the canonical group" % label,
          hooks_of(p) == {"PreToolUse": [dict(group, hooks=[HAND]), wt_canon()]}, "hooks were %r" % hooks_of(p))

# A profile that declares nothing still owns a worktree guard entry in its file.
p = project({"hooks": {"PreToolUse": [wt_canon(), {"hooks": [HAND]}]}})
skills.write_settings_local(APPLY, {"project": "toy", "project_path": p})
check("no declaration, a worktree guard entry in the file: removed, the hand hook stays",
      hooks_of(p) == {"PreToolUse": [{"hooks": [HAND]}]}, "hooks were %r" % hooks_of(p))
# Only worktree_guard declared: written.
p = project()
run(p, permissions=None, worktree_guard=True)
check("only worktree_guard declared: written", os.path.exists(slp(p)) and hooks_of(p) == {"PreToolUse": [wt_canon()]},
      "no file, or not the canonical group")
# A frozen project's own copy and a relative path are not forge's.
for label, other in (("a frozen project's copy", "python3 /somewhere/frozen-app/.claude/hooks/worktree_guard.py"),
                     ("a relative path", "python3 hooks/worktree_guard.py")):
    for state, extra in (("on", {"worktree_guard": True}), ("off", {})):
        p = project({"hooks": {"PreToolUse": [{"matcher": WT_MATCHER, "hooks": [{"type": "command", "command": other}]}]}})
        run(p, **extra)
        check("%s (worktree guard %s): not removed" % (label, state), other in commands(json.loads(read(p)), "PreToolUse"),
              "PreToolUse was %r" % commands(json.loads(read(p)), "PreToolUse"))
# A dry run writes nothing.
p = project({"permissions": {"allow": ["Edit"]}})
before = read(p)
line = run(p, ctx=DRY, worktree_guard=True)
check("worktree guard on, dry run: file untouched, says would write",
      read(p) == before and (line or "").lstrip().startswith("would write"), "line was %r" % line)
# A hand-corrupted PreToolUse is left as it is, and the line says so.
p = project({"hooks": {"PreToolUse": "x"}})
line = run(p, worktree_guard=True)
check("worktree guard on, PreToolUse not a list: left alone, said",
      hooks_of(p) == {"PreToolUse": "x"} and "worktree guard not merged" in (line or ""), "line was %r" % line)

# The field's type: a boolean or an object, nothing else (lib.profile_error, which every generator
# runs before reading a profile).
for label, value, expected in (("true", True, None), ("an object", {}, None), ("1", 1, "worktree_guard is not a JSON object or a boolean"),
                               ("a string", "x", "worktree_guard is not a JSON object or a boolean"),
                               ("null", None, "worktree_guard is not a JSON object or a boolean"),
                               ("a list", [], "worktree_guard is not a JSON object or a boolean")):
    got = lib.profile_error({"project": "toy", "worktree_guard": value})
    check("profile_error(worktree_guard %s)" % label, got == expected, "got %r, want %r" % (got, expected))
# Which profiles turn it on: one predicate, read by skills.py and cli.py.
on_of = getattr(lib, "worktree_guard_on", lambda prof: "missing")
for value, expected in ((True, True), (False, False), (None, False), ({}, True), ({"on": True}, True),
                        ({"on": False, "worktree_dirs": []}, False)):
    prof = {} if value is None else {"worktree_guard": value}
    check("worktree_guard_on(%r)" % (value,), on_of(prof) is expected, "got %r" % (on_of(prof),))

sandbox.cleanup(bool(failures))
if failures:
    print("%d of %d checks failed" % (len(failures), n_cases))
    sys.exit(1)
print("ok: %d checks over %d toy projects" % (n_cases, n_proj))
