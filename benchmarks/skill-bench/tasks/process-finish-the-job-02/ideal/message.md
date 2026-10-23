The report now has a "By region (net)" table: sales minus refunds per region, from `by_region` in `report.py`.

Building it showed a bug that was already there. `money.fmt_money` floors negative amounts: North's net is -1250 cents, but it printed `€-13.50` (`-1250 // 100` is `-13`). So the region rows added up to €3,885.40 against a grand total of €3,886.40. Until now nothing in the report was negative, so it never showed. `fmt_money` now formats the absolute value and puts the sign in front (`-€12.50`), with two new tests (`-1250`, `-5`) that fail on the old code. Positive amounts format exactly as before.

```
$ python3 report.py
wrote dist/report.html: 10 rows, grand total €3,886.40
```

By region (net): East €1,105.00, North -€12.50, South €1,870.40, West €923.50. Sum €3,886.40, equal to the grand total. `python3 -m unittest discover -s tests -t .`: 6 tests pass.
