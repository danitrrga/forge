"""The brand mark. PLACEHOLDER: this anvil stands in until a final logo exists; replace the grid, nothing else reads it.

The grid is pixels, two pixel rows per text line, drawn with half blocks. The first text line is `accent`, the other three
`mute`. The ascii set has no half blocks, so a filled cell there is `#`.
"""
from forge.ui.model import Span

MARK_PIXELS = (
    "##################",
    "..################",
    "......##########..",
    "........######....",
    "........######....",
    "........######....",
    ".....##########...",
    "....############..",
)
UPPER, LOWER, FULL = "▀", "▄", "█"


def _text_lines(pixels, upper, lower, full):
    out = []
    for r in range(0, len(pixels), 2):
        cells = []
        for a, b in zip(pixels[r], pixels[r + 1]):
            cells.append(full if a == b == "#" else upper if a == "#" else lower if b == "#" else " ")
        out.append("".join(cells))
    return out


MARK_PLACEHOLDER = tuple(_text_lines(MARK_PIXELS, UPPER, LOWER, FULL))


def mark_lines(ctx):
    """The mark as four lists of spans for header(): the first line accent, the others mute."""
    if ctx.glyphs == "ascii":
        text = _text_lines(MARK_PIXELS, "#", "#", "#")
    else:
        text = MARK_PLACEHOLDER
    return [[Span("accent" if i == 0 else "mute", line)] for i, line in enumerate(text)]
