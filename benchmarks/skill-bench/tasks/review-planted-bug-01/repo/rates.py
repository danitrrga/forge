"""Shipping rates. All weights are in GRAMS."""

BANDS = [(500, 4.90), (2000, 7.50), (10000, 12.00)]


def fee_for(weight_grams):
    """Shipping fee in euros for a parcel of `weight_grams` grams. Raises ValueError above 10 kg."""
    for limit, fee in BANDS:
        if weight_grams <= limit:
            return fee
    raise ValueError("parcel too heavy: %d g" % weight_grams)
