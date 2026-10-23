import unittest

from billing.invoice import invoice_totals


class InvoiceTotalsTest(unittest.TestCase):
    def test_single_line(self):
        self.assertEqual(invoice_totals([("Widget", "10.00", 2)]),
                         {"subtotal": "20.00", "vat": "4.20", "total": "24.20"})

    def test_reduced_rate(self):
        self.assertEqual(invoice_totals([("Bread", "1.25", 4)], vat_rate="0.04"),
                         {"subtotal": "5.00", "vat": "0.20", "total": "5.20"})

    def test_empty_invoice(self):
        self.assertEqual(invoice_totals([]), {"subtotal": "0.00", "vat": "0.00", "total": "0.00"})


if __name__ == '__main__':
    unittest.main()
