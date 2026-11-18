"""How forge's terminal screens look: the one place of marks and colours, so a later change of look touches nothing else.

Today it is the terminal's own foreground and background, no colour and no escape sequence, and plain marks. A look
chosen later changes the constants and the functions here; forge/selector.py asks for lines and never for a style.
"""

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
