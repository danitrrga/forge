"""User operations used by the web app."""
import search
import store

_AUDIT = []


def on_user_saved(user):
    """Run after every save: keeps the search index and the audit trail current."""
    search.index_user(user)
    _AUDIT.append(("saved", user["id"], user["name"]))


def register(user_id, name, email):
    if store.get_user(user_id) is not None:
        raise ValueError("user %s already exists" % user_id)
    store.save_user({"id": user_id, "name": name, "email": email})


def rename_user(user_id, name):
    user = store.get_user(user_id)
    if user is None:
        raise KeyError(user_id)
    user["name"] = name
    store.save_user(user)


def audit_log():
    return list(_AUDIT)
