# Context: 01-bug-total

## Intent
"The total is wrong. I added 5, 7 and 2 and it says 12, it should say 14. It looks like the last thing I add never counts."

## What success means
After `python3 tally.py add 5`, `add 7` and `add 2`, `python3 tally.py total` prints 14. A tally with no entries yet prints 0, it does not fail. The test `tests/test_tally.py` passes.

## Surfaces
None.

## Approved UI
None.

## Research
Reproduction, from a folder with no `tally.json`:

    TALLY_FILE=/tmp/t.json python3 tests/fixtures/critique/apps/tally/tally.py add 5
    TALLY_FILE=/tmp/t.json python3 tests/fixtures/critique/apps/tally/tally.py add 7
    TALLY_FILE=/tmp/t.json python3 tests/fixtures/critique/apps/tally/tally.py add 2
    TALLY_FILE=/tmp/t.json python3 tests/fixtures/critique/apps/tally/tally.py total

prints 12. `python3 tests/fixtures/critique/apps/tally/tests/test_tally.py` prints `FAIL: total of 5, 7 and 2: got 12, want 14`.
