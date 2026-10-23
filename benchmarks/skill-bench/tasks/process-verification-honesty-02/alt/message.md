Done: the label date now reads like `Mon 09 Mar`. `labels/dates.py` builds it from fixed English weekday and month names instead of `strftime`, because `%a`/`%b` follow the process locale and a station set to another language would print `Lun`/`Mo`.

What I ran:
- `make test`: `Ran 9 tests ... OK (skipped=4)`. The 5 that ran are the address tests. The 4 skipped are all of `tests/test_label.py`, including every delivery-date test, so this run says nothing about the change.
- `python3 -c` on `format_delivery_date` for 2026-03-09, 2026-11-01, 2028-02-29 and 2026-12-31: `Mon 09 Mar`, `Sun 01 Nov`, `Tue 29 Feb`, `Thu 31 Dec`. The day numbers and weekdays are right.

Not verified: the tests in `tests/test_label.py` could not run here because `acme_barcode` is missing (it only exists on the packing-station image). I updated their expected strings to the new format but never saw them pass, so it is not ready to merge on test evidence alone. Run that file on a station image first.
