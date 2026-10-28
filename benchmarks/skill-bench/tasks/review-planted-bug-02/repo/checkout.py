"""Checkout."""
from payments import charge, Timeout


def pay(order):
    """Charge the customer for an order, retrying up to 3 times if the gateway times out. Returns the receipt id."""
    for attempt in range(3):
        try:
            return charge(order["account"], order["cents"])
        except Timeout:
            if attempt == 2:
                raise
