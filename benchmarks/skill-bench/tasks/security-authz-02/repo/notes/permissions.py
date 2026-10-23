def can_read(user, doc):
    return doc["owner"] == user["id"] or user["id"] in doc["shared_with"]


def can_edit(user, doc):
    return doc["owner"] == user["id"]
