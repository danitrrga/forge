# acme-sales-report

The monthly sales report finance reads. `python3 report.py` reads `data/sales.csv` and writes
`dist/report.html`.

- Amounts are integer cents. A refund is a row with `kind` = `refund` and a negative amount.
- `money.fmt_money` formats every amount in the report.

```
python3 report.py
python3 -m unittest discover -s tests -t .
```
