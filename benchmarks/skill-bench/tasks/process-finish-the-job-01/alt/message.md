`crm import` is in, and I ran it on `data/legacy_customers.csv`:

```
$ python3 -m crm import data/legacy_customers.csv
12 rows: 11 added, 1 already known (merged)
$ python3 -m crm list
...
14 customers
```

Two things in the file needed handling. It starts with a UTF-8 byte-order mark, which breaks the header lookup if you read it naively. And Ben Okafor was already a customer: his existing record had no phone number, so the merge filled it in from the export and left everything else alone. The reader lives in `crm/legacy.py`; it sniffs `;` vs `,` because Excel picks the separator by locale. Running the import a second time adds nobody (`12 rows: 0 added, 12 already known`).
