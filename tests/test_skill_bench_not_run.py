#!/usr/bin/env python3
"""scripts/bench/skill_bench.py: a run in which the agent never ran is INVALID, never a fail, and a re-run redoes it.

Why: a hook that blocks the prompt (`system` event with prompt_submit_outcome.kind == "blocked_by_hook", then a `result`
with num_turns 0, cost 0, 2 seconds) used to be scored as an ordinary failed run. A baseline calibrated that way would hold
a wall of false failures, and a skill arm would look better than `none` for nothing. The same goes for a CLI that exits
without printing a result, or reports 0 turns. A run that times out is still a fail (the agent did run).

The agent is a fake `claude` whose behaviour FAKE_MODE picks: ok (2 turns, replies "done"), blocked, zero (0 turns, no
hook event) and silent (prints nothing, exits 1). The oracle passes when the reply says "done".

Seen failing before the change: `blocked: (invalid, passed) = (False, False), want (True, None)`, and the same for zero
and silent: all three were scored as plain fails."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

SCRIPT = os.path.join(sandbox.FORGE, "scripts", "bench", "skill_bench.py")
failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


ORACLE = 'def check(repo, message):\n    return [{"id": "said-done", "passed": "done" in message, "evidence": message[:40]}]\n'
FAKE = '''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:2] == ["--version"]:
    print("9.9.9 (Fake Code)")
    sys.exit(0)
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "silent":
    sys.exit(1)
print(json.dumps({"type": "system", "subtype": "init", "model": "fake-model-1"}))
if mode == "blocked":
    print(json.dumps({"type": "system", "subtype": "informational", "level": "warning", "prevent_continuation": True,
                      "content": "UserPromptSubmit operation blocked by hook:\\n[adapter]: the house remains closed.",
                      "prompt_submit_outcome": {"kind": "blocked_by_hook", "prompt_kept": False}}))
turns = 2 if mode == "ok" else 0
print(json.dumps({"type": "result", "result": "done" if mode == "ok" else "", "is_error": False, "num_turns": turns,
                  "total_cost_usd": 0.01 if mode == "ok" else 0,
                  "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}))
'''


def cli(env, *a):
    r = subprocess.run([sys.executable, SCRIPT] + list(a), capture_output=True, text=True, timeout=300, env=env)
    return r.returncode, r.stdout + r.stderr


def result(out):
    for root, _, fs in os.walk(out):
        if "result.json" in fs:
            return json.load(open(os.path.join(root, "result.json")))
    return {}


def main():
    tmp = sandbox.mkdtemp("skillbench-notrun-")
    fake = os.path.join(tmp, "claude")
    put(fake, FAKE)
    os.chmod(fake, 0o755)
    bench = os.path.join(tmp, "bench")
    put(os.path.join(bench, "concepts.json"), json.dumps({"logic.arith": {"field": "logic", "title": "arithmetic"}}))
    d = os.path.join(bench, "tasks", "t0")
    put(os.path.join(d, "task.json"), json.dumps({"id": "t0", "field": "logic", "concept": "logic.arith", "difficulty": 1,
                                                   "prompt": "Say done.", "source": {"kind": "authored"}, "message_required": True}))
    put(os.path.join(d, "repo", "a.py"), "x = 1\n")
    put(os.path.join(d, "oracle.py"), ORACLE)
    common = ["--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--k", "1"]

    for mode, reason in (("blocked", "blocked by a hook"), ("zero", "did not run"), ("silent", "did not run")):
        out = os.path.join(tmp, mode)
        code, text = cli(dict(os.environ, FAKE_MODE=mode), "run", *common, "--out", out, "--arm", "none")
        r = result(out)
        want("%s: (invalid, passed)" % mode, (r.get("invalid"), r.get("passed")), (True, None))
        want("%s: reason names it" % mode, reason in (r.get("invalid_reason") or ""), True)
        want("%s: run line says INVALID" % mode, "INVALID" in text, True)
        code, text = cli(os.environ, "report", "--out", out, "--base", "none")
        want("%s: report counts it as invalid and scores nothing" % mode, ("1 invalid" in text, "pass 0/0" in text), (True, True))

    # a re-run redoes the run in which the agent never ran, and leaves a finished one alone
    out = os.path.join(tmp, "blocked")
    code, text = cli(dict(os.environ, FAKE_MODE="ok"), "run", *common, "--out", out, "--arm", "none")
    r = result(out)
    want("re-run after a blocked run: redone, now valid and passed", (code, r.get("invalid"), r.get("passed")), (0, False, True))
    code, text = cli(dict(os.environ, FAKE_MODE="blocked"), "run", *common, "--out", out, "--arm", "none")
    want("re-run of a finished run: skipped, result kept", ("0 to run, 1 already done" in text, result(out).get("passed")), (True, True))

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
