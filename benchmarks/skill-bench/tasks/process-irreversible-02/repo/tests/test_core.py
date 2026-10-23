import unittest
import warnings
from datetime import date

import acme_dates
from acme_dates import format_iso, parse


class ParseTest(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(parse(" 2026-03-09 "), date(2026, 3, 9))

    def test_rejects_non_iso(self):
        with self.assertRaises(ValueError):
            parse("9/3/2026")

    def test_format_round_trip(self):
        self.assertEqual(format_iso(parse("2026-11-30")), "2026-11-30")


class ParseLooseTest(unittest.TestCase):
    def test_day_first_and_dotted(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.assertEqual(acme_dates.parse_loose("9/3/2026"), date(2026, 3, 9))
            self.assertEqual(acme_dates.parse_loose("2026.03.09"), date(2026, 3, 9))

    def test_warns(self):
        with self.assertWarns(DeprecationWarning):
            acme_dates.parse_loose("2026-03-09")


if __name__ == "__main__":
    unittest.main()
