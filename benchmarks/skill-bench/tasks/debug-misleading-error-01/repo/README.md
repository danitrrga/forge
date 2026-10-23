# acme invoicing

    python3 run_invoices.py            # reads settings.ini
    python3 -m unittest

## settings.ini

A `[billing]` section with one `key = value` per line:

| key | meaning |
|---|---|
| `currency` | ISO code printed before amounts |
| `tax_rate` | VAT as a fraction, e.g. `0.21` |
| `late_fee_rate` | fraction of the amount charged per month late |
| `net_days` | days from issue to due date |

Anything after `;` or `#` is a comment, on a line of its own or after a value.
