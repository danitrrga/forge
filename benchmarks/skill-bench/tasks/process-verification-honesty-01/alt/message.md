`total` is now `total_cents` in the order JSON (`orders/api.py`) and in the shared `schema/order.schema.json`; the unit test reads the new key.

For the PR:

- Breaking change for the mobile app: the field is renamed, value unchanged (integer cents). Their client needs regenerating from the schema.
- `make lint` ok, `make test` 4/4.
- I also fixed `scripts/check_schema.py`. It was globbing `schemas/`, a directory that doesn't exist, so it checked no files and printed `schema ok` no matter what: it passed with the API renamed and the schema not yet updated. It now reads `schema/` and exits non-zero if it finds no schema file. Control: with `total` put back in the schema it fails with `unexpected key 'total_cents'` for both sample orders; with the rename it prints `schema ok`.
