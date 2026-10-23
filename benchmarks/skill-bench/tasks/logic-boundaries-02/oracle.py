"""Oracle for logic-boundaries-02 (BigCodeBench/6 via over-editing, list-indexing row).

Checks: the five BigCodeBench tests for task 6 (task_func -> latest_log, mocks unchanged), the same contract on
real files with real modification times (one, two and three matching files, a newer non-matching file), and the
project's own tests."""
import json
import re
import subprocess
import sys

BCB_TESTS = r'''
import unittest
from unittest.mock import patch
import os
import re
class TestCases(unittest.TestCase):

    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_case_1(self, mock_getmtime, mock_listdir):
        # Test that no log files are returned when none match the regex pattern
        mock_listdir.return_value = ["file1.txt", "file2.log", "access.log.abc"]
        result = task_func(r'^access.log.[0-9]+$', '/mock_dir/')
        self.assertIsNone(result)

    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_case_2(self, mock_getmtime, mock_listdir):
        # Test that the correct latest log file is returned when multiple files match the regex
        mock_listdir.return_value = ["access.log.1", "access.log.2", "access.log.3"]
        mock_getmtime.side_effect = [3, 1, 2]
        result = task_func(r'^access.log.[0-9]+$', '/mock_dir/')
        self.assertEqual(result, '/mock_dir/access.log.1')

    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_case_3(self, mock_getmtime, mock_listdir):
        # Test that a correct single matching log file is returned among non-matching ones
        mock_listdir.return_value = ["file1.txt", "file2.log", "access.log.123"]
        mock_getmtime.return_value = 1
        result = task_func(r'^access.log.[0-9]+$', '/mock_dir/')
        self.assertEqual(result, '/mock_dir/access.log.123')

    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_case_4(self, mock_getmtime, mock_listdir):
        # Test that None is returned when the directory is empty
        mock_listdir.return_value = []
        result = task_func(r'^access.log.[0-9]+$', '/mock_dir/')
        self.assertIsNone(result)

    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_case_5(self, mock_getmtime, mock_listdir):
        # Test the function with the default directory parameter to ensure it handles defaults properly
        mock_listdir.return_value = ["access.log.999"]
        mock_getmtime.return_value = 1
        result = task_func(r'^access.log.[0-9]+$')
        self.assertEqual(result, '/var/log/access.log.999')
'''

RUN_BCB = r'''
import json, re, unittest
from logtools.latest import latest_log as task_func
ns = {"task_func": task_func}
exec(compile(TESTS, "bigcodebench_6_tests", "exec"), ns)
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

# (files as (name, mtime), expected name or None)
FS_CASES = [
    ([("access.log.7", 1000)], "access.log.7"),
    ([("access.log.1", 1000), ("access.log.2", 2000)], "access.log.2"),
    ([("access.log.2", 2000), ("access.log.1", 1000)], "access.log.2"),
    ([("access.log.1", 1000), ("access.log.2", 3000), ("access.log.3", 2000), ("error.log", 9000)], "access.log.2"),
    ([("access.log.10", 5000), ("access.log.9", 4000), ("access.log.11", 3000)], "access.log.10"),
    ([("error.log", 9000)], None),
]

RUN_FS = r'''
import json, os, tempfile
from logtools.latest import latest_log
res = []
for files, _ in CASES:
    with tempfile.TemporaryDirectory() as d:
        for name, mtime in files:
            p = os.path.join(d, name)
            with open(p, "w") as fh:
                fh.write("x\n")
            os.utime(p, (mtime, mtime))
        try:
            got = latest_log(r'^access.log.[0-9]+$', d)
            res.append(["ok", None if got is None else os.path.relpath(os.path.realpath(got), os.path.realpath(d))])
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
        out.append({"id": "bigcodebench-6-" + name, "passed": got == "ok", "evidence": got})

    res, err = _py(repo, "CASES = %r\n" % (FS_CASES,) + RUN_FS)
    bad = []
    if res is None:
        bad.append(err)
    else:
        for (files, want), (kind, got) in zip(FS_CASES, res):
            if kind != "ok" or got != want:
                bad.append("%s -> %s %r, want %r" % ([f for f, _ in files], kind, got, want))
    out.append({"id": "newest-on-real-files", "passed": not bad,
                "evidence": "%d directories; %s" % (len(FS_CASES), "; ".join(map(str, bad[:3])) or "newest file every time")})

    ok, ev = _repo_tests(repo)
    out.append({"id": "project-tests-pass", "passed": ok, "evidence": ev})
    return out
