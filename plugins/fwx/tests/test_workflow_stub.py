#!/usr/bin/env python3
"""tests/workflow_stub.mjs: runs a workflows/*.js with simulated hooks and records every launch (3.4 U5a).

referent: none, the harness is this repo's own: pstack and marshal test no workflow script, and the real script API
(agent, parallel, pipeline, phase, log, args, workflow, budget) comes from Claude Code's workflow-authoring reference.

Other tests use it through `run_workflow(script, scenario)` of this file (importable: the checks run only as a script).
Scenario JSON: {"args": ..., "answers": {"<label>": answer}, "workflows": {"<name>": answer}, "budget": {"total": N}};
an answer is returned as is, `{"$seq": [...]}` gives one element per call, `{"$throw": "msg"}` makes the call throw, and
`"*"` answers every label that has no entry. A label with no answer is an error in the record, never a silent null.
Record: launches (n, label, prompt, opts, phase, start, end, answer), phases, logs, workflows, swallowed, result,
error, finished, max_concurrent. Exit 0 whenever the record was written (the script's own error is in it), 2 on a usage
problem.

Without `node`: `NOT RUN, NOT ARMED`, exit 77 (checked by running this file with a PATH that holds only python3; the
control runs it again with node added and expects anything but 77).

Red before the stub existed (python3 tests/test_workflow_stub.py), the first lines:
  FAIL: base: stub ran: rc 1, stderr: node:internal/modules/cjs/loader:1607 ... Error: Cannot find module '.../tests/workflow_stub.mjs'
  FAIL: base: launches looked at: got 0, want 3
  FAIL: base: launch order: got [], want ['a', 'b', 'c']

Controls: the checks run on a copy of the stub changed in one place (red seen, copy discarded). The first FAIL line of each:
  options not recorded:      FAIL: base: launch 1: model None, want 'm1'
  written only on success:   FAIL: throws: record exists after an exception: rc 1, no record
  parallel does not null:    FAIL: parallel: a thunk that throws resolves to None: got 'rejected', want [{'ok': True}, None, {'ok': True}]
  pipeline does not null:    FAIL: pipeline: a stage that throws drops its item to None: got 'rejected', want [{'ok': True}, None]
  null answered as {}:       FAIL: base: a null answer reaches the script as None: got [{'ok': True}, {}, {'ok': True}], want [{'ok': True}, None, {'ok': True}]
  Date.now allowed:          FAIL: clock: Date.now() throws in the script: got None, want an error naming Date.now
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
STUB = os.path.join(ROOT, "tests", "workflow_stub.mjs")
TOY = os.path.join(ROOT, "tests", "fixtures", "workflows", "toy.js")
MODELS = {"a": "m1", "b": "m2", "c": "m3", "close": "m4"}
OK = {"ok": True}


def run_workflow(script, scenario, stub=STUB, work=None, timeout=None):
    """Run `script` under the stub with `scenario` (a dict). (rc, record or None, stderr); subprocess.TimeoutExpired after `timeout` s."""
    work = work or helpers.mkdtemp("fwx-wfstub-")
    sc, out = os.path.join(work, "scenario.json"), os.path.join(work, "record.json")
    with open(sc, "w", encoding="utf-8") as f:
        json.dump(scenario, f)
    r = subprocess.run(["node", stub, script, sc, out], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
    rec = None
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            rec = json.load(f)
    return r.returncode, rec, r.stderr.strip()


def toy(stub, mode, answers, **extra):
    sc = {"args": dict({"mode": mode, "models": MODELS, "order": ["a", "b", "c"]}, **extra), "answers": answers}
    return run_workflow(TOY, sc, stub)


def labels(rec):
    return [l["label"] for l in rec["launches"]]


def check_stub(stub, s):
    """Every scenario against `stub`, counted in suite `s`."""
    rc, rec, err = toy(stub, "base", {"a": OK, "b": OK, "c": OK})
    s.ok("base: stub ran", rc == 0 and rec, "rc %s, stderr: %s" % (rc, err[:200]))
    rec = rec or {"launches": [], "phases": [], "logs": []}
    s.eq("base: launches looked at", len(rec["launches"]), 3)
    s.eq("base: launch order", labels(rec), ["a", "b", "c"])
    for i, want in enumerate(["m1", "m2", "m3"]):
        l = rec["launches"][i] if i < len(rec["launches"]) else {"opts": {}}
        s.ok("base: launch %d: model %r, want %r" % (i + 1, l["opts"].get("model"), want), l["opts"].get("model") == want)
        s.eq("base: launch %d agentType" % (i + 1), l["opts"].get("agentType"), "toy:worker")
    s.eq("base: schema is recorded", (rec["launches"] or [{"opts": {}}])[0]["opts"].get("schema", {}).get("required"), ["ok"])
    s.eq("base: prompt is recorded", (rec["launches"] or [{}])[0].get("prompt"), "work on a")
    s.eq("base: phase of each launch", [l.get("phase") for l in rec["launches"]], ["Draft"] * 3)
    s.eq("base: phases", rec["phases"], ["Draft", "Review"])
    s.eq("base: logs", rec["logs"], ["drafted 3"])
    s.eq("base: result", rec.get("result"), [OK, OK, OK])
    s.eq("base: meta name", (rec.get("meta") or {}).get("name"), "toy")
    s.eq("base: no error, finished", (rec.get("error"), rec.get("finished")), (None, True))
    s.eq("base: sequential agents never overlap", rec.get("max_concurrent"), 1)
    s.eq("base: ticks ordered", all(l["start"] < l["end"] for l in rec["launches"]), True)

    rc, rec, _ = toy(stub, "base", {"a": OK, "b": None, "c": OK})
    s.eq("base: a null answer reaches the script as None", (rec or {}).get("result"), [OK, None, OK])

    rc, rec, _ = toy(stub, "throws", {"a": OK, "b": OK, "c": OK})
    s.ok("throws: record exists after an exception", rec, "rc %s, no record" % rc)
    rec = rec or {"launches": [], "error": None}
    s.eq("throws: the two launches before the exception", labels(rec), ["a", "b"])
    s.ok("throws: the exception is in the record", "boom after b" in ((rec.get("error") or {}).get("message") or ""), repr(rec.get("error")))
    s.eq("throws: the script's error is not the stub's (exit 0)", rc, 0)

    rc, rec, _ = toy(stub, "finally", {"a": OK, "b": OK, "close": OK})
    rec = rec or {"launches": [], "error": None}
    s.eq("finally: the cleanup agent launched after the throw", labels(rec), ["a", "b", "close"])
    s.ok("finally: the exception is still in the record", "boom after b" in ((rec.get("error") or {}).get("message") or ""))
    s.eq("finally: its options are recorded", (rec["launches"] or [{"opts": {}}])[-1]["opts"].get("model"), "m4" if rec["launches"] else None)

    rc, rec, _ = toy(stub, "retry", {"a": {"$seq": [None, OK]}})
    rec = rec or {"launches": []}
    s.eq("retry: $seq gives null, then the answer", (rec.get("result"), labels(rec)), (OK, ["a", "a"]))
    rc, rec, _ = toy(stub, "retry", {"a": {"$seq": [None]}})
    s.ok("retry: an exhausted sequence is an error, not a repeat", "exhausted" in (((rec or {}).get("error") or {}).get("message") or ""), repr((rec or {}).get("error")))

    rc, rec, _ = toy(stub, "parallel", {"a": OK, "c": OK})
    rec = rec or {"launches": []}
    s.eq("parallel: a thunk that throws resolves to None", rec.get("result", "rejected") if not rec.get("error") else "rejected", [OK, None, OK])
    s.ok("parallel: the swallowed error is listed", any("thunk blew up" in w.get("message", "") for w in rec.get("swallowed", [])), repr(rec.get("swallowed")))
    s.eq("parallel: thunks start together", rec.get("max_concurrent"), 2)

    rc, rec, _ = toy(stub, "pipeline", {"a": OK, "b": OK, "c": OK})
    rec = rec or {"launches": [], "logs": []}
    s.eq("pipeline: a stage that throws drops its item to None", rec.get("result", "rejected") if not rec.get("error") else "rejected", [OK, None])
    s.eq("pipeline: stages get (prev, item, index)", sorted(rec["logs"]), ["stage2 a 0 prev", "stage2 b 1 prev"])
    s.eq("pipeline: no barrier, a's second stage launched", sorted(labels(rec)), ["a", "b", "c"])

    rc, rec, _ = run_workflow(TOY, {"args": {"mode": "nested"}, "workflows": {"child": {"done": True}}}, stub)
    rec = rec or {}
    s.eq("workflow(): answer and call recorded", (rec.get("result"), [(w["ref"], w["args"]) for w in rec.get("workflows", [])]),
         ({"done": True}, [("child", {"x": 1})]))
    rc, rec, _ = run_workflow(TOY, {"args": {"mode": "nested"}}, stub)
    s.ok("workflow(): an unknown name throws", "unknown workflow" in (((rec or {}).get("error") or {}).get("message") or ""), repr((rec or {}).get("error")))

    rc, rec, _ = toy(stub, "base", {"a": OK, "c": OK})
    rec = rec or {"launches": []}
    s.ok("unanswered label: an error naming it, in the record", '"b"' in (((rec.get("error") or {}).get("message")) or ""), repr(rec.get("error")))
    s.eq("unanswered label: the launch is recorded", labels(rec), ["a", "b"])
    rc, rec, _ = toy(stub, "base", {"*": OK})
    s.eq("`*` answers every label", (rec or {}).get("result"), [OK, OK, OK])

    rc, rec, _ = toy(stub, "base", {"a": {"ok": "yes"}, "b": OK, "c": OK})
    rec = rec or {}
    s.ok("schema: an answer that breaks it is an error in the record", "schema" in (((rec.get("error") or {}).get("message")) or ""), repr(rec.get("error")))

    rc, rec, _ = toy(stub, "clock", {})
    s.ok("clock: Date.now() throws in the script", "Date.now" in (((rec or {}).get("error") or {}).get("message") or ""),
         "got %r, want an error naming Date.now" % ((rec or {}).get("result"),))

    rc, rec, _ = toy(stub, "host", {})
    s.eq("host: the script sees no process and no require", (rec or {}).get("logs"), ["process undefined require undefined"])


def check_runaway(stub, s):
    """A script that launches for ever is stopped by the stub after a count of launches (exit 124, the record says why), not by
    the caller's clock: a mutant of a workflow that loops used to cost the caller its whole time limit (25 s) per scenario."""
    work = helpers.mkdtemp("fwx-wfloop-")
    loop = helpers.write(work, "loop.js", "export const meta = {name: 'loop', description: 'never ends'}\nwhile (true) await agent('x', {label: 'a'})\n")
    try:
        rc, rec, err = run_workflow(loop, {"answers": {"a": OK}}, stub, work=work, timeout=8)
    except subprocess.TimeoutExpired:
        s.ok("runaway: the stub ends a script that launches for ever", False, "still running after 8 s")
        return
    s.eq("runaway: exit 124", rc, 124)
    s.ok("runaway: the record holds what ran and says the script did not end",
         bool(rec) and len(rec["launches"]) > 100 and rec["finished"] is False and "did not end" in ((rec["error"] or {}).get("message") or ""),
         repr(rec and (len(rec["launches"]), rec["finished"], rec["error"])))
    rc, rec, err = run_workflow(TOY, {"args": {"mode": "base", "models": MODELS, "order": ["a", "b", "c"]}, "answers": {"a": OK, "b": OK, "c": OK}},
                                stub, timeout=30)
    s.ok("runaway: a script that ends is not touched by the limit", rc == 0 and rec and rec["finished"] is True and len(rec["launches"]) == 3, "rc %s" % rc)


def check_edges(s):
    work = helpers.mkdtemp("fwx-wfedge-")
    bad = helpers.write(work, "bad.js", "export const meta = {name: 'x', description: 'y'}\nconst = 1\n")
    rc, rec, _ = run_workflow(bad, {}, work=helpers.mkdtemp("fwx-wfedge-"))
    s.ok("syntax error: a record with a compile error, exit 0", rc == 0 and rec and (rec.get("error") or {}).get("stage") == "compile", "rc %s %r" % (rc, rec and rec.get("error")))
    nometa = helpers.write(work, "nometa.js", "return 1\n")
    rc, rec, _ = run_workflow(nometa, {}, work=helpers.mkdtemp("fwx-wfedge-"))
    s.ok("no meta: refused as the real tool does", rec and "meta" in ((rec.get("error") or {}).get("message") or ""), repr(rec and rec.get("error")))
    r = subprocess.run(["node", STUB], capture_output=True, text=True)
    s.eq("usage: no arguments exits 2", r.returncode, 2)
    r = subprocess.run(["node", STUB, os.path.join(work, "missing.js"), os.path.join(work, "s.json"), os.path.join(work, "o.json")],
                       capture_output=True, text=True)
    s.eq("usage: a missing script exits 2 and writes nothing", (r.returncode, os.path.exists(os.path.join(work, "o.json"))), (2, False))
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "lib", "fwx", "lint_models.py"), TOY], capture_output=True, text=True)
    s.eq("lint: the toy passes the model lint named on the command line", r.returncode, 0)


# (what is wrong with the stub, text in its source, text instead, the check that must go red)
MUTANTS = [
    ("options not recorded", "opts: clone(opts)", "opts: {}", "FAIL: base: launch 1: model None, want 'm1'"),
    ("written only on success", ["function flush() {", "  } catch (e) {\n    rec.error = describe(e)\n  } finally {"],
     ["function flush() { if (!rec.finished) return", "  } catch (e) {\n    throw e\n  } finally {"],
     "FAIL: throws: record exists after an exception"),
    ("parallel does not null", "/*P*/ return null", "/*P*/ throw e", "FAIL: parallel: a thunk that throws resolves to None"),
    ("pipeline does not null", "/*L*/ return null", "/*L*/ throw e", "FAIL: pipeline: a stage that throws drops its item to None"),
    ("null answered as {}", "return value === null ? null : clone(value)", "return clone(value ?? {})",
     "FAIL: base: a null answer reaches the script as None"),
    ("Date.now allowed", "/*D*/ throw new Error(", "/*D*/ return 0; new Error(", "FAIL: clock: Date.now() throws in the script"),
    ("no launch limit", "const MAX_LAUNCHES = 400", "const MAX_LAUNCHES = 1e12", "FAIL: runaway: the stub ends a script that launches for ever"),
]


def mutate(src, old, new):
    olds, news = (old, new) if isinstance(old, list) else ([old], [new])
    for o, n in zip(olds, news):
        if o not in src:
            return None
        src = src.replace(o, n)
    return src


def check_controls(s):
    if not s.ok("controls: the stub exists", os.path.exists(STUB)):
        return
    with open(STUB, encoding="utf-8") as f:
        src = f.read()
    for name, old, new, want in MUTANTS:
        m = mutate(src, old, new)
        if not s.ok("control %s: the anchor is in the stub" % name, m is not None):
            continue
        path = helpers.write(helpers.mkdtemp("fwx-wfmut-"), "workflow_stub.mjs", m)
        sub = helpers.Suite()
        check_stub(path, sub)
        check_runaway(path, sub)
        s.ok("control %s: red with %r" % (name, want), any(f.startswith(want) for f in sub.fails),
             "got %r" % (sub.fails[:2],))
    check_stub_good = helpers.Suite()
    check_stub(STUB, check_stub_good)
    s.eq("control: the real stub is green under the same checks", check_stub_good.fails, [])


def check_no_node(s):
    """The test run with a PATH that holds no node: NOT RUN, NOT ARMED and 77; with node on it, the same run is armed."""
    fake = helpers.mkdtemp("fwx-fakepath-")
    os.symlink(sys.executable, os.path.join(fake, "python3"))
    me = os.path.realpath(__file__)
    env = helpers.clean_env(PATH=fake, FWX_STUB_NESTED="1")
    r = subprocess.run([os.path.join(fake, "python3"), me], env=env, capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    s.eq("no node: exit 77", r.returncode, 77)
    s.ok("no node: last line", last.startswith("NOT RUN, NOT ARMED"), repr(last))
    os.symlink(shutil.which("node"), os.path.join(fake, "node"))
    r = subprocess.run([os.path.join(fake, "python3"), me], env=env, capture_output=True, text=True)
    s.ok("control: with node on PATH the same run is armed, not 77", r.returncode != 77, "rc %s: %s" % (r.returncode, r.stdout[-200:]))


def main():
    s = helpers.Suite()
    if not shutil.which("node"):
        s.not_run("node is not on PATH")
    check_stub(STUB, s)
    check_edges(s)
    check_runaway(STUB, s)
    if not os.environ.get("FWX_STUB_NESTED"):  # the controls and the PATH run call this file again
        check_controls(s)
        check_no_node(s)
    s.done()


if __name__ == "__main__":
    main()
