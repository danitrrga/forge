"""Prices: VAT, line totals and coupons."""
from models import Line, Order

VAT_PCT = 21
COUPONS = {"SPRING10": 10, "VIP20": 20}


def line_total(line):
    """Line price including VAT, in cents, rounded half-up."""
    return (line.qty * line.unit_cents * (100 + VAT_PCT) + 50) // 100


def apply_coupon(order, code):
    """A copy of the order with a discount line for the coupon (an unknown code changes nothing)."""
    code = code.strip().upper()
    lines = list(order.lines)
    pct = COUPONS.get(code)
    if pct:
        net = sum(line.qty * line.unit_cents for line in order.lines)
        lines.append(Line("COUPON-" + code, 1, -(net * pct // 100)))
    return Order(order.number, order.customer, lines)
