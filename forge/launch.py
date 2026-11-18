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
project's profiles.

forge switch @NAME  inside a session started by `forge start @A`: the profile of that session becomes NAME. It writes a request
(profiles.write_switch) and nothing else; the launcher that is claude's parent sees it while claude runs, ends its own child with
TERM (claude leaves a whole transcript, measured in 4.3 U0), and starts `claude --resume <id>` with NAME's flags, so the
conversation goes on with the new skills, plugins and servers. It signals nobody: a `forge switch` outside such a session, or
whose launcher is gone, refuses and kills nothing. The relaunch carries the profile's flags and `--resume`, not the arguments the
session was started with (a prompt among them would be sent again). `forge switch` alone lists the profiles, the current one marked."""
import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid

from forge import framework, lib, mcp, profiles, skills, suggest

# claude's own flags that mean the session is not a new one, or already has the id the user chose: no `--session-id` of ours.
NOT_NEW = ("-r", "--resume", "-c", "--continue", "--session-id", "--from-pr")
PROFILE_FLAGS = ("--settings", "--mcp-config", "--strict-mcp-config")  # the flags a profile start sets itself
POLL = 0.25  # seconds between two looks at the switch request while claude runs
KILL_AFTER = 15  # seconds a claude asked to end by a switch has before it is killed
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


def _refuse(why, who="forge start"):
    print("! %s: %s" % (who, why), file=sys.stderr)
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


def _run(claude, argv, env, watch=None):
    """claude as a child, to its end; the exit code it gave (128 + the signal when a signal ended it). Ctrl-C goes to the whole
    foreground group, so claude has it already and we stay; a TERM or HUP aimed at us is passed on. With `watch`, called every
    POLL seconds: once it says True the child is sent TERM (and KILL after KILL_AFTER seconds, so a claude that ignores it cannot
    keep the loop from going on)."""
    sys.stdout.flush()
    child = subprocess.Popen([claude] + argv, env=env)
    saved = {sig: signal.signal(sig, handler) for sig, handler in (
        (signal.SIGINT, lambda *_: None), (signal.SIGTERM, lambda s, _: child.send_signal(s)), (signal.SIGHUP, lambda s, _: child.send_signal(s)))}
    try:
        ended = None  # when the child was asked to end
        while True:
            try:
                code = child.wait(timeout=POLL if watch else None)
                break
            except subprocess.TimeoutExpired:
                if ended is None and watch():
                    ended = time.monotonic()
                    child.terminate()
                elif ended is not None and time.monotonic() - ended > KILL_AFTER:
                    child.kill()
    finally:
        for sig, old in saved.items():
            signal.signal(sig, old)
    return 128 - code if code < 0 else code


def _target(who, text):
    """(project, project file, profile) that `@NAME` (text) names in the project of the current directory, or the exit code of the
    refusal that was printed. The profile is "" for a bare `@`. The reasons are `forge start`'s, for `forge switch` too."""
    try:
        profile = profiles.parse_at(text)
    except ValueError as e:
        return _refuse(str(e), who)
    found = profiles.project_here(os.getcwd())
    if not found:
        return _refuse("%s is not inside a project of forge's registry (a project file forge cannot read is left out of it)" % os.getcwd(), who)
    project, prof = found
    if not profile:
        return project, prof, ""
    given = prof.get("profiles")
    if prof.get("frozen") or not isinstance(given, dict):
        return _refuse("project '%s' %s" % (project, "is frozen, so it receives no profile" if prof.get("frozen")
                                             else "declares no profiles (`forge list @` says which a project has)"), who)
    known = [given["default"]] + list(given["offered"])
    if profile not in known:
        return _refuse(suggest.message("profile", "@" + profile, ["@" + n for n in known], " in project '%s'" % project), who)
    return project, prof, profile


def _flags(project, prof, profile):
    """(the claude flags of `profile`, the --settings document, the --mcp-config document, the env keys that are secrets, the two
    paths they go to), or raises profiles.ProfileError. The default label is the project file as it is: no flags, no documents.
    Nothing is written."""
    if profile == prof["profiles"]["default"]:
        return [], None, None, None, None, None
    settings, mcp_file, from_secrets = session_files(project, prof, profile, profiles.resolve(project, prof, profile))
    base = os.path.join(lib.STATE, "profile-settings", project)
    settings_path, mcp_path = os.path.join(base, profile + ".json"), os.path.join(base, profile + ".mcp.json")
    # --mcp-config takes any number of values and would swallow a prompt that follows it: a flag with one value comes after.
    return ["--strict-mcp-config", "--mcp-config", mcp_path, "--settings", settings_path], settings, mcp_file, from_secrets, settings_path, mcp_path


def _write_files(settings, mcp_file, settings_path, mcp_path):
    if settings is not None:
        lib.write_text(settings_path, json.dumps(settings, indent=2) + "\n", mode=0o600)
        lib.write_text(mcp_path, json.dumps(mcp_file, indent=2) + "\n", mode=0o600)


def _resume_id(req, sid):
    """The conversation a relaunch resumes: the one the request names when it is a uuid (claude gave a new one after /clear), else
    the session's own. A value that is not an id never reaches claude's command line."""
    try:
        return str(uuid.UUID(str(req.get("resume"))))
    except ValueError:
        return sid


def _session(claude, argv, env, sid, project, prof, profile, flags):
    """claude for session `sid` under launcher `os.getpid()`, started again, resumed and with the flags of the other profile, for as
    long as a switch request of this launcher is there when claude ends; then its exit code. A request is taken (deleted) whether it
    is honoured or not. When the profile asked for cannot be built now (the project file changed since the start) the line says so
    and claude comes back with the profile it had, resumed: the terminal is never left without claude. Every pass needs a request
    of its own, which only `forge switch` or a hand writes, so this ends with the first claude that ends without one."""
    me = os.getpid()
    while True:
        code = _run(claude, argv, env, watch=lambda: profiles.pending_switch(sid, me) is not None)
        req = profiles.take_switch(sid, me)
        if not req:
            return code
        target = req["to"]
        try:
            if target not in [prof["profiles"]["default"]] + list(prof["profiles"]["offered"]):
                raise profiles.ProfileError("project '%s' has no profile '%s'" % (project, target))
            new_flags, settings, mcp_file, _, settings_path, mcp_path = _flags(project, prof, target)
            _write_files(settings, mcp_file, settings_path, mcp_path)
            rec = profiles.read_session(sid) or profiles.session_record(profile, project, me)
            rec.update(profile=target, at=round(time.time(), 3))
            profiles.write_session(sid, rec)
        except (profiles.ProfileError, OSError) as e:
            print("forge: cannot switch to @%s (%s); claude comes back with @%s" % (target, getattr(e, "strerror", None) or e, profile), file=sys.stderr)
        else:
            print("forge: profile %s \u2192 %s" % (profile, target))
            profile, flags = target, new_flags
            env = dict(env, FORGE_PROFILE=profile)
        argv = flags + ["--resume", _resume_id(req, sid)]


def _profile(a):
    """forge start @NAME [--dry-run] [ARGS...]."""
    args, dry = list(a.args), a.dry_run
    if args and args[0] == "--dry-run":
        dry, args = True, args[1:]
    found = _target("forge start", a.name)
    if isinstance(found, int):
        return found
    project, prof, profile = found
    if not profile:
        return profiles.cmd_list(argparse.Namespace(target="@", json=False, names=False, session=None))
    given = prof["profiles"]
    settings = mcp_file = from_secrets = settings_path = mcp_path = None
    flags = []
    if profile != given["default"]:  # the default is the project file as it is: claude with no profile flags
        # Two --settings: claude keeps the last, so the user's would silently replace the profile while FORGE_PROFILE says it is on.
        # Every position is checked, `--` included: whether claude reads a flag after it as one is not ours to bet on.
        for arg in args:
            if arg.split("=", 1)[0] in PROFILE_FLAGS:
                return _refuse("%s is set by the profile: a profile start refuses it in ARGS" % arg.split("=", 1)[0])
        try:
            flags, settings, mcp_file, from_secrets, settings_path, mcp_path = _flags(project, prof, profile)
        except profiles.ProfileError as e:
            return _refuse(str(e))
    fresh = new_session(args)
    sid = str(uuid.uuid4()) if fresh else None
    env = dict(os.environ, FORGE_PROFILE=profile, FORGE_PROJECT=project)
    # The session the launcher can switch: its id and its own pid. A start that is not a new session has no record and so cannot be
    # switched, and must not carry the ones of an outer session it was started from.
    for var in ("FORGE_SESSION", "FORGE_LAUNCHER_PID"):
        env.pop(var, None)
    if fresh:
        env.update(FORGE_SESSION=sid, FORGE_LAUNCHER_PID=str(os.getpid()))
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
        print("environment  FORGE_PROFILE=%s FORGE_PROJECT=%s%s (added to this shell's)" % (
            profile, project, " FORGE_SESSION=%s FORGE_LAUNCHER_PID=(this launcher's pid)" % SESSION_ID if fresh else ""))
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
        _write_files(settings, mcp_file, settings_path, mcp_path)
        if record:
            profiles.write_session(sid, record)
    except OSError as e:
        return _refuse("cannot write the session's files under %s: %s" % (lib.STATE, e.strerror or e))
    if record:
        return _session(claude, argv, env, sid, project, prof, profile, flags)
    return _run(claude, argv, env)


def _launcher_above(sid):
    """The record of session `sid` when this process runs inside it: the id and the launcher's pid are in the environment forge start
    gave claude, they match the record, and that launcher is alive; else None. Whatever is wrong here, nothing is signalled."""
    rec = profiles.read_session(sid)
    pid = rec.get("launcher_pid") if rec else None
    if not isinstance(pid, int) or os.environ.get("FORGE_LAUNCHER_PID") != str(pid):
        return None
    try:
        os.kill(pid, 0)  # signal 0 sends nothing: only whether the process exists
    except ProcessLookupError:
        return None
    except OSError:
        pass  # exists, not ours to signal: alive
    return rec


def switch(a):
    """forge switch [@NAME]: the session this runs in changes to profile NAME; with no NAME (or a bare @) the profiles are listed, the
    current one marked. Exit 0 requested (or already on it), 2 refused with one line saying why."""
    who = "forge switch"
    found = _target(who, a.target or "@")
    if isinstance(found, int):
        return found
    project, prof, profile = found
    if not profile:
        return profiles.cmd_list(argparse.Namespace(target="@", json=False, names=False, session=None))
    sid = os.environ.get("FORGE_SESSION")
    rec = _launcher_above(sid)
    if rec is None:
        return _refuse("this is not a session started by `forge start @NAME` (it has no launcher to restart claude): "
                       "start it again with `forge start @%s`, or `forge start @%s --resume <id>` for this conversation" % (profile, profile), who)
    if rec.get("project") != project:
        return _refuse("this session belongs to project '%s', not to '%s': run it from there" % (rec.get("project"), project), who)
    if rec.get("profile") == profile:
        print("forge switch: already on @%s, nothing to do" % profile)
        return 0
    try:
        _flags(project, prof, profile)  # a profile that cannot be built now would leave the relaunch without it
    except profiles.ProfileError as e:
        return _refuse(str(e), who)
    try:
        profiles.write_switch(sid, profile, rec["launcher_pid"], _resume_id({"resume": os.environ.get("CLAUDE_CODE_SESSION_ID")}, sid))
    except OSError as e:
        return _refuse("cannot write the request under %s: %s" % (lib.STATE, e.strerror or e), who)
    print("forge switch: @%s requested; claude restarts in a moment and resumes this conversation" % profile)
    return 0


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
