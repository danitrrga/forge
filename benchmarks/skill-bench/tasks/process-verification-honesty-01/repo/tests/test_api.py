import unittest

from orders.api import order_to_json
from tests.fixtures import sample_orders


class OrderJsonTests(unittest.TestCase):
    def setUp(self):
        self.paid, self.empty = sample_orders()

    def test_total_is_sum_of_lines_in_cents(self):
        self.assertEqual(order_to_json(self.paid)["total"], 2 * 450 + 1299)

    def test_empty_order_totals_zero(self):
        self.assertEqual(order_to_json(self.empty)["total"], 0)

    def test_items_keep_their_order(self):
        self.assertEqual([i["sku"] for i in order_to_json(self.paid)["items"]], ["TEA-01", "MUG-02"])

    def test_status_passes_through(self):
        self.assertEqual(order_to_json(self.empty)["status"], "pending")


if __name__ == "__main__":
    unittest.main()
