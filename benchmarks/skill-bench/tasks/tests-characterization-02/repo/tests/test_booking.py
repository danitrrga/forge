import unittest
from datetime import date

from booking import validate


class ValidateTest(unittest.TestCase):
    def test_good_form(self):
        self.assertEqual(validate({"arrive": "2026-07-01", "leave": "2026-07-04"}, date(2026, 6, 1)), [])

    def test_departure_before_arrival(self):
        errors = validate({"arrive": "2026-07-04", "leave": "2026-07-01"}, date(2026, 6, 1))
        self.assertEqual(errors, ["Departure must be after arrival"])


if __name__ == "__main__":
    unittest.main()
