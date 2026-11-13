"""One capture per walked screen of a UI-walk run, with no model: fwx walk capture --run R [--screens JSON] [--out DIR].

`--run` is a run folder or a namespace, as for `fwx walk ab`. The screens are `--screens` (a JSON text, or the path of a file holding
it) or, without it, the `screens` of the run's `run.json`: a list of URLs or of `{url, theme}` (theme `light` or `dark`, default
`light`: the theme the screen was walked in), or `{screens: [...]}`. Each is opened at 1440 wide in the run's own browser session and
captured as a PNG in `--out`, default the run's captures folder (`<git-common-dir>/fwx/walks/<run>/shots/`, outside the work
tree). It serves the part review and the factory handoff; widths, other themes and states are not here.

Every browser call goes through `fwx walk ab`, so its guards hold (the app's own hosts only, the run's namespace and idle timeout, no
caller-set flags); this command never starts `agent-browser` itself. The height is 900. `open` returns before a cold dev server has
drawn the app, so after it the snapshot is asked again every 0.5 s until it has an element (and the text of `app_run.ready`, when the
project sets one) or `app_run.ready_timeout_s` seconds (default 30) have passed, as the walk's selftest does; a page that has drawn
nothing by then is missing, never an `ok` on a blank PNG. The captures are the page as the app draws it: the planted control of the
walk (control.json) is not loaded in these sessions.

Output, one line per screen on stdout: `ok <absolute path> <url> theme=T width=1440`, or `missing <url> theme=T width=1440: <why>`
(why is the last line the browser or the guard printed, "no element in the snapshot after N s" for a page that did not draw, or "no
file written" when the call returned 0 and left no PNG). The text line is split on whitespace by its readers, so a path with a space
in it is ambiguous there: `--json` prints one JSON object per screen instead, `{"status": "ok", "path", "url", "theme", "width"}` or
`{"status": "missing", "why", "url", "theme", "width"}`. Same exit codes and stderr. A stale PNG
at the target name is removed first, so only a capture of this call counts. Exit 0 when every screen has its capture; 1 with `fwx
screenshot: N of M missing: <urls>` on stderr when some do not (the others are still taken); 2 on a usage error or an unreadable run
or screens (nothing started, and zero screens is an error); 77 with `NOT RUN, NOT ARMED: ...` when `walk ab` could not start the
browser (`agent-browser` missing).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

from fwx import config
from fwx.commands import walk

WIDTH = 1440
HEIGHT = 900
THEMES = ("light", "dark")
USAGE = "usage: fwx walk capture --run R [--screens JSON|FILE] [--out DIR] [--json]"


def parse_screens(raw):
    """The list a `--screens` value holds: JSON text, or the path of a file with it."""
    if raw.lstrip()[:1] in ("[", "{"):
        text = raw
    else:
        try:
            with open(raw, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:  # a file that is not UTF-8 text is as unreadable as one that is not there
            raise walk.Stop("--screens is neither JSON nor a readable file (%s): %s" % (raw[:60], getattr(e, "strerror", None) or "not UTF-8 text"))
    try:
        value = json.loads(text)
    except ValueError as e:
        raise walk.Stop("--screens is not valid JSON (%s)" % e)
    return value["screens"] if isinstance(value, dict) and "screens" in value else value


def normalise(raw):
    """[{url, theme}] from a list of URLs and/or {url, theme}; anything else is exit 2."""
    if not isinstance(raw, list) or not raw:
        raise walk.Stop("no screens: give --screens or a `screens` list in run.json (a non-empty list of URLs or {url, theme})")
    out = []
    for item in raw:
        s = {"url": item} if isinstance(item, str) else item
        if not isinstance(s, dict) or not isinstance(s.get("url"), str) or not s["url"]:
            raise walk.Stop("a screen is a URL or {url, theme}: got %s" % json.dumps(item)[:80])
        theme = s.get("theme", "light")
        if theme not in THEMES:
            raise walk.Stop("screen %s: theme %r is not one of %s" % (s["url"], theme, ", ".join(THEMES)))
        out.append({"url": s["url"], "theme": theme})
    return out


def slug(url):
    path = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/]*", "", url)
    return re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-")[:40] or "root"


def ab_run(run_dir, session, args):
    """`fwx walk ab` with these words: the finished process. Never `agent-browser` directly. FWX_WALK_NO_CONTROL keeps the walk's planted
    control out of the session: a capture is the page as the app draws it."""
    cmd = [sys.executable, os.path.join(walk.ROOT, "bin", "fwx"), "walk", "ab", "--run", run_dir, session]
    return subprocess.run(cmd + args, capture_output=True, text=True, env=dict(os.environ, FWX_WALK_NO_CONTROL="1"))


def last_line(r):
    lines = [ln.strip() for ln in (r.stderr + r.stdout).splitlines() if ln.strip()]
    return lines[-1] if lines else "exit %d, no output" % r.returncode


def ab(run_dir, session, args):
    """(exit code, the last line `fwx walk ab` printed)."""
    r = ab_run(run_dir, session, args)
    return r.returncode, last_line(r)


def failed(rc, why):
    """None for exit 0, else the line that says why; 77 (`walk ab` could not start the browser) stops the whole command."""
    if rc == 77:
        raise walk.Stop(why[why.find("NOT RUN"):] if "NOT RUN" in why else "NOT RUN, NOT ARMED: " + why, 77)
    return None if rc == 0 else why


def step(run_dir, session, args):
    return failed(*ab(run_dir, session, args))


def settled(run_dir, session, ready, limit):
    """None once the page has drawn (a snapshot with an element, and `ready` when the project names one), else why not."""
    end = time.monotonic() + limit
    while True:
        r = ab_run(run_dir, session, ["snapshot"])
        if r.returncode:
            return failed(r.returncode, last_line(r))
        n = walk.count_elements(r.stdout)
        if n > 0 and (not ready or ready in r.stdout):
            return None
        if time.monotonic() >= end:
            if n:
                return "%r is not in the snapshot after %g s: not the logged-in app, or it did not finish drawing" % (ready, limit)
            return "no element in the snapshot after %g s: the page did not draw" % limit
        time.sleep(walk.SETTLE_POLL_S)


def parse(argv):
    got, i = {}, 0
    while i < len(argv):
        if argv[i] in ("--run", "--screens", "--out") and i + 1 < len(argv):
            got[argv[i]] = argv[i + 1]
            i += 2
        elif argv[i] == "--json":
            got["--json"] = True
            i += 1
        else:
            raise walk.Stop("%s is not an option of this command, or lacks its value\n%s" % (argv[i], USAGE))
    if "--run" not in got:
        raise walk.Stop("--run is required\n" + USAGE)
    return got


def capture(run_dir, session, sc, dest, state, stage=None):
    """None when the PNG is at `dest`, else why not. `state` is what the session already has: its size and its theme. The browser
    writes to `stage` (a name in the run's captures folder, since `fwx walk ab` refuses a path in /tmp) and the file is moved to `dest`."""
    stage = stage or dest
    steps = []
    if not state["sized"]:
        steps.append(walk.set_viewport(WIDTH, HEIGHT))
    if sc["theme"] != state["theme"]:
        steps.append(["set", "media", sc["theme"]])
    steps += [["open", sc["url"]], ["snapshot"], ["screenshot", stage]]
    for args in steps:
        state["launched"] = True
        why = settled(run_dir, session, state["ready"], state["limit"]) if args[0] == "snapshot" else step(run_dir, session, args)
        if why:
            return why
        if args[:2] == ["set", "viewport"]:
            state["sized"] = True
        elif args[:2] == ["set", "media"]:
            state["theme"] = sc["theme"]
    if not os.path.isfile(stage) or not os.path.getsize(stage):
        return "no file written"
    if stage != dest:
        shutil.move(stage, dest)
    return None


def cmd(argv):
    o = parse(argv)
    run_dir = walk.run_dir_of(o["--run"])
    run = walk.read_json(os.path.join(run_dir, "run.json"), "run.json")
    screens = parse_screens(o["--screens"]) if "--screens" in o else run.get("screens")
    screens = normalise(screens)
    out = os.path.abspath(o["--out"]) if "--out" in o else run["shots"]
    os.makedirs(out, exist_ok=True)
    session = "w1" if run.get("container") else "shot"
    ready, limit, bad = walk.ready_config(run)
    if bad:
        raise walk.Stop(bad)
    state = {"sized": False, "theme": None, "launched": False, "ready": ready, "limit": limit}
    miss = []
    try:
        for i, sc in enumerate(screens, 1):
            dest = os.path.join(out, "%02d-%s-%s-%d.png" % (i, slug(sc["url"]), sc["theme"], WIDTH))
            if os.path.lexists(dest):
                os.remove(dest)
            stage = os.path.join(run["shots"], "stage-%s" % os.path.basename(dest))
            if os.path.lexists(stage):
                os.remove(stage)
            why = capture(run_dir, session, sc, dest, state, stage if os.path.dirname(dest) != run["shots"] else None)
            tag = "%s theme=%s width=%d" % (sc["url"], sc["theme"], WIDTH)
            if why:
                miss.append(sc["url"])
            if "--json" in o:
                row = {"status": "missing", "why": why} if why else {"status": "ok", "path": dest}
                sys.stdout.write(json.dumps(dict(row, url=sc["url"], theme=sc["theme"], width=WIDTH)) + "\n")
            elif why:
                sys.stdout.write("missing %s: %s\n" % (tag, why))
            else:
                sys.stdout.write("ok %s %s\n" % (dest, tag))
    finally:
        if state["launched"]:
            ab(run_dir, session, ["close"])
    if miss:
        sys.stderr.write("fwx walk capture: %d of %d missing: %s\n" % (len(miss), len(screens), ", ".join(miss)))
        return 1
    return 0


def main(argv):
    try:
        return cmd(argv)
    except walk.Stop as e:
        sys.stderr.write("fwx walk capture: %s\n" % e)
        return e.code
    except config.ConfigError as e:
        sys.stderr.write("fwx walk capture: %s\n" % e)
        return 2
