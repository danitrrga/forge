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
      "measure": "`TALLY_FILE=<a new temp folder>/t.db python3 tests/fixtures/critique/apps/tally/tally.py total` prints 0 and exits 0."
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
    },
    {
      "id": "T2",
      "part": 1,
      "type": "refactor",
      "wave": 2,
      "files": [
        "tests/fixtures/critique/apps/tally/tally.py",
        "tests/fixtures/critique/apps/tally/tests/test_tally.py"
      ],
      "depends_on": [
        "T1"
      ],
      "tests": [
        {
          "run": "python3 tests/fixtures/critique/apps/tally/tests/test_tally.py",
          "measures": "add, total and reset on the new store, and the total of an untouched store",
          "red": "against a tally.py that still reads tally.json: FAIL: entries kept after three adds: got [], want [5, 7, 2]"
        }
      ],
      "size": "small",
      "ui": false
    }
  ],
  "not_built": [],
  "later": []
}
---

## Goal
Make the tally's total count every entry, and make a tally nobody has added to yet report 0.

## Approach
T1 removes the slice that drops the last entry: the line `tests/fixtures/critique/apps/tally/tally.py:34` sums `entries[:-1]` and has to sum `entries` (D1). With that one change the three added amounts give 14.

T2 then changes how the entries are kept. Today `load()` opens a JSON file that does not exist until the first add, which is why a new tally cannot report a total (D2). T2 moves the entries into a table `entries` of a single-file embedded SQL database through the standard library, so the file and the table are created on first use and `total()` becomes one `SELECT COALESCE(SUM(amount), 0)`. `add`, `total` and `reset` keep their command line; `tests/test_tally.py` is rewritten to run against the database file.

## Size
Small: two tasks in two waves, because both write `tally.py`. One part, one agent.
