import unittest
from decimal import Decimal

from billing.tax import rate_from_string, vat_cents


class TaxTest(unittest.TestCase):
    def test_rate_from_percent_or_fraction(self):
        self.assertEqual(rate_from_string("21%"), Decimal("0.21"))
        self.assertEqual(rate_from_string(" 0.19 "), Decimal("0.19"))

    def test_vat_cents(self):
        self.assertEqual(vat_cents(3999, "ES"), 840)


if __name__ == "__main__":
    unittest.main()
