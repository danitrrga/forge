"""Print the status-bar line: the session's subproject, only when the project has subprojects.

Reads the JSON Claude Code gives a status line on stdin (`session_id`, `workspace.current_dir` or `cwd`); with no stdin it takes
the session from CLAUDE_CODE_SESSION_ID and the current folder. Prints the subproject the session is bound to, or `root` when it
is bound to the root, and only when `subprojects/` has entries; otherwise nothing. It writes nothing. It always exits 0, never
prints a traceback and has to finish in under 100 ms: a broken input or a folder outside a repository is an empty line, not an error.

Imports only the standard library and fwx.state (itself standard library and config).
"""
import json
import os
import sys

from fwx import state


def _read_input():
    """The status-line JSON as a dict (empty when there is no stdin), or None when it is broken."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        text = sys.stdin.read()
    except (OSError, ValueError):
        return None
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _cwd(data):
    ws = data.get("workspace")
    cur = ws.get("current_dir") if isinstance(ws, dict) else None
    for c in (cur, data.get("cwd")):
        if isinstance(c, str) and c:
            return c
    return os.getcwd()


def line(cwd, sid):
    """The subproject text of the bar: "" without subprojects or without a bound session."""
    if not state.has_subprojects(state.plan_root(cwd)):
        return ""
    bound = state.read_session(cwd, sid)
    if bound is None:
        return ""
    return bound["subproject"] or "root"


def main(argv):
    try:
        data = _read_input()
        if data is None:
            return 0
        cwd = _cwd(data)
        given = data.get("session_id")
        sid = state.session_id(given if isinstance(given, str) and given else None)
        text = ""
        try:
            text = line(cwd, sid)
        except Exception:
            pass
        if text:
            print(text)
    except Exception:
        pass
    return 0
