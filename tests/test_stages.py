#!/usr/bin/env python3
"""data/stages.json, its validator, core.stages and `fwx stage`.

The table is checked against transitions listed by hand in this file (the allowed ones) and against the cartesian
product of every stage pair of a machine (everything else is forbidden), the shape of marshal's stages-regressions.ts.
The wiring goes through `bin/fwx stage` on a toy repo; the rows are read back with state.read_rows.

Seen red before the code existed (lib/fwx/core/stages.py and data/stages.json absent; the test stops at the import):
  FAIL: cannot import fwx.core.stages: No module named 'fwx.core'

Controls, each seen red on a copy of the repo with one thing changed (351 checks on the good code; first FAIL line shown):
  - `allowed` always says yes (250 failed):
      FAIL: session: cancelled -> cancelled is forbidden: got True
  - `advance` writes the stage it leaves, not the one it goes to (10 failed):
      FAIL: read back with state.last_stage: got 'discuss', want 'premortem'
  - `advance` writes the row before it checks the table (10 failed):
      FAIL: one row: got 2, want 1
  - a nested subphase starts in discuss (3 failed):
      FAIL: a nested subphase with no rows starts in executing: got 'discuss', want 'executing'
      FAIL: legal advance ('reviewing',): discuss -> reviewing is not in data/stages.json (session)
  - `current` decides by the NN.M name alone, not by the parent (2 failed):
      FAIL: a NN.M folder directly under phases/ starts in discuss: got 'executing', want 'discuss'
  - the machine is always `session` (6 failed):
      FAIL: a factory job starts in claimed: got 'discuss', want 'claimed'
  - `fwx stage` exits 0 on a refusal (1 failed):
      FAIL: discuss -> executing: exit 1: got 0, want 1
  - the table lets premortem go to executing (6 failed):
      FAIL: session: premortem -> executing is forbidden: got True
  - the table drops ui-walk -> discuss (1 failed):
      FAIL: session: ui-walk -> discuss is allowed: got False
  - the table lacks ui-walk -> executing (the walk's fixes go back to the executors; seen red on master, 1 failed):
      FAIL: session: ui-walk -> executing is allowed: got False
  - the table lacks executing -> phase-review (an executor's question goes to the owner's review of the part; seen red on master, 1 failed):
      FAIL: session: executing -> phase-review is allowed: got False
  - the validator returns no problem for anything (12 failed):
      FAIL: validator: a machine missing: wanted 'factory' in []
  - the validator does not look for unreachable stages (1 failed):
      FAIL: validator: a stage nobody reaches: wanted 'island' in []
  - the command names the audit file in its own source (1 failed):
      FAIL: outside state.py, lib/ never names the audit file: got ['lib/fwx/commands/stage.py'], want []
"""
import itertools
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx import state  # noqa: E402
    from fwx.core import stages  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.core.stages: %s" % e)
    sys.exit(1)

# ---- the allowed transitions, by hand ------------------------------------------------------------------------------

SESSION = {
    "discuss": ["premortem", "cancelled"],
    "premortem": ["planning", "discuss"],
    "planning": ["postmortem"],
    "postmortem": ["planning", "executing", "discuss"],
    "executing": ["reviewing", "phase-review"],
    "reviewing": ["executing", "ui-walk", "phase-review"],
    "ui-walk": ["phase-review", "discuss", "executing"],
    "phase-review": ["executing", "closed", "discuss"],
}
FACTORY = {
    "claimed": ["intake"],
    "intake": ["discuss", "needs-owner"],
    "discuss": ["premortem", "planning", "needs-owner"],
    "premortem": ["planning", "discuss"],
    "planning": ["postmortem"],
    "postmortem": ["planning", "executing", "discuss"],
    "executing": ["pr"],
    "pr": ["babysit"],
    "babysit": ["deciding", "executing"],
    "deciding": ["handover", "babysit"],
    "handover": ["done", "executing"],
    "failed": ["claimed"],
    "needs-owner": ["claimed"],
}
FAILURES = ["failed", "needs-owner"]
for _from in ("claimed", "intake", "discuss", "premortem", "planning", "postmortem", "executing", "pr", "babysit",
              "deciding", "handover"):  # from every stage that is not terminal and not itself a failure stage
    FACTORY[_from] = FACTORY[_from] + [t for t in FAILURES if t not in FACTORY[_from]]
STAGES = {"session": sorted(set(SESSION) | {t for v in SESSION.values() for t in v}),
          "factory": sorted(set(FACTORY) | {t for v in FACTORY.values() for t in v})}
HAND = {"session": SESSION, "factory": FACTORY}

table = stages.load()
s.eq("the machines", sorted(table), ["factory", "session"])
s.eq("session start and terminal", (table["session"]["start"], sorted(table["session"]["terminal"])),
     ("discuss", ["cancelled", "closed"]))
s.eq("factory start and terminal", (table["factory"]["start"], table["factory"]["terminal"]), ("claimed", ["done"]))

for machine in ("session", "factory"):
    allowed = {(a, b) for a, tos in HAND[machine].items() for b in tos}
    n_allowed = n_forbidden = 0
    for a, b in itertools.product(STAGES[machine], repeat=2):
        got = stages.allowed(machine, a, b)
        if (a, b) in allowed:
            n_allowed += 1
            s.ok("%s: %s -> %s is allowed" % (machine, a, b), got is True, "got %r" % (got,))
        else:
            n_forbidden += 1
            s.ok("%s: %s -> %s is forbidden" % (machine, a, b), got is False, "got %r" % (got,))
    s.eq("%s: looked at every listed transition" % machine, n_allowed, len(allowed))
    s.ok("%s: looked at forbidden pairs" % machine, n_forbidden > 20, "only %d" % n_forbidden)
s.ok("an unknown stage is not allowed", not stages.allowed("session", "discuss", "nope")
     and not stages.allowed("session", "nope", "discuss") and not stages.allowed("nomachine", "a", "b"))
s.ok("a terminal stage leads nowhere", not any(stages.allowed("session", t, x) for t in ("closed", "cancelled")
                                              for x in STAGES["session"]) and
     not any(stages.allowed("factory", "done", x) for x in STAGES["factory"]))

# ---- the validator -------------------------------------------------------------------------------------------------


def good():
    return json.loads(json.dumps({
        "session": {"start": "a", "terminal": ["c"], "transitions": {"a": ["b"], "b": ["c", "a"]}},
        "factory": {"start": "x", "terminal": ["z"], "transitions": {"x": ["y"], "y": ["z"]}}}))


s.eq("the shipped table has no problem", stages.validate(table), [])
s.eq("a small good table has no problem", stages.validate(good()), [])


def broken(label, mutate, want):
    t = good()
    mutate(t)
    problems = stages.validate(t)
    s.ok("validator: %s" % label, any(want in p for p in problems), "wanted %r in %r" % (want, problems))


broken("a machine missing", lambda t: t.pop("factory"), "factory")
broken("an unknown machine", lambda t: t.update(extra=t["session"]), "extra")
broken("no start", lambda t: t["session"].pop("start"), "start")
broken("a start that is no stage", lambda t: t["session"].update(start="ghost"), "ghost")
broken("a transition to a stage that has no row and is not terminal",
       lambda t: t["session"]["transitions"]["b"].append("dead"), "dead")
broken("a terminal stage that has transitions", lambda t: t["session"]["transitions"].update(c=["a"]), "terminal")
broken("a stage nobody reaches", lambda t: t["session"]["transitions"].update(island=["c"]), "island")
broken("a stage name the audit rows cannot carry", lambda t: t["session"]["transitions"]["b"].append("Bad Name"),
       "Bad Name")
broken("no terminal stage", lambda t: t["session"].update(terminal=[]), "terminal")
broken("a duplicated target", lambda t: t["session"]["transitions"].update(a=["b", "b"]), "twice")
broken("transitions that are not lists", lambda t: t["session"]["transitions"].update(a="b"), "list")
s.ok("validator: a table that is not an object", bool(stages.validate([])))

# ---- advance and current -------------------------------------------------------------------------------------------

repo = helpers.toy_repo()
head = helpers.git(repo, "rev-parse", "HEAD").strip()
phase = os.path.join(repo, ".fwx", "milestones", "v1", "phases", "01-x")
os.makedirs(phase)
s.eq("current of a new phase", stages.current(phase), "discuss")


def step(*args, **kw):
    """A legal advance: a refusal is a FAIL line, not a crash."""
    try:
        return stages.advance(*args, **kw)
    except state.StateError as e:
        s.ok("legal advance %s" % (args[1:],), False, str(e))


frm = step(phase, "premortem", "light critique", cwd=repo)
s.eq("advance returns the stage it left", frm, "discuss")
s.eq("read back with state.last_stage", state.last_stage(phase), "premortem")
rows = state.read_rows(state.phase_paths(phase)["audit"])
s.eq("one row", len(rows), 1)
s.eq("the row is a stage row at HEAD", (rows[0]["kind"], rows[0]["sha"]), ("stage", head))
s.eq("the row's detail is the target and the why", rows[0]["detail"], "premortem light critique")
s.eq("current follows the last row", stages.current(phase), "premortem")
try:
    stages.advance(phase, "executing", cwd=repo)
    s.ok("advance premortem -> executing is refused", False, "no error")
except state.StateError as e:
    s.eq("the refusal names both stages, the table and the machine", str(e),
         "premortem -> executing is not in data/stages.json (session)")
s.eq("a refused advance adds no row", len(state.read_rows(state.phase_paths(phase)["audit"])), 1)
s.eq("a refused advance leaves the stage", state.last_stage(phase), "premortem")
step(phase, "discuss", cwd=repo)  # no why: the detail is the stage alone
s.eq("advance without a why", state.read_rows(state.phase_paths(phase)["audit"])[-1]["detail"], "discuss")
try:
    stages.advance(os.path.join(repo, "nowhere"), "premortem", cwd=repo)
    s.ok("advance in a folder that is not there", False, "no error")
except state.StateError as e:
    s.ok("advance in a folder that is not there is refused, naming it", "nowhere" in str(e), str(e))

nested = os.path.join(phase.replace("01-x", "03-x"), "03.2-b")
os.makedirs(nested)
s.eq("a nested subphase with no rows starts in executing", stages.current(nested), "executing")
step(nested, "reviewing", cwd=repo)
s.eq("a nested subphase can go to reviewing", state.last_stage(nested), "reviewing")
direct = os.path.join(repo, ".fwx", "milestones", "v1", "phases", "02.5-x")
os.makedirs(direct)
s.eq("a NN.M folder directly under phases/ starts in discuss", stages.current(direct), "discuss")
try:
    stages.advance(direct, "reviewing", cwd=repo)
    s.ok("discuss -> reviewing in 02.5-x is refused", False, "no error")
except state.StateError as e:
    s.eq("the refusal", str(e), "discuss -> reviewing is not in data/stages.json (session)")

job = os.path.join(repo, ".fwx", "factory", "KEY-1")
os.makedirs(job)
s.eq("a factory job starts in claimed", stages.current(job), "claimed")
step(job, "intake", cwd=repo)
step(job, "failed", "tests", cwd=repo)
step(job, "claimed", "retry a2", cwd=repo)
s.eq("a factory job walks claimed, intake, failed, claimed", state.last_stage(job), "claimed")
try:
    stages.advance(job, "pr", cwd=repo)
    s.ok("claimed -> pr in a factory job is refused", False, "no error")
except state.StateError as e:
    s.eq("the refusal names the factory machine", str(e), "claimed -> pr is not in data/stages.json (factory)")

# ---- fwx stage -----------------------------------------------------------------------------------------------------

cli = os.path.join(repo, ".fwx", "milestones", "v1", "phases", "04-cli")
os.makedirs(cli)
r = helpers.fwx(repo, "stage", cli, "executing")
s.eq("discuss -> executing: exit 1", r.returncode, 1)
s.ok("discuss -> executing: the refusal on stderr", "discuss -> executing is not in data/stages.json (session)" in r.stderr,
     r.stderr)
s.eq("discuss -> executing: no row", state.read_rows(state.phase_paths(cli)["audit"]), [])
s.ok("discuss -> executing: no file made", not os.path.exists(state.phase_paths(cli)["audit"]))
r = helpers.fwx(repo, "stage", cli, "premortem", "--why", "first pass")
s.eq("discuss -> premortem: exit 0", (r.returncode, r.stderr), (0, ""))
s.ok("discuss -> premortem: says what it did", "discuss -> premortem" in r.stdout, r.stdout)
rows = state.read_rows(state.phase_paths(cli)["audit"])
s.eq("discuss -> premortem: the row", [(x["kind"], x["detail"], x["sha"]) for x in rows],
     [("stage", "premortem first pass", head)])
r = helpers.fwx(repo, "stage", cli)
s.eq("a missing stage is a usage error", r.returncode, 2)
r = helpers.fwx(repo, "stage", cli, "premortem", "--bogus")
s.eq("an unknown flag is a usage error", r.returncode, 2)
r = helpers.fwx(repo, "stage", os.path.join(repo, "nowhere"), "premortem")
s.eq("a folder that is not there: exit 2, not a refusal by the table", r.returncode, 2)
r = helpers.fwx(repo, "help")
s.ok("`fwx help` lists stage", any(line.split()[:1] == ["stage"] for line in r.stdout.splitlines()), r.stdout)

# ---- no one else writes the audit file -----------------------------------------------------------------------------

needle = "audit" + ".tsv"
hits, scanned = [], 0
for dirpath, _, files in os.walk(os.path.join(ROOT, "lib")):
    for f in files:
        p = os.path.join(dirpath, f)
        if f.endswith(".py") and os.path.relpath(p, os.path.join(ROOT, "lib")) != os.path.join("fwx", "state.py"):
            scanned += 1
            with open(p, encoding="utf-8") as fh:
                if needle in fh.read():
                    hits.append(os.path.relpath(p, ROOT))
s.ok("the scan looked at the python files of lib/", scanned > 5, "scanned %d" % scanned)
s.eq("outside state.py, lib/ never names the audit file", hits, [])

s.done()
