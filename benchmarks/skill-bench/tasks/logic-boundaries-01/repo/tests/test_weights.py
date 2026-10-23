import unittest

from textscore.weights import heaviest_substring, total_weight


class HeaviestSubstringTest(unittest.TestCase):
    def test_docstring_example(self):
        self.assertEqual(heaviest_substring('abc', {'a': 10, 'b': -5, 'c': 3}), 'a')

    def test_negative_middle_splits(self):
        self.assertEqual(heaviest_substring('aabc', {'a': 10, 'b': -5, 'c': 3}), 'aa')

    def test_all_negative_picks_least_negative(self):
        self.assertEqual(heaviest_substring('ab', {'a': -1, 'b': -3}), 'a')


class TotalWeightTest(unittest.TestCase):
    def test_unknown_characters_weigh_zero(self):
        self.assertEqual(total_weight('ax', {'a': 2}), 2)


if __name__ == '__main__':
    unittest.main()
