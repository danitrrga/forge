"""Shipping rates. All weights are in GRAMS."""

BANDS = [(500, 4.90), (2000, 7.50), (10000, 12.00)]
OVER_10_KG = 18.00


def fee_for(weight_grams):
    """Shipping fee in euros for a parcel of `weight_grams` grams. Parcels over 10 kg pay a flat 18.00."""
    for limit, fee in BANDS:
        if weight_grams <= limit:
            return fee
    return OVER_10_KG
