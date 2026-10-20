"""The record of what forge wrote: the core of step 10, increment I2.

forge decides what in a shared file is its own without state (an exact command, a file shape, a
declaration), so something it wrote outlives its source: a permission taken out of a profile stays in
settings.local.json, a hook row deleted from forge/hooks.py keeps its entry in ~/.claude/settings.json.
This module remembers, per file, what the last run put there, so the next run can tell what it
stopped wanting and take only that out.

The registry is one machine file, <lib.STATE>/owned.json, never in a repo:

    {"version": 1, "claims": {"<absolute file path>": [claim, ...]}}
    claim = {"kind": "item|key|hook|file", "at": [JSON path ...], "sum": "<sha256 hex>", "owner": "<name>"}

`kind` says what the claim is: `item` one element of a list, `key` one key of an object, `hook` one hook
row, `file` the file itself. `at` locates it, and (kind, at) is the claim's identity, which `stale` compares:
two claims with the same kind and `at` are the same claim, whatever their sums. So for an item `at` ends in
a locator the caller picks that names the element and is not a secret (a permission string, a hook's
command), never a list index, which moves. `owner` is core, an
integration's name or a profile. Only the SHA-256 of a value is kept, never the value: a resolved env
holds secrets, and the record must not become another place they live. The file is written 0600, because
the hash of a short secret can be guessed.

How a caller uses it (forge/skills.py and forge/hooks.py wire it in a later task):

    prev, warn = owned.previous(path)                 # what the last run recorded for this file; print warn if any
    now = [owned.claim(kind, at, value, owner), ...]  # what this run puts there
    for c in owned.stale(prev, now):                  # claimed last time, not wanted now
        if owned.removable(c, current_value_at(c)):   # still exactly what forge wrote
            remove it
        else:
            print("  ! %s: %s was edited, left in place" % (path, c["at"]))   # a hand-edited value is the user's
    owned.record(path, now, apply)                    # last, after the file was written

With no previous record (a first run, or the file was lost) nothing is stale: forgetting a claim only ever
leaves a stray value in place, never removes one it should not. The same holds for a registry that cannot
be trusted.

Every function is stdlib only and none raises on a bad registry. `load` and `previous` return their warning
as a line in forge's "  ! " style instead of printing it, so a caller that prints nothing (a hook's JSON
output) can still choose; the caller prints it. `record` takes an `apply` flag: False (a dry-run) writes
nothing, as does a checkout lib.may_write() refuses. It does not take lib.lock: its callers already run under
it (cmd_sync and session-start hold it in the parent process, and a generator subprocess taking it again
would block, lib.lock being an flock on a fresh descriptor). It reads, replaces one file's claims and writes
back, so two unlocked callers could lose each other's claims."""
import hashlib
import json
import os

from forge import lib

VERSION = 1
KINDS = ("item", "key", "hook", "file")


def path():
    """The registry's location, read from lib.STATE at each call."""
    return os.path.join(lib.STATE, "owned.json")


def digest(value):
    """SHA-256 hex of `value` as canonical JSON: sorted keys, compact separators, non-ASCII kept."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def claim(kind, at, value, owner):
    """The claim for `value`, which forge put at JSON path `at` (a list). Only its digest is kept."""
    return {"kind": kind, "at": list(at), "sum": digest(value), "owner": owner}


def _valid(doc):
    if not isinstance(doc, dict) or doc.get("version") != VERSION:
        return "version is not %d" % VERSION
    claims = doc.get("claims")
    if not isinstance(claims, dict):
        return "claims is not an object"
    for file, items in claims.items():
        if not isinstance(items, list):
            return "the claims of %s are not a list" % file
        for c in items:
            if not (isinstance(c, dict) and c.get("kind") in KINDS and isinstance(c.get("at"), list)
                    and isinstance(c.get("sum"), str) and isinstance(c.get("owner"), str)):
                return "a claim of %s is malformed" % file
    return None


def load():
    """(claims, warning): the registry's {file: [claim]}, and "" or one "  ! " line. A missing file is
    ({}, ""). One that cannot be read or parsed, has another version or the wrong shape is ({}, line)."""
    p = path()
    try:
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return {}, ""
    except (OSError, ValueError) as e:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        return {}, "  ! could not read %s: %s -- no ownership record, nothing will be removed" % (p, e)
    why = _valid(doc)
    if why:
        return {}, "  ! could not use %s: %s -- no ownership record, nothing will be removed" % (p, why)
    return doc["claims"], ""


def previous(file):
    """(claims, warning): what the last run recorded for `file`, as load's warning goes with it."""
    claims, warn = load()
    return claims.get(file, []), warn


def _identity(c):
    return (c["kind"], json.dumps(c["at"]))


def stale(prev, now):
    """The claims in `prev` whose identity (kind, at) is not among `now`'s, in `prev`'s order."""
    wanted = {_identity(c) for c in now}
    return [c for c in prev if _identity(c) not in wanted]


def removable(c, current_value):
    """Whether `current_value` is still what forge wrote for claim `c`: its digest equals the claim's.
    An edited value is the user's now and is never removable; the caller names it on one line."""
    return digest(current_value) == c["sum"]


def record(file, claims, apply):
    """Replace the claims of `file` (an absolute path) with `claims`, leaving every other file's alone;
    no claims drops the file's entry. Returns whether the registry was written: False for a dry-run
    (`apply` false) or when lib.may_write() refuses. A registry that cannot be read is replaced by one
    holding only this file's claims. Written through lib.write_json, 0600."""
    if not apply or not lib.may_write()[0]:
        return False
    registry, _ = load()
    registry = dict(registry)
    if claims:
        registry[file] = list(claims)
    else:
        registry.pop(file, None)
    lib.write_json(path(), {"version": VERSION, "claims": registry}, mode=0o600, newline=True)
    return True
