"""Name search over users."""

_INDEX = {}  # lower-case word -> set of user ids


def index_user(user):
    for ids in _INDEX.values():
        ids.discard(user["id"])
    for word in user["name"].lower().split():
        _INDEX.setdefault(word, set()).add(user["id"])


def find(word):
    return sorted(_INDEX.get(word.lower(), ()))
