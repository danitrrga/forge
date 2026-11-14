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

Red before the quota came from the configuration's cap (D90; `fwx walk capacity` is gone, `fwx walk start` prints `capacity.cap`). On master with this test:
  FAIL: quota from the cap: 2 tramos, a cap of 5: 4 walkers run at once (2 per tramo): got 1, want 4
  FAIL: cap 3: never more than the cap run at once, and as many as the cap and the tramos allow: got 2, want 3
  FAIL: cap missing: failed, with a reason that says cap and `fwx walk start`: ('done', '')
  FAIL: green: no capacity command is asked: the quota is the cap `walk start` printed, sized to the tramos (cap 4, 2 tramos: a quota of 4): ([...'executor:runner-capacity'...], ...)
Older, red before `sizeQuota` (3.5 U3d; the quota stayed what `up` said for one tramo):
  FAIL: green: the quota is sized to the tramos: capacity is asked after the tramos are known and before the control and any walker: ['executor:runner-up', 'ui-verifier:tramos', 'executor:runner-arm-control', ...]
  FAIL: quota from the second ask: the walkers of the tramos run at once: [('ui-walker:T1-breaker', 7, 8), ('ui-walker:T1-critic', 9, 10), ...]
  FAIL: capacity ask rc 1: the quota stays what `up` allowed (3) and it is logged: ['ui-walk: ui-walker:T2-critic waits in the queue (quota 3, ...
  (the first two also in recheck: no capacity ask before the verifiers)

Red before the workflow read the refusal of arm-control's read-back (D14; the reason of `{"armed": false, "reason": ...}` was dropped):
  FAIL: control refused (no visible change): the run does not count, and the reason says which it was: 'The run does not count: the control could not be planted on http://localhost:3000/settings.'
  FAIL: control refused (target not found): the run does not count, and the reason says which it was: 'The run does not count: the control could not be planted on http://localhost:3000/settings.'

Red before a failed `fwx walk converge` changed the final status (it ran in the close, after the gaps were read, and the run stayed `done` with no fix.json):
  FAIL: findings rc 1: failed, and the reason names `fwx walk converge`: ('done', '')
  FAIL: findings no answer: failed, and the reason names `fwx walk converge`: ('done', '')
  FAIL: findings not JSON: failed, and the reason names `fwx walk converge`: ('done', '')
  FAIL: findings and down fail: both are in the reason: 'fwx walk stop exited 1: a browser or the app may be left, .../down.json says how many'

Red before a job closed its own browser before freeing its slot (a browser stays up after its agent returns, so the quota limited agents, not browsers):
  FAIL: close: every job's browser is closed after it returned: [('ui-walker:T1-breaker', 'w1', None), ('ui-walker:T1-critic', 'w2', None), ...]
  FAIL: close quota 1: the next job starts only after the previous one's browser was closed: [('ui-walker:T1-breaker', 'ui-walker:T1-critic'), ...]

Red before the planted control's own verified row was taken out of what the fixer gets (the verifiers' browsers carry the plant too):
  FAIL: control row: the verifier confirmed the planted title: it leaves verified-T1.json and goes to control-T1.json: no executor:runner-control-T1 launched
  FAIL: control row clip: the clip of the control row is not listed: got ['.../control.webm'], want []
  FAIL: control row not taken out: a gap, and a failed run: the fixer must not get it: ('done', [])

Red before a recheck reply had to hold a row for each finding it was given (`{"findings": []}` was saved and the run was done with 0 still, 0 gone):
  FAIL: recheck reply with no row: launched once more, then a gap and a failed run: got (1, 'done', False), want (2, 'failed', True)

Controls (each on a copy of workflows/ui-walk.js with one branch taken out, `MUTANTS`; the anchor must be in the script exactly
once; the first matching FAIL line of each, seen red):
  the `finally` removed (scenario 1: the breaker of a tramo returns null):
      FAIL: breaker null: walk stop not called after a walker returned nothing: ['ui-verifier:T1', 'ui-verifier:T2', 'executor:runner-save-T1', ...]
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
  the walk keeps the quota `start` gave: FAIL: quota from the cap: 2 tramos, a cap of 5: 4 walkers run at once (2 per tramo): got 2, want 4
  a cap that is no number is not refused: FAIL: cap missing: failed, with a reason that says cap and `fwx walk start`: ('done', '')
  the cap is not applied:    FAIL: cap 3: never more than the cap run at once, and as many as the cap and the tramos allow: got 4, want 3
  a container run passes its apps: FAIL: container apps: 2 apps, a cap of 5: two walkers at once: got 4, want 2
  a raw tramo id in a path:  FAIL: unsafe tramo id: no launch or command carries the raw id: ['ui-walker:../x y-breaker', ...]
  the quota capped at two (a review of the pairwise overlap count, which added 1 to a sum that held the walker itself): against the count as first
      written the control stayed green: FAIL: control the quota is capped at two: red with 'FAIL: quota from the cap: 2 tramos, a cap of 5': got []
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
      "namespace": "walk-1-1-abc123", "capacity": {"role": "ui-walker", "want": 2, "cap": 4, "allowed": 2, "container": False}}


def up_cap(n, **over):
    """The answer of `walk start` when the configuration's cap for the walkers is `n`: `allowed` is for one tramo (2 walkers at most), the
    workflow sizes the rest itself."""
    up = json.loads(json.dumps(UP))
    up["capacity"].update(cap=n, allowed=min(n, 2))
    up["capacity"].update(over)
    return {"executor:runner-up": R(up)}
FINDINGS_OUT = {"fix_file": RUN_DIR + "/fix.json", "contradicted_file": RUN_DIR + "/contradicted.json",
                "counts": {"confirmed": 1, "plausible": 1, "contradicted": 0, "dropped": 1}}
def shots_out(rows):
    """What `fwx walk capture --json` prints (lib/fwx/commands/screenshot.py): one JSON object per screen, `ok` with its `path` or `missing` with its `why`."""
    return "".join(json.dumps(dict(r, url=APP + r["url"], theme="light", width=1440)) + "\n" for r in rows)


SHOTS = shots_out([{"status": "ok", "path": "/srv/git/fwx/walks/walk-1-1-abc123/shots/s1.png", "url": "/settings"},
                   {"status": "ok", "path": "/srv/git/fwx/walks/walk-1-1-abc123/shots/s2.png", "url": "/billing"}])
DOWN = {"namespace": "walk-1-1-abc123", "run_dir": RUN_DIR, "looked": 31, "unreadable": 0, "left": [], "browsers_left": 0, "steps": []}


def screens_out(*rows):
    """What `fwx walk check-screens` prints (lib/fwx/commands/walk.py): one object, each screen once with the status it answered."""
    return {"checked": len(rows), "bad": sum(1 for _, st in rows if not (isinstance(st, int) and 200 <= st < 300)),
            "screens": [{"url": u, "status": st, "ok": isinstance(st, int) and 200 <= st < 300} for u, st in rows]}


def verified(tramo, *rows):
    return {"findings": [dict({"id": "%s-%d" % (tramo, i + 1), "verdict": v, "severity": "minor", "file": "src/x.tsx", "line": 3, "claim": "claim",
                               "evidence": "e", "screen": "/settings", "steps": "1. open", "expected": "x", "type": "layout", "kind": "observed",
                               "why": "w"}, **({"clip": c} if c else {})) for i, (v, c) in enumerate(rows)]}


def green():
    """The answers of a run in which nothing goes wrong: two tramos (T2 asks for Firefox), a control found, a clean close."""
    return {
        "executor:runner-up": R(UP),
        "ui-verifier:tramos": json.dumps(TRAMOS),
        "executor:runner-check-screens": R(screens_out((APP + "/settings", 200), (APP + "/billing", 200))),
        "executor:runner-arm-control": R({"screen": APP + "/settings", "path": "/settings", "kind": "hierarchy"}),
        "ui-walker:T1-breaker": "0 blocker, 1 minor\n%s/findings-w1.md\nthe save bar clips" % RUN_DIR,
        "ui-walker:T1-critic": "0 blocker, 0 minor\n%s/findings-w2.md\nnone" % RUN_DIR,
        "ui-walker:T2-breaker": "0 blocker, 0 minor\n%s/findings-w3.md\nnone" % RUN_DIR,
        "ui-walker:T2-critic": "0 blocker, 1 minor\n%s/findings-w4.md\nthe list" % RUN_DIR,
        "ui-walker:T2-firefox": "0 blocker, 0 minor\n%s/findings-w5.md\nnone" % RUN_DIR,
        "ui-verifier:T1": verified("T1", ("CONFIRMED", RUN_DIR + "/clip-1.webm"), ("NOT REPRODUCED", None)),
        "ui-verifier:T2": verified("T2", ("PLAUSIBLE", None)),
        "executor:runner-save-T1": R("saved"), "executor:runner-save-T2": R("saved"),
        "ui-verifier:control": {"screen": "/settings", "found": True, "finding": "w2-F1", "why": "w2-F1 says the title reads like body text"},
        "executor:runner-findings": R(FINDINGS_OUT),
        "executor:runner-screenshot": R(SHOTS),
        "executor:runner-coverage": R("saved"),
        "executor:runner-down": R(DOWN),
        **{closing(v): R("") for v in ("w1", "w2", "w3", "w4", "w5", "v1", "v2")}, closer("v2", True): R(""),
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
    s.ok("green: no capacity command is asked: the quota is the cap `walk start` printed, sized to the tramos (cap 4, 2 tramos: a quota of 4)",
         not any("capacity" in l["label"] or "walk capacity" in l["prompt"] for l in rec["launches"]) and any("a quota of 4" in l for l in rec["logs"]),
         repr(([l["label"] for l in rec["launches"] if "capacity" in l["label"]], rec["logs"][-3:])))
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
    s.ok("green: up is told the repo, the folder, the part and the round", "cd '%s' && fwx walk start --dir '%s' --part 1 --round 1 --repo '%s'" % (REPO, PHASE, REPO) in up
         and "--app" not in up, up[-300:])
    arm = runner(rec, "arm-control")[0]["prompt"]
    s.ok("green: the control is planted on the first screen of the first tramo, as a URL of the app and the run's folder",
         "fwx control new --run '%s' --screen '%s/settings'" % (RUN_DIR, APP) in arm, arm[-300:])
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
    s.ok("green: findings, down name the run's folder", "fwx walk converge --run '%s'" % RUN_DIR in runner(rec, "findings")[0]["prompt"]
         and "fwx walk stop --run '%s'" % RUN_DIR in runner(rec, "down")[0]["prompt"])
    shot = runner(rec, "screenshot")[0]["prompt"]
    s.ok("green: screenshot is given the walked screens", "fwx walk capture --run '%s' --screens " % RUN_DIR in shot and APP + "/settings" in shot and APP + "/billing" in shot, shot[-400:])
    s.ok("green: the screenshot is asked for `--json` (a path with a space cannot be read from the text line)", " --json" in shot, shot[-200:])
    # Red on the base (the reader took `\S+` after `ok `, and the command had no --json, so the JSON line read as no capture):
    #   FAIL: green: details.shots are the paths the screenshots were written to: got [], want [...s1.png, ...s2.png]
    spaced = "/srv/git/fwx/walks/walk 1/shots/a b.png"
    rec2, err2 = go(script, answers_over={"executor:runner-screenshot": R(shots_out([{"status": "ok", "path": spaced, "url": "/settings"},
                                                                                     {"status": "missing", "why": "no file written", "url": "/billing"}]), 1)})
    rec2 = finish(s, "screenshot paths", rec2, err2)
    s.eq("screenshot paths: a path with a space is read whole, a missing screen is not a capture", details(rec2).get("shots"), [spaced])
    d = details(rec)
    s.eq("green: details keys", sorted(d), sorted(["run_dir", "fix_file", "counts", "contradicted_file", "control", "coverage_file", "shots", "clips", "down_file", "outside",
                                                 "recheck", "gaps", "agents", "unverified", "lost_slots"]))
    s.eq("green: details.run_dir, fix_file, contradicted_file, down_file, coverage_file", (d.get("run_dir"), d.get("fix_file"), d.get("contradicted_file"), d.get("down_file"), d.get("coverage_file")),
         (RUN_DIR, RUN_DIR + "/fix.json", RUN_DIR + "/contradicted.json", RUN_DIR + "/down.json", RUN_DIR + "/coverage.md"))
    s.eq("green: details.counts are what `findings` printed", d.get("counts"), FINDINGS_OUT["counts"])
    s.eq("green: details.control", d.get("control"), {"screen": "/settings", "found": True, "finding": "w2-F1"})
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
    # the runner may have started the app and lost its report: the run folder is `<phase>/ui-walk/<part>-<round>`, so the reason names the `down` that
    # closes it; the script does not run that `down` itself, for it cannot tell this attempt's app from an earlier open run of the same folder
    # Red on the base: FAIL: up with no report: the reason names the command that closes a run `up` may have started: 'runner did not return: up'
    rec, err = go(script, answers={"executor:runner-up": None})
    rec = finish(s, "up with no report", rec, err)
    r = result(rec)
    s.eq("up with no report: failed, and no `down` is run on a guess", (r.get("status"), labels(rec)), ("failed", ["executor:runner-up"]))
    s.ok("up with no report: the reason names the command that closes a run `up` may have started: %r" % r.get("reason"),
         "fwx walk stop --run '%s'" % RUN_DIR in str(r.get("reason")), repr(r.get("reason")))


def check_breaker_null(script, s):
    """Scenario 1: the breaker of a tramo returns nothing. The run is failed (a gap does not count as a pass), the other walkers' work is
    kept, and the browsers are closed all the same."""
    rec, err = go(script, answers_over={"ui-walker:T1-breaker": None})
    rec = finish(s, "breaker null", rec, err)
    ls = labels(rec)
    s.ok("breaker null: walk stop not called after a walker returned nothing", "executor:runner-down" in ls, repr(ls[-5:]))
    s.eq("breaker null: the breaker was launched once more and no more", ls.count("ui-walker:T1-breaker"), 2)
    s.eq("breaker null: failed, naming the walker", (result(rec).get("status"), "T1-breaker" in str(result(rec).get("reason"))), ("failed", True))
    s.ok("breaker null: the tramo is still verified from its critic's file and the findings are still collected", "ui-verifier:T1" in ls and "executor:runner-findings" in ls, repr(ls))
    s.ok("breaker null: the gap is in details", any("T1-breaker" in g for g in details(rec).get("gaps", [])), repr(details(rec).get("gaps")))


def check_screens(script, s):
    """F-1: a walk over screens that do not answer 2xx stops before the control is armed and before any walker starts. In the rehearsal
    `app_run.url` ended in a page, every screen became `<page>/<path>`, the walkers spent 13 minutes on not-found pages and the walk ended as
    `done: The run does not count` for another reason. Seen red on the base (the script never asked; the 404 answer below was left unused):
      FAIL: screens 404: failed, with the screen and the status in the reason: ('done', '')
      FAIL: screens 404: no walker and no control: ['executor:runner-up', 'ui-verifier:tramos', 'executor:runner-capacity', 'executor:runner-arm-control', 'ui-walker:T1-breaker', ...
      FAIL: screens no answer: failed, naming the command, and no walker ran: ('done', '', ['executor:runner-screenshot', 'executor:runner-coverage', 'executor:runner-down'])
    The green scenario (every screen answers 200) is the negative control: the same command, the same two screens, the walk goes on."""
    rec, err = go(script)
    rec = finish(s, "screens green", rec, err)
    ls = labels(rec)
    cmd = (runner(rec, "check-screens") or [{"prompt": ""}])[0]["prompt"]
    s.eq("screens green: one launch asks every screen", ls.count("executor:runner-check-screens"), 1)
    s.ok("screens green: the command names the run and every screen of every tramo, as URLs of the app",
         "fwx walk check-screens --run '%s' --screens '%s'" % (RUN_DIR, json.dumps([APP + "/settings", APP + "/billing"], separators=(",", ":"))) in cmd, cmd[-300:])
    s.ok("screens green: asked after the tramos and before the control and any walker",
         at(ls, "ui-verifier:tramos") < at(ls, "executor:runner-check-screens") < at(ls, "executor:runner-arm-control"), repr(ls))
    s.eq("screens green: the walk goes on", result(rec).get("status"), "done")
    bad = screens_out((APP + "/settings", 200), (APP + "/billing", 404))
    rec, err = go(script, answers_over={"executor:runner-check-screens": R(bad, 1)})
    rec = finish(s, "screens 404", rec, err)
    r = result(rec)
    why = str(r.get("reason"))
    s.ok("screens 404: failed, with the screen and the status in the reason", r.get("status") == "failed" and APP + "/billing answers 404" in why, repr((r.get("status"), why)))
    s.ok("screens 404: the reason says app_run.url is the base the screens are appended to, and what it was",
         "app_run.url is the base address each screen's path is appended to (here %s)" % APP in why and "root" in why, why)
    s.ok("screens 404: the screen that answers is not named", APP + "/settings" not in why, why)
    ls = labels(rec)
    s.ok("screens 404: no walker and no control", not any(l.startswith("ui-walker:") or l == "executor:runner-arm-control" for l in ls), repr(ls))
    s.ok("screens 404: the app is closed all the same", ls[-1:] == ["executor:runner-down"], repr(ls[-3:]))
    # every bad screen is named, and one that is not on the app, by its own words
    two = screens_out((APP + "/settings", 404), (APP + "/billing", "not on the app (localhost)"))
    rec, err = go(script, answers_over={"executor:runner-check-screens": R(two, 1)})
    rec = finish(s, "screens two bad", rec, err)
    why = str(result(rec).get("reason"))
    s.ok("screens two bad: both are named", APP + "/settings answers 404" in why and APP + "/billing: not on the app (localhost)" in why, why)
    # fail closed: no answer, an exit that is not 0 or 1, a pass that is not the command's own JSON
    ok_rows = screens_out((APP + "/settings", 200), (APP + "/billing", 200))
    no_ok = {"checked": 2, "bad": 0, "screens": [{"url": APP + "/settings", "status": 200}, {"url": APP + "/billing", "status": 200}]}
    for label, ans in (("no answer", None), ("exit 2", R("", 2)), ("exit 1 and no JSON", R("boom", 1)), ("exit 0 and no JSON", R("ok", 0)),
                       ("exit 0 and no screen looked at", R({"checked": 0, "bad": 0, "screens": []}, 0)),
                       ("exit 1 and every row ok", R(ok_rows, 1)), ("exit 0 and a row without ok", R(no_ok, 0)),
                       ("exit 0 and fewer rows than screens", R(screens_out((APP + "/settings", 200)), 0)),
                       ("exit 0 and rows that are no objects", R({"checked": 2, "bad": 0, "screens": [None, 3]}, 0))):
        rec, err = go(script, answers_over={"executor:runner-check-screens": ans})
        rec = finish(s, "screens %s" % label, rec, err)
        r = result(rec)
        s.ok("screens %s: failed, naming the command, and no walker ran" % label, r.get("status") == "failed" and "check-screens" in str(r.get("reason"))
             and not walkers(rec), repr((r.get("status"), r.get("reason"), labels(rec)[-3:])))
        # the reason says the reply was unusable, not that a screen answered badly, and sends the owner to run the command (a runner hands back stdout only)
        s.ok("screens %s: the reason says the answer was not usable and names no screen's status" % label,
             ("no usable answer" in str(r.get("reason")) or "did not return" in str(r.get("reason"))) and "stderr" not in str(r.get("reason")) and "answers" not in str(r.get("reason")),
             repr(r.get("reason")))
    rec, err = go(script, answers_over={"executor:runner-check-screens": R(bad, 0)})
    rec = finish(s, "screens exit 0 and a bad screen", rec, err)
    s.ok("screens exit 0 and a bad screen: the screen's own status decides, not the exit", result(rec).get("status") == "failed" and not walkers(rec),
         repr((result(rec).get("status"), labels(rec)[-3:])))


def check_screens_login(script, s):
    """An app that declares a login: check-screens does not judge a screen (the probe has no demo session), prints `NOT RUN, NOT ARMED` per screen and
    exits 0, and the walk goes on exactly as before check-screens existed. Seen red on 26d1cf6 (the command had no such answer, so it read as a failure):
      FAIL: screens login: the walk goes on: got 'failed', want 'done'"""
    not_run = {"checked": 0, "bad": 0, "not_run": "NOT RUN, NOT ARMED: app_run.login is set, so a screen's status says nothing without the demo session: 2 screen(s) not checked",
               "screens": [{"url": APP + "/settings", "checked": False, "status": None, "ok": None}, {"url": APP + "/billing", "checked": False, "status": None, "ok": None}]}
    rec, err = go(script, answers_over={"executor:runner-check-screens": R(not_run, 0)})
    rec = finish(s, "screens login", rec, err)
    s.eq("screens login: the walk goes on", (result(rec).get("status"), result(rec).get("reason")), ("done", ""))
    s.eq("screens login: five walkers", len(walkers(rec)), 5)
    # the same answer for fewer screens than asked, or with no reason, is not a pass
    for label, ans in (("fewer rows", dict(not_run, screens=not_run["screens"][:1])), ("no reason", {k: v for k, v in not_run.items() if k != "not_run"})):
        rec, err = go(script, answers_over={"executor:runner-check-screens": R(ans, 0)})
        rec = finish(s, "screens login %s" % label, rec, err)
        s.ok("screens login %s: failed, no walker" % label, result(rec).get("status") == "failed" and not walkers(rec), repr((result(rec).get("status"), labels(rec)[-3:])))


def check_critic_context(script, s):
    """The owner's decision (F-3): the critic judges THE WHOLE SCREEN, given the context in which the change was made (the `why` of each screen: the
    part's task, the decision it came from) as the place to start, so it can say whether the change is well done. Until then the brief named what
    changed and the critic looked only there, which is why a fault elsewhere on the same screen (the planted one) went unseen in three acceptances.
    Seen red on the base (the brief carried the screens' JSON and nothing about how to read it):
      FAIL: critic brief: the whole screen is judged against its reference, not only the changed element: 'You are the ui-walker, axis critic, ...'
      FAIL: critic brief: what changed is the context of the change and the place to start, not the edge of what is judged: ...
      FAIL: ui-walker.md: the critic section says the same
    The breaker's brief is the negative control: it is not told to judge a reference."""
    rec, err = go(script)
    rec = finish(s, "critic context", rec, err)
    ws = {l["label"]: l["prompt"] for l in walkers(rec)}
    for label in ("ui-walker:T1-critic", "ui-walker:T2-critic", "ui-walker:T2-firefox"):
        p = ws.get(label, "")
        s.ok("%s brief: the whole screen is judged against its reference, not only the changed element" % label,
             "Judge the whole screen against its reference" in p and "not only the changed element" in p, p[-700:])
        s.ok("%s brief: what changed is the context of the change and the place to start, not the edge of what is judged" % label,
             "the context in which the change was made" in p and "the place to start" in p and "whether the change is well done" in p, p[-700:])
    s.ok("critic brief: the screen's own why is in it, as the context", "the save bar" in ws.get("ui-walker:T1-critic", ""), ws.get("ui-walker:T1-critic", "")[-500:])
    s.ok("breaker brief: not told to judge a reference or the whole screen", all("whole screen" not in p and "context in which" not in p for k, p in ws.items() if k.endswith("breaker")),
         repr([k for k, p in ws.items() if k.endswith("breaker") and "whole screen" in p]))
    with open(os.path.join(ROOT, "agents", "ui-walker.md"), encoding="utf-8") as f:
        agent = f.read()
    critic = agent.split("## Axis `critic`", 1)[-1]
    s.ok("ui-walker.md: the critic section says the same", "the whole screen" in critic and "context" in critic and "place to start" in critic and "well done" in critic, critic[:600])


def check_down_fails(script, s):
    rec, err = go(script, answers_over={"executor:runner-down": R(DOWN, 1)})
    rec = finish(s, "down fails", rec, err)
    s.eq("down fails: status failed, and the reason says browsers may be left", (result(rec).get("status"), "down.json" in str(result(rec).get("reason"))), ("failed", True))
    rec, err = go(script, answers_over={"executor:runner-down": None})
    rec = finish(s, "down null", rec, err)
    s.eq("down null: status failed", result(rec).get("status"), "failed")


def check_findings_fails(script, s):
    """`fwx walk converge` runs in the close, after the gaps were read: a run that collected no fix.json must still end failed, and `down` still runs."""
    for what, ans in (("rc 1", R("", 1)), ("no answer", None), ("not JSON", R("nope"))):
        rec, err = go(script, answers_over={"executor:runner-findings": ans})
        rec = finish(s, "findings %s" % what, rec, err)
        r = result(rec)
        s.ok("findings %s: failed, and the reason names `fwx walk converge`" % what, r.get("status") == "failed" and "fwx walk converge" in str(r.get("reason")),
             repr((r.get("status"), r.get("reason"))))
        s.ok("findings %s: the browsers are closed all the same" % what, labels(rec)[-1:] == ["executor:runner-down"], repr(labels(rec)[-4:]))
        s.ok("findings %s: no fix file is reported" % what, details(rec).get("fix_file") is None, repr(details(rec).get("fix_file")))
    rec, err = go(script, answers_over={"executor:runner-findings": R("", 1), "executor:runner-down": R(DOWN, 1)})
    rec = finish(s, "findings and down fail", rec, err)
    s.ok("findings and down fail: both are in the reason", "fwx walk converge" in str(result(rec).get("reason")) and "down.json" in str(result(rec).get("reason")), repr(result(rec).get("reason")))


# the browser session each job of the green scenario drives (makeJobs numbers the walkers; a verifier takes the number of its tramo)
SESSION_OF = {"ui-walker:T1-breaker": "w1", "ui-walker:T1-critic": "w2", "ui-walker:T2-breaker": "w3", "ui-walker:T2-critic": "w4", "ui-walker:T2-firefox": "w5",
              "ui-verifier:T1": "v1", "ui-verifier:T2": "v2"}


def closer(session, pw=False):
    return "executor:runner-close-%s%s" % (session, "-pw" if pw else "")


def closing(session):
    """The runner that closes a job's own browser: the Firefox walker's is a `pw` one."""
    return closer(session, session == "w5")


def check_close(script, s):
    """The quota budgets browsers, but a browser stays up after its agent returns (until `down` or the idle timeout): a job closes its own
    sessions before it frees its slot, a failed job's included.

    Red on the base (no `close` was ever run; the answers below were never asked for):
      FAIL: close: every job's browser is closed after it returned: [('ui-walker:T1-breaker', 'w1', None), ('ui-walker:T1-critic', 'w2', None), ...]
      FAIL: close quota 1: the next job starts only after the previous one's browser was closed: [...]
    """
    rec, err = go(script)
    rec = finish(s, "close", rec, err)
    byl = collections.defaultdict(list)
    for l in rec["launches"]:
        byl[l["label"]].append(l)
    rows = []
    for label, session in SESSION_OF.items():
        c = byl.get(closing(session)) or [None]
        rows.append((label, session, c[0] and c[0]["start"] >= max(x["end"] for x in byl[label])))
    s.ok("close: every job's browser is closed after it returned", all(r[2] for r in rows), repr(rows))
    s.ok("close: the command is `close` of that session, in the run", all("fwx walk ab --run '%s' %s close" % (RUN_DIR, v) in (byl.get(closing(v)) or [{"prompt": ""}])[0]["prompt"]
                                                                           for k, v in SESSION_OF.items() if k != "ui-walker:T2-firefox"), repr(sorted(byl)))
    s.ok("close: the Firefox walker's session is closed through `pw`, and so is the Firefox tramo's verifier's",
         "fwx walk pw --run '%s' w5 close" % RUN_DIR in (byl.get(closing("w5")) or [{"prompt": ""}])[0]["prompt"]
         and "fwx walk pw --run '%s' v2 close" % RUN_DIR in (byl.get(closer("v2", True)) or [{"prompt": ""}])[0]["prompt"], repr(sorted(byl)))
    s.ok("close: no `pw` close for a tramo without Firefox", closer("v1", True) not in byl and closer("w1", True) not in byl, repr(sorted(byl)))
    rec, err = go(script, answers_over=up_cap(1))
    rec = finish(s, "close quota 1", rec, err)
    byl = collections.defaultdict(list)
    for l in rec["launches"]:
        byl[l["label"]].append(l)
    jobs = sorted((l for k in SESSION_OF for l in byl[k]), key=lambda l: l["start"])
    gaps = []
    for a, b in zip(jobs, jobs[1:]):
        c = byl.get(closing(SESSION_OF[a["label"]])) or [None]
        if not c[0] or not (a["end"] <= c[0]["start"] and c[0]["end"] <= b["start"]):
            gaps.append((a["label"], b["label"]))
    s.ok("close quota 1: the next job starts only after the previous one's browser was closed", len(jobs) >= 7 and not gaps, repr(gaps or len(jobs)))
    rec, err = go(script, answers_over={"ui-walker:T1-breaker": None})
    rec = finish(s, "close after a walker that returned nothing", rec, err)
    s.ok("close after a walker that returned nothing: its browser is closed all the same", closing("w1") in labels(rec), repr(labels(rec)))
    # a close that fails is no gap while capacity is left: `down` is the net, and the idle timeout; the job's slot stays taken (the browser may
    # still be up), so the run goes on with what is left
    rec, err = go(script, answers_over={closing("w1"): None, closing("v1"): R("", 1)})
    rec = finish(s, "close fails", rec, err)
    s.eq("close fails: the run is still done, with no gap", (result(rec).get("status"), details(rec).get("gaps")), ("done", []))
    # A close that did not return, or exited non-zero, leaves the browser up: its slot is not freed, so the quota still bounds browsers. With
    # a quota of 1 the next job would have started a second browser beside it; the queue is stopped instead (a gap each) and `down` runs.
    # Seen red on the base (PR 103 review thread, "Do not release capacity after an unsuccessful browser close"; the close's result was dropped):
    #   FAIL: close not confirmed (rc 1): no second browser starts beside one that may be up: got ['ui-walker:T1-breaker', 'ui-walker:T1-critic', 'ui-walker:T2-breaker', 'ui-walker:T2-critic', 'ui-walker:T2-firefox'], want ['ui-walker:T1-breaker']
    one = up_cap(1)
    for what, ans in (("rc 1", R("", 1)), ("no answer", None)):
        rec, err = go(script, answers_over={**one, closing("w1"): ans})
        rec = finish(s, "close not confirmed (%s)" % what, rec, err)
        s.eq("close not confirmed (%s): no second browser starts beside one that may be up" % what, [l["label"] for l in walkers(rec)], ["ui-walker:T1-breaker"])
        s.eq("close not confirmed (%s): the close was tried twice" % what, labels(rec).count(closing("w1")), 2)
        s.ok("close not confirmed (%s): the jobs left in the queue are gaps that say why, the run is failed and `down` still runs" % what,
             result(rec).get("status") == "failed" and any("no browser slot" in g for g in details(rec).get("gaps", [])) and labels(rec)[-1:] == ["executor:runner-down"],
             repr((result(rec).get("status"), details(rec).get("gaps"), labels(rec)[-3:])))
    # What the owner reads when the slot is lost (review of PR 125: the reason led with "the critic returned nothing", each job was a gap twice,
    # and the walker's findings were nowhere in the result). Seen red on 93e43d9:
    #   FAIL: close not confirmed, the owner's reading: the reason leads with the browser that could not be closed: 'The run does not count: the control screen ... was not walked: the critic of tramo T1 returned nothing. no tramo was verified: ...'
    #   FAIL: close not confirmed, the owner's reading: the findings the walker returned stay in the result as not verified: got None, want [{'tramo': 'T1', 'files': [...findings-w1.md]}]
    rec, err = go(script, answers_over={**one, closing("w1"): R("", 1)})
    rec = finish(s, "close not confirmed, the owner's reading", rec, err)
    r, d = result(rec), details(rec)
    s.ok("close not confirmed, the owner's reading: the reason leads with the browser that could not be closed and says no slot was left",
         str(r.get("reason")).startswith("A browser could not be closed (ui-walker:T1-breaker), so no browser slot was left"), repr(r.get("reason"))[:300])
    s.ok("close not confirmed, the owner's reading: the reason says the findings were collected but not verified", "collected but not verified" in str(r.get("reason")),
         repr(r.get("reason"))[:400])
    s.eq("close not confirmed, the owner's reading: the findings the walker returned stay in the result as not verified", d.get("unverified"),
         [{"tramo": "T1", "files": [RUN_DIR + "/findings-w1.md"]}])
    s.eq("close not confirmed, the owner's reading: one slot lost", d.get("lost_slots"), 1)
    s.eq("close not confirmed, the owner's reading: each job that never started is one gap, none of them 'did not return'",
         (len([g for g in d.get("gaps", []) if "was not started" in g]), [g for g in d.get("gaps", []) if "did not return" in g]), (5, []))
    # No hang at any quota: with two slots and both closes failing every slot is lost while jobs wait (a counter that stuck at 1 left them
    # queued for ever: `st.lost = 1`); with one of two lost the other carries the walk to its end.
    two = up_cap(2)
    rec, err = go(script, answers_over={**two, closing("w1"): R("", 1), closing("w2"): R("", 1)})
    rec = finish(s, "close not confirmed, quota 2, both lost", rec, err)
    s.eq("close not confirmed, quota 2, both lost: the two walkers that ran are the only ones, the run ends failed with the lost slots in front",
         (sorted(l["label"] for l in walkers(rec)), result(rec).get("status"), str(result(rec).get("reason")).startswith("A browser could not be closed ("), details(rec).get("lost_slots")),
         (["ui-walker:T1-breaker", "ui-walker:T1-critic"], "failed", True, 2))
    rec, err = go(script, answers_over={**two, closing("w1"): R("", 1)})
    rec = finish(s, "close not confirmed, quota 2, one lost", rec, err)
    s.eq("close not confirmed, quota 2, one lost: the other slot carries every job, done, with the loss said",
         (len(walkers(rec)), result(rec).get("status"), details(rec).get("gaps"), details(rec).get("lost_slots"), str(result(rec).get("reason")).startswith("A browser could not be closed (")),
         (5, "done", [], 1, True))
    # exit 77 of a close (`NOT RUN, NOT ARMED`: no Playwright Firefox, or no agent-browser, on this machine) means no browser of that tool can be open:
    # a confirmed close, no slot lost (a recheck of a machine with no Firefox lost one slot per verifier). Seen red on 93e43d9:
    #   FAIL: close exit 77: the recheck is done with no gap and no slot lost: got ('failed', 1, [...'ui-verifier:T2 was not started: no browser slot is left ...']), want ('done', 0, [])
    rc77 = {**recheck_answers(), **one, closer("v1", True): R("", 77), closer("v2", True): R("", 77)}
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers=rc77)
    rec = finish(s, "close exit 77", rec, err)
    s.eq("close exit 77: the recheck is done with no gap and no slot lost", (result(rec).get("status"), details(rec).get("lost_slots"), details(rec).get("gaps")), ("done", 0, []))
    # a `pw` close that fails keeps the slot of its verifier (`ab` closing is not the whole close of a recheck's verifier)
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers={**recheck_answers(), **one, closer("v1", True): R("", 1)})
    rec = finish(s, "pw close fails", rec, err)
    s.eq("pw close fails: the next verifier does not start beside a Firefox that may be up, and the reason says which close",
         ("ui-verifier:T2" in labels(rec), result(rec).get("status"), str(result(rec).get("reason")).startswith("A browser could not be closed (ui-verifier:T1)")), (False, "failed", True))
    # A runner error on the close (its agent type is missing: the script's own error) confirms nothing either: the browser may be up, so the slot stays
    # taken and no second browser starts beside it, and the run ends with that error. Seen red on a11691f (the slot was freed):
    #   FAIL: close with a missing runner agent type: no second browser starts, the run stops with that error: got (5, 'failed', True), want (1, 'failed', True)
    rec, err = go(script, answers_over={**one, closing("w1"): {"$throw": "agent type fwx:executor not found"}})
    rec = finish(s, "close with a missing runner agent type", rec, err)
    s.eq("close with a missing runner agent type: no second browser starts, the run stops with that error",
         (len(walkers(rec)), result(rec).get("status"), "agent type fwx:executor not found" in str(result(rec).get("reason"))), (1, "failed", True))
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers=recheck_answers())
    rec = finish(s, "close in a recheck", rec, err)
    s.ok("close in a recheck: each verifier's browser is closed", closing("v1") in labels(rec) and closing("v2") in labels(rec), repr(labels(rec)))
    # A recheck's verifier repeats a finding in the browser its `steps` name, and the tramo rebuilt from fix.json cannot say which: `ab` and `pw`
    # are both closed (`pw close` of a session nobody opened is a no-op, exit 0). Seen red on the base (PR 103 review thread, "Close Playwright
    # sessions used during rechecks"; `tramo.firefox` is false there, so a Firefox browser stayed up when the slot was freed):
    #   FAIL: close in a recheck: a Firefox browser a verifier opened is closed too: got [], want ['executor:runner-close-v1-pw', 'executor:runner-close-v2-pw']
    s.eq("close in a recheck: a Firefox browser a verifier opened is closed too", sorted(l for l in labels(rec) if l.endswith("-pw")), [closer("v1", True), closer("v2", True)])


def check_control_rows(script, s):
    """The planted fault is restyled by an init script that every `ab` browser of the run takes, the verifiers' too: a verifier confirms the title
    that reads like body text and `fwx walk converge` would hand it to the fixer as a defect of the repository. The judge names the walker's
    finding (`<session>-F<n>`, as agents/ui-verifier.md says); its verified row, and the rows tied to it by `duplicate_of`, are taken out of the
    verified file before `findings` reads it and kept in control-<tramo>.json. Rows are shaped by the keys of the agent text.

    Red on the base (no runner rewrote the file; the answers below were never asked for):
      FAIL: control row: the verifier confirmed the planted title: it leaves verified-T1.json and goes to control-T1.json: no executor:runner-control-T1 launched
    """
    def row(id, source, verdict="CONFIRMED", **kw):
        return real_row(s, id=id, source=source, verdict=verdict, kind="observed", type="hierarchy", **kw)

    def split(rec):
        """The two writes of the control runner's command: the verified file kept, the control rows set aside."""
        cmd = (runner(rec, "control-T1") or [{"prompt": ""}])[0]["prompt"]
        return (cmd.split(" && ")[-2:] + ["", ""])[:2] + [cmd[-500:] or "no executor:runner-control-T1 launched"]
    judged = {"screen": "/settings", "found": True, "finding": "w2-F1", "why": "w2-F1 says the title reads like body text"}
    rows = [row("T1-1", "w1-F1", clip=RUN_DIR + "/clip-1.webm"), row("T1-2", "w1-F2", "NOT REPRODUCED"), row("T1-3", "w2-F1")]
    over = {"ui-verifier:T1": {"findings": rows}, "ui-verifier:control": judged, "executor:runner-control-T1": R("saved")}
    rec, err = go(script, answers_over=over)
    rec = finish(s, "control row", rec, err)
    ls = labels(rec)
    keep, gone, shown = split(rec)
    s.ok("control row: the verifier confirmed the planted title: it leaves verified-T1.json and goes to control-T1.json",
         RUN_DIR + "/verified-T1.json" in keep and '"T1-3"' not in keep and '"T1-1"' in keep and '"T1-2"' in keep
         and RUN_DIR + "/control-T1.json" in gone and '"T1-3"' in gone and '"T1-1"' not in gone, shown)
    s.ok("control row: it is taken out after the judge and before `findings` reads the files",
         at(ls, "ui-verifier:control") < at(ls, "executor:runner-control-T1") < at(ls, "executor:runner-findings"), repr(ls))
    s.ok("control row: a tramo with no control row is not rewritten", "executor:runner-control-T2" not in ls, repr(ls))
    s.eq("control row: the run is done and the clips are those of the rows kept", (result(rec).get("status"), details(rec).get("clips")), ("done", [RUN_DIR + "/clip-1.webm"]))
    # the control row carries a clip: it is not a clip of a finding the fixer gets
    rec, err = go(script, answers_over={**over, "ui-verifier:T1": {"findings": [row("T1-1", "w1-F1"), row("T1-3", "w2-F1", clip=RUN_DIR + "/control.webm")]}})
    rec = finish(s, "control row clip", rec, err)
    s.eq("control row clip: the clip of the control row is not listed", details(rec).get("clips"), [])
    # the verifier grouped the sightings: the control walker's row is a DUPLICATE of the first one, which carries the verdict; and the other way round
    for what, dup in (("the judged row duplicates a kept sighting", [row("T1-1", "w1-F1"), row("T1-3", "w2-F1", "DUPLICATE", duplicate_of="T1-1")]),
                      ("a row duplicates the judged one", [row("T1-1", "w1-F1", "DUPLICATE", duplicate_of="T1-3"), row("T1-3", "w2-F1")])):
        rec, err = go(script, answers_over={**over, "ui-verifier:T1": {"findings": dup + [row("T1-4", "w1-F9")]}})
        rec = finish(s, "control row, " + what, rec, err)
        keep, gone, shown = split(rec)
        s.ok("control row, %s: both rows of the one defect leave, the other finding stays" % what,
             '"T1-1"' in gone and '"T1-3"' in gone and '"T1-1"' not in keep and '"T1-3"' not in keep and '"T1-4"' in keep, shown)
    # the id the judge names may also be the verified row's own
    rec, err = go(script, answers_over={**over, "ui-verifier:control": dict(judged, finding="T1-3")})
    rec = finish(s, "control row by id", rec, err)
    s.ok("control row by id: a finding named by the id of its verified row leaves too", "executor:runner-control-T1" in labels(rec), repr(labels(rec)))
    for what, ctl in (("not found", dict(judged, found=False, finding=None)), ("not judged", dict(judged, found=None, finding=None)),
                      ("found, no finding named", dict(judged, finding=None))):
        rec, err = go(script, answers_over={**over, "ui-verifier:control": ctl})
        rec = finish(s, "control row, " + what, rec, err)
        s.ok("control row, %s: no file is rewritten" % what, "executor:runner-control-T1" not in labels(rec), repr(labels(rec)))
    rec, err = go(script, answers_over={**over, "executor:runner-control-T1": R("", 1)})
    rec = finish(s, "control row not taken out", rec, err)
    s.ok("control row not taken out: a gap, and a failed run: the fixer must not get it", result(rec).get("status") == "failed"
         and any("control" in g and "T1" in g for g in details(rec).get("gaps", [])), repr((result(rec).get("status"), details(rec).get("gaps"))))


def check_control(script, s):
    rec, err = go(script, answers_over={"ui-verifier:control": {"screen": "/settings", "found": False, "finding": None, "why": "nothing about the title"}})
    rec = finish(s, "control missed", rec, err)
    r = result(rec)
    s.eq("control missed: still done, found false", (r.get("status"), details(rec).get("control", {}).get("found")), ("done", False))
    s.ok("control missed: the reason says first that the run does not count", str(r.get("reason")).lower().startswith("the run does not count"), repr(r.get("reason")))
    # The owner reads this line (the session shows the `reason` as printed): plain words, no "control" or "fault planted" of the walk's own jargon.
    # Seen red on the base: FAIL: control missed: the reason tells the owner, in plain words, that the walkers missed the fault planted on purpose on
    # the screen and that "no findings" proves nothing: 'The run does not count: the walkers did not find the fault planted on /settings.'
    why = str(r.get("reason"))
    s.ok("control missed: the reason tells the owner, in plain words, that the walkers missed the fault planted on purpose on the screen and that \"no findings\" proves nothing",
         "did not report the fault planted on purpose on /settings" in why and 'their "no findings" proves nothing about the screens they walked' in why, repr(why))
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


def peak(w):
    """The most walkers running at one moment: for each walker's start, the intervals that hold that tick."""
    return max([sum(1 for b in w if b["start"] <= a["start"] < b["end"]) for a in w] or [0])


def check_quota(script, s):
    """The quota of browsers is the cap of the configuration that `fwx walk start` prints as `capacity.cap`, sized to the tramos: at most 2
    walkers per tramo, and in a container run never more apps than `start` made (D90). No capacity command exists any more.

    Red on master (the quota came from `fwx walk capacity`, asked after the tramos; the scenario no longer answers it): see the head of this file.
    """
    rec, err = go(script, answers_over=up_cap(1))
    rec = finish(s, "quota 1", rec, err)
    w = walkers(rec)
    s.eq("quota 1: every walker still runs", len(w), 5)
    s.ok("quota 1: no two walkers at once", not any(overlap(a, b) for i, a in enumerate(w) for b in w[i + 1:]),
         repr([(x["label"], x["start"], x["end"]) for x in w]))
    s.ok("quota 1: what stays queued is logged", any("queue" in l and "quota 1" in l for l in rec["logs"]), repr(rec["logs"]))
    rec, err = go(script, answers_over=up_cap(5))
    rec = finish(s, "quota 5", rec, err)
    w = walkers(rec)
    s.ok("quota 5: the walkers of the two tramos run at once", any(overlap(a, b) for i, a in enumerate(w) for b in w[i + 1:]), repr([(x["label"], x["start"], x["end"]) for x in w]))
    # `walk start` is run before the tramos are known, so its `allowed` is for one tramo (2 walkers at most): the quota is the cap sized to the
    # real tramos. The walkers running at each walker's start, itself included: a pairwise overlap count read two at once as three, so a quota
    # capped at two passed.
    rec, err = go(script, answers_over=up_cap(5, allowed=1))
    rec = finish(s, "quota from the cap", rec, err)
    w = walkers(rec)
    s.eq("quota from the cap: 2 tramos, a cap of 5: 4 walkers run at once (2 per tramo)", peak(w), 4)
    for n, want in ((3, 3), (2, 2), (4, 4)):
        rec, err = go(script, answers_over=up_cap(n))
        rec = finish(s, "cap %d" % n, rec, err)
        w = walkers(rec)
        s.eq("cap %d: never more than the cap run at once, and as many as the cap and the tramos allow" % n, peak(w), want)
        s.eq("cap %d: every walker still runs" % n, len(w), 5)
    # a run of a container app: one app per walker `start` made (2 here); the quota never passes them, whatever the cap
    two_apps = [{"name": "walk-1-1-abc123-w%d" % k, "url": APP + "/w%d" % k, "run": ""} for k in (1, 2)]
    up = json.loads(json.dumps(UP))
    up["capacity"].update(cap=5, allowed=2, container=True)
    up["apps"] = two_apps
    rec, err = go(script, answers_over={"executor:runner-up": R(up)})
    rec = finish(s, "container apps", rec, err)
    s.eq("container apps: 2 apps, a cap of 5: two walkers at once", peak(walkers(rec)), 2)
    # no cap, or one that cannot be a cap: nothing is walked, the app is closed, and the run says so: never "all at once"
    for what, cap_value in (("missing", "drop"), ("null", None), ("0", 0), ("negative", -1), ("text", "4"), ("a fraction", 1.5), ("true", True)):
        up = json.loads(json.dumps(UP))
        if cap_value == "drop":
            del up["capacity"]["cap"]
        else:
            up["capacity"]["cap"] = cap_value
        rec, err = go(script, answers_over={"executor:runner-up": R(up)})
        rec = finish(s, "cap %s" % what, rec, err)
        s.ok("cap %s: failed, with a reason that says cap and `fwx walk start`" % what,
             result(rec).get("status") == "failed" and str(result(rec).get("reason", "")).startswith("cap:") and "fwx walk start" in str(result(rec).get("reason", "")),
             repr((result(rec).get("status"), result(rec).get("reason"))))
        s.ok("cap %s: no tramo, no walker, and the app is closed" % what, not walkers(rec) and "ui-verifier:tramos" not in labels(rec) and labels(rec)[-1:] == ["executor:runner-down"],
             repr(labels(rec)))
    rec, err = go(script, answers_over={"executor:runner-up": R({k: v for k, v in UP.items() if k != "capacity"})})
    rec = finish(s, "no capacity in start's output", rec, err)
    s.ok("no capacity in start's output: failed naming the cap", result(rec).get("status") == "failed" and str(result(rec).get("reason", "")).startswith("cap:"), repr(result(rec).get("reason")))


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
    # A saved reply is not a verified tramo: the walkers of T1 reported 2 findings and the verifier answered `{"findings": []}` (or one row), which
    # the script accepted, so the tramo left `details.unverified`, `fix.json` was empty and the run was `done`. The count comes from the walkers'
    # replies (`2 minor`); fewer rows than that is asked for once more, then a gap, and the tramo stays in `unverified`. Seen red on a11691f:
    #   FAIL: verifier with no row for the findings the walkers reported: asked once more, then a gap, failed: got (1, 'done', False), want (2, 'failed', True)
    two = "0 blocker, 2 minor\n%s/findings-w1.md\nthe save bar clips" % RUN_DIR
    for what, reply in (("no row", {"findings": []}), ("one row of two", verified("T1", ("CONFIRMED", None)))):
        rec, err = go(script, answers_over={"ui-walker:T1-breaker": two, "ui-verifier:T1": reply})
        rec = finish(s, "verifier with " + what, rec, err)
        s.eq("verifier with %s for the findings the walkers reported: asked once more, then a gap, failed" % what, (
            len(launched(rec, "ui-verifier:T1")), result(rec).get("status"), any("ui-verifier did not return: T1" in g and "2 finding(s)" in g for g in details(rec).get("gaps", []))),
             (2, "failed", True))
        s.eq("verifier with %s: nothing is saved for the tramo and its files are in details.unverified" % what, (runner(rec, "save-T1"), details(rec).get("unverified")),
             ([], [{"tramo": "T1", "files": [RUN_DIR + "/findings-w1.md", RUN_DIR + "/findings-w2.md"]}]))
    rec, err = go(script, answers_over={"ui-walker:T1-breaker": two, "ui-verifier:T1": verified("T1", ("CONFIRMED", None), ("NOT REPRODUCED", None))})
    rec = finish(s, "verifier with a row for each", rec, err)
    s.eq("verifier with a row for each finding reported: the tramo is verified", (len(launched(rec, "ui-verifier:T1")), result(rec).get("status"), details(rec).get("unverified")), (1, "done", []))
    rec, err = go(script, answers_over={"ui-walker:T1-breaker": "0 blocker, 0 minor\n%s/findings-w1.md\nnone" % RUN_DIR, "ui-verifier:T1": {"findings": []}})
    rec = finish(s, "verifier with no row, none reported", rec, err)
    s.eq("verifier with no row and no finding reported: accepted (an empty walk is a valid result)", (len(launched(rec, "ui-verifier:T1")), result(rec).get("status")), (1, "done"))


def recheck_fixes():
    return [dict(verified("T1", ("CONFIRMED", None))["findings"][0]), dict(verified("T2", ("PLAUSIBLE", None))["findings"][0])]


def recheck_answers():
    fixes = recheck_fixes()
    ans = green()
    ans.update({"executor:runner-read-fix": R(json.dumps(fixes)),
                "ui-verifier:T1": {"findings": [dict(fixes[0], verdict="NOT REPRODUCED", evidence_after="/srv/shots/after-1.png")]},
                "ui-verifier:T2": {"findings": [dict(fixes[1], verdict="PLAUSIBLE", evidence_after="/srv/shots/after-2.png")]},
                "executor:runner-save-T1": R("saved"), "executor:runner-save-T2": R("saved"),
                closer("v1", True): R(""), closer("v2", True): R("")})
    return ans


def check_recheck(script, s):
    """Scenario 2: recheck with a fix.json. Only verifiers; no breaker, no critic, no tramos agent, no control."""
    fixes = recheck_fixes()
    ans = recheck_answers()
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers=ans)
    rec = finish(s, "recheck", rec, err)
    ls = labels(rec)
    s.ok("recheck: no breaker or critic launched (critic launched in recheck)", walkers(rec) == [], repr([l for l in ls if l.startswith("ui-walker")]))
    s.ok("recheck: no tramos agent, no control, no judge", not any(l in ls for l in ("ui-verifier:tramos", "executor:runner-arm-control", "ui-verifier:control")), repr(ls))
    s.ok("recheck: one verifier per tramo of the fix.json", "ui-verifier:T1" in ls and "ui-verifier:T2" in ls, repr(ls))
    s.ok("recheck: no capacity command: the quota is the cap sized to the 2 tramos of the fix.json (cap 4: a quota of 4)",
         not any("capacity" in l for l in ls) and any("a quota of 4 for 2 tramo" in l for l in rec["logs"]), repr((ls, rec["logs"][-4:])))
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
    # `fwx walk start` removes control.json on a restart, so a recheck round has no control: it must not be armed, judged or reported as "not found"
    s.ok("recheck: no control is expected: no judge, found null, and the reason does not say the run does not count",
         "ui-verifier:control" not in ls and d.get("control", {}).get("found") is None and "does not count" not in str(r.get("reason")), repr((d.get("control"), r.get("reason"))))
    s.eq("recheck: fix_file is the one given", d.get("fix_file"), RUN_DIR + "/fix.json")
    s.eq("recheck: the up was run on the work branch's checkout", "fwx walk start --dir '%s' --part 1 --round 1 --repo '%s'" % (PHASE, REPO) in runner(rec, "up")[0]["prompt"], True)
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
    # a reply that holds no row for a finding it was given is no recheck of it: `{"findings": []}` was saved and read as "nothing still there"
    # Red on the base (the reply accepted as long as `findings` was an array; rows shaped by agents/ui-verifier.md), the first of each case:
    #   FAIL: recheck reply with no row: launched once more, then a gap and a failed run: got (1, 'done', False), want (2, 'failed', True)
    #   FAIL: recheck reply that skips one finding of two / with a row twice / with a row nobody gave: the same
    two = [dict(fixes[0], id="T1-1"), dict(fixes[0], id="T1-2"), dict(fixes[1], id="T2-1")]
    base2 = {**ans, "executor:runner-read-fix": R(json.dumps(two))}

    def row(id, verdict="NOT REPRODUCED"):
        return real_row(s, id=id, source="v1-F1", verdict=verdict, kind="observed", type="layout", evidence_after="/srv/shots/after.png")
    whole = {"findings": [row("T2-1")]}
    for what, rows in (("with no row", []), ("that skips one finding of two", [row("T1-1")]), ("with a row twice", [row("T1-1"), row("T1-1"), row("T1-2")]),
                       ("with a row nobody gave", [row("T1-1"), row("T1-2"), row("T1-9")])):
        rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers={**base2, "ui-verifier:T1": {"findings": rows}, "ui-verifier:T2": whole})
        rec = finish(s, "recheck reply " + what, rec, err)
        s.eq("recheck reply %s: launched once more, then a gap and a failed run" % what,
             (len(launched(rec, "ui-verifier:T1")), result(rec).get("status"), [g for g in details(rec).get("gaps", []) if "T1" in g] != []), (2, "failed", True))
        s.ok("recheck reply %s: nothing is saved for the tramo" % what, runner(rec, "save-T1") == [], repr(labels(rec)))
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers={**base2, "ui-verifier:T1": {"findings": [row("T1-2"), row("T1-1", "CONFIRMED")]}, "ui-verifier:T2": whole})
    rec = finish(s, "recheck reply in another order", rec, err)
    s.eq("recheck reply in another order: a row for each finding, in any order, is accepted", (result(rec).get("status"), (details(rec).get("recheck") or {}).get("still"),
         (details(rec).get("recheck") or {}).get("gone")), ("done", 1, 2))
    rec, err = go(script, args_over={"recheck": RUN_DIR + "/fix.json"}, answers={**ans, "executor:runner-read-fix": R("[]")})
    rec = finish(s, "recheck empty", rec, err)
    s.eq("recheck empty: a fix.json with nothing in it is failed, and the browsers closed", (result(rec).get("status"), "executor:runner-down" in labels(rec)), ("failed", True))


def agent_section(name, mode):
    """The text of one `## Mode` section of an agent file, as committed: the stub replies below are copied from it, never typed here."""
    with open(os.path.join(ROOT, "agents", name), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^## Mode `%s`\n(.*?)(?=^## |\Z)" % mode, text, re.S | re.M)
    return m.group(1) if m else ""


def real_row(s, **over):
    """One row of a verify reply with the keys agents/ui-verifier.md names (the optional ones left out), `over` set on top."""
    section = agent_section("ui-verifier.md", "verify")
    keys = re.search(r"each `\{([^}]*)\}`", section)
    s.ok("real verify reply: the row's keys are in the agent text", keys is not None, section[-300:])
    names = [k.strip() for k in (keys.group(1) if keys else "").split(",")]
    row = {k: ("x" if k not in ("severity", "file", "line") else None) for k in names if not k.endswith("?")}
    row.update(over)
    return row


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
    seen = list(dict.fromkeys(APP + x["url"] for t in tramos for x in t.get("screens", [])))  # check-screens prints each screen once
    rec, err = go(script, answers_over={"ui-verifier:tramos": "```json\n%s\n```" % json.dumps(tramos),
                                        "executor:runner-check-screens": R(screens_out(*[(u, 200) for u in seen]))})
    rec = finish(s, "real tramos reply", rec, err, allow_unanswered=True)
    critic = launched(rec, "ui-walker:T1-critic")[0]["prompt"]
    s.ok("real tramos reply: the critic is given the reference its screen carries (REFERENCE (data): none)", all(r in critic for r in refs), critic[:700])
    row = real_row(s, id="T1-1", source="critic1-F2", verdict="NOT REPRODUCED", kind="observed", type="layout")  # copied from the walker's finding, as the text says
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
    check_findings_fails(script, s)
    check_close(script, s)
    check_control_rows(script, s)
    check_control(script, s)
    check_quota(script, s)
    check_tramos(script, s)
    check_screens(script, s)
    check_screens_login(script, s)
    check_critic_context(script, s)
    check_verify(script, s)
    check_recheck(script, s)
    check_args(script, s)
    check_real_replies(script, s)


# (what is wrong with the script, text in it, text instead, the check that must go red). Each anchor is in the script exactly once.
MUTANTS = [
    ("the finally removed", "  } finally {\n    await closeRun()\n  }", "  } catch (e0) {\n    throw e0\n  }\n  await closeRun()", "FAIL: breaker null: walk stop not called after a walker returned nothing"),
    ("the recheck branch removed", "if (A.recheck) {", "if (false) {", "FAIL: recheck: no breaker or critic launched (critic launched in recheck)"),
    ("not armed carries on", "if (up.armed !== true) {", "if (false) {", "FAIL: not armed: status"),
    ("the walkers are not capped", "const SLOTS = () => quota", "const SLOTS = () => 99", "FAIL: quota 1: no two walkers at once"),
    ("the quota is capped at two", "const SLOTS = () => quota", "const SLOTS = () => Math.min(quota, 2)",
     "FAIL: quota from the cap: 2 tramos, a cap of 5"),
    ("the control is armed after the walkers", "await armControl(tramos)", "/* armed later */", "FAIL: green: the control is armed before any walker"),
    ("a missing walker is not a gap", "st.gaps.push('ui-walker did not return: ' + job.tag)", "", "FAIL: breaker null: failed, naming the walker"),
    ("a missed control still counts", "The run does not count", "Run", "FAIL: control missed: the reason says first that the run does not count"),
    ("a missed control's reason in the walk's jargon", "did not report the fault planted on purpose on ' + st.control.screen + ', so their \"no findings\" proves nothing about the screens they walked'",
     "did not find the fault planted on ' + st.control.screen", "FAIL: control missed: the reason tells the owner, in plain words"),
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
    ("the walk keeps the quota `start` gave", "await checkScreens(tramos)\n  sizeQuota(tramos.length)\n", "await checkScreens(tramos)\n",
     "FAIL: quota from the cap: 2 tramos, a cap of 5"),
    ("a slot is freed after a close that was not confirmed", "      if (closed) release()\n      else lose(tag)", "      release()", "FAIL: close not confirmed (rc 1): no second browser starts"),
    ("a close is not tried twice", "for (let i = 0; i < 2; i++) {\n    if (st.fatal) return false", "for (let i = 0; i < 1; i++) {\n    if (st.fatal) return false",
     "FAIL: close not confirmed (rc 1): the close was tried twice"),
    ("a lost slot leaves the queue waiting for ever", "if (st.lost >= quota) for (const next of st.sem.waiting.splice(0)) next(false)", "",
     "FAIL: close not confirmed (rc 1): the script ended"),
    ("a script error on a close frees the slot", "    if (st.fatal) return false\n    if (v && (v.rc === 0 || v.rc === 77)) return true", "    if (st.fatal || (v && (v.rc === 0 || v.rc === 77))) return true",
     "FAIL: close with a missing runner agent type"),
    ("a verifier reply with too few rows is accepted", " && coversWalkers(v.findings, expected, label) ? v : null)", " ? v : null)",
     "FAIL: verifier with no row for the findings the walkers reported"),
    ("the walkers' count is not read", "job.count = reportedCount(got)", "job.count = 0", "FAIL: verifier with no row for the findings the walkers reported"),
    ("the lost-slot counter stuck at 1","  st.lost += 1\n", "  st.lost = 1\n", "FAIL: close not confirmed, quota 2, both lost"),
    ("the `pw` close result ignored", "return ab && pw", "return ab", "FAIL: pw close fails"),
    ("a close that exits 77 is not confirmed", "(v.rc === 0 || v.rc === 77)", "v.rc === 0", "FAIL: close exit 77"),
    ("the findings of an unverified tramo dropped", "unverified: unverified(), lost_slots: st.lost,", "unverified: [], lost_slots: st.lost,",
     "FAIL: close not confirmed, the owner's reading: the findings the walker returned stay in the result as not verified"),
    ("the lost slot after the control's reason", "const lead = [lostLead(), st.noCount ? NO_COUNT + ': ' + st.noCount + '.' : ''].filter(Boolean).join(' ')",
     "const lead = [st.noCount ? NO_COUNT + ': ' + st.noCount + '.' : '', lostLead()].filter(Boolean).join(' ')",
     "FAIL: close not confirmed, the owner's reading: the reason leads with the browser that could not be closed"),
    ("a job that never started is a gap twice", "  if (got === NOSLOT) return null\n", "", "FAIL: close not confirmed, the owner's reading: each job that never started is one gap"),
    ("a recheck closes no Firefox browser","tramo.firefox || items ? await closeBrowser('pw', session) : true", "tramo.firefox ? await closeBrowser('pw', session) : true",
     "FAIL: close in a recheck: a Firefox browser a verifier opened is closed too"),
    ("the recheck keeps the quota `start` gave", "  sizeQuota(tramos.length)\n  st.tramos = tramos.map", "  st.tramos = tramos.map", "FAIL: recheck: no capacity command: the quota is the cap sized"),
    ("a cap that is no number is not refused", "if (!(Number.isInteger(c.cap) && c.cap > 0)) {", "if (false) {", "FAIL: cap missing: failed, with a reason that says cap"),
    ("the cap is not applied", "quota = Math.min(st.cap, 2 * tramos)", "quota = 2 * tramos", "FAIL: cap 3: never more than the cap run at once"),
    ("a container run passes its apps", "  if (st.container) quota = Math.min(quota, st.apps)\n", "", "FAIL: container apps: 2 apps, a cap of 5"),
    ("a recheck reply need not cover its findings", "if (!items) return true", "return true", "FAIL: recheck reply with no row: launched once more"),
    ("a job's browser is not closed", "      if (after) closed = (await after()) !== false\n", "", "FAIL: close: every job's browser is closed after it returned"),
    ("the slot is freed before the browser is closed", "      if (after) closed = (await after()) !== false\n    } finally {\n      if (closed) release()\n      else lose(tag)\n    }",
     "      release()\n      if (after) await after()\n    } finally {\n    }",
     "FAIL: close quota 1: the next job starts only after the previous one's browser was closed"),
    ("the planted control's row goes to the fixer", "if (!fid) return", "return", "FAIL: control row: the verifier confirmed the planted title"),
    ("the rows tied to the control's row stay", "if (out.has(a) !== out.has(b)) {", "if (false) {", "FAIL: control row, the judged row duplicates a kept sighting"),
    ("the control's clip is listed", "if (i >= 0) st.clips.splice(i, 1)", "", "FAIL: control row clip: the clip of the control row is not listed"),
    ("a suffixed id loses its tramo", "f.id.replace(/-\\d+(?:\\.x)*$/, '')", "f.id.replace(/-\\d+$/, '')", "FAIL: recheck suffixed ids: one verifier per tramo"),
    ("the runner may name its stderr file", "never a fixed name in /tmp. ", "", "FAIL: green: the runner is told to keep stderr in a mktemp file"),
    ("the verifier is not told where captures go", "A path in /tmp is refused.", "", "FAIL: green: the verifier is told a screenshot with no path lands"),
    ("a tramo id used raw", "const safe = (id, i) =>", "const safe = (id, i) => id ||", "FAIL: unsafe tramo id"),
    ("the screens are not checked", "  await checkScreens(tramos)\n", "", "FAIL: screens 404: failed, with the screen and the status in the reason"),
    ("the screens are checked after the control", ["  await checkScreens(tramos)\n", "  await armControl(tramos)\n"], ["", "  await armControl(tramos)\n  await checkScreens(tramos)\n"],
     "FAIL: screens green: asked after the tramos and before the control and any walker"),
    ("a screen that does not answer does not stop the walk", "if (v && v.rc === 0 && rows && rows.length === urls.length && bad.length === 0) return",
     "if (true) return", "FAIL: screens 404: failed, with the screen and the status in the reason"),
    ("the exit code decides, not the screens", "&& rows.length === urls.length && bad.length === 0) return", ") return", "FAIL: screens exit 0 and a bad screen"),
    ("a count of screens that is not compared", "rows && rows.length === urls.length && bad.length === 0) return", "rows && bad.length === 0) return",
     "FAIL: screens exit 0 and no screen looked at"),
    ("an app with a login is judged on its screens", "if (v && v.rc === 0 && out && typeof out === 'object' && typeof out.not_run === 'string'", "if (false && v && v.rc === 0 && out && typeof out === 'object' && typeof out.not_run === 'string'",
     "FAIL: screens login: the walk goes on"),
    ("a row with no ok passes", "const bad = rows ? rows.filter((x) => x.ok !== true) : []", "const bad = rows ? rows.filter((x) => x.ok === false) : []",
     "FAIL: screens exit 0 and a row without ok"),
    ("the exit code is not read", "if (v && v.rc === 0 && rows && rows.length === urls.length && bad.length === 0) return", "if (v && rows && rows.length === urls.length && bad.length === 0) return",
     "FAIL: screens exit 1 and every row ok"),
    ("fewer rows than screens pass", "rows && rows.length === urls.length && bad.length === 0) return", "rows && rows.length > 0 && bad.length === 0) return",
     "FAIL: screens exit 0 and fewer rows than screens"),
    ("rows that are no objects are read", "out.screens.filter((x) => x && typeof x === 'object')", "out.screens", "FAIL: screens exit 0 and rows that are no objects"),
    ("the critic is not told to judge the whole screen", "Judge the whole screen against its reference", "Look at the changed element", "FAIL: ui-walker:T1-critic brief: the whole screen is judged"),
    ("the reason does not say what app_run.url is", '". app_run.url is the base address each screen\'s path is appended to (here "', '". (here "',
     "FAIL: screens 404: the reason says app_run.url is the base the screens are appended to"),
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
            sub = helpers.FirstFail(lambda f, want=want: f.startswith(want))  # the control reads one FAIL: the run stops at it
            sub.run(check_all, helpers.write(mdir, "ui-walk.js", m), sub)
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
