from shop import db


def add_order(customer, total_cents):
    cur = db.intake().execute(
        "INSERT INTO orders (customer, total_cents) VALUES (?, ?)", (customer, total_cents)
    )
    return cur.lastrowid


def mark_shipped(order_id):
    with db.connect() as conn:
        conn.execute("UPDATE orders SET status = 'shipped' WHERE id = ?", (order_id,))


def get_order(order_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None
