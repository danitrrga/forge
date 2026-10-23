import unittest
from datetime import date

from report import aging_buckets, overdue

PAID = [{"number": "F-1", "customer": "Acme", "amount_cents": 1000, "due": date(2020, 1, 1), "paid": True}]


class ReportTest(unittest.TestCase):
    # Anything that depends on the date cannot be tested yet: report.py reads date.today() itself.
    def test_paid_invoices_are_never_overdue(self):
        self.assertEqual(overdue(PAID), [])

    def test_paid_invoices_are_not_aged(self):
        self.assertEqual(aging_buckets(PAID), {"current": 0, "1-30": 0, "31-60": 0, "61+": 0})


if __name__ == "__main__":
    unittest.main()
