"""Where each concept's settings live, in the layout forge has (everything in config/forge.json, plus a file
per tool) and in the layout it is moving to (a file per concept). The one place that knows: `load(concept)`
returns a concept's settings in the OLD shape from whichever layout is on disk, and `lib.settings()` is
composed with it, so no caller of `lib.settings()` and no test that writes a toy forge.json notices which
layout it is in.

LAYOUT is the table, and the only place the new names are written. A concept has `new`, the file (or
folder) it moves to, and `old`, {file it is in today: rows}. A row is a key path, dotted when the key is
nested ("skill_keep.sets"), or a pair (path in the old file, path in the new one) when the name changes; the
path "" is the whole file. The engine file is the one `lib.settings()` was given, so a toy world's
`forge-0.json` is ENGINE too.

A key in both places is an exit 1 naming both: two places that disagree have no right answer, and the one
that looks right today decides tomorrow. A key in neither is absent, as it is today. A file the new layout
has and the table does not name a key of is not read, so a key put in the wrong file is simply not found.

Only what `lib.settings()` served before, the rows whose old file is the engine file, is merged into it:
the files other code opens by path (toolchain.json, mcp-registry.json, the memory and framework files, the
profiles) are read by `load` for the units that move their readers, and by nothing else yet."""
import copy
import json
import os
import sys

ENGINE = "forge.json"

# The keys that stay in the engine file: the engine's switches and the machine's own settings.
# `skill_keep.extras` and `skill_keep.common_opt_out` are per-project rows: they go into the project's own
# file, but not before the unit that moves the readers of those two, so they stay here until then.
# `framework.models` and the GSD keys do not move (the GSD ones are removed with GSD).
_ENGINE_KEYS = (
    "integrations", "gsd_patches", "gsd_isolation_guard", "house_hooks", "codex_harness", "user_settings",
    "user_hooks", "local_plugins", "launchers", "instruction_files_skip", "lock_exclude", "doctor_extra",
    "skill_keep.gsd_exclude", "skill_keep.gsd_opt_in", "skill_keep.extras", "skill_keep.common_opt_out",
    "framework.models",
)

LAYOUT = {
    "engine": {"new": ENGINE, "old": {ENGINE: _ENGINE_KEYS}},
    "common": {"new": "common.json", "old": {ENGINE: (
        ("skill_keep.sets", "sets"), ("skill_keep.design_permissions", "design_permissions"),
        ("skill_keep.common_skills", "common_skills"), ("skill_keep.common_permissions", "common_permissions"),
        ("skill_keep.common_env", "common_env"), ("skill_keep.common_plugins", "common_plugins"),
        ("skill_keep.common_exclude", "common_exclude"),
    )}},
    "tools": {"new": "tools.json", "old": {
        "toolchain.json": ("tools", "pip", "skills"),
        "mcp-registry.json": ("servers",),
    }},
    "memory": {"new": "memory.json", "old": {
        ENGINE: ("session_wait",),
        "hindsight-coding-agents.json": (("", "hindsight_coding_agent"),),
        "memory-known-empty.json": (("", "known_empty"),),
    }},
    "framework": {"new": "framework.json", "old": {
        ENGINE: tuple(("framework." + k, k) for k in (
            "plugin_source", "limits", "rounds", "critique_rounds_unattended", "factory", "weekly", "paths", "linear")),
        "framework-permissions.json": (("", "permissions"),),
    }},
    # One file per project: NAME + suffix in each folder. Listed by `load` only; lib.profiles() is not moved yet.
    "projects": {"new": "projects", "old": "profiles", "new_suffix": ".json", "old_suffix": ".claude.json"},
}


def _die(message):
    sys.exit("! " + message)


def _read(directory, name, engine):
    """The parsed file `name` of `directory`, or None when it is not there. The engine file is `engine` when
    the caller already parsed it."""
    if name == ENGINE and engine is not None:
        return engine
    path = os.path.join(directory, name)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        _die("config/%s unreadable (%s)" % (name, e))
    if not isinstance(doc, dict):
        _die("config/%s unreadable (top level is %s, not an object)" % (name, type(doc).__name__))
    return doc


_MISSING = object()


def _get(doc, path):
    """The value at the dotted `path` of `doc`, whole when the path is "", or _MISSING."""
    if path == "":
        return doc
    for part in path.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return _MISSING
        doc = doc[part]
    return doc


def _put(doc, path, value, where):
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = doc.setdefault(part, {})
        if not isinstance(nxt, dict):
            _die("%s: %s is not an object, so %s cannot go into it" % (where, part, path))
        doc = nxt
    doc[parts[-1]] = value


def _rows(entry):
    """(old file, old path, new path) for every row of a concept's table entry."""
    for old_file, rows in entry["old"].items():
        for row in rows:
            old_path, new_path = (row, row) if isinstance(row, str) else row
            yield old_file, old_path, new_path


def _found(concept, directory, engine, served_only):
    """[(key in the old shape, value, whether it came from the new place)] for each row of `concept` that
    has a value. A row whose value is in both places exits 1."""
    entry, docs, out = LAYOUT[concept], {}, []

    def doc(name):
        if name not in docs:
            docs[name] = _read(directory, name, engine)
        return docs[name]
    for old_file, old_path, new_path in _rows(entry):
        if served_only and old_file != ENGINE:
            continue
        key = old_path or os.path.splitext(old_file)[0]
        old = doc(old_file)
        old_value = _MISSING if old is None else _get(old, old_path)
        if old_file == entry["new"]:  # the same file in both layouts: one place
            if old_value is not _MISSING:
                out.append((key, old_value, False))
            continue
        new = doc(entry["new"])
        new_value = _MISSING if new is None else _get(new, new_path)
        if old_value is not _MISSING and new_value is not _MISSING:
            _die("%s is in both config/%s and config/%s: keep one" % (key, old_file, entry["new"]))
        if new_value is not _MISSING:
            out.append((key, new_value, True))
        elif old_value is not _MISSING:
            out.append((key, old_value, False))
    return out


def _listing(directory, folder, suffix):
    base = os.path.join(directory, folder)
    try:
        names = sorted(os.listdir(base))
    except FileNotFoundError:
        names = []
    return {n[:-len(suffix)]: os.path.join(base, n) for n in names if n.endswith(suffix) and len(n) > len(suffix)}


def _load_projects(entry, directory):
    old = _listing(directory, entry["old"], entry["old_suffix"])
    new = _listing(directory, entry["new"], entry["new_suffix"])
    both = sorted(set(old) & set(new))
    if both:
        _die("%s is in both config/%s/ and config/%s/: keep one" % (", ".join(both), entry["old"], entry["new"]))
    out = {}
    for name, path in sorted(dict(old, **new).items()):
        out[name] = _read(os.path.dirname(path), os.path.basename(path), None)
    return out


def load(concept, directory, engine=None):
    """`concept`'s settings in the old shape, read from `directory` (config/): the engine file's own keys
    nested as they are in it ({"skill_keep": {"sets": ...}}), another old file's keys at its top level, a
    whole file under its file's name, and for "projects" {name: document}. `engine` is the parsed engine file
    when the caller has it."""
    if concept not in LAYOUT:
        raise ValueError("unknown concept %r (one of %s)" % (concept, ", ".join(LAYOUT)))
    if concept == "projects":
        return _load_projects(LAYOUT[concept], directory)
    out = {}
    for key, value, _ in _found(concept, directory, engine, False):
        _put(out, key, copy.deepcopy(value), "config/" + concept)
    return out


def merge(engine, directory):
    """The engine file `engine` with every setting `lib.settings()` serves that the new layout moved out of
    it put back where the old layout has it. With no new file there, `engine` is returned unchanged."""
    for concept in LAYOUT:
        if concept == "projects":
            continue
        for key, value, from_new in _found(concept, directory, engine, True):
            if from_new:
                _put(engine, key, value, "config/%s" % ENGINE)
    return engine
