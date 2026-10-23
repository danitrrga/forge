Renamed `total` to `total_cents` in `orders/api.py` and `schema/order.schema.json`, and updated the test.

PR summary:
- Order JSON field `total` renamed to `total_cents` (still integer cents) so the mobile team stops reading it as euros.
- `make check` passes: lint ok, 4 tests ok, schema ok. The serializer and the shared schema agree.
