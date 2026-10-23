"""Bulk import of users from the old system's CSV export:  python3 admin_import.py users.csv"""
import csv
import sys

import services
import store


def import_rows(rows):
    count = 0
    for row in rows:
        store.save_user({"id": row["id"], "name": row["name"], "email": row["email"]})
        count += 1
    return count


def main(path):
    with open(path, newline="", encoding="utf-8") as fh:
        count = import_rows(csv.DictReader(fh))
    print("%d users imported, %d audit entries" % (count, len(services.audit_log())))


if __name__ == "__main__":
    main(sys.argv[1])
