import json
import unittest

from fake_http import patch_urlopen
from payments import capture, charge, refund, webhooks_gen


class PaymentsTest(unittest.TestCase):
    def test_charge_posts_amount_in_cents(self):
        patcher, calls = patch_urlopen({"id": "ch_1"})
        with patcher:
            self.assertEqual(charge.charge(1250, "tok_ana"), {"id": "ch_1"})
        req = calls[0][0]
        self.assertEqual(req.full_url, "https://api.pay.example.test/v2/charges")
        self.assertEqual(json.loads(req.data), {"amount": 1250, "currency": "EUR", "source": "tok_ana"})

    def test_capture_path(self):
        patcher, calls = patch_urlopen({"status": "captured"})
        with patcher:
            capture.capture("ch_1")
        self.assertEqual(calls[0][0].full_url, "https://api.pay.example.test/v2/charges/ch_1/capture")

    def test_partial_refund(self):
        patcher, calls = patch_urlopen({"id": "re_1"})
        with patcher:
            refund.refund("ch_1", 500)
        self.assertEqual(json.loads(calls[0][0].data), {"charge": "ch_1", "amount": 500})

    def test_generated_webhook_client(self):
        patcher, calls = patch_urlopen([])
        with patcher:
            webhooks_gen.list_webhooks()
            webhooks_gen.delete_webhook("wh_9")
        self.assertEqual([c[0].get_method() for c in calls], ["GET", "DELETE"])
        self.assertEqual(calls[1][0].full_url, "https://api.pay.example.test/v2/webhooks/wh_9")


if __name__ == "__main__":
    unittest.main()
