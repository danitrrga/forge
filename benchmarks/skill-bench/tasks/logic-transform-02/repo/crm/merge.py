"""One contact list out of several exports."""


def _key(email):
    return email.strip().lower()


def merge_contacts(*exports):
    """Merge contact exports into one record per person.

    Each export is a list of dicts with an "email" key; exports are given oldest first.
    Records are matched by email, ignoring case and surrounding spaces. When a person
    appears more than once, later records win field by field; a field that is missing
    or None in a later record keeps the earlier value.

    Returns one dict per person, in order of first appearance.
    """
    merged = {}
    for export in exports:
        for record in export:
            current = merged.setdefault(_key(record["email"]), {})
            for field, value in record.items():
                if value:
                    current[field] = value
    return list(merged.values())
