"""Oracle for logic-datetime-02 (authored): elapsed time across daylight-saving changes with zoneinfo.

Europe/Madrid in 2026: clocks go forward at 02:00 on 29 March (a night shift 22:00-06:00 lasts 7 h) and back at
03:00 on 25 October (the same shift lasts 9 h). Python subtracts and adds aware datetimes that share a tzinfo as
wall-clock times, so both shift_hours and shift_end are wrong across a change. Times that do not exist or occur
twice are avoided, so no fold policy is needed. Needs the system tz database (zoneinfo)."""
import json
import math
import re
import subprocess
import sys

HOURS = {
    "hours-ordinary": [(("2026-06-10 09:00", "2026-06-10 17:00"), 8.0), (("2026-01-10 22:00", "2026-01-11 06:00"), 8.0)],
    "hours-spring-forward": [(("2026-03-28 22:00", "2026-03-29 06:00"), 7.0), (("2026-03-29 00:30", "2026-03-29 04:00"), 2.5)],
    "hours-fall-back": [(("2026-10-24 22:00", "2026-10-25 06:00"), 9.0), (("2026-10-25 00:00", "2026-10-25 04:15"), 5.25)],
}
ENDS = {
    "end-ordinary": [(("2026-06-10 09:00", 8), "2026-06-10 17:00"), (("2026-01-10 22:00", 8), "2026-01-11 06:00")],
    "end-spring-forward": [(("2026-03-28 22:00", 8), "2026-03-29 07:00"), (("2026-03-28 23:00", 7.5), "2026-03-29 07:30")],
    "end-fall-back": [(("2026-10-24 22:00", 8), "2026-10-25 05:00"), (("2026-10-24 23:30", 6), "2026-10-25 04:30")],
}
WEEK = ([("2026-03-27 22:00", "2026-03-28 06:00"), ("2026-03-28 22:00", "2026-03-29 06:00"),
         ("2026-03-30 09:00", "2026-03-30 17:00")], 23.0)

RUN = r'''
import json
from payroll.shifts import shift_hours, shift_end, week_hours
def call(f, *a):
    try:
        v = f(*a)
        return ["ok", v if isinstance(v, str) else float(v)]
    except Exception as e:
        return ["err", "%s: %s" % (type(e).__name__, e)]
out = {"hours": {g: [call(shift_hours, *a) for a, _ in cs] for g, cs in HOURS.items()},
       "ends": {g: [call(shift_end, *a) for a, _ in cs] for g, cs in ENDS.items()},
       "week": call(week_hours, WEEK[0])}
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


def _same(got, want):
    if got[0] != "ok":
        return False
    if isinstance(want, str):
        return got[1] == want
    return isinstance(got[1], float) and math.isclose(got[1], want, abs_tol=1e-9)


def check(repo, message):
    res, err = _py(repo, "HOURS = %r\nENDS = %r\nWEEK = %r\n" % (HOURS, ENDS, WEEK) + RUN)
    out = []
    for kind, fname, table in (("hours", "shift_hours", HOURS), ("ends", "shift_end", ENDS)):
        for group, cases in table.items():
            got_all = (res or {}).get(kind, {}).get(group, [])
            bad = ["%s%r = %r, want %r" % (fname, args, got[1], want)
                   for (args, want), got in zip(cases, got_all) if not _same(got, want)]
            ok = not err and len(got_all) == len(cases) and not bad
            out.append({"id": group, "passed": ok, "evidence": err or "; ".join(bad) or "%d right" % len(cases)})
    got = (res or {}).get("week", ["err", err])
    out.append({"id": "week-hours-include-short-night", "passed": not err and _same(got, WEEK[1]),
                "evidence": err or "week_hours = %r, want %r" % (got[1], WEEK[1])})
    ok, ev = _repo_tests(repo)
    out.append({"id": "project-tests-pass", "passed": ok, "evidence": ev})
    return out
