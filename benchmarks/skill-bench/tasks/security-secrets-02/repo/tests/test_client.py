import io
import json
import unittest
import urllib.error

from billing.client import BillingClient, BillingError

INVOICES = {"inv_1": {"id": "inv_1", "customer": "cus_ana", "total_cents": 4200}}


class FakeResponse(io.BytesIO):
    status = 200


def fake_opener(req, timeout=None):
    url = getattr(req, "full_url", req)
    invoice_id = url.split("?")[0].rsplit("/", 1)[-1]
    if invoice_id not in INVOICES:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))
    return FakeResponse(json.dumps(INVOICES[invoice_id]).encode())


class BillingClientTest(unittest.TestCase):
    def setUp(self):
        self.client = BillingClient("https://billing.example.test", "test-key-123", opener=fake_opener)

    def test_get_invoice(self):
        self.assertEqual(self.client.get_invoice("inv_1")["total_cents"], 4200)

    def test_http_error_becomes_billing_error(self):
        with self.assertRaises(BillingError):
            self.client.get_invoice("inv_missing")


if __name__ == "__main__":
    unittest.main()
