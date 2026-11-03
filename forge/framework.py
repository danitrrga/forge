"""The framework step of the generator: for a profile with `framework: true`, forge turns the framework's plugin
on in that project; with `false` or the field absent it writes nothing and takes out what it wrote itself.

What a `true` profile gets, all of it per project and none of it at user scope:
  * <project>/.claude/<plugin>.json, the one file the plugin reads (schema 1: project, factory, weekly, models,
    limits, rounds, linear.labels, integrations, paths). It is generated: git-ignored (the ignore line goes to
    .git/info/exclude for a profile with `writes_tracked_files: false`) and rewritten on every sync.
  * in settings.local.json, `enabledPlugins["<plugin>@<plugin>"] = true` and `extraKnownMarketplaces.<plugin>`
    (written by skills.write_settings_local, which this module feeds through a Plan), both owned claims; and
    `env.LINEAR_API_KEY` when config/secrets.json has the secret, else one line that is not a `!`.
  * on --apply, one `claude plugin marketplace add <path> --scope local` per machine, run from the project's
    folder, while ~/.claude/plugins/known_marketplaces.json does not hold the marketplace at that path. Declaring
    the marketplace in settings.local.json alone does not load the plugin (measured on 2.1.308: the registry
    entry is what makes the next session install it). A dry-run only prints the line. Turning the framework off
    leaves that entry: it belongs to the machine, every project shares it, and without enabledPlugins it loads
    nothing; `claude plugin marketplace remove <plugin>` undoes it.

The plugin's name is not in this code. It is the `name` of <plugin_source.path>/.claude-plugin/marketplace.json
(config/forge.json `framework.plugin_source`, a `directory` source until the repository is published), and that
marketplace must list a plugin of the same name. The file is `.claude/<name>.json` and the plugin `<name>@<name>`.

A `true` profile that cannot be served gets one `!` line and nothing written for the framework: no `plugins_keep`
(enabledPlugins is written whole, and only with plugins_keep), no plugin_source, a source that is not a directory,
a folder without a marketplace.json, a marketplace without a plugin of its name, a name that is not a plain
identifier (it becomes a file name). Such a profile is read as off by settings.local.json (the two keys go,
because the plugin cannot load from a source that is wrong anyway), and its generated file is left where it is.

Removal is by claim (forge/owned.py): the generated file is a `file` claim of part "framework", and is deleted
only while it still is what forge wrote; one edited since stays and is named on a `!` line, once. The ignore line
stays (it is claimed, so `forge uninstall` takes it out)."""
import copy
import collections
import json
import os
import re
import shlex
import shutil
import subprocess

from forge import lib, owned

PART = "framework"
LINEAR_KEY = "LINEAR_API_KEY"
# The four integrations the plugin's file reports (§ the file's `integrations`); a name forge has no switch for yet is false.
INTEGRATIONS = ("consent", "notifications", "agent_browser", "mempalace")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ADD_TIMEOUT = 120

# `on` False and `error` None is a profile that does not use the framework; `error` set is one that cannot be served.
Plan = collections.namedtuple("Plan", "on error name plugin source path file doc")
OFF = Plan(False, None, None, None, None, None, None, None)


def _error(why):
    return OFF._replace(error=why)


def _source():
    """(plugin_source with `~` expanded, or None, why not). Only a `directory` source with an absolute path."""
    section = lib.settings().get("framework")
    src = section.get("plugin_source") if isinstance(section, dict) else None
    if not isinstance(src, dict):
        return None, "framework.plugin_source is missing in config/forge.json"
    if src.get("source") != "directory":
        return None, "framework.plugin_source is a `%s` source; only `directory` is supported until the repository is published" % src.get("source")
    path = src.get("path")
    if not isinstance(path, str) or not path:
        return None, "framework.plugin_source.path is not a path"
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        return None, "framework.plugin_source.path %s is not absolute (or ~/...)" % path
    return dict(src, path=os.path.normpath(path)), None


def _name(path):
    """(the plugin's name, why not): the marketplace's `name`, which the marketplace must list as a plugin too."""
    mf = os.path.join(path, ".claude-plugin", "marketplace.json")
    try:
        with open(mf, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None, "%s does not exist: the plugin source is not a marketplace" % lib.short(mf)
    except (OSError, ValueError) as e:
        return None, "%s cannot be read (%s)" % (lib.short(mf), e)
    name = doc.get("name") if isinstance(doc, dict) else None
    if not isinstance(name, str) or not NAME.match(name):
        return None, "%s has no `name` that is a plain identifier (letters, digits, . _ -)" % lib.short(mf)
    listed = doc.get("plugins")
    if not (isinstance(listed, list) and any(isinstance(p, dict) and p.get("name") == name for p in listed)):
        return None, "%s lists no plugin called %s, its own name" % (lib.short(mf), name)
    return name, None


def _remote_name(ppath):
    """The last segment of origin's URL without `.git`; the folder's name without a remote."""
    url = lib._git_out(ppath, "remote", "get-url", "origin")
    seg = re.split(r"[/:]", url.rstrip("/"))[-1] if url else ""
    seg = seg[:-4] if seg.endswith(".git") else seg
    return seg or os.path.basename(os.path.realpath(ppath))


def _default_branch(ppath):
    """origin/HEAD's branch; else the checkout's own; None where git cannot say (no repository, detached HEAD)."""
    ref = lib._git_out(ppath, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if ref:
        return ref.split("/", 1)[1] if "/" in ref else ref
    return lib._git_out(ppath, "symbolic-ref", "--short", "HEAD") or None


def _document(prof, name, ppath):
    """The text of .claude/<plugin>.json as a dict: the profile's fields (a field it lacks is the default), the
    `framework` section of config/forge.json (a key it lacks is left out, so the plugin's own defaults apply), and
    the integrations' switches. `project.linear_project` is the profile's `linear_project`, else the remote's name.
    The file has no slot for a label a project's issues carry, so a profile can move the Linear project only."""
    section = lib.settings().get("framework")
    section = section if isinstance(section, dict) else {}

    def table(key):
        v = section.get(key)
        return copy.deepcopy(v) if isinstance(v, dict) else {}

    factory = {"mode": prof.get("factory", "off"), "ui_bugs": prof.get("factory_ui_bugs") is True}
    factory.update({k: v for k, v in table("factory").items() if k not in factory})
    linear = table("linear")
    linear["labels"] = linear["labels"] if isinstance(linear.get("labels"), dict) else {}
    doc = {
        "schema": 1,
        "framework": True,
        "project": {
            "name": prof.get("project") or name,
            "main_checkout": os.path.realpath(ppath),
            "linear_project": prof.get("linear_project") or _remote_name(ppath),
            "default_branch": _default_branch(ppath),
            "factory_branch": "factory",
            "checks": list(prof.get("checks") or []),
            "protected_paths": list(prof.get("protected_paths") or []),
            "production": copy.deepcopy(prof.get("production") or {"branches": [], "commands": []}),
            "verdict_command": prof.get("verdict_command"),
            "ui": prof.get("ui") is True,
            # Fields the later parts of the framework add to profiles: the schema's defaults until a profile has them.
            "checks_quick": list(prof.get("checks_quick") or []),
            "app_run": copy.deepcopy(prof.get("app_run")),
            "surface_context": copy.deepcopy(prof.get("surface_context") or {}),
        },
        "factory": factory,
        "weekly": table("weekly"),
        "models": table("models"),
        "limits": table("limits"),
    }
    for key in ("rounds", "critique_rounds_unattended"):
        if key in section:
            doc[key] = section[key]
    doc["linear"] = linear
    doc["integrations"] = {n: (lib.on(n) if n in lib.INTEGRATIONS else False) for n in INTEGRATIONS}
    doc["paths"] = table("paths")
    return doc


def plan(prof, name):
    """What the framework step does for this profile, decided without writing anything. `name` is the profile's
    file name, the project's name when the profile has none."""
    if prof.get("framework") is not True:
        return OFF
    if not prof.get("plugins_keep"):
        return _error("framework is true but the profile has no plugins_keep: the plugin is turned on through "
                      "enabledPlugins, which forge writes whole and only with plugins_keep")
    src, why = _source()
    if why:
        return _error(why)
    plugin, why = _name(src["path"])
    if why:
        return _error(why)
    ppath = prof["project_path"]
    return Plan(True, None, plugin, "%s@%s" % (plugin, plugin), src, src["path"],
                os.path.join(ppath, ".claude", plugin + ".json"), _document(prof, name, ppath))


def with_env(prof, p, secrets):
    """`prof` with LINEAR_API_KEY=${LINEAR_API_KEY} added to its env when the framework is on and the secret
    exists (write_settings_local resolves it, as it does every `${NAME}`); `prof` itself otherwise."""
    if not p.on or not secrets.get(LINEAR_KEY):
        return prof
    return dict(prof, env=dict(prof.get("env") or {}, **{LINEAR_KEY: "${%s}" % LINEAR_KEY}))


def _registered(p):
    """Whether the machine's marketplace registry already holds this plugin's marketplace at its path."""
    reg = lib.read_json(os.path.join(lib.HOME, ".claude", "plugins", "known_marketplaces.json"), quiet=True)
    entry = reg.get(p.name) if isinstance(reg, dict) else None
    src = entry.get("source") if isinstance(entry, dict) else None
    return isinstance(src, dict) and isinstance(src.get("path"), str) and os.path.normpath(src["path"]) == p.path


def _register(ctx, p, ppath):
    """The branch-B line: `claude plugin marketplace add` once while the machine's registry lacks the marketplace."""
    if _registered(p):
        return []
    cmd = ["claude", "plugin", "marketplace", "add", p.path, "--scope", "local"]
    text = " ".join(shlex.quote(a) for a in cmd)
    if not ctx.apply:
        return ["   framework -> would run `%s` in %s: the marketplace is not in the machine's registry" % (text, lib.short(ppath))]
    exe = shutil.which("claude")
    fix = "run `%s` in %s" % (text, lib.short(ppath))
    if exe is None:
        return ["   ! framework -> `claude` is not on PATH, so the marketplace is not registered on this machine: " + fix]
    try:
        r = subprocess.run([exe] + cmd[1:], cwd=ppath, capture_output=True, text=True, timeout=ADD_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return ["   ! framework -> `%s` did not finish (%s): %s" % (text, type(e).__name__, fix)]
    if r.returncode:
        last = (r.stderr.strip() or r.stdout.strip()).splitlines()[-1:] or ["no output"]
        return ["   ! framework -> `%s` exited %d (%s): %s" % (text, r.returncode, last[0][:200], fix)]
    return ["   framework -> registered the marketplace on this machine: `%s`" % text]


def _write_file(ctx, prof, p, name):
    """The generated file and its ignore line. Returns the lines to print."""
    ppath = prof["project_path"]
    entry = ".claude/%s.json" % p.name
    owner = prof.get("project") or name
    short = lib.short(p.file)
    try:
        ignored, gi = lib.ensure_ignored(ctx.apply, ppath, entry, lib.repo_owns_tracked_files(prof))
    except lib.Unreadable as e:  # the project's .gitignore
        return ["   ! framework -> %s NOT written: %s unreadable (%s)" % (short, lib.short(e.path), e.reason)]
    if not ignored:
        return ["   ! framework -> %s NOT written%s" % (short, gi)]
    if os.path.islink(p.file):
        return ["   ! framework -> %s NOT written: it is a link, which forge never writes through" % short]
    owned.claim_ignore_line(ctx.apply, ppath, entry, gi, lib.repo_owns_tracked_files(prof), PART, owner)
    text = lib.dumps(p.doc) + "\n"
    if lib.holds(p.file, text):
        state = "already current"
    else:
        state = ("updated" if os.path.exists(p.file) else "created") if ctx.apply else (
            "would update" if os.path.exists(p.file) else "would create")
        if ctx.apply:
            os.makedirs(os.path.dirname(p.file), exist_ok=True)
            lib.write_text(p.file, text)
    owned.record(p.file, [owned.claim("file", [], p.doc, owner)], ctx.apply, part=PART)
    return ["   framework -> %s (%s)%s" % (short, state, gi)]


def _drop_stale(ctx, ppath, keep):
    """Take out the generated files this project's earlier runs claimed (a `file` claim of part "framework" in
    <project>/.claude), except `keep`: the one still wanted. Deleted while unchanged; one edited stays, named
    once, and its claim goes."""
    out, claims = [], owned.load()[0]
    here = os.path.join(ppath, ".claude")
    for f in sorted(claims):
        mine = [c for c in claims[f] if c.get("part") == PART and c["kind"] == "file"]
        if os.path.dirname(f) != here or f == keep or not mine:
            continue
        found, value = owned.current(f, mine[0])
        if found and owned.removable(mine[0], value):
            out.append("   framework -> %s (%s)" % (lib.short(f), "removed" if ctx.apply else "would remove"))
            if ctx.apply:
                lib.unlink(f)
        elif found:
            out.append("  ! framework -> %s was edited by hand, left in place" % lib.short(f))
        owned.record(f, [], ctx.apply, part=PART)
    return out


def write(ctx, prof, p, name, secrets):
    """The framework step after settings.local.json is written: the lines to print. A profile that is off has the
    files it wrote earlier taken out; one that cannot be served says why and is left as it is."""
    ppath = prof["project_path"]
    if p.error:
        return ["   ! framework -> %s -- nothing written for the framework in this project" % p.error]
    out = []
    if p.on:
        out += _write_file(ctx, prof, p, name)
        if not secrets.get(LINEAR_KEY):
            out.append("   linear key -> NOT RUN, NOT ARMED: %s is not in config/secrets.json (%s linear exits 2)" % (LINEAR_KEY, p.name))
        out += _register(ctx, p, ppath)
    return out + _drop_stale(ctx, ppath, p.file if p.on else None)
