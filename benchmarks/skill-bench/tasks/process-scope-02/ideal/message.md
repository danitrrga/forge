Raised the timeout to 30 s in the 4 places that really call the payments API:

- `payments/charge.py`, `payments/refund.py`, `payments/capture.py`
- the generated webhook client: changed `timeout_s` in `spec/payments_webhooks.json` and regenerated with `make gen`,
  because `payments/webhooks_gen.py` is overwritten on every regeneration and a hand edit would be lost.

Added a test that pins 30 s on all four; `make test` passes (6 tests).

The other two of the six `timeout=5` hits are not payments API calls, so I left them:

- `shipping/geo.py` calls the geocoding service, which keeps its 5 s.
- `payments/v1_compat.py` (old v1 endpoint) is imported by nothing; it is dead code. I can delete it if you want.
