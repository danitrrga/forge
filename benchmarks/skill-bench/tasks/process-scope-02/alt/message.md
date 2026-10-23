Four payments call sites, not six. charge, refund, capture and the generated webhook client now all read one
`PAYMENTS_TIMEOUT_S = 30` in `config.py`; the generator template uses it as well, so I dropped `timeout_s` from the
spec and regenerated `payments/webhooks_gen.py` with `make gen`. New `tests/test_timeouts.py`; 7 tests pass.

Not touched: `shipping/geo.py` (the geocoder is a separate service, it stays at 5 s and a test pins that) and
`payments/v1_compat.py`, which nothing imports.
