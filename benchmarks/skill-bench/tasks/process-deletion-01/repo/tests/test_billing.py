import unittest

from billing.exports import ledger_rows
from billing.invoices import build_invoice


class InvoiceTest(unittest.TestCase):
    def test_vat_is_rounded_half_up(self):
        inv = build_invoice({"number": "T-1", "customer": "Ana", "country": "ES", "lines": [{"net_cents": 250}]})
        self.assertEqual((inv["net_cents"], inv["vat_cents"], inv["gross_cents"]), (250, 53, 303))

    def test_ledger_row(self):
        inv = build_invoice({"number": "T-2", "customer": "Ben", "country": "DE", "lines": [{"net_cents": 1000}]})
        self.assertEqual(ledger_rows([inv]), [["T-2", "Ben", "10.00", "1.90", "11.90"]])


if __name__ == "__main__":
    unittest.main()
