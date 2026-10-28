#!/usr/bin/env python3
"""scripts/bench/skill_bench.py: the per-run metrics read from claude's stream-json, and the figures `report` prints
from them (cost per passing task, turns, harness overhead).

Why: a run that spawns background subagents ends with TWO `result` events. Each carries a per-segment `usage` (partial)
and the same cumulative `modelUsage`. `parse_stream` kept the last event's `usage`, so `tokens` and `turns` undercounted
the runs where a workflow fans out: the stream below is the shape of a real one (stored 444,285 tokens and 6 turns;
the cumulative total is 1,602,373 tokens and the turns are 14 + 6). Cost was never affected (`total_cost_usd` is cumulative).

Controls, each seen failing before the fix: on the unchanged `parse_stream` this stream gives tokens 444285, want
1602373, and turns 6, want 20 (checked by hand with the old tuple API); and with the `modelUsage` preference removed from
the fixed code the same cases fail with `tokens = 444285` (mutation run, see the commit message). A report built from old
result.json files (no new fields) must still print, with "-" where a figure does not exist.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "scripts", "bench"))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

SCRIPT = os.path.join(sandbox.FORGE, "scripts", "bench", "skill_bench.py")
failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def line(**ev):
    return json.dumps(ev)


MODEL_USAGE = {"claude-test-1": {"inputTokens": 62, "outputTokens": 28828, "cacheReadInputTokens": 1449088,
                                 "cacheCreationInputTokens": 124395, "costUSD": 0.84}}
# the first main-thread request carries what the harness loads before any work: 2 + 15157 + 11549 = 26708
STREAM = "\n".join([
    line(type="system", subtype="init", model="claude-test-1"),
    line(type="assistant", parent_tool_use_id=None, message={"content": [{"type": "text", "text": "hi"}],
         "usage": {"input_tokens": 2, "cache_creation_input_tokens": 15157, "cache_read_input_tokens": 11549, "output_tokens": 16}}),
    line(type="assistant", parent_tool_use_id=None, message={"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
         "usage": {"input_tokens": 1, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 30000, "output_tokens": 20}}),
    line(type="user", parent_tool_use_id=None, message={"content": [{"type": "tool_result", "is_error": True, "content": "no such file"}]}),
    line(type="assistant", parent_tool_use_id="toolu_sub", message={"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "a"}}],
         "usage": {"input_tokens": 9, "cache_creation_input_tokens": 9, "cache_read_input_tokens": 9, "output_tokens": 9}}),
    line(type="user", parent_tool_use_id="toolu_sub", message={"content": [{"type": "tool_result", "content": "fine"}]}),
    line(type="result", subtype="success", result="first", is_error=False, num_turns=14, total_cost_usd=0.84,
         usage={"input_tokens": 24, "output_tokens": 4242, "cache_creation_input_tokens": 55513, "cache_read_input_tokens": 541315},
         modelUsage=MODEL_USAGE),
    line(type="result", subtype="success", result="the final reply", is_error=False, num_turns=6, total_cost_usd=0.84,
         usage={"input_tokens": 14, "output_tokens": 3415, "cache_creation_input_tokens": 8696, "cache_read_input_tokens": 432160},
         modelUsage=MODEL_USAGE),
])
# an older CLI: no modelUsage, one result event: the per-event usage is all there is
OLD_STREAM = "\n".join([
    line(type="system", subtype="init", model="claude-old"),
    line(type="result", result="done", is_error=False, num_turns=3, total_cost_usd=0.25,
         usage={"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}),
])


def write_result(out, task, arm, trial, **kw):
    d = os.path.join(out, task, arm, str(trial))
    os.makedirs(d, exist_ok=True)
    res = {"task": task, "arm": arm, "trial": trial, "field": "logic", "concept": "logic.arith", "model": "m", "model_id": "claude-test-1",
           "invalid": False, "skill_called": False, "duration_s": 10.0, "checks": []}
    res.update(kw)
    with open(os.path.join(d, "result.json"), "w") as fh:
        json.dump(res, fh)


def main():
    import skill_bench as sb  # noqa: E402

    m = sb.parse_stream(STREAM)
    want("final reply is the last result's", m["msg"], "the final reply")
    want("tokens are the cumulative modelUsage total, not the last segment", m["tokens"], 62 + 28828 + 1449088 + 124395)
    want("cache read tokens", m["cache_read_tokens"], 1449088)
    want("cache write tokens", m["cache_write_tokens"], 124395)
    want("turns are summed over the result events", m["turns"], 20)
    want("cost is the cumulative figure", m["cost"], 0.84)
    want("overhead is the first main-thread request, not a subagent's", m["overhead_tokens"], 2 + 15157 + 11549)
    want("tool calls counted across main thread and subagents", m["tool_calls"], 2)
    want("tool errors counted from tool_result is_error", m["tool_errors"], 1)
    want("model id from init", m["model"], "claude-test-1")

    o = sb.parse_stream(OLD_STREAM)
    want("without modelUsage the result's own usage is used", o["tokens"], 150)
    want("without modelUsage the turns are the result's", o["turns"], 3)
    want("no assistant event: overhead unknown, not 0", o["overhead_tokens"], None)

    tmp = sandbox.mkdtemp("skillbench-metrics-")
    out = os.path.join(tmp, "runs")
    # base `none`: 1 of 2 pass, $0.10 each -> $0.20 per pass; arm `lean`: 2 of 2 pass, $0.15 each -> $0.15 per pass
    for t, passed in (("t0", True), ("t1", False)):
        write_result(out, t, "none", 1, passed=passed, tokens=1000, cost_usd=0.10, turns=10, overhead_tokens=26000)
    for t in ("t0", "t1"):
        write_result(out, t, "lean", 1, passed=True, tokens=800, cost_usd=0.15, turns=8, overhead_tokens=20000)
    # a result written before these fields existed must not break the report
    for t in ("t0", "t1"):
        write_result(out, t, "old", 1, passed=True, tokens=900, cost_usd=0.12)
    r = subprocess.run([sys.executable, SCRIPT, "report", "--out", out, "--base", "none"], capture_output=True, text=True, timeout=120)
    text = r.stdout + r.stderr
    want("report exits 0 with old and new result files mixed", r.returncode, 0)
    lines = text.splitlines()
    none_l = next((l for l in lines if l.strip().startswith("none")), "")
    lean_l = next((l for l in lines if l.strip().startswith("lean")), "")
    old_l = next((l for l in lines if l.strip().startswith("old")), "")
    want("none: cost per pass $0.20", "cost/pass $0.20" in none_l, True)
    want("lean: cost per pass $0.15", "cost/pass $0.15" in lean_l, True)
    want("none: overhead shown", "overhead 26000" in none_l, True)
    want("old results: overhead shown as -", "overhead -" in old_l, True)
    want("delta block names cost per pass against the base", any("cost/pass" in l and "lean" in l and "-25%" in l for l in lines), True)
    want("delta block names turns", any(l.strip().startswith("turns") and "lean" in l for l in lines), True)

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
