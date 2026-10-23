import os
import tempfile
import unittest

from shop import db, orders


class OrdersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "shop.sqlite3")
        db._intake = None
        db.init()

    def tearDown(self):
        if db._intake is not None:
            db._intake.close()
            db._intake = None
        self.tmp.cleanup()

    def test_add_order(self):
        order_id = orders.add_order("Ana", 1250)
        self.assertIsNotNone(order_id)

    def test_ship_order(self):
        order_id = orders.add_order("Ben", 4000)
        orders.mark_shipped(order_id)
        self.assertEqual(orders.get_order(order_id)["status"], "shipped")


if __name__ == "__main__":
    unittest.main()
