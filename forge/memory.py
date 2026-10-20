"""Memory: which store a project remembers into, and the Hindsight coding-agents config.

Two memory systems are live. claude-mem-lite keeps one store per project, and the store's path is
derived here from the project name, never declared (invariant). Hindsight's client config is
rendered from git with any `${VAR}` resolved (write_hindsight_config), and its staged runtime is
checked against what that config asks for (check_hindsight_runtime). A memory mismatch blocks
every write for its profile; a runtime that cannot honour the config is an error of the run."""
import os

from forge import lib, mcp, owned

ROOT = lib.ROOT

# claude-mem-lite is a plugin, not a registry server: it brings its own hooks and its own MCP
# server, and the only thing it takes from the outside is where to put the database. So a
# profile opts in by listing the plugin, and the directory is DERIVED from the project name
# rather than restated: a per-project store named by hand in two places is how 235 claude-mem
# observations spent four months in the wrong database. The path must be absolute; the package rejects a relative one loudly and
# a missing one silently resolves to the single shared default.
LITE_PLUGIN = "claude-mem-lite@sdsrss"
LITE_ROOT = os.path.join(ROOT, "data", "memory-lite")

# claude-mem (thedotmack) was retired: some projects remember
# through Hindsight, others have their own systems, and every
# other project uses claude-mem-lite. Its stores stay on disk under data/memory/ as an archive.
# A profile that grants either half again would bring back a worker per store and capture hooks
# in every session, so it is refused rather than quietly wired.
RETIRED_MEMORY = {"server_prefix": "claude-mem", "plugin": "claude-mem@thedotmack"}


def invariant(ctx, prof, profile_file):
    """The memory errors of one profile, [] when it is consistent: a retired claude-mem grant, or a
    CLAUDE_MEM_DIR that disagrees with the derived one. Only a profile that passes the first check
    gets derive_lite_env's changes (its env, its store directory)."""
    return check_retired_memory(prof, profile_file) or derive_lite_env(ctx, prof, profile_file)


def check_retired_memory(prof, profile_file):
    where = os.path.basename(profile_file)
    errs = ["%s grants retired claude-mem server %s -- drop it from `servers`" % (where, s)
            for s in prof.get("servers", []) if s.startswith(RETIRED_MEMORY["server_prefix"])]
    if RETIRED_MEMORY["plugin"] in (prof.get("plugins_keep") or []):
        errs.append("%s keeps retired plugin %s -- drop it from `plugins_keep`"
                    % (where, RETIRED_MEMORY["plugin"]))
    return errs


def lite_store_name(prof, default=None):
    """The directory name, under LITE_ROOT, of the store this profile writes to: its own project
    name (`default` when the profile dict does not carry one), or the one named by `memory_lite_store`, or "" when that key is malformed.

    The key exists so projects that are one body of work can remember into ONE store: the Omarchy
    plugins are separate git repositories (each is published on its own), so they cannot be one
    project, but a lesson from one is a lesson for the next. It names another project's store, so
    the path is still derived and never typed, and claude-mem-lite's own cross-project search
    (MEM_CROSS_PROJECT_BOOST, set in the profile's env) is what lets one project read what the
    others wrote: the plugin scopes a row to the project it came from, and sharing the file only
    makes the rows visible to each other's searches."""
    store = prof.get("memory_lite_store")
    if store is None:
        return prof["project"] if default is None else default
    ok = isinstance(store, str) and store and store[0].isalnum() \
        and all(c.isalnum() or c == "-" for c in store)
    return store if ok else ""


def derive_lite_env(ctx, prof, profile_file):
    """Give a profile that enables claude-mem-lite its store directory.

    Derived from the project name (or from `memory_lite_store`, see lite_store_name), never
    declared: see LITE_ROOT. A profile that states the
    key itself is an error rather than a silent overwrite -- two answers to one question is the
    failure this generator exists to prevent.

    The directory is created here too. The package writes its database on first use and would
    otherwise create whatever path it is handed at whatever moment a hook first fires, which
    puts the one irreversible step (the schema migration) somewhere nobody is watching."""
    errs = []
    where = os.path.basename(profile_file)
    if LITE_PLUGIN not in (prof.get("plugins_keep") or []):
        return errs
    store = lite_store_name(prof)
    if not store:
        return ["%s: memory_lite_store must be a project-name slug (letters, digits, hyphens), got %r"
                % (where, prof.get("memory_lite_store"))]
    want = os.path.join(LITE_ROOT, store)
    env = dict(prof.get("env") or {})
    got = env.get("CLAUDE_MEM_DIR")
    if got is not None and got != want:
        errs.append("%s declares CLAUDE_MEM_DIR = %s but the project name says %s -- remove "
                    "the line from the profile. The generator will not choose between them."
                    % (where, got, want))
        return errs
    env["CLAUDE_MEM_DIR"] = want
    prof["env"] = env
    if ctx.apply:
        lib.makedirs(want)
    return errs


def _object(doc):
    """A parsed JSON file whose top level is not an object (42, true, [1]) read as an empty one."""
    return doc if isinstance(doc, dict) else {}


def write_hindsight_config(ctx, secrets, errors):
    """Render config/hindsight-coding-agents.json to ~/.hindsight/coding-agent.json, mode 600.

    WHY THIS IS GENERATED AND NOT JUST A FILE ON DISK. Every setting in it overrides a default
    that is actively harmful on the personal bank: without the file the package resolves ONE BANK PER
    REPOSITORY (`coding-agent::{gitProject}`), which sends the personal-assistant project's sessions to a new, empty bank
    instead of the personal bank; `optInOnly` reverts to false, so memory runs in every project instead
    of only that project and the `mapPathToBank` entries -- client work included; and `manageBankConfig` reverts to
    true, at which point the package writes retain strategies, a `knowledge` entity-label group
    and missions into a bank that is the user's personal memory, not a coding bank. A file whose
    absence silently does all that has no business being the only copy, so the canonical copy is
    in git and this rewrites the rendered one every run.

    Any `${VAR}` in the canonical file is resolved here from credentials/secrets.json, the same
    indirection every MCP server gets. There is none now: the personal bank lives on the
    coding server on this laptop (127.0.0.1:9077), which takes no bearer, so every `apiToken` is
    empty. The file is still written 0600 and never tracked, because a `${VAR}` added later would
    put a real secret in it in clear."""
    CANON = os.path.join(ROOT, "config", "hindsight-coding-agents.json")
    TARGET = os.path.join(lib.HOME, ".hindsight", "coding-agent.json")
    short = lib.short(TARGET)

    canon = lib.read_json(CANON)
    if not isinstance(canon, dict):  # 42, true, [1]: as unusable as a file that does not parse
        return "   ! %s is not a JSON object -- nothing rendered" % CANON.replace(ROOT, "forge")
    if not canon:
        return "   ! %s missing -- nothing rendered" % CANON.replace(ROOT, "forge")

    resolved = mcp.resolve_secrets(canon, secrets, errors, "hindsight-coding-agents", block="config")
    if len(resolved) != len(canon):
        return "   ! secret unresolved -- %s NOT written" % short

    old = lib.read_json(TARGET)
    shapeless = not isinstance(old, dict)  # rendered whole, so a non-object is simply replaced
    old = _object(old)
    # The ownership record (forge/owned.py): the file holds `resolved` once this run has written it or found
    # it so, and `resolved` can hold a secret, so only its hash is kept.
    claimed = [owned.claim("file", [], resolved, "hindsight")]
    if old == resolved:
        # Mode is part of the contract, not cosmetics: the file and its once-ever .bak may carry
        # a secret in clear (an old .bak held a dead server's bearer). It once checked only the file here, so a 644 .bak beside a
        # current file stayed 644 for good; lib.write_json corrects both. The .bak is the one beside
        # the resolved file, where write_json keeps it: until simplify-3 T3 a linked TARGET had its
        # .bak looked for beside the link, so the one holding the secret was never seen.
        loose = mcp.loose_secrets(TARGET)
        if not loose:
            owned.record(TARGET, claimed, ctx.apply)
            return "   config -> %s (already current)" % short
        if not ctx.apply:
            return "   would chmod 600 %s (content current)" % ", ".join(lib.short(p) for p in loose)
        lib.write_json(TARGET, resolved, mode=0o600, backup=True)
        owned.record(TARGET, claimed, True)
        if loose == [TARGET]:
            return "   config -> %s (content current, mode corrected to 600)" % short
        return "   config -> %s (content current, chmod 600 %s)" % (short, ", ".join(os.path.basename(p) for p in loose))

    drift = sorted(k for k in set(canon) | set(old or {})
                   if not k.startswith("_") and (old or {}).get(k) != resolved.get(k))
    if shapeless:
        what = "replaced: was not a JSON object"
    elif not old:
        what = "created"
    elif drift:
        what = "drift on " + ", ".join(drift)
    else:
        # Only `_doc`-style keys differ. Still written -- the rendered file is the one a human
        # reads when memory misbehaves, so its explanations must not lag the canonical.
        what = "commentary only"
    if not ctx.apply:
        return "   would write %s (%s)" % (short, what)
    lib.write_json(TARGET, resolved, mode=0o600, backup=True)
    owned.record(TARGET, claimed, True)
    return "   config -> %s (%s)" % (short, what)


def check_hindsight_runtime(errors):
    """Fail loudly when the staged runtime cannot honour the configured `autoInject`: each failure is
    appended to `errors`, as write_hindsight_config does, and the return is the status line or None.

    WHY THIS EXISTS. `autoInject` is not in any published release: npm's latest (0.6.1,
    when checked) does not contain the string anywhere in its compiled code. The runtime under
    ~/.hindsight/coding-agents is therefore built from the upstream main branch, and the hooks in
    ~/.claude/settings.json run that staged copy by absolute path.

    The failure this guards against is silent, not loud. Anything that restages the package from
    npm -- `npx @vectorize-io/hindsight-coding-agents`, an installer run, a teammate following the
    upstream README -- overwrites dist/ with a build that simply ignores `autoInject`. The config
    keeps saying "recall", the hook goes back to attempting a reflect that measures 60-113 s
    against a 20 s cap, and memory injection degrades to the fallback chain that already left one
    session with no memory at all. Nothing errors; the sessions just get worse.

    So: if the canonical config asks for an `autoInject` mode, the staged code must know the word.
    """
    CANON = os.path.join(ROOT, "config", "hindsight-coding-agents.json")
    HOOK = os.path.join(lib.HOME, ".hindsight", "coding-agents", "dist", "claude-hook.js")
    ORIGIN = os.path.join(lib.HOME, ".hindsight", "coding-agents", ".install-origin.json")

    # Not an object is unreadable, as in write_hindsight_config, which already said so on a '!' line.
    canon = _object(lib.read_json(CANON))
    modo = canon.get("autoInject")
    if not modo:
        return None

    if not os.path.exists(HOOK):
        errors.append("hindsight: config asks for autoInject %r but the staged runtime is missing "
                      "(%s). Memory injection is not running." % (modo, lib.short(HOOK)))
        return None
    try:
        with open(HOOK, "r", encoding="utf-8", errors="ignore") as fh:
            soporta = "autoInject" in fh.read()
    except OSError as e:
        errors.append("hindsight: cannot read %s (%s)" % (lib.short(HOOK), e))
        return None

    origen = _object(lib.read_json(ORIGIN))
    marca = origen.get("commit") or origen.get("source") or "unknown origin"
    if not soporta:
        errors.append("hindsight: the staged runtime does NOT support autoInject, but the config asks "
                      "for %r (staged from %s). Something restaged the published package, which ignores "
                      "the option: injection has silently fallen back to the reflect path. Rebuild from "
                      "upstream main, or restore ~/.hindsight/coding-agents.bak-0.6.1-20260920."
                      % (modo, marca))
        return None
    return "   runtime -> ~/.hindsight/coding-agents honours autoInject %r (%s)" % (
        modo, marca[:12] if origen.get("commit") else marca)
