"""Orders and order lines."""
from dataclasses import dataclass, field

from pricing import line_total


@dataclass
class Line:
    sku: str
    qty: int
    unit_cents: int


@dataclass
class Order:
    number: str
    customer: str
    lines: list = field(default_factory=list)

    def total(self):
        """Order total including VAT, in cents."""
        return sum(line_total(line) for line in self.lines)
