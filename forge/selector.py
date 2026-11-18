"""A list in the terminal, moved with the arrows and toggled with space: sections of rows that are switched on and off.

Standard library only (termios, tty and the stdlib `select`). Three layers, each testable alone:

  Selector   a state machine fed key names ("up", "down", "space", "enter", "esc", "ctrl-c"); no terminal involved
  read_keys  decodes the bytes a terminal sends into those names
  run        owns the terminal: raw mode, drawing through forge/render.py, and the restore of the terminal in a `finally`

A row is `(id, label, on)`; a section is `(title, [rows])`, and an empty title draws no title line. `run` returns
`{id: new state}` for the rows that differ from where they began (`{}` when Enter confirms no change) and None when
the choice was cancelled (Esc, Ctrl-C, the input ending) or could not be asked (no terminal). Callers treat both
"no change" outcomes alike unless they want to say "cancelled".

It is `selector`, not `select`: a file named like the stdlib module would shadow it wherever the forge/ folder ends up on
sys.path and `select` is an extension module, not a built-in one.
"""
import os
import select as stdlib_select
import sys

from forge import render

try:
    import termios
    import tty
except ImportError:  # not POSIX: run() refuses, the Selector still works
    termios = tty = None

ESC_WAIT = 0.05  # seconds a lone escape byte waits for the rest of an arrow's bytes before it counts as Esc
DEFAULT_WINDOW = 10
NO_TERMINAL = "forge: this screen needs a terminal; use the command's flags (--on, --off) instead"
CTRL_C, ESC, ENTER_BYTES = b"\x03", b"\x1b", (b"\r", b"\n")


class Selector:
    """The state of the list: rows, the cursor, the scroll window and whether it is finished."""

    def __init__(self, sections, window=DEFAULT_WINDOW):
        self.rows = []        # [id, label, on, on at the start]
        self._lines = []      # the display lines in order: ("header", title) or ("row", index of self.rows)
        self._row_line = []   # for each row, its place in self._lines
        seen = set()
        for title, rows in sections:
            if title:
                self._lines.append(("header", title))
            for key, label, on in rows:
                if key in seen:
                    raise ValueError("the row id %r is in the list twice" % (key,))
                seen.add(key)
                self._row_line.append(len(self._lines))
                self._lines.append(("row", len(self.rows)))
                self.rows.append([key, label, bool(on), bool(on)])
        self.window = max(1, int(window))
        self.cursor = 0
        self.top = 0
        self.finished = False
        self.cancelled = False
        self._scroll()

    def press(self, key):
        """Apply one key name; True once the selector is finished (Enter, Esc or Ctrl-C). Keys after the end and
        names it does not know change nothing."""
        if self.finished:
            return True
        if key == "enter":
            self.finished = True
        elif key in ("esc", "ctrl-c"):
            self.finished = self.cancelled = True
        elif not self.rows:
            pass
        elif key == "down":
            self.cursor = min(self.cursor + 1, len(self.rows) - 1)
        elif key == "up":
            self.cursor = max(self.cursor - 1, 0)
        elif key == "space":
            self.rows[self.cursor][2] = not self.rows[self.cursor][2]
        self._scroll()
        return self.finished

    def changed(self):
        """{id: state now} for each row that differs from where it began, in list order."""
        return {key: on for key, _, on, start in self.rows if on != start}

    def result(self):
        """What run returns: the changed rows, or None when cancelled (and before it is finished)."""
        return self.changed() if self.finished and not self.cancelled else None

    def visible(self):
        """The window: at most `window` display lines, the cursor's row always among them. A title is ("header",
        title); a row is ("row", label, on, is the cursor's)."""
        out = []
        for kind, ref in self._lines[self.top:self.top + self.window]:
            if kind == "header":
                out.append(("header", ref))
            else:
                key, label, on, _ = self.rows[ref]
                out.append(("row", label, on, ref == self.cursor))
        return out

    def _scroll(self):
        if not self.rows:
            return
        line = self._row_line[self.cursor]
        # Keep the cursor's line in the window; when it is a section's first row and there is room, the title too.
        first = line - 1 if self.window >= 2 and line > 0 and self._lines[line - 1][0] == "header" else line
        if first < self.top:
            self.top = first
        if line >= self.top + self.window:
            self.top = line - self.window + 1
        self.top = max(0, min(self.top, len(self._lines) - self.window))


def _byte(fd, timeout):
    """One byte from fd; None when `timeout` seconds pass with nothing (None waits for ever); EOFError at the end."""
    if timeout is not None and not stdlib_select.select([fd], [], [], timeout)[0]:
        return None
    try:
        got = os.read(fd, 1)
    except OSError as e:  # a pty whose other end closed reads as EIO
        raise EOFError from e
    if not got:
        raise EOFError
    return got


def _key(fd):
    byte = _byte(fd, None)
    if byte == ESC:
        nxt = _byte(fd, ESC_WAIT)
        if nxt is None:
            return "esc"
        if nxt not in (b"[", b"O"):
            return "other"  # Alt plus a key
        while True:  # parameters (1;5) then the final byte, 0x40 to 0x7e
            last = _byte(fd, ESC_WAIT)
            if last is None:
                return "other"
            if 0x40 <= last[0] <= 0x7e:
                return {b"A": "up", b"B": "down"}.get(last, "other")
    if byte == b" ":
        return "space"
    if byte in ENTER_BYTES:
        return "enter"
    if byte == CTRL_C:
        return "ctrl-c"
    return "other"


def read_keys(fd):
    """Key names decoded from the bytes of fd (a terminal in raw mode), until it ends. A lone escape byte that nothing
    follows within 50 ms is "esc"; a key forge has no use for is "other"."""
    while True:
        try:
            name = _key(fd)
        except EOFError:
            return
        yield name


def _fileno(stream):
    try:
        return stream.fileno()
    except (AttributeError, ValueError, OSError):  # io.UnsupportedOperation is an OSError
        return None


def _size(fd):
    try:
        size = os.get_terminal_size(fd)
    except OSError:
        size = os.terminal_size((80, 24))
    return size.columns or 80, size.lines or 24


def _write(fd, text):
    data = text.encode("utf-8")
    while data:
        data = data[os.write(fd, data):]


def _draw(fd, sel, cols, rows, height):
    """Draw the frame over the one drawn before (`height` lines up) and return its height. Raw mode does not turn \\n
    into a line break, so each line ends in \\r\\n; lines are cut to the width so none wraps and the height holds."""
    frame = render.lines(sel.visible())
    if rows >= 2:
        frame.append(render.hint())
    _write(fd, ("\x1b[%dA\r" % height if height else "")
           + "".join("\x1b[2K%s\r\n" % line[:cols - 1] for line in frame))
    return len(frame)


def run(sections, window=None, keys=None, stdin=None, stdout=None):
    """Ask the owner. With `keys` (an iterable of key names, for a caller's tests) nothing touches a terminal.
    Otherwise stdin and stdout (default: the process's) must both be a terminal, else one line goes to stderr and the
    result is None. `window` caps the rows shown; the default fits the terminal."""
    if keys is not None:
        sel = Selector(sections, window or DEFAULT_WINDOW)
        for key in keys:
            if sel.press(key):
                break
        return sel.result()
    fd_in = _fileno(sys.stdin if stdin is None else stdin)
    fd_out = _fileno(sys.stdout if stdout is None else stdout)
    if termios is None or fd_in is None or fd_out is None or not (os.isatty(fd_in) and os.isatty(fd_out)):
        print(NO_TERMINAL, file=sys.stderr)
        return None
    cols, lines = _size(fd_out)
    room = max(1, lines - 1)  # a line is left for the hint
    sel = Selector(sections, min(window or room, room))
    if not sel.rows:
        return {}
    before = termios.tcgetattr(fd_in)
    height = 0
    try:
        tty.setraw(fd_in)
        height = _draw(fd_out, sel, cols, lines, height)
        for key in read_keys(fd_in):
            if sel.press(key):
                break
            height = _draw(fd_out, sel, cols, lines, height)
        else:
            sel.press("esc")  # the input ended: nothing was confirmed
    finally:
        try:
            _write(fd_out, "\x1b[%dA\r\x1b[J" % height if height else "")  # leave the screen as it was found
        finally:
            termios.tcsetattr(fd_in, termios.TCSADRAIN, before)
    return sel.result()
