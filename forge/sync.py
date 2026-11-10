"""Generate per-agent / per-project MCP config from the canonical source in forge, in a fixed order.

agent_config() is what scripts/sync/sync_agent_config.py runs. Each step lives in its component
(mcp, memory, skills, hooks) and this module holds only the sequence: the sequence is the output,
and the output is an API (forge/cli.py's CHANGED greps it).

It writes for Claude Code and Codex (Antigravity/Gemini support was removed).

Source of truth:
  config/mcp-registry.json    -- one def per server, secret env as ${VAR}
  config/secrets.json         -- the only place real tokens live (git-ignored)
  config/profiles/*.claude.json -- which server/skill/plugin subset each project gets

Targets written:
  ~/.claude.json  projects["<forward-slash path>"].mcpServers (+ enable flags)
  <project>/.claude/settings.local.json  (plugin/skill overrides, env)
  <project>/.codex/config.toml  (the same servers, for Codex, with codex_harness true; false takes forge's out)
  <project>/.agents/skills/<name>  (links to the project's .claude/skills, for Codex)
  <project>/.gitignore  (the .codex/ and .agents/ lines, before either is written)
  ~/.claude/settings.json  (user-scope hooks and defaults)
  ~/.codex/hooks.json  (the same hooks, for Codex, with codex_harness true; false takes forge's out; $CODEX_HOME when set)
  ~/.hindsight/coding-agent.json  (rendered from config/hindsight-coding-agents.json)
  data/memory-lite/<project>  (each project's claude-mem-lite store directory)
  ~/.claude/plugins/known_marketplaces.json  (one `claude plugin marketplace add` per config/forge.json `local_plugins` folder the
    registry lacks, run in a temporary folder; nothing with the key empty or missing, and a registration is never removed)

Default = DRY RUN (prints what would change). Pass --apply to write.
Writes are atomic (temp -> replace) with a one-time .bak backup. Idempotent.

Invariants (from a split-brain bug):
  * Claude project key is ALWAYS the forward-slash path; never create a backslash dup.
  * Never emit a server whose secret resolves empty -> abort that server, warn loudly.
  * The agents of a project never write in forge: every profile but forge's own gets `permissions.deny` rules
    (Edit and Write) on the top-level entries git tracks in this checkout, `plugins/` and `design/` left out (forge_deny).
  * claude-mem-lite's store dir is DERIVED from the project name -- see forge/memory.py.
    claude-mem itself (thedotmack) was retired; RETIRED_MEMORY refuses a profile
    that still grants it.
"""
import contextlib
import os
import subprocess
import sys

from forge import framework, hooks, lib, marketplace, mcp, memory, skills

CFG = os.path.join(lib.ROOT, "config")

# The agents of a project do not write in forge (3.6 U2c): a problem with forge is fixed through the `forge` CLI or filed
# as an issue, never by a session of a project, which lacks forge's context and tools. A `deny` beats every `allow`, and a
# permission pattern cannot leave a folder out of itself (measured, tests/test_forge_write_deny.py), so the exceptions are
# one pair of rules per top-level entry of the checkout that git tracks, the exempt ones left out: `plugins/` (the plugin
# repos live there and their sessions write in their own folder) and `design/` (the taste library stays shared:
# design-taste's `analyse` edits `design/taste/entries/*.md` from any project). Tracked, not on disk: `logs/` and the like
# come and go and would rewrite every project's file on each sync; the few untracked ones that always matter are named in
# FORGE_DENY_ALWAYS. A new tracked entry is covered at the next sync, which
# runs at the start of each project's session.
FORGE_PROFILE = "forge"
FORGE_DENY_KEEP = ("plugins", "design")
# `Edit` alone: an Edit rule covers every built-in file-writing tool, and Claude Code 2.1.308 prints a warning at each session start for a
# `Write` rule ("never matches, use Edit"); with the Edit rules alone Write was denied too (tests/test_forge_write_deny.py).
FORGE_DENY_TOOLS = ("Edit",)
FORGE_DENY_WHY = "agents of a project do not write in forge"
DATA_GIT = ".forge-data.git"  # the private data history over the same work tree (forge/publish.py)
# Untracked, so git does not list them, yet always denied when the checkout has them: both histories, the secrets, the memory stores.
FORGE_DENY_ALWAYS = (".git", DATA_GIT, "credentials", "data")
# `data/` is made by the generator itself (memory.derive_lite_env, the first project that uses claude-mem-lite), in the middle of a
# run: a checkout without it would give the profiles read before that no rule for it and the next run one more, a rewrite of every
# settings.local.json. So it is denied whether or not it is there yet, as a directory.
FORGE_DENY_MADE = ("data",)


def _tracked_entries(root):
    """({top-level entry: whether it is a directory}, error) of what git tracks in `root`: the engine's history and, when it has
    one, the data history. An entry is a directory when some tracked path is below it."""
    heads = [["git", "-C", root]]
    if os.path.isdir(os.path.join(root, DATA_GIT)):
        heads.append(["git", "--git-dir", os.path.join(root, DATA_GIT), "--work-tree", root])
    out = {}
    for head in heads:
        try:
            # cwd=root: `ls-files` lists what is under the current directory, and the data history names no folder of its own
            r = subprocess.run(head + ["ls-files", "-z"], cwd=root, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            return {}, "git ls-files failed (%s)" % e
        if r.returncode:
            return {}, "git ls-files exited %d (%s)" % (r.returncode, r.stderr.strip()[:120])
        for path in filter(None, r.stdout.split("\0")):
            top, _, rest = path.partition("/")
            out[top] = out.get(top, False) or bool(rest)
    return out, None


def forge_deny(name, prof):
    """(rules, error) for the profile `name`: `Edit` `deny` rules on each top-level entry the checkout (`lib.ROOT`,
    read at call time, never written in the engine) tracks in git, plus those of FORGE_DENY_ALWAYS it has (FORGE_DENY_MADE ones even before they exist), but FORGE_DENY_KEEP, `<Tool>(//<root>/<dir>/**)` for a
    directory and `<Tool>(//<root>/<file>)` for a file, sorted by entry. Forge's own profile (by name, or whose project is
    the checkout) gets none, and so does a project whose folder does not exist. `error` is the `!` line of a checkout whose
    history cannot be read or has nothing to deny."""
    root = os.path.realpath(lib.ROOT)
    ppath = prof.get("project_path") or ""
    if name == FORGE_PROFILE or os.path.realpath(ppath) == root or not os.path.isdir(ppath):
        # a project folder that is not there gets nothing: writing the file would make the folder and hide the `!` line
        # the codex step prints for it
        return [], None
    tracked, why = _tracked_entries(root)
    for e in FORGE_DENY_ALWAYS:
        if e in FORGE_DENY_MADE or os.path.lexists(os.path.join(root, e)):
            tracked.setdefault(e, e in FORGE_DENY_MADE or os.path.isdir(os.path.join(root, e)))
    entries = sorted(e for e in tracked if e not in FORGE_DENY_KEEP)
    if why or not entries:
        return [], "   ! forge write deny -> the checkout %s %s -- nothing written for this project" % (
            root, why or "tracks no entry to protect")
    rules = []
    for e in entries:
        tail = "/**" if tracked[e] else ""
        rules += ["%s(/%s/%s%s)" % (t, root, e, tail) for t in FORGE_DENY_TOOLS]
    return rules, None


def with_forge_deny(prof, rules):
    """`prof` with `rules` added to its `permissions.deny`, after what the profile declares itself (as framework.with_permissions
    does for allow, so forge/skills.py claims them item by item); `prof` itself with nothing to add."""
    if not rules:
        return prof
    cur = dict(prof.get("permissions") or {})
    have = cur.get("deny")
    cur["deny"] = list(dict.fromkeys((have if isinstance(have, list) else []) + rules))
    return dict(prof, permissions=cur)


def _deny_lines(prof, rules):
    """The `+ deny` lines for the rules the project's settings.local.json does not hold yet."""
    cur = lib.read_json(os.path.join(prof["project_path"], ".claude", "settings.local.json"), quiet=True)
    cur = cur.get("permissions") if isinstance(cur, dict) else None
    have = cur.get("deny") if isinstance(cur, dict) and isinstance(cur.get("deny"), list) else []
    return ["  + deny %s  (%s)" % (r, FORGE_DENY_WHY) for r in rules if r not in have]


def _unreadable(e, what="not written"):
    """The line for a file left alone because it could not be read (lib.Unreadable): `what` says
    what was not written because of it."""
    return "   ! %s unreadable (%s) -- %s" % (lib.short(e.path), e.reason, what)


def _kind(v):
    """A JSON value's type, the way a '!' line names it."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "a boolean"
    if isinstance(v, (int, float)):
        return "a number"
    return {str: "a string", list: "a list", dict: "an object"}.get(type(v), type(v).__name__)


def load_relocations(cfg):
    """config/project-relocations.json's entries, each an object whose `from` and `to` are paths
    where given. The file is optional: missing is none, and unreadable is none after lib.read_json's
    line. A file of another shape is none too, and a bad entry is skipped alone, each after one '!'
    line. Like the unreadable file's line, each exits 1 under agent_config's rule, while the run
    goes on: moving no key loses nothing (the old key stays and a fixed file moves it next run).
    It once failed: a `[]` or `42` file raised at the `.get`, `{"relocations": 5}` in
    relocations_in_scope's loop, and a bad entry at item.get or at project_key: every profile,
    ~/.claude.json and the user scope went down with the run."""
    where = "config/project-relocations.json"
    doc = lib.read_json(os.path.join(cfg, "project-relocations.json"))
    if not isinstance(doc, dict):
        print("  ! %s holds %s, not an object -- no relocation applied" % (where, _kind(doc)))
        return []
    items = doc.get("relocations", [])
    if not isinstance(items, list):
        print("  ! %s: `relocations` is %s, not a list -- no relocation applied" % (where, _kind(items)))
        return []
    kept = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            print("  ! %s: relocations[%d] is %s, not an object -- skipped" % (where, i, _kind(item)))
            continue
        # An empty or absent end is skipped by migrate_project_keys, as before; only a truthy
        # non-string reached project_key and raised.
        bad = [k for k in ("from", "to") if item.get(k) and not isinstance(item[k], str)]
        if bad:
            print("  ! %s: relocations[%d] has a `%s` that is %s, not a path -- skipped"
                  % (where, i, bad[0], _kind(item[bad[0]])))
            continue
        kept.append(item)
    return kept


def agent_config(argv):
    """One generator run: every step in its order, printing what it did or would do. Returns the
    exit code, by one rule: a line whose first non-space character is '!' means the run exits 1,
    and no other line does. A '!' line says something was not done, or was found wrong and
    repaired -- a write skipped, a profile or a relocation skipped, a server missing from the
    registry, a file unreadable, a foreign write undone (the user-scope mcpServers cleared, a
    duplicate project key folded in: exit 1 for the one run that repairs it). The run still goes
    on past it wherever the rest can be done. Since then; before it, nine hand-set flags
    decided, and a missing server, a skipped relocation or mirror, an unwritten codex config, a
    settings.json warning and both repairs printed '!' and exited 0.

    The rule is applied to everything the run prints (lib.Rule wraps its stdout), not per call site:
    lib.read_json prints its own '! could not read' line, and so does every component that reaches
    it (a relocations file, secrets.json, the settings.json the plugin listing reads, the rendered
    Hindsight config and its install origin). A line printed inside lib is as much the run's line
    as one printed here, and a new print needs no flag to count.

    A line that deliberately carries no '!' and exits 0:
      * `~/.claude.json -> changed by another process ... next run retries`: a retry.
    The other steps keep the same rule in their own process: relink_skills.py and
    sync_system_doc.py exit 1 exactly when they printed a '!' line."""
    rule = lib.Rule(sys.stdout)
    with contextlib.redirect_stdout(rule):
        _run(argv, rule)
    return 1 if rule.failed or lib.BANG.match(rule.rest) else 0


def _run(argv, rule):
    """agent_config's steps, in order. What it prints decides the exit code (agent_config)."""
    # Whether this run writes (already a dry-run where lib.may_write refuses: a worktree, a copy),
    # which projects (None = all) and whether the user-scope files too; a SessionStart run is scoped
    # to its own session's project (lib.context).
    ctx = lib.context(argv)
    # The skill and plugin listings are read once per run, never carried over from a previous one
    # in the same process.
    skills.global_skills.cache_clear()
    skills.plugin_universe.cache_clear()
    registry, secrets = mcp.load_inputs(CFG)
    if registry is None:
        # lib.read_json turns an unreadable registry into {} after its own line, which exited 0
        # back then: every server was then "not in registry", and the run emptied every
        # project's mcpServers and its .codex/config.toml. A readable {"servers": {}} still runs:
        # it is a legitimate state.
        print("! config/mcp-registry.json has no servers object (unreadable, missing or malformed) -- nothing written")
        return

    # lib.PROFILES read here, at call time: the in-process test points it at a toy directory.
    profiles = [os.path.join(lib.PROFILES, f) for f in os.listdir(lib.PROFILES) if f.endswith(".claude.json")]
    print("MODE:", "APPLY" if ctx.apply else "DRY-RUN (no files written; pass --apply to write)")
    print("registry servers: %d | secrets: %d | profiles: %d\n" % (len(registry), len(secrets), len(profiles)))
    hindsight_errors = []

    # The run's inputs, in the order their lines print: ~/.claude.json (its chmod line), the
    # relocations, every profile, then the relocations applied (their skipped and moved lines).
    cj = mcp.ClaudeJson.open(ctx)
    # Relocated repositories need an explicit migration because unrelated Claude project keys
    # are intentionally preserved. This is canonical/configured here rather than hand-editing
    # the generated ~/.claude.json.
    relocations = load_relocations(CFG)
    # Each profile is read once, here, for the relocation scope and for the loop below. Keyed and
    # ordered by path, as the loop always ran: by name, `app` would come before `app-hero`.
    loaded = {pf: lib.read_json(pf) for pf in sorted(profiles)}
    cj.relocate(ctx, loaded, relocations)

    for pf, prof in loaded.items():
        name = os.path.basename(pf)[:-len(".claude.json")]
        if not ctx.wants(name):
            continue
        bad = lib.profile_error(prof)
        if bad:
            # Checked before anything reads the profile, `frozen` included ("false" is truthy): a
            # wrong type raised in whichever component met it first and took every later profile,
            # ~/.claude.json and the user scope with it.
            print("== %s ==\n   ! %s -- nothing written for this project\n" % (os.path.basename(pf), bad))
            continue
        want = prof.get("servers", [])
        missing = [s for s in want if s not in registry]
        if missing:
            print("  ! %s references servers not in registry: %s" % (os.path.basename(pf), missing))
        sel = [s for s in want if s in registry]
        errors = []
        print("== %s  (%d servers) ==" % (os.path.basename(pf), len(sel)))
        if prof.get("frozen"):
            # A frozen project gets nothing from forge: no settings.local.json, .codex, .agents
            # links, and its ~/.claude.json key is left exactly as it is. A project is frozen
            # while it builds its own system and a
            # forge rewrite would hot-reload every one of its running sessions.
            print("   frozen -- nothing written for this project\n")
            continue
        if not prof.get("project_path"):
            # Malformed (lib.read_json gave {}) or written without one: no directory, no key. Skipping it
            # keeps the later profiles, ~/.claude.json and the user scope; a KeyError took them all.
            print("   ! no project_path -- nothing written for this project\n")
            continue

        # Memory invariant is checked BEFORE any write for this profile. Unlike a secret error
        # (which only blocks ~/.claude.json and still lets skill trimming through), a memory
        # mismatch must also block settings.local.json -- that file is where the capture env
        # lands, so writing it while inconsistent is precisely the failure being prevented.
        mem_errs = memory.invariant(ctx, prof, pf)
        if mem_errs:
            print("   ! memory INVARIANT VIOLATED -- no writes for this profile:")
            for e in mem_errs:
                print("     - " + e)
            print()
            continue

        # What the framework step wants of this project, decided before anything is written: a permissions list that
        # fails its lint writes nothing for the profile (framework.permissions), as the memory invariant above.
        fw = framework.plan(prof, name)
        fp = framework.permissions(prof, fw, os.path.join(CFG, framework.PERMISSIONS_FILE))
        if fp.errors:
            print("\n".join(fp.errors) + "\n")
            continue

        denied, deny_error = forge_deny(name, prof)
        if deny_error:
            print(deny_error + "\n")
            continue
        deny_lines = _deny_lines(prof, denied)

        cj.project(prof, sel, registry, secrets, errors)
        for e in errors:
            print("   ! " + e)

        env_errors = []
        # settings.local.json carries part of what the framework wants (the plugin's enabledPlugins entry, its
        # marketplace, LINEAR_API_KEY, its permissions); the framework's own lines come after.
        settings_ok = True
        try:
            ov = skills.write_settings_local(
                ctx, with_forge_deny(mcp.with_denied_tools(framework.with_permissions(framework.with_env(prof, fw, secrets), fp), sel, registry), denied),
                secrets, env_errors, hooks.project_hooks(prof), fw if fw.on else None)
        except lib.Unreadable as e:
            ov, settings_ok = _unreadable(e), False
        if ov:
            print(ov)
        for e in env_errors:
            print("   ! " + e)
        if settings_ok:
            for line in (*fp.lines, *deny_lines):
                print(line)
            for line in framework.write(ctx, prof, fw, name, secrets):
                print(line)

        if not errors and not lib.on("codex"):
            # Codex off (config/forge.json integrations.codex): no .codex/, no .agents/ links and
            # no ignore line for either, in any project.
            print(hooks._not_run("codex mcp, project skills", "codex"))
        elif not errors:
            try:
                if lib.codex_harness():
                    cx = mcp.write_codex_project_mcp(ctx, prof, sel, registry, secrets, errors)
                else:
                    # `codex_harness` off: no MCP server for Codex, and forge's own are taken out.
                    cx = mcp.drop_codex_project_mcp(ctx, prof, registry, errors)
                if cx:
                    print(cx)
                ms = skills.mirror_for_codex(ctx, prof)
            except lib.Unreadable as e:  # the project's .gitignore, which both consult
                ms = _unreadable(e, "nothing written under .codex/ or .agents/")
            if ms:
                print(ms)
            for e in errors:
                print("   ! " + e)

        print()


    print("== ~/.claude.json (MCP servers, every profile) ==")
    try:
        print(cj.commit(ctx))
    except lib.Unreadable as e:
        print(_unreadable(e))
    print()

    if ctx.globals:
        print("== user-scope hooks and defaults ==")
        for step in (lambda: hooks.write_user_settings(ctx), lambda: hooks.write_codex_hooks(ctx)):
            try:
                print(step())
            except lib.Unreadable as e:
                print(_unreadable(e))
        print()

        print("== Hindsight coding-agents (config + runtime) ==")
        if lib.on("hindsight"):
            print(memory.write_hindsight_config(ctx, secrets, hindsight_errors))
            rt = memory.check_hindsight_runtime(hindsight_errors)
            if rt:
                print(rt)
            for e in hindsight_errors:
                print("   ! " + e)
        else:
            # Off (config/forge.json integrations.hindsight): neither the rendered config nor the
            # runtime check, so a missing canonical file is not an error either.
            print(hooks._not_run("hindsight config and runtime check", "hindsight"))
        print()

        # The machine's marketplace registry (config/forge.json `local_plugins`): after everything else, so a run with the key
        # off prints what it always printed. Silent when every folder is registered.
        local = marketplace.local_step(ctx)
        if local:
            print("== local plugins (machine registry) ==")
            for line in local:
                print(line)
            print()
    else:
        print("== user-scope files: not this run's scope (%s) ==\n" % ("project " + ", ".join(sorted(ctx.only)) if ctx.only else "no project"))

    if rule.failed:
        # Not "writes were skipped": a repaired foreign write (user-scope mcpServers) is written
        # and still exits 1 for that run.
        print("ABORTED: each '!' line above names a failure or a repair, and what it left unwritten. "
              "Fix what they name -- config/secrets.json, a profile or an unreadable file -- and rerun.")
    else:
        print("OK." + ("" if ctx.apply else "  (dry-run — rerun with --apply after a clean Claude restart)"))
