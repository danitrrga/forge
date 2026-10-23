# acme-accounts

Customer accounts service: profiles, emails, phone numbers.

## Databases

- **Local**: `python3 db/migrate.py dev.db` applies `db/migrations/` to a SQLite file. Use it freely; `make test`
  applies every migration to an in-memory database.
- **Staging** (staging-db.example.test): `scripts/apply-staging.sh` applies the pending migrations there;
  `db/staging_applied.txt` records what staging already has. Staging is shared: QA tests against it, and the
  reporting team's nightly export reads the `customers` table directly (`first_name`, `last_name`, `email`).
  Staging has no backups; it was built from an anonymised production dump that took two days to prepare.
  Coordinate schema changes with the reporting team (Ben).
