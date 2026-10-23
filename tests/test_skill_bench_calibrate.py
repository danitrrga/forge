#!/usr/bin/env python3
"""skill_bench.py calibrate and the `hard` selector: only tasks a model can still fail carry signal about a skill.

`calibrate` reads the results of a run of the no-skill arm (several trials per task) and writes <bench>/calibration.json:
per task the baseline pass rate over valid trials, with the model and date. `--tasks hard[:RATE]` selects the tasks whose
baseline rate is at most RATE (default 0.7); it refuses when the bench was never calibrated. `report` prints how many tasks
were saturated (baseline at least 0.9, no room to improve) so a flat score is read for what it is.

The fake agent solves the tasks named in FAKE_SOLVE with the ideal patch and fails the rest, so the baseline rate of every
task is known: t0 and t1 are always solved (saturated), t2 and t3 never (hard). Controls: with the `hard` selector removed
from select_tasks the run picks all four; with the rate comparison inverted it picks the saturated ones; an uncalibrated
bench is refused with a message naming `calibrate`. Seen failing before the commands existed: "invalid choice: 'calibrate'"."""
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


START, IDEAL = "def add(a, b):\n    return a - b\n", "def add(a, b):\n    return a + b\n"
ORACLE = ("import sys\ndef check(repo, message):\n    sys.path.insert(0, repo)\n    import calc\n"
          "    return [{'id': 'adds', 'passed': calc.add(2, 3) == 5, 'evidence': 'add(2, 3)'}]\n")
FAKE = '''#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
tasks = os.environ["FAKE_TASKS"]
solve = os.environ.get("FAKE_SOLVE", "").split(",")
for tid in sorted(os.listdir(tasks)):
    meta = json.load(open(os.path.join(tasks, tid, "task.json")))
    if meta["prompt"] in prompt:
        if tid in solve:
            subprocess.run(["git", "apply", os.path.join(tasks, tid, "ideal", "solution.patch")], check=True)
        break
print(json.dumps({"type": "result", "result": "done", "is_error": False, "num_turns": 1,
                  "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.01}))
'''


def make_bench(tmp):
    b = os.path.join(tmp, "bench")
    put(os.path.join(b, "concepts.json"), json.dumps({"logic.arith": {"field": "logic", "title": "arith"}}))
    pa, pb = os.path.join(tmp, "pa"), os.path.join(tmp, "pb")
    put(pa, START)
    put(pb, IDEAL)
    patch = subprocess.run(["diff", "-u", "--label", "a/calc.py", "--label", "b/calc.py", pa, pb], capture_output=True, text=True).stdout
    for i in range(4):
        d = os.path.join(b, "tasks", "t%d" % i)
        put(os.path.join(d, "task.json"), json.dumps({"id": "t%d" % i, "field": "logic", "concept": "logic.arith", "difficulty": 1,
                                                       "prompt": "Fix add() in task %d." % i, "source": {"kind": "authored"}, "message_required": False}))
        put(os.path.join(d, "repo", "calc.py"), START)
        put(os.path.join(d, "oracle.py"), ORACLE)
        put(os.path.join(d, "ideal", "solution.patch"), patch)
    return b


def cli(*a, env=None):
    r = subprocess.run([sys.executable, SCRIPT] + list(a), capture_output=True, text=True, env=env, timeout=300)
    return r.returncode, r.stdout + r.stderr


def main():
    tmp = sandbox.mkdtemp("skillbench-cal-")
    bench = make_bench(tmp)
    fake = os.path.join(tmp, "claude")
    put(fake, FAKE)
    os.chmod(fake, 0o755)
    env = dict(os.environ, FAKE_TASKS=os.path.join(bench, "tasks"), FAKE_SOLVE="t0,t1")
    out = os.path.join(tmp, "runs")
    common = ["--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", out, "--k", "3"]

    code, text = cli("run", *common, "--arm", "none", env=env)
    want("baseline run: exit 0", code, 0)

    code, text = cli("select", "--bench", bench, "--tasks", "hard")
    want("hard on an uncalibrated bench is refused, naming calibrate", (code, "calibrate" in text), (1, True))

    code, text = cli("calibrate", "--bench", bench, "--out", out)
    want("calibrate: exit 0", code, 0)
    cal = json.load(open(os.path.join(bench, "calibration.json")))
    want("calibration: baseline rates", {t: cal["tasks"][t]["rate"] for t in sorted(cal["tasks"])}, {"t0": 1.0, "t1": 1.0, "t2": 0.0, "t3": 0.0})
    want("calibration: trials counted", cal["tasks"]["t0"]["n"], 3)
    want("calibration: model and arm recorded", (cal.get("arm"), "model" in cal), ("none", True))

    # an invalid run (the oracle crashed) is not a trial: it must not enter the baseline rate or its count
    inv = os.path.join(out, "t0", "none", "9")
    put(os.path.join(inv, "result.json"), json.dumps({"task": "t0", "arm": "none", "trial": 9, "invalid": True, "passed": None}))
    cli("calibrate", "--bench", bench, "--out", out)
    cal2 = json.load(open(os.path.join(bench, "calibration.json")))
    want("invalid runs stay out of the calibration", (cal2["tasks"]["t0"]["n"], cal2["tasks"]["t0"]["rate"]), (3, 1.0))
    shutil_rm = __import__("shutil").rmtree
    shutil_rm(inv)

    code, text = cli("select", "--bench", bench, "--tasks", "hard")
    want("hard selects the tasks the baseline fails", (code, text.split()), (0, ["t2", "t3"]))
    code, text = cli("select", "--bench", bench, "--tasks", "hard:1.0")
    want("hard:1.0 selects every task", text.split(), ["t0", "t1", "t2", "t3"])
    code, text = cli("select", "--bench", bench, "--tasks", "field:logic,hard")
    want("hard combines with another selector (intersection)", text.split(), ["t2", "t3"])

    code, text = cli("report", "--out", out, "--base", "none")
    want("report names the saturated tasks", "2 of 4 tasks are saturated" in text, True)

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
