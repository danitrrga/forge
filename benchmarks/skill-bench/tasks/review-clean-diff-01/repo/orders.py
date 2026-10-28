"""Order totals."""
from rates import fee_for


def order_total(items):
    """items: list of dicts with price (euros), qty and weight_kg per unit."""
    subtotal = sum(i["price"] * i["qty"] for i in items)
    weight_kg = sum(i["weight_kg"] * i["qty"] for i in items)
    return round(subtotal + fee_for(weight_kg * 1000), 2)
