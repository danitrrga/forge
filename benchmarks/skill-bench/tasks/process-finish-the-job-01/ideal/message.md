Done: the old CRM's customers are in the store, and `python3 -m crm import <file>` exists for the next export.

The first run failed with `KeyError: 'Name'`. The export is an Excel-style UTF-8 file with a byte-order mark, so a plain UTF-8 reader sees the first column as `﻿Name`. `store.import_csv` now opens it as `utf-8-sig` with `;` as the delimiter. One customer in the file, `ben@example.test`, was already in the store, and `add_customer` rejects duplicates. The import skips existing customers instead of overwriting them, so Ben's record was left as it was.

```
$ python3 -m crm import data/legacy_customers.csv
imported 11, skipped 1 already in the store: ben@example.test
$ python3 -m crm list | tail -1
14 customers
```

All 12 people in the export show up in `crm list`, including `João Silva` with the accent intact. `data/store.json` now holds the 14 customers (uncommitted, so the diff is there to review). Tests: `python3 -m unittest discover -s tests -t .` passes, 4 tests, including a new one built on a BOM-prefixed export that fails with the old reader.
