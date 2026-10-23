import unittest

from tab.split import split_evenly


class SplitEvenlyTest(unittest.TestCase):
    def test_divides_exactly(self):
        self.assertEqual(split_evenly("10.00", ["Ana", "Ben", "Cleo", "Dan"]),
                         {"Ana": "2.50", "Ben": "2.50", "Cleo": "2.50", "Dan": "2.50"})

    def test_one_person_pays_everything(self):
        self.assertEqual(split_evenly("42.10", ["Ana"]), {"Ana": "42.10"})


if __name__ == '__main__':
    unittest.main()
