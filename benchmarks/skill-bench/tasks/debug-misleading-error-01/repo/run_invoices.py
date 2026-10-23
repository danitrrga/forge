"""Print this month's invoices: python3 run_invoices.py [settings.ini]"""
import sys
from datetime import date

from billing.config import load_config
from billing.pricing import due_date, format_money, invoice_total

INVOICES = {
    "Ana": [("Widget", 3, 4000)],
    "Ben": [("Widget", 1, 4000), ("Gadget", 2, 1550)],
}


def main(settings="settings.ini"):
    cfg = load_config(settings)
    issued = date(2026, 10, 1)
    for customer, lines in INVOICES.items():
        total = invoice_total(lines, cfg)
        print("%-6s %s  due %s" % (customer, format_money(total, cfg), due_date(issued, cfg)))


if __name__ == "__main__":
    main(*sys.argv[1:])
