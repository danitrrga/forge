"""The framework step of the generator: for a profile with `framework: true`, forge turns the framework's plugin
on in that project; with `false` or the field absent it writes nothing and takes out what it wrote itself.

What a `true` profile gets, all of it per project and none of it at user scope:
  * <project>/.claude/<plugin>.json, the one file the plugin reads (schema 1: project, factory, weekly, models,
    limits, rounds, linear.labels, integrations, paths). It is generated and rewritten on every sync.
  * one managed block at the end of the project's ignore file (forge/fwxignore.py): it ignores that file and
    .claude/worktrees/, and un-ignores `.fwx/**/*.md` after the project's own `*.md`, so the framework's documents are
    tracked (it goes to .git/info/exclude for a profile with `writes_tracked_files: false`, whose own ignore file forge
    never writes). A profile that turns the framework off has exactly the block taken out, and `framework_ignore_block:
    false` (the project keeps its documents out of its git on purpose) writes and checks no block and takes one out too.
  * in settings.local.json, `enabledPlugins["<plugin>@<plugin>"] = true` and `extraKnownMarketplaces.<plugin>`
    (written by skills.write_settings_local, which this module feeds through a Plan), both owned claims; and
    `env.LINEAR_API_KEY` when config/secrets.json has the secret, else one line that is not a `!`.
  * in settings.local.json, `permissions.allow` gets the `allow` rules of config/framework-permissions.json (3.6, schema 1:
    narrow rules measured as denied by the auto-mode classifier, each with the roles that use it), and
    `permissions.additionalDirectories` the main checkout, so a session in a linked worktree may reach it. Both go in
    as the profile's own permissions do (with_permissions), so forge/skills.py claims them item by item, writes them and
    takes them out when the profile turns the framework off; a rule put by hand stays. The list is linted first
    (permission_errors): a rule that is too broad, one that overlaps an `only_daniel` prefix or a `production.commands`
    of the profile, a role that is not a key of `framework.models`, or a file that is not schema 1 is one `!` line and
    nothing is written for that profile. Without the file the step prints `NOT RUN, NOT ARMED` and writes only the
    main checkout.
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
only while it still is what forge wrote; one edited since stays and is named on a `!` line, once. The ignore block
goes the same way (fwxignore.drop); a single `.claude/<plugin>.json` line an earlier forge wrote is folded into it."""
import copy
import collections
import json
import os
import re

from forge import fwxignore, lib, marketplace, owned

PART = "framework"
LINEAR_KEY = "LINEAR_API_KEY"
# The four integrations the plugin's file reports (§ the file's `integrations`); a name forge has no switch for yet is false.
INTEGRATIONS = ("consent", "notifications", "agent_browser", "mempalace")
PERMISSIONS_FILE = "framework-permissions.json"
PERMISSIONS_SCHEMA = 1
# A command that runs whatever follows it: `Bash(<one of these>:*)` allows any program or package script.
RUNNERS = frozenset("""python python3 node nodejs deno bun ruby perl php lua bash sh zsh fish dash env sudo xargs eval exec
                       npm npx pnpm pnpx yarn pip pip3 pipx uv uvx poetry cargo gem bundle composer mise""".split())
RULE = re.compile(r"^([A-Za-z0-9_.*-]+)(?:\((.*)\))?$", re.S)

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
    return marketplace.plugin_name(path)


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
            "default_branch_protected": prof.get("default_branch_protected") is True,
            "ui_image": copy.deepcopy(prof.get("ui_image")),
        },
        "factory": factory,
        "weekly": table("weekly"),
        "models": table("models"),
        "limits": table("limits"),
    }
    if prof.get("worktree_setup"):  # written only when set: a profile without it leaves the file as it was (fwx reads the empty list)
        doc["project"]["worktree_setup"] = list(prof["worktree_setup"])
    for key in ("rounds", "critique_rounds_unattended"):
        if key in section:
            doc[key] = section[key]
    if isinstance(section.get("walk"), dict):  # the plugin validates its own keys; a section without one leaves it out
        doc["walk"] = table("walk")
    if isinstance(section.get("open"), dict):  # the user's opener ({"command": argv with {url} and {path}}), as is
        doc["open"] = table("open")
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


# What the permissions step does for one profile, decided without writing: the rules to add as (rule, roles), the
# directories to add, the lines to print once settings.local.json is written, and the `!` lines of a list that failed
# the lint (then nothing is written for the profile).
Perms = collections.namedtuple("Perms", "rules dirs lines errors")
NO_PERMS = Perms((), (), (), ())


def _norm(rule):
    """The literal head of a rule, to compare prefixes: `Bash(git push origin fwx/*)` -> `Bash(git push origin fwx/`,
    `Bash(git:*)` -> `Bash(git`."""
    s = rule[:-1] if rule.endswith(")") else rule
    for tail in (":*", "*"):
        if s.endswith(tail):
            return s[:-len(tail)]
    return s


def _broad(rule):
    """Why `rule` is too broad (or not a rule), or None: a tool without specifier, a `*` or empty specifier (so `Agent`,
    `Monitor` and `Workflow` need a name), a bare MCP server, an interpreter or package manager followed only by a
    wildcard. A bare `mcp__<server>__<tool>` names one tool and is narrow."""
    m = RULE.match(rule)
    if not m:
        return "is not a permission rule (`Tool` or `Tool(specifier)`)"
    tool, spec = m.groups()
    if spec is None:
        if tool.startswith("mcp__") and tool.count("__") >= 2 and "*" not in tool:
            return None
        return "has no specifier, so it allows every use of %s" % tool
    if spec.strip() in ("", "*", ":*"):
        return "allows every use of %s: the specifier is empty or `*`" % tool
    if tool == "Bash":
        body = spec.strip()
        wild = body.endswith("*")
        body = _norm("Bash(" + body)[len("Bash("):].strip()
        if wild and body in RUNNERS:
            return "allows any `%s` command (an interpreter or package manager followed only by a wildcard)" % body
    return None


def permission_errors(doc, roles, production):
    """The errors of a framework-permissions list, as text, [] when it is clean (3.6 Appendix C): `doc` is the parsed
    file, `roles` the keys of `framework.models`, `production` the profile's `production.commands`. Shape (schema 1,
    `allow` a list of rows with a `rule` string and non-empty `roles`), then per rule: too broad, overlapping an
    `only_daniel` prefix or a production command (one is a prefix of the other), a role that is not in `roles`."""
    if not isinstance(doc, dict):
        return ["the list is not a JSON object"]
    errs = []
    if doc.get("schema") != PERMISSIONS_SCHEMA:
        errs.append("schema is %r, not %d" % (doc.get("schema"), PERMISSIONS_SCHEMA))
    if not isinstance(doc.get("allow"), list):
        return errs + ["allow is not a list"]
    for key in ("not_allowed", "only_daniel"):
        if key in doc and not (isinstance(doc[key], list) and all(isinstance(r, dict) for r in doc[key])):
            errs.append("%s is not a list of objects" % key)
    prefixes = []
    for r in doc.get("only_daniel") if isinstance(doc.get("only_daniel"), list) else ():
        if isinstance(r, dict) and isinstance(r.get("prefix"), str) and r["prefix"].strip():
            prefixes.append(r["prefix"])
        else:
            errs.append("an only_daniel row has no `prefix` string")
    for i, r in enumerate(doc["allow"]):
        rule = r.get("rule") if isinstance(r, dict) else None
        if not isinstance(rule, str) or not rule.strip():
            errs.append("allow[%d] has no `rule` string" % i)
            continue
        why = _broad(rule)
        if why:
            errs.append("`%s` %s" % (rule, why))
            continue
        head = _norm(rule)
        for pre in prefixes:
            if head.startswith(pre) or pre.startswith(head):
                errs.append("`%s` overlaps the only_daniel prefix `%s`" % (rule, pre))
        if rule.startswith("Bash("):
            body = head[len("Bash("):]
            for cmd in production:
                if isinstance(cmd, str) and cmd and (body.startswith(cmd) or cmd.startswith(body)):
                    errs.append("`%s` overlaps the production command `%s` of the profile" % (rule, cmd))
        have = r.get("roles")
        if not (isinstance(have, list) and have and all(isinstance(x, str) for x in have)):
            errs.append("`%s` has no `roles` (a non-empty list of keys of framework.models)" % rule)
        else:
            for role in have:
                if role not in roles:
                    errs.append("`%s` names the role `%s`, which is not a key of framework.models" % (rule, role))
    return errs


def permissions(prof, p, path):
    """The permissions step for this profile: the main checkout always (a session in a linked worktree reaches the
    main checkout through `permissions.additionalDirectories`), and the `allow` rules of the list at `path`. The
    list missing is one NOT RUN, NOT ARMED line; a list that fails permission_errors (or does not parse) is the
    `!` lines of `errors`, and the caller writes nothing for the profile. `lines` are the `+ allow` and
    `+ additionalDirectories` lines for what the file does not hold yet, printed once settings.local.json is written."""
    if not p.on:
        return NO_PERMS
    main = os.path.realpath(prof["project_path"])
    cur = lib.read_json(os.path.join(prof["project_path"], ".claude", "settings.local.json"), quiet=True)
    cur = cur.get("permissions") if isinstance(cur, dict) else None
    cur = cur if isinstance(cur, dict) else {}
    have_allow = cur.get("allow") if isinstance(cur.get("allow"), list) else []
    have_dirs = cur.get("additionalDirectories") if isinstance(cur.get("additionalDirectories"), list) else []
    lines = []
    rules = {}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        doc = None
        lines.append("   framework permissions -> NOT RUN, NOT ARMED: config/%s missing" % PERMISSIONS_FILE)
    except (OSError, ValueError) as e:
        return NO_PERMS._replace(errors=("   ! framework permissions -> config/%s cannot be read (%s) -- nothing written for this project"
                                         % (PERMISSIONS_FILE, e),))
    if doc is not None:
        section = lib.settings().get("framework")
        models = section.get("models") if isinstance(section, dict) else None
        production = (prof.get("production") or {}).get("commands") or []
        errs = permission_errors(doc, set(models) if isinstance(models, dict) else set(), production)
        if errs:
            return NO_PERMS._replace(errors=tuple("   ! framework permissions -> config/%s: %s -- nothing written for this project"
                                                  % (PERMISSIONS_FILE, e) for e in errs))
        for r in doc["allow"]:
            rules.setdefault(r["rule"], list(dict.fromkeys(rules.get(r["rule"], []) + r["roles"])))
    out = [("  + allow %s  (framework: %s)" % (rule, ", ".join(roles))) for rule, roles in rules.items() if rule not in have_allow]
    if main not in have_dirs:
        out.append("  + additionalDirectories %s  (framework: the main checkout, for a session in a linked worktree)" % main)
    return Perms(tuple(rules.items()), (main,), tuple(lines + out), ())


def with_permissions(prof, perms):
    """`prof` with the step's rules added to its `permissions.allow` and its directories to
    `permissions.additionalDirectories`, after what the profile declares itself; `prof` itself with nothing to add."""
    if not perms.rules and not perms.dirs:
        return prof
    cur = dict(prof.get("permissions") or {})
    for key, add in (("allow", [r for r, _ in perms.rules]), ("additionalDirectories", list(perms.dirs))):
        if add:
            have = cur.get(key)
            cur[key] = list(dict.fromkeys((have if isinstance(have, list) else []) + add))
    return dict(prof, permissions=cur)


def _registered(p):
    """Whether the machine's marketplace registry already holds this plugin's marketplace at its path."""
    return marketplace.registered(p.name, p.path)


def _register(ctx, p, ppath):
    """The branch-B line: `claude plugin marketplace add` once while the machine's registry lacks the marketplace,
    run in the project's folder (forge/marketplace.py is the shared code)."""
    return marketplace.register(ctx.apply, "framework", p.name, p.path, ppath)


def _write_file(ctx, prof, p, name):
    """The generated file and the ignore block that keeps it out of git status. Returns the lines to print."""
    ppath = prof["project_path"]
    owner = prof.get("project") or name
    short = lib.short(p.file)
    if prof.get("framework_ignore_block") is False:  # kept out of this git on purpose: nothing to write, nothing to ask git
        ignored, block = True, fwxignore.switched_off(ctx.apply, ppath, owner)
    else:
        try:
            ignored, block = fwxignore.ensure(ctx.apply, ppath, p.name, lib.repo_owns_tracked_files(prof), owner)
        except lib.Unreadable as e:  # the project's .gitignore
            return ["   ! framework -> %s NOT written: %s unreadable (%s)" % (short, lib.short(e.path), e.reason)]
    if not ignored:
        return block + ["   ! framework -> %s NOT written: it is not known to be ignored" % short]
    if os.path.islink(p.file):
        return block + ["   ! framework -> %s NOT written: it is a link, which forge never writes through" % short]
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
    return ["   framework -> %s (%s)" % (short, state)] + block


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
    if not p.on:
        out += fwxignore.drop(ctx.apply, ppath, prof.get("project") or name)
    return out + _drop_stale(ctx, ppath, p.file if p.on else None)
