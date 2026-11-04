---
{
  "size": {
    "tag": "small",
    "parts": 1,
    "agents": 1
  },
  "criteria": [
    {
      "id": "C1",
      "text": "The total counts every entry: 5, 7 and 2 give 14.",
      "measure": "`python3 tests/fixtures/critique/apps/tally/tests/test_tally.py` exits 0 (it prints `FAIL: total of 5, 7 and 2: got 12, want 14` today)."
    },
    {
      "id": "C2",
      "text": "A tally with no entries yet prints a total of 0 and does not fail.",
      "measure": "`python3 tests/fixtures/critique/apps/tally/tally.py total`, run in a folder where the tally has never been used, prints 0 and exits 0."
    }
  ],
  "tasks": [
    {
      "id": "T1",
      "part": 1,
      "type": "bug",
      "wave": 1,
      "files": [
        "tests/fixtures/critique/apps/tally/tally.py"
      ],
      "depends_on": [],
      "tests": [
        {
          "run": "python3 tests/fixtures/critique/apps/tally/tests/test_tally.py",
          "measures": "the total of three added amounts",
          "red": "against the current tally.py: FAIL: total of 5, 7 and 2: got 12, want 14"
        }
      ],
      "size": "small",
      "ui": false
    }
  ],
  "not_built": [
    {
      "what": "a change to how the entries are stored",
      "why": "nothing asked for it."
    }
  ],
  "later": []
}
---

## Goal
Make the tally's total count every entry.

## Approach
T1 removes the slice that drops the last entry: the line `tests/fixtures/critique/apps/tally/tally.py:34` sums `entries[:-1]` and has to sum `entries` (D1). Nothing else in `tally.py` changes.

`total()` already returns 0 when the store is empty: it loads the stored list, and the sum of an empty list is 0, so a tally nobody has added to yet needs no change to meet D2. C2 is measured by running `total` in a new folder, and T1 adds no test of its own for it.

## Size
Small: one line of one file. One part, one agent.
