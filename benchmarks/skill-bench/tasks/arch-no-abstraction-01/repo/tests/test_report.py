import unittest

from report import render_text, summarize


class ReportTest(unittest.TestCase):
    def test_summarize_groups_and_sorts(self):
        orders = [{"customer": "B", "amount_cents": 100}, {"customer": "A", "amount_cents": 300},
                  {"customer": "B", "amount_cents": 250}]
        self.assertEqual(summarize(orders), [("B", 2, 350), ("A", 1, 300)])

    def test_render_text(self):
        self.assertEqual(render_text([("Acme", 2, 123456)]).splitlines()[1],
                         "Acme                          2     1,234.56")


if __name__ == "__main__":
    unittest.main()
