"""Customer sales summary:  python3 report.py orders.csv"""
import argparse
import csv
import sys


def load_orders(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [{"customer": r["customer"], "amount_cents": int(r["amount_cents"])} for r in csv.DictReader(fh)]


def summarize(orders):
    """[(customer, number of orders, total cents)], biggest total first, then by name."""
    totals = {}
    for order in orders:
        n, cents = totals.get(order["customer"], (0, 0))
        totals[order["customer"]] = (n + 1, cents + order["amount_cents"])
    return sorted(((c, n, t) for c, (n, t) in totals.items()), key=lambda row: (-row[2], row[0]))


def render_text(rows):
    lines = ["%-24s %6s %12s" % ("customer", "orders", "total")]
    for customer, n, cents in rows:
        lines.append("%-24s %6d %12s" % (customer, n, "{:,.2f}".format(cents / 100)))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Customer sales summary")
    parser.add_argument("path", help="orders CSV with customer and amount_cents columns")
    parser.add_argument("--format", choices=["text"], default="text")
    args = parser.parse_args(argv)
    rows = summarize(load_orders(args.path))
    sys.stdout.write(render_text(rows))


if __name__ == "__main__":
    main()
