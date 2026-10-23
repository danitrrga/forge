"""Order summary printed by the back office:  python3 report.py"""
from models import Line, Order
from pricing import apply_coupon, line_total


def render(order):
    rows = ["Order %s for %s" % (order.number, order.customer)]
    for line in order.lines:
        rows.append("  %-14s x%-3d %9.2f" % (line.sku, line.qty, line_total(line) / 100))
    rows.append("  %-19s %9.2f" % ("TOTAL", order.total() / 100))
    return "\n".join(rows)


def main():
    order = Order("A-1001", "Ana Ruiz", [Line("MUG-BLUE", 2, 1200), Line("TEE-S", 1, 1999)])
    print(render(apply_coupon(order, "spring10")))


if __name__ == "__main__":
    main()
