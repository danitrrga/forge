Labels now print the weekday: `format_delivery_date` in `labels/dates.py` uses `%a %d %b`, so 9 March 2026 prints `Mon 09 Mar`.

**Ran:** `make test` → `Ran 10 tests, OK (skipped=2)`. The date tests used to live in `tests/test_label.py`, where they were skipped here along with everything else in that file, so `make test` said OK without running a single date test. They don't need the SDK, so I moved them to `tests/test_dates.py` (weekday, zero-padded day, leap day). They now run, and against the old formatter they fail (`'09 Mar' != 'Mon 09 Mar'`).

**Not run:** the 2 tests left in `tests/test_label.py` (`test_label_fields`, `test_render_encodes_the_reference`) are skipped because `acme_barcode` isn't installed on this machine. It only ships with the packing-station image. I updated `test_label_fields` to expect `Mon 09 Mar`, but I haven't seen it run, so the printed label itself is unverified.

Ready to merge as far as the date text goes. Before it goes out, run the test suite once on a station image, where `acme_barcode` exists, to cover the rendering.
