"""Show a page or file to the owner: fwx open FILE|URL [--print|--no-open] [--json].

FILE is made absolute and must exist (exit 2, one line on stderr, when it does not); an http(s):// or file:// URL goes
through as is. The target is handed to the openers of OPENERS in order, and the first that works wins. With none working
nothing is opened by itself (a window must never appear on the owner's desktop without warning): the command prints
`NOT OPENED: <reason>` and, on the next line, the command for this system that the owner pastes (`xdg-open`, `open` or
`start`, by sys.platform). `--print` (or `--no-open`) skips the openers and prints that command alone, for unattended
runs and tests. `--json` prints `{opened, by, target, command}` instead. It exits 0 whatever the openers do.

An opener is a function `(url) -> (ok, reason)` listed in OPENERS as `(name, function)`; a new IDE or system is one new
function and one row, and the core below names none of them. The one that exists is Orca, the IDE's own browser, used
when an `orca` program is on PATH: `orca tab create --url <url> --json` with the worktree inferred from the cwd, and, when
that is not ok, once more with `--worktree active`. Measured on the real program: with `--json` it exits 0 and prints
`{"ok": true, "result": {"browserPageId": ...}}` and the tab loads a `file://` page; a failure carries `"ok": false` and
`"error": {"code", "message"}` (seen: `browser_no_tab`). It has no option for a side pane, so the page is a normal tab.
Not measured: the exit code when Orca is not running, so a non-zero exit and a reply that is not JSON both count as
"not ok".
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

URL = re.compile(r"(https?|file)://", re.I)
TIMEOUT_S = 30
# what the owner pastes, by sys.platform prefix; the last row is the default
SHOW = (("linux", "xdg-open"), ("darwin", "open"), ("win32", 'start ""'), ("", "xdg-open"))


def paste_command(target, platform=None):
    """The command that shows `target` on this system (a path or a URL), quoted for its shell."""
    platform = sys.platform if platform is None else platform
    word = next(w for prefix, w in SHOW if platform.startswith(prefix))
    quoted = '"%s"' % target if platform.startswith("win32") else shlex.quote(target)
    return "%s %s" % (word, quoted)


def _reason(proc):
    """Why an `orca` call was not ok, in one short piece of text."""
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("ok") is False:
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        return ": ".join(str(x) for x in (err.get("code"), err.get("message")) if x) or "ok false"
    if proc.returncode:
        tail = (proc.stderr or "").strip().splitlines()
        return "exit %d%s" % (proc.returncode, ": " + tail[-1] if tail else "")
    return "reply was not an ok JSON"


def orca(url):
    """The Orca browser: `orca tab create --url URL --json`, then once more with `--worktree active`."""
    exe = shutil.which("orca")
    if not exe:
        return False, "orca is not on PATH"
    why = []
    for extra in ([], ["--worktree", "active"]):
        try:
            proc = subprocess.run([exe, "tab", "create", "--url", url] + extra + ["--json"],
                                  capture_output=True, text=True, timeout=TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as e:
            why.append("%s" % e)
            continue
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            data = None
        if proc.returncode == 0 and isinstance(data, dict) and data.get("ok") is True:
            return True, ""
        why.append(_reason(proc))
    return False, "; ".join(dict.fromkeys(why))  # the same reason twice is said once


OPENERS = [("orca", orca)]


def show(target, openers=None, do_open=True, platform=None):
    """Try the openers in order on `target` (an absolute path or a URL). {opened, by, target, command, reason}."""
    openers = OPENERS if openers is None else openers
    url = target if URL.match(target) else Path(target).as_uri()
    res = {"opened": False, "by": None, "target": target, "command": paste_command(target, platform), "reason": ""}
    if not do_open:
        return res
    why = []
    for name, opener in openers:
        ok, reason = opener(url)
        if ok:
            res.update(opened=True, by=name)
            return res
        why.append("%s: %s" % (name, reason))
    res["reason"] = "; ".join(why) or "no opener"
    return res


def main(argv):
    flags = {"--print", "--no-open", "--json"}
    bad = [a for a in argv if a.startswith("-") and a not in flags and a not in ("-h", "--help")]
    pos = [a for a in argv if not a.startswith("-")]
    if "-h" in argv or "--help" in argv:
        sys.stdout.write("usage: fwx open FILE|URL [--print|--no-open] [--json]\n")
        return 0
    if bad or len(pos) != 1:
        sys.stderr.write("fwx open: %s\nusage: fwx open FILE|URL [--print|--no-open] [--json]\n"
                         % ("unknown option: " + bad[0] if bad else "give exactly one FILE or URL"))
        return 2
    noopen = "--print" in argv or "--no-open" in argv
    target = pos[0]
    if not URL.match(target):
        target = os.path.abspath(target)
        if not os.path.exists(target):
            sys.stderr.write("fwx open: no such file: %s\n" % pos[0])
            return 2
    res = show(target, do_open=not noopen)
    if "--json" in argv:
        sys.stdout.write(json.dumps({k: res[k] for k in ("opened", "by", "target", "command")}) + "\n")
    elif res["opened"]:
        sys.stdout.write("opened %s (by %s)\n" % (target, res["by"]))
    elif noopen:
        sys.stdout.write(res["command"] + "\n")
    else:
        sys.stdout.write("NOT OPENED: %s\n%s\n" % (res["reason"], res["command"]))
    return 0
