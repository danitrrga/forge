"""What a draw needs to know about where it is drawing: the theme, the glyph set, the colour depth and the width.

`detect(env, stream)` reads them from the environment: NO_COLOR, a tty, COLORTERM and TERM for the colour depth; the locale and
FORGE_ICONS (nerd|unicode|ascii) for the glyph set; FORGE_THEME (dark|light, and auto when unset: COLORFGBG says light or dark,
dark when it is not set) for the theme; COLUMNS or the terminal size for the width, at least MIN_WIDTH."""
import shutil

from forge.ui import tokens

MIN_WIDTH = 60  # the narrowest width the screens are drawn and tested at; status_line(width=) still adapts below it
COLOR_DEPTHS = ("none", "16", "256", "truecolor")
LIGHT_BG = {"7", "15"}


class Context:
    """`theme`, `glyphs` and `color` are names (dark|light, nerd|unicode|ascii, none|16|256|truecolor); `width` is columns.
    Components read glyphs through `glyph(name)` and never carry one themselves."""

    def __init__(self, theme="dark", glyphs="unicode", color="none", width=80):
        if theme not in tokens.THEMES:
            raise ValueError("unknown theme %r" % (theme,))
        if glyphs not in tokens.GLYPH_SETS:
            raise ValueError("unknown glyph set %r" % (glyphs,))
        if color not in COLOR_DEPTHS:
            raise ValueError("unknown colour depth %r" % (color,))
        self.theme, self.glyphs, self.color, self.width = theme, glyphs, color, int(width)

    def glyph(self, name):
        return tokens.glyphs(self.glyphs)[name]

    @property
    def colors(self):
        return tokens.theme(self.theme)

    @property
    def layout(self):
        return tokens.layout()

    @property
    def ellipsis(self):
        """The mark of a cut text: the `ellipsis` token of the glyph set."""
        return self.glyph("ellipsis")

    def replace(self, **kw):
        fields = {"theme": self.theme, "glyphs": self.glyphs, "color": self.color, "width": self.width}
        fields.update(kw)
        return Context(**fields)

    def __repr__(self):
        return "Context(theme=%r, glyphs=%r, color=%r, width=%r)" % (self.theme, self.glyphs, self.color, self.width)


def _color_depth(env, stream):
    if env.get("NO_COLOR"):
        return "none"
    isatty = getattr(stream, "isatty", None)
    if stream is None or isatty is None or not isatty():
        return "none"
    term = env.get("TERM", "")
    if term in ("", "dumb"):
        return "none"
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    if "256color" in term:
        return "256"
    return "16"


def _utf8(env):
    for key in ("LC_ALL", "LC_CTYPE", "LANG"):
        value = env.get(key)
        if value:
            return "utf-8" in value.lower() or "utf8" in value.lower()
    return False


def _glyph_set(env):
    if not _utf8(env):
        return "ascii"
    choice = env.get("FORGE_ICONS", "").lower()
    return choice if choice in tokens.GLYPH_SETS else "unicode"


def _theme(env):
    """FORGE_THEME dark or light; anything else, and unset, is auto: COLORFGBG says light (7 or 15) or dark, and dark when it is not set."""
    choice = env.get("FORGE_THEME", "").lower()
    if choice in tokens.THEMES:
        return choice
    return "light" if env.get("COLORFGBG", "").split(";")[-1] in LIGHT_BG else "dark"


def _width(env):
    try:
        columns = int(env.get("COLUMNS", ""))
    except ValueError:
        columns = 0
    if columns <= 0:
        columns = shutil.get_terminal_size((80, 24)).columns
    return max(MIN_WIDTH, columns)


def detect(env, stream):
    """The Context for a process: `env` is a mapping (os.environ), `stream` the file the screen is written to."""
    return Context(theme=_theme(env), glyphs=_glyph_set(env), color=_color_depth(env, stream), width=_width(env))
