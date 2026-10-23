import json
import unittest

from shop.views import render_orders


def transport_returning(status, payload):
    def transport(method, path):
        return status, json.dumps(payload)
    return transport


class RenderOrdersTest(unittest.TestCase):
    def test_lists_orders(self):
        html = render_orders("c-1", transport_returning(200, {"orders": [
            {"id": "A-1001", "placed_on": "1 Oct 2026", "total": "€42.00", "status": "shipped"}]}))
        self.assertIn("A-1001", html)
        self.assertIn("shipped", html)

    def test_customer_without_orders(self):
        html = render_orders("c-2", transport_returning(200, {"orders": []}))
        self.assertIn("You have no orders yet.", html)


if __name__ == "__main__":
    unittest.main()
