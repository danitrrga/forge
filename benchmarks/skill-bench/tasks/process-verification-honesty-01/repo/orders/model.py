from dataclasses import dataclass, field


@dataclass
class Line:
    sku: str
    qty: int
    unit_cents: int


@dataclass
class Order:
    id: str
    customer: str
    status: str
    lines: list = field(default_factory=list)
