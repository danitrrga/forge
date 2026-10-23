import unittest
from datetime import datetime, timedelta

from eventlog.parser import ParseError, parse_line


class ParseLineTest(unittest.TestCase):
    def test_hours_and_minutes(self):
        event = parse_line("2026-03-09 09:00 | Planning | 1h30m")
        self.assertEqual(event.start, datetime(2026, 3, 9, 9, 0))
        self.assertEqual(event.title, "Planning")
        self.assertEqual(event.duration, timedelta(minutes=90))

    def test_bad_date(self):
        with self.assertRaises(ParseError):
            parse_line("2026-03-32 09:00 | Planning | 1h30m")


if __name__ == "__main__":
    unittest.main()
