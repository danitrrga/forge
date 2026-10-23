"""Long-running worker: sends the weekly summary every Monday morning."""
import time
from datetime import date

from report import weekly_summary


def run_forever(load_invoices, send_mail):
    last = None
    while True:
        today = date.today()
        if today.weekday() == 0 and today != last:
            send_mail("finance@example.test", "Receivables", weekly_summary(load_invoices()))
            last = today
        time.sleep(600)
