Not ready. `order_total` passes kilograms to `rates.fee_for`, which expects grams, so every parcel is priced as under 500 g (4.90) and the heavy bands and the too-heavy error are unreachable. Pass `weight_kg * 1000`. Review is in REVIEW.md.

VERDICT: request changes
