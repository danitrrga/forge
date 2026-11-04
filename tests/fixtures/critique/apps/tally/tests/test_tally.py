#!/usr/bin/env python3
"""tally.py: add keeps every entry, total sums them all, reset empties the store. A plain script: prints each FAIL and
exits 1 on any."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["TALLY_FILE"] = os.path.join(tempfile.mkdtemp(prefix="tally-test-"), "tally.json")
sys.path.insert(0, HERE)
import tally  # noqa: E402

failed = 0


def check(name, got, want):
    global failed
    if got != want:
        failed += 1
        print("FAIL: %s: got %r, want %r" % (name, got, want))


for amount in (5, 7, 2):
    tally.add(amount)
check("entries kept after three adds", tally.load(), [5, 7, 2])
check("total of 5, 7 and 2", tally.total(), 14)
tally.reset()
check("entries after reset", tally.load(), [])
check("total after reset", tally.total(), 0)

print("%d failed" % failed if failed else "all passed")
sys.exit(1 if failed else 0)
