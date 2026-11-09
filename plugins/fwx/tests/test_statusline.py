#!/usr/bin/env python3
"""`fwx statusline`: the status-bar line (the subproject of the session, only when the project has subprojects) and the
budget file it saves for `fwx budget` (`<git-common-dir>/fwx/sessions/<session_id>.budget.json`).

Every check goes through `bin/fwx statusline` with the Claude Code JSON on stdin. The JSON shape is the one in
code.claude.com/docs/en/statusline (`session_id`, `cwd`, `workspace.current_dir`, `context_window`, `rate_limits`).
The timing check runs only with FWX_TIMING=1 (the median depends on the machine's load, so the runner and the gate
do not); without it it prints `timing: SKIP (set FWX_TIMING=1)`.

Seen red before the command existed (bin/fwx has no `statusline`; 50 checks, 40 failed, first lines shown):
  FAIL: no subprojects, session bound to the root: exit code: got 2, want 0
  FAIL: .fwx/subprojects/web, session bound to web: prints 'web': got '', want 'web'
  FAIL: budget: the file is written: budget file missing: <repo>/.git/fwx/sessions/s-budget.budget.json
Green with FWX_TIMING=1: 59 checks, `timing: median 34.2 ms of 10 (min 33.3, max 36.3)`.

Controls, each seen red on a copy of the repo with statusline.py changed in one place (first FAIL lines shown):
  - prints the subproject line always (the `has_subprojects` gate removed):
      FAIL: no subprojects, session bound to the root: prints nothing: got 'root', want ''
  - never prints (`if text:` made `if False:`; 7 failed):
      FAIL: .fwx/subprojects/web, session bound to web: prints 'web': got '', want 'web'
      FAIL: subprojects, session bound to the root: prints 'root': got '', want 'root'
  - prints but does not save the budget:
      FAIL: budget: the file is written: budget file missing: <repo>/.git/fwx/sessions/s-budget.budget.json
      FAIL: no rate_limits: the file is written: budget file missing: <repo>/.git/fwx/sessions/s-norl.budget.json
      FAIL: no subprojects: the budget is still saved
  - requires `rate_limits` (`data["rate_limits"]`; the command swallows the KeyError, so the test sees the missing file,
    not the trace):
      FAIL: no rate_limits: the file is written: budget file missing: <repo>/.git/fwx/sessions/s-norl.budget.json
  - no `except Exception` (errors reach the user):
      FAIL: cwd outside a git repository: exit code: got 1, want 0
      FAIL: cwd outside a git repository: no traceback or stderr: stderr: '... raise ConfigError("not in a git repos...
      FAIL: a path-like session id: exit code: got 1, want 0
      FAIL: sessions folder without write permission: exit code: got 1, want 0
  - `time.sleep(0.15)` at the top of main, FWX_TIMING=1:
      timing: median 196.6 ms of 10 (min 195.3, max 209.4)
      FAIL: timing: median of 10 runs under 100 ms: median 196.6 ms (writes budget.json each run)
      FAIL: timing: read-only sessions folder under 100 ms: 197.2 ms
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()


def run(cwd, payload, env=None, raw=None):
    t = time.perf_counter()
    r = helpers.fwx(cwd, "statusline", input=raw if raw is not None else json.dumps(payload), env=env)
    return r, (time.perf_counter() - t) * 1000


def silent(label, r, want_out=""):
    """exit 0, no traceback, nothing on stderr, and `want_out` on stdout."""
    s.eq("%s: exit code" % label, r.returncode, 0)
    s.ok("%s: no traceback or stderr" % label, r.stderr == "", "stderr: %r" % r.stderr[-300:])
    s.eq("%s: prints %s" % (label, repr(want_out) if want_out else "nothing"), r.stdout.strip(), want_out)


def session_file(repo, sid, suffix=".json"):
    return os.path.join(repo, ".git", "fwx", "sessions", sid + suffix)


def bind(repo, sid, subproject):
    d = os.path.join(repo, ".git", "fwx", "sessions")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, sid + ".json"), "w") as f:
        json.dump({"subproject": subproject, "phase_dir": None}, f)


# ---- the printed line, both directions ----------------------------------------------------------------------------
plain = helpers.toy_repo()
bind(plain, "s-plain", None)
r, _ = run(plain, {"session_id": "s-plain", "cwd": plain})
silent("no subprojects, session bound to the root", r)

multi = helpers.toy_repo({"README": "toy\n", ".fwx/subprojects/web/.keep": "", ".fwx/subprojects/api/.keep": ""})
bind(multi, "s-web", "web")
r, _ = run(multi, {"session_id": "s-web", "workspace": {"current_dir": multi}})
silent(".fwx/subprojects/web, session bound to web", r, "web")
bind(multi, "s-root", None)
r, _ = run(multi, {"session_id": "s-root", "cwd": multi})
silent("subprojects, session bound to the root", r, "root")
r, _ = run(multi, {"session_id": "s-unbound", "cwd": multi})
silent("subprojects, session bound to nothing", r)
os.makedirs(os.path.join(multi, "sub", "deep"))
r, _ = run(multi, {"session_id": "s-web", "cwd": os.path.join(multi, "sub", "deep")})
silent("from a subfolder", r, "web")
wt = helpers.add_worktree(multi, "feat")
r, _ = run(wt, {"session_id": "s-web", "cwd": wt})
silent("from a linked worktree: the session file is the main checkout's", r, "web")
r = helpers.fwx(multi, "statusline", input="", env={"CLAUDE_CODE_SESSION_ID": "s-web"})
silent("no stdin: the environment's session and the current folder", r, "web")

# ---- broken input, no repository ----------------------------------------------------------------------------------
r, _ = run(multi, None, raw="{not json")
silent("broken JSON", r)
r, _ = run(multi, None, raw="[1, 2]")
silent("JSON that is not an object", r)
nogit = helpers.mkdtemp("fwx-nogit-")
r, _ = run(nogit, {"session_id": "s-x", "cwd": nogit, "context_window": {"used_percentage": 5}})
silent("cwd outside a git repository", r)
r, _ = run(multi, {"session_id": "../evil", "cwd": multi, "context_window": {}})
silent("a path-like session id", r)
s.ok("a path-like session id writes nothing outside the sessions folder",
     not os.path.exists(os.path.join(multi, ".git", "fwx", "evil.budget.json")))

# ---- the budget file ----------------------------------------------------------------------------------------------
cw = {"total_input_tokens": 15500, "total_output_tokens": 1200, "context_window_size": 200000, "used_percentage": 8,
      "remaining_percentage": 92, "current_usage": {"input_tokens": 8500, "output_tokens": 1200,
                                                    "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 2000}}
rl = {"five_hour": {"used_percentage": 23.5, "resets_at": 1738425600},
      "seven_day": {"used_percentage": 41.2, "resets_at": 1738857600}}
bind(multi, "s-budget", "web")
r, _ = run(multi, {"session_id": "s-budget", "cwd": multi, "context_window": cw, "rate_limits": rl})
silent("budget: output is the same as without a budget", r, "web")
p = session_file(multi, "s-budget", ".budget.json")
if s.ok("budget: the file is written", os.path.exists(p), "budget file missing: %s" % p):
    with open(p) as f:
        got = json.load(f)
    s.eq("budget: keys", sorted(got), ["at", "context_window", "rate_limits"])
    s.eq("budget: context_window equals the input", got["context_window"], cw)
    s.eq("budget: rate_limits equals the input", got["rate_limits"], rl)
    s.ok("budget: at is a UTC time of now", abs(time.time() - time.mktime(time.strptime(got["at"], "%Y-%m-%dT%H:%M:%SZ")) + time.timezone) < 120, got["at"])
    s.ok("budget: no temp file left", [n for n in os.listdir(os.path.dirname(p)) if n.endswith(".tmp")] == [])

r, _ = run(multi, {"session_id": "s-norl", "cwd": multi, "context_window": cw})
silent("no rate_limits", r)
p = session_file(multi, "s-norl", ".budget.json")
if s.ok("no rate_limits: the file is written", os.path.exists(p), "budget file missing: %s" % p):
    with open(p) as f:
        got = json.load(f)
    s.ok("no rate_limits: rate_limits is null", "rate_limits" in got and got["rate_limits"] is None, repr(got))
    s.eq("no rate_limits: context_window kept", got["context_window"], cw)

r, _ = run(plain, {"session_id": "s-nosub", "cwd": plain, "context_window": cw, "rate_limits": rl})
silent("no subprojects: still prints nothing", r)
s.ok("no subprojects: the budget is still saved", os.path.exists(session_file(plain, "s-nosub", ".budget.json")))

# a read-only sessions folder: exit 0, no trace (root ignores the mode, so the check is armed only for others)
ro = helpers.toy_repo({"README": "toy\n", ".fwx/subprojects/web/.keep": ""})
bind(ro, "s-ro", "web")
sessions = os.path.dirname(session_file(ro, "s-ro"))
os.chmod(sessions, 0o500)
try:
    if os.access(sessions, os.W_OK):
        print("read-only sessions folder: SKIP (this user can write there anyway)")
    else:
        r, ms_ro = run(ro, {"session_id": "s-ro", "cwd": ro, "context_window": cw, "rate_limits": rl})
        silent("sessions folder without write permission", r, "web")
        s.ok("sessions folder without write permission: no budget file", not os.path.exists(session_file(ro, "s-ro", ".budget.json")))
finally:
    os.chmod(sessions, 0o700)

# ---- timing (M13): median of 10 runs under 100 ms, the budget write included --------------------------------------
if os.environ.get("FWX_TIMING") == "1":
    times = []
    for i in range(10):
        r, ms = run(multi, {"session_id": "s-web", "cwd": multi, "context_window": cw, "rate_limits": rl})
        times.append(ms)
    med = statistics.median(times)
    print("timing: median %.1f ms of 10 (min %.1f, max %.1f)" % (med, min(times), max(times)))
    s.ok("timing: median of 10 runs under 100 ms", med < 100, "median %.1f ms (writes budget.json each run)" % med)
    sessions = os.path.dirname(session_file(ro, "s-ro"))
    os.chmod(sessions, 0o500)
    try:
        if not os.access(sessions, os.W_OK):
            _, ms = run(ro, {"session_id": "s-ro", "cwd": ro, "context_window": cw, "rate_limits": rl})
            s.ok("timing: read-only sessions folder under 100 ms", ms < 100, "%.1f ms" % ms)
    finally:
        os.chmod(sessions, 0o700)
else:
    print("timing: SKIP (set FWX_TIMING=1)")

s.done()
