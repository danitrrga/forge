import unittest
from datetime import date

from shop import events
from shop.emails import render

ORDER = events.Order(id="A-1001", customer_name="Ana Lopez", email="ana@example.test", total_cents=4250)
SHIPMENT = events.Shipment(carrier="ParcelCo", tracking_number="PC-1000-0001")


class EmailTest(unittest.TestCase):
    def test_placed(self):
        subject, body = render(events.OrderPlaced(ORDER))
        self.assertEqual(subject, "Order A-1001 confirmed")
        self.assertIn("EUR 42.50", body)
        self.assertTrue(body.startswith("Hi Ana,"))

    def test_payment_failed(self):
        subject, body = render(events.PaymentFailed(ORDER, "card declined"))
        self.assertEqual(subject, "Payment problem with order A-1001")
        self.assertIn("card declined", body)

    def test_shipped(self):
        subject, body = render(events.OrderShipped(ORDER, SHIPMENT))
        self.assertEqual(subject, "Order A-1001 is on its way")
        self.assertIn("ParcelCo", body)

    def test_delivered(self):
        subject, body = render(events.OrderDelivered(ORDER, SHIPMENT, date(2026, 3, 9)))
        self.assertEqual(subject, "Order A-1001 delivered")
        self.assertIn("09 Mar 2026", body)


if __name__ == "__main__":
    unittest.main()
