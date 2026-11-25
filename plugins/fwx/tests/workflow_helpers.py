"""What a test of a workflow script shares: running one under tests/workflow_stub.mjs and reading the record of its launches.

referent: none, moved from tests/test_execute_workflow.py (the suite of workflows/execute.js, deleted in 09.6 T62); test_ui_walk_workflow.py is the one
suite that runs a workflow script now.

The name does not match test_*.py, so `forge test fwx` never runs it; the tests import it.
"""
import json
import os
import subprocess

import helpers

ROOT = helpers.ROOT


def R(obj, rc=0):
    """What a runner returns: the stdout of the command and its exit code."""
    return {"stdout": obj if isinstance(obj, str) else json.dumps(obj), "rc": rc}


def run_capped(script, scenario, seconds=25):
    """Run `script` under the stub; one that never ends (a mutant that loops on a scenario that always answers) is killed after
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


def labels(rec):
    return [l["label"] for l in rec["launches"]]


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


def mutate(src, old, new):
    """`src` with `old` replaced by `new` (or each of two lists, in order), or None when an anchor is not in it exactly once."""
    olds, news = (old, new) if isinstance(old, list) else ([old], [new])
    for o, n in zip(olds, news):
        if src.count(o) != 1:
            return None
        src = src.replace(o, n)
    return src
