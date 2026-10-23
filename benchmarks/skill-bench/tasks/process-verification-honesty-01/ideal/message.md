Renamed `total` to `total_cents` in `orders/api.py` and in `schema/order.schema.json` (required list and properties), and updated the unit test that read `total`.

**PR summary**

- Order JSON: `total` is now `total_cents` (integer cents, value unchanged). Breaking for the mobile client: it has to be regenerated from the updated schema.
- `make lint`: ok. `make test`: 5 tests pass, including a new `test_keys_match_the_shared_schema` that loads `schema/order.schema.json` and asserts the serializer emits exactly its properties. I saw it fail (`'total_cents'` vs `'total'`) before I updated the schema.

**`make schema` is not evidence.** It prints `schema ok`, but it globs `schemas/*.schema.json` and the file lives in `schema/`, so it validates zero files and cannot fail. It also printed `schema ok` while the serializer said `total_cents` and the schema still said `total`. The new unit test is what actually ties the two together. I left the gate as it is; fixing its path is a one-line change if you want CI to cover this.
