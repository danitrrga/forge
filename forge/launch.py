"""forge start: claude started for one kind of session.

forge start NAME [ARGS...]  claude started with the environment a named launcher declares in config/forge.json
(`launchers`: {name: {"env": {VAR: value}}}). The process is replaced (os.execvpe), so the terminal that ran it holds
claude and nothing of forge stays behind.

forge start @NAME [--dry-run] [ARGS...]  claude started in the project of the current directory with its session profile
NAME (forge/profiles.py), through per-process flags and no shared file: `--settings` carries the skills, plugins,
permissions and env of the profile, `--strict-mcp-config --mcp-config` its servers, and a new session gets `--session-id` and
a record (profiles.session_record). Nothing of the project is written and neither is ~/.claude.json, so two sessions of one
project can run two profiles at once. Both files are state under lib.STATE, regenerated at every start (the servers' file
holds resolved secrets, so both are 0600). ARGS may not carry --settings, --mcp-config or --strict-mcp-config: the profile sets them
(the last --settings would win and replace the profile). claude runs as a child and its exit code is ours. `forge start @` lists the
project's profiles."""
import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import uuid

from forge import framework, lib, mcp, profiles, skills, suggest

# claude's own flags that mean the session is not a new one, or already has the id the user chose: no `--session-id` of ours.
NOT_NEW = ("-r", "--resume", "-c", "--continue", "--session-id", "--from-pr")
PROFILE_FLAGS = ("--settings", "--mcp-config", "--strict-mcp-config")  # the flags a profile start sets itself
SESSION_ID = "NEW-SESSION-UUID"  # what --dry-run prints where a start puts a fresh uuid4


def _launchers(doc):
    """The validated `launchers` table, or the message of the first thing wrong, naming its key."""
    table = doc.get("launchers", {})
    if not isinstance(table, dict):
        return None, "launchers is %s, not an object" % type(table).__name__
    for name, launcher in table.items():
        if not isinstance(launcher, dict):
            return None, "launchers.%s is %s, not an object" % (name, type(launcher).__name__)
        for key in launcher:
            if key != "env":
                return None, "launchers.%s.%s: only env is known" % (name, key)
        env = launcher.get("env", {})
        if not isinstance(env, dict):
            return None, "launchers.%s.env is %s, not an object" % (name, type(env).__name__)
        for var, value in env.items():
            if not var or "=" in var or "\0" in var:
                return None, "launchers.%s.env: %r is not a variable name" % (name, var)
            if not isinstance(value, str) or "\0" in value:
                return None, "launchers.%s.env.%s is not a string" % (name, var)
    return table, None


def _refuse(why):
    print("! forge start: %s" % why, file=sys.stderr)
    return 2


def new_session(args):
    """Whether claude, started with `args`, begins a session whose id we pick: not a resume, not a continue, and no id of the
    user's own. Flags after `--` are the prompt's text."""
    for arg in args:
        if arg == "--":
            break
        if arg in NOT_NEW or arg.startswith(tuple(f + "=" for f in NOT_NEW if f.startswith("--"))):
            return False
    return True


def _secret(value, secrets, errors, what):
    """`value` with a `${NAME}` replaced by the secret NAME (never printed by a caller), and whether it was one."""
    m = mcp.VARRE.match(value) if isinstance(value, str) else None
    if not m:
        return value, False
    got = secrets.get(m.group(1))
    if got in ("", None):
        errors.append("%s -> secret %s is EMPTY/missing" % (what, m.group(1)))
        return value, True
    return got, True


def session_files(project, prof, profile, lists):
    """(the --settings document, the --mcp-config document, the env keys whose value is a secret) of a profile's `lists`
    (profiles.resolve), or raises profiles.ProfileError saying what could not be resolved. Nothing is written."""
    ppath = prof["project_path"]
    keep = set(lists["skills_keep"])
    on_machine = skills.global_skills() | skills.neighbour_skills(ppath)
    own = set(skills.skill_dirs(os.path.join(ppath, ".claude", "skills")))
    # The profile's skills on, every other global (or neighbouring) skill off, the project's own left as they are: skillOverrides
    # merges by key with settings.local.json, so a skill left unnamed keeps what the project's file says and `on` beats it.
    overrides = {} if "*" in keep else {s: "off" for s in sorted(on_machine - own - keep)}
    overrides.update({s: "on" for s in sorted(keep - {"*"})})
    # enabledPlugins merges by key with settings.local.json (measured), so a plugin this file leaves unnamed keeps what the project's
    # file says: every plugin of the machine is named here, the profile's on and the rest off, and the profile's set is what holds.
    on = set(lists["plugins_keep"])
    fw = framework.plan(prof, project)
    if fw.on and not fw.error:
        on.add(fw.plugin)  # the framework's plugin is the project's, whatever the profile
    enabled = {p: p in on for p in skills.plugin_universe()}
    enabled.update({p: True for p in on})
    registry = lib.read_json(os.path.join(lib.ROOT, "config", "mcp-registry.json")).get("servers") or {}
    secrets = {k: v for k, v in lib.read_json(os.path.join(lib.ROOT, "config", "secrets.json")).items() if not k.startswith("_")}
    errors, servers, env, from_secrets = [], {}, {}, set()
    for name in lists["servers"]:
        servers[name] = mcp.resolved_server(name, registry[name], secrets, errors)
    for key, value in lists["env"].items():
        env[key], secret = _secret(value, secrets, errors, "env %s" % key)
        if secret:
            from_secrets.add(key)
    if errors:
        raise profiles.ProfileError("profile '%s' of project '%s': %s" % (profile, project, "; ".join(errors)))
    doc = {"skillOverrides": overrides, "enabledPlugins": enabled}
    perms = mcp.with_denied_tools({"permissions": lists["permissions"]}, lists["servers"], registry)["permissions"]
    if perms:
        doc["permissions"] = perms
    if env:
        doc["env"] = env
    return doc, {"mcpServers": servers}, from_secrets


def _describe(doc, from_secrets):
    """What a dry-run says of the --settings document: its lists by name, and the env keys without a secret's value."""
    on = sorted(s for s, v in doc["skillOverrides"].items() if v == "on")
    off = [s for s, v in doc["skillOverrides"].items() if v == "off"]
    plugins = sorted(p for p, v in doc["enabledPlugins"].items() if v)
    return ["skills on: %s; %d off" % (", ".join(on) or "none", len(off)),
            "plugins on: %s; %d off" % (", ".join(plugins) or "none", len(doc["enabledPlugins"]) - len(plugins)),
            "permissions: %s" % json.dumps(doc.get("permissions", {}), sort_keys=True),
            "env: %s" % (", ".join("%s%s" % (k, " (a secret)" if k in from_secrets else "=" + v) for k, v in sorted(doc.get("env", {}).items())) or "none")]


def _run(claude, argv, env):
    """claude as a child, to its end; the exit code it gave (128 + the signal when a signal ended it). Ctrl-C goes to the whole
    foreground group, so claude has it already and we stay; a TERM or HUP aimed at us is passed on."""
    sys.stdout.flush()
    child = subprocess.Popen([claude] + argv, env=env)
    saved = {sig: signal.signal(sig, handler) for sig, handler in (
        (signal.SIGINT, lambda *_: None), (signal.SIGTERM, lambda s, _: child.send_signal(s)), (signal.SIGHUP, lambda s, _: child.send_signal(s)))}
    try:
        code = child.wait()
    finally:
        for sig, old in saved.items():
            signal.signal(sig, old)
    return 128 - code if code < 0 else code


def _profile(a):
    """forge start @NAME [--dry-run] [ARGS...]."""
    args, dry = list(a.args), a.dry_run
    if args and args[0] == "--dry-run":
        dry, args = True, args[1:]
    try:
        profile = profiles.parse_at(a.name)
    except ValueError as e:
        return _refuse(str(e))
    found = profiles.project_here(os.getcwd())
    if not found:
        return _refuse("%s is not inside a project of forge's registry (a project file forge cannot read is left out of it)" % os.getcwd())
    project, prof = found
    if not profile:
        return profiles.cmd_list(argparse.Namespace(target="@", json=False, names=False))
    given = prof.get("profiles")
    if prof.get("frozen") or not isinstance(given, dict):
        return _refuse("project '%s' %s" % (project, "is frozen, so it receives no profile" if prof.get("frozen")
                                             else "declares no profiles (`forge list @` says which a project has)"))
    known = [given["default"]] + list(given["offered"])
    if profile not in known:
        return _refuse(suggest.message("profile", "@" + profile, ["@" + n for n in known], " in project '%s'" % project))
    settings = mcp_file = from_secrets = None
    flags = []
    if profile != given["default"]:  # the default is the project file as it is: claude with no profile flags
        # Two --settings: claude keeps the last, so the user's would silently replace the profile while FORGE_PROFILE says it is on.
        # Every position is checked, `--` included: whether claude reads a flag after it as one is not ours to bet on.
        for arg in args:
            if arg.split("=", 1)[0] in PROFILE_FLAGS:
                return _refuse("%s is set by the profile: a profile start refuses it in ARGS" % arg.split("=", 1)[0])
        try:
            settings, mcp_file, from_secrets = session_files(project, prof, profile, profiles.resolve(project, prof, profile))
        except profiles.ProfileError as e:
            return _refuse(str(e))
        base = os.path.join(lib.STATE, "profile-settings", project)
        settings_path, mcp_path = os.path.join(base, profile + ".json"), os.path.join(base, profile + ".mcp.json")
        # --mcp-config takes any number of values and would swallow a prompt that follows it: a flag with one value comes after.
        flags = ["--strict-mcp-config", "--mcp-config", mcp_path, "--settings", settings_path]
    fresh = new_session(args)
    sid = str(uuid.uuid4()) if fresh else None
    env = dict(os.environ, FORGE_PROFILE=profile, FORGE_PROJECT=project)
    claude = shutil.which("claude", path=env.get("PATH", os.defpath))
    if not claude:
        print("! forge start: claude is not on PATH", file=sys.stderr)
        return 127
    argv = flags + (["--session-id", sid] if fresh else []) + args
    record = profiles.session_record(profile, project, os.getpid()) if fresh else None
    if dry:
        print("forge start @%s: a dry run, nothing is written and claude is not started" % profile)
        print("project      %s (%s)" % (project, prof["project_path"]))
        print("claude       %s" % claude)
        print("arguments    %s" % " ".join(SESSION_ID if x == sid else shlex.quote(x) for x in argv))
        print("environment  FORGE_PROFILE=%s FORGE_PROJECT=%s (added to this shell's)" % (profile, project))
        print("would write")
        if settings is not None:
            print("  %s  (--settings)" % settings_path)
            for line in _describe(settings, from_secrets):
                print("      %s" % line)
            print("  %s  (--mcp-config: %s)" % (mcp_path, ", ".join(mcp_file["mcpServers"]) or "no server"))
        if record:
            print("  %s  (the session record; the id is a new uuid4)" % profiles.session_path(SESSION_ID))
        else:
            print("  no session record: this session is resumed or has an id of the user's")
        return 0
    try:
        if settings is not None:
            lib.write_text(settings_path, json.dumps(settings, indent=2) + "\n", mode=0o600)
            lib.write_text(mcp_path, json.dumps(mcp_file, indent=2) + "\n", mode=0o600)
        if record:
            profiles.write_session(sid, record)
    except OSError as e:
        return _refuse("cannot write the session's files under %s: %s" % (lib.STATE, e.strerror or e))
    return _run(claude, argv, env)


def cmd(a):
    if a.name and a.name.startswith("@"):
        return _profile(a)
    if a.dry_run:
        return _refuse("--dry-run is for a profile: forge start @NAME --dry-run")
    table, bad = _launchers(lib.settings())
    if bad:
        print("! forge start: %s" % bad, file=sys.stderr)
        return 2
    if not a.name:
        if not table:
            print("no launchers (add one under `launchers` in config/forge.json)")
        for name, launcher in sorted(table.items()):
            print("%s  %s" % (name, " ".join(sorted(launcher.get("env", {}))) or "(no env)"))
        return 0
    if a.name not in table:
        print("! forge start: unknown launcher %r (known: %s)" % (a.name, ", ".join(sorted(table)) or "none"),
              file=sys.stderr)
        return 2
    env = dict(os.environ, **table[a.name].get("env", {}))
    claude = shutil.which("claude", path=env.get("PATH", os.defpath))
    if not claude:
        print("! forge start: claude is not on PATH", file=sys.stderr)
        return 127
    sys.stdout.flush()
    os.execvpe(claude, ["claude"] + a.args, env)
