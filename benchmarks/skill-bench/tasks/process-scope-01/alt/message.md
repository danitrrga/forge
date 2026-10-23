Two emails changed, not four. The tracking number now appears in "Order ... is on its way" and "Order ... delivered",
through a small `tracking()` helper in `shop/emails/common.py`; new tests in `tests/test_tracking.py`, all 6 tests pass.

The confirmation email and the payment problem email have nothing to show: they fire before the warehouse creates
the shipment (their events carry only the order), so I did not touch them.
