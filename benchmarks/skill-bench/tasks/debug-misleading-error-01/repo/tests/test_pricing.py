import unittest
from datetime import date

from billing.pricing import due_date, format_money, invoice_total, late_fee_cents

CFG = {"currency": "EUR", "tax_rate": 0.21, "late_fee_rate": 0.015, "net_days": 30}


class PricingTest(unittest.TestCase):
    def test_invoice_total(self):
        self.assertEqual(invoice_total([("Widget", 3, 4000)], CFG), 14520)

    def test_late_fee(self):
        self.assertEqual(late_fee_cents(10000, 2, CFG), 300)

    def test_due_date(self):
        self.assertEqual(due_date(date(2026, 10, 1), CFG), date(2026, 10, 31))

    def test_format_money(self):
        self.assertEqual(format_money(14520, CFG), "EUR 145.20")


if __name__ == "__main__":
    unittest.main()
