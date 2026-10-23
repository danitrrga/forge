import random
import unittest

from booking.intervals import busy_minutes, free_slots, merge


def covered(ranges):
    """Brute-force model of the union: every half-minute point inside some range."""
    points = set()
    for start, end in ranges:
        points.update(range(2 * start, 2 * end + 1))
    return points


class MergeTest(unittest.TestCase):
    def test_overlapping(self):
        self.assertEqual(merge([(540, 600), (570, 630)]), [(540, 630)])

    def test_touching(self):
        self.assertEqual(merge([(540, 600), (600, 660)]), [(540, 660)])

    def test_disjoint_unsorted(self):
        self.assertEqual(merge([(700, 720), (540, 600)]), [(540, 600), (700, 720)])

    def test_random_days(self):
        for _ in range(10):
            starts = [random.randrange(480, 1080, 15) for _ in range(3)]
            bookings = [(s, s + random.choice([15, 30, 45, 60])) for s in starts]
            merged = merge(bookings)
            self.assertEqual(len(covered(merged)), len(covered(bookings)))


class FreeSlotsTest(unittest.TestCase):
    def test_free_slots(self):
        self.assertEqual(free_slots([(540, 600), (720, 780)]), [(480, 540), (600, 720), (780, 1080)])

    def test_busy_minutes(self):
        self.assertEqual(busy_minutes([(540, 600), (570, 630)]), 90)


if __name__ == "__main__":
    unittest.main()
