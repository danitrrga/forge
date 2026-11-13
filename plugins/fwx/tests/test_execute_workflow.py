#!/usr/bin/env python3
"""workflows/execute.js through tests/workflow_stub.mjs (3.4 U5b): the waves, the join, the fix rounds, the review.

referent: none, the script is this repo's own control flow; its test is the stub's scenarios (tests/workflow_stub.mjs, 3.4 U5a).

No network and no real agent: every `agent()` answer is a line of a scenario, so a run is a sequence of launches and what the
script put in their prompts. Needs `node`; without it `NOT RUN, NOT ARMED`, exit 77.

Red before the script existed (python3 tests/test_execute_workflow.py, first lines; there was no workflows/ folder):
  FAIL: green: the script ran: rc 2, no record: workflow_stub: ENOENT: no such file or directory, open '.../workflows/execute.js'
  FAIL: green: status: got None, want 'done'
  FAIL: green: launch order: got [], want ['executor:runner-capacity', 'executor:T1', ...]

Controls: each behaviour is also run on a copy of workflows/execute.js with its branch taken out (`MUTANTS`; the anchor must
be in the script exactly once), and must go red with the text given. The first FAIL line of each, seen red:
  serial wave ignored:        FAIL: clash: the two executors never run at once: T1 3-5 overlaps T2 4-7
  a cap that is no number not refused: FAIL: cap missing: no executor launched: got ['executor:T1', 'executor:T2', 'executor:T3'], want []
  conflict to the plain fixer: FAIL: conflict: the resolver ran (conflict sent to the plain fixer): [...]
  a miss spends a round:      FAIL: executor null once: no round spent (fix-round called for a null): [...]
  second miss counted as done: FAIL: two nulls: failed: got 'done', want 'failed'
  unknown agentType retried:  FAIL: unknown agentType: not relaunched (unknown agentType retried): got 2, want 1
  verify rc 2 on one plane:   FAIL: verify rc 2 on the session plane (session plane returned failed for verify rc 2): got 'failed', want 'needs-owner'
  protected path is done:     FAIL: protected path (security needed: True): needs-owner, never done (protected path with security asked returned done): got ('done', '') ...
  security review skipped:    FAIL: protected path (security needed: False): the security reviewer ran (protected path skipped the security review)
  every real finding fixed:   FAIL: no fix verdict: no fixer, no round (note finding was fixed)
  the runner's rc decides:    FAIL: rc 1 with ok true: carries on (the exit code is not read): got ('failed', False), want ('done', False)
  catchable_by "maybe" in the schema: FAIL: verifier schema: catchable_by "maybe" is rejected: {'type': 'string', 'enum': [..., 'maybe']}
  finding ids not prefixed:   FAIL: fix: the fixer is given the finding under its unique id and not the one it was written with
  and 21 more rows of MUTANTS, each seen red with the text in its fourth column. A control run stops at the first FAIL it waits
  for (helpers.FirstFail: the rest of the run could only add FAILs the control does not read). A mutant that makes the script
  loop is cut off by the stub after 400 launches (exit 124); `run_capped` cuts a script that does not even launch
  after 25 s.

Red before 3.4 align (the gate's stage, the re-entry at the gate, the agents' wording; first lines of this file on the old script):
  FAIL: stage: the wave merge runs in executing, the gate (last wave's --final integrate) in reviewing (gate ran in executing): got ['executing', 'executing'], want ['executing', 'reviewing']
  FAIL: stage: a review fix is made in executing and gated and reviewed in reviewing (n_C9 to n_C8 to n_C5 to n_C7): got ('reviewing', 'reviewing', 'reviewing'), want ('executing', 'reviewing', 'reviewing')
  FAIL: from gate: the gate, then the review: done (a second run of finished tasks returned needs-owner): got ('needs-owner', 'every task of the part is already on the phase branch: there is nothing to execute'), want ('done', '')
  FAIL: agents: reviewer, security-reviewer and review-verifier say what the script does (agents/*.md vs workflows/execute.js): got ['reviewer: names a brief file, the script gives the brief in the prompt', ...
  and one MUTANTS row each for the stage of the gate, of the fix after a red gate, of a review fix, the re-entry and `--branches` left empty.

Red before the 3.4 U8 fix (the live acceptance found a two-wave plan failing `wrong-base` in wave 2, and an executor unable to write
its report under `.git` with `acceptEdits`); `check_wave_base` and `check_scratch` on the old script:
  FAIL: wave base: wave 2's T3 checks the head after wave 1's merge (the sha its worktree is born from), not prepare's (a two-wave plan ran wrong-base): got [], want ['h1']
  FAIL: wave base: a new attempt of a wave-2 task checks the same head: got [[], []], want [['h1'], ['h1']]
  FAIL: scratch: the resolver is given no path under .git and none in the old reports/ or tmp/ of the run (it wrote the report there, and was refused): You are the conflict resolver ...
  FAIL: executor a report in the run folder under .git, where agents no longer write once: relaunched once: got 1, want 2
  (the brief's side is in tests/test_wave_brief.py, `fwx scratch new` in tests/test_wave_prepare.py)
The live rerun then found a reviewer that wrote `report.json` in `tmp/` of its folder (the prompt said "in it" after naming `tmp/`);
the wording check above is "report.json directly in that folder, not in tmp/", red on the first wording:
  FAIL: scratch: the reviewer is told to run `fwx scratch new ... r1` and to use its tmp/ and report.json: ...
Controls added: a report outside a scratch folder, of another unit or with `..` in its path accepted; a later wave checking prepare's
base; a fixer told to write under .git again.

Settled here (3.4 U5b), and why each is in the script and not in a CLI:
  - finding ids repeat across rounds (a reviewer numbers F1, F2 each time, and `integrate --findings` and `revert` match by id):
    the script prefixes every finding with its review pass, `r1-F1`, `r2-F1`, before it goes to the verifier, the fixer or
    `integrate --findings`, so an id is unique in a run and the agents, `integrate` and `revert` stay as they are;
  - a relaunch after `failed` or `wrong-base` and the conflict resolver have no brief file: their prompt is a brief of its own;
  - `met` of a criterion is `yes|no|unproven`: only `no` is a finding, and a `no` no finding names is a report that lacks
    what it was asked for (relaunched once).
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
SCRIPT = os.path.join(ROOT, "workflows", "execute.js")
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "execute")
RUN_DIR = "/work/.git/fwx/runs/01-toy-ab12cd3-1"
HEAD0 = "ab12cd34ab12cd34ab12cd34ab12cd34ab12cd34"


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


# ---- answers --------------------------------------------------------------------------------------------------------
def R(obj, rc=0):
    """What a runner returns: the stdout of the command and its exit code."""
    return {"stdout": obj if isinstance(obj, str) else json.dumps(obj), "rc": rc}


def integ(head, merged, ok=True, **kw):
    d = {"ok": ok, "head": head, "merged": merged, "conflict": None, "locked": [], "findings_check": {"ok": True, "problems": []},
         "quick": {"ran": True, "cmds": ["t"], "rc": 0}, "verify": {"ran": False, "rc": None, "line": ""}, "trusted": [], "protected": []}
    d.update(kw)
    return R(d, 0 if ok else 1)


def final(head, merged, rc=0, **kw):
    v = {"ran": True, "rc": rc, "line": "evidence %s t=%d" % (head, rc)}
    return integ(head, merged, ok=rc == 0, verify=v, **kw)


def report_at(unit):
    """Where an agent's report is: in the folder `fwx scratch new RUN UNIT` made in its own worktree, never under .git."""
    return "/work/wt-%s/.fwx-agent/%s/%s/report.json" % (unit, os.path.basename(RUN_DIR), unit)


def exec_line(tid, status="done", n=2):
    return "%s %s commits=%d" % (status, report_at(tid), n)


def exec_report(branch, status="done", **kw):
    d = {"status": status, "branch": branch, "worktree": "/w/" + branch, "head": "h-" + branch, "commits": 2, "outside": [], "could_not_run": []}
    d.update(kw)
    return R(d)


def review_line(tag, role="reviewer", looked=2, findings=0, no=0, unproven=0):
    return "reviewed %s looked_at=%d findings=%d criteria_no=%d criteria_unproven=%d" % (
        report_at(tag if role == "reviewer" else tag + "-sec"), looked, findings, no, unproven)


def crit(c1="yes", c2="yes"):
    return [{"id": "C1", "met": c1, "evidence": "ran the measure of C1"}, {"id": "C2", "met": c2, "evidence": "ran the measure of C2"}]


def review_report(findings=(), criteria=None, looked=("a.py", "b.py")):
    return R({"looked_at": list(looked), "findings": list(findings), "criteria": crit() if criteria is None else criteria})


def finding(i, severity="medium", file="a.py", claim=None):
    return {"id": i, "file": file, "line": 3, "claim": claim or "claim of " + i, "evidence": "evidence of " + i, "severity": severity}


def verdicts(*rows):
    return {"verdicts": [{"id": i, "verdict": v, "severity": sev, "reason": "because " + i, **({"catchable_by": c} if c else {})}
                         for i, v, sev, c in rows]}


CLEAN_CLEANUP = R({"removed": ["wt-t1", "wt-t2", "wt-t3"], "kept": [], "leftover": []})


def green():
    """The answers of a run in which nothing goes wrong: wave 1 (T1, T2), wave 2 (T3, the last), a clean review."""
    return {
        "executor:T1": exec_line("T1"), "executor:runner-report-T1": exec_report("wt-t1"),
        "executor:T2": exec_line("T2"), "executor:runner-report-T2": exec_report("wt-t2"),
        "executor:T3": exec_line("T3"), "executor:runner-report-T3": exec_report("wt-t3"),
        "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"])]},
        "reviewer:r1": review_line("r1"), "executor:runner-report-r1": review_report(),
        "executor:runner-cleanup": CLEAN_CLEANUP,
        # what the runner finds when it looks for a failed setup's record in the worktree of a job that reported `failed`: none
        **{"executor:runner-setup-" + u: R("", 1) for u in ("T1", "T2", "T3", "fix-1", "fix-2", "fix-3", "resolve-1", "resolve-2")},
    }


def go(script, args_over=None, answers_over=None, base=None, allow_unanswered=False):
    """(record, error text) for one run; `args_over` is a dict merged in or a function that edits the args, `answers_over` a dict."""
    args = fixture("args.json")
    if callable(args_over):
        args_over(args)
    elif args_over:
        args.update(args_over)
    answers = base if base is not None else green()
    answers.update(answers_over or {})
    rc, rec, err = run_capped(script, {"args": args, "answers": answers})
    return rec, "rc %s, no record: %s" % (rc, err[-300:]) if rec is None else ""


def run_capped(script, scenario, seconds=25):
    """run_workflow, but a script that never ends (a mutant that loops on a scenario that always answers) is killed after
    `seconds`: the stub writes its record at every launch, so what ran is still there, with a note in its error."""
    work = helpers.mkdtemp("fwx-exrun-")
    try:
        sc, out = os.path.join(work, "scenario.json"), os.path.join(work, "record.json")
        with open(sc, "w", encoding="utf-8") as f:
            json.dump(scenario, f)
        try:
            r = subprocess.run(["node", os.path.join(ROOT, "tests", "workflow_stub.mjs"), script, sc, out], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=seconds)
            rc, err = r.returncode, r.stderr.strip()
        except subprocess.TimeoutExpired:
            rc, err = 124, "killed after %d s: the script did not end" % seconds
        rec = None
        if os.path.exists(out):
            try:
                with open(out, encoding="utf-8") as f:
                    rec = json.load(f)
            except ValueError:  # killed in the middle of a write
                rec, err = None, err + " (the record was cut off)"
            if rec is not None and rc == 124:
                rec["error"] = rec.get("error") or {"message": err, "stage": "run"}
    finally:
        helpers.remove(work)  # hundreds of runs per suite: not all of them in /tmp at once
    return rc, rec, err


# ---- reading a record -----------------------------------------------------------------------------------------------
def labels(rec):
    return [l["label"] for l in rec["launches"]]


def last(rec):
    return (labels(rec) or [None])[-1]


def pos(rec, label):
    """Where a label was launched first; past the end when it never was."""
    return labels(rec).index(label) if label in labels(rec) else 10 ** 6


class Launches(list):
    """A list of launches that answers a missing one with an empty launch, so a script that launched too few fails the checks
    that look at them instead of stopping the whole test."""

    def __getitem__(self, i):
        try:
            return list.__getitem__(self, i)
        except IndexError:
            return {"label": "(not launched)", "prompt": "", "opts": {}, "start": 0, "end": 0, "answer": None}


def launched(rec, prefix):
    return Launches(l for l in rec["launches"] if l["label"].startswith(prefix))


def workers(rec):
    """The launches that got a worktree of their own: executors, fixers, resolvers (a runner has none)."""
    return Launches(l for l in rec["launches"] if l["opts"].get("isolation") == "worktree")


def runner(rec, step):
    return launched(rec, "executor:runner-" + step)


def result(rec):
    return rec.get("result") or {}


def details(rec):
    return result(rec).get("details") or {}


def overlap(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def blank(rec):
    return rec or {"launches": [], "phases": [], "logs": [], "result": None, "error": None}


def finish(s, name, rec, err, allow_unanswered=False):
    """The checks every run owes: it ran, it ended without a script error, no launch lacked an answer in the scenario."""
    s.ok("%s: the script ran" % name, rec is not None, err)
    rec = blank(rec)
    s.ok("%s: the script ended" % name, rec.get("finished") is True, repr(rec.get("error")))
    s.ok("%s: no error in the script" % name, rec.get("error") is None, repr(rec.get("error")))
    if not allow_unanswered:
        s.ok("%s: every launch had an answer" % name, all(l["answer"] != "unanswered" for l in rec["launches"]),
             repr([l["label"] for l in rec["launches"] if l["answer"] == "unanswered"]))
    return rec


# ---- the scenarios --------------------------------------------------------------------------------------------------
def check_green(script, s):
    rec, err = go(script)
    rec = finish(s, "green", rec, err)
    r = result(rec)
    s.eq("green: status", r.get("status"), "done")
    s.eq("green: reason", r.get("reason"), "")
    s.eq("green: phase_dir", r.get("phase_dir"), "/work/.fwx/phases/01-toy")
    want = ["executor:T1", "executor:T2", "executor:runner-report-T1", "executor:runner-report-T2",
            "executor:runner-integrate", "executor:T3", "executor:runner-report-T3",
            "executor:runner-integrate", "reviewer:r1", "executor:runner-report-r1", "executor:runner-cleanup"]
    s.eq("green: launch order", labels(rec), want)
    s.eq("green: phases", rec.get("phases"), ["executing", "reviewing"])
    s.eq("green: meta phases are the stage names", [p.get("title") for p in (rec.get("meta") or {}).get("phases", [])], ["executing", "reviewing"])
    for l in rec["launches"]:
        role = l["label"].split(":")[0]
        model = {"reviewer": "m-rev"}.get(role) if role != "executor" else None
        if l["label"].startswith("executor:runner-"):
            s.eq("green: %s model" % l["label"], (l["opts"].get("model"), l["opts"].get("agentType")), ("m-run", "fwx:executor"))
            s.eq("green: %s schema" % l["label"], sorted((l["opts"].get("schema") or {}).get("required", [])), ["rc", "stdout"])
            s.ok("green: %s has no worktree" % l["label"], "isolation" not in l["opts"])
        elif l["label"].startswith("executor:T"):
            tid = l["label"].split(":")[1]
            s.eq("green: %s model, agentType, isolation" % tid,
                 (l["opts"].get("model"), l["opts"].get("agentType"), l["opts"].get("isolation")),
                 ({"T1": "m-t1", "T2": "m-t2", "T3": "m-t3"}[tid], "fwx:executor", "worktree"))
            s.ok("green: %s prompt names its brief" % tid, "%s/briefs/%s.md" % (RUN_DIR, tid) in l["prompt"], l["prompt"])
            s.ok("green: %s prompt is one line" % tid, "\n" not in l["prompt"].strip(), repr(l["prompt"]))
        elif model:
            s.eq("green: reviewer model, agentType, no worktree", (l["opts"].get("model"), l["opts"].get("agentType"), "isolation" in l["opts"]),
                 ("m-rev", "fwx:reviewer", False))
    t1, t2 = launched(rec, "executor:T1")[0], launched(rec, "executor:T2")[0]
    s.ok("green: the two tasks of a wave with no clash run at once", overlap(t1, t2), "T1 %s-%s, T2 %s-%s" % (t1["start"], t1["end"], t2["start"], t2["end"]))
    ints = runner(rec, "integrate")
    s.ok("green: the first wave is not integrated with --final", "--final" not in ints[0]["prompt"], ints[0]["prompt"][-200:])
    s.ok("green: the last wave is integrated with --final", "--final" in ints[1]["prompt"], ints[1]["prompt"][-200:])
    s.ok("green: the branches go in task order", "--branches 'wt-t1' 'wt-t2'" in ints[0]["prompt"], ints[0]["prompt"][-200:])
    s.ok("green: the runner is told the checkout and the run", "cd '/work/wt' && fwx wave merge --part-dir '/work/.fwx/phases/01-toy' --run '01-toy-ab12cd3-1'" in ints[0]["prompt"],
         ints[0]["prompt"][-300:])
    s.ok("green: the reviewer is asked for the diff base..head", HEAD0 in launched(rec, "reviewer:")[0]["prompt"] and "h2" in launched(rec, "reviewer:")[0]["prompt"],
         launched(rec, "reviewer:")[0]["prompt"][:300])
    d = details(rec)
    s.eq("green: details.run and head", (d.get("run"), d.get("head")), ("01-toy-ab12cd3-1", "h2"))
    s.eq("green: details.evidence is the gate's line", d.get("evidence"), "evidence h2 t=0")
    s.eq("green: details.agents counts every launch", d.get("agents"), len(rec["launches"]))
    s.eq("green: details.kept_worktrees and leftover come from cleanup", (d.get("kept_worktrees"), d.get("leftover")), ([], []))
    s.eq("green: details.criteria", d.get("criteria"), crit())
    s.eq("green: details.plan_failures", d.get("plan_failures"), [])
    s.eq("green: details.findings", d.get("findings"), {"reported": 0, "fix": 0, "consider": [], "note": [], "dismissed": [], "fixed": []})
    s.eq("green: details keys", sorted(d), sorted(["run", "head", "evidence", "rounds", "plan_failures", "criteria", "findings", "outside", "protected",
                                                 "tried", "gaps", "kept_worktrees", "leftover", "agents"]))
    s.eq("green: the cleanup is the last launch", last(rec), "executor:runner-cleanup")
    s.ok("green: cleanup names the run", "fwx wave remove --run '01-toy-ab12cd3-1'" in launched(rec, "executor:runner-cleanup")[0]["prompt"])
    s.eq("green: no fix-round, no fixer", (runner(rec, "fix-round"), [l for l in workers(rec) if not l["label"].startswith("executor:T")]), ([], []))

    def skip_t1(a):
        a["done"] = ["T1", "T2"]
    rec, err = go(script, args_over=skip_t1, answers_over={"executor:runner-integrate": {"$seq": [final("h2", ["wt-t3"])]}})
    rec = finish(s, "done tasks", rec, err)
    s.ok("done tasks: a task already on the phase branch is not launched (and its wave is not run)",
         not launched(rec, "executor:T1") and not launched(rec, "executor:T2") and len(launched(rec, "executor:T3")) == 1, repr(labels(rec)))
    s.eq("done tasks: the last wave left is the final one", ["--final" in c["prompt"] for c in runner(rec, "integrate")], [True])

    def one_done(a):
        a["done"] = ["T1"]
    rec, err = go(script, args_over=one_done)
    rec = finish(s, "one task done", rec, err)
    s.ok("done tasks: in a wave half done only the other task is launched and merged",
         not launched(rec, "executor:T1") and len(launched(rec, "executor:T2")) == 1 and "--branches 'wt-t2'" in runner(rec, "integrate")[0]["prompt"]
         and "wt-t1" not in runner(rec, "integrate")[0]["prompt"], repr(labels(rec)))

    def all_done(a):
        a["done"] = ["T1", "T2", "T3"]
    rec, err = go(script, args_over=all_done)
    rec = finish(s, "all done", rec, err)
    s.eq("all done: nothing to execute is for the owner, no agent but the cleanup", (result(rec).get("status"), [l for l in labels(rec) if l != "executor:runner-cleanup"]),
         ("needs-owner", []))


def check_clash(script, s):
    def clash(a):
        a["waves"][0]["serial"] = True
        a["plan_failures"] = [{"wave": 1, "tasks": ["T1", "T2"], "files": ["a.py"]}]
    rec, err = go(script, args_over=clash)
    rec = finish(s, "clash", rec, err)
    t1, t2 = launched(rec, "executor:T1")[0], launched(rec, "executor:T2")[0]
    s.ok("clash: the two executors never run at once", not overlap(t1, t2), "T1 %s-%s overlaps T2 %s-%s" % (t1["start"], t1["end"], t2["start"], t2["end"]))
    s.eq("clash: one task per batch whatever the cap (3)", peak(launched(rec, "executor:T")), 1)
    s.eq("clash: plan_failures reach the output", details(rec).get("plan_failures"), [{"wave": 1, "tasks": ["T1", "T2"], "files": ["a.py"]}])
    s.eq("clash: the run still ends done", result(rec).get("status"), "done")


def check_executor_misses(script, s):
    ok = exec_report("wt-t1")
    for name, first in (("null", None), ("empty string", ""), ("schema exhaustion", {"$throw": "agent({schema}): subagent completed without calling StructuredOutput (after in-conversation nudge)"}),
                        ("a line that is not a report", "I finished the work"), ("a report that is not there", "done /elsewhere/T1.json commits=2"),
                        ("a report in the run folder under .git, where agents no longer write", "done %s/reports/T1.json commits=2" % RUN_DIR),
                        ("the report of another unit", "done %s commits=2" % report_at("T2")),
                        ("a path that climbs out of a scratch folder", "done /work/wt-T1/../../etc%s commits=2" % report_at("T1")[len("/work/wt-T1"):])):
        rec, err = go(script, answers_over={"executor:T1": {"$seq": [first, exec_line("T1")]}})
        rec = finish(s, "executor " + name, rec, err)
        s.eq("executor %s once: relaunched once" % name, len(launched(rec, "executor:T1")), 2)
        s.ok("executor %s once: no round spent (fix-round called for a %s)" % (name, name), not runner(rec, "fix-round"), repr(labels(rec)))
        s.ok("executor %s once: %s counted as done" % (name, name), result(rec).get("status") == "done" and not details(rec).get("gaps"),
             "status %r gaps %r" % (result(rec).get("status"), details(rec).get("gaps")))

    rec, err = go(script, answers_over={"executor:T1": {"$seq": [None, None]}})
    rec = finish(s, "two nulls", rec, err)
    s.eq("two nulls: failed", result(rec).get("status"), "failed")
    s.eq("two nulls: reason names the task", result(rec).get("reason"), "executor did not return: T1")
    s.eq("two nulls: the gap is recorded (second null counted as done)", details(rec).get("gaps"), ["executor did not return: T1"])
    s.eq("two nulls: launched twice, not three times", len(launched(rec, "executor:T1")), 2)
    s.ok("two nulls: no round spent", not runner(rec, "fix-round"))
    s.ok("two nulls: nothing is integrated", not runner(rec, "integrate"), repr(labels(rec)))
    s.eq("two nulls: cleanup is last", last(rec), "executor:runner-cleanup")

    rec, err = go(script, answers_over={"executor:T1": {"$throw": "agent({agentType}): agent type 'fwx:executor' not found. Available agents: claude"}})
    rec = finish(s, "unknown agentType", rec, err)
    s.eq("unknown agentType: not relaunched (unknown agentType retried)", len(launched(rec, "executor:T1")), 1)
    s.eq("unknown agentType: failed", result(rec).get("status"), "failed")
    s.ok("unknown agentType: the message is the reason", "agent type 'fwx:executor' not found" in str(result(rec).get("reason")), repr(result(rec).get("reason")))
    s.ok("unknown agentType: no round spent", not runner(rec, "fix-round"))

    rec, err = go(script, answers_over={"executor:T2": exec_line("T2", "question"),
                                        "executor:runner-report-T2": exec_report("wt-t2", "question", question="Which of the two APIs wins?")})
    rec = finish(s, "question", rec, err)
    s.eq("question: needs-owner with the question", (result(rec).get("status"), result(rec).get("reason")), ("needs-owner", "Which of the two APIs wins?"))
    s.ok("question: no round, nothing integrated", not runner(rec, "fix-round") and not runner(rec, "integrate"), repr(labels(rec)))

    rec, err = go(script, answers_over={
        "executor:T1": {"$seq": [exec_line("T1", "wrong-base"), exec_line("T1")]},
        "executor:runner-report-T1": {"$seq": [exec_report("wt-t1", "wrong-base", reason="wrong base: HEAD x, expected y"), exec_report("wt-t1b")]},
        "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"})})
    rec = finish(s, "wrong-base", rec, err)
    ints = runner(rec, "integrate")
    s.eq("wrong-base: a round is spent and the task is launched again", (len(runner(rec, "fix-round")), len(launched(rec, "executor:T1"))), (1, 2))
    s.ok("wrong-base: its branch does not go to integrate, the new one does", "'wt-t1b'" in ints[0]["prompt"] and "'wt-t1'" not in ints[0]["prompt"].replace("'wt-t1b'", ""),
         ints[0]["prompt"][-160:])
    s.ok("wrong-base: the new attempt is told what the last one returned", "wrong base: HEAD x, expected y" in launched(rec, "executor:T1")[1]["prompt"],
         launched(rec, "executor:T1")[1]["prompt"])
    s.ok("wrong-base: the new attempt keeps the brief", "%s/briefs/T1.md" % RUN_DIR in launched(rec, "executor:T1")[1]["prompt"])
    s.eq("wrong-base: the round is in details.rounds", details(rec).get("rounds"), "1/3")
    s.eq("wrong-base: the attempt is listed in tried", len(details(rec).get("tried") or []), 1)

    rec, err = go(script, answers_over={
        "executor:T1": exec_line("T1", "failed"), "executor:runner-report-T1": exec_report("wt-t1", "failed", reason="no test can fail"),
        "executor:runner-fix-round": R({"ok": False, "spent": False, "rounds": "3/3", "why": "w"}, 1)})
    rec = finish(s, "rounds exhausted", rec, err)
    s.eq("rounds exhausted: failed, reason", (result(rec).get("status"), result(rec).get("reason")), ("failed", "rounds exhausted"))
    s.eq("rounds exhausted: no executor launched after it (no fixer more)", len(launched(rec, "executor:T1")), 1)
    s.ok("rounds exhausted: nothing is integrated", not runner(rec, "integrate"))
    s.eq("rounds exhausted: cleanup still runs", last(rec), "executor:runner-cleanup")


def check_setup_failed(script, s):
    """A worktree setup that failed (exit 43 of `fwx base`, or `setup` in the result of `integrate` and `revert`) ends the job
    with its own line: a new attempt would run the same setup and fail the same way, and the round it takes is one a real failure needs.

    The signal is a fact the code wrote, not words an agent chose: `check-base` leaves `.fwx-agent/worktree-setup-failed.json` in the
    worktree and the workflow reads it with a runner when an executor reports `failed`. The start of the reason stays as a second net.

    Red on the script before this check (the round was available, `fix-round` answered ok):
      FAIL: setup failed in an executor (session): ended with the setup's line, no round spent, no new attempt: got ('done', ...), want ('needs-owner', 'worktree setup failed: npm ci (exit 1, ...)', 0, 1)
      FAIL: setup failed at the join (session): ended with the setup's line, no round spent: ...
    Red on the script that read only the start of the reason (second review): the three paraphrases each went the old way, one round
    and a new executor:
      FAIL: setup failed, reason 'Worktree setup failed: ...': ended once with the record's line, no round, no new attempt: got ('done', '', 1, 2), want (...)
      FAIL: setup failed, reason ' worktree setup failed: ...' (leading space): ...
      FAIL: setup failed, reason 'check-base exit 43: worktree setup failed: ...': ...
      FAIL: setup failed, reason 'npm could not install': ...
    """
    line = "worktree setup failed: npm ci (exit 1, log /w/.fwx-agent/worktree-setup.log)"
    record = R({"setup_failed": line})

    def failing(reason, plane="session", rec_answer=record):
        def pl(a):
            a["plane"] = plane
        return go(script, args_over=pl, answers_over={
            "executor:T1": {"$seq": [exec_line("T1", "failed"), exec_line("T1")]},
            "executor:runner-report-T1": {"$seq": [exec_report("wt-t1", "failed", reason=reason), exec_report("wt-t1b")]},
            "executor:runner-setup-T1": rec_answer,
            "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"})})
    for plane, want in (("session", "needs-owner"), ("factory", "failed")):
        rec, err = failing(line, plane)
        rec = finish(s, "setup failed in an executor (%s)" % plane, rec, err)
        s.eq("setup failed in an executor (%s): ended with the setup's line, no round spent, no new attempt" % plane,
             (result(rec).get("status"), result(rec).get("reason"), len(runner(rec, "fix-round")), len(launched(rec, "executor:T1"))), (want, line, 0, 1))
        s.ok("setup failed in an executor (%s): nothing was integrated" % plane, not runner(rec, "integrate"), repr(labels(rec)))
    s.ok("setup failed: the runner reads the record in the worktree the report came from", "cat -- '/work/wt-T1/.fwx-agent/worktree-setup-failed.json'" in runner(rec, "setup-T1")[0]["prompt"],
         runner(rec, "setup-T1")[0]["prompt"][-200:] if runner(rec, "setup-T1") else "no runner")
    for label, reason in (("'Worktree setup failed: ...'", "Worktree setup failed: npm ci (exit 1)"), ("' worktree setup failed: ...' (leading space)", " worktree setup failed: npm ci (exit 1)"),
                          ("'check-base exit 43: worktree setup failed: ...'", "check-base exit 43: worktree setup failed: npm ci (exit 1)"), ("'npm could not install'", "npm could not install")):
        rec, err = failing(reason)
        rec = finish(s, "setup failed, reason " + label, rec, err)
        s.eq("setup failed, reason %s: ended once with the record's line, no round, no new attempt" % label,
             (result(rec).get("status"), result(rec).get("reason"), len(runner(rec, "fix-round")), len(launched(rec, "executor:T1"))), ("needs-owner", line, 0, 1))
    # the second net: no record (the runner found none), the reason still starts with the phrase, any case, any padding
    for reason in ("worktree setup failed: npm ci", "Worktree Setup Failed: npm ci", "  worktree setup failed: npm ci"):
        rec, err = failing(reason, rec_answer=R("", 1))
        rec = finish(s, "setup failed, no record, reason %r" % reason, rec, err)
        s.eq("setup failed, no record, reason %r: the start of the reason is the second net" % reason,
             (result(rec).get("status"), len(runner(rec, "fix-round")), len(launched(rec, "executor:T1"))), ("needs-owner", 0, 1))
    # a failure that is not the setup's: no record, another reason: a round, a new attempt
    rec, err = failing("check-base exit 43: worktree setup failed: npm ci (exit 1)", rec_answer=R("", 1))
    rec = finish(s, "no record, phrase inside the reason", rec, err)
    s.eq("no record and the phrase inside other words: an ordinary failure (a round, a new attempt)", (len(runner(rec, "fix-round")), len(launched(rec, "executor:T1"))), (1, 2))
    rec, err = failing("no test can fail", rec_answer=R({"setup_failed": ""}))
    rec = finish(s, "empty record", rec, err)
    s.eq("an empty record is no record", (len(runner(rec, "fix-round")), len(launched(rec, "executor:T1"))), (1, 2))
    for plane, want in (("session", "needs-owner"), ("factory", "failed")):
        def pl(a, plane=plane):
            a["plane"] = plane
        rec, err = go(script, args_over=pl, answers_over={
            "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"], ok=False, setup=line)]},
            "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"})})
        rec = finish(s, "setup failed at the join (%s)" % plane, rec, err)
        s.eq("setup failed at the join (%s): ended with the setup's line, no round spent" % plane,
             (result(rec).get("status"), result(rec).get("reason"), len(runner(rec, "fix-round"))), (want, line, 0))

    def rev(a):
        a["revert"] = ["r1-F1"]
    rec, err = go(script, args_over=rev, base={
        "executor:runner-revert": R({"ok": False, "head": "h4", "reverted": [{"id": "r1-F1", "commit": "c1", "revert": "h4"}], "failed": None, "setup": line}, 1),
        "executor:runner-cleanup": CLEAN_CLEANUP})
    rec = finish(s, "setup failed after a revert", rec, err)
    s.eq("setup failed after a revert: ended with the setup's line, no gate", (result(rec).get("status"), result(rec).get("reason"), runner(rec, "verify")), ("needs-owner", line, []))
    rec, err = go(script, answers_over={
        "executor:T1": exec_line("T1", "failed"), "executor:runner-report-T1": exec_report("wt-t1", "failed", reason="no test can fail"),
        "executor:runner-fix-round": R({"ok": False, "spent": False, "rounds": "3/3", "why": "w"}, 1)})
    rec = finish(s, "other failure", rec, err)
    s.eq("a failure that is not the setup's still takes the round path", (result(rec).get("reason"), len(runner(rec, "fix-round"))), ("rounds exhausted", 1))


def check_join(script, s):
    conflict = integ("h1", ["wt-t1"], ok=False, conflict={"branch": "wt-t2", "files": ["a.py"]})
    rec, err = go(script, answers_over={
        "executor:runner-integrate": {"$seq": [conflict, integ("h1r", ["wt-res", ]), final("h2", ["wt-t3"])]},
        "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"}),
        "executor:resolve-1": exec_line("resolve-1"), "executor:runner-report-resolve-1": exec_report("wt-res")})
    rec = finish(s, "conflict", rec, err)
    s.ok("conflict: the resolver ran (conflict sent to the plain fixer)", len(launched(rec, "executor:resolve-")) == 1 and not launched(rec, "executor:fix-"), repr(labels(rec)))
    res = (launched(rec, "executor:resolve-") or [{"prompt": "", "opts": {}}])[0]
    s.eq("conflict: the resolver has a worktree of its own and the fixer's model", (res["opts"].get("isolation"), res["opts"].get("model")), ("worktree", "m-fix"))
    s.ok("conflict: the resolver is told the branch to bring in, the files and the base", "wt-t2" in res["prompt"] and "a.py" in res["prompt"] and "h1" in res["prompt"], res["prompt"][:400])
    s.ok("conflict: the resolver is told to merge, never to rebase, and to abort a contradiction", "git merge --no-commit" in res["prompt"] and "git merge --abort" in res["prompt"], res["prompt"][:600])
    s.ok("conflict: the resolver's merge carries the conflicting task's trailer", "Fwx-Task: 01-toy/T2" in res["prompt"], res["prompt"][:600])
    s.eq("conflict: one round, then integrate again", (len(runner(rec, "fix-round")), len(runner(rec, "integrate"))), (1, 3))
    s.ok("conflict: the second integrate takes the resolver's branch and not the conflicting one", "'wt-res'" in runner(rec, "integrate")[1]["prompt"] and "'wt-t2'" not in runner(rec, "integrate")[1]["prompt"],
         runner(rec, "integrate")[1]["prompt"][-200:])
    s.eq("conflict: ends done", result(rec).get("status"), "done")

    rec, err = go(script, answers_over={
        "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"], ok=False, quick={"ran": True, "cmds": ["make quick"], "rc": 1}),
                                               integ("h1f", ["wt-fix"]), final("h2", ["wt-t3"])]},
        "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"}),
        "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix")})
    rec = finish(s, "quick red", rec, err)
    fx = (launched(rec, "executor:fix-") or [{"prompt": "", "opts": {}}])[0]
    s.ok("quick red: the plain fixer ran, not the resolver", len(launched(rec, "executor:fix-")) == 1 and not launched(rec, "executor:resolve-"), repr(labels(rec)))
    s.ok("quick red: the fixer is told the failing command", "make quick" in fx["prompt"] and "h1" in fx["prompt"], fx["prompt"][:500])
    s.eq("quick red: the fixer's worktree and model", (fx["opts"].get("isolation"), fx["opts"].get("model"), fx["opts"].get("agentType")), ("worktree", "m-fix", "fwx:executor"))
    s.ok("quick red: the branches that merged are not merged again; the fixer's is", "'wt-fix'" in runner(rec, "integrate")[1]["prompt"] and "'wt-t1'" not in runner(rec, "integrate")[1]["prompt"],
         runner(rec, "integrate")[1]["prompt"][-200:])
    s.ok("quick red: the round is spent before the fixer", pos(rec, "executor:runner-fix-round") < pos(rec, "executor:fix-1"))
    s.eq("quick red: done", result(rec).get("status"), "done")

    rec, err = go(script, answers_over={
        "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"], ok=False, quick={"ran": True, "cmds": ["make quick"], "rc": 1})]},
        "executor:runner-fix-round": R({"ok": False, "spent": False, "rounds": "3/3", "why": "w"}, 1)})
    rec = finish(s, "three attempts spent", rec, err)
    s.eq("three attempts spent: failed, rounds exhausted", (result(rec).get("status"), result(rec).get("reason")), ("failed", "rounds exhausted"))
    s.ok("three attempts spent: no fixer more", not launched(rec, "executor:fix-") and not launched(rec, "executor:resolve-"), repr(labels(rec)))
    s.ok("three attempts spent: cleanup ran after the failure", last(rec) == "executor:runner-cleanup")

    rec, err = go(script, answers_over={"executor:runner-integrate": {"$seq": [
        integ("h1", ["wt-t1", "wt-t2"], ok=False, locked=[{"branch": "wt-t2", "worktree": "/w", "pid": 1, "lock": "x"}]),
    ]}})
    rec = finish(s, "locked", rec, err)
    s.eq("locked: a live agent holds a branch: failed, no round", (result(rec).get("status"), bool(runner(rec, "fix-round"))), ("failed", False))
    s.ok("locked: the reason names the branch", "wt-t2" in str(result(rec).get("reason")), repr(result(rec).get("reason")))

    # a runner's rc is not the decision, its stdout is
    rec, err = go(script, answers_over={"executor:runner-integrate": {"$seq": [R(json.loads(integ("h1", ["wt-t1", "wt-t2"])["stdout"]), 1), final("h2", ["wt-t3"])]}})
    rec = finish(s, "rc 1 ok true", rec, err)
    s.eq("rc 1 with ok true: carries on (the exit code is not read)", (result(rec).get("status"), bool(runner(rec, "fix-round"))), ("done", False))
    bad = integ("h1", ["wt-t1", "wt-t2"], ok=False, quick={"ran": True, "cmds": ["q"], "rc": 1})
    bad["rc"] = 0
    rec, err = go(script, answers_over={"executor:runner-integrate": {"$seq": [bad]}, "executor:runner-fix-round": R({"ok": False, "rounds": "3/3"}, 1)})
    rec = finish(s, "rc 0 ok false", rec, err)
    s.ok("rc 0 with ok false: a failure (trusted runner rc 0, stdout says ok false)", len(runner(rec, "fix-round")) == 1 and result(rec).get("status") == "failed",
         "fix-round calls %d, status %r" % (len(runner(rec, "fix-round")), result(rec).get("status")))

    rec, err = go(script, answers_over={"executor:runner-integrate": {"$seq": [R("integrate: Traceback ...", 2)]}})
    rec = finish(s, "runner prints no JSON", rec, err)
    s.eq("runner without JSON: failed, naming the step", (result(rec).get("status"), "integrate" in str(result(rec).get("reason"))), ("failed", True))


def check_gate(script, s):
    def gate(**kw):
        return {"executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"], **kw)]}}
    rec, err = go(script, answers_over=gate(trusted=[".github/workflows/ci.yml"]))
    rec = finish(s, "trusted", rec, err)
    s.eq("trusted: needs-owner", result(rec).get("status"), "needs-owner")
    s.ok("trusted: the file is named", ".github/workflows/ci.yml" in str(result(rec).get("reason")), repr(result(rec).get("reason")))
    s.ok("trusted: no fix-round and no review", not runner(rec, "fix-round") and not launched(rec, "reviewer:"), repr(labels(rec)))

    for plane, want in (("session", "needs-owner"), ("factory", "failed")):
        def pl(a, plane=plane):
            a["plane"] = plane
        rec, err = go(script, args_over=pl, answers_over={"executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"], rc=2)]}})
        rec = finish(s, "verify rc 2 " + plane, rec, err)
        s.eq("verify rc 2 on the %s plane (session plane returned failed for verify rc 2)" % plane, result(rec).get("status"), want)
        s.ok("verify rc 2 on the %s plane: no round" % plane, not runner(rec, "fix-round") and not launched(rec, "reviewer:"), repr(labels(rec)))
        s.ok("verify rc 2 on the %s plane: the reason says verify could not run" % plane, "verify could not run" in str(result(rec).get("reason")), repr(result(rec).get("reason")))

    rec, err = go(script, answers_over={
        "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"], rc=1), final("h3", ["wt-fix"])]},
        "executor:runner-fix-round": R({"ok": True, "spent": False, "rounds": "1/3", "why": "w"}),
        "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix")})
    rec = finish(s, "verify rc 1", rec, err)
    s.ok("verify rc 1: a fix attempt, then the gate again with --final", len(launched(rec, "executor:fix-")) == 1 and "--final" in runner(rec, "integrate")[2]["prompt"], repr(labels(rec)))
    s.ok("verify rc 1: the fixer is told the evidence line", "evidence h2 t=1" in launched(rec, "executor:fix-")[0]["prompt"], launched(rec, "executor:fix-")[0]["prompt"][:400])
    s.eq("verify rc 1: done after the fix", result(rec).get("status"), "done")


def check_review(script, s):
    prot = ["config/forge.json"]
    for needed, want_sec in ((True, True), (False, True)):
        def sec(a, needed=needed):
            a["security"] = {"needed": needed, "why": "x"}
        rec, err = go(script, args_over=sec, answers_over={
            "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"], protected=prot)]},
            "security-reviewer:r1": review_line("r1", "security-reviewer"), "executor:runner-report-r1-sec": review_report(criteria=[])})
        rec = finish(s, "protected, security.needed %s" % needed, rec, err)
        s.eq("protected path (security needed: %s): needs-owner, never done (protected path with security asked returned done)" % needed,
             (result(rec).get("status"), result(rec).get("reason", "")[:14]), ("needs-owner", "protected path"))
        s.ok("protected path (security needed: %s): the security reviewer ran (protected path skipped the security review)" % needed,
             len(launched(rec, "security-reviewer:")) == 1, repr(labels(rec)))
        s.eq("protected path (security needed: %s): details.protected" % needed, details(rec).get("protected"), prot)
        s.ok("protected path (security needed: %s): no round, no fixer" % needed, not runner(rec, "fix-round"))
        sr = (launched(rec, "security-reviewer:") or [{"opts": {}, "prompt": ""}])[0]
        s.eq("protected path: the security reviewer's agentType, model, no worktree", (sr["opts"].get("agentType"), sr["opts"].get("model"), "isolation" in sr["opts"]),
             ("fwx:security-reviewer", "m-sec", False))
        s.ok("protected path: the security reviewer is told the protected path", "config/forge.json" in sr["prompt"], sr["prompt"][:400])

    rec, err = go(script, args_over=lambda a: a.update(security={"needed": True, "why": "x"}), answers_over={
        "security-reviewer:r1": review_line("r1", "security-reviewer"), "executor:runner-report-r1-sec": review_report(criteria=[])})
    rec = finish(s, "security asked, no protected path", rec, err)
    s.eq("security asked, nothing protected: the security reviewer runs and the part is done", (len(launched(rec, "security-reviewer:")), result(rec).get("status")), (1, "done"))
    rec, err = go(script)
    rec = finish(s, "no security", rec, err)
    s.eq("no security asked and nothing protected: no security reviewer", launched(rec, "security-reviewer:"), [])

    rec, err = go(script, answers_over={"reviewer:r1": {"$seq": [None, None]}})
    rec = finish(s, "reviewer null twice", rec, err)
    s.eq("reviewer null twice: failed, reviewer did not return", (result(rec).get("status"), result(rec).get("reason")), ("failed", "reviewer did not return"))
    s.eq("reviewer null twice: two launches", len(launched(rec, "reviewer:")), 2)
    s.ok("reviewer null twice: cleanup is last", last(rec) == "executor:runner-cleanup")
    rec, err = go(script, answers_over={"reviewer:r1": {"$seq": ["", review_line("r1")]}})
    rec = finish(s, "reviewer empty string", rec, err)
    s.eq("reviewer empty string once: relaunched, then done", (len(launched(rec, "reviewer:")), result(rec).get("status"), bool(runner(rec, "fix-round"))), (2, "done", False))
    rec, err = go(script, answers_over={"reviewer:r1": {"$seq": [review_line("r1", looked=0), review_line("r1")]}})
    rec = finish(s, "looked_at 0", rec, err)
    s.eq("looked_at 0: relaunched once (an empty looked_at is a failed review)", (len(launched(rec, "reviewer:")), result(rec).get("status")), (2, "done"))
    rec, err = go(script, answers_over={"executor:runner-report-r1": {"$seq": [review_report(looked=()), review_report()]}})
    rec = finish(s, "report looked_at empty", rec, err)
    s.eq("a report whose looked_at is empty: relaunched once", (len(launched(rec, "reviewer:")), result(rec).get("status")), (2, "done"))

    # the groups: only `fix` is fixed
    fs = [finding("F1"), finding("F2"), finding("F3"), finding("F4")]
    rec, err = go(script, answers_over={
        "reviewer:r1": review_line("r1", findings=4), "executor:runner-report-r1": review_report(fs),
        "review-verifier:r1": verdicts(("r1-F1", "dismiss", "none", None), ("r1-F2", "note", "low", "none"), ("r1-F3", "consider", "medium", "check"),
                                       ("r1-F4", "dismiss", "none", None))})
    rec = finish(s, "no fix verdict", rec, err)
    s.ok("no fix verdict: no fixer, no round (note finding was fixed)", not runner(rec, "fix-round") and not launched(rec, "executor:fix-"), repr(labels(rec)))
    f = details(rec).get("findings") or {}
    s.eq("no fix verdict: reported and fix counts", (f.get("reported"), f.get("fix")), (4, 0))
    s.eq("no fix verdict: consider keeps its finding", f.get("consider"), [{"id": "r1-F3", "file": "a.py", "line": 3, "claim": "claim of F3", "severity": "medium"}])
    s.eq("no fix verdict: note", f.get("note"), [{"id": "r1-F2", "claim": "claim of F2"}])
    s.eq("no fix verdict: dismissed with the reason", f.get("dismissed"), [{"id": "r1-F1", "reason": "because r1-F1"}, {"id": "r1-F4", "reason": "because r1-F4"}])
    s.eq("no fix verdict: done", result(rec).get("status"), "done")
    v = (launched(rec, "review-verifier:") or [{"opts": {}, "prompt": ""}])[0]
    s.eq("verifier: one launch for the batch, its model, agentType, no worktree", (len(launched(rec, "review-verifier:")), v["opts"].get("model"), v["opts"].get("agentType"), "isolation" in v["opts"]),
         (1, "m-ver", "fwx:review-verifier", False))
    s.ok("verifier: it is given the findings with their unique ids and the diff, and not the reviewer's report", "r1-F3" in v["prompt"] and "evidence of F3" in v["prompt"] and HEAD0 in v["prompt"], v["prompt"][:500])
    sc = (v["opts"].get("schema") or {}).get("properties", {}).get("verdicts", {}).get("items", {}).get("properties", {})
    s.ok("verifier schema: catchable_by \"maybe\" is rejected", "maybe" not in (sc.get("catchable_by") or {}).get("enum", ["maybe"]), repr(sc.get("catchable_by")))
    s.ok("verifier schema: verdict \"ask\" is rejected", "ask" not in (sc.get("verdict") or {}).get("enum", ["ask"]), repr(sc.get("verdict")))
    s.eq("verifier schema: the four groups", sorted((sc.get("verdict") or {}).get("enum", [])), ["consider", "dismiss", "fix", "note"])
    s.eq("verifier schema: catchable_by", sorted((sc.get("catchable_by") or {}).get("enum", [])), ["check", "code", "none", "rule"])

    for what, bad in (("catchable_by \"maybe\"", verdicts(("r1-F1", "fix", "high", "maybe"))), ("verdict \"ask\"", verdicts(("r1-F1", "ask", "high", "code")))):
        rec, err = go(script, answers_over={"reviewer:r1": review_line("r1", findings=1), "executor:runner-report-r1": review_report([finding("F1")]),
                                            "review-verifier:r1": {"$seq": [bad, bad]}})
        rec = finish(s, "bad verdict " + what, rec, err)
        s.eq("a verdict with %s breaks the schema: the answer never counts, failed" % what, (result(rec).get("status"), result(rec).get("reason")), ("failed", "review-verifier did not return"))
    rec, err = go(script, answers_over={"reviewer:r1": review_line("r1", findings=2), "executor:runner-report-r1": review_report([finding("F1"), finding("F2")]),
                                        "review-verifier:r1": {"$seq": [verdicts(("r1-F1", "note", "low", "none")), verdicts(("r1-F1", "note", "low", "none"), ("r1-F2", "dismiss", "none", None))]}})
    rec = finish(s, "verdict missing", rec, err)
    s.eq("a verifier that skips a finding is relaunched once", (len(launched(rec, "review-verifier:")), result(rec).get("status")), (2, "done"))

    # the criteria: only `no` is a finding
    rec, err = go(script, answers_over={"reviewer:r1": review_line("r1", unproven=1), "executor:runner-report-r1": review_report(criteria=crit("unproven", "yes"))})
    rec = finish(s, "criterion unproven", rec, err)
    s.ok("criterion unproven: not a finding, no fixer, and done", not launched(rec, "executor:fix-") and result(rec).get("status") == "done", repr(labels(rec)))
    s.eq("criterion unproven: stays in details.criteria", [c["met"] for c in details(rec).get("criteria", [])], ["unproven", "yes"])
    rec, err = go(script, answers_over={"reviewer:r1": {"$seq": [review_line("r1", no=1), review_line("r1")]},
                                        "executor:runner-report-r1": {"$seq": [review_report(criteria=crit("no", "yes")), review_report()]}})
    rec = finish(s, "criterion no, no finding", rec, err)
    s.eq("criterion no that no finding names: the report lacks what it was asked for, relaunched once", len(launched(rec, "reviewer:")), 2)
    rv = (launched(rec, "reviewer:") or [{"prompt": ""}])[0]
    s.ok("reviewer: the prompt carries the criteria, the intent files, the range and the report path", all(x in rv["prompt"] for x in ("C1", "g is exported", HEAD0, "/work/.fwx/phases/01-toy/plan.md", "/work/.fwx/phases/01-toy/context.md", "fwx scratch new %s r1" % os.path.basename(RUN_DIR))),
         rv["prompt"][:700])
    rec, err = go(script, answers_over={"reviewer:r1": review_line("r1", no=1, findings=1), "executor:runner-report-r1": review_report([finding("F1", claim="C1 is not met: g is missing")], crit("no", "yes")),
                                        "review-verifier:r1": verdicts(("r1-F1", "fix", "high", "check")),
                                        "executor:runner-fix-round": R({"ok": False, "spent": False, "rounds": "3/3"}, 1)})
    rec = finish(s, "criterion no with a finding", rec, err)
    s.ok("criterion no with its finding: goes to the verifier", len(launched(rec, "review-verifier:")) == 1, repr(labels(rec)))


def fix_scenario():
    """A run with one review finding to fix (r1-F1, in a.py), fixed by one fixer, whose diff the second review lets through."""
    return {
        "reviewer:r1": review_line("r1", findings=2), "executor:runner-report-r1": review_report([finding("F1", "high"), finding("F2")]),
        "review-verifier:r1": verdicts(("r1-F1", "fix", "high", "check"), ("r1-F2", "note", "low", "none")),
        "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"}),
        "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix"),
        "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"]), final("h3", ["wt-fix"])]},
        "executor:runner-commits": R("c0ffee0 r1-F1\n"),
        "reviewer:r2": review_line("r2", findings=1), "executor:runner-report-r2": review_report([finding("F1", "low", claim="a nit")]),
        "review-verifier:r2": verdicts(("r2-F1", "dismiss", "none", None)),
    }


def check_fix(script, s):
    first = fix_scenario()
    rec, err = go(script, base={**green(), **first})
    rec = finish(s, "fix", rec, err)
    s.eq("fix: status", result(rec).get("status"), "done")
    s.eq("fix: one round, one fixer", (len(runner(rec, "fix-round")), len(launched(rec, "executor:fix-"))), (1, 1))
    fx = (launched(rec, "executor:fix-") or [{"prompt": "", "opts": {}}])[0]
    s.ok("fix: the fixer is given the finding under its unique id and not the one it was written with", "r1-F1" in fx["prompt"] and "\"id\": \"F1\"" not in fx["prompt"], fx["prompt"][:600])
    s.ok("fix: one commit per finding, each with its Fwx-Finding trailer", "Fwx-Finding" in fx["prompt"] and "one commit per finding" in fx["prompt"], fx["prompt"][:600])
    s.ok("fix: the finding that is a note is not given to the fixer", "r1-F2" not in fx["prompt"], fx["prompt"][:600])
    s.eq("fix: the fixer's isolation and model", (fx["opts"].get("isolation"), fx["opts"].get("model")), ("worktree", "m-fix"))
    ints = runner(rec, "integrate")
    s.ok("fix: integrate --findings with the unique id and --final", "--findings 'r1-F1'" in ints[2]["prompt"] and "--final" in ints[2]["prompt"] and "'wt-fix'" in ints[2]["prompt"], ints[2]["prompt"][-250:])
    s.ok("fix: the round is spent before the fixer starts", pos(rec, "executor:runner-fix-round") < pos(rec, "executor:fix-1"))
    s.eq("fix: the fix's diff is reviewed again, as pass 2", (len(launched(rec, "reviewer:")), launched(rec, "reviewer:")[-1]["label"]), (2, "reviewer:r2"))
    s.ok("fix: the second review is of the fix's diff, h2..h3, not the whole part", "h2" in launched(rec, "reviewer:")[1]["prompt"] and "h3" in launched(rec, "reviewer:")[1]["prompt"] and HEAD0 not in launched(rec, "reviewer:")[1]["prompt"],
         launched(rec, "reviewer:")[1]["prompt"][:400])
    f = details(rec).get("findings") or {}
    s.eq("fix: fixed lists the finding with its commit and severity", f.get("fixed"), [{"id": "r1-F1", "commit": "c0ffee0", "severity": "high"}])
    s.eq("fix: the F1 of the second pass does not collide with the first (a finding id repeats across rounds)", [d["id"] for d in f.get("dismissed", [])], ["r2-F1"])
    s.eq("fix: counts", (f.get("reported"), f.get("fix")), (3, 1))
    s.eq("fix: note kept", f.get("note"), [{"id": "r1-F2", "claim": "claim of F2"}])
    s.eq("fix: details.rounds", details(rec).get("rounds"), "1/3")

    # the same, the second round's finding being fixed too: ids stay unique
    again = {**first,
             "review-verifier:r2": verdicts(("r2-F1", "fix", "low", "code")),
             "executor:runner-fix-round": {"$seq": [R({"ok": True, "spent": True, "rounds": "1/3"}), R({"ok": True, "spent": True, "rounds": "2/3"})]},
             "executor:fix-2": exec_line("fix-2"), "executor:runner-report-fix-2": exec_report("wt-fix2"),
             "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"]), final("h3", ["wt-fix"]), final("h4", ["wt-fix2"])]},
             "reviewer:r3": review_line("r3"), "executor:runner-report-r3": review_report(), "executor:runner-commits": {"$seq": [R("c0ffee0 r1-F1\n"), R("beef000 r2-F1\n")]}}
    rec, err = go(script, base={**green(), **again})
    rec = finish(s, "second fix", rec, err)
    ints = runner(rec, "integrate")
    s.ok("second fix: integrate --findings r2-F1, not F1 again", len(ints) == 4 and "--findings 'r2-F1'" in ints[3]["prompt"], repr([i["prompt"][-100:] for i in ints]))
    s.eq("second fix: both fixes are listed", [d["id"] for d in (details(rec).get("findings") or {}).get("fixed", [])], ["r1-F1", "r2-F1"])
    s.eq("second fix: two rounds", len(runner(rec, "fix-round")), 2)

    # a fixer branch that does not merge as one commit per finding is a failure of the fixer's, not an exit
    rec, err = go(script, base={**green(), **first, "executor:runner-integrate": {"$seq": [
        integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"]),
        integ("h2", [], ok=False, findings_check={"ok": False, "problems": ["commit abc carries r1-F1 and r1-F3: one commit per finding"]}),
        final("h3", ["wt-fix-b"])]},
        "executor:runner-fix-round": {"$seq": [R({"ok": True, "rounds": "1/3"}), R({"ok": True, "rounds": "2/3"})]},
        "executor:fix-2": exec_line("fix-2"), "executor:runner-report-fix-2": exec_report("wt-fix-b")})
    rec = finish(s, "findings check", rec, err)
    s.eq("findings check: a second round and a second fixer", (len(runner(rec, "fix-round")), len(launched(rec, "executor:fix-"))), (2, 2))
    s.ok("findings check: the second fixer is told what was wrong", "one commit per finding" in launched(rec, "executor:fix-")[1]["prompt"] and "abc carries" in launched(rec, "executor:fix-")[1]["prompt"],
         launched(rec, "executor:fix-")[1]["prompt"][:700])
    s.ok("findings check: and integrate asks for the findings again", "--findings 'r1-F1'" in runner(rec, "integrate")[3]["prompt"], runner(rec, "integrate")[3]["prompt"][-200:])

    # three rounds gone: no fixer, failed
    rec, err = go(script, base={**green(), **first, "executor:runner-fix-round": R({"ok": False, "spent": False, "rounds": "3/3"}, 1)})
    rec = finish(s, "fix exhausted", rec, err)
    s.eq("fix with the rounds spent: failed, no fixer", (result(rec).get("status"), result(rec).get("reason"), launched(rec, "executor:fix-")), ("failed", "rounds exhausted", []))

    # control findings join the first review, and `--fix` makes the fixer the one task
    cf = [finding("CF1", "low", claim="a known false one")]
    rec, err = go(script, args_over=lambda a: a.update(control_findings=cf), answers_over={
        "review-verifier:r1": verdicts(("r1-CF1", "dismiss", "none", None))})
    rec = finish(s, "control findings", rec, err)
    s.ok("control findings: sent to the verifier with the reviewer's, under the pass prefix", len(launched(rec, "review-verifier:")) == 1 and "r1-CF1" in launched(rec, "review-verifier:")[0]["prompt"],
         repr(labels(rec)))
    s.eq("control findings: counted as reported, the false one dismissed", ((details(rec).get("findings") or {}).get("reported"), [d["id"] for d in (details(rec).get("findings") or {}).get("dismissed", [])]), (1, ["r1-CF1"]))


def check_fix_scope(script, s):
    """The fixer's brief is its prompt, so its SCOPE is in the prompt too: the finding's file and the files of the part's tasks (named in
    the plan), and a test file only where a task of the part lists tests. A UI task carries none (`brief.missing`: only a task with ui
    false must have ACCEPTANCE and VERIFY), and `args` has the id and the `ui` flag of every task and the path of the plan, but no brief
    path the fixer may be given (the scratch check above keeps every path under the run's git folder out of its prompt).

    Red before the fix (the fixer prompt of a part whose tasks are all UI, `tests: []`; first line of each FAIL, the prompt follows it):
      FAIL: fixer scope (no task lists tests): a SCOPE line names the finding's file and the plan's files of the part's tasks: You are the fixer of run ...
      FAIL: fixer scope (no task lists tests): no unconditional test demand in the goal: You are the fixer of run ... GOAL: fix each finding below, one commit per finding, the test in that commit and seen failing first. ...
      FAIL: fixer scope (no task lists tests): no test file, and the report says so and why: You are the fixer of run ...
      FAIL: fixer scope (gate red, no task lists tests): the test rule follows the part: ... GOAL: make this failure pass, test first when a test can express it. ...
      (and, with tests listed, FAIL: fixer scope (tests listed): a SCOPE line names the finding's file ... : the SCOPE line was missing)
      FAIL: agents: ... got ['executor: the test of a fix has no exception for a UI task or a plan that lists no tests'], want []
    A first version that named the briefs in the SCOPE line went red on the older check `scratch: the fixer is given no path under .git`."""
    def ui(on):
        def edit(a):
            for w in a["waves"]:
                for t in w["tasks"]:
                    t["ui"] = on
        return edit

    def fixer(over, what):
        rec, err = go(script, args_over=over, base={**green(), **fix_scenario()})
        rec = finish(s, "fixer scope, " + what, rec, err)
        return (launched(rec, "executor:fix-") or [{"prompt": ""}])[0]["prompt"]

    for what, over, tests in (("tests listed", ui(False), True), ("no task lists tests", ui(True), False)):
        p = fixer(over, what)
        s.ok("fixer scope (%s): a SCOPE line names the finding's file and the plan's files of the part's tasks" % what,
             re.search(r"^SCOPE: .*finding.*plan\.md.*T1, T2, T3", p, re.M) is not None, p[:900])
        s.ok("fixer scope (%s): the fixer is told to write no other path" % what, re.search(r"^SCOPE: .*no other path", p, re.M) is not None, p[:900])
        if tests:
            s.ok("fixer scope (%s): the test in the commit, seen failing first, is still asked for" % what,
                 "the test in that commit and seen failing first" in p, p[:900])
            s.ok("fixer scope (%s): a test file only where a task lists tests" % what, "no test file" not in p, p[:900])
        else:
            s.ok("fixer scope (%s): no unconditional test demand in the goal" % what,
                 "the test in that commit" not in p and "seen failing first" not in p, p[:900])
            s.ok("fixer scope (%s): no test file, and the report says so and why" % what,
                 "write no test file" in p and "could_not_run" in p, p[:900])
    # args with no task at all: nothing says the part lists no tests, so the old demand stands (a missing fact is not "no tests")
    rec, err = go(script, args_over=lambda a: a.update(waves=[], done=[], **{"from": "gate"}), base={**green(), **fix_scenario(),
                  "executor:runner-integrate": {"$seq": [final("h2", []), final("h3", ["wt-fix"])]}})
    rec = finish(s, "fixer scope, no task in args", rec, err)
    p = (launched(rec, "executor:fix-") or [{"prompt": ""}])[0]["prompt"]
    s.ok("fixer scope (no task in args): the test is still asked for", "the test in that commit and seen failing first" in p and "write no test file" not in p, p[:900])
    # a failing gate or a refused merge sends the plain fixer (no finding): same scope, same rule on tests
    for what, over, tests in (("gate red, tests listed", ui(False), True), ("gate red, no task lists tests", ui(True), False)):
        rec, err = go(script, args_over=over, answers_over={
            "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"], rc=1), final("h3", ["wt-fix"])]},
            "executor:runner-fix-round": R({"ok": True, "spent": False, "rounds": "1/3", "why": "w"}),
            "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix")})
        rec = finish(s, "fixer scope, " + what, rec, err)
        p = (launched(rec, "executor:fix-") or [{"prompt": ""}])[0]["prompt"]
        s.ok("fixer scope (%s): a SCOPE line, without the finding's file it has none" % what,
             re.search(r"^SCOPE: .*plan\.md.*T1, T2, T3", p, re.M) is not None and not re.search(r"^SCOPE: .*finding", p, re.M), p[:900])
        s.ok("fixer scope (%s): the test rule follows the part" % what,
             ("test first when a test can express it" in p and "no test file" not in p) if tests else ("test first" not in p and "write no test file" in p), p[:900])


def check_wave_base(script, s):
    """3.4 U8 fix, F1: a later wave's worktrees are born from the phase head after the earlier wave merged, so the sha they check
    is the head when their wave launches (what the last `integrate` returned), never the one `prepare` saw. The check itself is
    still exact (`fwx base`, tests/test_wave_prepare.py): a base that is not the head is `wrong-base`."""
    rec, err = go(script)
    rec = finish(s, "wave base", rec, err)

    def says(label):
        p = launched(rec, label)[0]["prompt"]
        return re.findall(r"`fwx base (\S+)`", p), p
    for tid in ("T1", "T2"):
        got, p = says("executor:" + tid)
        s.eq("wave base: wave 1's %s checks the head at prepare (%s)" % (tid, HEAD0[:7]), got, [HEAD0])
    got, p = says("executor:T3")
    s.eq("wave base: wave 2's T3 checks the head after wave 1's merge (the sha its worktree is born from), not prepare's (a two-wave plan ran wrong-base)", got, ["h1"])
    s.ok("wave base: the prompt says it replaces any other base", "BASE:" in p, p)

    def attempts(a):
        a["models"]["executor"]["T3"] = "m-t3"
    rec, err = go(script, answers_over={
        "executor:T3": {"$seq": [exec_line("T3", "failed"), exec_line("T3")]},
        "executor:runner-report-T3": {"$seq": [exec_report("wt-t3", "failed", reason="x"), exec_report("wt-t3b")]},
        "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"})})
    rec = finish(s, "wave base, new attempt", rec, err)
    s.eq("wave base: a new attempt of a wave-2 task checks the same head", [re.findall(r"fwx base (\S+)`", l["prompt"]) for l in launched(rec, "executor:T3")], [["h1"], ["h1"]])

    def fixmode(a):
        a["fix"] = {"source": "/work/findings.json", "findings": [finding("W1", "high")], "brief": RUN_DIR + "/briefs/_fix.md"}
        for w in a["waves"]:
            for t in w["tasks"]:
                t["brief"] = None
    rec, err = go(script, args_over=fixmode, base={
        "executor:fix": exec_line("fix"), "executor:runner-report-fix": exec_report("wt-w"),
        "executor:runner-integrate": {"$seq": [final("h2", ["wt-w"])]},
        "reviewer:r1": review_line("r1"), "executor:runner-report-r1": review_report(), "executor:runner-cleanup": CLEAN_CLEANUP})
    rec = finish(s, "wave base, fix", rec, err)
    s.eq("wave base: the fixer of --fix checks the head at prepare", re.findall(r"fwx base (\S+)`", workers(rec)[0]["prompt"]), [HEAD0])


def check_scratch(script, s):
    """3.4 U8 fix, F2: no agent is told to write under .git (Claude Code asks permission for it under `acceptEdits` and refuses an
    isolated agent's write outside its worktree, and the `auto` classifier denied one fixer for building that path). Each one that
    has no brief file makes its scratch folder with `fwx scratch new RUN UNIT`, in its own worktree, and writes there."""
    run = os.path.basename(RUN_DIR)

    def told(name, launch, unit):
        p = launch["prompt"]
        s.ok("scratch: %s is told to run `fwx scratch new %s %s` and to use its tmp/ and report.json" % (name, run, unit),
             "`fwx scratch new %s %s`" % (run, unit) in p and "tmp/ inside that folder" in p and "report.json directly in that folder, not in tmp/" in p, p[-420:])
        s.ok("scratch: %s is given no path under .git and none in the old reports/ or tmp/ of the run (it wrote the report there, and was refused)" % name,
             ".git" not in p and "/reports/" not in p and RUN_DIR not in p, p)
    conflict = integ("h1", ["wt-t1"], ok=False, conflict={"branch": "wt-t2", "files": ["a.py"]})
    rec, err = go(script, answers_over={
        "executor:runner-integrate": {"$seq": [conflict, integ("h1r", ["wt-res"]), final("h2", ["wt-t3"])]},
        "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"}),
        "executor:resolve-1": exec_line("resolve-1"), "executor:runner-report-resolve-1": exec_report("wt-res")})
    rec = finish(s, "scratch, resolver", rec, err)
    told("the resolver", launched(rec, "executor:resolve-")[0], "resolve-1")
    rec, err = go(script, answers_over={
        "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"], ok=False, quick={"ran": True, "cmds": ["make quick"], "rc": 1}),
                                               integ("h1f", ["wt-fix"]), final("h2", ["wt-t3"])]},
        "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"}),
        "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix")})
    rec = finish(s, "scratch, fixer", rec, err)
    told("the fixer", launched(rec, "executor:fix-")[0], "fix-1")
    rec, err = go(script, args_over=lambda a: a.update(security={"needed": True, "why": "x"}), answers_over={
        "reviewer:r1": review_line("r1", findings=1), "executor:runner-report-r1": review_report([finding("F1")]),
        "security-reviewer:r1": review_line("r1", "security-reviewer"), "executor:runner-report-r1-sec": review_report(criteria=[]),
        "review-verifier:r1": verdicts(("r1-F1", "dismiss", "none", None))})
    rec = finish(s, "scratch, reviewers", rec, err)
    told("the reviewer", launched(rec, "reviewer:")[0], "r1")
    told("the security reviewer", launched(rec, "security-reviewer:")[0], "r1-sec")
    p = launched(rec, "review-verifier:")[0]["prompt"]
    s.ok("scratch: the verifier makes its TMPDIR with `fwx scratch new %s r1-verifier` and is told no path under .git" % run, "`fwx scratch new %s r1-verifier`" % run in p and ".git" not in p, p)
    s.ok("scratch: the executor of a task is told nothing of it (its brief says it) and nothing under .git is in its prompt but the brief's own path",
         ".git" not in launched(rec, "executor:T1")[0]["prompt"].replace(RUN_DIR + "/briefs/T1.md", ""), launched(rec, "executor:T1")[0]["prompt"])


def check_args_fix_and_revert(script, s):
    def fixmode(a):
        a["fix"] = {"source": "/work/findings.json", "findings": [finding("W1", "high"), finding("W2")], "brief": RUN_DIR + "/briefs/_fix.md"}
        for w in a["waves"]:
            for t in w["tasks"]:
                t["brief"] = None
    rec, err = go(script, args_over=fixmode, base={
        "executor:fix": exec_line("fix"), "executor:runner-report-fix": exec_report("wt-w"),
        "executor:runner-integrate": {"$seq": [final("h2", ["wt-w"])]},
        "reviewer:r1": review_line("r1"), "executor:runner-report-r1": review_report(), "executor:runner-cleanup": CLEAN_CLEANUP})
    rec = finish(s, "args.fix", rec, err)
    s.eq("args.fix: the only worker is the fixer, on the fixer's model", [(l["label"], l["opts"].get("model")) for l in workers(rec)], [("executor:fix", "m-fix")])
    s.ok("args.fix: its prompt names the fix brief", RUN_DIR + "/briefs/_fix.md" in workers(rec)[0]["prompt"], workers(rec)[0]["prompt"])
    ints = runner(rec, "integrate")
    s.ok("args.fix: one integrate with the findings' ids and --final", len(ints) == 1 and "--findings 'W1,W2'" in ints[0]["prompt"] and "--final" in ints[0]["prompt"], repr([i["prompt"][-160:] for i in ints]))
    s.eq("args.fix: reviewed and done", (len(launched(rec, "reviewer:")), result(rec).get("status")), (1, "done"))

    def rev(a):
        a["revert"] = ["r1-F1", "r2-F1"]
    rec, err = go(script, args_over=rev, base={
        "executor:runner-revert": R({"ok": True, "head": "h5", "reverted": [{"id": "r2-F1", "commit": "c2", "revert": "h4"}, {"id": "r1-F1", "commit": "c1", "revert": "h5"}], "failed": None}),
        "executor:runner-verify": R({"sha": "h5", "clean": True, "source": "recipe", "commands": [{"cmd": "t", "rc": 0}], "rc": 0}),
        "executor:runner-cleanup": CLEAN_CLEANUP})
    rec = finish(s, "revert", rec, err)
    s.eq("revert: done, with no executor and no reviewer (--revert without a reviewer)", (result(rec).get("status"), workers(rec), launched(rec, "reviewer:"), launched(rec, "security-reviewer:")), ("done", [], [], []))
    s.ok("revert: the revert runner names the ids", "fwx wave revert --part-dir '/work/.fwx/phases/01-toy' --run '01-toy-ab12cd3-1' --findings 'r1-F1,r2-F1'" in runner(rec, "revert")[0]["prompt"],
         runner(rec, "revert")[0]["prompt"][-250:])
    s.ok("revert: then the gate on the new head", "fwx verify --json --dir '/work/.fwx/phases/01-toy'" in runner(rec, "verify")[0]["prompt"], runner(rec, "verify")[0]["prompt"][-200:])
    s.eq("revert: head from the revert, cleanup last", (details(rec).get("head"), last(rec)), ("h5", "executor:runner-cleanup"))
    rec, err = go(script, args_over=rev, base={
        "executor:runner-revert": R({"ok": False, "head": "h4", "reverted": [], "failed": {"id": "r2-F1", "commit": "c2", "files": ["a.py"]}}, 1),
        "executor:runner-cleanup": CLEAN_CLEANUP})
    rec = finish(s, "revert conflicts", rec, err)
    s.eq("a revert that conflicts: failed, no gate", (result(rec).get("status"), runner(rec, "verify")), ("failed", []))
    s.ok("a revert that conflicts: the reason names the finding", "r2-F1" in str(result(rec).get("reason")), repr(result(rec).get("reason")))


def check_gate_entry_and_stage(script, s):
    """3.4 align: the gate is the tree's n_C7 and runs in stage `reviewing`; `args.from == "gate"` re-enters there (n_C7F loops back)."""
    def stage_of(rec, label, nth):
        return (launched(rec, label) or Launches())[nth].get("phase")
    rec, err = go(script)
    rec = finish(s, "stage green", rec, err)
    s.eq("stage: the wave merge runs in executing, the gate (last wave's --final integrate) in reviewing (gate ran in executing)",
         [stage_of(rec, "executor:runner-integrate", 0), stage_of(rec, "executor:runner-integrate", 1)], ["executing", "reviewing"])
    s.eq("stage: one entry into each stage", rec.get("phases"), ["executing", "reviewing"])

    fixed = {"executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"], rc=1), final("h3", ["wt-fix"])]},
             "executor:runner-fix-round": R({"ok": True, "spent": False, "rounds": "1/3", "why": "w"}),
             "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix")}
    rec, err = go(script, answers_over=fixed)
    rec = finish(s, "stage gate red", rec, err)
    s.eq("stage: a red gate sends the fix to executing (n_C8 to n_C5) and the gate again to reviewing",
         (stage_of(rec, "executor:fix-", 0), stage_of(rec, "executor:runner-integrate", 2)), ("executing", "reviewing"))
    s.eq("stage: gate red, phases", rec.get("phases"), ["executing", "reviewing", "executing", "reviewing"])

    rec, err = go(script, base={**green(), **{
        "reviewer:r1": review_line("r1", findings=1), "executor:runner-report-r1": review_report([finding("F1", "high")]),
        "review-verifier:r1": verdicts(("r1-F1", "fix", "high", "check")),
        "executor:runner-fix-round": R({"ok": True, "spent": True, "rounds": "1/3", "why": "w"}),
        "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix"),
        "executor:runner-integrate": {"$seq": [integ("h1", ["wt-t1", "wt-t2"]), final("h2", ["wt-t3"]), final("h3", ["wt-fix"])]},
        "executor:runner-commits": R("c0ffee0 r1-F1\n"),
        "reviewer:r2": review_line("r2"), "executor:runner-report-r2": review_report()}})
    rec = finish(s, "stage review fix", rec, err)
    s.eq("stage: a review fix is made in executing and gated and reviewed in reviewing (n_C9 to n_C8 to n_C5 to n_C7)",
         (stage_of(rec, "executor:fix-", 0), stage_of(rec, "executor:runner-integrate", 2), stage_of(rec, "reviewer:", 1)), ("executing", "reviewing", "reviewing"))

    # re-entry at the gate: every task is on the phase branch, `from` is "gate"
    def gate_entry(a):
        a["done"] = ["T1", "T2", "T3"]
        a["from"] = "gate"
    entry = {"executor:runner-integrate": {"$seq": [final("h2", [])]}}
    rec, err = go(script, args_over=gate_entry, answers_over=entry)
    rec = finish(s, "from gate", rec, err)
    s.eq("from gate: the gate, then the review: done (a second run of finished tasks returned needs-owner)", (result(rec).get("status"), result(rec).get("reason")), ("done", ""))
    ints = runner(rec, "integrate")
    s.ok("from gate: one integrate, with --final and no --branches", len(ints) == 1 and "--final" in ints[0]["prompt"] and "--branches" not in ints[0]["prompt"],
         repr([i["prompt"][-200:] for i in ints]))
    s.eq("from gate: no executor, no fixer; one reviewer", (list(workers(rec)), len(launched(rec, "reviewer:"))), ([], 1))
    s.eq("from gate: the gate and the review run in reviewing, the reviewed range starts at the part's base",
         (rec.get("phases"), HEAD0 in launched(rec, "reviewer:")[0]["prompt"]), (["reviewing"], True))
    s.eq("from gate: cleanup is last", last(rec), "executor:runner-cleanup")
    s.eq("from gate: no executor, so no cap is read", [l["label"] for l in workers(rec)], [])

    rec, err = go(script, args_over=gate_entry, answers_over={**entry, "executor:runner-integrate": {"$seq": [final("h2", [], rc=1), final("h3", ["wt-fix"])]},
                                                                "executor:runner-fix-round": R({"ok": True, "spent": False, "rounds": "1/3", "why": "w"}),
                                                                "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix")})
    rec = finish(s, "from gate red", rec, err)
    s.eq("from gate: a red gate is fixed like any other (a fixer, the gate again, then the review)",
         (len(launched(rec, "executor:fix-")), len(runner(rec, "integrate")), result(rec).get("status")), (1, 2, "done"))

    rec, err = go(script, args_over=gate_entry, answers_over={"executor:runner-integrate": {"$seq": [final("h2", [], protected=["config/forge.json"], trusted=["ci.yml"])]}})
    rec = finish(s, "from gate trusted", rec, err)
    s.eq("from gate: a diff that edits the checks is for the owner here too, no review", (result(rec).get("status"), "ci.yml" in str(result(rec).get("reason")), list(launched(rec, "reviewer:"))),
         ("needs-owner", True, []))

    # without `from`, finished tasks are still nothing to execute, and the reason says how to go on
    rec, err = go(script, args_over=lambda a: a.update(done=["T1", "T2", "T3"]))
    rec = finish(s, "all done, no from", rec, err)
    s.ok("all done without `from`: needs-owner, and the reason is the whole command that goes on (the orchestrator loads no playbook)",
         result(rec).get("status") == "needs-owner" and "fwx wave new --part-dir '/work/.fwx/phases/01-toy' --plane session --branch 'phase-01' --from gate" in str(result(rec).get("reason")),
         repr(result(rec).get("reason")))


def agent_problems(texts):
    """What an agent file says about its input and its output, against what the script does: the reviewers get their brief inline
    and write a report file named in the prompt (one reply line), the verifier gets its brief inline and answers through the
    structured output (no file, no reply line)."""
    found = []
    for name in ("reviewer", "security-reviewer", "review-verifier"):
        text = texts.get(name, "")
        if re.search(r"brief file", text) and not re.search(r"no brief file", text):
            found.append("%s: names a brief file, the script gives the brief in the prompt" % name)
        if "Your prompt is your brief" not in text:
            found.append("%s: does not say its prompt is its brief" % name)
    for name in ("reviewer", "security-reviewer"):
        if "reviewed <report path>" not in texts.get(name, ""):
            found.append("%s: lost its one-line reply (`reviewed <report path> ...`)" % name)
    # readReview rejects a report where no finding contains the id of a criterion whose `met` is `no`
    if "must contain the criterion's `id`" not in texts.get("reviewer", ""):
        found.append("reviewer: is not told that a finding must contain the id of each criterion it marks `no` (the script rejects the report)")
    # a task executor reads a brief file; the fixer and the conflict resolver have none, their prompt is the brief
    if "no brief file" not in texts.get("executor", ""):
        found.append("executor: does not say that the fixer and the resolver have no brief file")
    # an isolated agent's Bash refuses compound commands and heredocs (measured, 3.4 U8 fix): the executor is told what to do instead
    if "plain, separate commands" not in texts.get("executor", ""):
        found.append("executor: is not told that an isolated agent's Bash refuses joined commands and heredocs (plain, separate commands, Write for files)")
    # a fix comes with its test, except where the task is UI or the plan lists no tests (a fixer wrote tests/x.test.mjs for a part with `tests: []`)
    if not re.search(r"The test goes in that same commit.*except where the task is UI or the plan lists no tests", texts.get("executor", "")):
        found.append("executor: the test of a fix has no exception for a UI task or a plan that lists no tests")
    v = texts.get("review-verifier", "")
    if "structured output" not in v:
        found.append("review-verifier: does not say it answers through the structured output")
    if re.search(r"verified <|report path|file your report", v):
        found.append("review-verifier: still writes a report file and replies with a line, the script reads neither")
    return found


def check_agents(s):
    texts = {}
    for name in ("reviewer", "security-reviewer", "review-verifier", "executor"):
        with open(os.path.join(ROOT, "agents", name + ".md"), encoding="utf-8") as f:
            texts[name] = f.read()
    s.eq("agents: reviewer, security-reviewer and review-verifier say what the script does (agents/*.md vs workflows/execute.js)", agent_problems(texts), [])
    old = {n: t.replace("Your prompt is your brief", "Your prompt names a brief file") for n, t in texts.items()}
    s.ok("agents: control, the old wording is found", len(agent_problems(old)) >= 3, repr(agent_problems(old)))
    s.ok("agents: control, a reviewer not told to put the criterion's id in a finding is found",
         any("criterion it marks" in p for p in agent_problems({**texts, "reviewer": texts["reviewer"].replace("must contain the criterion's `id`", "names the fault")})), "")
    s.ok("agents: control, an executor not told to run plain, separate commands is found",
         any("plain, separate" in p for p in agent_problems({**texts, "executor": texts["executor"].replace("plain, separate commands", "commands")})), "")
    s.ok("agents: control, an executor whose fix test has no exception is found",
         any("test of a fix" in p for p in agent_problems({**texts, "executor": texts["executor"].replace("except where the task is UI or the plan lists no tests", "always")})), "")
    s.ok("agents: control, an executor that knows no promptless fixer is found",
         any("executor" in p for p in agent_problems({**texts, "executor": texts["executor"].replace("no brief file", "no file")})), "")
    # what the script gives each one, so the agent files cannot drift from it
    rec, err = go(SCRIPT, answers_over={"security-reviewer:r1": review_line("r1", "security-reviewer"), "executor:runner-report-r1-sec": review_report(criteria=[])},
                  args_over=lambda a: a.update(security={"needed": True, "why": "x"}))
    rec = finish(s, "agents: prompts", rec, err)
    for label in ("reviewer:r1", "security-reviewer:r1"):
        p = (launched(rec, label) or Launches())[0]["prompt"]
        s.ok("agents: %s gets its brief in the prompt: range, intent files, its scratch folder for TMPDIR and report, no file to open" % label,
             all(x in p for x in ("DIFF:", "INTENT:", "Your TMPDIR is tmp/ inside that folder", "fwx scratch new %s %s" % (os.path.basename(RUN_DIR), "r1" if label.startswith("reviewer") else "r1-sec")))
             and "brief file" not in p.replace("no brief file", ""), p[:300])


def check_lint_and_shape(s):
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "lib", "fwx", "lint_models.py"), SCRIPT], capture_output=True, text=True)
    s.eq("lint: the script passes the model lint", r.returncode, 0)
    s.ok("lint: and it looked at the one script and its agent() call", "1 workflow file(s)" in r.stdout and "0 agent() call(s)" not in r.stdout, r.stdout[-200:])
    text = open(SCRIPT, encoding="utf-8").read() if os.path.exists(SCRIPT) else ""
    s.ok("no fork in the script", not re.search(r"fork", text.replace("fork", "", 0)) or "agentType: 'fork'" not in text)
    s.ok("the header names a referent in its first lines", any(l.startswith("// referent:") for l in text.splitlines()[:10]), text[:300])
    # the args the script expects are the ones `prepare` returns (C.3): the keys of the fixture are the keys of prepare's dict
    with open(os.path.join(ROOT, "lib", "fwx", "execute", "prepare.py"), encoding="utf-8") as f:
        src = f.read()
    tail = src[src.rindex("    return {"):]
    keys = set(re.findall(r'^\s+"(\w+)":', tail, re.M)) | set(re.findall(r'"(\w+)": ', tail.split("\n", 1)[1].split("\n    }")[0]))
    top = {k for k in fixture("args.json")}
    s.ok("args fixture: every top-level key of prepare's return is in the fixture", top <= keys and {"run", "plane", "waves", "models", "control_findings", "revert", "fix"} <= keys,
         "fixture-only %s, prepare-only %s" % (sorted(top - keys), sorted({"run", "plane", "waves", "models", "control_findings", "revert", "fix"} - keys)))


def peak(units):
    """The most of `units` (launches with a start and an end tick) running at one moment: at each start, the intervals that hold that tick."""
    return max([sum(1 for b in units if b["start"] <= a["start"] < b["end"]) for a in units] or [0])


def tasks_of(n):
    return [{"id": "T%d" % i, "type": "feature", "size": "normal", "ui": False, "brief": "%s/briefs/T%d.md" % (RUN_DIR, i), "trailer": "01-toy/T%d" % i}
            for i in range(1, n + 1)]


def one_wave(n, cap_value):
    """`args` edit: one wave of `n` tasks and the cap `cap_value` in `args.cap`; answers for them."""
    def edit(a):
        a["cap"] = cap_value
        a["waves"] = [{"n": 1, "serial": False, "tasks": tasks_of(n)}]
        a["models"]["executor"] = {"T%d" % i: "m-t%d" % i for i in range(1, n + 1)}
    return edit


def wave_answers(n):
    ans = {"executor:runner-integrate": {"$seq": [final("h2", ["wt-t%d" % i for i in range(1, n + 1)])]}}
    for i in range(1, n + 1):
        ans["executor:T%d" % i] = exec_line("T%d" % i)
        ans["executor:runner-report-T%d" % i] = exec_report("wt-t%d" % i)
        ans["executor:runner-setup-T%d" % i] = R("", 1)
    return ans


def check_fixed_cap(script, s):
    """The number of executors at once is `args.cap`, a fixed number of the configuration that `fwx wave new` prints (D90): no command is asked
    how many can start, nothing measures the RAM, and a cap that is not a positive whole number ends the run, never "all at once".

    Red on master (the script asked `fwx capacity` before each batch, and read nothing of `args.cap`):
      FAIL: cap 2, 5 tasks: never more than 2 executors at once, and as many as the cap and the tasks allow run together: got 3, want 2
      FAIL: cap 2, 5 tasks: no capacity command is run: ['executor:runner-capacity', 'executor:runner-capacity']
      FAIL: cap 0: no executor launched: got ['executor:T1', 'executor:T2', 'executor:T3'], want []
      FAIL: args fixture: every top-level key of prepare's return is in the fixture: fixture-only ['cap'], prepare-only []
    (the 3 is the old green answer's `allowed`, which master asked for; the fixture's `cap` is read by the prepare test as well)
    """
    for n, c, want in ((5, 2, 2), (5, 1, 1), (3, 8, 3)):
        name = "cap %d, %d tasks" % (c, n)
        rec, err = go(script, args_over=one_wave(n, c), answers_over=wave_answers(n))
        rec = finish(s, name, rec, err)
        ex = [l for l in launched(rec, "executor:T")]
        s.eq("%s: every task is launched once" % name, sorted(l["label"] for l in ex), sorted("executor:T%d" % i for i in range(1, n + 1)))
        s.eq("%s: never more than %d executors at once, and as many as the cap and the tasks allow run together" % (name, want), peak(ex), want)
        s.ok("%s: no capacity command is run" % name, not any("capacity" in l["label"] or "fwx capacity" in l["prompt"] for l in rec["launches"]),
             repr([l["label"] for l in rec["launches"] if "capacity" in l["label"] or "fwx capacity" in l["prompt"]]))
        s.eq("%s: done" % name, result(rec).get("status"), "done")
    # a serial wave is one at a time whatever the cap
    def serial(a):
        one_wave(3, 5)(a)
        a["waves"][0]["serial"] = True
    rec, err = go(script, args_over=serial, answers_over=wave_answers(3))
    rec = finish(s, "cap 5, serial wave", rec, err)
    s.eq("cap 5, serial wave: one executor at a time", peak(launched(rec, "executor:T")), 1)
    # no cap, or one that cannot be a cap: no executor starts and the run says so (never "unlimited"); the cleanup still runs
    for what, edit in (("missing", lambda a: a.pop("cap")), ("null", lambda a: a.update(cap=None)), ("0", lambda a: a.update(cap=0)),
                       ("negative", lambda a: a.update(cap=-2)), ("text", lambda a: a.update(cap="3")), ("a fraction", lambda a: a.update(cap=2.5)),
                       ("true", lambda a: a.update(cap=True))):
        rec, err = go(script, args_over=edit, answers_over=wave_answers(3))
        rec = finish(s, "cap %s" % what, rec, err)
        s.eq("cap %s: no executor launched" % what, [l["label"] for l in workers(rec)], [])
        s.eq("cap %s: failed" % what, result(rec).get("status"), "failed")
        s.ok("cap %s: failed with a reason that says cap, and where it comes from" % what,
             str(result(rec).get("reason", "")).startswith("cap:") and "wave new" in str(result(rec).get("reason", "")), repr(result(rec).get("reason")))
        s.ok("cap %s: cleanup still runs" % what, labels(rec)[-1:] == ["executor:runner-cleanup"], repr(labels(rec)))
    # the same on every entry path (review of PR 140): a run that enters at the gate launches a fixer after a red gate or a review finding, and the
    # cap must be checked before the first launch, not only in a wave or in --fix. Seen red on the head of PR 140:
    #   FAIL: cap missing, from gate with a red gate: no agent is launched before the cap is refused: got ['executor:runner-integrate', 'executor:runner-fix-round', 'executor:fix-1', ...]
    def gate_red(a):
        a["done"] = ["T1", "T2", "T3"]
        a["from"] = "gate"
    red = {"executor:runner-integrate": {"$seq": [final("h2", [], rc=1), final("h3", ["wt-fix"])]},
           "executor:runner-fix-round": R({"ok": True, "spent": False, "rounds": "1/3", "why": "w"}),
           "executor:fix-1": exec_line("fix-1"), "executor:runner-report-fix-1": exec_report("wt-fix")}
    for what, edit in (("missing", lambda a: a.pop("cap")), ("0", lambda a: a.update(cap=0))):
        def both(a, edit=edit):
            gate_red(a)
            edit(a)
        rec, err = go(script, args_over=both, answers_over=red)
        rec = finish(s, "cap %s, from gate with a red gate" % what, rec, err)
        s.eq("cap %s, from gate with a red gate: no agent is launched before the cap is refused" % what,
             [l["label"] for l in rec["launches"] if l["label"] != "executor:runner-cleanup"], [])
        s.ok("cap %s, from gate with a red gate: failed with a reason that says cap" % what,
             result(rec).get("status") == "failed" and str(result(rec).get("reason", "")).startswith("cap:"), repr(result(rec).get("reason")))


def check_all(script, s):
    check_fixed_cap(script, s)
    check_green(script, s)
    check_clash(script, s)
    check_executor_misses(script, s)
    check_setup_failed(script, s)
    check_join(script, s)
    check_gate(script, s)
    check_review(script, s)
    check_fix(script, s)
    check_fix_scope(script, s)
    check_args_fix_and_revert(script, s)
    check_wave_base(script, s)
    check_scratch(script, s)
    check_gate_entry_and_stage(script, s)


# (what is wrong with the script, text in it, text instead, the check that must go red). Each anchor is in the script exactly once.
MUTANTS = [
    ("a failed setup takes a round", "if (setupLine) return { end:", "if (false) return { end:", "FAIL: setup failed in an executor (session)"),
    ("the record is not read", "return j && typeof j.setup_failed === 'string' && j.setup_failed.trim() ? oneLine(j.setup_failed, 600) : null", "return null",
     "FAIL: setup failed, reason 'npm could not install'"),
    ("a failed setup at the join takes a round", "fail the same way.\n    if (typeof r.setup === 'string' && r.setup.trim())", "fail the same way.\n    if (false)",
     "FAIL: setup failed at the join (session)"),
    ("a failed setup after a revert takes the gate", "if (r.head) st.head = r.head\n    if (typeof r.setup === 'string' && r.setup.trim())", "if (r.head) st.head = r.head\n    if (false)",
     "FAIL: setup failed after a revert"),
    ("serial wave ignored", "rest.slice(0, wave.serial ? 1 : most)", "rest.slice(0, most)", "FAIL: clash: the two executors never run at once"),
    ("a cap that is no number is not refused", "if (!(Number.isInteger(A.cap) && A.cap > 0)) {", "if (false) {", "FAIL: cap missing: no executor launched"),
    ("the cap is not applied", "rest.slice(0, wave.serial ? 1 : most)", "rest.slice(0, wave.serial ? 1 : rest.length)",
     "FAIL: cap 2, 5 tasks: never more than 2 executors at once"),
    ("rounds not honoured", "if (r.ok !== true) return { end: ['failed', 'rounds exhausted'] }", "if (false) return { end: ['failed', 'rounds exhausted'] }",
     "FAIL: three attempts spent: failed, rounds exhausted"),
    ("conflict to the plain fixer", "const mine = await resolverJob(r.conflict, r.head)", "const mine = await fixerJob({ why: text, head: r.head })",
     "FAIL: conflict: the resolver ran (conflict sent to the plain fixer)"),
    ("a miss spends a round", "if (got) return { got }", "if (got) return { got }\n    await fixRound('a miss')", "FAIL: executor null once: no round spent"),
    ("empty string counted as done", "async function readExec(unit, reply) {", "async function readExec(unit, reply) {\n  if (reply === '') return { status: 'done', branch: 'wt-empty' }",
     "FAIL: executor empty string once"),
    ("second miss counted as done", "return { gap: true }", "return { got: { status: 'done', branch: 'wt-gap' } }", "FAIL: two nulls: failed"),
    ("unknown agentType retried", "if (/agent type .* not found/i.test(m)) return { fatal: m }", "if (false) return { fatal: m }", "FAIL: unknown agentType: not relaunched"),
    ("a report outside a scratch folder accepted", "if (!p.endsWith(reportTail(unit)) || /(^|\\/)\\.\\.(\\/|$)/.test(p)) return null", "", "FAIL: executor a report that is not there once"),
    ("a report of another unit accepted", "if (!p.endsWith(reportTail(unit)) ||", "if (!p.endsWith('/report.json') ||", "FAIL: executor the report of another unit once"),
    ("a path that climbs accepted", " || /(^|\\/)\\.\\.(\\/|$)/.test(p)) return null", ") return null", "FAIL: executor a path that climbs out of a scratch folder once"),
    ("the later wave checks prepare's base", "const launchBase = () => st.head || A.base", "const launchBase = () => A.base", "FAIL: wave base: wave 2's T3 checks the head after wave 1's merge"),
    ("the fixer writes under .git again", "'REPORT: run `fwx scratch new ' + RUN + ' ' + unit + '`:", "'REPORT: run `fwx scratch new ' + RUN + ' ' + unit + '` (the old place was /work/.git/fwx/runs/old/reports/x.json):",
     "FAIL: scratch: the resolver is given no path under .git"),
    ("trusted edit goes on", "if (Array.isArray(r.trusted) && r.trusted.length) {", "if (false) {", "FAIL: trusted: needs-owner"),
    ("verify rc 2 is failed on the session plane", "if (r.verify.rc !== 1) stop(A.plane === 'session' ? 'needs-owner' : 'failed',", "if (r.verify.rc !== 1) stop('failed',",
     "FAIL: verify rc 2 on the session plane"),
    ("protected path is done", "if (st.protected.length) stop('needs-owner', 'protected path: '", "if (false) stop('needs-owner', 'protected path: '",
     "FAIL: protected path (security needed: True)"),
    ("protected path skips the security review", "if ((A.security && A.security.needed) || st.protected.length > 0)", "if (A.security && A.security.needed)",
     "FAIL: protected path (security needed: False): the security reviewer ran"),
    ("reviewer's second miss is done", "return { end: ['failed', role + ' did not return'] }", "return { report: { looked_at: ['x'], findings: [], criteria: [] } }",
     "FAIL: reviewer null twice"),
    ("looked_at 0 accepted", "if (!m || Number(m[2]) === 0) return null", "if (!m) return null", "FAIL: looked_at 0"),
    ("every real finding is fixed", "if (d.verdict === 'fix') {", "if (d.verdict !== 'dismiss') {", "FAIL: no fix verdict: no fixer, no round (note finding was fixed)"),
    ("wrong-base is integrated", "if (rep.status === 'done') {", "if (rep.status === 'done' || rep.status === 'wrong-base') {", "FAIL: wrong-base:"),
    ("the last attempt is not passed on", "      prev = rep\n", "", "FAIL: wrong-base: the new attempt is told what the last one returned"),
    ("cleanup only after done", "st.cleanup = await run('cleanup',", "if (outcome[0] === 'done') st.cleanup = await run('cleanup',", "FAIL: cap missing: cleanup still runs"),
    ("the runner's rc decides", "const r = await run('integrate', cmd)",
     "const r0 = await exec('integrate', inCheckout(cmd))\n    const r = Object.assign(parseJson(r0.stdout), { ok: r0.rc === 0 })", "FAIL: rc 1 with ok true"),
    ("--revert reviewed", ["st.evidence)\n    return\n"], ["st.evidence)\n"], "FAIL: revert: done, with no executor and no reviewer"),
    ("catchable_by maybe allowed", "enum: ['code', 'check', 'rule', 'none']", "enum: ['code', 'check', 'rule', 'none', 'maybe']", "FAIL: verifier schema: catchable_by"),
    ("verdict ask allowed", "enum: ['fix', 'consider', 'note', 'dismiss']", "enum: ['fix', 'consider', 'note', 'dismiss', 'ask']", "FAIL: verifier schema: verdict"),
    ("finding ids not prefixed", "let id = tag + '-' + String(f.id)", "let id = String(f.id)", "FAIL: fix: the fixer is given the finding under its unique id"),
    ("--final on every wave", "(o.final ? ' --final' : '')", "' --final'", "FAIL: green: the first wave is not integrated with --final"),
    ("review fix not gated by the rounds", ["    if (fr.end) stop(fr.end[0], fr.end[1])\n    const before"], ["    const before"], "FAIL: fix with the rounds spent: failed, no fixer"),
    ("done tasks are launched again", "const tasks = wave.tasks.filter((t) => !done.has(t.id))", "const tasks = wave.tasks", "FAIL: done tasks: in a wave half done"),
    ("a criterion no needs no finding", "if (c.met === 'no' && !rep.findings.some", "if (false && !rep.findings.some", "FAIL: criterion no that no finding names"),
    ("control findings ignored", "if (tag === 'r1') (A.control_findings || []).forEach(take)", "", "FAIL: control findings"),
    ("the whole part is reviewed again", "    from = before\n", "    from = A.base\n", "FAIL: fix: the second review is of the fix's diff"),
    ("all done, the reason is no command", "' --from gate`, then execute again'", "' gate`'", "FAIL: all done without `from`: needs-owner, and the reason is the whole command"),
    ("the gate runs in executing", "    if (o.final) enter('reviewing')\n", "", "FAIL: stage: the wave merge runs in executing, the gate"),
    ("a fix after a red gate stays in reviewing", "    if (o.final) enter('executing')\n", "", "FAIL: stage: a red gate sends the fix"),
    ("a review fix is made in reviewing", "    enter('executing')\n    const mine", "    const mine", "FAIL: stage: a review fix is made"),
    ("from gate ignored", "  if (A.from === 'gate') {\n", "  if (false) {\n", "FAIL: from gate: the gate, then the review"),
    ("no branch still passes --branches", "(pending.length ? ' --branches ' + pending.map(sh).join(' ') : '')", "' --branches ' + pending.map(sh).join(' ')",
     "FAIL: from gate: one integrate, with --final and no --branches"),
    ("unproven rejected as malformed", "['yes', 'no', 'unproven'].includes(c.met)", "['yes', 'no'].includes(c.met)", "FAIL: criterion unproven"),
    ("the fixer has no SCOPE line", "  lines.push(scope.line)\n", "", "FAIL: fixer scope (tests listed): a SCOPE line names"),
    ("no task in args reads as no tests", "const tests = tasks.length === 0 || tasks.some((t) => !t.ui)", "const tests = tasks.some((t) => !t.ui)",
     "FAIL: fixer scope (no task in args): the test is still asked for"),
    ("the fixer's test is asked for whatever the part lists", "const tests = tasks.length === 0 || tasks.some((t) => !t.ui)", "const tests = true", "FAIL: fixer scope (no task lists tests): no unconditional test demand"),
    ("the fixer is never told to ask for the test", "(scope.tests ? ', the test in that commit and seen failing first' : '')", "''", "FAIL: fixer scope (tests listed): the test in the commit"),
]


def mutate(src, old, new):
    olds, news = (old, new) if isinstance(old, list) else ([old], [new])
    for o, n in zip(olds, news):
        if src.count(o) != 1:
            return None
        src = src.replace(o, n)
    return src


def check_controls(s):
    if not os.path.exists(SCRIPT):
        return
    with open(SCRIPT, encoding="utf-8") as f:
        src = f.read()
    for name, old, new, want in MUTANTS:
        m = mutate(src, old, new)
        if not s.ok("control %s: the anchor is in the script exactly once" % name, m is not None):
            continue
        mdir = helpers.mkdtemp("fwx-exmut-")
        try:
            sub = helpers.FirstFail(lambda f, want=want: f.startswith(want))  # the control reads one FAIL: the run stops at it
            sub.run(check_all, helpers.write(mdir, "execute.js", m), sub)
        finally:
            helpers.remove(mdir)
        s.ok("control %s: red with %r" % (name, want), any(f.startswith(want) for f in sub.fails), "got %r" % (sub.fails[:2],))
    good = helpers.Suite()
    check_all(SCRIPT, good)
    s.eq("control: the real script is green under the same checks", good.fails, [])


def main():
    s = helpers.Suite()
    if not shutil.which("node"):
        s.not_run("node is not on PATH")
    check_all(SCRIPT, s)
    check_lint_and_shape(s)
    check_agents(s)
    if not os.environ.get("FWX_EXEC_NESTED"):
        check_controls(s)
    s.done()


if __name__ == "__main__":
    main()
