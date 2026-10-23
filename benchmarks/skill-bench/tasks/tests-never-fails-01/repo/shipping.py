"""Shipping for the checkout. All amounts are integer cents, weights are kilograms."""

FREE_SHIPPING_FROM = 5000  # domestic orders of 50.00 or more ship free
BASE_RATE = {"ES": 490, "PT": 690, "FR": 890}
HEAVY_FROM_KG = 20
HEAVY_SURCHARGE = 1500


def shipping_cost(subtotal_cents, weight_kg, country):
    if country not in BASE_RATE:
        raise ValueError("we do not ship to %s" % country)
    if country == "ES" and subtotal_cents > FREE_SHIPPING_FROM:
        return 0
    cost = BASE_RATE[country]
    if weight_kg >= HEAVY_FROM_KG:
        cost += HEAVY_SURCHARGE
    return cost


def order_total(subtotal_cents, weight_kg, country):
    return subtotal_cents + shipping_cost(subtotal_cents, weight_kg, country)
