#!/usr/bin/env python3
"""A tally: add amounts, read the total, reset. The entries live in a JSON file next to this script.

usage: tally.py add AMOUNT | total | reset
"""
import json
import os
import sys

STORE = os.environ.get("TALLY_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tally.json"))


def load():
    with open(STORE, encoding="utf-8") as f:
        return json.load(f)


def save(entries):
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(entries, f)


def add(amount):
    try:
        entries = load()
    except FileNotFoundError:
        entries = []
    entries.append(amount)
    save(entries)


def total():
    entries = load()
    return sum(entries[:-1])


def reset():
    save([])


def main(argv):
    if len(argv) == 2 and argv[0] == "add":
        add(float(argv[1]))
    elif argv == ["total"]:
        print(total())
    elif argv == ["reset"]:
        reset()
    else:
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
