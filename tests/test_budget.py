#!/usr/bin/env python3
"""`fwx budget`: the session's context and weekly quota, from the file `fwx statusline` saves, or from the transcript.

The decision checks call `budget.compute(...)` with an injected clock and a toy transcript; the wiring checks go through
`bin/fwx budget` and a `bin/fwx statusline` run that writes the file the command reads.

Seen red before the command existed (lib/fwx/commands/budget.py absent; the test stops at the import):
  FAIL: cannot import fwx.commands.budget: cannot import name 'budget' from 'fwx.commands' (lib/fwx/commands/__init__.py)

Controls, each seen red on a copy of the repo with budget.py changed in one place (41 checks each, first FAIL lines shown):
  - serves the file whatever its age (the 15-minute test removed; 5 failed):
      FAIL: file 16 minutes old: stale budget served: stale budget served: source 'statusline'
      FAIL: file 16 minutes old: tokens: got 68000, want 4500
  - `week_tight` always false:
      FAIL: 80 percent of the week used, 40 percent elapsed: week_tight: week_tight False at 80 of 40
  - `week_tight` always true:
      FAIL: 30 percent of the week used, 40 percent elapsed: week_tight false: week_tight True at 30 of 40
  - never falls back to the transcript (11 failed):
      FAIL: no file, a transcript: source: got 'unknown', want 'transcript'
      FAIL: fwx budget --transcript PATH: got 'unknown', want 4500
  - reads the first usage line of the transcript, not the last:
      FAIL: transcript: tokens are the last call's input, cache included (a later sidechain line is not it): got 5100, want 4500
  - counts a sidechain (subagent) line as the session's:
      FAIL: transcript: tokens are the last call's input, cache included (a later sidechain line is not it): got 4600, want 4500
  - reads only the last 256 KiB of the transcript (no growing window):
      FAIL: a last usage line far from the end of a large file is found: got 'unknown', want 21
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx.commands import budget  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.commands.budget: %s" % e)
    sys.exit(1)

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
FMT = "%Y-%m-%dT%H:%M:%SZ"
repo = helpers.toy_repo()
sessions = os.path.join(repo, ".git", "fwx", "sessions")
os.makedirs(sessions)


def stamp(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).strftime(FMT)


def put(sid, at, cw, rl):
    with open(os.path.join(sessions, sid + ".budget.json"), "w") as f:
        json.dump({"context_window": cw, "rate_limits": rl, "at": at}, f)


def ctx(r, key):
    """A field of the context, or the word `unknown` when there is no context (a check then fails instead of crashing)."""
    return r["context"].get(key) if isinstance(r["context"], dict) else r["context"]


def week(used, elapsed_pct):
    """A seven_day window that has run `elapsed_pct` percent of its 7 days at NOW."""
    resets = NOW.timestamp() + (100 - elapsed_pct) / 100 * 7 * 86400
    return {"five_hour": {"used_percentage": 10, "resets_at": NOW.timestamp() + 3600},
            "seven_day": {"used_percentage": used, "resets_at": resets}}


def usage_line(inp, create, read, out=50, **extra):
    row = {"type": "assistant", "message": {"role": "assistant", "usage": {
        "input_tokens": inp, "cache_creation_input_tokens": create, "cache_read_input_tokens": read, "output_tokens": out}}}
    row.update(extra)
    return json.dumps(row)


def transcript(name, lines):
    return helpers.write(helpers.mkdtemp("fwx-tr-"), name, "\n".join(lines) + "\n")


CW = {"context_window_size": 200000, "used_percentage": 34, "remaining_percentage": 66,
      "current_usage": {"input_tokens": 8000, "output_tokens": 100, "cache_creation_input_tokens": 20000,
                        "cache_read_input_tokens": 40000}}

# ---- the file, recent ---------------------------------------------------------------------------------------------
put("s-new", stamp(5), CW, week(41.2, 40))
r = budget.compute(session="s-new", cwd=repo, now=NOW)
s.eq("file 5 minutes old: source", ctx(r, "source"), "statusline")
s.eq("file 5 minutes old: used_percentage", r["context"]["used_percentage"], 34)
s.eq("file 5 minutes old: remaining_percentage", r["context"]["remaining_percentage"], 66)
s.eq("file 5 minutes old: tokens are the last call's input, cache included", ctx(r, "tokens"), 68000)
s.eq("file 5 minutes old: at is the file's", r["at"], stamp(5))
s.eq("file 5 minutes old: five_hour", r["quota"]["five_hour"]["used_percentage"], 10)
s.eq("file 5 minutes old: seven_day", r["quota"]["seven_day"]["used_percentage"], 41.2)
s.eq("file exactly 15 minutes old is still recent", ctx(budget.compute(session="s-new", cwd=repo, now=NOW + timedelta(minutes=10)), "source"), "statusline")

# ---- week_tight, both directions ----------------------------------------------------------------------------------
put("s-tight", stamp(1), CW, week(80, 40))
r = budget.compute(session="s-tight", cwd=repo, now=NOW)
s.ok("80 percent of the week used, 40 percent elapsed: week_tight", r["quota"]["week_tight"] is True,
     "week_tight %r at 80 of 40" % r["quota"]["week_tight"])
put("s-calm", stamp(1), CW, week(30, 40))
r = budget.compute(session="s-calm", cwd=repo, now=NOW)
s.ok("30 percent of the week used, 40 percent elapsed: week_tight false", r["quota"]["week_tight"] is False,
     "week_tight %r at 30 of 40" % r["quota"]["week_tight"])
put("s-norl", stamp(1), CW, None)
r = budget.compute(session="s-norl", cwd=repo, now=NOW)
s.eq("file without rate_limits: quota", r["quota"], "unknown")
s.eq("file without rate_limits: the context is still the file's", ctx(r, "source"), "statusline")

# ---- the file, stale or missing: the transcript -------------------------------------------------------------------
tr = transcript("t.jsonl", [
    usage_line(100, 2000, 3000),
    '{"type": "user", "message": {"content": "hi"}}',
    usage_line(10, 1490, 3000),
    usage_line(500, 1000, 3100, isSidechain=True),
    '{"type": "system", "subtype": "x"}',
    "not json at all",
])
put("s-old", stamp(16), CW, week(80, 40))
r = budget.compute(session="s-old", cwd=repo, now=NOW, transcript=tr)
s.ok("file 16 minutes old: stale budget served", r["context"] != "unknown" and ctx(r, "source") != "statusline",
     "stale budget served: source %r" % (r["context"].get("source") if isinstance(r["context"], dict) else r["context"]))
s.eq("file 16 minutes old: source", ctx(r, "source"), "transcript")
s.eq("file 16 minutes old: tokens", ctx(r, "tokens"), 4500)
s.eq("file 16 minutes old: quota unknown", r["quota"], "unknown")
s.eq("file 16 minutes old: percentages unknown", (ctx(r, "used_percentage"), ctx(r, "remaining_percentage")), (None, None))
r = budget.compute(session="s-missing", cwd=repo, now=NOW, transcript=tr)
s.eq("no file, a transcript: source", ctx(r, "source"), "transcript")
s.eq("transcript: tokens are the last call's input, cache included (a later sidechain line is not it)", ctx(r, "tokens"), 4500)
s.eq("no file, a transcript: quota unknown", r["quota"], "unknown")
s.eq("no file, a transcript: at is now", r["at"], NOW.strftime(FMT))

# the transcript found by session id under a config dir, as Claude Code lays it out
cfg = helpers.mkdtemp("fwx-claude-")
helpers.write(cfg, "projects/-some-project/s-find.jsonl", usage_line(1, 2, 3) + "\n")
r = budget.compute(session="s-find", cwd=repo, now=NOW, claude_dir=cfg)
s.eq("transcript found by session id under projects/*/", (ctx(r, "source"), ctx(r, "tokens")), ("transcript", 6))
big = transcript("big.jsonl", [usage_line(7, 7, 7)] + ['{"type": "user", "message": {"content": "%s"}}' % ("x" * 4000)] * 400)
s.eq("a last usage line far from the end of a large file is found", ctx(budget.compute(session="s-m", cwd=repo, now=NOW, transcript=big), "tokens"), 21)

# ---- nothing to read ----------------------------------------------------------------------------------------------
r = budget.compute(session="s-missing", cwd=repo, now=NOW, claude_dir=cfg)
s.eq("no file and no transcript: context unknown", r["context"], "unknown")
s.eq("no file and no transcript: quota unknown", r["quota"], "unknown")
empty = transcript("e.jsonl", ['{"type": "user", "message": {"content": "hi"}}'])
s.eq("a transcript with no usage line: context unknown", budget.compute(session="s-missing", cwd=repo, now=NOW, transcript=empty)["context"], "unknown")
nogit = helpers.mkdtemp("fwx-nogit-")
s.eq("outside a git repository: context unknown, no error", budget.compute(session="s-x", cwd=nogit, now=NOW, claude_dir=cfg)["context"], "unknown")
helpers.write(sessions, "s-bad.budget.json", "{broken")
s.eq("a corrupt file counts as missing", ctx(budget.compute(session="s-bad", cwd=repo, now=NOW, transcript=tr), "source"), "transcript")
helpers.write(sessions, "s-badat.budget.json", json.dumps({"context_window": CW, "rate_limits": None, "at": "yesterday"}))
s.eq("an unreadable time counts as stale", ctx(budget.compute(session="s-badat", cwd=repo, now=NOW, transcript=tr), "source"), "transcript")

# ---- through bin/fwx: statusline writes, budget reads -------------------------------------------------------------
env = {"CLAUDE_CODE_SESSION_ID": "s-e2e", "CLAUDE_CONFIG_DIR": cfg}
real = {"session_id": "s-e2e", "cwd": repo, "context_window": CW,
        "rate_limits": {"seven_day": {"used_percentage": 90, "resets_at": time.time() + 6 * 86400}}}
w = helpers.fwx(repo, "statusline", input=json.dumps(real))
s.eq("statusline run: exit code", w.returncode, 0)
r = helpers.fwx(repo, "budget", "--json", env=env)
s.eq("fwx budget --json: exit code", r.returncode, 0)
try:
    out = json.loads(r.stdout)
except ValueError:
    out = {}
    s.ok("fwx budget --json: prints JSON", False, r.stdout[:200] + r.stderr[-200:])
s.eq("fwx budget --json: the context is the statusline's", (out.get("context") or {}).get("source"), "statusline")
s.eq("fwx budget --json: tokens", (out.get("context") or {}).get("tokens"), 68000)
s.ok("fwx budget --json: week_tight, 90 percent used and 14 percent elapsed", (out.get("quota") or {}).get("week_tight") is True, r.stdout[:300])
r = helpers.fwx(repo, "budget", env=env)
s.eq("fwx budget (text): exit code", r.returncode, 0)
s.ok("fwx budget (text): names the context and the week", "context" in r.stdout and "week" in r.stdout and "tight" in r.stdout, r.stdout)
r = helpers.fwx(repo, "budget", "--json", env={"CLAUDE_CODE_SESSION_ID": "s-none", "CLAUDE_CONFIG_DIR": cfg})
s.eq("fwx budget, nothing to read: exit code", r.returncode, 0)
s.eq("fwx budget, nothing to read: context and quota unknown", (json.loads(r.stdout)["context"], json.loads(r.stdout)["quota"]), ("unknown", "unknown"))
r = helpers.fwx(nogit, "budget", "--json", env={"CLAUDE_CODE_SESSION_ID": "s-none", "CLAUDE_CONFIG_DIR": cfg})
s.ok("fwx budget outside a repository: exit 0, no traceback", r.returncode == 0 and "Traceback" not in r.stderr, r.stderr[-200:])
r = helpers.fwx(repo, "budget", "--json", env={"CLAUDE_CONFIG_DIR": cfg})
s.ok("fwx budget without a session id: exit 0, no traceback", r.returncode == 0 and "Traceback" not in r.stderr, r.stderr[-200:])
r = helpers.fwx(repo, "budget", "--json", "--transcript", tr, env={"CLAUDE_CODE_SESSION_ID": "s-none"})
s.eq("fwx budget --transcript PATH", ctx(json.loads(r.stdout), "tokens"), 4500)

s.done()
