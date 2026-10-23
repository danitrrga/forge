"""User storage (in memory here; the real one is a database)."""
import services

_USERS = {}


def save_user(user):
    if "@" not in user.get("email", ""):
        raise ValueError("invalid email: %r" % user.get("email"))
    _USERS[user["id"]] = dict(user)
    services.on_user_saved(dict(user))


def get_user(user_id):
    user = _USERS.get(user_id)
    return dict(user) if user else None


def all_users():
    return [dict(u) for u in _USERS.values()]
