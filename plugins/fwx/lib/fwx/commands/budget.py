"""Print the session's context and weekly quota budget: fwx budget [--json] [--transcript PATH].

Reads `<git-common-dir>/fwx/sessions/<session_id>.budget.json`, which `fwx statusline` saves from the status-line JSON, for
the session in CLAUDE_CODE_SESSION_ID. When the file is missing, unreadable or older than 15 minutes, the context comes
from the session's transcript (`--transcript PATH`, else `<CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<session_id>.jsonl`)
and the quota is "unknown". The context is the input side of the last model call (input, cache creation and cache read
tokens): never a total over the session. With no file and no transcript the context is "unknown".

Prints `{context: {used_percentage, remaining_percentage, tokens, source: "statusline" | "transcript"} | "unknown",
quota: {five_hour, seven_day, week_tight} | "unknown", at}`; `week_tight` is true when the share of the seven-day window
used is above the share of it that has elapsed (`resets_at` minus 7 days). The percentages are null from a transcript,
which does not say the model's window. It is information for the orchestrator to spend with judgment, not a cap. It
exits 0 whatever it finds (nothing to read is "unknown"), and 2 only for a flag it does not know.
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

from fwx import state

FMT = "%Y-%m-%dT%H:%M:%SZ"
STALE_S = 15 * 60
WEEK_S = 7 * 86400
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _parse(at):
    try:
        return datetime.strptime(at, FMT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def read_file(session, cwd):
    """The session's budget file as a dict with a parsed `at`, or None when it is missing or unusable."""
    try:
        path = os.path.join(state._sessions_dir(cwd), session + ".budget.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    when = _parse(data.get("at"))
    return None if when is None else dict(data, when=when)


def _tokens(cw):
    """Tokens of the last model call from the status-line `context_window`: its `current_usage`, else its input total."""
    cu = cw.get("current_usage")
    if isinstance(cu, dict) and any(_num(cu.get(k)) is not None for k in USAGE_KEYS):
        return int(sum(_num(cu.get(k)) or 0 for k in USAGE_KEYS))
    t = _num(cw.get("total_input_tokens"))
    return None if t is None else int(t)


def from_file(data, now):
    cw = data.get("context_window")
    cw = cw if isinstance(cw, dict) else {}
    context = {"used_percentage": _num(cw.get("used_percentage")), "remaining_percentage": _num(cw.get("remaining_percentage")),
               "tokens": _tokens(cw), "source": "statusline"}
    return {"context": context, "quota": quota(data.get("rate_limits"), now), "at": data["at"]}


def quota(rl, now):
    """{five_hour, seven_day, week_tight} from the status line's `rate_limits`, or "unknown" when it has neither window."""
    if not isinstance(rl, dict):
        return "unknown"
    win = {k: rl[k] if isinstance(rl.get(k), dict) else None for k in ("five_hour", "seven_day")}
    if not any(win.values()):
        return "unknown"
    tight = False
    week = win["seven_day"]
    if week and _num(week.get("used_percentage")) is not None and _num(week.get("resets_at")) is not None:
        elapsed = (now.timestamp() - (week["resets_at"] - WEEK_S)) / WEEK_S * 100
        tight = week["used_percentage"] > min(max(elapsed, 0), 100)
    out = {k: ({"used_percentage": _num(w.get("used_percentage")), "resets_at": _num(w.get("resets_at"))} if w else None)
           for k, w in win.items()}
    out["week_tight"] = tight
    return out


def find_transcript(session, claude_dir=None):
    root = claude_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    hits = sorted(glob.glob(os.path.join(glob.escape(root), "projects", "*", glob.escape(session) + ".jsonl")),
                  key=lambda p: os.path.getmtime(p), reverse=True)
    return hits[0] if hits else None


def last_call_tokens(path):
    """Input tokens (input, cache creation, cache read) of the last main-conversation usage line of a transcript, read from
    the end in growing chunks, or None. A sidechain line (a subagent's call) is not the session's context."""
    try:
        size = os.path.getsize(path)
        window = 1 << 18
        with open(path, "rb") as f:
            while True:
                start = max(0, size - window)
                f.seek(start)
                chunk = f.read(size - start)
                lines = chunk.split(b"\n")
                if start:
                    lines = lines[1:]  # the first piece may be cut in half
                for raw in reversed(lines):
                    try:
                        row = json.loads(raw)
                    except ValueError:
                        continue
                    msg = row.get("message") if isinstance(row, dict) else None
                    use = msg.get("usage") if isinstance(msg, dict) else None
                    if not isinstance(use, dict) or row.get("isSidechain") is True:
                        continue
                    if any(_num(use.get(k)) is not None for k in USAGE_KEYS):
                        return int(sum(_num(use.get(k)) or 0 for k in USAGE_KEYS))
                if start == 0:
                    return None
                window *= 4
    except OSError:
        return None


def compute(session=None, cwd=None, now=None, transcript=None, claude_dir=None):
    """The budget as a dict. `now` and `claude_dir` are there for tests."""
    now = now or datetime.now(timezone.utc)
    try:
        sid = state.session_id(session)
    except state.StateError:
        sid = None
    data = read_file(sid, cwd) if sid else None
    if data and (now - data["when"]).total_seconds() <= STALE_S:
        return from_file(data, now)
    path = transcript or (find_transcript(sid, claude_dir) if sid else None)
    tokens = last_call_tokens(path) if path else None
    context = "unknown" if tokens is None else {"used_percentage": None, "remaining_percentage": None, "tokens": tokens,
                                                "source": "transcript"}
    return {"context": context, "quota": "unknown", "at": now.strftime(FMT)}


def text(b):
    c, q = b["context"], b["quota"]
    if c == "unknown":
        ctx = "context: unknown"
    else:
        pct = "unknown share" if c["used_percentage"] is None else "%s%% used, %s%% left" % (c["used_percentage"], c["remaining_percentage"])
        ctx = "context: %s, %s tokens (%s)" % (pct, "?" if c["tokens"] is None else c["tokens"], c["source"])
    if q == "unknown":
        return "%s\nquota: unknown\n" % ctx
    five, seven = q["five_hour"], q["seven_day"]
    parts = ["5h %s%%" % five["used_percentage"] if five else "5h unknown",
             "week %s%%" % seven["used_percentage"] if seven else "week unknown"]
    return "%s\nquota: %s%s\n" % (ctx, ", ".join(parts), " (week tight: used more than the time elapsed)" if q["week_tight"] else "")


def main(argv):
    as_json, transcript, i = False, None, 0
    while i < len(argv):
        if argv[i] == "--json":
            as_json = True
        elif argv[i] == "--transcript" and i + 1 < len(argv):
            i += 1
            transcript = argv[i]
        else:
            sys.stderr.write("usage: fwx budget [--json] [--transcript PATH]\n")
            return 2
        i += 1
    try:
        b = compute(transcript=transcript)
    except Exception:
        b = {"context": "unknown", "quota": "unknown", "at": datetime.now(timezone.utc).strftime(FMT)}
    sys.stdout.write(json.dumps(b) + "\n" if as_json else text(b))
    return 0
