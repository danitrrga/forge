"""Oracle for debug-misleading-error-02: 'invalid date format' for lines whose date is fine.

parse_line() wraps the whole line in `except Exception` and always blames the date, so the real failure,
parse_duration() crashing on `15m` or `2h` (an optional regex group is None), is reported as a bad date.
Fixing the regex alone leaves every other bad duration or malformed line still blamed on the date. The
oracle checks the durations the docstring allows, that bad durations, dates and field counts each raise a
ValueError (ParseError is one) whose message names the right culprit and never the date when the date is
fine, and that the importer still reports bad lines by number and keeps going (it catches ParseError, so a
fix that lets raw exceptions escape parse_line fails there)."""
import json
import os
import subprocess
import sys
import tempfile

CALENDAR = """# start | title | duration
2026-03-09 09:00 | Planning | 1h30m
2026-03-09 14:00 | Standup | 15m
2026-03-10 13:00 | Offsite prep | 2h
2026-03-10 15:00 | Demo | soon
2026-03-11 09:30 | Retro | 0h45m
2026-03-31 25:00 | Late call | 30m
2026-03-11 16:00 | 1:1 with Ben | 90m
"""

PROBE = r'''
import json, re, sys
from datetime import timedelta
repo, calendar = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo)
from eventlog.parser import parse_line
from eventlog.importer import import_file
BLAMES_DATE = re.compile(r"invalid date|date format|bad date", re.I)
res = {"durations": [], "bad_duration": [], "bad_date": None, "malformed": []}
for text, minutes in [("45m", 45), ("2h", 120), ("1h30m", 90), ("90m", 90), ("0h45m", 45), ("1h0m", 60)]:
    try:
        got = parse_line("2026-03-09 14:00 | Standup | %s" % text).duration
        if got != timedelta(minutes=minutes):
            res["durations"].append("%s -> %s, want %d min" % (text, got, minutes))
    except Exception as e:
        res["durations"].append("%s -> %s: %s" % (text, type(e).__name__, e))
for text in ["soon", "", "m", "-5m"]:
    line = "2026-03-09 14:00 | Standup | %s" % text
    try:
        ev = parse_line(line)
        res["bad_duration"].append("%r accepted as %s" % (text, ev.duration))
    except ValueError as e:  # ParseError is a ValueError; whether the importer copes is checked on its own
        if BLAMES_DATE.search(str(e)):
            res["bad_duration"].append("%r -> %r blames the date" % (text, str(e)))
        elif text.strip() and text not in str(e):
            res["bad_duration"].append("%r -> %r does not show the bad value" % (text, str(e)))
    except Exception as e:
        res["bad_duration"].append("%r -> %s: %s" % (text, type(e).__name__, e))
try:
    parse_line("2026-03-32 09:00 | Planning | 1h30m")
    res["bad_date"] = "accepted"
except ValueError as e:
    res["bad_date"] = "ok" if "2026-03-32 09:00" in str(e) else "message %r does not show the bad date" % str(e)
except Exception as e:
    res["bad_date"] = "%s: %s" % (type(e).__name__, e)
for line in ["2026-03-09 09:00 | Planning", "2026-03-09 09:00 | Planning | 1h | extra"]:
    try:
        parse_line(line)
        res["malformed"].append("%r accepted" % line)
    except ValueError as e:
        if BLAMES_DATE.search(str(e)):
            res["malformed"].append("%r -> %r blames the date" % (line, str(e)))
    except Exception as e:
        res["malformed"].append("%r -> %s: %s" % (line, type(e).__name__, e))
try:
    events, errors = import_file(calendar)
    res["import"] = {"events": len(events), "minutes": sum(e.duration.total_seconds() for e in events) / 60,
                     "errors": errors}
except Exception as e:
    res["import"] = "%s: %s" % (type(e).__name__, e)
print(json.dumps(res))
'''


def check(repo, message):
    repo = os.path.abspath(repo)
    with tempfile.TemporaryDirectory() as tmp:
        cal = os.path.join(tmp, "calendar.txt")
        open(cal, "w").write(CALENDAR)
        r = subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, repo, cal], capture_output=True, text=True,
                           timeout=30, cwd=repo)
    ids = ("durations-parse", "bad-duration-named-not-date", "bad-date-named", "malformed-line-not-blamed-on-date",
           "importer-reports-and-continues")
    lines = r.stdout.strip().splitlines()
    if r.returncode or not lines:
        err = (r.stderr.strip().splitlines() or ["no output"])[-1]
        return [{"id": i, "passed": False, "evidence": "probe failed: " + err} for i in ids]
    res = json.loads(lines[-1])
    imp = res["import"]
    if isinstance(imp, dict):
        errs = imp["errors"]
        imp_ok = (imp["events"] == 5 and imp["minutes"] == 90 + 15 + 120 + 45 + 90 and len(errs) == 2
                  and errs[0].startswith("line 5") and "soon" in errs[0] and errs[1].startswith("line 7"))
        imp_ev = "%d events, %g minutes, errors %r (want 5 events, 360 minutes, line 5 naming 'soon', line 7)" % (
            imp["events"], imp["minutes"], errs)
    else:
        imp_ok, imp_ev = False, "import_file raised " + imp
    return [
        {"id": ids[0], "passed": not res["durations"], "evidence": "; ".join(res["durations"]) or "45m 2h 1h30m 90m 0h45m 1h0m all parse"},
        {"id": ids[1], "passed": not res["bad_duration"],
         "evidence": "; ".join(res["bad_duration"]) or "soon, '', m, -5m each raise a ValueError/ParseError naming the value, not the date"},
        {"id": ids[2], "passed": res["bad_date"] == "ok", "evidence": "2026-03-32 09:00: %s" % res["bad_date"]},
        {"id": ids[3], "passed": not res["malformed"],
         "evidence": "; ".join(res["malformed"]) or "two- and four-field lines raise an error that does not blame the date"},
        {"id": ids[4], "passed": imp_ok, "evidence": imp_ev},
    ]
