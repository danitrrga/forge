import unittest

from sensors.readings import is_rising, last_drop


class IsRisingTest(unittest.TestCase):
    def test_rising(self):
        self.assertTrue(is_rising([1, 2, 5]))

    def test_not_rising(self):
        self.assertFalse(is_rising([1, 5, 2]))


class LastDropTest(unittest.TestCase):
    def test_no_drop(self):
        self.assertEqual(last_drop([1, 2, 3]), -1)
        self.assertEqual(last_drop([1, 2, 4, 5]), -1)

    def test_empty(self):
        self.assertEqual(last_drop([]), -1)


if __name__ == '__main__':
    unittest.main()
