"""Admin back office: staff type prices in euros ("9.00", "12,50")."""
from decimal import Decimal, InvalidOperation


def change_price(book, sku, euros):
    try:
        cents = Decimal(euros.strip().replace(",", ".")) * 100
    except InvalidOperation:
        raise ValueError("not a price: %r" % euros)
    if cents != cents.to_integral_value():
        raise ValueError("more than two decimals: %r" % euros)
    book.set_price(sku, int(cents))
