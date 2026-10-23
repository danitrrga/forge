"""User profiles and their preferences."""
import functools
import json
import os

DEFAULTS_FILE = os.path.join(os.path.dirname(__file__), "defaults.json")


@functools.lru_cache(maxsize=None)
def load_defaults():
    """The shipped default preferences. Read once: the file does not change while we run."""
    with open(DEFAULTS_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def new_profile(name, **overrides):
    """A profile with the default preferences, with any top-level preference overridden."""
    prefs = load_defaults()
    prefs.update(overrides)
    return {"name": name, "prefs": prefs}


def mute_notifications(profile):
    for channel in ("email", "push"):
        profile["prefs"]["notifications"][channel] = False
    return profile


def set_digest(profile, how_often):
    profile["prefs"]["notifications"]["digest"] = how_often
    return profile
