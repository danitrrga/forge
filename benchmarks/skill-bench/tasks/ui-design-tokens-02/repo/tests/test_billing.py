import datetime
import unittest

from pages import billing

ACCOUNT = {"name": "Northwind", "plan": "Team", "seats": 12, "plan_expires": datetime.date(2026, 11, 30),
           "monthly_total": "€96.00"}


class BillingPageTest(unittest.TestCase):
    def test_active_account(self):
        html = billing.render(ACCOUNT, datetime.date(2026, 10, 23))
        self.assertIn("Active", html)
        self.assertIn("30 Nov 2026", html)
        self.assertIn('href="/billing/plans"', html)

    def test_expired_badge(self):
        html = billing.render(ACCOUNT, datetime.date(2026, 12, 2))
        self.assertIn("Expired", html)


if __name__ == "__main__":
    unittest.main()
