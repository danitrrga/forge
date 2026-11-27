#!/usr/bin/env python3
r"""`fwx wave report` (09.5 T51): lib/fwx/execute/report.py, lib/fwx/commands/wave.py, lib/fwx/routes.py.

One command judges an executor's report (a task's, a fixer's, a resolver's) and says what comes next: `merge` its branch,
`relaunch` it once (with the rejection note), `retry` (spend a round with `fwx wave fix`, start a new attempt with `last`),
`owner` or `stop`. It decides what execute.js decides at d348f8d (readExec, outsideProblem, waveScope, setupRecord and the
branching of job()), so every case below ends as the scenario of tests/test_execute_workflow.py named in its comment ends there:
status and reason recorded first. A miss is counted from the run's own files (`<n>-report.json`), never from the session's words.

Builds a toy repo (tests/test_wave_prepare.py `Scene`: a linked worktree on `phase`, the part's plan in `.fwx/`) and, for each
fake executor, a linked worktree on `worktree-agent-<unit>` born from `phase` that holds its commits and its
`.fwx-agent/<run>/<unit>/report.json`, and asks the command through `bin/fwx`. Nothing here reads the real HOME or configuration.

Seen red before the code existed (python3 tests/test_wave_report.py: `wave report` was no verb, `fwx wave` read it as the summary's
first word and exited 2 with its usage):
  FAIL: a good report: exit: got 2, want 0
  FAIL: a good report: stdout is JSON: got <not JSON: ''>, want an object

Controls: each case also runs on a copy of bin/ and lib/ with one line of the code changed (`MUTANTS` below, each `old` must be in
its file exactly once) and must fail with the text in `MUTANTS`; the good code passes first (238 checks with the controls). The first
FAIL line of each, seen red (cut at 120 characters):
  report read once, never relaunched:   FAIL: an unreadable first report relaunches the executor -> next stop: want next 'relaunch', got 'stop' ...
  no claimed-file rule:                 FAIL: a file another branch of the wave changed is a breach -> next merge: want next 'retry', got 'merge' ...
  rejection note dropped:               FAIL: outside shape (no fix): the relaunch note says the report was rejected, naming `fix`: ''
  miss count not ended by a new attempt: FAIL: a miss after a new attempt is a first miss again (relaunch, retry, relaunch, stop): got ['relaunch', 'retry', 'stop', 'stop'] ...
  misses of all units are one count:    FAIL: a miss is counted per unit: got ('relaunch', 'stop'), want ('relaunch', 'relaunch')
  status of the line not compared:      FAIL: an unreadable first report (a status that differs from the line) relaunches the executor -> next retry ...
  any path naming a report is read:     FAIL: an unreadable first report (the report of another unit) relaunches the executor -> next stop ...
  a path that climbs is read:           FAIL: an unreadable first report (a path that climbs out of a scratch folder) relaunches the executor -> next stop ...
  `done` with no branch merged:         FAIL: an unreadable first report (a `done` with no branch) relaunches the executor -> next merge ...
  `outside` shape not checked:          FAIL: a malformed `outside` (no fix) relaunches the executor -> next merge ...
  second rejection says `did not return`: FAIL: outside shape (no fix): the reason is the rejection, not `did not return`: 'executor did not return: T1'
  question sent to a new attempt:       FAIL: question asks the owner -> next retry: want next 'owner', got 'retry' ...
  setup record ignored:                 FAIL: a setup record in the worktree (session) -> next retry: want next 'owner', got 'retry' ...
  plane ignored:                        FAIL: a setup record in the worktree (factory) -> next owner: want next 'stop', got 'owner' ...
  second net off / case sensitive:      FAIL: no record, reason 'worktree setup failed: npm ci': the start of the reason is the second net -> next retry ...
  task beside it not a breach:          FAIL: a file of a task beside it is a breach -> next merge: want next 'retry', got 'merge' ...
  serial wave reads its diff:           FAIL: a serial wave reads no diff (its tasks declare the overlap) -> next retry: want next 'merge', got 'retry' ...
  renames followed:                     FAIL: a rename away from a task's file shows both paths, so it is a breach -> next merge ...
  unreadable diff passes:               FAIL: a branch whose diff cannot be read -> next merge: want next 'stop', got 'merge' ...
  a claim binds every wave:             FAIL: a claim of wave 1 binds nobody in wave 2 -> next retry: want next 'merge', got 'retry' ...
  a fixer judged against the plan:      FAIL: a fixer or resolver report (fix-1) is judged with no scope -> next None: want next 'merge', got None ({})
  any plane taken:                      FAIL: usage (a plane that is neither): exit 2 with the usage on stderr: got (0, False, '{"next": "relaunch", ...
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
import test_wave_prepare as wp  # noqa: E402
from test_wave_prepare import mutant_tree, runner  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
RUN = "01-alpha-abc1234-1"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
TASKS = [wp.task("T1", 1, ["src/a.py"]), wp.task("T2", 1, ["src/b.py"]), wp.task("T3", 2, ["src/c.py"]), wp.task("T4", 2, ["src/d.py"])]


def J(r):
    try:
        v = json.loads(r.stdout)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def item(where="src/z.py:7", size="small", issue="DTC-5", what="z drops the last row", fix="read to the end"):
    return {"where": where, "what": what, "fix": fix, "size": size, "issue": issue}


class World:
    """A toy repo with the part's plan (T1, T2 in wave 1; T3, T4 in wave 2), and the executors' worktrees."""

    def __init__(self, tasks=None, linear=True):
        project = {"checks": ["true"]}
        if linear:
            project["linear_project"] = "forge"
        self.S = wp.Scene(tasks=tasks if tasks is not None else TASKS, config={"project": project})
        self.dirs = {}

    def agent(self, unit, changes=None):
        """A worktree on `worktree-agent-<unit>` from `phase`, one commit for `changes` ({path: text, or None to delete}); its branch."""
        branch = "worktree-agent-" + unit
        wt = os.path.join(helpers.mkdtemp("fwx-agent-"), unit)
        helpers.git(self.S.repo, "worktree", "add", "-q", "-b", branch, wt, "phase")
        self.dirs[unit] = os.path.realpath(wt)
        for rel, text in (changes or {}).items():
            if text is None:
                os.remove(os.path.join(wt, rel))
            else:
                helpers.write(wt, rel, text)
        if changes:
            helpers.git(wt, "add", "-A")
            helpers.git(wt, "commit", "-q", "-m", "work\n\nFwx-Task: 01-alpha/%s\nFwx-Run: %s" % (unit, RUN))
        return branch

    def dir(self, unit):
        return self.dirs.setdefault(unit, helpers.mkdtemp("fwx-report-"))

    def write(self, unit, status="done", run=RUN, branch=None, **fields):
        rep = {"status": status, "branch": branch if branch is not None else "worktree-agent-" + unit, "worktree": self.dir(unit), "head": "abc",
               "commits": 2, "outside": [], "could_not_run": []}
        rep.update(fields)
        return helpers.write(os.path.join(self.dir(unit), ".fwx-agent", run, unit), "report.json", json.dumps(rep))

    def line(self, unit, status="done", run=RUN):
        return "%s %s commits=2" % (status, os.path.join(self.dir(unit), ".fwx-agent", run, unit, "report.json"))

    def say(self, R, unit, line, plane="session", run=RUN):
        r = R(self.S.cwd, "wave", "report", "--part-dir", self.S.part, "--run", run, "--unit", unit, "--line", line, "--plane", plane, env=dict(self.S.env, **IDENT))
        return r, J(r) or {}

    def judge(self, R, unit, status="done", plane="session", run=RUN, **fields):
        """Write the unit's report and judge it: (result, what it printed)."""
        self.write(unit, status, run, **fields)
        return self.say(R, unit, self.line(unit, status, run), plane, run)

    def files(self, run=RUN):
        d = os.path.join(self.S.repo, ".git", "fwx", "runs", run)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []


def nxt(S, label, v, want):
    """The case's check on `next`: the label names what is expected, and says what came instead."""
    return S.ok("%s -> next %s" % (label, v.get("next")), v.get("next") == want, "want next %r, got %r (%s)" % (want, v.get("next"), json.dumps(v)[:200]))


# ---------------------------------------------------------------------------------------------------- a good report

def case_good(R, S):
    """test_execute_workflow.py check_green: every executor `done`, its branch goes to integrate (status done)."""
    W = World()
    br = W.agent("T1", {"src/a.py": "a2\n"})
    r, v = W.judge(R, "T1", branch=br)
    S.eq("a good report: exit", (r.returncode, r.stderr.strip()[:200]), (0, ""))
    S.ok("a good report: stdout is JSON", bool(v), "got <not JSON: %r>, want an object" % r.stdout[:80])
    nxt(S, "a good report merges its branch", v, "merge")
    S.eq("a good report: the branch, no note, nothing to quote", (v.get("branch"), v.get("note"), v.get("last"), v.get("why")), (br, "", None, ""))
    S.eq("a good report: the call is one file of the run", W.files(), ["1-report.json"])
    try:
        rec = json.load(open(os.path.join(W.S.repo, ".git", "fwx", "runs", RUN, "1-report.json"), encoding="utf-8"))
    except OSError:
        rec = {}
    S.eq("a good report: the file keeps the step, the arguments and the result", (rec.get("step"), rec.get("exit"), (rec.get("args") or {}).get("unit"), (rec.get("result") or {}).get("next")),
         ("report", 0, "T1", "merge"))
    # a fixer, a resolver and a task alone in its wave have no scope: no diff is read, so a branch git does not have is no obstacle
    for unit in ("fix-1", "resolve-1", "T3-alone"):
        r, v = W.judge(R, unit, branch="no-such-branch")
        nxt(S, "a fixer or resolver report (%s) is judged with no scope" % unit, v, "merge")
    W2 = World(tasks=[wp.task("T1", 1, ["src/a.py"])])
    r, v = W2.judge(R, "T1", branch="no-such-branch")
    nxt(S, "a wave of one task reads no diff", v, "merge")
    # a report with no `outside` is read as none
    path = W.write("T2", run="r-absent", branch=W.agent("T2"))
    rep = json.load(open(path, encoding="utf-8"))
    del rep["outside"]
    helpers.write(os.path.dirname(path), "report.json", json.dumps(rep))
    r, v = W.say(R, "T2", W.line("T2", run="r-absent"), run="r-absent")
    nxt(S, "an absent `outside` is none", v, "merge")


# ---------------------------------------------------------------------------------------------------- a miss

MISS_LABELS = ["a line that is not a report", "an empty reply", "a report that is not there", "a report in the run folder under .git, where agents no longer write",
               "the report of another unit", "a path that climbs out of a scratch folder", "a report that is not JSON", "a report that is a list",
               "a status that differs from the line", "a `done` with no branch", "a `question` with no question"]


def miss_line(W, label, run):
    """The reply line of the report that is not one, `label` saying how, written for `run`; T1 is the unit."""
    folder = os.path.join(W.dir("T1"), ".fwx-agent", run, "T1")
    if label == "a line that is not a report":
        return "I finished the work"
    if label == "an empty reply":
        return ""
    if label == "a report that is not there":
        return "done /elsewhere/T1.json commits=2"
    if label.startswith("a report in the run folder"):
        return "done %s/.git/fwx/runs/%s/reports/T1.json commits=2" % (W.S.repo, run)
    if label == "the report of another unit":
        return "done %s commits=2" % W.write("T2", run=run)
    if label.startswith("a path that climbs"):
        # the report is there, at the end of a path that goes through a folder and back: only the `..` makes it a miss
        os.makedirs(os.path.join(W.dir("T1"), "x"), exist_ok=True)
        W.write("T1", run=run)
        return "done %s/x/../.fwx-agent/%s/T1/report.json commits=2" % (W.dir("T1"), run)
    if label == "a report that is not JSON":
        helpers.write(folder, "report.json", "{not json")
    elif label == "a report that is a list":
        helpers.write(folder, "report.json", "[1]")
    elif label == "a status that differs from the line":
        W.write("T1", "failed", run=run, reason="x")
        return W.line("T1", "done", run)
    elif label == "a `done` with no branch":
        W.write("T1", "done", run=run, branch="")
    else:
        W.write("T1", "question", run=run)
        return W.line("T1", "question", run)
    return "done %s commits=2" % os.path.join(folder, "report.json")


def case_misses(R, S):
    """check_executor_misses: a null, an empty string, a line that is no report, a report that is not there, one under .git, the report of
    another unit and a path that climbs out of its folder: each is relaunched once with no round spent, and a second miss of the same
    launch is a gap: status failed, reason `executor did not return: T1`."""
    W = World()
    r, v = W.say(R, "T1", "I finished the work", run="r-first")
    nxt(S, "an unreadable first report relaunches the executor", v, "relaunch")
    for i, label in enumerate(MISS_LABELS):
        run = "r-m%d" % i
        line = miss_line(W, label, run)
        r, v = W.say(R, "T1", line, run=run)
        nxt(S, "an unreadable first report (%s) relaunches the executor" % label, v, "relaunch")
        S.eq("a miss (%s): no note, no branch, exit 0" % label, (v.get("note"), v.get("branch"), r.returncode), ("", None, 0))
        r, v = W.say(R, "T1", line, run=run)
        nxt(S, "a second miss (%s) stops the run" % label, v, "stop")
        S.eq("a second miss (%s): the reason names the task" % label, v.get("why"), "executor did not return: T1")
    # the count is per unit: a miss of T2 is not the second miss of T1
    r, v1 = W.say(R, "T1", "nothing", run="r-units")
    r, v2 = W.say(R, "T2", "nothing", run="r-units")
    S.eq("a miss is counted per unit", (v1.get("next"), v2.get("next")), ("relaunch", "relaunch"))
    # and per launch: a miss, a failed attempt (a round, a new worktree), a miss again is a first miss
    run = "r-launch"
    steps = []
    steps.append(W.say(R, "T1", "nothing", run=run)[1].get("next"))
    steps.append(W.judge(R, "T1", "failed", run=run, reason="boom")[1].get("next"))
    steps.append(W.say(R, "T1", "nothing", run=run)[1].get("next"))
    steps.append(W.say(R, "T1", "nothing", run=run)[1].get("next"))
    S.eq("a miss after a new attempt is a first miss again (relaunch, retry, relaunch, stop)", steps, ["relaunch", "retry", "relaunch", "stop"])
    # a miss and then a good report: merge, and nothing is left against the next launch
    run = "r-recover"
    br = W.agent("T4")
    steps = [W.say(R, "T4", "nothing", run=run)[1].get("next"), W.judge(R, "T4", run=run, branch=br)[1].get("next")]
    S.eq("a miss, then a good report: relaunch, merge", steps, ["relaunch", "merge"])


# ---------------------------------------------------------------------------------------------------- outside

def case_outside(R, S):
    """check_outside (D13): an `outside` item has one shape; a report that lacks it is rejected whole, its agent is launched again and told why
    (the relaunch note), and a second rejection fails with the real reason, not `did not return`."""
    W = World()
    for u in ("T1", "T2", "T3", "T4"):
        W.agent(u)
    bad = {"no fix": ({k: v for k, v in item().items() if k != "fix"}, "fix"), "a size that is neither": (item(size="medium"), "size"),
           "no line in where": (item(where="src/z.py"), "where"), "an empty what": (item(what=" "), "what"),
           "an issue that is no key": (item(issue="the issue"), "issue"), "the old fixed field": (dict(item(), fixed=None), "fixed"),
           "not an object": ("src/z.py:7", "object"), "no issue, Linear on": (item(issue=None), "fwx linear new"),
           "an error with an empty text": (dict(item(issue=None), issue_error=" "), "issue_error"), "an error beside a key": (dict(item(), issue_error="x"), "issue_error"),
           "an error that is no text": (dict(item(issue=None), issue_error=3), "issue_error"), "an unknown field": (dict(item(), extra=1), "extra")}
    for i, (label, (it, word)) in enumerate(bad.items()):
        run = "r-o%d" % i
        r, v = W.judge(R, "T1", run=run, outside=[it])
        nxt(S, "a malformed `outside` (%s) relaunches the executor" % label, v, "relaunch")
        S.ok("outside shape (%s): the relaunch note says the report was rejected, naming `%s`" % (label, word), "rejected" in v.get("note", "") and word in v.get("note", ""), repr(v.get("note")))
        r, v = W.judge(R, "T1", run=run, outside=[it])
        nxt(S, "a second malformed `outside` (%s) stops the run" % label, v, "stop")
        S.ok("outside shape (%s): the reason is the rejection, not `did not return`" % label,
             v.get("why", "").startswith("executor T1 returned a report that was rejected: outside item 1:") and word in v.get("why", ""), repr(v.get("why")))
    # a rejection, then an unreadable report: the rejection is still the reason; an unreadable report, then a rejection: the rejection is
    r, v = W.judge(R, "T1", run="r-o-mix1", outside=[item(size="medium")])
    r, v = W.say(R, "T1", "nothing", run="r-o-mix1")
    S.ok("a rejection, then an unreadable report: stop with the rejection as the reason", v.get("next") == "stop" and "rejected" in v.get("why", "") and "size" in v.get("why", ""), json.dumps(v))
    r, v = W.say(R, "T1", "nothing", run="r-o-mix2")
    S.eq("an unreadable report first: no note", v.get("note"), "")
    r, v = W.judge(R, "T1", run="r-o-mix2", outside=[item(size="medium")])
    S.ok("an unreadable report, then a rejection: stop with the rejection as the reason", v.get("next") == "stop" and "size" in v.get("why", ""), json.dumps(v))
    # a rejection, then a good report: merge
    r, v = W.judge(R, "T2", run="r-o-ok", outside=[item(size="medium")])
    r, v = W.judge(R, "T2", run="r-o-ok", outside=[])
    nxt(S, "a rejection, then a good report", v, "merge")
    # accepted: a key filed, an error with `issue: null` (Linear unreachable), an item of either size
    unreachable = dict(item(issue=None), issue_error="fwx linear: Linear unreachable")
    for label, items in (("filed items", [item(), item(where="lib/q.py:2", size="large", issue="DTC-6")]), ("Linear unreachable", [unreachable]), ("none", [])):
        r, v = W.judge(R, "T3", run="r-oa-" + label.replace(" ", "-"), outside=items)
        nxt(S, "outside (%s) is accepted" % label, v, "merge")
    S.eq("a merge carries the report's `outside` for the part report", v.get("outside"), [])
    r, v = W.judge(R, "T4", run="r-oa-carry", outside=[unreachable])
    S.eq("a merge carries the report's `outside` for the part report: an item with no key", v.get("outside"), [unreachable])
    # with Linear off for the project a null issue is right
    W2 = World(linear=False)
    br = W2.agent("T1")
    r, v = W2.judge(R, "T1", outside=[item(issue=None)], branch=br)
    nxt(S, "outside (Linear off): a null issue is accepted", v, "merge")
    # the reason and the discarded attempt: a failed report with a bad item is still failed
    r, v = W.judge(R, "T2", "failed", run="r-o-failed", reason="boom", outside=[item(size="medium")])
    nxt(S, "a failed report with a malformed `outside` is rejected first", v, "relaunch")


# ---------------------------------------------------------------------------------------------------- failed, wrong-base, question

def case_branching(R, S):
    """check_executor_misses: `wrong-base` and `failed` spend a round and launch a new attempt told what the last one returned
    (job(): fixRound, then `prev = rep`); `question` ends the job needs-owner with the question; `done` is merged."""
    W = World()
    rep = {"reason": "wrong base: HEAD x, expected y"}
    r, v = W.judge(R, "T1", "wrong-base", **rep)
    nxt(S, "wrong-base spends a round and starts a new attempt", v, "retry")
    S.eq("wrong-base: why is the text of the round, last is the report", (v.get("why"), v.get("last", {}).get("reason"), v.get("last", {}).get("status"), v.get("branch")),
         ("T1 wrong-base: wrong base: HEAD x, expected y", "wrong base: HEAD x, expected y", "wrong-base", None))
    r, v = W.judge(R, "T2", "failed", reason="no test can fail")
    nxt(S, "failed spends a round and starts a new attempt", v, "retry")
    S.eq("failed: why", v.get("why"), "T2 failed: no test can fail")
    r, v = W.judge(R, "T3", "failed")
    S.eq("failed with no reason: why", v.get("why"), "T3 failed: no reason given")
    r, v = W.judge(R, "T4", "failed", reason="x\n  y " + "z" * 600)
    S.ok("failed: the text of the round is one line of at most 400 characters", len(v.get("why", "")) == 400 and "\n" not in v.get("why", ""), repr(v.get("why", ""))[:80])
    r, v = W.judge(R, "T1", "question", question="Which of the two APIs wins?")
    nxt(S, "question asks the owner", v, "owner")
    S.eq("question: the question is the reason, no branch", (v.get("why"), v.get("branch")), ("Which of the two APIs wins?", None))
    r, v = W.judge(R, "T2", "question", plane="factory", question="Which of the two APIs wins?")
    nxt(S, "question asks the owner on the factory's plane too (the job ends needs-owner)", v, "owner")


# ---------------------------------------------------------------------------------------------------- setup

def case_setup(R, S):
    """check_setup_failed: a setup that failed (exit 43 of `fwx base`) fails the same way in every new worktree: the job ends with its own line,
    no round, no new attempt; needs-owner on the session plane, failed (stop) on the factory's. The signal is the record `fwx base` leaves in the
    worktree; the start of the reason is only the second net."""
    line = "worktree setup failed: npm ci (exit 1, log /w/.fwx-agent/worktree-setup.log)"
    W = World()
    helpers.write(W.dir("T1"), ".fwx-agent/worktree-setup-failed.json", json.dumps({"setup_failed": line}))
    for plane, want in (("session", "owner"), ("factory", "stop")):
        r, v = W.judge(R, "T1", "failed", plane=plane, run="r-s-" + plane, reason="check-base exit 43")
        nxt(S, "a setup record in the worktree (%s)" % plane, v, want)
        S.eq("a setup record (%s): the line is the reason, there is nothing to quote" % plane, (v.get("why"), v.get("last")), (line, None))
    for i, (label, reason) in enumerate((("'Worktree setup failed: ...'", "Worktree setup failed: npm ci (exit 1)"), ("'npm could not install'", "npm could not install"))):
        r, v = W.judge(R, "T1", "failed", run="r-s-w%d" % i, reason=reason)
        nxt(S, "a setup record beats the words of the reason, reason %s" % label, v, "owner")
        S.eq("the record's line is the reason, reason %s" % label, v.get("why"), line)
    # the second net: no record, the reason starts with the phrase, any case, any padding
    W2 = World()
    for reason in ("worktree setup failed: npm ci", "Worktree Setup Failed: npm ci", "  worktree setup failed: npm ci"):
        r, v = W2.judge(R, "T1", "failed", run="r-n-" + str(len(reason)), reason=reason)
        nxt(S, "no record, reason %r: the start of the reason is the second net" % reason, v, "owner")
        S.eq("the second net: the line is the reason, one line of at most 600 characters", v.get("why"), reason.strip())
    r, v = W2.judge(R, "T1", "failed", plane="factory", run="r-n-f", reason="worktree setup failed: npm ci")
    nxt(S, "no record, the factory's plane", v, "stop")
    # a failure that is not the setup's: no record, another reason: a round, a new attempt
    r, v = W2.judge(R, "T2", "failed", run="r-n-x", reason="check-base exit 43: worktree setup failed: npm ci (exit 1)")
    nxt(S, "the phrase inside other words is an ordinary failure", v, "retry")
    helpers.write(W2.dir("T3"), ".fwx-agent/worktree-setup-failed.json", json.dumps({"setup_failed": " "}))
    r, v = W2.judge(R, "T3", "failed", run="r-n-e", reason="no test can fail")
    nxt(S, "an empty record is no record", v, "retry")
    helpers.write(W2.dir("T4"), ".fwx-agent/worktree-setup-failed.json", "not json")
    r, v = W2.judge(R, "T4", "failed", run="r-n-j", reason="no test can fail")
    nxt(S, "a record that is not JSON is no record", v, "retry")
    # only a failed report is read for a record: a done one is merged whatever the worktree holds
    helpers.write(W.dir("T2"), ".fwx-agent/worktree-setup-failed.json", json.dumps({"setup_failed": line}))
    r, v = W.judge(R, "T2", "done", run="r-s-done", branch=W.agent("T2"))
    nxt(S, "a done report is merged even when a record lies in its worktree", v, "merge")


# ---------------------------------------------------------------------------------------------------- scope

def case_scope(R, S):
    """check_outside, `outside scope`: what a branch changed is read from git, not from the report. A file that a task beside it lists (a file or
    a folder entry) and a file nobody lists that another branch of the wave already changed are a failed attempt: a round and a new attempt,
    told the file and the task. Paths are NUL-delimited and renames are not followed, so both sides of a rename count."""
    W = World()
    r, v = W.judge(R, "T1", run="r-sc1", branch=W.agent("a", {"src/a.py": "a2\n", "src/b.py": "b2\n"}))
    nxt(S, "a file of a task beside it is a breach", v, "retry")
    S.ok("a breach: the round text names the file, the task and the rule; the report to quote says failed",
         v.get("why", "").startswith("T1 failed: scope breach: ") and "src/b.py is a file of task T2" in v.get("why", "")
         and v.get("last", {}).get("status") == "failed" and v.get("last", {}).get("reason", "").startswith("scope breach: "), json.dumps(v)[:300])
    S.eq("a breach: no branch goes to the merge", v.get("branch"), None)
    r, v = W.judge(R, "T2", run="r-sc2", branch=W.agent("own", {"src/b.py": "b2\n", "lib/own-fix.py": "x\n"}))
    nxt(S, "a file of its own and a file nobody lists are fine", v, "merge")
    # folder entries, a name with a tab, a rename
    F = World(tasks=[wp.task("T1", 1, ["src/a.py"]), wp.task("T2", 1, ["src/auth"]), wp.task("T3", 1, ["src/slash/"]), wp.task("T4", 2, ["src/d.py"])])
    for i, (label, changes, word) in enumerate((("a folder entry covers the file", {"src/auth/x.py": "x\n"}, "src/auth/x.py"),
                                                ("a folder entry written with a slash", {"src/slash/x.py": "x\n"}, "src/slash/x.py"),
                                                ("a name with a tab under a folder entry", {"src/auth/we\tird.py": "x\n"}, "ird.py"))):
        r, v = F.judge(R, "T1", run="r-scf%d" % i, branch=F.agent("v%d" % i, changes))
        nxt(S, "scope (%s)" % label, v, "retry")
        S.ok("scope (%s): the file and the task that lists it" % label, word in v.get("why", "") and ("task T2" in v.get("why", "") or "task T3" in v.get("why", "")), v.get("why", ""))
    r, v = W.judge(R, "T1", run="r-sc-rename", branch=W.agent("mv", {"lib/b.py": "b\n", "src/b.py": None}))
    nxt(S, "a rename away from a task's file shows both paths, so it is a breach", v, "retry")
    S.ok("a rename: the file left behind is named", "src/b.py is a file of task T2" in v.get("why", ""), v.get("why", ""))
    # the same file twice: the first to return keeps it
    run = "r-tw"
    r, v = W.judge(R, "T1", run=run, branch=W.agent("t1", {"src/a.py": "a2\n", "lib/z.py": "1\n"}))
    nxt(S, "the first to return keeps a file nobody lists", v, "merge")
    S.eq("the merge says which files outside its own it claimed", v.get("claimed"), ["lib/z.py"])
    r, v = W.judge(R, "T2", run=run, branch=W.agent("t2", {"src/b.py": "b2\n", "lib/z.py": "2\n"}))
    nxt(S, "a file another branch of the wave changed is a breach", v, "retry")
    S.ok("the second to return is told the file is T1's now and to report its defect in `outside`",
         "lib/z.py was already changed by task T1" in v.get("why", "") and "`outside`" in v.get("why", ""), v.get("why", ""))
    r, v = W.judge(R, "T2", run=run, branch=W.agent("t2b", {"src/b.py": "b2\n"}))
    nxt(S, "its new attempt without the file is merged", v, "merge")
    r, v = W.judge(R, "T1", run=run, branch=W.agent("t1b", {"src/a.py": "a3\n", "lib/z.py": "3\n"}))
    nxt(S, "the task that claimed a file may change it again", v, "merge")
    # a claim is the wave's: the next wave starts from a later head, so wave 2 claims for itself
    r, v = W.judge(R, "T3", run=run, branch=W.agent("t3", {"src/c.py": "c2\n", "lib/z.py": "4\n"}))
    nxt(S, "a claim of wave 1 binds nobody in wave 2", v, "merge")
    r, v = W.judge(R, "T4", run=run, branch=W.agent("t4", {"src/d.py": "d2\n", "lib/z.py": "5\n"}))
    nxt(S, "the first to return in wave 2 keeps the file", v, "retry")
    S.ok("wave 2: the file is T3's", "lib/z.py was already changed by task T3" in v.get("why", ""), v.get("why", ""))
    # the claims are the run's own files: another run has none
    r, v = W.judge(R, "T2", run="r-other", branch=W.agent("o2", {"src/b.py": "b2\n", "lib/z.py": "6\n"}))
    nxt(S, "the claims of another run are no claim", v, "merge")
    # a breach claims nothing
    run = "r-nobreach"
    r, v = W.judge(R, "T1", run=run, branch=W.agent("nb1", {"src/a.py": "a2\n", "src/b.py": "b2\n", "lib/y.py": "1\n"}))
    nxt(S, "a breach (setup of the next check)", v, "retry")
    r, v = W.judge(R, "T2", run=run, branch=W.agent("nb2", {"src/b.py": "b2\n", "lib/y.py": "2\n"}))
    nxt(S, "a branch that was a breach claimed none of its files", v, "merge")
    # a serial wave declares its overlap: no diff is read
    Z = World(tasks=[wp.task("T1", 1, ["src/a.py"]), wp.task("T2", 1, ["src/a.py", "src/b.py"])])
    r, v = Z.judge(R, "T1", run="r-serial", branch=Z.agent("s1", {"src/b.py": "b2\n"}))
    nxt(S, "a serial wave reads no diff (its tasks declare the overlap)", v, "merge")
    # a diff that cannot be read leaves the scope unproven: the run stops
    r, v = W.judge(R, "T1", run="r-sc-bad", branch="no-such-branch")
    nxt(S, "a branch whose diff cannot be read", v, "stop")
    S.ok("an unproven scope names the task and the branch and says `unproven`", all(w in v.get("why", "") for w in ("T1", "no-such-branch", "unproven")), v.get("why", ""))
    # scope is judged only for a report that was read and is `done`
    r, v = W.judge(R, "T1", "failed", run="r-sc-failed", reason="boom", branch="no-such-branch")
    nxt(S, "a failed report reads no diff", v, "retry")


# ---------------------------------------------------------------------------------------------------- usage

def case_usage(R, S):
    W = World()
    base = ["wave", "report", "--part-dir", W.S.part, "--run", RUN, "--unit", "T1", "--line", "x", "--plane", "session"]

    def without(opt):
        a = list(base)
        i = a.index(opt)
        return a[:i] + a[i + 2:]
    cases = [("no --part-dir", without("--part-dir")), ("no --run", without("--run")), ("no --unit", without("--unit")), ("no --line", without("--line")),
             ("no --plane", without("--plane")), ("a plane that is neither", base[:-1] + ["both"]), ("a unit that is a path", base[:7] + ["../T1"] + base[8:]),
             ("an option nobody knows", base + ["--now"]), ("a stray word", base + ["T1"])]
    for label, argv in cases:
        r = R(W.S.cwd, *argv, env=dict(W.S.env, **IDENT))
        S.eq("usage (%s): exit 2 with the usage on stderr" % label, (r.returncode, "usage: fwx wave report" in r.stderr, r.stdout), (2, True, ""))
    S.eq("usage: nothing was written for a refused call", W.files(), [])
    r = R(W.S.cwd, *base, env=dict(W.S.env, **IDENT))
    S.eq("usage: the good call runs", r.returncode, 0)
    r = R(helpers.mkdtemp("fwx-nogit-"), *base, env=dict(W.S.env, **IDENT))
    S.eq("outside a repository: exit 2", r.returncode, 2)


def case_recorded(R, S):
    """`wave run` records each unit's worktree in state.json (`workers`, newest attempt last): the report is read from there, and the path the agent
    echoes is a hint (a worker that echoed `.claude/worktrees/x/.fwx-agent/...` or `.fwx-agent/...` relative to its own worktree had finished work
    counted as missing)."""
    W = World()
    br = W.agent("T1", {"src/a.py": "a2\n"})
    old = helpers.mkdtemp("fwx-old-")
    helpers.write(os.path.join(old, ".fwx-agent", RUN, "T1"), "report.json", json.dumps({"status": "failed", "reason": "boom"}))
    W.write("T1", branch=br)
    workers = {"T1/1": {"unit": "T1", "worktree": old}, "T1/2": {"unit": "T1", "worktree": W.dir("T1")}}
    helpers.write(os.path.join(W.S.repo, ".git", "fwx", "runs", RUN), "state.json", json.dumps({"workers": workers}))
    for label, path in (("no folder before .fwx-agent", ".fwx-agent/%s/T1/report.json" % RUN),
                        ("a relative folder", ".claude/worktrees/%s-T1/.fwx-agent/%s/T1/report.json" % (RUN, RUN))):
        r, v = W.say(R, "T1", "done %s commits=2" % path)
        nxt(S, "a recorded unit is read from its newest worktree, whatever path the line echoes (%s)" % label, v, "merge")
    r, v = W.say(R, "T1", "done %s commits=2" % os.path.join(old, ".fwx-agent", RUN, "T1", "report.json"))
    nxt(S, "the echoed path of an older attempt is not read", v, "merge")


CASES = [case_good, case_misses, case_outside, case_branching, case_setup, case_scope, case_usage, case_recorded]
R_ = "lib/fwx/execute/report.py"
W_ = "lib/fwx/commands/wave.py"
MUTANTS = [
    ("a report is read once and never relaunched", case_misses, R_, "    if n >= 1:\n", "    if True:\n",
     "an unreadable first report (a line that is not a report) relaunches the executor -> next stop"),
    ("no claimed-file rule", case_scope, R_, " and f in claimed and claimed[f] != unit:", " and False:",
     "a file another branch of the wave changed is a breach -> next merge"),
    ("the rejection note dropped", case_outside, R_, 'note = "\\nYour last report was rejected, so write it again: %s." % rejection if rejection else ""', 'note = ""',
     "the relaunch note says the report was rejected"),
    ("the miss count never ends at a new attempt", case_misses, R_, '        if res.get("next") != "relaunch":\n            break\n', '        if res.get("next") != "relaunch":\n            continue\n',
     "a miss after a new attempt is a first miss again"),
    ("the misses of every unit are one count", case_misses, R_, ' or (rec.get("args") or {}).get("unit") != unit:', ":",
     "a miss is counted per unit"),
    ("the status of the line not compared with the report", case_misses, R_, ' or rep.get("status") != m.group(1):', ":",
     "(a status that differs from the line) relaunches"),
    ("any path that names a report is read", case_misses, R_, 'if not ("/" + path).endswith(tail) or ".." in path.split("/"):', "if False:",
     "(the report of another unit) relaunches"),
    ("a path that climbs is read", case_misses, R_, ' or ".." in path.split("/"):', ":",
     "(a path that climbs out of a scratch folder) relaunches"),
    ("a `done` with no branch is merged", case_misses, R_, 'not (isinstance(rep.get("branch"), str) and rep["branch"])', "False",
     "(a `done` with no branch) relaunches"),
    ("a `question` with no question is asked", case_misses, R_, 'not _text(rep.get("question"))', "False",
     "(a `question` with no question) relaunches"),
    ("the `outside` shape is not checked", case_outside, R_, 'why = outside_problem(rep, "executor", linear)', "why = None",
     "a malformed `outside` (no fix) relaunches the executor -> next merge"),
    ("a second rejection says `did not return`", case_outside, R_, 'if rejection else "executor did not return: %s" % unit', 'if False else "executor did not return: %s" % unit',
     "the reason is the rejection, not `did not return`"),
    ("Linear is always off", case_outside, R_, 'linear = bool(config.load(top)["project"].get("linear_project"))', "linear = False",
     "no issue, Linear on) relaunches the executor -> next merge"),
    ("a question goes to a new attempt", case_branching, R_, 'return 0, _result("owner", why=rep["question"])', 'return 0, _result("retry", why=rep["question"])',
     "question asks the owner -> next retry"),
    ("a failure has no reason to give", case_branching, R_, 'rep.get("reason") or "no reason given"', 'rep.get("reason")',
     "failed with no reason: why"),
    ("the record of a failed setup ignored", case_setup, R_, 'if isinstance(rec, dict) and _text(rec.get("setup_failed")):', "if False:",
     "a setup record in the worktree (session) -> next retry"),
    ("the plane ignored: a failed setup always asks the owner", case_setup, R_, '_result("owner" if plane == "session" else "stop", why=setup)', '_result("owner", why=setup)',
     "a setup record in the worktree (factory) -> next owner"),
    ("the start of the reason is no second net", case_setup, R_, 'SETUP_FAILED.match(str(rep.get("reason")))', "False",
     "the start of the reason is the second net"),
    ("the second net is case sensitive", case_setup, R_, 're.compile(r"\\s*worktree setup failed:", re.I)', 're.compile(r"\\s*worktree setup failed:")',
     "no record, reason 'Worktree Setup Failed: npm ci'"),
    ("a file of a task beside it is no breach", case_scope, R_, "        if owner:\n", "        if False:\n",
     "a file of a task beside it is a breach -> next merge"),
    ("a serial wave reads its diff", case_scope, R_, 'if any(c["wave"] == task["wave"] for c in plan._clashes("plan.md", data)) or len(wave) < 2:', "if len(wave) < 2:",
     "a serial wave reads no diff"),
    ("renames are followed", case_scope, R_, '"--name-only", "--no-renames", "-z"', '"--name-only", "-z"',
     "a rename away from a task's file shows both paths, so it is a breach"),
    ("a diff that cannot be read passes", case_scope, R_, "    if r.returncode != 0:\n", "    if False:\n",
     "a branch whose diff cannot be read -> next merge"),
    ("a claim binds the tasks of every wave", case_scope, R_, 'ids = {t["id"] for t in wave}', 'ids = {t["id"] for t in tasks}',
     "a claim of wave 1 binds nobody in wave 2 -> next retry"),
    ("a fixer is judged against the plan", case_good, R_, "    if task is None:\n", "    if False:\n",
     "a fixer or resolver report (fix-1)"),
    ("any plane is taken", case_usage, W_, ' or parsed[0]["--plane"] not in ("session", "factory")', "",
     "usage (a plane that is neither)"),
]

if __name__ == "__main__":
    real = runner(ROOT)
    for case in CASES:
        case(real, s)
    for name, case, path, old, new, needle in MUTANTS:
        m = helpers.FirstFail(lambda f, needle=needle: needle in f)
        try:
            tree = mutant_tree(path, old, new)
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        m.run(case, runner(tree), m)
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
    s.done()
