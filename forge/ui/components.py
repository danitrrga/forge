"""The components: pure functions that take a Context and return lines (a Line is `forge.ui.model.Line`).

The one rule: a component never carries a colour or a glyph. It names a role (`"accent"`) or a glyph token
(`ctx.glyph("check_on")`) from tokens.json. No printing and no I/O here; render_ansi and render_html draw what comes back.
Every public component returns `list[Line]` except `meter`, which returns the `list[Span]` that goes inside a line.
"""
import textwrap
import unicodedata

from forge.ui import tokens
from forge.ui.model import Line, Span

FAMILY = {"executor": "build", "planner": "plan", "pre-mortem": "plan", "post-mortem": "plan", "reviewer": "check",
          "security-reviewer": "check", "review-verifier": "check", "ui-walker": "check", "ui-verifier": "check",
          "researcher": "read", "state": "read", "decisions": "read", "demo": "read", "skill-proposer": "read"}
DOT = {"build": "dot_build", "plan": "dot_plan", "check": "dot_check", "read": "dot_read"}
# band kind -> (surface, icon glyph, icon role)
BAND = {"refused": ("warn_band", "icon_refused", "warn"), "broken": ("error_band", "icon_broken", "error"),
        "frozen": ("neutral_band", "icon_frozen", "ink"), "stale": ("neutral_band", "icon_stale", "ink"),
        "done": ("ok_band", "icon_done", "ok")}
AGENT_STATE_ROLE = {"starting": "mute", "running": "mute", "done": "ok", "findings": "warn", "failed": "error"}
KEYS_NAME_WIDTH = 11
UNIT_WIDTH = 7
MARGIN = 2  # a right-aligned part ends this many columns before the width


# ---- small helpers -------------------------------------------------------------------------------------------------------
def _w(ctx, width):
    return ctx.width if width is None else width


def _blank(n):
    return Span("body", " " * n)


def _spans_width(spans):
    return sum(len(s.text) for s in spans)


def _recolor(spans, role):
    return [Span(role, s.text, s.bold) for s in spans]


def _fill(spans, width):
    """`spans` padded with spaces to `width` columns (never cut)."""
    pad = width - _spans_width(spans)
    return list(spans) + ([_blank(pad)] if pad > 0 else [])


def _right(left, right, width):
    """`left` then `right` so that `right` ends MARGIN columns before `width`; at least one space between."""
    gap = max(1, width - MARGIN - _spans_width(left) - _spans_width(right))
    return list(left) + [_blank(gap)] + list(right)


def count_word(n, word):
    """`1 skill`, `2 skills`: a count and its word, singular for exactly one."""
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def truncate(ctx, text, n):
    """`text` cut to at most `n` characters, the last of them the ellipsis when something was cut."""
    if len(text) <= n:
        return text
    return text[:n - 1] + ctx.ellipsis if n > 0 else ""


def fit_first(candidates, width):
    """The first line of `candidates` that is at most `width` wide; the last one when none is."""
    for line in candidates:
        if line.width <= width:
            return line
    return candidates[-1]


def _printable(text):
    """`text` with every control character (a newline, a tab, an escape) and line separator replaced by a space: a band is one line."""
    return "".join(" " if unicodedata.category(ch) in ("Cc", "Zl", "Zp") else ch for ch in text)


# ---- meter -----------------------------------------------------------------------------------------------------------------
def meter(ctx, done, total, cells=None, mode="ramp"):
    """`cells` glyphs, the first `filled` of them full. ramp: the filled cells brighten from ramp0 to ramp3; flat: all accent."""
    if cells is None:
        cells = ctx.layout["meter_cells"]
    if total <= 0 or done <= 0:
        filled = 0
    elif done >= total:
        filled = cells
    else:  # a full bar means complete: below the total it keeps one empty cell (but at least one filled, when there are two)
        filled = max(1, min(cells - 1, round(cells * done / total)))
    full, empty = ctx.glyph("meter_full"), ctx.glyph("meter_empty")
    if mode == "ramp":
        spans = [Span("ramp%d" % min(3, i * 4 // filled), full) for i in range(filled)]
    elif mode == "flat":
        spans = [Span("accent", full * filled)] if filled else []
    else:
        raise ValueError("unknown meter mode %r" % (mode,))
    if cells > filled:
        spans.append(Span("faint", empty * (cells - filled)))
    return spans


# ---- the rail and the steps ----------------------------------------------------------------------------------------------
def step(ctx, label, note="", state="active", label_width=0):
    """`<marker>  label   note`. `note` is a string (dim) or a list of spans. `label_width` pads the label so notes align."""
    if state not in ("active", "disabled"):
        raise ValueError("unknown step state %r (active or disabled)" % (state,))
    active = state == "active"
    spans = [Span("accent" if active else "faint", ctx.glyph("step_active")), _blank(2),
             Span("ink" if active else "faint", label.ljust(label_width), active)]
    if note:
        spans.append(_blank(3))
        spans.extend([Span("dim", note)] if isinstance(note, str) else note)
    return [Line(spans)]


def rail_start(ctx, spans):
    return [Line([Span("faint", ctx.glyph("rail_start")), _blank(2)] + list(spans))]


def rail_end(ctx, spans):
    return [Line([Span("faint", ctx.glyph("rail_end")), _blank(2)] + list(spans))]


def rail_blank(ctx):
    return [Line([Span("faint", ctx.glyph("rail_v"))])]


def _rail_line(ctx, spans, right=None, cursor=False, width=None):
    w = _w(ctx, width)
    spans = [Span("faint", ctx.glyph("rail_v")), _blank(2)] + list(spans)
    if right:
        spans = _right(spans, right, w)
    if cursor:
        return Line(_fill(spans, w), bg="band")
    return Line(spans)


def rail_line(ctx, spans, right=None, cursor=False, width=None):
    """`rail_v` and two spaces, then `spans`; `right` spans end two columns before the width; a cursor fills the line with the band."""
    return [_rail_line(ctx, spans, right, cursor, width)]


# ---- rows --------------------------------------------------------------------------------------------------------------------
def check_row(ctx, name, state, right=None, cursor=False):
    """A toggle row. state: on | off | pending_off (asked off, not applied yet) | on_faint (a frozen project's row)."""
    if state == "on":
        mark, label = Span("accent", ctx.glyph("check_on")), Span("body", name)
    elif state == "on_faint":
        mark, label = Span("faint", ctx.glyph("check_on")), Span("faint", name)
    elif state == "off":
        mark, label = Span("faint", ctx.glyph("check_off")), Span("faint", name)
    elif state == "pending_off":
        mark, label = Span("warn", ctx.glyph("check_off")), Span("dim", name)
        if right is None:
            right = [Span("warn", "off, not applied yet")]
    else:
        raise ValueError("unknown check state %r" % (state,))
    if cursor:
        label = Span("ink", name, True)
    return [_rail_line(ctx, [mark, _blank(1), label], right, cursor)]


def group(ctx, name, members, cursor=None, meter_done=None, icon_on=None, faint=False):
    """A set and its members as a tree. `cursor` is the index of the member under the cursor; `icon_on` is a (role, glyph) shown
    at the right of that row. The set's meter is flat: the set is a count, not a progress."""
    n = len(members)
    done = n if meter_done is None else meter_done
    count = [Span("mute", "  %d of %d" % (done, n))]
    bar = meter(ctx, done, n, cells=min(n, ctx.layout["meter_cells"]), mode="flat")
    head = [Span("faint" if faint else "accent", ctx.glyph("check_on")), _blank(1), Span("faint" if faint else "ink", name, not faint)]
    right = bar + count
    lines = [_rail_line(ctx, head, _recolor(right, "faint") if faint else right)]
    for i, member in enumerate(members):
        last = i == n - 1
        at = cursor == i
        tree = Span("faint", ctx.glyph("tree_last" if last else "tree_pipe") + " ")
        nest = Span("accent" if at else "faint", ctx.glyph("nest") + " ")
        label = Span("ink", member, True) if at else Span("faint" if faint else "mute", member)
        icon = [Span(icon_on[0], icon_on[1])] if at and icon_on else None
        lines.append(_rail_line(ctx, [tree, nest, label], icon, at))
    return lines


# ---- bands -------------------------------------------------------------------------------------------------------------------
def band(ctx, kind, message, action="", width=None):
    """One line on a coloured surface: icon, message, and the action at the right. Too long and the message is cut, never wrapped."""
    w = _w(ctx, width)
    message, action = _printable(message), _printable(action)
    surface, icon, role = BAND[kind]
    prefix = 1 + 1 + 2
    room = w - prefix - MARGIN
    if action and len(message) + 2 + len(action) > room:
        if room - 2 - len(action) >= 1:
            message = truncate(ctx, message, room - 2 - len(action))
        else:
            action = ""
    if not action:
        message = truncate(ctx, message, room)
    spans = [_blank(1), Span(role, ctx.glyph(icon)), _blank(2), Span("ink", message, True)]
    if action:
        spans = _right(spans, [Span("mute", action)], w)
    return [Line(_fill(spans, w), bg=surface)]


def stack(ctx, bands):
    """Bands under a screen: alert_gap_lines blank lines before each, none after the last. A band is a (kind, message, action)
    tuple or a list of Lines (what band() returns); anything else is a TypeError."""
    out = []
    for item in bands:
        if isinstance(item, tuple) and len(item) == 3 and all(isinstance(x, str) for x in item):
            lines = band(ctx, *item)
        elif isinstance(item, list) and item and all(isinstance(x, Line) for x in item):
            lines = item
        else:
            raise TypeError("stack takes (kind, message, action) tuples or lists of Line, not %r" % (item,))
        out.extend(Line([]) for _ in range(ctx.layout["alert_gap_lines"]))
        out.extend(lines)
    return out


# ---- keys, tables, header ------------------------------------------------------------------------------------------------
def keys(ctx, items):
    """The key line under a screen: `(glyph name or text, label)` items joined by the separator glyph. Too wide, it closes the gaps
    around the separators to one space, and then cuts the text."""
    table = tokens.glyphs(ctx.glyphs)
    parts = []
    for key, label in items:
        text = table.get(key, key)
        parts.append(text + (" " + label if label else ""))
    prefix = [Span("faint", ctx.glyph("rail_end")), _blank(2)]
    room = ctx.width - _spans_width(prefix)
    for gap in ("  ", " "):
        text = (gap + ctx.glyph("sep") + gap).join(parts)
        if len(text) <= room:
            break
    return [Line(prefix + [Span("dim", truncate(ctx, text, room))])]


def table(ctx, headers, rows, widths, align=None):
    """Columns without borders, two spaces apart. `headers` are strings (dim), `rows` lists of cells, a cell a list of spans."""
    align = align or ["l"] * len(widths)
    last = len(widths) - 1

    def pad(spans, i):
        gap = widths[i] - _spans_width(spans)
        if gap <= 0 or (i == last and align[i] == "l"):
            return list(spans)
        return list(spans) + [_blank(gap)] if align[i] == "l" else [_blank(gap)] + list(spans)

    out = []
    for cells in [[[Span("dim", h)] for h in headers]] + list(rows):
        spans = []
        for i, c in enumerate(cells):
            if i:
                spans.append(_blank(2))
            spans.extend(pad(c, i))
        out.append(Line(spans))
    return out


def header(ctx, product, version, tagline, mark_lines):
    """The mark on the left, then the product name, the version and the tagline wrapped at the layout measure."""
    mark_w = max((_spans_width(m) for m in mark_lines), default=0)
    text_w = max(10, min(ctx.layout["measure"], ctx.width - 2 - mark_w - 4))
    texts = [[Span("ink", product, True)], [Span("mute", version)]] + [[Span("mute", t)] for t in textwrap.wrap(tagline, text_w)]
    out = []
    for i in range(max(len(mark_lines), len(texts))):
        left = mark_lines[i] if i < len(mark_lines) else []
        right = texts[i] if i < len(texts) else []
        out.append(Line([_blank(2)] + _fill(left, mark_w) + [_blank(4)] + right))
    return out


# ---- the status line -----------------------------------------------------------------------------------------------------
def status_line(ctx, profile, skills, servers, phase=None, done=None, total=None, width=None):
    """One adaptive line: the profile on the left, the phase progress on the right. When it does not fit it drops, in order, the
    server count, the skill count, the phase text, the meter. The profile stays."""
    w = _w(ctx, width)
    if (done is None) != (total is None):
        raise ValueError("status_line takes done and total together, got done=%r total=%r" % (done, total))
    sep = Span("faint", "  " + ctx.glyph("sep") + "  ")

    def build(level):
        left = [_blank(2), Span("accent", ctx.glyph("mark")), _blank(1), Span("ink", profile, True)]
        if level < 2:
            left += [sep, Span("mute", count_word(skills, "skill"))]
        if level < 1:
            left += [sep, Span("mute", "%d mcp" % servers)]
        if phase is None:
            return left, []
        right = [Span("mute", "phase")]
        if level < 3:
            right.append(Span("mute", " " + phase))
        if total is not None:
            right.append(_blank(1))
            if level < 4:
                right += meter(ctx, done, total) + [_blank(2)]
            right.append(Span("mute", "%d/%d" % (done, total)))
        return left, right

    for level in range(5):
        left, right = build(level)
        if _spans_width(left) + (2 + _spans_width(right) if right else 0) + MARGIN <= w:
            break
    return [Line(_right(left, right, w))] if right else [Line(left)]


# ---- agent events --------------------------------------------------------------------------------------------------------
def agent_block(ctx, title, rows):
    """The fwx line and one line per agent: a dot whose shape names its kind, the agent, its unit, what it does and its state.
    `rows` are (agent, unit, what, (state kind, text)) tuples."""
    w = ctx.width
    name_w = max([KEYS_NAME_WIDTH] + [len(r[0]) + 1 for r in rows])
    out = [Line([_blank(2), Span("accent", ctx.glyph("mark")), _blank(1), Span("ink", "fwx", True), _blank(2), Span("mute", title)])]
    for i, (agent, unit, what, state) in enumerate(rows):
        kind, text = state
        tree = ctx.glyph("tree_last" if i == len(rows) - 1 else "tree_mid")
        left = [_blank(2), Span("faint", tree), _blank(1), Span("mute", ctx.glyph(DOT[FAMILY.get(agent, "read")])), _blank(1),
                Span("ink", agent.ljust(name_w), True), Span("mute", unit.ljust(UNIT_WIDTH))]
        right = [Span(AGENT_STATE_ROLE.get(kind, "mute"), text)]
        room = w - MARGIN - _spans_width(left) - len(text) - 2
        what = truncate(ctx, what, room) if room > 0 else ""
        out.append(Line(_right(left + [Span("mute", what)], right, w)))
    return out
