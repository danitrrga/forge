"""Loads and checks tokens.json, the one source of forge's look: colour roles per theme, glyph sets, layout numbers.

Nothing here draws. Components name a role or a glyph; the renderers ask this module for the value. `problems(data)` is
the whole schema check (tests/test_ui.py runs it and the contrast rules on the shipped file).
"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.json")
THEMES = ("dark", "light")
GLYPH_SETS = ("nerd", "unicode", "ascii")
RAMP = 4


def load(path=PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_cache = {}


def data():
    """The shipped tokens.json, read once."""
    if "data" not in _cache:
        _cache["data"] = load()
    return _cache["data"]


def theme(name):
    """The colour table of a theme: role -> "#rrggbb" (`ramp` is a list of four)."""
    return data()["themes"][name]


def glyphs(name):
    """The glyph table of a set: token name -> the string drawn."""
    return data()["glyphs"][name]


def cell_glyphs():
    """The glyph names that must be exactly one terminal cell in every set."""
    return data()["glyphs"]["cell_glyphs"]


def layout():
    return data()["layout"]


def role_color(table, role):
    """The "#rrggbb" of a span role in a theme table: `ramp0`..`ramp3` are the cells of `ramp`."""
    if role.startswith("ramp") and role[4:].isdigit():
        return table["ramp"][int(role[4:])]
    return table[role]


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hex_color):
    """WCAG 2.x relative luminance."""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(hex_color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a, b):
    """WCAG contrast ratio of two "#rrggbb" colours, 1.0 to 21.0."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _is_hex(v):
    return isinstance(v, str) and len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in v[1:])


def problems(tokens):
    """Every structural fault of a tokens dict, as readable lines; [] when it is sound."""
    out = []
    themes = tokens.get("themes", {})
    for name in THEMES:
        if name not in themes:
            out.append("theme %s is missing" % name)
    if out:
        return out
    keys = {name: set(themes[name]) for name in THEMES}
    if keys["dark"] != keys["light"]:
        out.append("dark and light differ in keys: %s" % sorted(keys["dark"] ^ keys["light"]))
    for name in THEMES:
        for role, value in themes[name].items():
            if role == "ramp":
                if not (isinstance(value, list) and len(value) == RAMP and all(_is_hex(v) for v in value)):
                    out.append("%s.ramp is not %d colours" % (name, RAMP))
            elif not _is_hex(value):
                out.append("%s.%s = %r is not #rrggbb" % (name, role, value))
    for role in tokens.get("roles", {}):
        for name in THEMES:
            if role not in themes[name]:
                out.append("role %s has no colour in theme %s" % (role, name))
    sets = tokens.get("glyphs", {})
    for name in GLYPH_SETS:
        if name not in sets:
            out.append("glyph set %s is missing" % name)
    if any(name not in sets for name in GLYPH_SETS):
        return out
    names = set(sets["nerd"])
    for name in GLYPH_SETS:
        if set(sets[name]) != names:
            out.append("glyph set %s differs from nerd in keys: %s" % (name, sorted(set(sets[name]) ^ names)))
    for glyph in sets.get("cell_glyphs", []):
        for name in GLYPH_SETS:
            value = sets[name].get(glyph)
            if value is None:
                out.append("cell glyph %s is not in set %s" % (glyph, name))
            elif len(value) != 1:
                out.append("cell glyph %s in set %s is %d characters (%r), want 1" % (glyph, name, len(value), value))
    for glyph, value in sets["ascii"].items():
        if not value.isascii():
            out.append("ascii glyph %s = %r is not ASCII" % (glyph, value))
    return out


def contrast_rows(table, rules):
    """(role, surface, ratio, minimum) for every pair the `contrast` block of tokens.json asks for, in one theme table."""
    rows = []
    for role in rules["text"]:
        for surface in rules["surfaces"]:
            rows.append((role, surface, contrast(role_color(table, role), table[surface]), rules["text_min"]))
    for role in rules["graphic"]:
        for i in range(RAMP):
            for surface in rules["surfaces"]:
                rows.append(("%s%d" % (role, i), surface, contrast(role_color(table, "%s%d" % (role, i)), table[surface]), rules["graphic_min"]))
    cb = rules["on_coloured_bands"]
    for band in cb["bands"]:
        for role in cb["roles"]:
            rows.append((role, band, contrast(table[role], table[band]), rules["text_min"]))
        own = cb["own_role"].get(band)
        if own:
            rows.append((own, band, contrast(table[own], table[band]), rules["text_min"]))
    return rows
