"""Directory marketplaces on the machine: what the framework step and the `local_plugins` step share.

Claude Code loads a plugin from a marketplace folder once ~/.claude/plugins/known_marketplaces.json holds that folder
(measured on 2.1.308: declaring the marketplace in a settings file does not, and `claude plugin install` is not needed).
The registry belongs to the machine, so one `claude plugin marketplace add <folder> --scope local` is enough for every
project, and which project turns the plugin on is `enabledPlugins` in its settings.local.json (written whole by
forge/skills.py from plugins_keep and common_plugins; nothing here touches it).

  * plugin_name, registry_path, registered, register: the primitives. framework.py (one plugin, run in the project's
    folder) and local_step (any number of plugins, run in a temporary folder) both call them.
  * config/forge.json `local_plugins`: a list of forge-owned plugin folders, absolute or ~/..., each a directory marketplace
    whose `name` is the plugin's name (and which lists a plugin of that name). Empty or missing is off: nothing is printed,
    nothing is run, and the `local plugins` row of `forge doctor` is a SKIP. local_step is the generator's step (forge/sync.py,
    in the user-scope part of a run), row is the doctor's.

Why a temporary folder for local_plugins: `--scope local` writes <cwd>/.claude/settings.local.json besides the registry
(measured, a probe in a toy HOME with an empty folder as cwd), and every folder forge could pick is somebody's: a project's
file is generated whole and forge's own is a generated file too. A fresh folder that is removed afterwards changes none.
`--scope user` would write extraKnownMarketplaces in ~/.claude/settings.json, which forge generates from user_settings.

Nothing here removes a registration, and nothing calls `claude plugin install` (it writes enabledPlugins in the user's
settings, so a project that does not list the plugin would get it) or `claude plugin list` (it shows nothing for a plugin
loaded without install, so it is no check)."""
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile

from forge import lib

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ADD_TIMEOUT = 120
FIX = "python3 bin/forge sync --apply"
TEMP = "a temporary folder"


def plugin_name(path):
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


def registry_path(name):
    """The folder the machine's marketplace registry holds `name` at, or None."""
    reg = lib.read_json(os.path.join(lib.HOME, ".claude", "plugins", "known_marketplaces.json"), quiet=True)
    entry = reg.get(name) if isinstance(reg, dict) else None
    src = entry.get("source") if isinstance(entry, dict) else None
    if isinstance(src, dict) and isinstance(src.get("path"), str):
        return os.path.normpath(src["path"])
    return None


def registered(name, path):
    """Whether the machine's registry already holds the marketplace `name` at `path`."""
    return registry_path(name) == os.path.normpath(path)


def register(apply, label, name, path, cwd=None):
    """The lines for one `claude plugin marketplace add <path> --scope local` while the registry lacks it: none when it is
    there; the line it would run in a dry-run; on --apply the run (in `cwd`, or in a temporary folder removed afterwards
    when there is none) and what came of it. A `!` line says what was not done and the command to run by hand."""
    if registered(name, path):
        return []
    cmd = ["claude", "plugin", "marketplace", "add", path, "--scope", "local"]
    text = " ".join(shlex.quote(a) for a in cmd)
    where = lib.short(cwd) if cwd else TEMP
    if not apply:
        return ["   %s -> would run `%s` in %s: the marketplace is not in the machine's registry" % (label, text, where)]
    exe = shutil.which("claude")
    fix = "run `%s` in %s" % (text, where)
    if exe is None:
        return ["   ! %s -> `claude` is not on PATH, so the marketplace is not registered on this machine: %s" % (label, fix)]
    try:
        if cwd:
            r = subprocess.run([exe] + cmd[1:], cwd=cwd, capture_output=True, text=True, timeout=ADD_TIMEOUT)
        else:
            with tempfile.TemporaryDirectory(prefix="forge-marketplace-") as tmp:
                r = subprocess.run([exe] + cmd[1:], cwd=tmp, capture_output=True, text=True, timeout=ADD_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return ["   ! %s -> `%s` did not finish (%s): %s" % (label, text, type(e).__name__, fix)]
    if r.returncode:
        last = (r.stderr.strip() or r.stdout.strip()).splitlines()[-1:] or ["no output"]
        return ["   ! %s -> `%s` exited %d (%s): %s" % (label, text, r.returncode, last[0][:200], fix)]
    return ["   %s -> registered the marketplace on this machine: `%s`" % (label, text)]


def local_entries():
    """([(name, folder)], [why not]) for config/forge.json `local_plugins`. A folder that cannot be served is one
    message and left out; the rest still go. Each message starts with what it is about, as a `!` line needs."""
    value = lib.settings().get("local_plugins")
    if value is None or value == []:
        return [], []
    if not isinstance(value, list):
        return [], ["local_plugins in config/forge.json is not a list of plugin folders"]
    entries, errors, seen = [], [], {}
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item:
            errors.append("local_plugins[%d] in config/forge.json is not a folder (a string)" % i)
            continue
        folder = os.path.expanduser(item)
        if not os.path.isabs(folder):
            errors.append("local_plugins[%d] %s is not absolute (or ~/...)" % (i, item))
            continue
        folder = os.path.normpath(folder)
        if not os.path.isdir(folder):
            errors.append("local_plugins[%d] %s is not a directory" % (i, lib.short(folder)))
            continue
        name, why = plugin_name(folder)
        if why:
            errors.append("local_plugins[%d]: %s" % (i, why))
        elif name in seen:
            errors.append("local_plugins: %s and %s are both the marketplace %s" % (lib.short(seen[name]), lib.short(folder), name))
        else:
            seen[name] = folder
            entries.append((name, folder))
    return entries, errors


def local_step(ctx):
    """The lines of the `local_plugins` step: one registration per folder the registry lacks, a `!` line per folder that
    cannot be served. Empty when the key is off or everything is registered."""
    entries, errors = local_entries()
    lines = ["   ! local plugin -> " + e for e in errors]
    for name, folder in entries:
        lines += register(ctx.apply, "local plugin " + name, name, folder)
    return lines


def row():
    """The `local plugins` row of forge doctor: a SKIP when `local_plugins` is empty or missing, a FAIL naming the fix when
    a folder cannot be served, is not registered, or the registry holds it at another path, else a PASS that says how many
    it looked at and where each is registered."""
    entries, errors = local_entries()
    if not entries and not errors:
        return lib.Result("SKIP", "local plugins", lib.NOT_ARMED + "local_plugins in config/forge.json is empty or missing, so no local plugin was looked at")
    problems = list(errors)
    for name, folder in entries:
        at = registry_path(name)
        if at is None:
            problems.append("%s (%s) is not in the machine's marketplace registry" % (name, lib.short(folder)))
        elif at != folder:
            problems.append("%s is registered at %s, not at %s" % (name, lib.short(at), lib.short(folder)))
    if problems:
        fix = ("correct local_plugins in config/forge.json (the folder, its marketplace.json), then " if errors else "") + FIX
        return lib.Result("FAIL", "local plugins", "%s -- %s" % ("; ".join(problems), fix))
    return lib.Result("PASS", "local plugins", "looked at %d local plugin(s), each registered at its path: %s" % (
        len(entries), ", ".join("%s (%s)" % (n, lib.short(f)) for n, f in entries)))
