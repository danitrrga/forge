import unittest

from admin import change_price
from db import PriceDB
from pricebook import PriceBook
from shop import price_list


class CountingDB:
    def __init__(self, prices):
        self.prices = dict(prices)
        self.reads = 0

    def get_price(self, sku):
        self.reads += 1
        return self.prices[sku]

    def set_price(self, sku, cents):
        self.prices[sku] = cents


class PriceBookTest(unittest.TestCase):
    def test_price_comes_from_the_database_once(self):
        db = CountingDB({"MUG-BLUE": 1200})
        book = PriceBook(db)
        self.assertEqual(book.price("MUG-BLUE"), 1200)
        self.assertEqual(book.price("MUG-BLUE"), 1200)
        self.assertEqual(db.reads, 1)

    def test_set_price_writes_to_the_database(self):
        db = CountingDB({"MUG-BLUE": 1200})
        PriceBook(db).set_price("MUG-BLUE", 900)
        self.assertEqual(db.prices["MUG-BLUE"], 900)

    def test_negative_or_fractional_prices_are_rejected(self):
        book = PriceBook(CountingDB({}))
        for bad in (-1, 9.5):
            with self.assertRaises(ValueError):
                book.set_price("MUG-BLUE", bad)


class AdminAndShopTest(unittest.TestCase):
    def test_change_price_from_euros(self):
        db = PriceDB()
        change_price(PriceBook(db), "MUG-BLUE", "12,50")
        self.assertEqual(db.get_price("MUG-BLUE"), 1250)

    def test_price_list(self):
        book = PriceBook(CountingDB({"MUG-BLUE": 1200, "TEE-S": 1999}))
        self.assertEqual(price_list(book, ["MUG-BLUE", "TEE-S"]).splitlines(),
                         ["MUG-BLUE        12.00", "TEE-S           19.99"])


if __name__ == "__main__":
    unittest.main()
