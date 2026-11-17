"""The profiles of a project: sets of skills, plugins and MCP servers that hold for one session (not for the project), and
the two commands that read them, `forge list @` and `forge list @NAME`, and the record of a session started with one
(session_record, which forge/launch.py writes). Nothing else here writes a file.

Two layers (docs/modes-design.md, "Where modes live"). A definition, shared by every project, is
config/profile-defs/<name>.json (examples/profile-def.json has its shape): description, color, skills (names or `@SET` of
config/forge.json skill_keep.sets), plugins, the kinds of MCP server it needs, permissions and env. A project file chooses
among them in its `profiles` field:

    "profiles": {"default": "<label>",
                 "offered": {"<name>": {"skills": [], "plugins": [], "servers": {"<kind>": "<server of the registry>"}}}}

`default` is only the label of the profile the project has today (its file as it is: it is never resolved, which is why a
project without `profiles` does not change); `offered` holds one row per definition the project takes, with the skills and
plugins that are only its own and the server each kind of the definition means here. A profile is complete: it does not
inherit from the default (a marketing session must not list the code skills, and the skill listing has a budget).

shape_error validates the field and is called by lib.project_error, so a malformed `profiles` makes lib.projects() leave the
project out and name it. resolve() is the profile's lists; cmd_list is the command."""
import functools
import importlib.util
import json
import os
import re
import shutil
import sys
import time

from forge import lib, suggest

NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FIELDS = ("skills", "plugins", "servers")
# The keys of a definition, and the type of each (lists of strings, objects of strings are checked by definition_error).
DEFINITION = {"description": str, "color": str, "skills": list, "plugins": list, "server_kinds": list,
              "permissions": dict, "env": dict}
ANSI = {"black": 30, "red": 31, "green": 32, "yellow": 33, "blue": 34, "magenta": 35, "cyan": 36, "white": 37}
DEFAULT_TEXT = "the project file as it is"


class ProfileError(Exception):
    """A profile that cannot be resolved: the message names the project, the profile and the cause."""


def name_error(name):
    """None when `name` can name a profile, else why not. With the verb first a profile has no reserved word (`list` is
    fine, `@list` is not a command), but `@` marks a profile on the command line and `-` opens an option."""
    if not isinstance(name, str) or not name:
        return "a profile name is a non-empty string"
    if name.startswith("@"):
        return "%r starts with @, which marks a profile on the command line and is not part of its name" % name
    if name.startswith("-"):
        return "%r starts with -, which would read as an option" % name
    if not NAME.fullmatch(name):  # fullmatch: `$` would also match before a final newline
        return "%r is not kebab-case (lowercase letters and digits, single dashes between them)" % name
    return None


def _strings(value):
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def shape_error(profiles):
    """None when the `profiles` field of a project file has its shape, else why not (the first thing wrong)."""
    if not isinstance(profiles, dict):
        return "profiles is not a JSON object"
    extra = sorted(set(profiles) - {"default", "offered"})
    if extra:
        return "profiles.%s is not a key of profiles (known: default, offered)" % extra[0]
    for key in ("default", "offered"):
        if key not in profiles:
            return "profiles.%s is missing" % key
    label, offered = profiles["default"], profiles["offered"]
    why = name_error(label)
    if why:
        return "profiles.default: %s" % why
    if not isinstance(offered, dict):
        return "profiles.offered is not a JSON object"
    if label in offered:
        return ("profiles.offered repeats the default label %r: the default is the project file as it is, so it has no row"
                % label)
    for name, row in offered.items():
        why = name_error(name)
        if why:
            return "profiles.offered: %s" % why
        if not isinstance(row, dict):
            return "profiles.offered.%s is not a JSON object" % name
        extra = sorted(set(row) - set(FIELDS))
        if extra:
            return "profiles.offered.%s.%s is not a key of a profile row (known: %s)" % (name, extra[0], ", ".join(FIELDS))
        for key in ("skills", "plugins"):
            if key in row and not _strings(row[key]):
                return "profiles.offered.%s.%s is not a list of strings" % (name, key)
        servers = row.get("servers", {})
        if not isinstance(servers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in servers.items()):
            return "profiles.offered.%s.servers is not an object of strings (kind: server)" % name
    return None


def parse_at(text):
    """The profile name of the command-line argument `@name` ('' for a bare `@`). ValueError, with the reason, for any other
    argument or for a name that starts with @ or -. A name that is merely not kebab-case is let through: no profile has it, so
    the lookup answers with the closest one (`@toy-` proposes `@toy-b`)."""
    if not text.startswith("@"):
        raise ValueError("%r is not a profile: a profile is written @NAME" % text)
    name = text[1:]
    if name.startswith(("@", "-")):
        raise ValueError(name_error(name))
    return name


def definition_path(name):
    return os.path.join(lib.ROOT, "config", "profile-defs", name + ".json")


def definition(name):
    """config/profile-defs/<name>.json as a dict with every key present, or ProfileError saying why not."""
    rel = os.path.relpath(definition_path(name), lib.ROOT)
    try:
        text = lib.read_text(definition_path(name))
    except lib.Unreadable as e:
        raise ProfileError("%s cannot be read (%s)" % (rel, e.reason))
    if text is None:
        raise ProfileError("no definition: %s does not exist" % rel)
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise ProfileError("%s is not valid JSON (%s)" % (rel, e))
    if not isinstance(doc, dict):
        raise ProfileError("%s is not a JSON object" % rel)
    extra = sorted(k for k in doc if k not in DEFINITION and not k.startswith("_"))  # `_...` keys are documentation
    if extra:
        raise ProfileError("%s: %s is not a key of a definition (known: %s)" % (rel, extra[0], ", ".join(DEFINITION)))
    for key, kind in DEFINITION.items():
        if key in doc and not isinstance(doc[key], kind):
            raise ProfileError("%s: %s is not a %s" % (rel, key, "string" if kind is str else "list" if kind is list else "JSON object"))
    for key in ("skills", "plugins", "server_kinds"):
        if not _strings(doc.get(key, [])):
            raise ProfileError("%s: %s is not a list of strings" % (rel, key))
    if not all(isinstance(v, str) for v in doc.get("env", {}).values()):
        raise ProfileError("%s: env is not an object of strings" % rel)
    for key in ("allow", "deny", "additionalDirectories"):  # the lists the resolver unions: a bare string would be split into letters
        if key in doc.get("permissions", {}) and not _strings(doc["permissions"][key]):
            raise ProfileError("%s: permissions.%s is not a list of strings" % (rel, key))
    return {"description": "", "color": "", "skills": [], "plugins": [], "server_kinds": [], "permissions": {}, "env": {},
            **{k: v for k, v in doc.items() if k in DEFINITION}}


@functools.lru_cache(maxsize=None)
def _skill_keep():
    """scripts/sync/sync_skill_keep.py as a module, loaded by path (scripts/ is no package): the one place that knows the
    common layer every project's lists start from. Importing it reads config/forge.json and the skills installed under
    ~/.claude/skills, as the script itself does."""
    spec = importlib.util.spec_from_file_location("forge_sync_skill_keep", os.path.join(lib.ROOT, "scripts", "sync", "sync_skill_keep.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _union(*lists):
    return list(dict.fromkeys(x for items in lists for x in items))


def default_lists(prof):
    """The default profile: the project file as it is, in the shape resolve() returns."""
    return {"skills_keep": list(prof.get("skills_keep", [])), "plugins_keep": list(prof.get("plugins_keep", [])),
            "servers": list(prof.get("servers", [])), "permissions": dict(prof.get("permissions", {})),
            "env": dict(prof.get("env", {}))}


def resolve(project, prof, profile):
    """The lists one session of `profile` runs with: {"description", "color", "skills_keep", "plugins_keep", "servers",
    "permissions", "env"}. The base is the one sync_skill_keep.py gives every project (the common skills, plugins,
    permissions and env, and the design set's file access), then the definition, then the project's row; the `@SET` of a
    skill is expanded from skill_keep.sets. Nothing is read from the project's own lists (a profile does not inherit from
    the default) and nothing is written. ProfileError, naming the project, the profile and the cause, when it cannot."""
    def fail(cause):
        return ProfileError("profile '%s' of project '%s': %s" % (profile, project, cause))
    profiles = prof.get("profiles")
    if not isinstance(profiles, dict) or shape_error(profiles):
        raise ProfileError("project '%s' has no valid profiles" % project)
    offered = profiles["offered"]
    if profile not in offered:
        raise ProfileError(suggest.message("profile", profile, [profiles["default"]] + list(offered), " in project '%s'" % project))
    row = offered[profile]
    try:
        d = definition(profile)
    except ProfileError as e:
        raise fail(e)
    sk = _skill_keep()
    sets = sk.SKILL_KEEP.get("sets") or {}
    names = d["skills"] + row.get("skills", [])
    for n in names:
        if n.startswith("@") and n[1:] not in sets:
            raise fail("unknown skill set '%s' (skill_keep.sets in config/forge.json has: %s)" % (n, ", ".join(sorted(sets)) or "none"))
    skills = sk.expand_extras({profile: names}, sets)[profile]
    installed = sk.installed_skills()
    for n in skills:
        if n not in installed:
            raise fail("unknown skill '%s' (no folder of that name in %s)" % (n, lib.short(sk.GLOBAL_SKILLS)))
    extra = sorted(set(row.get("servers", {})) - set(d["server_kinds"]))
    if extra:
        raise fail("the row assigns a server to the kind '%s', which the definition does not list (server_kinds: %s)"
                   % (extra[0], ", ".join(d["server_kinds"]) or "none"))
    doc = lib.read_json(os.path.join(lib.ROOT, "config", "mcp-registry.json"))
    registry = doc.get("servers") if isinstance(doc, dict) and isinstance(doc.get("servers"), dict) else {}
    servers = []
    for kind in d["server_kinds"]:
        if kind not in row.get("servers", {}):
            raise fail("the server kind '%s' has no server assigned: add it to profiles.offered.%s.servers" % (kind, profile))
        if row["servers"][kind] not in registry:
            raise fail("server '%s' (kind '%s') is not in config/mcp-registry.json" % (row["servers"][kind], kind))
        servers.append(row["servers"][kind])
    out = {"skills_keep": _union(skills), "plugins_keep": _union(d["plugins"], row.get("plugins", [])),
           "permissions": json.loads(json.dumps(d["permissions"]))}
    fn = project + ".claude.json"
    sk.apply_common(fn, out)
    sk.apply_common_plugins(fn, out)
    sk.apply_design(out)
    for n in out["skills_keep"]:  # after the common layer: a common skill that is not installed is no better than one of the definition
        if n != "*" and n not in installed:
            raise fail("unknown skill '%s' (no folder of that name in %s)" % (n, lib.short(sk.GLOBAL_SKILLS)))
    out.setdefault("permissions", {})
    out["env"] = {**out.get("env", {}), **d["env"]}  # the definition's env last: it wins over the common layer's
    return {"description": d["description"], "color": d["color"], "skills_keep": out["skills_keep"],
            "plugins_keep": out["plugins_keep"], "servers": servers, "permissions": out["permissions"], "env": out["env"]}


def _flat(lists):
    """Each field of resolve()'s lists as a set of strings, so two profiles can be told apart field by field."""
    perms = set()
    for k, v in lists["permissions"].items():
        if isinstance(v, list):
            perms |= {"%s:%s" % (k, x if isinstance(x, str) else json.dumps(x, sort_keys=True)) for x in v}
        else:
            perms.add("%s=%s" % (k, json.dumps(v, sort_keys=True)))
    return {"skills_keep": set(lists["skills_keep"]), "plugins_keep": set(lists["plugins_keep"]), "servers": set(lists["servers"]),
            "permissions": perms, "env": {"%s=%s" % kv for kv in lists["env"].items()}}


def differences(lists, default):
    """{field: {"added": [...], "removed": [...]}} for what `lists` has that the default lacks and the reverse; a field that does not differ is left out."""
    a, b = _flat(lists), _flat(default)
    return {f: {"added": sorted(a[f] - b[f]), "removed": sorted(b[f] - a[f])} for f in a if a[f] != b[f]}


def project_here(cwd):
    """(name, project file) of the project `cwd` belongs to, or None. A linked worktree is its main checkout's project."""
    cwd = os.path.realpath(cwd)
    if lib.git_dir(cwd)[1]:
        top = lib._git_out(cwd, "rev-parse", "--show-toplevel")
        common = lib._git_out(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if top and common:
            cwd = os.path.join(os.path.dirname(common), os.path.relpath(cwd, os.path.realpath(top)))
    name = lib.resolve_project(cwd)
    return (name, lib.projects()[name]) if name else None


def _paint(text, color):
    """`text` in `color` when stdout is a terminal and NO_COLOR is not set; otherwise as it is."""
    if color in ANSI and sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return "\033[%dm%s\033[0m" % (ANSI[color], text)
    return text


def _say(text="", err=False):
    print(text, file=sys.stderr if err else sys.stdout)


def _rows(prof):
    """One row per profile of the project, the default first: {"name", "default", "description", "color"}. A definition
    that cannot be read leaves its row with the reason as the description."""
    p = prof["profiles"]
    rows = [{"name": p["default"], "default": True, "description": DEFAULT_TEXT, "color": ""}]
    for name in p["offered"]:
        try:
            d = definition(name)
            rows.append({"name": name, "default": False, "description": d["description"], "color": d["color"]})
        except ProfileError as e:
            rows.append({"name": name, "default": False, "description": "! %s" % e, "color": ""})
    return rows


def _list(a, name, prof):
    rows = _rows(prof) if isinstance(prof.get("profiles"), dict) and not prof.get("frozen") else []
    if a.json:
        _say(json.dumps(rows, indent=2, ensure_ascii=False))
    elif a.names:
        for r in rows:
            _say(r["name"])
    elif not rows:
        _say("no profiles: project '%s' %s" % (name, "is frozen, so it receives none" if prof.get("frozen") else "declares none"))
    else:
        w = max(len(r["name"]) for r in rows), max(len(r["color"]) for r in rows)
        _say("project %s: %d profile(s), the default is %s" % (name, len(rows), prof["profiles"]["default"]))
        for r in rows:
            _say("  %s  %s  %s" % (r["name"].ljust(w[0]), _paint(r["color"].ljust(w[1]), r["color"]), r["description"]))
    return 0 if rows else 1


def _card(a, name, prof, profile):
    p = prof.get("profiles")
    if not isinstance(p, dict) or prof.get("frozen"):
        _say("forge list: project '%s' has no profiles" % name, err=True)
        return 1
    known = [p["default"]] + list(p["offered"])
    if profile not in known:
        _say("forge list: %s" % suggest.message("profile", "@" + profile, ["@" + n for n in known], " in project '%s'" % name), err=True)
        return 2
    is_default = profile == p["default"]
    try:
        lists = default_lists(prof) if is_default else resolve(name, prof, profile)
    except ProfileError as e:
        _say("forge list: %s" % e, err=True)
        return 2
    row = next(r for r in _rows(prof) if r["name"] == profile)
    lists = {"description": row["description"], "color": row["color"], **lists}
    diff = {} if is_default else differences(lists, default_lists(prof))
    if a.json:
        _say(json.dumps({"project": name, "profile": profile, "default": is_default, **lists, "differs_from_default": diff},
                        indent=2, ensure_ascii=False))
        return 0
    _say("profile %s of project %s%s" % (profile, name, " (the default: %s)" % DEFAULT_TEXT if is_default else ""))
    _say("  description   %s" % lists["description"])
    _say("  color         %s" % _paint(lists["color"], lists["color"]))
    for f in ("skills_keep", "plugins_keep", "servers"):
        _say("  %-13s %s" % (f, ", ".join(lists[f])))
    _say("  permissions   %s" % json.dumps(lists["permissions"], sort_keys=True))
    _say("  env           %s" % json.dumps(lists["env"], sort_keys=True))
    if not is_default:
        _say("differs from the default (%s):" % DEFAULT_TEXT)
        for f, d in diff.items():
            _say("  %-13s %s" % (f, " ".join(["+%s" % x for x in d["added"]] + ["-%s" % x for x in d["removed"]])))
        if not diff:
            _say("  no difference")
    return 0


def cmd_list(a):
    """forge list @ | forge list @NAME [--json] [--names]: the profiles of the project of this directory, or one of them. Exit 0
    it did, 1 the project has no profiles (or is frozen), 2 a bad argument, a folder that is no project or a profile it has not."""
    def usage(why):
        _say("forge list: %s; it takes @ (this project's profiles) or @NAME (one profile)" % why, err=True)
        return 2
    if a.target is None:
        return usage("no argument")
    try:
        profile = parse_at(a.target)
    except ValueError as e:
        return usage(str(e))
    if profile and a.names:
        return usage("--names is for forge list @")
    found = project_here(os.getcwd())
    if not found:
        _say("forge list: %s is not inside a project of forge's registry (a project file forge cannot read is left out of it)"
             % os.getcwd(), err=True)
        return 2
    return _card(a, found[0], found[1], profile) if profile else _list(a, *found)


def _contributes(prof, profile, lists):
    """Whether the profile adds anything of its own to the common layer every project starts from: a skill (a `@SET` expanded),
    a plugin or a server. The common layer is in resolve()'s lists, so they cannot say it."""
    d, row, sk = definition(profile), prof["profiles"]["offered"][profile], _skill_keep()
    names = d["skills"] + row.get("skills", [])
    return bool(sk.expand_extras({profile: names}, sk.SKILL_KEEP.get("sets") or {})[profile]
                or d["plugins"] or row.get("plugins") or lists["servers"])


def _problem(project, prof, profile):
    """None when `profile` of `project` resolves, adds something of its own and has session files that can be built
    (launch.session_files: the --settings and --mcp-config documents, which writes nothing, and both serialise); else why not,
    in one line. A secret the store lacks is named by its NAME: the documents are never printed."""
    from forge import launch  # launch imports this module
    prefix = "profile '%s' of project '%s': " % (profile, project)
    try:
        lists = resolve(project, prof, profile)
        if not _contributes(prof, profile, lists):
            return "resolves to nothing: no skill, plugin or server of its own, only what every project has"
        docs = launch.session_files(project, prof, profile, lists)[:2]
    except ProfileError as e:
        return str(e)[len(prefix):] if str(e).startswith(prefix) else str(e)
    except Exception as e:  # a file the build could not read: a FAIL naming the profile, not a traceback that hides the rest
        return "its session files cannot be built (%s: %s)" % (type(e).__name__, e)
    try:
        for doc in docs:
            json.dumps(doc)
    except (TypeError, ValueError) as e:
        return "its session files are not valid JSON (%s)" % e
    return None


def doctor_row(only=None):
    """The `profiles` row of forge doctor (just project `only`, when given): for each project that declares `profiles` (a frozen
    one receives none and is left out), every offered profile resolves, is not empty and has session files that can be built, and
    `claude` is on PATH (forge start @NAME runs it). A FAIL names `project/profile` and the cause, never a secret's value. How many
    projects and profiles it looked at is in the detail; zero where a project declares profiles is a FAIL, and no project declaring
    them is a SKIP, NOT RUN, NOT ARMED, in which `claude` is not looked for."""
    wanted = {n: p for n, p in sorted(lib.projects().items()) if isinstance(p.get("profiles"), dict) and (only is None or n == only)}
    frozen = [n for n, p in wanted.items() if p.get("frozen")]
    wanted = {n: p for n, p in wanted.items() if n not in frozen}
    note = "; not looked at, frozen (it receives none): %s" % ", ".join(frozen) if frozen else ""
    if not wanted:
        who = "project %s declares no profiles" % only if only else "no project declares profiles"
        return lib.Result("SKIP", "profiles", lib.NOT_ARMED + "%s%s, so no profile was looked at" % (who, note))
    looked, problems = 0, []
    for name, prof in wanted.items():
        for profile in prof["profiles"]["offered"]:  # the profiles looked at
            looked += 1
            why = _problem(name, prof, profile)
            if why:
                problems.append("%s/%s: %s" % (name, profile, why))
    head = "looked at %d project(s) (%s), %d profile(s)" % (len(wanted), ", ".join(wanted), looked)
    if not looked:
        problems.append("a check that saw no profile is not a pass (does profiles.offered of %s hold one?)" % ", ".join(wanted))
    claude = shutil.which("claude", path=os.environ.get("PATH", os.defpath))
    if not claude:
        problems.append("claude is not on PATH: forge start @NAME runs it; install Claude Code or put its folder on PATH")
    if problems:
        return lib.Result("FAIL", "profiles", "%s%s: %s" % (head, note, " | ".join(problems)))
    return lib.Result("PASS", "profiles", "%s%s: each resolves, adds something of its own and has session files that build; claude is at %s"
                      % (head, note, lib.short(claude)))


def session_path(session_id):
    """Where the record of a session started with a profile lives: lib.STATE/profile-sessions/<session id>.json."""
    return os.path.join(lib.STATE, "profile-sessions", session_id + ".json")


def session_record(profile, project, launcher_pid, parent=None):
    """The record of one session, as forge start @NAME writes it: {"profile", "project", "launcher_pid", "at"} (`at` in epoch
    seconds), and `parent` (the parent session's id) only for a session another one started."""
    rec = {"profile": profile, "project": project, "launcher_pid": launcher_pid, "at": round(time.time(), 3)}
    if parent:
        rec["parent"] = parent
    return rec


def write_session(session_id, record):
    """session_path(session_id) holds `record`; atomic and private (0600), like every state file the launcher writes."""
    lib.write_text(session_path(session_id), json.dumps(record, indent=2) + "\n", mode=0o600)
    return session_path(session_id)
