"""Oracle for logic-datetime-01 (authored): monthly renewals across month ends, leap days and year ends.

Contract (renewal_dates docstring): renew on the start's day of the month; in a month too short for it, on that
month's last day. So a 31 January plan renews 29 February 2024 and then 31 March (not 29 March): every renewal is
anchored on the start, not on the previous renewal. Expected dates below are written out by hand."""
import json
import re
import subprocess
import sys
from datetime import date

CASES = {
    "month-end-clamp": [
        (("2024-01-31", 2), ["2024-02-29", "2024-03-31"]),
        (("2023-01-31", 1), ["2023-02-28"]),
        (("2024-03-31", 1), ["2024-04-30"]),
    ],
    "anchored-on-start-day": [
        (("2024-01-31", 14), ["2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31", "2024-06-30", "2024-07-31",
                              "2024-08-31", "2024-09-30", "2024-10-31", "2024-11-30", "2024-12-31", "2025-01-31",
                              "2025-02-28", "2025-03-31"]),
        (("2024-08-30", 7), ["2024-09-30", "2024-10-30", "2024-11-30", "2024-12-30", "2025-01-30", "2025-02-28",
                             "2025-03-30"]),
        (("2024-02-29", 13), ["2024-03-29", "2024-04-29", "2024-05-29", "2024-06-29", "2024-07-29", "2024-08-29",
                              "2024-09-29", "2024-10-29", "2024-11-29", "2024-12-29", "2025-01-29", "2025-02-28",
                              "2025-03-29"]),
    ],
    "year-rollover": [
        (("2025-11-30", 4), ["2025-12-30", "2026-01-30", "2026-02-28", "2026-03-30"]),
        (("2025-12-15", 2), ["2026-01-15", "2026-02-15"]),
        (("2023-12-31", 3), ["2024-01-31", "2024-02-29", "2024-03-31"]),
    ],
    "ordinary-days-unchanged": [
        (("2024-01-10", 3), ["2024-02-10", "2024-03-10", "2024-04-10"]),
        (("2024-05-01", 0), []),
    ],
}
NEXT_CASES = [
    (("2024-01-31", "2024-03-01"), "2024-03-31"),
    (("2024-01-31", "2024-02-01"), "2024-02-29"),
]

RUN = r'''
import json
from datetime import date
from subscriptions.renewals import renewal_dates, next_renewal
out = {"renewals": {}, "next": []}
for group, cases in CASES.items():
    res = []
    for (start, n), _ in cases:
        try:
            res.append(["ok", [d.isoformat() for d in renewal_dates(date.fromisoformat(start), n)]])
        except Exception as e:
            res.append(["err", "%s: %s" % (type(e).__name__, e)])
    out["renewals"][group] = res
for (start, today), _ in NEXT_CASES:
    try:
        out["next"].append(["ok", next_renewal(date.fromisoformat(start), date.fromisoformat(today)).isoformat()])
    except Exception as e:
        out["next"].append(["err", "%s: %s" % (type(e).__name__, e)])
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


def _first_diff(got, want):
    for i, (g, w) in enumerate(zip(got, want)):
        if g != w:
            return "renewal %d is %s, want %s" % (i + 1, g, w)
    return "%d dates, want %d" % (len(got), len(want))


def check(repo, message):
    res, err = _py(repo, "CASES = %r\nNEXT_CASES = %r\n" % (CASES, NEXT_CASES) + RUN)
    out = []
    for group, cases in CASES.items():
        bad = []
        got_all = (res or {}).get("renewals", {}).get(group, [])
        for ((start, n), want), got in zip(cases, got_all):
            if got[0] != "ok":
                bad.append("%s x%d raised %s" % (start, n, got[1]))
            elif got[1] != want:
                bad.append("%s x%d: %s" % (start, n, _first_diff(got[1], want)))
        ok = not err and len(got_all) == len(cases) and not bad
        out.append({"id": group, "passed": ok, "evidence": err or "; ".join(bad) or "%d series right" % len(cases)})
    bad = []
    for ((start, today), want), got in zip(NEXT_CASES, (res or {}).get("next", [])):
        if got != ["ok", want]:
            bad.append("next_renewal(%s, %s) = %s, want %s" % (start, today, got[1], want))
    out.append({"id": "next-renewal-follows", "passed": not err and not bad,
                "evidence": err or "; ".join(bad) or "%d right" % len(NEXT_CASES)})
    ok, ev = _repo_tests(repo)
    out.append({"id": "project-tests-pass", "passed": ok, "evidence": ev})
    return out
