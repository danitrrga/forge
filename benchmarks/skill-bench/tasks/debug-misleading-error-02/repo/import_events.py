"""Import the calendar export and print a summary: python3 import_events.py [calendar.txt]"""
import sys

from eventlog.importer import import_file


def main(path="calendar.txt"):
    events, errors = import_file(path)
    hours = sum(e.duration.total_seconds() for e in events) / 3600
    print("%d events, %.1f hours" % (len(events), hours))
    for error in errors:
        print("  " + error)


if __name__ == "__main__":
    main(*sys.argv[1:])
