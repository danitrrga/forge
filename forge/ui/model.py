"""What a component returns: lines of spans. A span is a run of text in one role; a line may carry a background surface.

Roles are token names of tokens.json. Every glyph forge draws is one terminal cell, so a line's width is its text length.
"""
import unicodedata
from dataclasses import dataclass, field

ROLES = ("ink", "body", "mute", "dim", "faint", "accent", "ramp0", "ramp1", "ramp2", "ramp3", "warn", "ok", "error")
SURFACES = ("band", "warn_band", "error_band", "ok_band", "neutral_band")


def printable(text):
    """`text` with every control character (a newline, a tab, an escape) and line separator replaced by a space, so a span can
    neither split a line nor smuggle an escape sequence into a terminal."""
    return "".join(" " if unicodedata.category(ch) in ("Cc", "Zl", "Zp") else ch for ch in text)


@dataclass
class Span:
    role: str
    text: str
    bold: bool = False

    def __post_init__(self):
        self.text = printable(self.text)
        if self.role not in ROLES:
            raise ValueError("unknown role %r (roles: %s)" % (self.role, ", ".join(ROLES)))


@dataclass
class Line:
    spans: list = field(default_factory=list)
    bg: str = None

    def __post_init__(self):
        if self.bg is not None and self.bg not in SURFACES:
            raise ValueError("unknown surface %r (surfaces: %s)" % (self.bg, ", ".join(SURFACES)))

    @property
    def width(self):
        return sum(len(s.text) for s in self.spans)

    @property
    def text(self):
        return "".join(s.text for s in self.spans)
