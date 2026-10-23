"""Oracle for logic-money-02 (authored): an even split whose shares add up to the total to the cent.

Contract (split_evenly docstring): everyone pays the same, the leftover cents go one each to the first people in
the list, shares are two-decimal strings in the order given. The cases catch converting with int(float * 100)
(19.99 becomes 1998 cents, 0.29 becomes 28), giving the whole remainder to one person (1.00 between 7) and
rounding every share up or down. Expected shares are written out by hand."""
import json
import re
import subprocess
import sys

NAMES = ["Ana", "Ben", "Cleo", "Dan", "Eva", "Femi", "Gus"]
CASES = {
    "reported-three-way": [(("100.00", 3), ["33.34", "33.33", "33.33"])],
    "amount-not-exact-in-binary": [
        (("19.99", 3), ["6.67", "6.66", "6.66"]),
        (("0.29", 2), ["0.15", "0.14"]),
        (("4.35", 2), ["2.18", "2.17"]),
    ],
    "leftover-spread-one-cent-each": [
        (("1.00", 7), ["0.15", "0.15", "0.14", "0.14", "0.14", "0.14", "0.14"]),
        (("0.05", 3), ["0.02", "0.02", "0.01"]),
        (("0.02", 5), ["0.01", "0.01", "0.00", "0.00", "0.00"]),
        (("1000000.01", 2), ["500000.01", "500000.00"]),
    ],
    "even-splits-unchanged": [
        (("10.00", 4), ["2.50", "2.50", "2.50", "2.50"]),
        (("42.10", 1), ["42.10"]),
        (("0.00", 3), ["0.00", "0.00", "0.00"]),
    ],
}

RUN = r'''
import json
from tab.split import split_evenly
out = {}
for group, cases in CASES.items():
    res = []
    for (total, n), _ in cases:
        try:
            shares = split_evenly(total, NAMES[:n])
            res.append(["ok", [[str(k), str(v)] for k, v in shares.items()]])
        except Exception as e:
            res.append(["err", "%s: %s" % (type(e).__name__, e)])
    out[group] = res
print(json.dumps(out))
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
    res, err = _py(repo, "CASES = %r\nNAMES = %r\n" % (CASES, NAMES) + RUN)
    out = []
    for group, cases in CASES.items():
        got_all = (res or {}).get(group, [])
        bad = []
        for ((total, n), want), got in zip(cases, got_all):
            want_items = [[name, share] for name, share in zip(NAMES[:n], want)]
            if got[0] != "ok":
                bad.append("%s / %d raised %s" % (total, n, got[1]))
            elif got[1] != want_items:
                bad.append("%s / %d -> %s, want %s" % (total, n, " ".join("%s=%s" % tuple(i) for i in got[1]),
                                                      " ".join(want)))
        ok = not err and len(got_all) == len(cases) and not bad
        out.append({"id": group, "passed": ok, "evidence": err or "; ".join(bad) or "%d split(s) right" % len(cases)})
    ok, ev = _repo_tests(repo)
    out.append({"id": "project-tests-pass", "passed": ok, "evidence": ev})
    return out
