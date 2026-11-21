"""The brand mark: the anvil of design/system/logo.md, read from `anvil.json` (glyphs and exact colours: the art and nothing else).
Every glyph is plain ASCII, so the same art serves every glyph set.

A terminal with true colour or 256 colours and the dark theme draws each cell in the art's own colour (at 256, the nearest entry), a
soft pink gradient the palette roles cannot hold. Everywhere else (the light theme, 16 colours) each cell is drawn in the role nearest to
its colour in the dark theme, so contrast holds on any ground; with colour off it is the plain glyphs. The role is derived from the
current tokens when the module loads and never stored, so a changed token cannot leave stale data behind.
"""
import json
import os

from forge.ui import tokens
from forge.ui.model import Span

FALLBACK = ("ink", "body", "mute", "accent", "ramp2")  # the roles a cell may fall back to

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "anvil.json"), encoding="utf-8") as _f:
    ART = json.load(_f)


def fallback_roles(art, table):
    """For every cell of `art` the nearest of FALLBACK in `table` (a theme's colours), by distance in RGB; a space is `body`."""
    pal = {r: tokens.rgb(table["ramp"][2] if r == "ramp2" else table[r]) for r in FALLBACK}
    return [["body" if g == " " else min(pal, key=lambda r: sum((a - b) ** 2 for a, b in zip(tokens.rgb(c), pal[r])))
             for g, c in zip(row, colors)] for row, colors in zip(art["rows"], art["colors"])]


ROLES = fallback_roles(ART, tokens.theme("dark"))


def mark_lines(ctx):
    """The mark as one list of spans per row for header(): runs of cells that share a colour (or a role) are one span."""
    exact = ctx.color in ("truecolor", "256") and ctx.theme == "dark"
    out = []
    for glyphs, colors, roles in zip(ART["rows"], ART["colors"], ROLES):
        spans, key = [], None
        for g, c, r in zip(glyphs, colors, roles):
            cell = (r, c if exact and g != " " else None)
            if cell == key:
                spans[-1].text += g
            else:
                spans.append(Span(cell[0], g, rgb=cell[1]))
                key = cell
        out.append(spans)
    return out
