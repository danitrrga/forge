import unittest

from money import fmt_money


class FmtMoneyTests(unittest.TestCase):
    def test_euros_and_cents(self):
        self.assertEqual(fmt_money(12345), "€123.45")

    def test_thousands_separator(self):
        self.assertEqual(fmt_money(123456789), "€1,234,567.89")

    def test_pads_cents(self):
        self.assertEqual(fmt_money(5), "€0.05")

    def test_zero(self):
        self.assertEqual(fmt_money(0), "€0.00")


if __name__ == "__main__":
    unittest.main()
