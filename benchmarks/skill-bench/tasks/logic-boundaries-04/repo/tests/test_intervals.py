import unittest

from katas.intervals import intersection


class IntersectionTest(unittest.TestCase):
    def test_disjoint(self):
        self.assertEqual(intersection((1, 2), (3, 5)), "NO")

    def test_one_inside_the_other(self):
        self.assertEqual(intersection((-3, -1), (-5, 5)), "YES")


if __name__ == '__main__':
    unittest.main()
