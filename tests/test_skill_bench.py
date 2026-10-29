#!/usr/bin/env python3
"""scripts/bench/skill_bench.py validate: a benchmark task is only evidence if its oracle is proved able to fail and
able to pass. Per task the validator checks that the start state fails the oracle (the task is not already solved),
the ideal and the alternative solution (a second, differently built correct one) both pass it, the naive plausible
wrong solution fails it, the oracle gives the same verdict twice, and it looks at something (zero checks is a
failure). Per benchmark: every concept has at least --min-per-concept tasks.

A toy benchmark is built under /tmp (one concept with two tasks, each a one-function repo and three patches); the
clean one must exit 0 and stay byte-identical, and each case below breaks exactly one thing and must exit 1 naming it.
Seen failing before the script existed: "FileNotFoundError ... scripts/bench/skill_bench.py" (every case)."""
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


def patch(tmp, before, after):
    """A unified diff from one calc.py text to another, paths a/calc.py b/calc.py."""
    a, b = os.path.join(tmp, "pa"), os.path.join(tmp, "pb")
    put(a, before)
    put(b, after)
    r = subprocess.run(["diff", "-u", "--label", "a/calc.py", "--label", "b/calc.py", a, b], capture_output=True, text=True)
    return r.stdout


START = "def add(a, b):\n    return a - b\n"
IDEAL = "def add(a, b):\n    return a + b\n"
ALT = "def add(a, b):\n    return sum((a, b))\n"
NAIVE = "def add(a, b):\n    return 5\n"
ORACLE = '''
import sys
def check(repo, message):
    sys.path.insert(0, repo)
    import calc
    return [{"id": "adds", "passed": calc.add(2, 3) == 5, "evidence": "add(2, 3)"},
            {"id": "zero", "passed": calc.add(-1, 1) == 0, "evidence": "add(-1, 1)"}]
'''


# Verdict of the first check flips on every call (a counter file outside the bench), so two runs always disagree.
FLIP = '''
import os
def check(repo, message):
    p = %r
    n = int(open(p).read()) + 1 if os.path.exists(p) else 1
    open(p, "w").write(str(n))
    return [{"id": "flip", "passed": n %% 2 == 0, "evidence": "run %%d" %% n}]
'''


def task(bench, tid, concept="logic.arith", **over):
    d = os.path.join(bench, "tasks", tid)
    meta = {"id": tid, "field": concept.split(".")[0], "concept": concept, "difficulty": 1, "prompt": "Fix add().",
            "source": {"kind": "authored"}, "message_required": False}
    meta.update(over.pop("meta", {}))
    put(os.path.join(d, "task.json"), json.dumps(meta))
    put(os.path.join(d, "repo", "calc.py"), over.pop("start", START))
    put(os.path.join(d, "oracle.py"), over.pop("oracle", ORACLE))
    for name, after in (("ideal", IDEAL), ("alt", ALT), ("naive", NAIVE)):
        after = over.pop(name, after)
        if after is not None:
            put(os.path.join(d, name, "solution.patch"), after if after.startswith("---") else patch(bench, START, after))
    return d


def bench(tmp, name, tasks=("t1", "t2"), concepts=None):
    b = os.path.join(tmp, name)
    put(os.path.join(b, "concepts.json"), json.dumps(concepts or {"logic.arith": {"field": "logic", "title": "arithmetic"}}))
    for t in tasks:
        task(b, t)
    return b


def run(b, *flags):
    r = subprocess.run([sys.executable, SCRIPT, "validate", "--bench", b] + list(flags), capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def snapshot(b):
    out = {}
    for root, _, files in os.walk(b):
        for f in files:
            p = os.path.join(root, f)
            out[p] = open(p, "rb").read()
    return out


def broken(tmp, name, **over):
    """The clean two-task bench with task t1 rebuilt with one thing broken (over: task() keyword arguments)."""
    b = bench(tmp, name)
    import shutil
    shutil.rmtree(os.path.join(b, "tasks", "t1"))
    task(b, "t1", **over)
    return b


def main():
    tmp = sandbox.mkdtemp("skillbench-test-")
    clean = bench(tmp, "clean")
    before = snapshot(clean)
    code, out = run(clean)
    want("clean bench: exit and summary", (code, "2 tasks" in out and "0 failure" in out), (0, True))
    want("clean bench is left byte-identical", snapshot(clean), before)

    cases = [
        ("ideal fails the oracle", dict(ideal=ALT.replace("sum((a, b))", "a * b")), "ideal"),
        ("alt fails the oracle", dict(alt=ALT.replace("sum((a, b))", "a * b")), "alt"),
        ("naive passes the oracle (weak oracle)", dict(naive=IDEAL), "naive"),
        ("start state already passes", dict(start=IDEAL, ideal=IDEAL + "\n", alt=ALT, naive=NAIVE), "start"),
        ("oracle with zero checks", dict(oracle="def check(repo, message):\n    return []\n"), "zero checks"),
        ("nondeterministic oracle", dict(oracle=FLIP % os.path.join(tmp, "toggle")), "nondeterministic"),
        ("missing alt solution", dict(alt=None), "alt"),
        ("patch that does not apply", dict(ideal="--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-nothing like this\n+x\n"), "apply"),
        ("public source without a licence", dict(meta={"source": {"kind": "public", "ref": "https://example.test/x"}}), "licen"),
        ("id different from the directory", dict(meta={"id": "other"}), "id"),
        ("concept the file does not declare", dict(meta={"concept": "logic.unknown", "field": "logic"}), "concept"),
    ]
    for i, (label, over, needle) in enumerate(cases):
        code, out = run(broken(tmp, "case%d" % i, **over))
        want("%s: exit 1" % label, code, 1)
        want("%s: names %r" % (label, needle), needle in out.lower() and "t1" in out, True)
        want("%s: no traceback" % label, "Traceback" in out, False)
        want("%s: the other task still passes" % label, "t2: ok" in out, True)

    code, out = run(bench(tmp, "hang", tasks=("t1", "t2")), "--oracle-timeout", "1")
    b = bench(tmp, "hang2")
    task_dir = os.path.join(b, "tasks", "t1")
    put(os.path.join(task_dir, "oracle.py"), "import time\ndef check(repo, message):\n    time.sleep(30)\n")
    code, out = run(b, "--oracle-timeout", "1")
    want("hanging oracle: exit 1 and timeout named", (code, "timeout" in out.lower()), (1, True))

    # a task is admitted by calibration (it can fail on the bare model), not by pairing it with a twin: one task per concept is enough by
    # default, and --min-per-concept 2 still demands a second. Seen failing before the default changed: 'a concept with one task: default
    # passes = 1, want 0' (the shipped bench, after pruning the tasks no arm ever failed, has 8 one-task concepts).
    b = bench(tmp, "thin", tasks=("t1",))
    code, out = run(b)
    want("a concept with one task: default passes", code, 0)
    code, out = run(b, "--min-per-concept", "2")
    want("same bench with --min-per-concept 2: exit 1, coverage named", (code, "coverage" in out.lower() and "logic.arith" in out), (1, True))

    b = bench(tmp, "empty", tasks=("t1", "t2"), concepts={"logic.arith": {"field": "logic", "title": "x"}, "ui.none": {"field": "ui", "title": "y"}})
    code, out = run(b)
    want("a declared concept with zero tasks: exit 1", (code, "ui.none" in out), (1, True))

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
