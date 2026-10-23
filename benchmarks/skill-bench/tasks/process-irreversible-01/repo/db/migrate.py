"""Apply db/migrations/*.sql in name order to a local SQLite database:  python3 db/migrate.py dev.db"""
import os
import sqlite3
import sys

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def apply(conn):
    """Apply every migration not yet recorded in schema_migrations; returns the names applied."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for name in sorted(f for f in os.listdir(DIR) if f.endswith(".sql")):
        if name in done:
            continue
        with open(os.path.join(DIR, name)) as fh:
            conn.executescript(fh.read())
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (name,))
        conn.commit()
        applied.append(name)
    return applied


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: migrate.py DB_FILE")
    for name in apply(sqlite3.connect(sys.argv[1])):
        print("applied", name)
