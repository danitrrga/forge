"""SQLite access for the shop. DB_PATH can be pointed elsewhere (tests use a temp file)."""
import os
import sqlite3

DB_PATH = os.environ.get("SHOP_DB", "shop.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer TEXT NOT NULL,
    total_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
)
"""


def connect():
    """A new connection. Use it as `with connect() as conn:` so the work is committed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_intake = None


def intake():
    """One long-lived connection for order intake, which is the hot path: no reconnect per order."""
    global _intake
    if _intake is None:
        _intake = connect()
    return _intake


def init():
    with connect() as conn:
        conn.execute(SCHEMA)
