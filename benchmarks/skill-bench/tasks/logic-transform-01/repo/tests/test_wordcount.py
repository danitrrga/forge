import unittest

from subtitles.wordcount import count_words, top_words


class CountWordsTest(unittest.TestCase):
    def test_one_word(self):
        self.assertEqual(count_words("word"), {"word": 1})

    def test_cramped_list(self):
        self.assertEqual(count_words("one,two,three"), {"one": 1, "two": 1, "three": 1})

    def test_numbers(self):
        self.assertEqual(count_words("testing, 1, 2 testing"), {"testing": 2, "1": 1, "2": 1})

    def test_case(self):
        self.assertEqual(count_words("go Go GO Stop stop"), {"go": 3, "stop": 2})

    def test_contractions(self):
        self.assertEqual(
            count_words("First: don't laugh. Then: don't cry."),
            {"first": 1, "don't": 2, "laugh": 1, "then": 1, "cry": 1},
        )


class TopWordsTest(unittest.TestCase):
    def test_most_frequent_first(self):
        self.assertEqual(top_words("one fish two fish red fish blue fish", 2), ["fish", "one"])


if __name__ == '__main__':
    unittest.main()
