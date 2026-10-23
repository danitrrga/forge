import unittest

from checkout import euros


class EurosTest(unittest.TestCase):
    def test_formats_cents(self):
        self.assertEqual(euros(123456), "1234.56 EUR")
        self.assertEqual(euros(5), "0.05 EUR")


if __name__ == "__main__":
    unittest.main()
