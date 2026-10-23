"""Checkout page: turns the cart into the summary the customer confirms."""
from billing import compute_total


def euros(cents):
    return "%d.%02d EUR" % divmod(cents, 100)


def summary(cart, code=None, country="ES", member=False):
    lines = [(item["sku"], item["qty"], item["unit_cents"]) for item in cart]
    totals = compute_total(lines, code=code, country=country, member=member)
    return {key: euros(value) for key, value in totals.items()}
