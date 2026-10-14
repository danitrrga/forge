#!/usr/bin/env python3
"""omarchy_notify.py -- bridge Claude Code's Notification event to the Omarchy desktop.

WHY. Claude Code's own notification settings (inputNeededNotifEnabled,
agentPushNotifEnabled) push to Anthropic's apps, not to the local desktop. On an
Omarchy machine that means a session waiting for input is invisible unless its
window happens to be on screen. Omarchy ships the other half of the bridge --
`omarchy-notification-send`, whose `--exec` makes a toast clickable -- so this hook
is the missing wire between the two.

WHAT IT DOES. Reads the Notification payload on stdin, then raises an Omarchy toast
titled with the project directory and bodied with Claude's own message. Clicking it
focuses the exact Hyprland window this session runs in: the hook walks its own parent
process chain and matches a pid against `hyprctl clients`, so it finds the right
terminal even with several sessions open at once. When that window is already focused
the toast is suppressed -- there is nothing to tell someone who is looking at it.

FAILURE POLICY. Always exits 0 and never writes to stdout. A notification hook that
can block or annoy is worse than no notification hook, so every branch degrades:
no Hyprland -> a toast with no click action; no omarchy-notification-send -> silence.
"""
import json
import os
import shutil
import subprocess
import sys

GLYPH = "\U000f06a9"  # 󰚩 -- the same mark Omarchy's own agent notifications use
TIMEOUT = 3


def read_payload():
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def ancestor_pids():
    """Every pid from this process up to init.

    The hook is a descendant of the `claude` process, which is itself a descendant of
    the terminal window Hyprland knows about. Which generation carries the window
    varies with how the session was launched, so collect the whole chain and let the
    caller intersect it with the compositor's client list.
    """
    pids, pid = [], os.getpid()
    for _ in range(24):  # bounded: a /proc cycle must never hang a notification
        pids.append(pid)
        try:
            with open("/proc/%d/stat" % pid, "rb") as fh:
                # comm can contain spaces and parens; the ppid is the field after the
                # LAST ')', which is why this splits on rpartition rather than on space.
                fields = fh.read().rpartition(b")")[2].split()
            parent = int(fields[1])
        except (OSError, IndexError, ValueError):
            break
        if parent <= 1 or parent == pid:
            break
        pid = parent
    return pids


def hyprctl_json(*args):
    if not shutil.which("hyprctl"):
        return None
    try:
        out = subprocess.run(
            ["hyprctl", "-j"] + list(args),
            capture_output=True, timeout=TIMEOUT, check=True,
        ).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def session_window():
    """(address, is_focused) for the window this session runs in, or (None, False)."""
    clients = hyprctl_json("clients")
    if not isinstance(clients, list):
        return None, False

    by_pid = {}
    for c in clients:
        if isinstance(c, dict) and isinstance(c.get("pid"), int) and c.get("address"):
            by_pid.setdefault(c["pid"], c["address"])

    address = None
    for pid in ancestor_pids():  # nearest ancestor wins
        if pid in by_pid:
            address = by_pid[pid]
            break
    if address is None:
        return None, False

    active = hyprctl_json("activewindow")
    focused = isinstance(active, dict) and active.get("address") == address
    return address, focused


def main():
    if not shutil.which("omarchy-notification-send"):
        return 0

    payload = read_payload()
    message = (payload.get("message") or "").strip() or "Claude Code needs your attention"
    cwd = payload.get("cwd") or os.getcwd()
    project = os.path.basename(os.path.normpath(cwd)) or cwd

    address, focused = session_window()
    if focused:
        return 0  # the window is already on screen; a toast about it is pure noise

    cmd = [
        "omarchy-notification-send",
        "-u", "critical",   # a waiting session should not expire unseen
        "-g", GLYPH,
        "--app-name", "claude-code",
        project,
        message,
    ]
    if address:
        # --exec consumes the rest of the line as argv and is never re-parsed by a
        # shell, so the address rides as one argument. It must come last.
        cmd += ["--exec", "hyprctl", "dispatch", "focuswindow", "address:%s" % address]

    try:
        subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
