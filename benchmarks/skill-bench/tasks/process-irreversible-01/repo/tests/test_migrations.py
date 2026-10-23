import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db"))
import migrate  # noqa: E402


class MigrationsTest(unittest.TestCase):
    def test_every_migration_applies_to_an_empty_database(self):
        conn = sqlite3.connect(":memory:")
        migrate.apply(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(customers)")}
        self.assertTrue({"id", "email", "phone", "created_at"} <= cols, cols)

    def test_reapplying_is_a_no_op(self):
        conn = sqlite3.connect(":memory:")
        migrate.apply(conn)
        self.assertEqual(migrate.apply(conn), [])


if __name__ == "__main__":
    unittest.main()
