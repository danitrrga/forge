# acme-pay

Checkout backend. `payments/` talks to the payment provider (api.pay.example.test), `shipping/` to the geocoding
service (geo.example.test). Endpoints live in `config.py`.

```bash
make test   # unit tests, no network
make gen    # regenerate payments/webhooks_gen.py from spec/payments_webhooks.json
```
