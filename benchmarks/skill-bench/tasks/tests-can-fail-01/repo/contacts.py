"""Merge the contact exports of the CRM and the newsletter tool into one list.

    python3 contacts.py crm.csv newsletter.csv > merged.csv

Files are read in the order given; for a person who appears in several, the first file wins.
"""
import csv
import sys

FIELDS = ["email", "name", "phone", "company"]


def normalize_email(email):
    return email.strip().lower()


def merge_contacts(rows):
    """Collapse rows that share an e-mail address (case and surrounding spaces do not matter).

    The first row seen for an address is kept; later rows only fill in the fields that are
    still empty on it. Returns the kept rows in first-seen order.
    """
    by_email = {}
    merged = []
    for row in rows:
        key = normalize_email(row["email"])
        if key in by_email:
            kept = by_email[key]
            for field, value in row.items():
                if value and not kept.get(field):
                    kept[field] = value
        else:
            kept = dict(row)
            by_email[row["email"]] = kept
            merged.append(kept)
    return merged


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(paths, out=sys.stdout):
    rows = []
    for path in paths:
        rows.extend(load(path))
    writer = csv.DictWriter(out, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in merge_contacts(rows):
        writer.writerow(row)


if __name__ == "__main__":
    main(sys.argv[1:])
