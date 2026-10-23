Added a "By region (net)" table to `report.py`: `by_region` sums each region's sales and refunds and the table is rendered with the existing `table` helper and `fmt_money`, under the monthly table.

Run `python3 report.py` to regenerate `dist/report.html`; the region totals are computed from the same rows as the grand total, so they add up.
