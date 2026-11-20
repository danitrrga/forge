#!/usr/bin/env python3
"""The ledger of `outside` items and the stage guard: `fwx outside` and `fwx stage` (the owner's ownership rule, principles.md rule 12).

An agent that sees a defect outside its task either fixes it or reports it as an `outside` item
`{where: path:line, what, fix, size: small|large, fixed: <commit>|null}`. The ledger is `outside` rows of the part's `audit.tsv`
(`state.append_audit`, its one writer). `fwx outside add` validates the shape and checks `fixed` against git; `fwx outside route`
marks an item routed (a Linear issue key, or a fix task); `fwx stage` refuses to enter `reviewing`, `phase-review` or `closed`
while an item of the phase or of one of its subphases is neither fixed nor routed.

Red on master (no `fwx outside`, no `outside` audit kind, no guard in `stages.advance`); `fwx outside` is `fwx: unknown command: outside`,
and the first FAIL lines:
  FAIL: add a good item: exit: got 2, want 0
  FAIL: add a good item: the ids: got None, want ['O1']
  FAIL: a fixed item whose commit is on the branch: recorded fixed: got (2, None, None), want (0, ['O2'], [])
  FAIL: an open item: reviewing is refused: exit: got 0, want 1
  FAIL: an open item: phase-review is refused: exit: got 0, want 1
  FAIL: routed with an issue key: exit 0: got 2, want 0
  FAIL: an item added after the review: closed is refused: got 0, want 1
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()
repo = helpers.toy_repo()
head = helpers.git(repo, "rev-parse", "HEAD").strip()
phase = os.path.join(repo, ".fwx", "milestones", "v1", "phases", "01-x")
sub = os.path.join(phase, "01.1-a")
os.makedirs(sub)


def item(**kw):
    d = {"where": "src/a.py:12", "what": "the parser drops the last row", "fix": "read to the end of the file", "size": "large", "fixed": None}
    d.update(kw)
    return d


def add(items, folder=sub, run="r1"):
    return helpers.fwx(repo, "outside", "add", "--part-dir", folder, "--run", run, "--items", json.dumps(items))


def listed(folder=sub, *flags):
    r = helpers.fwx(repo, "outside", "--part-dir", folder, *flags)
    try:
        return r.returncode, json.loads(r.stdout)
    except ValueError:
        return r.returncode, None


def stage(to, folder=phase):
    return helpers.fwx(repo, "stage", folder, to)


for to in ("premortem", "planning", "postmortem", "executing"):
    r = stage(to)
    s.eq("the phase walks to %s" % to, r.returncode, 0)

# ---- the shape of an item: each way to lack it is exit 2 and nothing written -----------------------------------------
r = add([item()])
s.eq("add a good item: exit", r.returncode, 0)
try:
    out = json.loads(r.stdout)
except ValueError:
    out = {}
s.eq("add a good item: the ids", out.get("ids"), ["O1"])
bad = {
    "no fix": ({k: v for k, v in item().items() if k != "fix"}, "fix"),
    "an empty what": (item(what="  "), "what"),
    "a size that is neither small nor large": (item(size="medium"), "size"),
    "a where with no line": (item(where="src/a.py"), "where"),
    "a fixed that is no commit": (item(fixed="the fix"), "fixed"),
    "an extra key": (dict(item(), note="x"), "note"),
}
for label, (it, word) in bad.items():
    r = add([it])
    s.eq("shape, %s: exit 2" % label, r.returncode, 2)
    s.ok("shape, %s: the message names the field `%s`" % (label, word), word in r.stderr, r.stderr)
r = add([item(where="src/ok.py:1"), item(size="huge")])
s.eq("shape, a good item and a bad one: exit 2", r.returncode, 2)
code, doc = listed()
s.eq("shape: nothing of a refused batch was written (only O1 is there)", [i["id"] for i in (doc or {}).get("items", [])], ["O1"])
r = helpers.fwx(repo, "outside", "add", "--part-dir", sub, "--run", "r1", "--items", "not json")
s.eq("items that are no JSON: exit 2", r.returncode, 2)

# ---- fixed is checked against git, not taken on the agent's word ------------------------------------------------------
r = add([item(where="src/b.py:3", size="small", fixed=head)])
out = json.loads(r.stdout or "{}")
s.eq("a fixed item whose commit is on the branch: recorded fixed", (r.returncode, out.get("ids"), out.get("demoted")), (0, ["O2"], []))
r = add([item(where="src/c.py:4", size="small", fixed="deadbee")])
out = json.loads(r.stdout or "{}")
s.eq("a fixed item whose commit is not on the branch: recorded unfixed, and said so", (r.returncode, out.get("ids"), out.get("demoted")), (0, ["O3"], ["O3"]))
code, doc = listed()
by = {i["id"]: i for i in (doc or {}).get("items", [])}
s.eq("O2 is fixed by the commit", by.get("O2", {}).get("fixed"), head)
s.eq("O3 is not fixed", by.get("O3", {}).get("fixed"), None)
s.eq("open: O1 and O3, not the fixed O2", (doc or {}).get("open"), ["O1", "O3"])
code, doc = listed(sub, "--open")
s.eq("--open exits 1 while an item is open", code, 1)

# ---- the guard: no part reviews or closes with an item neither fixed nor routed ---------------------------------------
for to in ("reviewing", "phase-review"):
    r = stage(to)
    s.eq("an open item: %s is refused: exit" % to, r.returncode, 1)
    s.ok("an open item: %s refusal names the items and the command that routes them" % to,
         "O1" in r.stderr and "O3" in r.stderr and "fwx outside route" in r.stderr and "src/a.py:12" in r.stderr, repr(r.stderr))
def stage_rows():
    with open(os.path.join(phase, "audit.tsv"), encoding="utf-8") as f:
        return len([l for l in f.read().splitlines() if "\tstage\t" in l])


rows_before = stage_rows()
helpers.fwx(repo, "stage", phase, "reviewing")
s.eq("a refused stage wrote no row", stage_rows(), rows_before)

for bad_route, label in (((sub, "O9", "--issue", "DTC-12"), "an unknown id"), ((sub, "O1", "--issue", "nope"), "an issue key that is none"),
                         ((sub, "O1"), "neither --issue nor --task"), ((sub, "O1", "--issue", "DTC-1", "--task", "T"), "both")):
    r = helpers.fwx(repo, "outside", "route", "--part-dir", bad_route[0], *bad_route[1:])
    s.eq("route, %s: exit 2" % label, r.returncode, 2)
r = helpers.fwx(repo, "outside", "route", "--part-dir", sub, "O1", "--issue", "DTC-12")
s.eq("routed with an issue key: exit 0", r.returncode, 0)
r = stage("reviewing")
s.eq("one item still open (O3): reviewing is refused, naming only it", (r.returncode, "O3" in r.stderr and "O1" not in r.stderr), (1, True))
r = helpers.fwx(repo, "outside", "route", "--part-dir", sub, "O3", "--task", "r1-F4")
s.eq("routed to a fix task: exit 0", r.returncode, 0)
code, doc = listed(sub, "--open")
s.eq("nothing open: --open exits 0", (code, (doc or {}).get("open")), (0, []))
by = {i["id"]: i for i in (doc or {}).get("items", [])}
s.eq("the routing is in the ledger", (by.get("O1", {}).get("routed"), by.get("O3", {}).get("routed")), ("issue:DTC-12", "task:r1-F4"))
r = stage("reviewing")
s.eq("routed and fixed: reviewing goes through", r.returncode, 0)

# ---- the close: an item added later, in a subphase, stops `closed` ---------------------------------------------------
r = stage("phase-review")
s.eq("reviewing -> phase-review with nothing open", r.returncode, 0)
add([item(where="src/d.py:9")], run="r2")
r = stage("closed")
s.eq("an item added after the review: closed is refused", r.returncode, 1)
s.ok("the refusal names it, found in the subphase from the phase folder", "O4" in r.stderr, r.stderr)
helpers.fwx(repo, "outside", "route", "--part-dir", sub, "O4", "--issue", "DTC-13")
r = stage("closed")
s.eq("routed: closed goes through", r.returncode, 0)

# ---- a folder with no ledger is not an error -------------------------------------------------------------------------
other = os.path.join(repo, ".fwx", "milestones", "v1", "phases", "02-y")
os.makedirs(other)
for to in ("premortem", "planning", "postmortem", "executing", "reviewing"):
    r = stage(to, other)
s.eq("a phase that never had an item walks to reviewing", r.returncode, 0)
code, doc = listed(other)
s.eq("an empty ledger lists nothing and exits 0", (code, doc), (0, {"items": [], "open": []}))

s.done()
