"""The price table. Production uses SQLite; tests can pass any object with the same two methods."""
import sqlite3


class PriceDB:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS prices (sku TEXT PRIMARY KEY, cents INTEGER NOT NULL)")

    def get_price(self, sku):
        row = self.conn.execute("SELECT cents FROM prices WHERE sku = ?", (sku,)).fetchone()
        if row is None:
            raise KeyError(sku)
        return row[0]

    def set_price(self, sku, cents):
        self.conn.execute("INSERT INTO prices (sku, cents) VALUES (?, ?) "
                          "ON CONFLICT(sku) DO UPDATE SET cents = excluded.cents", (sku, cents))
        self.conn.commit()
