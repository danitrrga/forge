"""How forge's terminal screens look: the one place of marks and colours, so a later change of look touches nothing else.

The selector's rows are the terminal's own foreground and background with plain marks. The cards of `forge list` are
bold and dim in a terminal and plain into a pipe or with NO_COLOR (color_on). A look chosen later changes the constants and
the functions here; forge/selector.py and forge/configure.py ask for lines and never for a style.
"""
import os
import sys

CURSOR = ">"
ON = "[x]"
OFF = "[ ]"


def lines(visible):
    """The text lines for what a Selector shows (Selector.visible()): a title line per section, and a row line per row
    with the cursor mark (a space when the cursor is elsewhere), the on or off mark and the label."""
    out = []
    for item in visible:
        if item[0] == "header":
            out.append(item[1])
        else:
            _, label, on, at_cursor = item
            out.append("%s %s %s" % (CURSOR if at_cursor else " ", ON if on else OFF, label))
    return out


def hint():
    """The line under the list."""
    return "up/down move, space toggles, enter confirms, esc cancels"


# ---- the cards of forge list (forge/configure.py builds them, this draws them) -----------------------------------------------
# One card is a dict: the title keys `project`, `path`, `frozen`, then one labelled line per other key present. `skills` is a
# count in a short card (the string `*` where the project keeps every global skill) and a list, with `origins`, in a full one.
BOLD, DIM, YELLOW = "1", "2", "33"
LABEL_WIDTH = 10  # the label column: the longest label (`opted-out`) and a space
OPTION_WORD = {True: "on", False: "off", None: "unset"}
EVERY = {"skills": "* (every global skill)", "plugins": "* (every plugin)"}


def color_on(stream=None):
    """Whether `stream` (default stdout) is painted: a terminal, and NO_COLOR not set to anything."""
    stream = sys.stdout if stream is None else stream
    return stream.isatty() and not os.environ.get("NO_COLOR")


def paint(text, code, on):
    """`text` in the SGR `code` when `on`, as it is otherwise: the only place an escape sequence is made."""
    return "\033[%sm%s\033[0m" % (code, text) if on else text


def _value(card, key):
    v = card[key]
    if key == "skills" and isinstance(v, int):
        return str(v)
    if key == "profiles":
        return "none" if v is None else ", ".join(["%s (default)" % v["default"]] + list(v["offered"]))
    if key == "options":
        return ", ".join("%s %s" % (k, OPTION_WORD[x]) for k, x in v.items())
    origins = card.get("origins") or {}
    names = []
    for n in v:
        if n == "*":
            names.append(EVERY[key])
        elif key == "skills" and origins.get(n):
            names.append("%s (%s)" % (n, ",".join(origins[n])))
        else:
            names.append(n)
    return ", ".join(names) or "none"


def card_lines(card, color=False):
    """The readable lines of one card: `NAME  PATH  [frozen]`, then a labelled line for each key the card has, in its order
    (`opted_out` is labelled `opted-out`; `origins` is said inside the skills line)."""
    title = "%s  %s%s" % (paint(card["project"], BOLD, color), card["path"], "  " + paint("[frozen]", YELLOW, color) if card["frozen"] else "")
    out = [title]
    for key in card:
        if key in ("project", "path", "frozen", "origins"):
            continue
        label = key.replace("_", "-")
        out.append("  %s%s %s" % (paint(label, DIM, color), " " * (LABEL_WIDTH - len(label)), _value(card, key)))
    return out
