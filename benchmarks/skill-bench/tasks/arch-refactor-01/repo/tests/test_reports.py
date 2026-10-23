import unittest

from reports import payouts_csv, refunds_csv, sales_csv

ROWS = [
    {"date": "2026-03-01", "customer": "Ana Ruiz", "amount_cents": 1250},
    {"date": "2026-03-02", "customer": "Acme, Inc.", "amount_cents": 99900},
    {"date": "2026-03-02", "customer": "Ben", "amount_cents": 0},
]


class ReportsTest(unittest.TestCase):
    def test_sales(self):
        self.assertEqual(sales_csv(ROWS).splitlines(), [
            "date,customer,amount",
            "2026-03-01,Ana Ruiz,12.50",
            '2026-03-02,"Acme, Inc.",999.00',
            "2026-03-02,Ben,0.00",
        ])

    def test_refunds_are_negative(self):
        self.assertEqual(refunds_csv(ROWS[:1]).splitlines()[1], "2026-03-01,Ana Ruiz,-12.50")

    def test_payouts_skip_zero_amounts(self):
        self.assertEqual(len(payouts_csv(ROWS).splitlines()), 3)

    def test_quotes_in_names_are_doubled(self):
        rows = [{"date": "2026-03-03", "customer": 'Cy "the boss" Park', "amount_cents": 100}]
        self.assertEqual(sales_csv(rows).splitlines()[1], '2026-03-03,"Cy ""the boss"" Park",1.00')


if __name__ == "__main__":
    unittest.main()
