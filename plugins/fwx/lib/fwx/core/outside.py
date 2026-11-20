"""The ledger of `outside` items: what an agent saw outside its task and did not fix, kept where the close can read it.

The ownership rule (playbooks/principles.md rule 12): an agent owns the result, not the brief, so a defect it sees is fixed or
reported with its fix, never left as a mention. An item has one shape, `{where: path:line, what, fix, size: small|large, fixed:
<commit>|null}` (`problems` says what is wrong with one), and a ledger entry adds the `id` the ledger gives it (`O1`, `O2`, ... in the part),
`routed` and `run`.

The ledger is the `outside` rows of a part's audit log, written only through `state.append_audit` (its one writer). A row's
detail is the item as JSON. The latest row of an id is its state: `add` writes the first, `route` writes the next with `routed` set. An
item is open while its `fixed` and its `routed` are both empty; `routed` is `issue:<KEY>` (a Linear issue, its id recorded) or `task:<id>`
(a fix task). `add` checks `fixed` against git: a commit that is not an ancestor of HEAD is not a fix of this branch, so the item is
recorded unfixed and said to be `demoted`.

`open_items(folder)` reads the folder and the subphases inside it: `stages.advance` calls it to refuse `reviewing`, `phase-review` and
`closed` while one is open, and `fwx decide` counts them as `review.open_outside`.

Imports the standard library and `state`.
"""
import json
import os
import re
import subprocess

from fwx import state

SIZES = ("small", "large")
KEYS = ("where", "what", "fix", "size", "fixed")
_WHERE = re.compile(r"\S.*:\d+\Z")
_COMMIT = re.compile(r"[0-9a-f]{7,40}\Z")
_ISSUE = re.compile(r"[A-Z][A-Z0-9]*-\d+\Z")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
GUARDED = ("reviewing", "phase-review", "closed")


def problems(item):
    """What is wrong with one item of an `outside` list, as texts that name the field; [] for a good one."""
    if not isinstance(item, dict):
        return ["an item is an object with %s, got %s" % (", ".join(KEYS), type(item).__name__)]
    found = ["unknown field `%s`" % k for k in item if k not in KEYS] + ["missing field `%s`" % k for k in KEYS if k not in item]
    if found:
        return found
    if not (isinstance(item["where"], str) and _WHERE.match(item["where"])):
        found.append("`where` is path:line, got %r" % (item["where"],))
    for k in ("what", "fix"):
        if not (isinstance(item[k], str) and item[k].strip()):
            found.append("`%s` is a sentence, got %r" % (k, item[k]))
    if item["size"] not in SIZES:
        found.append("`size` is small or large, got %r" % (item["size"],))
    if item["fixed"] is not None and not (isinstance(item["fixed"], str) and _COMMIT.match(item["fixed"])):
        found.append("`fixed` is a commit (7 to 40 hex digits) or null, got %r" % (item["fixed"],))
    return found


def _audit(folder):
    return state.phase_paths(folder)["audit"]


def _entries(folder):
    """{id: the latest state of that id} of one folder, in the order the ids first appeared."""
    found = {}
    for row in state.read_rows(_audit(folder)):
        if row.get("kind") != "outside":
            continue
        try:
            entry = json.loads(row.get("detail", ""))
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            found[entry["id"]] = entry
    return found


def items(folder):
    """The ledger of one folder: a list of entries, each `{id, where, what, fix, size, fixed, routed, run}`."""
    return list(_entries(folder).values())


def is_open(entry):
    return not entry.get("fixed") and not entry.get("routed")


def folders(folder):
    """The folder and the subphases inside it (a part's ledger is in its own folder, the phase is stage-checked as a whole)."""
    return [str(folder)] + [str(p) for p in state.subphases(folder)]


def open_items(folder):
    """[(folder, entry)] of every open item of the folder and its subphases."""
    return [(f, e) for f in folders(folder) for e in items(f) if is_open(e)]


def _reachable(cwd, commit):
    r = subprocess.run(["git", "-C", cwd, "merge-base", "--is-ancestor", commit, "HEAD"], capture_output=True, text=True)
    return r.returncode == 0


def add(folder, batch, run, cwd):
    """Record a batch of items, all or none: (ids, demoted ids). A `fixed` commit that is not an ancestor of HEAD in `cwd` is recorded
    as unfixed. Raises state.StateError with every problem when an item is malformed."""
    bad = ["item %d: %s" % (i + 1, p) for i, it in enumerate(batch) for p in problems(it)]
    if bad:
        raise state.StateError("; ".join(bad))
    n = len(_entries(folder))
    ids, demoted = [], []
    rows = []
    for it in batch:
        n += 1
        entry = dict(it, id="O%d" % n, routed=None, run=run)
        if entry["fixed"] and not _reachable(cwd, entry["fixed"]):
            entry["fixed"] = None
            demoted.append(entry["id"])
        ids.append(entry["id"])
        rows.append(entry)
    for entry in rows:  # nothing is written before every item passed
        state.append_audit(folder, "outside", detail=json.dumps(entry, sort_keys=True), rc="")
    return ids, demoted


def route(folder, item_id, issue=None, task=None):
    """Mark an item routed: to a Linear issue (`issue`, its key) or a fix task (`task`, its id). Returns the entry."""
    if (issue is None) == (task is None):
        raise state.StateError("route to an issue (--issue KEY) or to a fix task (--task ID), one of the two")
    if issue is not None and not _ISSUE.match(issue):
        raise state.StateError("%r is no Linear issue key (like DTC-12)" % (issue,))
    if task is not None and not _TASK.match(task):
        raise state.StateError("%r is no task id" % (task,))
    entry = _entries(folder).get(item_id)
    if entry is None:
        raise state.StateError("no item %s in %s" % (item_id, folder))
    entry = dict(entry, routed=("issue:" + issue) if issue is not None else ("task:" + task))
    state.append_audit(folder, "outside", detail=json.dumps(entry, sort_keys=True), rc="")
    return entry


def refusal(folder, to):
    """The text of the refusal when `to` is a stage the open items stop, else None."""
    if to not in GUARDED:
        return None
    open_ = open_items(folder)
    if not open_:
        return None
    named = ["%s%s %s (%s)" % (e["id"], "" if f == str(folder) else " in " + os.path.basename(f), e["where"], e["size"]) for f, e in open_[:5]]
    more = "" if len(open_) <= 5 else " and %d more" % (len(open_) - 5)
    return ("%d outside item%s neither fixed nor routed: %s%s. Fix each or route it: `fwx outside route <part folder> <id> --issue KEY` "
            "(a Linear issue) or `--task ID` (a fix task); `fwx outside --part-dir <part folder> --open` lists them"
            % (len(open_), " is" if len(open_) == 1 else "s are", "; ".join(named), more))
