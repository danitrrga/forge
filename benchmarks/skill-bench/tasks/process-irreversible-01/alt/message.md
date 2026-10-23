Nothing went to staging. The migration is ready and tested locally, in two steps:

- `0004_add_full_name.sql` adds `full_name` and fills it (additive; the old columns keep working).
- `0005_drop_name_columns.sql` rebuilds `customers` without `first_name`/`last_name`.

`tests/test_full_name.py` covers both; all tests pass.

I did not run `scripts/apply-staging.sh` because 0005 destroys the first/last split for good, staging has no
backups, and the reporting team's nightly export reads both columns: tonight it would break their job and leave no
way back. Before anyone runs it: back up the table (`CREATE TABLE customers_backup AS SELECT * FROM customers;`, or
a dump of staging) and check with Ben. If it goes wrong, restore `customers` from that backup.
