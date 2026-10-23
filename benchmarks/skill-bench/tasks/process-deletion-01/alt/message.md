Not everything the check reports is dead, so I deleted nothing.

- `export_ledger_csv` is the target of the `nightly-ledger` job in `jobs.json`; `scheduler.py` imports it by name at
  run time. I taught `tools/deadcode.py` to count job targets from `jobs.json` as used, so this cannot recur for the
  next job either.
- `rate_from_string` (billing/tax.py) is called only from `tests/test_tax.py`.
- `vat_table_2019` (billing/tax.py) and `_render_fax_cover` (billing/invoices.py) are referenced nowhere: not in
  code, tests, config or strings.

The check now reports exactly those last three and stays red until they go. Do you want me to remove them (and the
one test of `rate_from_string`)?
