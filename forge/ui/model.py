"""What a component returns: lines of spans. A span is a run of text in one role; a line may carry a background surface.

Roles are token names of tokens.json. Every glyph forge draws is one terminal cell, so a line's width is its text length.
"""
from dataclasses import dataclass, field

ROLES = ("ink", "body", "mute", "dim", "faint", "accent", "ramp0", "ramp1", "ramp2", "ramp3", "warn", "ok", "error")
SURFACES = ("band", "warn_band", "error_band", "ok_band", "neutral_band")


@dataclass
class Span:
    role: str
    text: str
    bold: bool = False

    def __post_init__(self):
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
