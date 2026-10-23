#!/usr/bin/env python3
"""scripts/bench/skill_bench.py run and report: arms of the same tasks, k trials each, scored by the task oracles,
compared with the paired statistics the research in benchmarks/skill-bench/SOURCES.md recommends.

The agent is a fake `claude` (a script the test writes): it finds the task by its prompt, then applies that task's
ideal or naive patch depending on a MODE file in the skill the arm mounted (no skill mounted: naive), and prints the
stream-json lines the real CLI prints. So the outcome of every arm is known in advance and the test can demand it:
the `good` arm passes everything, the `none` arm nothing, the paired difference is exactly 1.

Controls, each failing when its behaviour is removed: the statistics are checked against hand-computed values (a Wilson
interval for 8 of 10, a permutation p-value for an effect that is all-or-nothing and for none at all); an oracle that
crashes makes an invalid run that is counted and left out of the pass rate; a rerun with the same --out skips finished
runs (resume); a run that times out counts as a fail; and arm order is interleaved (no arm runs all its trials first).
Seen failing before the commands existed: "invalid choice: 'run'" (every case)."""
import json
import os
import random
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


def close(label, got, expected, tol=0.01):
    if got is None or abs(got - expected) > tol:
        failures.append("%s = %r, want %r +- %s" % (label, got, expected, tol))


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


START, IDEAL, NAIVE = "def add(a, b):\n    return a - b\n", "def add(a, b):\n    return a + b\n", "def add(a, b):\n    return 5\n"
ORACLE = '''
import sys
def check(repo, message):
    sys.path.insert(0, repo)
    import calc
    return [{"id": "adds", "passed": calc.add(2, 3) == 5, "evidence": "add(2, 3)"},
            {"id": "zero", "passed": calc.add(-1, 1) == 0, "evidence": "add(-1, 1)"}]
'''
CRASH = "def check(repo, message):\n    raise RuntimeError('boom')\n"


def diff(tmp, after):
    a, b = os.path.join(tmp, "pa"), os.path.join(tmp, "pb")
    put(a, START)
    put(b, after)
    return subprocess.run(["diff", "-u", "--label", "a/calc.py", "--label", "b/calc.py", a, b], capture_output=True, text=True).stdout


def make_bench(tmp, n, crash_task=None):
    b = os.path.join(tmp, "bench")
    put(os.path.join(b, "concepts.json"), json.dumps({"logic.arith": {"field": "logic", "title": "arithmetic"}}))
    for i in range(n):
        tid = "t%d" % i
        d = os.path.join(b, "tasks", tid)
        put(os.path.join(d, "task.json"), json.dumps({"id": tid, "field": "logic", "concept": "logic.arith", "difficulty": 1,
                                                       "prompt": "Fix add() in task %d." % i, "source": {"kind": "authored"},
                                                       "message_required": False}))
        put(os.path.join(d, "repo", "calc.py"), START)
        put(os.path.join(d, "oracle.py"), CRASH if tid == crash_task else ORACLE)
        put(os.path.join(d, "ideal", "solution.patch"), diff(tmp, IDEAL))
        put(os.path.join(d, "ideal", "message.md"), "Fixed add and ran it: 5.\n")
        put(os.path.join(d, "naive", "solution.patch"), diff(tmp, NAIVE))
        put(os.path.join(d, "naive", "message.md"), "Done.\n")
    return b


FAKE = '''#!/usr/bin/env python3
import json, os, subprocess, sys, glob, time
args = sys.argv[1:]
if args and args[0] == "--version":
    print("9.9.9 (Fake Code)")
    sys.exit(0)
prompt = args[args.index("-p") + 1] if "-p" in args else ""
tasks = os.environ["FAKE_TASKS"]
mode = "naive"
for f in glob.glob(".claude/skills/*/MODE"):
    mode = open(f).read().strip()
if os.environ.get("FAKE_SLEEP") and mode == "slow":
    time.sleep(float(os.environ["FAKE_SLEEP"]))
for tid in sorted(os.listdir(tasks)):
    meta = json.load(open(os.path.join(tasks, tid, "task.json")))
    if meta["prompt"] in prompt:
        patch = os.path.join(tasks, tid, "naive" if mode in ("naive", "slow") else mode, "solution.patch")
        subprocess.run(["git", "apply", patch], check=True)
        msg = open(os.path.join(tasks, tid, "naive" if mode in ("naive", "slow") else mode, "message.md")).read()
        break
print(json.dumps({"type": "system", "subtype": "init", "model": os.environ.get("FAKE_MODEL_ID", "fake-model-1")}))
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": mode}}]}}))
print(json.dumps({"type": "result", "result": msg, "is_error": False, "num_turns": 3, "duration_ms": 1000,
                  "total_cost_usd": 0.5 if mode == "ideal" else 0.25,
                  "usage": {"input_tokens": 100, "output_tokens": 50 if mode != "ideal" else 100,
                            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}))
'''


def skill(tmp, name, mode):
    d = os.path.join(tmp, "skills", name)
    put(os.path.join(d, "SKILL.md"), "---\nname: %s\ndescription: fake\n---\n" % name)
    put(os.path.join(d, "MODE"), mode)
    return d


def cli(*a, env=None):
    r = subprocess.run([sys.executable, SCRIPT] + list(a), capture_output=True, text=True, env=env, timeout=300)
    return r.returncode, r.stdout + r.stderr


def main():
    import skill_bench as sb  # noqa: E402  (the module under test, for the statistics)
    tmp = sandbox.mkdtemp("skillbench-run-")

    # --- statistics against hand-computed values -------------------------------------------------------------
    lo, hi = sb.wilson(8, 10)
    close("wilson 8/10 low", lo, 0.490)
    close("wilson 8/10 high", hi, 0.943)
    want("wilson 0/0", sb.wilson(0, 0), (None, None))
    rng = random.Random(1)
    diffs = [1.0] * 12
    close("sign-flip p, all 12 tasks improve", sb.sign_flip_p(diffs, rng), 2 / 4096, 0.0005)
    close("sign-flip p, symmetric differences", sb.sign_flip_p([1, -1] * 6, random.Random(1)), 1.0, 0.05)
    ci = sb.bootstrap_ci([1.0] * 12, random.Random(1), 2000)
    want("bootstrap CI of a constant difference", ci, (1.0, 1.0))
    lo, hi = sb.bootstrap_ci([1, 0, 1, 0, 1, 1, 0, 1], random.Random(1), 4000)
    want("bootstrap CI brackets the mean 0.625", lo < 0.625 < hi, True)

    # --- end to end with the fake agent ------------------------------------------------------------------------
    fake = os.path.join(tmp, "claude")
    put(fake, FAKE)
    os.chmod(fake, 0o755)
    bench = make_bench(tmp, 6)
    env = dict(os.environ, FAKE_TASKS=os.path.join(bench, "tasks"))
    good, bad = skill(tmp, "good", "ideal"), skill(tmp, "idle", "naive")
    out = os.path.join(tmp, "runs")
    common = ["--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", out, "--k", "2", "--seed", "7"]
    code, text = cli("run", *common, "--arm", "none", "--arm", "good=" + good, "--arm", "idle=" + bad, env=env)
    want("run: exit 0", (code, "Traceback" in text), (0, False))
    res = [json.load(open(os.path.join(r, f))) for r, _, fs in os.walk(out) for f in fs if f == "result.json"]
    want("run: 6 tasks x 3 arms x 2 trials = 36 results", len(res), 36)
    by = {}
    for r in res:
        by.setdefault(r["arm"], []).append(r["passed"])
    want("arms: good passes every run", by.get("good"), [True] * 12)
    want("arms: none and idle fail every run", (by.get("none"), by.get("idle")), ([False] * 12, [False] * 12))
    want("a skill arm records that the Skill tool was called", all(r["skill_called"] for r in res if r["arm"] == "good"), True)
    want("tokens and cost are recorded", all(r["tokens"] and r["cost_usd"] for r in res), True)
    order = [r["arm"] for r in sorted(res, key=lambda r: r["started"])]
    want("arms are interleaved (the first 6 runs hold more than one arm)", len(set(order[:6])) > 1, True)

    code, text = cli("report", "--out", out, "--base", "none")
    want("report: exit 0", code, 0)
    want("report names the paired difference of arm good as +1.000", "good" in text and "+1.000" in text, True)
    want("report: idle arm shows no difference", any("idle" in l and "+0.000" in l for l in text.splitlines()), True)
    want("report prints discordant counts", "6 better, 0 worse" in text, True)
    want("report prints the token delta", "tokens" in text.lower(), True)

    # space: a finished run keeps result.json and a gzipped transcript, and drops its throwaway working copy
    one = [os.path.join(r) for r, _, fs in os.walk(out) if "result.json" in fs][0]
    want("space: the working copy is gone after scoring", os.path.exists(os.path.join(one, "work")), False)
    want("space: the transcript is gzipped, the plain one removed",
         (os.path.exists(os.path.join(one, "agent.jsonl.gz")), os.path.exists(os.path.join(one, "agent.jsonl"))), (True, False))
    import gzip
    want("space: the gzipped transcript still holds the result line", b'"type": "result"' in gzip.open(os.path.join(one, "agent.jsonl.gz")).read(), True)
    out_keep = os.path.join(tmp, "runs-keep")
    cli("run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", out_keep, "--k", "1", "--tasks", "t0",
        "--arm", "none", "--keep-work", env=env)
    kept = [r for r, _, fs in os.walk(out_keep) if "result.json" in fs][0]
    want("--keep-work keeps the working copy", os.path.isdir(os.path.join(kept, "work")), True)
    # the default output directory is durable (the XDG data dir), not the cache or /tmp, and report/calibrate find the latest run
    xdg = os.path.join(tmp, "xdg")
    env_x = dict(env, XDG_DATA_HOME=xdg)
    code, text = cli("run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--k", "1", "--tasks", "t0", "--arm", "none", env=env_x)
    runs_dir = os.path.join(xdg, "forge", "skill-bench", "runs")
    want("default --out is under $XDG_DATA_HOME/forge/skill-bench/runs", (code, os.path.isdir(runs_dir) and len(os.listdir(runs_dir)) == 1), (0, True))
    code, text = cli("report", "--base", "none", env=env_x)
    want("report without --out reads the latest run", (code, "skill-bench report" in text), (0, True))

    # identity: every run says which model, CLI and skill content produced it, so comparisons are never between unknowns
    man = json.load(open(os.path.join(out, "run.json")))
    want("run.json: model alias, CLI version, k, seed", (man["model_alias"], man["cli_version"], man["k"], man["seed"]), ("sonnet", "9.9.9 (Fake Code)", 2, 7))
    import hashlib

    def tree_hash(d):
        """The documented rule: sha256 over the sorted files, each as relative path, NUL, bytes, NUL."""
        h = hashlib.sha256()
        for root, _, files in sorted(os.walk(d)):
            for f in sorted(files):
                full = os.path.join(root, f)
                h.update(os.path.relpath(full, d).encode() + b"\0" + open(full, "rb").read() + b"\0")
        return h.hexdigest()
    want("run.json: the arm's skill content is pinned by a hash of its files", man["arms"]["good"]["skills"][0]["sha256"], tree_hash(good))
    want("run.json: the none arm mounts nothing", man["arms"]["none"]["skills"], [])
    want("run.json: a fingerprint of the task files and the task list", (len(man["tasks_fingerprint"]), len(man["tasks"])), (64, 6))
    want("every result carries the resolved model id", {r["model_id"] for r in res}, {"fake-model-1"})
    code, text = cli("report", "--out", out, "--base", "none")
    want("report names the model per arm and the CLI", ("fake-model-1" in text and "9.9.9 (Fake Code)" in text), True)
    # the same --out with another model alias, or an arm name whose skill content changed, is refused
    code, text = cli("run", *common[:-4], "--out", out, "--k", "2", "--seed", "7", "--model", "opus", "--arm", "none", env=env)
    want("same --out, another model alias: refused, naming the model", (code, "model" in text.lower()), (1, True))
    import shutil
    shutil.copytree(good, os.path.join(tmp, "skills", "good-b"), dirs_exist_ok=True)
    put(os.path.join(tmp, "skills", "good-b", "EXTRA.md"), "changed\n")
    code, text = cli("run", *common, "--arm", "good=" + os.path.join(tmp, "skills", "good-b"), env=env)
    want("same --out, arm name with other skill content: refused", (code, "good" in text and "changed" in text.lower()), (1, True))
    # arms run on different models cannot be compared by accident
    outm = os.path.join(tmp, "runs-mixed")
    cli("run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", outm, "--k", "1", "--tasks", "t0", "--arm", "none",
        env=dict(env, FAKE_MODEL_ID="model-A"))
    cli("run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", outm, "--k", "1", "--tasks", "t0", "--arm", "good=" + good,
        env=dict(env, FAKE_MODEL_ID="model-B"))
    code, text = cli("report", "--out", outm, "--base", "none")
    want("arms on different models: report refuses and names both", (code, "model-A" in text and "model-B" in text and "different models" in text), (1, True))
    code, text = cli("report", "--out", outm, "--base", "none", "--allow-mixed-models")
    want("--allow-mixed-models lets it through, still naming them", (code, "model-A" in text and "model-B" in text), (0, True))
    cli("calibrate", "--bench", bench, "--out", out)
    want("calibrate records the model id and CLI version", (json.load(open(os.path.join(bench, "calibration.json"))).get("model_ids"),
                                                           json.load(open(os.path.join(bench, "calibration.json"))).get("cli_version")),
         (["fake-model-1"], "9.9.9 (Fake Code)"))

    # resume: a second run with the same --out does no new work
    code, text = cli("run", *common, "--arm", "none", "--arm", "good=" + good, "--arm", "idle=" + bad, env=env)
    want("resume: nothing to run the second time", "0 to run" in text and "36 already done" in text, True)

    # an oracle that crashes is an invalid run: counted, and not a fail
    os.makedirs(os.path.join(tmp, "b2"))
    bench2 = make_bench(os.path.join(tmp, "b2"), 2, crash_task="t1")
    env2 = dict(env, FAKE_TASKS=os.path.join(bench2, "tasks"))
    out2 = os.path.join(tmp, "runs2")
    code, text = cli("run", "--bench", bench2, "--claude-bin", fake, "--sandbox", "none", "--out", out2, "--k", "1",
                     "--arm", "none", "--arm", "good=" + good, env=env2)
    code, text = cli("report", "--out", out2, "--base", "none")
    want("invalid runs are counted in the report", "2 invalid" in text, True)
    want("invalid runs are left out of the pass rate (good: 1 of 1 valid runs)", "good" in text and "1/1" in text, True)

    # a job that cannot even start (no such agent binary) is an invalid run, not a crashed runner; the other jobs finish
    out4 = os.path.join(tmp, "runs4")
    code, text = cli("run", "--bench", bench, "--claude-bin", os.path.join(tmp, "no-such-claude"), "--sandbox", "none", "--out", out4,
                     "--k", "1", "--tasks", "t0,t1", "--arm", "none", "--arm", "good=" + good, env=env)
    r4 = [json.load(open(os.path.join(rr, f))) for rr, _, fs in os.walk(out4) for f in fs if f == "result.json"]
    want("unstartable agent: exit 0, no traceback, every job recorded as invalid with a runner error",
         (code, "Traceback" in text, len(r4), all(r["invalid"] and "runner error" in r.get("invalid_reason", "") for r in r4)), (0, False, 4, True))
    # many workers on a machine with a login: the shared agent home is made once, no job loses a race for it
    fake_home = os.path.join(tmp, "fakehome")
    os.makedirs(os.path.join(fake_home, ".claude"))
    put(os.path.join(fake_home, ".claude", ".credentials.json"), "{}")
    out5 = os.path.join(tmp, "runs5")
    bad5 = []
    for i in range(4):
        shutil_rm = __import__("shutil").rmtree
        shutil_rm(out5, ignore_errors=True)
        code, text = cli("run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", out5, "--k", "1", "--workers", "6",
                         "--arm", "none", "--arm", "good=" + good, env=dict(env, HOME=fake_home))
        n5 = len([1 for rr, _, fs in os.walk(out5) for f in fs if f == "result.json"])
        if code != 0 or n5 != 12:
            bad5.append((code, n5))
    want("6 workers, 4 repeats: every run completes all 12 jobs (no credentials-link race)", bad5, [])

    # a run that exceeds --timeout is a fail, not a crash of the runner
    slow = skill(tmp, "slow", "slow")
    out3 = os.path.join(tmp, "runs3")
    code, text = cli("run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", out3, "--k", "1", "--timeout", "1",
                     "--tasks", "t0", "--arm", "slow=" + slow, env=dict(env, FAKE_SLEEP="5"))
    r = [json.load(open(os.path.join(rr, f))) for rr, _, fs in os.walk(out3) for f in fs if f == "result.json"]
    want("timeout: one result, failed, marked timed out", (len(r), r and r[0]["passed"], r and r[0].get("timed_out")), (1, False, True))

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
