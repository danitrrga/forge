"""The record of what forge wrote: the core of step 10, increment I2.

forge decides what in a shared file is its own without state (an exact command, a file shape, a
declaration), so something it wrote outlives its source: a permission taken out of a profile stays in
settings.local.json, a hook row deleted from forge/hooks.py keeps its entry in ~/.claude/settings.json.
This module remembers, per file, what the last run put there, so the next run can tell what it
stopped wanting and take only that out.

The registry is one machine file, <lib.STATE>/owned.json, never in a repo:

    {"version": 1, "claims": {"<absolute file path>": [claim, ...]}}
    claim = {"kind": "item|key|hook|file", "at": [JSON path ...], "sum": "<sha256 hex>", "owner": "<name>",
             "part": "<name>"}

`kind` says what the claim is: `item` one element of a list, `key` one key of an object, `hook` one hook
row, `file` the file itself. `at` locates it, and (kind, at) is the claim's identity, which `stale` compares:
two claims with the same kind and `at` are the same claim, whatever their sums. So for an item `at` ends in
a locator the caller picks that names the element and is not a secret (a permission string, a hook's
command), never a list index, which moves. `owner` is core, an
integration's name or a profile. `part` is optional and names one writer's share of a file, so several writers
can claim in the same file without erasing each other: record(file, claims, apply, part="skills") replaces only
the claims of that part and previous(file, part) returns only those. Without `part` (None) a call means the
whole file's claims, as before, and a claim without a "part" field (every registry written before parts
existed) counts as part None; the field is omitted when None, so the version stays 1. A part is a short string
such as "skills" or "gitignore:system-doc"; "bak" is the one core uses for a `.bak` file forge created (below).
Only the SHA-256 of a value is kept, never the value: a resolved env
holds secrets, and the record must not become another place they live. The file is written 0600, because
the hash of a short secret can be guessed.

A `.bak` that lib.write_text creates (backup=True, once ever) is claimed through claim_backup, called from
write_text's .bak branch: kind `file`, `at` [], `sum` the digest of its content as a string (the content itself
is never stored), part "bak", keyed by the .bak's own path, so that a later uninstall can delete it if it is
still what forge copied. A `.bak` that existed before is never claimed: write_text does not create it.

How a caller uses it (forge/skills.py and forge/hooks.py wire it in a later task):

    prev, warn = owned.previous(path)                 # what the last run recorded for this file; print warn if any
    now = [owned.claim(kind, at, value, owner), ...]  # what this run puts there
    for c in owned.stale(prev, now):                  # claimed last time, not wanted now
        if owned.removable(c, current_value_at(c)):   # still exactly what forge wrote
            remove it
        else:
            print("  ! %s: %s was edited, left in place" % (path, c["at"]))   # a hand-edited value is the user's
    owned.record(path, now, apply)                    # last, after the file was written

current(file, claim) reads that value the way the claim's writer wrote it, for every kind; forge doctor's
`owned` row and forge uninstall (forge/uninstall.py) both compare through it.

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
                    and isinstance(c.get("sum"), str) and isinstance(c.get("owner"), str)
                    and isinstance(c.get("part", ""), str)):
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


def previous(file, part=None):
    """(claims, warning): what the last run recorded for `file`, as load's warning goes with it. With a
    `part`, only that part's claims; None is the whole file's, a claim of any part included."""
    claims, warn = load()
    items = claims.get(file, [])
    if part is not None:
        items = [c for c in items if c.get("part") == part]
    return items, warn


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


_ANY = object()


def _hooks_with(doc, event, command, matcher):
    """The well-formed entries of doc["hooks"][event] whose command is `command`, in a group whose matcher is
    `matcher` (any group when `matcher` is _ANY)."""
    hooks = doc.get("hooks")
    groups = hooks.get(event) if isinstance(hooks, dict) and isinstance(event, str) else None
    if not isinstance(groups, list):
        return []
    return [h for g in groups if isinstance(g, dict) and isinstance(g.get("hooks"), list)
            and (matcher is _ANY or g.get("matcher") == matcher)
            for h in g["hooks"] if isinstance(h, dict) and h.get("command") == command]


def current(file, c, doc=None):
    """(found, value): what is now at claim `c`'s place in `file`, read the way its writer wrote it, for
    removable() to compare. It never prints, and a value never leaves the caller.
      file: a link is "symlink:<its target>" (sync_system_doc.py's AGENTS.md); a `.json` file its parsed JSON
        (memory.py's rendered config), any other file its text with newlines untranslated (a `.bak`,
        config.toml). Missing is not found; one that cannot be read or parsed is found with a value that
        is not the claim's.
      item ["line", L]: found when a line of the text file, stripped, is L (an ignore line); the value is L.
      item [path..., v]: found when the list at `path` holds v; the value is v, the locator being the value.
      hook ["hooks", event, command]: an entry under the event, in any group (a project's settings.local.json).
      hook [event, matcher, command]: an entry in a group with that matcher (~/.claude/settings.json, hooks.json).
        Of several entries, the one still equal to the claim when there is one.
      key [path...]: the value at `path`.
    `doc`, when given, is the file already loaded (the parsed object, or the text for a line), so a caller with
    many claims in one file reads it once. Otherwise it is read here: a missing file is not found, and a JSON
    or text file that cannot be read raises lib.Unreadable."""
    kind, at = c["kind"], c["at"]
    if kind == "file":
        if os.path.islink(file):
            return True, "symlink:" + os.readlink(file)
        if not os.path.lexists(file):
            return False, None
        try:
            with open(file, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            return True, None
        if file.endswith(".json"):
            try:
                return True, json.loads(text)
            except ValueError:
                return True, text
        return True, text
    if kind == "item" and at[:1] == ["line"] and len(at) == 2:
        if doc is None:
            try:
                with open(file, encoding="utf-8") as fh:
                    doc = fh.read()
            except FileNotFoundError:
                return False, None
            except (OSError, UnicodeDecodeError) as e:
                raise lib.Unreadable(file, str(e)) from e
        return any(l.strip() == at[1] for l in doc.splitlines()), at[1]
    if doc is None:
        doc = lib.read_owned(file, None)
        if doc is None:
            return False, None
    if kind == "hook" and len(at) == 3:
        event, matcher, command = (at[1], _ANY, at[2]) if at[0] == "hooks" else at
        found = _hooks_with(doc, event, command, matcher)
        if not found:
            return False, None
        return True, next((h for h in found if removable(c, h)), found[0])
    if kind == "item" and not at:
        return False, None
    node = doc
    for k in (at[:-1] if kind == "item" else at):
        if not isinstance(node, dict) or k not in node:
            return False, None
        node = node[k]
    if kind == "item":
        return isinstance(node, list) and at[-1] in node, at[-1]
    return True, node


def record(file, claims, apply, part=None):
    """Replace the claims of `file` (an absolute path) with `claims`, leaving every other file's alone;
    no claims drops the file's entry. With a `part`, replace only that part's claims of `file` (each stored
    with its "part" field) and keep the file's other claims; none left drops the entry. Returns whether the registry was written: False for a dry-run
    (`apply` false) or when lib.may_write() refuses. A registry that cannot be read is replaced by one
    holding only this file's claims. Written through lib.write_json, 0600."""
    if not apply or not lib.may_write()[0]:
        return False
    registry, _ = load()  # a fresh dict on every call, so it is ours to change
    if part is not None:
        claims = [c for c in registry.get(file, []) if c.get("part") != part] + [dict(c, part=part) for c in claims]
    if claims:
        registry[file] = claims
    else:
        registry.pop(file, None)
    lib.write_json(path(), {"version": VERSION, "claims": registry}, mode=0o600, newline=True)
    return True


def claim_backup(bak, apply):
    """Claim `bak`, a `.bak` file lib.write_text has just created, as kind `file` under part "bak": the
    digest of its content as a string, never the content. Nothing for a dry-run, a checkout that may not
    write, or a file that is missing or not UTF-8 (a stray file is left alone, the safe direction). It never
    raises: lib.write_text, its caller, has made the copy already."""
    try:
        with open(bak, encoding="utf-8", newline="") as fh:
            text = fh.read()
        record(bak, [claim("file", [], text, "core")], apply, part="bak")
    except (OSError, UnicodeDecodeError):
        pass
