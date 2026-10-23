The dead-code step flagged four functions: one false positive and three real candidates, which I have not deleted.

Fixed the false positive: `export_ledger_csv` (`billing/exports.py`) is live. `scheduler.py` runs it by name from
`jobs.json` as the `nightly-ledger` job (cron 02:15), which the AST check cannot see. It is now in
`tools/deadcode-allow.txt` with that reason.

Candidates for deletion, with what I found (searched the code, the tests, `jobs.json` and string literals):

- `_render_fax_cover` (`billing/invoices.py:15`): no reference anywhere.
- `vat_table_2019` (`billing/tax.py:22`): no reference anywhere. Its docstring says it is for re-issuing pre-2020
  invoices, so someone may still call it by hand.
- `rate_from_string` (`billing/tax.py:14`): only `tests/test_tax.py` uses it; deleting it means deleting that test.

`make check` stays red on these three until you decide; the unit tests pass. OK to delete all three, together with
the `rate_from_string` test?
