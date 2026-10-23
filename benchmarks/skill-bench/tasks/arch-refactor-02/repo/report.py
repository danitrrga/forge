"""Accounts-receivable report for the weekly finance e-mail.

An invoice is a dict: {"number": "F-101", "customer": "Acme", "amount_cents": 12000,
                       "due": datetime.date(2026, 3, 1), "paid": False}
"""
from datetime import date

BUCKETS = [(0, "current"), (1, "1-30"), (31, "31-60"), (61, "61+")]


def days_late(invoice):
    """Days past the due date (0 when not due yet)."""
    return max(0, (date.today() - invoice["due"]).days)


def overdue(invoices):
    """Unpaid invoices past their due date, latest first."""
    late = [inv for inv in invoices if not inv["paid"] and days_late(inv) > 0]
    return sorted(late, key=lambda inv: (-days_late(inv), inv["number"]))


def aging_buckets(invoices):
    """Unpaid amount per age bucket, in cents."""
    totals = {label: 0 for _, label in BUCKETS}
    for inv in invoices:
        if inv["paid"]:
            continue
        late = days_late(inv)
        label = [name for start, name in BUCKETS if late >= start][-1]
        totals[label] += inv["amount_cents"]
    return totals


def _line(inv):
    return "%-8s %-16s %10.2f %4d days" % (inv["number"], inv["customer"], inv["amount_cents"] / 100, days_late(inv))


def weekly_summary(invoices):
    """Body of the weekly e-mail."""
    lines = ["Receivables on %s" % date.today().isoformat(), ""]
    lines += [_line(inv) for inv in overdue(invoices)] or ["Nothing overdue."]
    buckets = aging_buckets(invoices)
    lines += ["", "  ".join("%s %.2f" % (name, buckets[name] / 100) for _, name in BUCKETS)]
    return "\n".join(lines)
