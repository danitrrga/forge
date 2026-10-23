Added the tracking number to the shipped and delivered emails (`shop/emails/shipped.py`, `shop/emails/delivered.py`)
and extended their tests; `make test` passes (4 tests).

Only 2 of the 4 order emails can carry it. The order confirmation (`placed.py`) and the payment-failed email are sent
before any parcel exists: `OrderPlaced` and `PaymentFailed` in `shop/events.py` have no `Shipment`, so there is no
tracking number to show. I left those two unchanged.
