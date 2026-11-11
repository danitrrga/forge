#!/usr/bin/env python3
"""workflows/ui-walk.js through tests/workflow_stub.mjs (3.5 U5): the app up, the tramos, the planted control, the walkers within
the quota, the verifiers, the control judge, and the close in a `finally`; plus the `recheck` mode.

referent: none, the script is this repo's own control flow; its test is the stub's scenarios (tests/workflow_stub.mjs, 3.4 U5a).

No network, no browser and no real agent: every `agent()` answer is a line of a scenario, so a run is a sequence of launches and
what the script put in their prompts. Needs `node`; without it `NOT RUN, NOT ARMED`, exit 77.

Red before the script existed (python3 tests/test_ui_walk_workflow.py, first lines; there was no workflows/ui-walk.js):
  FAIL: green: the script ran: rc 2, no record: workflow_stub: ENOENT: no such file or directory, open '.../workflows/ui-walk.js'
  FAIL: green: status: got None, want 'done'
  FAIL: not armed: status: got None, want 'done'

Red before `sizeQuota` (3.5 U3d; the quota stayed what `up` said for one tramo):
  FAIL: green: the quota is sized to the tramos: capacity is asked after the tramos are known and before the control and any walker: ['executor:runner-up', 'ui-verifier:tramos', 'executor:runner-arm-control', ...]
  FAIL: quota from the second ask: the walkers of the tramos run at once: [('ui-walker:T1-breaker', 7, 8), ('ui-walker:T1-critic', 9, 10), ...]
  FAIL: capacity ask rc 1: the quota stays what `up` allowed (3) and it is logged: ['ui-walk: ui-walker:T2-critic waits in the queue (quota 3, ...
  (the first two also in recheck: no capacity ask before the verifiers)

Red before the workflow read the refusal of arm-control's read-back (D14; the reason of `{"armed": false, "reason": ...}` was dropped):
  FAIL: control refused (no visible change): the run does not count, and the reason says which it was: 'The run does not count: the control could not be planted on http://localhost:3000/settings.'
  FAIL: control refused (target not found): the run does not count, and the reason says which it was: 'The run does not count: the control could not be planted on http://localhost:3000/settings.'

Controls (each on a copy of workflows/ui-walk.js with one branch taken out, `MUTANTS`; the anchor must be in the script exactly
once; the first matching FAIL line of each, seen red):
  the `finally` removed (scenario 1: the breaker of a tramo returns null):
      FAIL: breaker null: walk down not called after a walker returned nothing: ['ui-verifier:T1', 'ui-verifier:T2', 'executor:runner-save-T1', ...]
  the `recheck` branch removed (scenario 2: recheck with a fix.json):
      FAIL: recheck: no breaker or critic launched (critic launched in recheck): ['ui-walker:T1-breaker', 'ui-walker:T1-critic', ...]
  not armed carries on:      FAIL: not armed: status: got 'failed', want 'done'
  walkers not capped:        FAIL: quota 1: no two walkers at once: [('ui-walker:T1-breaker', 7, 12), ('ui-walker:T1-critic', 8, 13), ...]
  control armed too late:    FAIL: green: the control is armed before any walker: ['executor:runner-up', 'ui-verifier:tramos', 'ui-walker:T1-breaker', ...]
  a missing walker no gap:   FAIL: breaker null: failed, naming the walker: got ('done', False), want ('failed', True)
  a missed control counts:   FAIL: control missed: the reason says first that the run does not count: 'Run: the walkers did not find the fault planted on /settings.'
  an unwalked control judged: FAIL: control not walked: no judge launched, and the reason says the run does not count: ([..., 'ui-verifier:control', ...], ...)
  a down that exits 1 is done: FAIL: down fails: status failed, and the reason says browsers may be left: got ('done', False), want ('failed', True)
  Firefox critic for all:    FAIL: green: five walkers: a breaker and a critic per tramo, one more critic for Firefox: got [..., 'ui-walker:T1-firefox', ...]
  walkers told of the control: FAIL: green: no walker is told about the control: [...]
  recheck overwrites fix.json: FAIL: recheck: nothing overwrites fix.json (no `findings`), and the browsers are closed: [..., 'executor:runner-findings', ...]
  the walk keeps the quota `up` gave: FAIL: quota from the second ask: the walkers of the tramos run at once: [('ui-walker:T1-breaker', 7, 12), ...]
  a capacity that gives no answer drops the quota: FAIL: capacity ask rc 1: the quota stays what `up` allowed (3) and it is logged: [...]
  a raw tramo id in a path:  FAIL: unsafe tramo id: no launch or command carries the raw id: ['ui-walker:../x y-breaker', ...]
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
from test_execute_workflow import R, blank, finish, labels, launched, mutate, overlap, run_capped  # noqa: E402

ROOT = helpers.ROOT
VERIFIER_TEXT = os.path.join(ROOT, "agents", "ui-verifier.md")
SCRIPT = os.path.join(ROOT, "workflows", "ui-walk.js")
PHASE = "/srv/work/.fwx/phases/01-toy"
RUN_DIR = PHASE + "/ui-walk/1-1"
REPO = "/srv/work/wt"
APP = "http://localhost:3000"

ARGS = {
    "phase_dir": PHASE, "part": 1, "part_dir": PHASE + "/part-1", "plan": PHASE + "/plan.md", "context": PHASE + "/context.md",
    "decisions": PHASE + "/decisions.tsv", "config": "/srv/work/.claude/fwx.json", "work_branch": "fwx/toy", "repo": REPO,
    "base": "ab12cd34ab12cd34ab12cd34ab12cd34ab12cd34", "round": 1, "app": None,
    "models": {"breaker": "m-brk", "critic": "m-cri", "verifier": "m-ver", "runner": "m-run"},
    "recheck": None,
}
TRAMOS = [
    {"id": "T1", "screens": [{"url": "/settings", "states": ["empty", "dark"], "why": "the save bar", "reference": "demo/settings.png"}],
     "files": ["src/SaveBar.tsx"], "firefox": False},
    {"id": "T2", "screens": [{"url": "/billing", "states": ["with 3 items"], "why": "the invoice list", "reference": "/settings"}],
     "files": ["src/Invoices.tsx"], "firefox": True},
]
UP = {"armed": True, "run": "", "run_dir": RUN_DIR, "url": APP, "apps": [{"name": "walk-1-1-abc123", "url": APP, "run": ""}],
      "namespace": "walk-1-1-abc123", "capacity": {"role": "ui-walker", "want": 2, "allowed": 4}}
FINDINGS_OUT = {"fix_file": RUN_DIR + "/fix.json", "contradicted_file": RUN_DIR + "/contradicted.json",
                "counts": {"confirmed": 1, "plausible": 1, "contradicted": 0, "dropped": 1}}
SHOTS = "ok /srv/git/fwx/walks/walk-1-1-abc123/shots/s1.png %s/settings theme=light width=1440\nok /srv/git/fwx/walks/walk-1-1-abc123/shots/s2.png %s/billing theme=light width=1440\n" % (APP, APP)
DOWN = {"namespace": "walk-1-1-abc123", "run_dir": RUN_DIR, "looked": 31, "unreadable": 0, "left": [], "browsers_left": 0, "steps": []}


def verified(tramo, *rows):
    return {"findings": [dict({"id": "%s-%d" % (tramo, i + 1), "verdict": v, "severity": "minor", "file": "src/x.tsx", "line": 3, "claim": "claim",
                               "evidence": "e", "screen": "/settings", "steps": "1. open", "expected": "x", "type": "layout", "kind": "observed",
                               "why": "w"}, **({"clip": c} if c else {})) for i, (v, c) in enumerate(rows)]}


def green():
    """The answers of a run in which nothing goes wrong: two tramos (T2 asks for Firefox), a control found, a clean close."""
    return {
        "executor:runner-up": R(UP),
        "ui-verifier:tramos": json.dumps(TRAMOS),
        "executor:runner-capacity": R({"role": "ui-walker", "want": 4, "allowed": 4}),
        "executor:runner-arm-control": R({"screen": APP + "/settings", "path": "/settings", "kind": "hierarchy"}),
        "ui-walker:T1-breaker": "0 blocker, 1 minor\n%s/findings-w1.md\nthe save bar clips" % RUN_DIR,
        "ui-walker:T1-critic": "0 blocker, 0 minor\n%s/findings-w2.md\nnone" % RUN_DIR,
        "ui-walker:T2-breaker": "0 blocker, 0 minor\n%s/findings-w3.md\nnone" % RUN_DIR,
        "ui-walker:T2-critic": "0 blocker, 1 minor\n%s/findings-w4.md\nthe list" % RUN_DIR,
        "ui-walker:T2-firefox": "0 blocker, 0 minor\n%s/findings-w5.md\nnone" % RUN_DIR,
        "ui-verifier:T1": verified("T1", ("CONFIRMED", RUN_DIR + "/clip-1.webm"), ("NOT REPRODUCED", None)),
        "ui-verifier:T2": verified("T2", ("PLAUSIBLE", None)),
        "executor:runner-save-T1": R("saved"), "executor:runner-save-T2": R("saved"),
        "ui-verifier:control": {"screen": "/settings", "found": True, "finding": "T1-1", "why": "T1-1 says the title reads like body text"},
        "executor:runner-findings": R(FINDINGS_OUT),
        "executor:runner-screenshot": R(SHOTS),
        "executor:runner-coverage": R("saved"),
        "executor:runner-down": R(DOWN),
    }


def go(script, answers_over=None, args_over=None, answers=None):
    args = json.loads(json.dumps(ARGS))
    if callable(args_over):
        args_over(args)
    elif args_over:
        args.update(args_over)
    ans = answers if answers is not None else green()
    ans.update(answers_over or {})
    rc, rec, err = run_capped(script, {"args": args, "answers": ans})
    return rec, "rc %s, no record: %s" % (rc, err[-300:]) if rec is None else ""


def result(rec):
    return (rec or {}).get("result") or {}


def details(rec):
    return result(rec).get("details") or {}


def walkers(rec):
    return [l for l in rec["launches"] if l["opts"].get("agentType") == "fwx:ui-walker"]


BIG = 10 ** 6


def at(ls, label):
    """Where a label was first launched; past the end when it never was."""
    return ls.index(label) if label in ls else BIG


def runner(rec, step):
    return launched(rec, "executor:runner-" + step)


def check_green(script, s):
    rec, err = go(script)
    rec = finish(s, "green", rec, err)
    r = result(rec)
    s.eq("green: status", r.get("status"), "done")
    s.eq("green: reason", r.get("reason"), "")
    s.eq("green: phase_dir", r.get("phase_dir"), PHASE)
    s.eq("green: phases", rec.get("phases"), ["ui-walk"])
    s.eq("green: meta phases are the stage name", [p.get("title") for p in (rec.get("meta") or {}).get("phases", [])], ["ui-walk"])
    ls = labels(rec)
    s.eq("green: the app comes up first, then the tramos", ls[:2], ["executor:runner-up", "ui-verifier:tramos"])
    s.ok("green: the runner is told to keep stderr in a mktemp file it removes, never a fixed /tmp name (3.5 acceptance D9)",
         all("mktemp" in l["prompt"] and "never a fixed name in /tmp" in l["prompt"] for l in runner(rec, "up")), runner(rec, "up")[0]["prompt"][-300:])
    s.ok("green: the verifier is told a screenshot with no path lands in the run's captures folder and a /tmp path is refused (D8)",
         all("no path saves into the run's captures folder" in l["prompt"] and "A path in /tmp is refused" in l["prompt"] for l in launched(rec, "ui-verifier:T1")),
         (launched(rec, "ui-verifier:T1") or [{"prompt": ""}])[0]["prompt"][-400:])
    s.ok("green: the quota is sized to the tramos: capacity is asked after the tramos are known and before the control and any walker",
         at(ls, "ui-verifier:tramos") < at(ls, "executor:runner-capacity") < at(ls, "executor:runner-arm-control"), repr(ls))
    s.ok("green: capacity is asked for the run and the number of tramos (2)", "fwx walk capacity --run '%s' --tramos 2" % RUN_DIR in runner(rec, "capacity")[0]["prompt"],
         runner(rec, "capacity")[0]["prompt"][-300:])
    s.ok("green: the control is armed before any walker", at(ls, "executor:runner-arm-control") < min([at(ls, l) for l in ls if l.startswith("ui-walker:")] or [BIG]),
         repr(ls))
    s.eq("green: the close is findings, screenshot, coverage, down, in that order, and last", ls[-4:],
         ["executor:runner-findings", "executor:runner-screenshot", "executor:runner-coverage", "executor:runner-down"])
    s.ok("green: the control judge runs after every verifier and before the close",
         max(at(ls, "ui-verifier:T1"), at(ls, "ui-verifier:T2")) < at(ls, "ui-verifier:control") < at(ls, "executor:runner-findings"), repr(ls))
    s.eq("green: five walkers: a breaker and a critic per tramo, one more critic for Firefox", sorted(l["label"] for l in walkers(rec)),
         ["ui-walker:T1-breaker", "ui-walker:T1-critic", "ui-walker:T2-breaker", "ui-walker:T2-critic", "ui-walker:T2-firefox"])
    for l in rec["launches"]:
        o = l["opts"]
        role = l["label"].split(":")[0]
        s.ok("%s: model and agentType are named" % l["label"], bool(o.get("model")) and str(o.get("agentType", "")).startswith("fwx:"), repr(o))
        if l["label"].startswith("executor:runner-"):
            s.eq("%s: runner model, agentType, schema" % l["label"], (o.get("model"), o.get("agentType"), sorted((o.get("schema") or {}).get("required", []))),
                 ("m-run", "fwx:executor", ["rc", "stdout"]))
            s.ok("%s: no worktree" % l["label"], "isolation" not in o)
        elif role == "ui-walker":
            axis = "breaker" if l["label"].endswith("breaker") else "critic"
            s.eq("%s: model and agentType" % l["label"], (o.get("model"), o.get("agentType")), ({"breaker": "m-brk", "critic": "m-cri"}[axis], "fwx:ui-walker"))
    s.eq("green: the verifiers' model", {l["opts"]["model"] for l in launched(rec, "ui-verifier:T")}, {"m-ver"})
    s.eq("green: the control judge is the ui-verifier on the small model", (launched(rec, "ui-verifier:control")[0]["opts"].get("model"),
         launched(rec, "ui-verifier:control")[0]["opts"].get("agentType")), ("m-run", "fwx:ui-verifier"))
    up = runner(rec, "up")[0]["prompt"]
    s.ok("green: up is told the repo, the folder, the part and the round", "cd '%s' && fwx walk up --dir '%s' --part 1 --round 1 --repo '%s'" % (REPO, PHASE, REPO) in up
         and "--app" not in up, up[-300:])
    arm = runner(rec, "arm-control")[0]["prompt"]
    s.ok("green: the control is planted on the first screen of the first tramo, as a URL of the app and the run's folder",
         "fwx walk arm-control --run '%s' --screen '%s/settings'" % (RUN_DIR, APP) in arm, arm[-300:])
    ws = collections.defaultdict(str, {l["label"]: l["prompt"] for l in walkers(rec)})
    s.ok("green: a walker's session and findings file are its own", "w1" in ws["ui-walker:T1-breaker"] and RUN_DIR + "/findings-w1.md" in ws["ui-walker:T1-breaker"]
         and RUN_DIR + "/findings-w4.md" in ws["ui-walker:T2-critic"], ws["ui-walker:T1-breaker"][:400])
    s.ok("green: the walker is told its axis and its screens as URLs of the app", "breaker" in ws["ui-walker:T1-breaker"] and APP + "/settings" in ws["ui-walker:T1-breaker"],
         ws["ui-walker:T1-breaker"][:400])
    s.ok("green: the critic is given the reference of its screen", "demo/settings.png" in ws["ui-walker:T1-critic"], ws["ui-walker:T1-critic"][:400])
    s.ok("green: every walker command names the run (`--run`): without it two open runs refuse every call",
         all("fwx walk %s --run %s w" % ("pw" if k.endswith("firefox") else "ab", RUN_DIR) in p for k, p in ws.items()), repr([k for k, p in ws.items() if "--run" not in p]))
    vp = launched(rec, "ui-verifier:T1")[0]["prompt"]
    s.ok("green: the verifier is given the repo and `--run` for its browser", "REPO: " + REPO in vp and "fwx walk ab --run %s v1" % RUN_DIR in vp, vp[:600])
    s.ok("green: no walker is told about the control", all("control" not in p.lower() and "planted" not in p.lower() for p in ws.values()), repr([k for k, p in ws.items() if "control" in p.lower()]))
    s.ok("green: only the Firefox critic is sent to `fwx walk pw`", "fwx walk pw" in ws["ui-walker:T2-firefox"] and all(
         "fwx walk pw" not in p for k, p in ws.items() if k != "ui-walker:T2-firefox"), repr([k for k, p in ws.items() if "fwx walk pw" in p]))
    saves = runner(rec, "save-T1")[0]["prompt"]
    s.ok("green: a verifier's reply is saved as verified-<tramo>.json in the run's folder", RUN_DIR + "/verified-T1.json" in saves and "T1-1" in saves, saves[-300:])
    s.ok("green: the verifier is told the findings files of its tramo", RUN_DIR + "/findings-w1.md" in launched(rec, "ui-verifier:T1")[0]["prompt"]
         and RUN_DIR + "/findings-w3.md" not in launched(rec, "ui-verifier:T1")[0]["prompt"], launched(rec, "ui-verifier:T1")[0]["prompt"][:500])
    s.ok("green: findings, down name the run's folder", "fwx walk findings --run '%s'" % RUN_DIR in runner(rec, "findings")[0]["prompt"]
         and "fwx walk down --run '%s'" % RUN_DIR in runner(rec, "down")[0]["prompt"])
    shot = runner(rec, "screenshot")[0]["prompt"]
    s.ok("green: screenshot is given the walked screens", "fwx screenshot --run '%s' --screens " % RUN_DIR in shot and APP + "/settings" in shot and APP + "/billing" in shot, shot[-400:])
    d = details(rec)
    s.eq("green: details keys", sorted(d), sorted(["run_dir", "fix_file", "counts", "contradicted_file", "control", "coverage_file", "shots", "clips", "down_file", "outside",
                                                 "recheck", "gaps", "agents"]))
    s.eq("green: details.run_dir, fix_file, contradicted_file, down_file, coverage_file", (d.get("run_dir"), d.get("fix_file"), d.get("contradicted_file"), d.get("down_file"), d.get("coverage_file")),
         (RUN_DIR, RUN_DIR + "/fix.json", RUN_DIR + "/contradicted.json", RUN_DIR + "/down.json", RUN_DIR + "/coverage.md"))
    s.eq("green: details.counts are what `findings` printed", d.get("counts"), FINDINGS_OUT["counts"])
    s.eq("green: details.control", d.get("control"), {"screen": "/settings", "found": True, "finding": "T1-1"})
    s.eq("green: details.shots are the paths the screenshots were written to", d.get("shots"), [
         "/srv/git/fwx/walks/walk-1-1-abc123/shots/s1.png", "/srv/git/fwx/walks/walk-1-1-abc123/shots/s2.png"])
    s.eq("green: details.clips are the clip paths of the kept findings", d.get("clips"), [RUN_DIR + "/clip-1.webm"])
    s.eq("green: details.agents counts every launch, details.gaps is empty", (d.get("agents"), d.get("gaps")), (len(rec["launches"]), []))
    s.ok("green: no finding text in the result", "claim" not in json.dumps(result(rec)) and "the save bar clips" not in json.dumps(result(rec)), json.dumps(result(rec))[:300])


def check_not_armed(script, s):
    rec, err = go(script, answers={"executor:runner-up": R({"armed": False, "reason": "no app_run in the project's configuration and no --app"})})
    rec = finish(s, "not armed", rec, err)
    r = result(rec)
    s.eq("not armed: status", r.get("status"), "done")
    s.ok("not armed: the reason starts with NOT RUN, NOT ARMED and says why", str(r.get("reason")).startswith("NOT RUN, NOT ARMED: ") and "no app_run" in str(r.get("reason")), repr(r.get("reason")))
    s.eq("not armed: nothing else launched", labels(rec), ["executor:runner-up"])
    s.eq("not armed: phase_dir", r.get("phase_dir"), PHASE)


def check_up_fails(script, s):
    rec, err = go(script, answers={"executor:runner-up": R("", 2)})
    rec = finish(s, "up refused", rec, err)
    s.eq("up refused: status failed, nothing else launched", (result(rec).get("status"), labels(rec)), ("failed", ["executor:runner-up"]))


def check_breaker_null(script, s):
    """Scenario 1: the breaker of a tramo returns nothing. The run is failed (a gap does not count as a pass), the other walkers' work is
    kept, and the browsers are closed all the same."""
    rec, err = go(script, answers_over={"ui-walker:T1-breaker": None})
    rec = finish(s, "breaker null", rec, err)
    ls = labels(rec)
    s.ok("breaker null: walk down not called after a walker returned nothing", "executor:runner-down" in ls, repr(ls[-5:]))
    s.eq("breaker null: the breaker was launched once more and no more", ls.count("ui-walker:T1-breaker"), 2)
    s.eq("breaker null: failed, naming the walker", (result(rec).get("status"), "T1-breaker" in str(result(rec).get("reason"))), ("failed", True))
    s.ok("breaker null: the tramo is still verified from its critic's file and the findings are still collected", "ui-verifier:T1" in ls and "executor:runner-findings" in ls, repr(ls))
    s.ok("breaker null: the gap is in details", any("T1-breaker" in g for g in details(rec).get("gaps", [])), repr(details(rec).get("gaps")))


def check_down_fails(script, s):
    rec, err = go(script, answers_over={"executor:runner-down": R(DOWN, 1)})
    rec = finish(s, "down fails", rec, err)
    s.eq("down fails: status failed, and the reason says browsers may be left", (result(rec).get("status"), "down.json" in str(result(rec).get("reason"))), ("failed", True))
    rec, err = go(script, answers_over={"executor:runner-down": None})
    rec = finish(s, "down null", rec, err)
    s.eq("down null: status failed", result(rec).get("status"), "failed")


def check_control(script, s):
    rec, err = go(script, answers_over={"ui-verifier:control": {"screen": "/settings", "found": False, "finding": None, "why": "nothing about the title"}})
    rec = finish(s, "control missed", rec, err)
    r = result(rec)
    s.eq("control missed: still done, found false", (r.get("status"), details(rec).get("control", {}).get("found")), ("done", False))
    s.ok("control missed: the reason says first that the run does not count", str(r.get("reason")).lower().startswith("the run does not count"), repr(r.get("reason")))
    # the critic of the control tramo never returned: the control tramo was not walked, so found is null without a judge
    rec, err = go(script, answers_over={"ui-walker:T1-critic": None})
    rec = finish(s, "control not walked", rec, err)
    r = result(rec)
    s.eq("control not walked: found null", details(rec).get("control", {}).get("found"), None)
    s.ok("control not walked: no judge launched, and the reason says the run does not count", "ui-verifier:control" not in labels(rec)
         and str(r.get("reason")).lower().startswith("the run does not count"), repr((labels(rec)[-6:], r.get("reason"))))
    rec, err = go(script, answers_over={"executor:runner-arm-control": R("", 2)})
    rec = finish(s, "control not armed", rec, err)
    s.ok("control not armed: found null, the run does not count, the walk went on",
         details(rec).get("control", {}).get("found") is None and str(result(rec).get("reason")).lower().startswith("the run does not count") and len(walkers(rec)) == 5,
         repr((result(rec).get("reason"), len(walkers(rec)))))
    # D14: arm-control reads the plant back and refuses (exit 1, `{"armed": false, "reason": ...}` on stdout) when the target is not there or
    # the plant changes nothing. The control is then not armed, no judge runs, found is never true, and the result says which of the two it was.
    for why in ("no visible change on %s/settings: the `h1` has font-size 16px and font-weight 400 with and without the plant" % APP,
                "target not found on %s/settings: no `h1` after 30 s, so a plant there would change nothing" % APP):
        tag = why.split(" on ")[0]
        rec, err = go(script, answers_over={"executor:runner-arm-control": R({"armed": False, "reason": "arm-control: " + why}, 1)})
        rec = finish(s, "control refused: " + tag, rec, err)
        r = result(rec)
        s.ok("control refused (%s): not armed: no judge, found null (never true), the walk went on" % tag,
             "ui-verifier:control" not in labels(rec) and details(rec).get("control", {}).get("found") is None and len(walkers(rec)) == 5,
             repr((labels(rec)[-4:], details(rec).get("control"))))
        s.ok("control refused (%s): the run does not count, and the reason says which it was" % tag,
             str(r.get("reason")).lower().startswith("the run does not count") and tag in str(r.get("reason")), repr(r.get("reason")))


def check_quota(script, s):
    def cap(n, up_n=None):
        """`up` allows `up_n` (it was asked for one tramo), the second ask for the real tramos allows `n`."""
        up = json.loads(json.dumps(UP))
        up["capacity"]["allowed"] = n if up_n is None else up_n
        return {"executor:runner-up": R(up), "executor:runner-capacity": R({"role": "ui-walker", "want": 4, "allowed": n})}
    rec, err = go(script, answers_over=cap(1))
    rec = finish(s, "quota 1", rec, err)
    w = walkers(rec)
    s.eq("quota 1: every walker still runs", len(w), 5)
    s.ok("quota 1: no two walkers at once", not any(overlap(a, b) for i, a in enumerate(w) for b in w[i + 1:]),
         repr([(x["label"], x["start"], x["end"]) for x in w]))
    s.ok("quota 1: what stays queued is logged", any("queue" in l and "quota 1" in l for l in rec["logs"]), repr(rec["logs"]))
    rec, err = go(script, answers_over=cap(5))
    rec = finish(s, "quota 5", rec, err)
    w = walkers(rec)
    s.ok("quota 5: the walkers of the two tramos run at once", any(overlap(a, b) for i, a in enumerate(w) for b in w[i + 1:]), repr([(x["label"], x["start"], x["end"]) for x in w]))
    # `up` is run before the tramos are known, so its capacity is for one tramo (a quota of 2 at most): the quota is the second ask's.
    # Red before the second ask (a quota that stayed at what `up` said, 1, with the second ask allowing 5):
    #   FAIL: quota from the second ask: the walkers of the tramos run at once: [('ui-walker:T1-breaker', 7, 12), ('ui-walker:T1-critic', 8, 13), ...]
    rec, err = go(script, answers_over=cap(5, up_n=1))
    rec = finish(s, "quota from the second ask", rec, err)
    w = walkers(rec)
    s.ok("quota from the second ask: the walkers of the tramos run at once", any(overlap(a, b) for i, a in enumerate(w) for b in w[i + 1:]), repr([(x["label"], x["start"], x["end"]) for x in w]))
    s.ok("quota from the second ask: more than the 2 `up` would have allowed run at once", max(sum(1 for b in w if overlap(a, b)) + 1 for a in w) > 2,
         repr([(x["label"], x["start"], x["end"]) for x in w]))
    # a second ask that does not answer leaves the quota `up` gave, said
    for what, ans in (("rc 1", R("", 1)), ("no answer", None), ("not JSON", R("nope"))):
        over = cap(1, up_n=3)
        over["executor:runner-capacity"] = ans
        rec, err = go(script, answers_over=over)
        rec = finish(s, "capacity ask %s" % what, rec, err)
        w = walkers(rec)
        s.ok("capacity ask %s: the quota stays what `up` allowed (3) and it is logged" % what,
             any("capacity" in l and "quota of 3" in l for l in rec["logs"]) and any(overlap(a, b) for i, a in enumerate(w) for b in w[i + 1:]) and len(w) == 5,
             repr(rec["logs"][-4:]))
    rec, err = go(script, answers_over={"executor:runner-up": R(dict(UP, capacity={"role": "ui-walker", "want": 2, "allowed": 0})),
                                        "executor:runner-capacity": R({"role": "ui-walker", "want": 4, "allowed": 0})})
    rec = finish(s, "quota 0", rec, err)
    s.eq("quota 0: a quota of 0 is read as 1, with a log line", (len(walkers(rec)), any("quota" in l for l in rec["logs"])), (5, True))


def check_tramos(script, s):
    rec, err = go(script, answers_over={"ui-verifier:tramos": "[]"})
    rec = finish(s, "no tramo", rec, err)
    s.eq("no tramo: failed and the browsers closed", (result(rec).get("status"), "executor:runner-down" in labels(rec), walkers(rec)), ("failed", True, []))
    rec, err = go(script, answers_over={"ui-verifier:tramos": None})
    rec = finish(s, "tramos null", rec, err)
    s.eq("tramos null: failed and the browsers closed", (result(rec).get("status"), "executor:runner-down" in labels(rec)), ("failed", True))
    fenced = "```json\n%s\n```" % json.dumps(TRAMOS)
    rec, err = go(script, answers_over={"ui-verifier:tramos": fenced})
    rec = finish(s, "fenced tramos", rec, err)
    s.eq("fenced tramos: the list is read from inside a code fence", (result(rec).get("status"), len(walkers(rec))), ("done", 5))
    # a tramo id that is not a safe file name is renamed, never used in a path
    bad = json.loads(json.dumps(TRAMOS))
    bad[0]["id"] = "../x y"
    rec, err = go(script, answers_over={"ui-verifier:tramos": json.dumps(bad)}, answers={**green(), "ui-walker:T1-breaker": "x", "ui-walker:T1-critic": "x",
                                                                                                   "ui-verifier:T1": verified("T1", ("CONFIRMED", None))})
    rec = finish(s, "unsafe tramo id", rec, err, allow_unanswered=True)
    s.ok("unsafe tramo id: no launch or command carries the raw id", all("../x y" not in l["prompt"] for l in rec["launches"]), repr([l["label"] for l in rec["launches"] if "../x y" in l["prompt"]]))


def check_verify(script, s):
    bad = {"findings": [{"id": "T1-1", "verdict": "MAYBE"}]}
    rec, err = go(script, answers_over={"ui-verifier:T1": bad})
    rec = finish(s, "verifier schema", rec, err, allow_unanswered=True)
    s.ok("verifier schema: a verdict outside the list breaks the schema, so it is a miss", any(l["answer"] == "schema" for l in launched(rec, "ui-verifier:T1")),
         repr([l["answer"] for l in launched(rec, "ui-verifier:T1")]))
    rec, err = go(script, answers_over={"ui-verifier:T1": None})
    rec = finish(s, "verifier null", rec, err)
    s.eq("verifier null: launched once more, then a gap and a failed run", (len(launched(rec, "ui-verifier:T1")), result(rec).get("status"), "executor:runner-down" in labels(rec)),
         (2, "failed", True))
    rec, err = go(script, answers_over={"executor:runner-save-T1": R("", 1)})
    rec = finish(s, "save fails", rec, err)
    s.ok("save fails: a verified file that was not written is a gap", result(rec).get("status") == "failed" and any("T1" in g for g in details(rec).get("gaps", [])), repr(details(rec).get("gaps")))


def check_recheck(script, s):
    """Scenario 2: recheck with a fix.json. Only verifiers; no breaker, no critic, no tramos agent, no control."""
    fixes = [dict(verified("T1", ("CONFIRMED", None))["findings"][0]), dict(verified("T2", ("PLAUSIBLE", None))["findings"][0])]
    ans = green()
    ans.update({"executor:runner-read-fix": R(json.dumps(fixes)),
                "ui-verifier:T1": {"findings": [dict(fixes[0], verdict="NOT REPRODUCED", evidence_after="/srv/shots/after-1.png")]},
                "ui-verifier:T2": {"findings": [dict(fixes[1], verdict="PLAUSIBLE", evidence_after="/srv/shots/after-2.png")]},
                "executor:runner-save-T1": R("saved"), "executor:runner-save-T2": R("saved")})
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers=ans)
    rec = finish(s, "recheck", rec, err)
    ls = labels(rec)
    s.ok("recheck: no breaker or critic launched (critic launched in recheck)", walkers(rec) == [], repr([l for l in ls if l.startswith("ui-walker")]))
    s.ok("recheck: no tramos agent, no control, no judge", not any(l in ls for l in ("ui-verifier:tramos", "executor:runner-arm-control", "ui-verifier:control")), repr(ls))
    s.ok("recheck: one verifier per tramo of the fix.json", "ui-verifier:T1" in ls and "ui-verifier:T2" in ls, repr(ls))
    s.ok("recheck: capacity is asked for the 2 tramos of the fix.json, before their verifiers", "fwx walk capacity --run '%s' --tramos 2" % RUN_DIR in runner(rec, "capacity")[0]["prompt"]
         and at(ls, "executor:runner-capacity") < at(ls, "ui-verifier:T1"), repr(ls))
    s.eq("recheck: the fix.json is read by a runner from the run's folder", "cat -- '%s/fix.json'" % RUN_DIR in runner(rec, "read-fix")[0]["prompt"], True)
    p = launched(rec, "ui-verifier:T1")[0]["prompt"]
    s.ok("recheck: the verifier is told it is a recheck and given its findings", "recheck" in p.lower() and "T1-1" in p and "T2-1" not in p, p[:500])
    s.ok("recheck: nothing overwrites fix.json (no `findings`), and the browsers are closed", "executor:runner-findings" not in ls and ls[-1:] == ["executor:runner-down"], repr(ls))
    s.ok("recheck: the verdicts are saved apart from the walk's verified files", all("rechecked-" in l["prompt"] and "verified-" not in l["prompt"].replace("rechecked-", "")
                                                                                       for l in runner(rec, "save-T1") + runner(rec, "save-T2")), repr([l["prompt"][-120:] for l in runner(rec, "save-T1")]))
    r = result(rec)
    d = details(rec)
    s.eq("recheck: status", r.get("status"), "done")
    s.eq("recheck: a judgement finding still there (PLAUSIBLE) counts as still there, not as other", (d.get("recheck") or {}).get("still"), 1)
    s.eq("recheck: gone", (d.get("recheck") or {}).get("gone"), 1)
    s.eq("recheck: fix_file is the one given", d.get("fix_file"), RUN_DIR + "/fix.json")
    s.eq("recheck: the up was run on the work branch's checkout", "fwx walk up --dir '%s' --part 1 --round 1 --repo '%s'" % (PHASE, REPO) in runner(rec, "up")[0]["prompt"], True)
    # `uniqueIds` appends `.x` to an id the run already used (T1-1 twice): the finding still belongs to its tramo (3.5 U3d). Against the
    # grouping as first written (`id.replace(/-\d+$/, '')`; the `.x` was left in the tramo id, so the verifier was `ui-verifier:T1-1.x`):
    #   FAIL: recheck suffixed ids: one verifier per tramo, the suffixed ids with their tramo: got ['ui-verifier:T1-1.x', 'ui-verifier:T2-2.x.x'], want ['ui-verifier:T1', 'ui-verifier:T2']
    sfx = [dict(fixes[0], id="T1-1.x"), dict(fixes[1], id="T2-2.x.x")]
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers={**ans, "executor:runner-read-fix": R(json.dumps(sfx))})
    rec = finish(s, "recheck suffixed ids", rec, err, allow_unanswered=True)
    s.eq("recheck suffixed ids: one verifier per tramo, the suffixed ids with their tramo", sorted(set(l for l in labels(rec) if l.startswith("ui-verifier:"))),
         ["ui-verifier:T1", "ui-verifier:T2"])
    s.ok("recheck suffixed ids: each verifier is given its own finding", "T1-1.x" in launched(rec, "ui-verifier:T1")[0]["prompt"] and "T2-2.x.x" in launched(rec, "ui-verifier:T2")[0]["prompt"]
         and "T2-2.x.x" not in launched(rec, "ui-verifier:T1")[0]["prompt"], repr([l["prompt"][-200:] for l in launched(rec, "ui-verifier:T")]))
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers={**ans, "executor:runner-read-fix": R("[]")})
    rec = finish(s, "recheck empty", rec, err)
    s.eq("recheck empty: a fix.json with nothing in it is failed, and the browsers closed", (result(rec).get("status"), "executor:runner-down" in labels(rec)), ("failed", True))


def agent_section(name, mode):
    """The text of one `## Mode` section of an agent file, as committed: the stub replies below are copied from it, never typed here."""
    with open(os.path.join(ROOT, "agents", name), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^## Mode `%s`\n(.*?)(?=^## |\Z)" % mode, text, re.S | re.M)
    return m.group(1) if m else ""


def check_real_replies(script, s):
    """Replies shaped by what agents/ui-verifier.md says the real agent returns (the green scenario's replies are hand-written, so a
    disagreement between the script and the text never showed: both blockers of the text review were green).

    Red against the script as first reviewed (the two scenarios below, first lines):
      FAIL: real tramos reply: the critic is given the reference its screen carries (REFERENCE (data): none): You are the ui-walker, axis critic ... REFERENCE (data): none. ...
      FAIL: real verify reply: a NOT REPRODUCED row with severity null is accepted: got ['schema', 'schema'], want ['value']
      FAIL: real verify reply: the run is done and not failed: got ('failed', ['ui-verifier did not return: T1']), want ('done', [])
    """
    section = agent_section("ui-verifier.md", "tramos")
    block = re.search(r"```\n(.*?)\n```", section, re.S)
    s.ok("real tramos reply: the example is in the agent text", block is not None, section[:200])
    tramos = json.loads(block.group(1)) if block else []
    refs = [x.get("reference") for t in tramos for x in t.get("screens", [])]
    s.ok("real tramos reply: the example gives every screen a reference of its own", bool(refs) and all(isinstance(r, str) and r for r in refs), repr(refs))
    rec, err = go(script, answers_over={"ui-verifier:tramos": "```json\n%s\n```" % json.dumps(tramos)})
    rec = finish(s, "real tramos reply", rec, err, allow_unanswered=True)
    critic = launched(rec, "ui-walker:T1-critic")[0]["prompt"]
    s.ok("real tramos reply: the critic is given the reference its screen carries (REFERENCE (data): none)", all(r in critic for r in refs), critic[:700])
    section = agent_section("ui-verifier.md", "verify")
    keys = re.search(r"each `\{([^}]*)\}`", section)
    s.ok("real verify reply: the row's keys are in the agent text", keys is not None, section[-300:])
    names = [k.strip() for k in (keys.group(1) if keys else "").split(",")]
    row = {k: ("x" if k not in ("severity", "file", "line") else None) for k in names if not k.endswith("?")}
    row.update(id="T1-1", source="critic1-F2", verdict="NOT REPRODUCED", kind="observed", type="layout")  # copied from the walker's finding, as the text says
    rec, err = go(script, answers_over={"ui-verifier:T1": {"findings": [row]}})
    rec = finish(s, "real verify reply", rec, err, allow_unanswered=True)
    s.eq("real verify reply: a NOT REPRODUCED row with severity null is accepted", [l["answer"] for l in launched(rec, "ui-verifier:T1")], ["value"])
    s.eq("real verify reply: the run is done and not failed", (result(rec).get("status"), details(rec).get("gaps")), ("done", []))


def check_args(script, s):
    rec, err = go(script, args_over={"app": {"up": "make up", "run": "", "down": "make down", "url": APP}})
    rec = finish(s, "app by hand", rec, err)
    up = runner(rec, "up")[0]["prompt"]
    s.ok("app by hand: an `app` in args goes to `up --app` as JSON, quoted", "--app '" in up and '"make up"' in up, up[-300:])
    rec, err = go(script, args_over={"repo": "/srv/it's"})
    rec = finish(s, "quoting", rec, err)
    s.ok("quoting: a quote in a path is escaped", "cd '/srv/it'\\''s' &&" in runner(rec, "up")[0]["prompt"], runner(rec, "up")[0]["prompt"][:200])


def check_shape(script, s):
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "lib", "fwx", "lint_models.py"), script], capture_output=True, text=True)
    s.eq("lint: the script passes the model lint", r.returncode, 0)
    s.ok("lint: and it looked at its agent() calls", "0 agent() call(s)" not in r.stdout and "1 workflow file(s)" in r.stdout, r.stdout[-200:])
    text = open(script, encoding="utf-8").read() if os.path.exists(script) else ""
    head = text.splitlines()[:10]
    s.ok("the header names its referent in its first lines", any(l.startswith("// referent: ") and ".claude/skills/ui-walk/SKILL.md @76eca414" in l for l in head), repr(head[:3]))
    s.ok("no workflow() call and no fork", not re.search(r"\bworkflow\(", text) and "agentType: 'fork'" not in text)
    s.ok("the script has a try/finally and a recheck branch", re.search(r"finally\s*\{", text) is not None and "A.recheck" in text)


def check_all(script, s):
    check_green(script, s)
    check_not_armed(script, s)
    check_up_fails(script, s)
    check_breaker_null(script, s)
    check_down_fails(script, s)
    check_control(script, s)
    check_quota(script, s)
    check_tramos(script, s)
    check_verify(script, s)
    check_recheck(script, s)
    check_args(script, s)
    check_real_replies(script, s)


# (what is wrong with the script, text in it, text instead, the check that must go red). Each anchor is in the script exactly once.
MUTANTS = [
    ("the finally removed", "  } finally {\n    await closeRun()\n  }", "  } catch (e0) {\n    throw e0\n  }\n  await closeRun()", "FAIL: breaker null: walk down not called after a walker returned nothing"),
    ("the recheck branch removed", "if (A.recheck) {", "if (false) {", "FAIL: recheck: no breaker or critic launched (critic launched in recheck)"),
    ("not armed carries on", "if (up.armed !== true) {", "if (false) {", "FAIL: not armed: status"),
    ("the walkers are not capped", "const SLOTS = () => quota", "const SLOTS = () => 99", "FAIL: quota 1: no two walkers at once"),
    ("the control is armed after the walkers", "await armControl(tramos)", "/* armed later */", "FAIL: green: the control is armed before any walker"),
    ("a missing walker is not a gap", "st.gaps.push('ui-walker did not return: ' + job.tag)", "", "FAIL: breaker null: failed, naming the walker"),
    ("a missed control still counts", "The run does not count", "Run", "FAIL: control missed: the reason says first that the run does not count"),
    ("a refused control's reason dropped", "(ctl.why ? ' (' + ctl.why + ')' : '')", "''", "FAIL: control refused (no visible change): the run does not count, and the reason says which it was"),
    ("a control tramo not walked is judged", "walked = st.walked[ctl.tramo] === true", "walked = true", "FAIL: control not walked: no judge launched"),
    ("a down that exits 1 is done", "if (down.rc !== 0)", "if (false)", "FAIL: down fails: status failed"),
    ("the Firefox critic always", "if (t.firefox === true)", "if (true)", "FAIL: green: five walkers"),
    ("the walkers are told about the control", "const brief = (job) => [", "const brief = (job) => ['The planted control is on this screen.',", "FAIL: green: no walker is told about the control"),
    ("recheck overwrites fix.json", "if (!A.recheck) await collect()", "await collect()", "FAIL: recheck: nothing overwrites fix.json"),
    ("a null severity refused by the schema", "severity: { type: ['string', 'null'], enum: ['blocker', 'major', 'minor', 'cosmetic', null] },",
     "severity: { type: 'string', enum: ['blocker', 'major', 'minor', 'cosmetic'] },", "FAIL: real verify reply: a NOT REPRODUCED row with severity null is accepted"),
    ("the screen's reference dropped", "reference: String(x.reference || 'none') })),", "reference: 'none' })),", "FAIL: real tramos reply: the critic is given the reference its screen carries"),
    ("a judgement still there counted as other", "if (f.verdict === 'CONFIRMED' || f.verdict === 'PLAUSIBLE') rc.still += 1", "if (f.verdict === 'CONFIRMED') rc.still += 1",
     "FAIL: recheck: a judgement finding still there"),
    ("the walkers are not told the run", "`fwx walk ab --run ' + st.runDir + ' ' + job.session", "`fwx walk ab ' + job.session", "FAIL: green: every walker command names the run"),
    ("the walk keeps the quota `up` gave", "const tramos = await getTramos()\n  await sizeQuota(tramos.length)\n", "const tramos = await getTramos()\n",
     "FAIL: quota from the second ask: the walkers of the tramos run at once"),
    ("the recheck keeps the quota `up` gave", "  await sizeQuota(tramos.length)\n  st.tramos = tramos.map", "  st.tramos = tramos.map", "FAIL: recheck: capacity is asked for the 2 tramos"),
    ("a capacity that gives no answer drops the quota", "if (!Number.isInteger(allowed)) {", "if (false) {", "FAIL: capacity ask rc 1: the quota stays what `up` allowed (3)"),
    ("a suffixed id loses its tramo", "f.id.replace(/-\\d+(?:\\.x)*$/, '')", "f.id.replace(/-\\d+$/, '')", "FAIL: recheck suffixed ids: one verifier per tramo"),
    ("the runner may name its stderr file", "never a fixed name in /tmp. ", "", "FAIL: green: the runner is told to keep stderr in a mktemp file"),
    ("the verifier is not told where captures go", "A path in /tmp is refused.", "", "FAIL: green: the verifier is told a screenshot with no path lands"),
    ("a tramo id used raw", "const safe = (id, i) =>", "const safe = (id, i) => id ||", "FAIL: unsafe tramo id"),
]


def check_controls(s):
    if not os.path.exists(SCRIPT):
        return
    with open(SCRIPT, encoding="utf-8") as f:
        src = f.read()
    for name, old, new, want in MUTANTS:
        m = mutate(src, old, new)
        if not s.ok("control %s: the anchor is in the script exactly once" % name, m is not None):
            continue
        mdir = helpers.mkdtemp("fwx-uwmut-")
        try:
            sub = helpers.Suite()
            check_all(helpers.write(mdir, "ui-walk.js", m), sub)
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
    check_shape(SCRIPT, s)
    if not os.environ.get("FWX_UW_NESTED"):
        check_controls(s)
    s.done()


if __name__ == "__main__":
    main()
