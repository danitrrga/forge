from orders.model import Line, Order


def sample_orders():
    return [
        Order("o-1001", "Ana", "paid", [Line("TEA-01", 2, 450), Line("MUG-02", 1, 1299)]),
        Order("o-1002", "Ben", "pending", []),
    ]
