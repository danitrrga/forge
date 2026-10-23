# acme-orders

Serializes orders for the Acme mobile app.

- `orders/api.py` turns an `Order` into the JSON the app reads.
- `schema/order.schema.json` is the contract we share with the mobile team. Their client is generated
  from it, so the serializer and the schema must always agree.

## Checks

```
make lint     # byte-compiles every module
make test     # unit tests
make schema   # validates the serializer's output for the sample orders against the shared schema
make check    # all three; CI runs this on every PR
```
