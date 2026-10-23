import unittest

from payroll.shifts import shift_end, shift_hours, week_hours


class ShiftHoursTest(unittest.TestCase):
    def test_day_shift(self):
        self.assertEqual(shift_hours("2026-06-10 09:00", "2026-06-10 17:00"), 8)

    def test_night_shift_over_midnight(self):
        self.assertEqual(shift_hours("2026-01-10 22:00", "2026-01-11 06:00"), 8)


class ShiftEndTest(unittest.TestCase):
    def test_day_shift(self):
        self.assertEqual(shift_end("2026-06-10 09:00", 8), "2026-06-10 17:00")

    def test_half_hours(self):
        self.assertEqual(shift_end("2026-06-10 09:00", 7.5), "2026-06-10 16:30")


class WeekHoursTest(unittest.TestCase):
    def test_sum(self):
        self.assertEqual(week_hours([("2026-06-10 09:00", "2026-06-10 17:00"),
                                     ("2026-06-11 09:00", "2026-06-11 13:30")]), 12.5)


if __name__ == '__main__':
    unittest.main()
