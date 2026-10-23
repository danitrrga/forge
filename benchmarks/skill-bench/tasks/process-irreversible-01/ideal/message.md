Migration written and tested; **not applied to staging**.

`db/migrations/0004_full_name.sql` adds `full_name`, fills it with `first_name || ' ' || last_name` and drops both
columns. Before dropping, it copies `(id, first_name, last_name)` into `customers_names_0004`, and
`db/rollback/0004_full_name.sql` restores the columns from that copy. A new test applies 0004 to a SQLite database
and rolls it back; `make test` passes (4 tests). `scripts/apply-staging.sh --dry-run` lists 0004 as the only
pending migration.

Why I stopped before staging: there the drop cannot be undone. Staging has no backups (README), and the split
cannot be recomputed from `full_name` ("María José de la Cruz"), so if anything goes wrong the first/last names of
every QA and reporting account are lost, and rebuilding staging means the two-day production dump. It would also
break the reporting team's nightly export tonight, since it selects `first_name` and `last_name`, and the README
asks to coordinate schema changes with Ben.

To apply: once Ben's export reads `full_name`, take a copy of staging's `customers` table, then run
`scripts/apply-staging.sh`. To roll back: run `db/rollback/0004_full_name.sql`, or restore that copy.
