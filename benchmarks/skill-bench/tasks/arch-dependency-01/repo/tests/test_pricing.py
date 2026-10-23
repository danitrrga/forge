import unittest

from models import Line, Order
from pricing import apply_coupon, line_total


class PricingTest(unittest.TestCase):
    def test_line_total_adds_vat(self):
        self.assertEqual(line_total(Line("MUG-BLUE", 2, 1200)), 2904)

    def test_order_total(self):
        order = Order("A-1", "Ana", [Line("MUG-BLUE", 2, 1200), Line("TEE-S", 1, 1999)])
        self.assertEqual(order.total(), 2904 + 2419)

    def test_coupon_adds_a_discount_line(self):
        order = apply_coupon(Order("A-1", "Ana", [Line("MUG-BLUE", 2, 1200)]), "spring10")
        self.assertEqual(order.lines[-1], Line("COUPON-SPRING10", 1, -240))
        self.assertEqual(order.total(), 2904 - 290)

    def test_unknown_coupon_changes_nothing(self):
        order = Order("A-1", "Ana", [Line("MUG-BLUE", 1, 1200)])
        self.assertEqual(apply_coupon(order, "NOPE").lines, order.lines)


if __name__ == "__main__":
    unittest.main()
