"""Show a page or file to the owner: fwx open FILE|URL [--print|--no-open] [--json].

FILE is made absolute and must exist (exit 2, one line on stderr, when it does not); an http(s):// or file:// URL goes
through as is. How the page is opened is the user's configuration, never code: the optional `open` table of `.claude/fwx.json`
holds `command`, an argv list (never a shell string, no shell is run) in which `{url}` (a `file://` URL for a file, the URL
itself for a URL) and `{path}` (the absolute path; the URL itself for a URL) are replaced inside each element, e.g.
`{"open": {"command": ["my-viewer", "--open", "{url}"]}}`. The core knows no IDE and no system opener that launches
anything. A `command` that is not a non-empty list of strings with at least one placeholder, or an `open` that is not a
table, is a configuration error: exit 2, one line naming the key. A key left out and an explicit null mean the same, "not set"
(the generated file writes null for what is unset), so `{"open": null}` and `{"command": null}` are no opener, not an error.

The command runs with stdout and stderr captured and a timeout of TIMEOUT_S; exit 0 is "opened" (`by` is its first word).
A non-zero exit, a timeout or a program not on PATH is not opened, and so is a project with no `open.command` (the default,
and outside a git repository, where there is no configuration): nothing is opened by itself (a window must never appear on
the owner's desktop without warning), and the command prints `NOT OPENED: <reason>` and, on the next line, the command for
this system that the owner pastes (`xdg-open`, `open` or `start`, by sys.platform); for a target that cannot be quoted
safely for that shell (`unsafe`) no line is made and the one NOT OPENED line says why (`--print` then exits 2, `--json`
has `command: null`). It exits 0 either way. `--print` (or
`--no-open`) skips the configuration and the opener and prints that command alone, for unattended runs and tests.
`--json` prints `{opened, by, target, command}` instead.

An opener is a function `(url, path) -> (ok, reason)`; `show` tries a list of `(name, function)` in order, the first that works
wins. The configured command is the one opener there is today (`command_opener`).
"""
import json
import os
import re
import shlex
import subprocess
import sys
import unicodedata
from pathlib import Path

from fwx import config

URL = re.compile(r"(https?|file)://", re.I)
TIMEOUT_S = 20
USAGE = "usage: fwx open FILE|URL [--print|--no-open] [--json]\n"
# what the owner pastes, by sys.platform prefix; the last row is the default
SHOW = (("linux", "xdg-open"), ("darwin", "open"), ("win32", 'start ""'), ("", "xdg-open"))
PLACEHOLDERS = ("{url}", "{path}")


class OpenConfigError(Exception):
    """The `open` table cannot be used; the message names the key."""


def unsafe(target, platform=None):
    """Why no line to paste can be made for `target` on this system, or None when one can. Refused everywhere: a control or
    format character (a newline pasted into a terminal runs what follows it; a bidi override or a C1 control makes the owner
    read another target). On Windows, where the line is for cmd.exe: a double quote (no way to quote it), a %NAME% (expands even
    inside quotes) and any `!` (delayed expansion under `cmd /v:on` expands !NAME! and drops a lone one); every other
    character, `&` `|` `^` `<` `>` `(` `)` included, is literal inside the double quotes. On POSIX: a backslash (fish reads
    `\\` and `\'` inside single quotes where sh does not, so no one line is right for every shell); everything else is covered
    by shlex.quote, which closes and reopens the single quotes around a quote, and nothing inside single quotes expands."""
    platform = sys.platform if platform is None else platform
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in target):
        return "the target holds a control or format character"
    if platform.startswith("win32"):
        if '"' in target:
            return "the target holds a double quote, which cmd.exe cannot quote"
        if re.search(r"%[^%]+%", target):
            return "the target holds a %NAME% that cmd.exe would expand"
        if "!" in target:
            return "the target holds a !, which cmd.exe expands under /v:on"
    elif "\\" in target:
        return "the target holds a backslash, which fish reads differently from sh inside single quotes"
    return None


def paste_command(target, platform=None):
    """The command that shows `target` (a path or a URL) on this system, quoted for its shell; None when `unsafe`."""
    platform = sys.platform if platform is None else platform
    if unsafe(target, platform):
        return None
    word = next(w for prefix, w in SHOW if platform.startswith(prefix))
    quoted = '"%s"' % target if platform.startswith("win32") else shlex.quote(target)
    return "%s %s" % (word, quoted)


def command_from(cfg):
    """The argv template of `open.command` in a loaded configuration, or None when none is set. OpenConfigError otherwise."""
    table = cfg.get("open")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise OpenConfigError("`open` is %r, not a table (expected {\"command\": [...]})" % (table,))
    cmd = table.get("command")
    if cmd is None:
        return None
    if not isinstance(cmd, list) or not cmd or not all(isinstance(a, str) and a for a in cmd):
        raise OpenConfigError("`open.command` is %r, not a non-empty list of non-empty strings" % (cmd,))
    if not any(p in a for a in cmd for p in PLACEHOLDERS):
        raise OpenConfigError("`open.command` has neither {url} nor {path} in any element: %r" % (cmd,))
    return cmd


def command_opener(template):
    """An opener running the argv `template` with {url} and {path} filled in, no shell, output captured."""
    def opener(url, path):
        fill = {"{url}": url, "{path}": path}  # one pass: what is inserted is never scanned again
        argv = [re.sub(r"\{url\}|\{path\}", lambda m: fill[m.group(0)], a) for a in template]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=TIMEOUT_S)
        except FileNotFoundError:
            return False, "%s: not found on PATH" % argv[0]
        except subprocess.TimeoutExpired:
            return False, "%s: timed out after %gs" % (argv[0], TIMEOUT_S)
        except OSError as e:
            return False, "%s: %s" % (argv[0], e.strerror or e)
        if proc.returncode == 0:
            return True, ""
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, "%s: exit %d%s" % (argv[0], proc.returncode, ": " + tail[-1] if tail else "")
    return opener


def show(target, openers, platform=None):
    """Try `openers` ([(name, function)]) in order on `target` (an absolute path or a URL); the first that works wins.
    {opened, by, target, command, reason}. An opener is called `(url, path)`."""
    is_url = bool(URL.match(target))
    url = target if is_url else Path(target).as_uri()
    res = {"opened": False, "by": None, "target": target, "command": paste_command(target, platform), "reason": ""}
    why = []
    for name, opener in openers:
        ok, reason = opener(url, target)
        if ok:
            res.update(opened=True, by=name)
            return res
        why.append(reason)
    res["reason"] = "; ".join(why)
    return res


def _openers():
    """[(name, function)] from the project's configuration; [] when none is set or there is no configuration (outside a
    git repository). A broken configuration file raises config.ConfigError, a bad `open` table OpenConfigError."""
    try:
        config.main_checkout()
    except config.ConfigError:
        return []
    template = command_from(config.load())
    return [] if template is None else [(template[0], command_opener(template))]


def main(argv):
    flags = {"--print", "--no-open", "--json", "-h", "--help"}
    bad = [a for a in argv if a.startswith("-") and a not in flags]
    pos = [a for a in argv if not a.startswith("-")]
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(USAGE)
        return 0
    if bad or len(pos) != 1:
        sys.stderr.write("fwx open: %s\n%s" % ("unknown option: " + bad[0] if bad else "give exactly one FILE or URL", USAGE))
        return 2
    noopen = "--print" in argv or "--no-open" in argv
    target = pos[0]
    if not URL.match(target):
        target = os.path.abspath(target)
        if not os.path.exists(target):
            sys.stderr.write("fwx open: no such file: %s\n" % pos[0])
            return 2
    try:
        openers = [] if noopen else _openers()
    except (OpenConfigError, config.ConfigError) as e:
        sys.stderr.write("fwx open: %s\n" % " ".join(str(e).split()))
        return 2
    res = show(target, openers)
    if not res["opened"] and not noopen and not openers:
        res["reason"] = "no opener configured (set open.command in the fwx configuration)"
    # the exit status does not depend on the output format: --print has nothing to print without a safe line
    rc = 2 if noopen and res["command"] is None else 0
    why = unsafe(target) if res["command"] is None else None
    if rc:
        sys.stderr.write("fwx open: no command to paste: %s\n" % why)
    if "--json" in argv:
        sys.stdout.write(json.dumps({k: res[k] for k in ("opened", "by", "target", "command")}) + "\n")
    elif res["opened"]:
        sys.stdout.write("opened %s (by %s)\n" % (target, res["by"]))
    elif rc:
        pass
    elif res["command"] is None:
        sys.stdout.write("NOT OPENED: %s; no command to paste: %s\n" % (res["reason"], why))
    elif noopen:
        sys.stdout.write(res["command"] + "\n")
    else:
        sys.stdout.write("NOT OPENED: %s\n%s\n" % (res["reason"], res["command"]))
    return rc
