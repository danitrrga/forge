"""The round counter of a job: how many implement-verify rounds it has used, against the configured cap.

A round is a distinct SHA with a red `evidence` row (any rc but 0), or a `round` row whose detail starts with the word
`use`, counted since the last `round` row whose detail starts with the word `reset`. The same red SHA twice is one
round; a green SHA is none; a `round` row that is neither `use` nor `reset` is none. A reset empties the count, the SHAs
and the `use` rows before it, so a SHA that was red before it counts again if it goes red after it.

The cap is the configuration's `rounds` (config.py), a positive integer; it is never fixed here. The rows are read with
state.read_rows and written with state.append_audit, which this module never bypasses.

Imports only the standard library, state and config.
"""
import os

from fwx import config, state


def _word(row):
    """The first word of a row's detail, or ''."""
    words = row.get("detail", "").split(None, 1)
    return words[0] if words else ""


def count(rows):
    """The rounds the rows (as state.read_rows gives them, oldest first) have used."""
    shas, uses = set(), 0
    for row in rows:
        kind = row.get("kind")
        if kind == "evidence" and row.get("rc", "").strip() != "0":
            shas.add(row.get("sha", ""))
        elif kind == "round":
            word = _word(row)
            if word == "reset":
                shas, uses = set(), 0
            elif word == "use":
                uses += 1
    return len(shas) + uses


def cap(cwd=None):
    """The configured cap, found from `cwd` (a job folder works: the main checkout is found through git). Raises
    config.ConfigError for a cap that is not a positive integer."""
    value = config.load(cwd)["rounds"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise config.ConfigError("rounds is %r in the configuration: it must be a positive integer (the cap of rounds per job)"
                                 % (value,))
    return value


def status(folder):
    """`(used, cap)` of a job folder. state.StateError when the folder has no audit rows to count."""
    path = state.phase_paths(folder)["audit"]
    if not os.path.isfile(path):
        raise state.StateError("%s has no audit rows yet: nothing to count (is it a job folder?)" % folder)
    return count(state.read_rows(path)), cap(str(folder))


def record(folder, kind, motive):
    """Write the `use` or `reset` row; `kind` is one of those two words and `motive` is not blank."""
    if kind not in ("use", "reset"):
        raise state.StateError("a round row is `use` or `reset`, got %r" % (kind,))
    if not str(motive).strip():
        raise state.StateError("--%s needs a motive" % kind)
    if not os.path.isdir(str(folder)):
        raise state.StateError("%s is not a folder" % folder)
    state.append_audit(folder, "round", detail="%s %s" % (kind, motive))
