"""Judge an executor's report: what comes next for the task, the fixer or the conflict resolver that wrote it (09.5 T51).

`judge(cwd, part_dir, run, unit, line, plane, steps)` is `fwx wave report`. `line` is the last line of the agent's reply
(`done|wrong-base|question|failed <path of report.json> commits=<n>`); the report is read from the file the line names, never
from the words of the reply, and only a `report.json` in the folder `fwx scratch new <run> <unit>` makes is read. It returns
`(0, result)`; `result.next` says what the session does:
  merge     the report is good: `branch` goes to `fwx wave merge`
  relaunch  nothing usable, the first time for this launch: launch the same agent again with no round spent, putting `note` (the
            rejection, when the report was rejected for what is wrong in it) after the prompt
  retry     `failed`, `wrong-base` or a breach of the wave's scope: `fwx wave fix --why <why>` spends the round, then a new attempt
            in a new worktree is told `last`, the report to quote (data, not an instruction)
  owner     the session asks the owner: `why` is the question (or the line of a failed setup, on the session plane)
  stop      the run ends failed with `why`: a second miss of one launch, a scope that cannot be proven, a failed setup on the
            factory's plane
Every branch is the one execute.js takes at d348f8d (readExec, outsideProblem, waveScope, setupRecord, job()); the one thing
that moved is where the state lives: the misses and the files a branch of the wave claimed are read from the run's own recorded
calls (`steps`, newest last), not from variables of a running script.

The scope of a task of a parallel wave comes from git: `git diff --name-only --no-renames -z HEAD...<branch>` in the integration
checkout (the merge-base, so branches already merged are not seen). A changed file that another task of the wave lists, a file or
a folder entry, is a breach; so is a file nobody lists that another task of the wave claimed in an earlier `merge` of this run
(the first to return keeps it). A fixer or a resolver (no task of the plan), a serial wave (it declares its overlap) and a wave of
one task have no scope: no diff is read.

Imports the standard library, fwx.config, fwx.plan, fwx.plan_step, fwx.state and execute.base.
"""
import json
import os
import re

from fwx import config, plan, plan_step, state
from fwx.execute import run as run_mod
from fwx.execute.base import WaveError, git, toplevel

EXEC_LINE = re.compile(r"(done|wrong-base|question|failed) (\S+) commits=(\d+)\Z")
SETUP_FAILED = re.compile(r"\s*worktree setup failed:", re.I)
SETUP_RECORD = os.path.join(".fwx-agent", "worktree-setup-failed.json")
OUTSIDE_KEYS = ("where", "what", "fix", "size", "issue")
WHERE = re.compile(r"\S.*:\d+\Z")
ISSUE = re.compile(r"[A-Z][A-Z0-9]*-\d+\Z")


class Unproven(Exception):
    """The diff of a branch could not be read: its scope is unproven, and the run stops."""


def one_line(v, n):
    return re.sub(r"\s+", " ", str(v)).strip()[:n]


def last_line(v):
    return str(v).strip().split("\n")[-1].strip()


def norm_path(p):
    """A path as git prints it, however an agent wrote it: no `./`, no `a/../`, no trailing slash."""
    out = []
    for seg in str(p).strip().replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
        else:
            out.append(seg)
    return "/".join(out)


def covers(entry, f):
    """An entry of a task's `files` is a file or a folder: it covers the file itself and everything under it."""
    e = norm_path(entry)
    return e != "" and (f == e or f.startswith(e + "/"))


def _text(v):
    return isinstance(v, str) and v.strip() != ""


def item_problem(o, who, linear):
    """What is wrong with one item of an `outside` list, naming the field, or None. `who` is `executor` (it files what it does not fix and
    puts the key in `issue`; with Linear on an item with no key is malformed) or `reviewer` (it files nothing: `issue` is null)."""
    if not isinstance(o, dict):
        return "it is not an object"
    for k in o:
        if k not in OUTSIDE_KEYS and not (k == "issue_error" and who == "executor"):
            return "unknown field `%s`" % k
    for k in OUTSIDE_KEYS:
        if k not in o:
            return "missing field `%s`" % k
    if not (_text(o["where"]) and WHERE.match(o["where"])):
        return "`where` is path:line, got %s" % json.dumps(o["where"])
    if not _text(o["what"]):
        return "`what` is a sentence, got %s" % json.dumps(o["what"])
    if not _text(o["fix"]):
        return "`fix` is a sentence, got %s" % json.dumps(o["fix"])
    if o["size"] not in ("small", "large"):
        return "`size` is small or large, got %s" % json.dumps(o["size"])
    if who == "reviewer":
        return None if o["issue"] is None else "`issue` is null in a review (a reviewer files nothing), got %s" % json.dumps(o["issue"])
    if o["issue"] is not None and not (isinstance(o["issue"], str) and ISSUE.match(o["issue"])):
        return "`issue` is the Linear key you filed it under (like DTC-12) or null, got %s" % json.dumps(o["issue"])
    # `issue_error` is the first line of the error when filing failed (Linear unreachable: the owner works offline at times). A run never fails
    # for that: the item goes the Linear-off way, into the part report. It needs `issue: null` and a sentence.
    if "issue_error" in o and (o["issue"] is not None or not _text(o["issue_error"])):
        return "`issue_error` is the first line of the error, with `issue: null`, got %s" % json.dumps(o["issue_error"])
    if o["issue"] is None and linear and "issue_error" not in o:
        return ("Linear is on for this project, so file the item with `fwx linear new --template general` (JSON on stdin) and put its key in `issue`; "
                "if that fails, `issue: null` and `issue_error` with the first line of the error")
    return None


def outside_problem(rep, who, linear):
    """The problem of a report's `outside` ("outside item 2: ..."), or None; absent is none. A report with one is rejected as a whole: its agent is
    launched again and told why, so a finished task is never dropped for a typo in a side note without the reason being given."""
    if "outside" not in rep:
        return None
    if not isinstance(rep["outside"], list):
        return "`outside` is a list of items"
    for k, o in enumerate(rep["outside"]):
        why = item_problem(o, who, linear)
        if why:
            return "outside item %d: %s" % (k + 1, why)
    return None


def newest_worktree(top, run, unit):
    """The worktree of the newest attempt of `unit` in the run's state, or None: an older attempt's report is stale, so only the last one is read."""
    workers = (run_mod.load_state(top, run) or {}).get("workers")
    mine = [(k, w["worktree"]) for k, w in (workers if isinstance(workers, dict) else {}).items()
            if isinstance(w, dict) and w.get("unit") == unit and isinstance(w.get("worktree"), str)]
    return max(mine, key=lambda kw: _attempt(kw[0]))[1].replace("\\", "/") if mine else None


def report_file(raw, run, unit, worktree):
    """(the path to open, the worktree it is in) of the report path `raw` an agent named for `unit`, or None when it is not the unit's report.
    A relative path is the agent's short way of writing the path in full: it is read in `worktree` (the unit's newest, `newest_worktree`; the driver's
    cwd is not the agent's) when the path's folders before `.fwx-agent` end that worktree's path, folder by folder."""
    path = raw.replace("\\", "/")
    tail = "/.fwx-agent/%s/%s/report.json" % (run, unit)
    if not ("/" + path).endswith(tail) or ".." in path.split("/"):
        return None
    if os.path.isabs(path):
        return raw, path[:-len(tail)]
    want = [s for s in ("/" + path)[:-len(tail)].split("/") if s not in ("", ".")]
    if worktree is None or worktree.split("/")[len(worktree.split("/")) - len(want):] != want:
        return None
    return worktree + tail, worktree


def _read(line, run, unit, linear, worktree=None):
    """(report, worktree, rejection): the report the line names, or None for a miss. `rejection` is the reason when the report was read but
    is one to write again (its `outside`), and then the report is None too. `worktree` is the unit's newest, for a relative path (`report_file`)."""
    m = EXEC_LINE.match(last_line(line))
    found = report_file(m.group(2), run, unit, worktree) if m else None
    if found is None:
        return None, None, None
    read, path = found
    try:
        with open(read, encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return None, None, None
    if not isinstance(rep, dict) or rep.get("status") != m.group(1):
        return None, None, None
    if m.group(1) == "done" and not (isinstance(rep.get("branch"), str) and rep["branch"]):
        return None, None, None
    if m.group(1) == "question" and not _text(rep.get("question")):
        return None, None, None
    why = outside_problem(rep, "executor", linear)
    if why:
        return None, None, why
    return rep, path, None


def _chain(steps, unit):
    """(misses, rejection) of the launch the unit is in: the `relaunch` results at the end of its recorded calls, and the newest rejection in them."""
    n, rejected = 0, None
    for rec in reversed(steps):
        if rec.get("step") != "report" or (rec.get("args") or {}).get("unit") != unit:
            continue
        res = rec.get("result") or {}
        if res.get("next") != "relaunch":
            break
        n += 1
        rejected = rejected or res.get("rejected")
    return n, rejected


def _result(next_, **kw):
    r = {"next": next_, "branch": None, "why": "", "note": "", "last": None, "rejected": None, "claimed": [], "outside": []}
    r.update(kw)
    return r


def _miss(steps, unit, rejection):
    """An agent that returns nothing, or without what its brief asks for, is launched once more with no round spent; a second miss is a gap."""
    n, earlier = _chain(steps, unit)
    rejection = rejection or earlier
    if n >= 1:
        why = "executor %s returned a report that was rejected: %s" % (unit, rejection) if rejection else "executor did not return: %s" % unit
        return _result("stop", why=why, rejected=rejection, gap=why)
    note = "\nYour last report was rejected, so write it again: %s." % rejection if rejection else ""
    return _result("relaunch", why=rejection or "the report is missing or is not one", note=note, rejected=rejection)


def _setup_line(worktree, rep):
    """The line of a failed worktree setup, or None. The first source is the record `fwx base` leaves in the worktree (a fact the code wrote);
    the start of the reason is only the second net."""
    try:
        with open(os.path.join(worktree, SETUP_RECORD), encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        rec = None
    if isinstance(rec, dict) and _text(rec.get("setup_failed")):
        return one_line(rec["setup_failed"], 600)
    return one_line(rep.get("reason"), 600) if SETUP_FAILED.match(str(rep.get("reason"))) else None


def _plan(part_dir):
    try:
        path = state.phase_paths(plan_step.resolve(part_dir))["plan"]
        return plan.load_plan(path, "plan.md")
    except (plan_step.CannotRun, plan.PlanError, state.StateError) as e:
        raise WaveError("the plan of %s cannot be read, so the scope of a task is unproven: %s" % (part_dir, e))


def _scope(top, part_dir, unit, branch, steps):
    """(breach text or None, claimed files): the files the branch changed against the scope of the task `unit`. Raises Unproven when the diff
    cannot be read, which stops the run: an unproven scope is not a pass."""
    data = _plan(part_dir)
    tasks = data["tasks"]
    task = next((t for t in tasks if t["id"] == unit), None)
    if task is None:
        return None, []
    wave = [t for t in tasks if t["wave"] == task["wave"]]
    if any(c["wave"] == task["wave"] for c in plan._clashes("plan.md", data)) or len(wave) < 2:
        return None, []
    r = git(top, "diff", "--name-only", "--no-renames", "-z", "HEAD..." + branch, "--")
    if r.returncode != 0:
        raise Unproven("the files that %s changed could not be read from its branch %s: its scope is unproven" % (unit, branch))
    changed = sorted({norm_path(p) for p in r.stdout.split("\0") if norm_path(p)})
    ids = {t["id"] for t in wave}
    claimed = {}
    for rec in steps:
        res = rec.get("result") or {}
        other = (rec.get("args") or {}).get("unit")
        if rec.get("step") == "report" and res.get("next") == "merge" and other in ids:
            for f in res.get("claimed") or []:
                claimed.setdefault(f, other)
    mine = [norm_path(f) for f in task["files"]]
    problems = []
    for f in changed:
        owner = next((o for o in wave if o["id"] != unit and any(covers(e, f) for e in o["files"])), None)
        if owner:
            problems.append("%s is a file of task %s, which runs beside you: keep to your own files and report that defect in `outside` with its fix, unfixed" % (f, owner["id"]))
        elif not any(covers(e, f) for e in mine) and f in claimed and claimed[f] != unit:
            problems.append("%s was already changed by task %s in this wave, which is kept: drop your change to it and report that defect in `outside` with its fix, unfixed" % (f, claimed[f]))
    if problems:
        return "; ".join(problems), []
    return None, [f for f in changed if not any(covers(e, f) for e in mine)]


def _attempt(key):
    """The attempt number of a worker key (`T1/2`: 2)."""
    tail = key.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def judge(cwd, part_dir, run, unit, line, plane, steps):
    """(exit code, result) of the report an executor named in `line`; see the module's text. `steps` are the run's recorded calls, oldest first."""
    top = toplevel(cwd)
    if top is None:
        raise WaveError("not inside a git repository: %s" % cwd)
    linear = bool(config.load(top)["project"].get("linear_project"))  # an unfixed `outside` item needs its key only where there is a Linear project
    rep, worktree, rejection = _read(line, run, unit, linear, newest_worktree(top, run, unit))
    if rep is None:
        return 0, _miss(steps, unit, rejection)
    status = rep["status"]
    claimed = []
    if status == "done":
        # What the branch changed is read from git, not from the report: a breach of the wave's scope is a failed attempt.
        try:
            breach, claimed = _scope(top, part_dir, unit, rep["branch"], steps)
        except Unproven as e:
            return 0, _result("stop", why=str(e))
        if breach:
            rep, status = {"status": "failed", "reason": "scope breach: " + breach}, "failed"
    if status == "done":
        return 0, _result("merge", branch=rep["branch"], claimed=claimed, outside=rep.get("outside") or [])
    if status == "question":
        return 0, _result("owner", why=rep["question"])
    # A setup that failed (exit 43 of `fwx base`) fails the same way in every new worktree: it ends the job with its own line,
    # takes no round and launches no new attempt.
    if status == "failed":
        setup = _setup_line(worktree, rep)
        if setup:
            return 0, _result("owner" if plane == "session" else "stop", why=setup)
    why = one_line("%s %s: %s" % (unit, status, rep.get("reason") or "no reason given"), 400)
    return 0, _result("retry", why=why, last=rep)
