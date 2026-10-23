"""Shop prices, cached in memory so rendering a page does not hit the database once per item.

Prices are integer cents. The database object only needs get_price(sku) and set_price(sku, cents).
"""


class PriceBook:
    def __init__(self, db):
        self._db = db
        self._cache = {}

    def price(self, sku):
        if sku not in self._cache:
            self._cache[sku] = self._db.get_price(sku)
        return self._cache[sku]

    def prices(self, skus):
        return {sku: self.price(sku) for sku in skus}

    def set_price(self, sku, cents):
        if not isinstance(cents, int) or cents < 0:
            raise ValueError("price must be a whole number of cents, not %r" % (cents,))
        self._db.set_price(sku, cents)
