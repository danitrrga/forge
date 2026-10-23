"""Oracle for logic-boundaries-01 (BigCodeBench/670 via over-editing, range-bounds row).

Checks: the five BigCodeBench tests for task 670 (task_func -> heaviest_substring), a property check against a
brute force over every non-empty substring (any substring of maximum weight is accepted, so tie-breaking is free),
and the project's own tests."""
import json
import random
import re
import subprocess
import sys

BCB_TESTS = r'''
import unittest
class TestCases(unittest.TestCase):
    def test_case_1(self):
        self.assertEqual(task_func('c', {'a': 1, 'b': 2, 'c': 3}), 'c')

    def test_case_2(self):
        self.assertEqual(task_func('aabc', {'a': 10, 'b': -5, 'c': 3}), 'aa')
    def test_case_3(self):
        self.assertEqual(task_func('aabc', {'a': 10, 'b': -2, 'c': 3}), 'aabc')
    def test_case_4(self):
        self.assertEqual(task_func('aabc', {'a': 2, 'b': -5, 'c': 3}), 'aa')

    def test_case_5(self):
        self.assertEqual(task_func('aabc', {'a': 0, 'b': -1, 'c': 1}), 'c')
'''

RUN_BCB = r'''
import json, re, unittest
from textscore.weights import heaviest_substring as task_func
ns = {"task_func": task_func}
exec(compile(TESTS, "bigcodebench_670_tests", "exec"), ns)
out = {}
for name in sorted(n for n in dir(ns["TestCases"]) if n.startswith("test_")):
    r = unittest.TestResult()
    ns["TestCases"](name).run(r)
    bad = r.failures + r.errors
    if not bad:
        out[name] = "ok"
    else:
        tb = bad[0][1].strip().splitlines()
        exc = [l for l in tb if re.match(r"^[A-Za-z_.]*(Error|Exception)\b", l)]
        out[name] = (exc or tb)[-1][:200]
print(json.dumps(out))
'''

RUN_CASES = r'''
import json
from textscore.weights import heaviest_substring
res = []
for text, weights in CASES:
    try:
        res.append(["ok", heaviest_substring(text, weights)])
    except Exception as e:
        res.append(["err", "%s: %s" % (type(e).__name__, e)])
print(json.dumps(res))
'''


def _py(repo, code, timeout=40):
    prog = "import sys\nsys.path.insert(0, %r)\n" % repo + code
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", prog], cwd=repo, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    lines = r.stdout.strip().splitlines()
    if r.returncode or not lines:
        return None, (r.stderr.strip().splitlines() or ["exit %d" % r.returncode])[-1][:300]
    try:
        return json.loads(lines[-1]), None
    except ValueError:
        return None, "unparseable output: " + lines[-1][:200]


def _cases():
    rnd = random.Random(670)
    cases = [("", {"a": 1}), ("z", {"a": 1}), ("ab", {"a": -1, "b": -3}), ("ba", {"a": -1, "b": -3}),
             ("abcab", {"a": 1, "b": -1, "c": 2})]
    for _ in range(60):
        n = rnd.randint(1, 8)
        text = "".join(rnd.choice("abc") for _ in range(n))
        weights = {c: rnd.randint(-5, 5) for c in "abc"}
        cases.append((text, weights))
    return cases


def _best(text, weights):
    subs = [text[i:j] for i in range(len(text)) for j in range(i + 1, len(text) + 1)]
    return max(sum(weights.get(c, 0) for c in s) for s in subs) if subs else None


def _repo_tests(repo):
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=repo, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    ran = re.search(r"Ran (\d+) test", r.stderr)
    n = int(ran.group(1)) if ran else 0
    return r.returncode == 0 and n > 0, "%d test(s) ran, exit %d: %s" % (n, r.returncode, r.stderr.strip().splitlines()[-1:])


def check(repo, message):
    out = []
    res, err = _py(repo, "TESTS = %r\n" % BCB_TESTS + RUN_BCB)
    for name in ("test_case_1", "test_case_2", "test_case_3", "test_case_4", "test_case_5"):
        got = (res or {}).get(name, err or "missing")
        out.append({"id": "bigcodebench-670-" + name, "passed": got == "ok", "evidence": got})

    cases = _cases()
    res, err = _py(repo, "CASES = %r\n" % (cases,) + RUN_CASES)
    bad = []
    if res is None:
        bad.append(err)
    else:
        for (text, weights), (kind, got) in zip(cases, res):
            best = _best(text, weights)
            if kind != "ok":
                bad.append("%r %r raised %s" % (text, weights, got))
            elif not isinstance(got, str) or got not in text:
                bad.append("%r %r -> %r is not a substring" % (text, weights, got))
            elif best is None and got != "":
                bad.append("%r -> %r, want ''" % (text, got))
            elif best is not None and (got == "" or sum(weights.get(c, 0) for c in got) != best):
                bad.append("%r %r -> %r, weight %s, best is %s" % (text, weights, got,
                           sum(weights.get(c, 0) for c in got), best))
    out.append({"id": "max-weight-property", "passed": not bad,
                "evidence": "%d cases; %s" % (len(cases), "; ".join(map(str, bad[:3])) or "all at maximum weight")})

    ok, ev = _repo_tests(repo)
    out.append({"id": "project-tests-pass", "passed": ok, "evidence": ev})
    return out
