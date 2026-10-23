"""Payment reminder e-mails for invoices that fall due in the next few days.

Run daily by cron:  python3 reminders.py data/invoices.json
Invoices come from the billing export (see data/invoices.example.json).
"""
import json
import sys
from datetime import date

REMIND_DAYS = 3


def days_until_due(invoice, today):
    return (date.fromisoformat(invoice["due"]) - today).days


def due_soon(invoices, today, days=REMIND_DAYS):
    """Unpaid invoices due between today and `days` days from now (both included), soonest first."""
    picked = []
    for inv in invoices:
        if "paid_at" in inv:
            continue
        left = days_until_due(inv, today)
        if 0 <= left <= days:
            picked.append(inv)
    return sorted(picked, key=lambda inv: inv["due"])


def reminder_text(invoice, today):
    left = days_until_due(invoice, today)
    when = "today" if left == 0 else "in %d day%s" % (left, "" if left == 1 else "s")
    return "Invoice %s for %.2f EUR is due %s." % (invoice["number"], invoice["amount_cents"] / 100, when)


def send_reminders(invoices, send, today=None):
    """Call send(email, text) once per invoice due soon; return how many were sent."""
    today = today or date.today()
    count = 0
    for inv in due_soon(invoices, today):
        send(inv["email"], reminder_text(inv, today))
        count += 1
    return count


def main(path):
    with open(path, encoding="utf-8") as fh:
        invoices = json.load(fh)
    n = send_reminders(invoices, lambda to, text: print("to %s: %s" % (to, text)))
    print("%d reminder(s) sent" % n)


if __name__ == "__main__":
    main(sys.argv[1])
