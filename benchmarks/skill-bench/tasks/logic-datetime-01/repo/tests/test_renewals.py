import unittest
from datetime import date

from subscriptions.renewals import add_months, next_renewal, renewal_dates


class AddMonthsTest(unittest.TestCase):
    def test_one_month(self):
        self.assertEqual(add_months(date(2024, 1, 15), 1), date(2024, 2, 15))


class RenewalDatesTest(unittest.TestCase):
    def test_mid_month_start(self):
        self.assertEqual(renewal_dates(date(2024, 1, 10), 3),
                         [date(2024, 2, 10), date(2024, 3, 10), date(2024, 4, 10)])

    def test_no_renewals(self):
        self.assertEqual(renewal_dates(date(2024, 1, 10), 0), [])


class NextRenewalTest(unittest.TestCase):
    def test_next_after_today(self):
        self.assertEqual(next_renewal(date(2024, 3, 5), date(2024, 5, 20)), date(2024, 6, 5))


if __name__ == '__main__':
    unittest.main()
