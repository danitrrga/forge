#!/usr/bin/env python3
"""forge/selector.py and forge/render.py: the key selector, a list moved with the arrows and toggled with space
(framework-discuss plan 4.4 U3a). Three layers, each tested on its own: `Selector.press` (a state machine fed key
names), `read_keys` (the decoder of a terminal's bytes, fed through a real pty) and `run` (owns the terminal).

Written first and run against a tree without forge/selector.py: "ImportError: cannot import name 'render' from 'forge'"
(the whole file stops at its first import). Negative controls on the finished code, each mutation put back afterwards; the message each one made this
file print is in the commit message:
  (b) a cancel that returns what changed         -> "esc returned changes = ..."
  (c) a decoder that reads \\x1b[B as esc          -> "down arrow read as esc = ..."
  (d) a run without its finally                  -> "terminal left in raw mode after ..."
  (e) a drawing of every row                     -> "rendered 30 rows, window is 10"
plus a window of one row that loses the cursor, a run that does not refuse without a tty, and a render that paints.

The terminal is a pty made here with pty.openpty(): no window opens, and nothing of this machine's terminal is read.
Without termios or pty (not POSIX) the three pty cases print NOT RUN, NOT ARMED and the file exits 77."""
import contextlib
import io
import itertools
import os
import re
import select as stdlib_select
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from forge import render  # noqa: E402
from forge import selector  # noqa: E402

try:
    import pty
    import termios
    import tty
except ImportError:
    pty = termios = tty = None

failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def two_sections():
    return [("Skills", [("skill:a", "a", True), ("skill:b", "b", False)]),
            ("Servers", [("server:x", "x", False), ("server:y", "y", True)])]


def many(n=30):
    return [("Skills", [("skill:%02d" % i, "row%02d" % i, False) for i in range(n)])]


def feed(sel, names):
    for name in names:
        sel.press(name)
    return sel


def marked(lines):
    """The labels of the rows the drawing marks with the cursor."""
    return [l.split()[-1] for l in lines if l.startswith(render.CURSOR)]


# (a) the recorded keys over two sections: the two rows changed, nothing else.
RECORDED = ["down", "space", "down", "space", "enter"]
want("(a) run with recorded keys returns the two changed rows",
     selector.run(two_sections(), keys=RECORDED), {"skill:b": True, "server:x": True})
sel = feed(selector.Selector(two_sections()), RECORDED)
want("(a) press: finished and not cancelled", (sel.finished, sel.cancelled), (True, False))
want("(a) a row toggled twice is not a change",
     selector.run(two_sections(), keys=["space", "space", "enter"]), {})
want("(a) space on an on row turns it off",
     selector.run(two_sections(), keys=["space", "enter"]), {"skill:a": False})
want("(a) up at the first row and down at the last stay put",
     feed(selector.Selector(two_sections()), ["up", "up"]).cursor, 0)
want("(a) down past the end stays on the last row",
     feed(selector.Selector(two_sections()), ["down"] * 9).cursor, 3)
want("(a) an unknown key changes nothing and does not finish",
     (feed(selector.Selector(two_sections()), ["other", "x"]).finished,), (False,))
want("(a) keys that run out before Enter are a cancel",
     selector.run(two_sections(), keys=["down", "space"]), None)
want("(a) no rows: nothing to choose, no change", selector.run([("Empty", [])], keys=["enter"]), {})
try:
    selector.Selector([("A", [("k", "one", True)]), ("B", [("k", "two", False)])])
    failures.append("a duplicate row id was accepted")
except ValueError:
    pass

# (b) esc and ctrl-c return nothing, whatever was toggled before.
for name in ("esc", "ctrl-c"):
    got = selector.run(two_sections(), keys=["down", "space", name])
    want("%s returned changes" % name, got, None)
    sel = feed(selector.Selector(two_sections()), ["down", "space", name])
    want("%s: press finishes as a cancel" % name, (sel.finished, sel.cancelled, sel.result()), (True, True, None))
sel = feed(selector.Selector(two_sections()), ["esc", "down", "space", "enter"])
want("keys after the end are ignored", (sel.cancelled, sel.result()), (True, None))

# (e) a long list scrolls: 30 rows, a window of 10.
sel = selector.Selector(many(), window=10)
for _ in range(12):
    sel.press("down")
lines = render.lines(sel.visible())
want("rendered %d rows, window is 10" % len(lines), len(lines) <= 10, True)
want("(e) after twelve down, row 12 is the marked one", marked(lines), ["row12"])
sel = feed(sel, ["up"] * 12)
lines = render.lines(sel.visible())
want("(e) back at the top: the section's title and row 0 are shown", (lines[0], marked(lines)), ("Skills", ["row00"]))
want("(e) the end of the list: the last row marked, still 10 rows",
     (len(render.lines(feed(selector.Selector(many(), window=10), ["down"] * 40).visible())),
      marked(render.lines(feed(selector.Selector(many(), window=10), ["down"] * 40).visible()))), (10, ["row29"]))
want("(e) a list that fits is drawn whole: 2 titles and 4 rows",
     len(render.lines(selector.Selector(two_sections(), window=10).visible())), 6)

# A window smaller than three rows still shows the cursor's row, walking down the whole list and back up.
for window in (1, 2):
    sel = selector.Selector(two_sections(), window=window)
    for step, name in enumerate(["down"] * 3 + ["up"] * 3):
        lines = render.lines(sel.visible())
        want("window %d, step %d: cursor row shown, at most %d lines" % (window, step, window),
             (len(marked(lines)), len(lines) <= window), (1, True))
        sel.press(name)

# The default look: the terminal's own colours and plain marks, no escape sequence at all.
every = render.lines(selector.Selector(two_sections()).visible()) + [render.hint()]
want("render: no escape sequence in a drawing", [l for l in every if "\x1b" in l], [])
want("render: on and off marks",
     (any("[x] a" in l for l in every), any("[ ] b" in l for l in every)), (True, True))

# Not a terminal: one line, no change, no traceback.
r, w = os.pipe()
err = io.StringIO()
try:
    with os.fdopen(r, "rb", buffering=0) as pin, os.fdopen(w, "wb", buffering=0) as pout, contextlib.redirect_stderr(err):
        got = selector.run(two_sections(), stdin=pin, stdout=pout)
except Exception as e:  # noqa: BLE001
    got, err = "raised %r" % e, io.StringIO()
want("no tty: run returns no change instead of raising", got, None)
want("no tty: one line that points at the flags", (err.getvalue().count("\n"), "flags" in err.getvalue()), (1, True))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    got = selector.run(two_sections(), stdin=io.StringIO(""), stdout=io.StringIO())
want("no tty: objects without a file descriptor are refused too", (got, err.getvalue().count("\n")), (None, 1))

if pty is None:
    print("NOT RUN, NOT ARMED: no termios or pty on this platform; the decoder and the terminal cases did not run")
    for msg in failures:
        print("FAIL", msg)
    sys.exit(1 if failures else 77)


def raw_pty():
    master, slave = pty.openpty()
    return master, slave


def drain(master):
    out = b""
    while True:
        time.sleep(0.05)
        try:
            if not stdlib_select.select([master], [], [], 0.2)[0]:
                return out
            out += os.read(master, 65536)
        except OSError:
            return out


# (c) the decoder, through a real pty and real bytes.
master, slave = raw_pty()
try:
    tty.setraw(slave)
    os.write(master, b"\x1b[B \r")
    want("down arrow read as esc", list(itertools.islice(selector.read_keys(slave), 3)), ["down", "space", "enter"])
    os.write(master, b"\x1b[A\x1bOB\x1b[1;5B\x03\nx")
    want("(c) up, application-mode down, modified down, ctrl-c, newline, a letter",
         list(itertools.islice(selector.read_keys(slave), 6)), ["up", "down", "down", "ctrl-c", "enter", "other"])
    os.write(master, b"\x1b")
    t0 = time.monotonic()
    got = list(itertools.islice(selector.read_keys(slave), 1))
    want("(c) a lone escape byte followed by nothing is esc", got, ["esc"])
    want("(c) ... and it waits for the 50 ms, not for ever", time.monotonic() - t0 < 2, True)
    os.write(master, b"\x1bx \x1b[")
    want("(c) alt+letter and a cut-off sequence are other, and the stream goes on",
         list(itertools.islice(selector.read_keys(slave), 3)), ["other", "space", "other"])
finally:
    os.close(master)
    os.close(slave)


def run_in_pty(keys, boom=False, sections=None, window=None):
    """run() on a pty in a thread; the keys are written once the terminal is raw (a byte written earlier meets the
    line discipline: Ctrl-C would be eaten as a signal). Returns (result, exception, attrs before, attrs after, drawn)."""
    master, slave = pty.openpty()
    box = {}
    try:
        before = termios.tcgetattr(slave)
        term = os.fdopen(slave, "r+b", buffering=0, closefd=False)

        def target():
            try:
                box["result"] = selector.run(sections or two_sections(), window=window, stdin=term, stdout=term)
            except BaseException as e:  # noqa: BLE001
                box["error"] = e
        saved = render.lines
        if boom:
            def exploding(visible):
                raise RuntimeError("boom")
            render.lines = exploding
        try:
            th = threading.Thread(target=target)
            th.start()
            deadline = time.monotonic() + 5
            while th.is_alive() and time.monotonic() < deadline and termios.tcgetattr(slave)[3] & termios.ICANON:
                time.sleep(0.01)
            if not boom:
                time.sleep(0.1)
                os.write(master, keys)
            th.join(5)
            alive = th.is_alive()
        finally:
            render.lines = saved
        if alive:
            os.write(master, b"\x03\x03")  # unstick a run that did not end, so the test can report
            th.join(2)
        drawn = drain(master)
        after = termios.tcgetattr(slave)
        term.close()
        return box.get("result", "no result"), box.get("error"), before, after, drawn, alive
    finally:
        os.close(master)
        os.close(slave)


for label, keys, expect in (("Enter", b"\x1b[B \r", {"skill:b": True}),
                            ("Ctrl-C", b"\x1b[B \x03", None)):
    result, error, before, after, drawn, alive = run_in_pty(keys)
    want("(d) run ended on %s" % label, (alive, error), (False, None))
    want("(a) the pty run on %s: result" % label, result, expect)
    want("terminal left in raw mode after %s" % label, after == before, True)
    want("(d) %s: the drawing used no colour" % label, re.findall(rb"\x1b\[[0-9;]*m", drawn), [])
    want("(d) %s: the screen showed the rows" % label, b"[x] a" in drawn and b"Servers" in drawn, True)
result, error, before, after, drawn, alive = run_in_pty(b"", boom=True)
want("(d) an exception in the drawing reaches the caller", (alive, repr(error)), (False, "RuntimeError('boom')"))
want("terminal left in raw mode after an exception", after == before, True)
result, error, before, after, drawn, alive = run_in_pty(b"\x1b[B\x1b[B\x1b[B\x1b[B \r", sections=many(), window=5)
want("(e) a pty run with 30 rows and a window of 5 reaches row 4 and toggles it", (error, result), (None, {"skill:04": True}))
want("(e) every redraw is at most 5 rows plus the hint: the highest row printed is 5 lines below the title",
     b"row09" not in drawn, True)

for msg in failures:
    print("FAIL", msg)
print("%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
