"""Skills and plugins: which of them each project sees, for Claude Code and for Codex.

The global skills live in forge's skills/ and reach ~/.claude/skills through relink_skills.py's
links; a profile trims them, and the plugins, per project in <project>/.claude/settings.local.json
(write_settings_local). A project's own .claude/skills are Claude Code's alone until they are
linked into .agents/skills, the root Codex reads (mirror_for_codex)."""
import functools
import os

from forge import lib, mcp, owned


def skill_dirs(path):
    return [d for d in os.listdir(path)
            if os.path.isdir(os.path.join(path, d)) and not d.startswith('.')] \
           if os.path.isdir(path) else []


@functools.lru_cache(maxsize=None)
def global_skills():
    """~/.claude/skills, read once per run rather than once per profile (20 x ~140 stats)."""
    return frozenset(skill_dirs(os.path.join(lib.HOME, ".claude", "skills")))


@functools.lru_cache(maxsize=None)
def plugin_universe():
    """Every plugin ~/.claude/settings.json knows. Nothing in this run changes enabledPlugins."""
    return list((lib.read_json(os.path.join(lib.HOME, ".claude", "settings.json")).get("enabledPlugins") or {}).keys())


def _repo_root(path):
    """The directory holding path's .git, resolved, or None outside any repository."""
    g = lib.git_dir(path)[0]
    return os.path.realpath(os.path.dirname(g)) if g else None


def neighbour_skills(ppath):
    """The project skills of every other profile nested with ppath in ONE git repository: an
    ancestor's, which Claude Code's startup walk loads (cwd up to the git root), and a
    descendant's, which a session meets once it reads a file under it. skillOverrides matches by
    name, project skills included, so these must be switched off too, or the outer project's skills reach
    the nested project and its skills reach the outer one. A profile in no repository (~/dev) or in another
    repository is no neighbour, whatever its path says. docs/skill-placement-design.md, B2."""
    here = os.path.realpath(ppath)
    root = _repo_root(here)
    if root is None:
        return frozenset()
    found = set()
    for prof in lib.profiles().values():
        if not prof.get("project_path"):
            continue
        other = os.path.realpath(prof["project_path"])
        if other == here or not (other.startswith(here + os.sep) or here.startswith(other + os.sep)):
            continue
        if _repo_root(other) == root:
            found.update(skill_dirs(os.path.join(prof["project_path"], ".claude", "skills")))
    return frozenset(found)


def _groups_ok(have):
    """Whether an event's value is a list of hook groups, each an object whose `hooks` is a list of
    objects: the only shape the merge and the guard's pruning trust enough to edit."""
    return isinstance(have, list) and all(
        isinstance(g, dict) and isinstance(g.get("hooks", []), list)
        and all(isinstance(h, dict) for h in g.get("hooks", [])) for g in have)


GUARD_SCRIPT = "guard_tool_use.py"
GUARD_TIMEOUT = 10  # the guard entry's own timeout in settings.local.json, and the doctor's probes'
# forge's guards, each one PreToolUse entry it owns: (script in hooks/, the group's matcher or None,
# whether the profile turns it on, its name in the summary line's "<name> on", its name in "<name>
# not merged" and "<name> entries removed N"). The command guard's second name, "guard", predates
# the table and the line is an API (cli.WOULD). The command guard is docs/command-guard-design.md;
# the worktree guard is research/21-para-forge/04-guarda-de-worktrees.md, and its matcher is every
# tool that writes.
GUARDS = (
    (GUARD_SCRIPT, None, lambda prof: bool(prof.get("command_guard")), "command guard", "guard"),
    ("worktree_guard.py", "Write|Edit|MultiEdit|NotebookEdit|Bash", lib.worktree_guard_on, "worktree guard",
     "worktree guard"),
)


def guard_command(name, script=GUARD_SCRIPT):
    """The one command a forge guard runs as, for the profile `name`: the command guard reads
    config/guard/<name>.json itself, the worktree guard config/profiles/<name>.claude.json."""
    return "python3 %s --project %s" % (os.path.join(lib.ROOT, "hooks", script), name)


# What a guard's entry is when it can stop a call. The one definition: _own_guard writes it and the
# doctor's rows (cli.guard_problem, cli.worktree_guard_problem) compare against it. A row written per
# project (forge.hooks.project_hooks) is the same shape with its own timeout.
def canonical_hook(command, timeout=GUARD_TIMEOUT):
    return {"type": "command", "command": command, "timeout": timeout}


def _runs_forge_guard(command, script=GUARD_SCRIPT):
    """Whether `command` runs forge's own hooks/<script>, whatever its arguments. Another
    project's copy (a frozen project keeps one under .claude/hooks) and a relative path are not forge's."""
    want = os.path.realpath(os.path.join(lib.ROOT, "hooks", script))
    return isinstance(command, str) and any(
        os.path.isabs(t) and os.path.realpath(t) == want for t in command.split())


def _holds(sl, ours):
    """Whether the file's hooks hold an entry whose command `ours` accepts."""
    hooks = sl.get("hooks")
    return isinstance(hooks, dict) and any(
        _groups_ok(have) and any(ours(h.get("command")) for g in have for h in g.get("hooks", []))
        for have in hooks.values())


def _has_forge_guard(sl):
    return _holds(sl, lambda cmd: any(_runs_forge_guard(cmd, row[0]) for row in GUARDS))


def _own_guard(sl, prof, row):
    """forge owns every hook entry that runs one of its guards (docs/command-guard-design.md), one
    GUARDS row per call. With the row's profile line on, the file ends with exactly one: the
    canonical PreToolUse group, the row's matcher (none for the command guard), timeout 10; any
    other that runs the guard goes, whichever event, matcher or argument. Without it every one
    goes, except a command the profile's own `hooks` block declares (one project's, until its profile
    moved to the line). Entries that do not run the guard are never touched. Runs after the
    `hooks` merge, so what the merge appended is judged too. Returns the summary text."""
    script, matcher, is_on, label, short = row
    return _own_hook(sl, prof, lambda cmd: _runs_forge_guard(cmd, script), "PreToolUse",
                     canonical_hook(guard_command(prof.get("project"), script)), matcher, is_on(prof), label, short)


def _own_hook(sl, prof, ours, want_event, entry, matcher, on, label, short):
    """_own_guard's ownership, for any one entry forge owns in the file: every hook whose command
    `ours` accepts is forge's. On, the file ends with exactly one, `entry` in a `want_event` group
    with `matcher`, the first one whose command is entry's kept whatever its timeout or type; off,
    only a command the profile's own `hooks` declares stays. Returns the summary text."""
    hooks = sl.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        return ", %s not merged (the file's hooks is not an object)" % short if on else ""
    hooks = hooks if hooks is not None else {}
    canon = entry["command"]
    declared = {h.get("command") for groups in (prof.get("hooks") or {}).values()
                for g in groups for h in g.get("hooks", [])}
    removed, seen = 0, False
    for event in list(hooks):
        have = hooks[event]
        if not _groups_ok(have):
            continue
        out = []
        for g in have:
            kept = []
            for h in g.get("hooks", []):
                cmd = h.get("command")
                if ours(cmd):
                    # On, only the first canonical entry of the wanted event, in a group with the
                    # row's matcher, stays; off, what the profile declares.
                    if on:
                        stays = cmd == canon and event == want_event and g.get("matcher") == matcher and not seen
                        seen = seen or stays
                    else:
                        stays = cmd in declared
                    if not stays:
                        removed += 1
                        continue
                kept.append(h)
            if len(kept) == len(g.get("hooks", [])):
                out.append(g)
            elif kept:
                out.append(dict(g, hooks=kept))
        if out != have:
            if out:
                hooks[event] = out
            else:
                del hooks[event]
    summary = ""
    if on and not seen:
        have = hooks.get(want_event, [])
        if not _groups_ok(have):
            summary = ", %s not merged (%s is not a list of hook groups)" % (short, want_event)
        else:
            group = {"matcher": matcher} if matcher else {}
            group["hooks"] = [dict(entry)]
            hooks[want_event] = have + [group]
    if on and not summary:
        summary = ", %s on" % label
    if removed:
        summary += ", %s entries removed %d" % (short, removed)
    if hooks:
        sl["hooks"] = hooks
    elif removed:
        sl.pop("hooks", None)    # emptied by this run: the file is what it was before the guard
    return summary


def _claims(prof):
    """What forge puts in settings.local.json because the profile declares it, as owned claims: each
    permissions allow/deny/ask rule and additionalDirectories entry (located by the string itself), each
    hook entry of the profile's `hooks` (located by event and command). Owner: the profile's name.
    Identities are unique, so a rule listed twice is one claim."""
    owner, now = prof.get("project") or "", {}

    def add(kind, at, value):
        now.setdefault((kind, tuple(at)), owned.claim(kind, at, value, owner))

    perms = prof.get("permissions")
    for k in ("allow", "deny", "ask", "additionalDirectories"):
        for v in perms.get(k) if isinstance(perms, dict) and isinstance(perms.get(k), list) else ():
            if isinstance(v, str):
                add("item", ["permissions", k, v], v)
    hooks = prof.get("hooks")
    for event, groups in (hooks.items() if isinstance(hooks, dict) else ()):
        for g in groups if isinstance(groups, list) else ():
            for h in g.get("hooks", []) if isinstance(g, dict) and isinstance(g.get("hooks", []), list) else ():
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    add("hook", ["hooks", event, h["command"]], h)
    return list(now.values())


def _record(slp, now, apply):
    """owned.record for this file, unless lib.write_json is not forge's own: cli.settings_forge_would_write
    swaps it for a recorder to compute the document forge would write, in memory and with `apply` true,
    and a registry write through the recorder would be taken for that document."""
    if getattr(lib.write_json, "__module__", None) == lib.__name__:
        owned.record(slp, now, apply)


def _prune_item(sl, c):
    """Take the element claim `c` names out of its list, when it is still exactly what forge wrote.
    Returns 1 for an element removed, else 0. A list or object this run empties goes with it."""
    _, key, value = c["at"]
    perms = sl.get("permissions")
    have = perms.get(key) if isinstance(perms, dict) else None
    if not isinstance(have, list) or value not in have or not owned.removable(c, value):
        return 0
    perms[key] = [v for v in have if v != value]
    if not perms[key]:
        del perms[key]
    if not perms:
        del sl["permissions"]
    return 1


def _prune_hook(sl, c, slp_short):
    """Take the hook entry claim `c` names out of the file's hooks, when unchanged; an edited one stays
    and is named on one '  ! ' line. Returns 1 for an entry removed, else 0. A group, an event and the
    `hooks` key this run empties go with it."""
    _, event, command = c["at"]
    hooks = sl.get("hooks")
    have = hooks.get(event) if isinstance(hooks, dict) else None
    if not _groups_ok(have):
        return 0
    for g in have:
        for h in g.get("hooks", []):
            if h.get("command") != command:
                continue
            if not owned.removable(c, h):
                print("  ! %s: hook %s (%s) was edited by hand, left in place" % (slp_short, command, event))
                return 0
            g["hooks"].remove(h)
            if not g["hooks"]:
                have.remove(g)
            if not have:
                del hooks[event]
            if not hooks:
                del sl["hooks"]
            return 1
    return 0


def write_settings_local(ctx, prof, secrets=None, errors=None, project_hooks=()):
    """Owns <project>/.claude/settings.local.json: everything the profile says goes there, merged
    into the file. For a claude profile carrying `plugins_keep` and/or `skills_keep`, that is:
      * enabledPlugins -- full canonical map (kept=True, rest=False; whole-object,
        because CC ignores per-key partial overrides). Written ONLY if `plugins_keep` set.
      * skillOverrides -- every user-global standalone skill, and every project skill of an
        ancestor or nested profile in the same git repository (neighbour_skills), set to
        "off", EXCEPT the project's own .claude/skills/ names AND any in `skills_keep` (an
        allowlist of global skills to keep available in this project; empty -> hide them all).
      * permissions -- union-merged from the profile's `permissions` key, if present.
      * env -- session environment variables from the profile's `env` key, if present.
        Claude Code passes these to the session AND to every subprocess it spawns, so this
        is the supported way to give plugin hooks (which get no env of their own) per-project
        configuration -- see the comment at the env block below.
      * hooks -- the profile's `hooks` ({event: [group, ...]}) appended to the file's, never
        removing anything: a command already in that event is not added again, and a hook written
        by hand beside it stays. How a project's own forge hooks reach that project only.
      * command guard -- `command_guard: true` adds forge's guard as one PreToolUse entry, and
        forge owns every entry that runs hooks/guard_tool_use.py: others go, and all go when the
        line is absent, except what the profile's own `hooks` declares (_own_guard).
      * worktree guard -- `worktree_guard` (lib.worktree_guard_on) does the same for
        hooks/worktree_guard.py, its group behind the matcher of every writing tool (GUARDS).
      * project_hooks -- the rows forge writes per project instead of at user scope
        (forge.hooks.project_hooks: Hindsight's, for a profile that uses it), each owned by its
        exact command the same way: a wanted row ends as one entry, one not wanted goes. The
        callers pass them, so this module never reads config/forge.json.
    Returns a one-line summary string, or None if the profile carries none of those keys and the
    file holds none of the three written only while declared (skillOverrides, enabledPlugins, env),
    which go when the profile stops declaring them.

    TRIMMING vs PASS-THROUGH (fixed): `skillOverrides` is written only when the
    profile asks to be trimmed (`plugins_keep` and/or `skills_keep`). `permissions` and `env`
    are independent pass-throughs and now work on their own. Before this, an UNTRIMMED profile
    (one project) that declared permissions/env had them silently dropped -- and the obvious
    workaround (adding an empty `skills_keep` to make the guard pass) would have turned
    trimming ON and hidden all ~136 global skills from that project."""
    keep = prof.get("plugins_keep")
    skills_keep = set(prof.get("skills_keep") or [])
    trim = bool(keep) or "skills_keep" in prof
    # skills_keep ["*"] -- keep EVERY global skill while still trimming plugins. forge needs
    # exactly this: it pins plugins_keep (to hold the memory plugin off) but authors every
    # global skill, so it must see the whole surface. Without the wildcard, plugins_keep alone
    # switched trimming on and an absent skills_keep hid all 68 globals in the repo that owns
    # them. Listing them one by one would go stale the moment a new skill is authored here.
    all_skills = "*" in skills_keep
    ppath = prof["project_path"]
    slp = os.path.join(ppath, ".claude", "settings.local.json")
    declared = (trim or prof.get("permissions") or prof.get("env") or prof.get("hooks") or prof.get("command_guard")
                or prof.get("worktree_guard") or prof.get("mcpjson_approved") is not None or prof.get("mcpjson_disabled") is not None
                or prof.get("enableAllProjectMcpServers") is not None
                or any(row[5] for row in project_hooks))
    # A profile that declares none of it still owns the keys written only while declared: read
    # the file, and leave early only when it holds none of them. Returning first, as it once did,
    # kept a stale skillOverrides hiding skills in a project that had stopped trimming.
    sl = lib.read_owned(slp)
    # What the last run recorded for this file (forge/owned.py): a profile that dropped everything it
    # declared still has leftovers to prune, so a record keeps the run going.
    prev, warn = owned.previous(slp)
    if warn:
        print(warn)
    if not declared and not prev and not any(k in sl for k in ("skillOverrides", "enabledPlugins", "env")) \
            and not _has_forge_guard(sl) and not _holds(sl, lambda cmd: any(cmd == row[1] for row in project_hooks)):
        return None
    on_machine = global_skills() | neighbour_skills(ppath)
    proj_skills = set(skill_dirs(os.path.join(ppath, ".claude", "skills")))
    overrides = ({} if all_skills
                 else {s: "off" for s in sorted(on_machine - proj_skills - skills_keep)})

    sl_before = lib.dumps(sl)
    pl_summary = "plugins unchanged"
    removed = []
    if keep:
        universe = plugin_universe()
        enabled = {p: (p in keep) for p in universe}
        for p in keep:               # keep entries not in the current universe -> still enable
            enabled.setdefault(p, True)
        sl["enabledPlugins"] = enabled
        pl_summary = "plugins %d/%d on" % (sum(1 for v in enabled.values() if v), len(enabled))
    elif sl.pop("enabledPlugins", None) is not None:
        # Written whole only while `plugins_keep` asks for it, like env: left behind, the map from
        # the last trimmed run keeps every plugin it switched off, off.
        removed.append("enabledPlugins")
        pl_summary = "plugins untrimmed"
    if trim and not all_skills:
        sl["skillOverrides"] = overrides
    elif sl.pop("skillOverrides", None) is not None and not trim:
        # Under the wildcard, dropped silently as it always was: writing an empty map is harmless,
        # but a STALE one left from before would keep every skill off. Absent == all available.
        # Untrimmed, the same stale map hid the skills of a profile that stopped trimming.
        removed.append("skillOverrides")

    # permissions pass-through (ADR-010): persist a per-project
    # permission allowlist via the profile so it survives SessionStart, instead of hand-editing
    # settings.local.json (which AGENT-SYSTEM.md forbids). Union-merge allow/deny/ask so
    # CLI-approved permissions and repeated runs never duplicate or clobber; any other
    # permission key (e.g. defaultMode) overwrites. Profiles without "permissions" are untouched.
    perm_summary = ""
    perms = prof.get("permissions")
    if perms:
        cur = sl.get("permissions") or {}
        for k in ("allow", "deny", "ask"):
            if perms.get(k):
                cur[k] = list(dict.fromkeys((cur.get(k) or []) + list(perms[k])))
        for k, v in perms.items():
            if k not in ("allow", "deny", "ask"):
                cur[k] = v
        sl["permissions"] = cur
        perm_summary = ", perms allow %d" % len(cur.get("allow") or [])

    # env pass-through (project memory/plugin routing). Claude Code applies settings `env` to every
    # session AND to the subprocesses it spawns -- which is how plugin hooks inherit it, and how
    # claude-mem-lite's hooks find CLAUDE_MEM_DIR. Plugin hooks are invoked with no environment of
    # their own, so without this they fall back to one shared default store (the failure that
    # sent claude-mem's capture into another project's store for months). Whole-key overwrite is
    # intentional: stale memory variables must disappear when dropped from the profile -- which is
    # how the retired CLAUDE_MEM_DATA_DIR / CLAUDE_MEM_WORKER_PORT left every project when claude-mem was retired.
    env_summary, from_secrets = "", 0
    prof_env = prof.get("env")
    if prof_env:
        # Sorted, not insertion-ordered: CLAUDE_MEM_DIR is derived and appended by
        # derive_lite_env(), so insertion order would depend on whether a profile happened to
        # declare it and where. Sorting makes the output a function of the content alone.
        #
        # A value of the exact form ${NAME} is a secret, resolved here from the same secrets the
        # MCP servers' env is (mcp.resolve_secrets), never copied as text: the project's sessions
        # get the real value in their environment. A NAME the secrets lack is an error and the
        # key is not written, so a session never sees the literal "${NAME}" as a password. The
        # line only counts them; a value is never printed.
        refs = {k: v for k, v in prof_env.items() if isinstance(v, str) and mcp.VARRE.match(v)}
        got = mcp.resolve_secrets(refs, secrets or {}, [], "")
        for k in refs:
            if k not in got and errors is not None:
                errors.append("env %s -> secret %s is EMPTY/missing" % (k, mcp.VARRE.match(refs[k]).group(1)))
        from_secrets = len(got)
        sl["env"] = {k: got.get(k, prof_env[k]) for k in sorted(prof_env) if k not in refs or k in got}
        env_summary = ", env %d%s" % (len(prof_env), " (%d from secrets)" % from_secrets if from_secrets else "")
    elif sl.pop("env", None) is not None:
        # The key is generator-owned in both directions: a profile with no env gets none. Only
        # overwriting when the profile had one left a project capturing into a retired
        # claude-mem store for days after its profile stopped declaring it (found in use).
        env_summary = ", env removed"

    # hooks pass-through (T4 of docs/hooks-phase-design.md): one project's guard, audit and skill-tracking
    # hooks were written by hand into this git-ignored file, so a fresh machine never got them, and
    # at user scope they would have run in every project. Appending only, like permissions: removing
    # an entry is a hand edit of profile and file. The file's own hooks (that project's two cache
    # refreshers) are never ours to touch, so the key is merged into, not replaced.
    hooks_summary = ""
    prof_hooks = prof.get("hooks")
    if prof_hooks:
        cur = sl.get("hooks")
        if cur is not None and not isinstance(cur, dict):
            hooks_summary = ", hooks not merged (the file's is not an object)"
        else:
            cur = sl["hooks"] = cur if cur is not None else {}
            merged, skipped = 0, []
            for event, groups in prof_hooks.items():
                have = cur.get(event, [])
                # Not ours to fix: a hand-corrupted event (not a list, a group that is not an object
                # or whose `hooks` is not a list of objects: _groups_ok) stays as the file has it, and the
                # line names it. Dedupe by command cannot be trusted over such an entry (round 8).
                if not _groups_ok(have):
                    skipped.append(event)
                    continue
                present = {h.get("command") for g in have for h in g.get("hooks", [])}
                for g in groups:
                    new = [h for h in g.get("hooks", []) if h.get("command") not in present]
                    if new:
                        have.append(dict(g, hooks=new))
                        present.update(h.get("command") for h in new)
                cur[event] = have
                merged += sum(len(g.get("hooks", [])) for g in groups)
            hooks_summary = ", hooks %d" % merged + "".join(
                ", %s not merged (the file's is not a list of hook groups)" % e for e in skipped)

    # The command guard (T2 of docs/command-guard-design.md) and the worktree guard: forge owns
    # every entry that runs one of its guards, which the append-only merge above could never remove.
    for row in GUARDS:
        hooks_summary += _own_guard(sl, prof, row)
    for event, cmd, timeout, marker, matcher, wanted in project_hooks:
        hooks_summary += _own_hook(sl, prof, lambda c, cmd=cmd: c == cmd, event, canonical_hook(cmd, timeout),
                                   matcher, wanted, "%s %s" % (marker, event), marker)

    # What the profile declared last time and no longer does goes, if it is still what forge wrote: forge
    # cannot tell its leftovers from the user's in-session approvals in the same lists, so only an element
    # it claimed (forge/owned.py) is ever removed, and only unchanged. A hook entry edited since stays and
    # is named. With no record nothing is stale. Runs after both merges, so a rule still declared stays.
    now = _claims(prof)
    slp_short = lib.short(slp)
    pruned = 0
    for c in owned.stale(prev, now):
        if c["kind"] == "item" and len(c["at"]) == 3 and c["at"][0] == "permissions":
            pruned += _prune_item(sl, c)
        elif c["kind"] == "hook" and len(c["at"]) == 3 and c["at"][0] == "hooks":
            pruned += _prune_hook(sl, c, slp_short)
    pruned_summary = ", pruned %d" % pruned if pruned else ""

    # .mcp.json approval, owned by the profile when it declares `mcpjson_approved` (the list) or
    # `enableAllProjectMcpServers` (that key alone, with or without a list). Claude Code
    # reads enableAllProjectMcpServers and enabledMcpjsonServers from settings.local.json, and
    # the generator once wrote them only into ~/.claude.json -- so whatever a session
    # had once approved in-session stayed approved. One project's file said
    # enableAllProjectMcpServers true and approved a server (one that writes to a real
    # account, meant for a single project only) and a retired claude-mem entry, while its
    # profile said false. With the key declared, the list is written whole (never merged) and
    # the profile's enableAllProjectMcpServers lands here too. Registry servers need no entry:
    # they are local scope in ~/.claude.json, not .mcp.json servers. .mcp.json itself is never
    # read -- it can hold tokens, and the list is the profile's decision, not the file's.
    #
    # Approval alone does not keep a server out. Measured on 2.1.280 in print mode,
    # which is how an unattended agent runs: a .mcp.json server with enableAllProjectMcpServers
    # false and an empty approved list still started (init status "pending"), exactly as with no
    # keys at all; only disabledMcpjsonServers kept it out (init listed no server). So a profile
    # can also name servers in `mcpjson_disabled`, written whole into disabledMcpjsonServers.
    mcp_summary = ""
    approved = prof.get("mcpjson_approved")
    if prof.get("enableAllProjectMcpServers") is not None:
        sl["enableAllProjectMcpServers"] = prof["enableAllProjectMcpServers"]
    if approved is not None:
        sl["enabledMcpjsonServers"] = list(approved)
        mcp_summary = ", .mcp.json approved %d%s" % (
            len(approved), "" if sl.get("enableAllProjectMcpServers") is not True else " (ALL: on)")
    elif sl.get("enableAllProjectMcpServers") is True:
        mcp_summary = ", .mcp.json (ALL: on)"
    disabled = prof.get("mcpjson_disabled")
    if disabled is not None:
        sl["disabledMcpjsonServers"] = list(disabled)
        mcp_summary += ", .mcp.json disabled %d" % len(disabled)

    skill_summary = ("%s, skills off %d, kept-global %s"
                     % (pl_summary, len(overrides), "ALL (*)" if all_skills else len(skills_keep))
                     if trim else "untrimmed (pass-through only)")
    removed_summary = ", %s removed" % " and ".join(removed) if removed else ""
    summary = "overrides -> %s (%s%s%s%s%s%s%s)" % (
        slp_short, skill_summary, removed_summary, perm_summary, env_summary, hooks_summary, mcp_summary, pruned_summary)
    # The file carries resolved secrets from here on, so it is 0600 (mcp.loose_secrets, the rule
    # ~/.claude.json follows): set when written, and corrected when the content is current but the
    # mode is not, since Claude Code rewrites this file too.
    loose = [os.path.basename(p) for p in mcp.loose_secrets(slp)] if from_secrets else []
    if lib.dumps(sl) == sl_before and os.path.exists(slp):
        if not loose:
            _record(slp, now, ctx.apply)
            return "   %s (already current)" % summary
        if ctx.apply:
            for p in mcp.loose_secrets(slp):
                lib.chmod(p, 0o600)
        _record(slp, now, ctx.apply)
        return "   %s (content current, %schmod 600 %s)" % (summary, "" if ctx.apply else "would ", ", ".join(loose))
    if ctx.apply:
        lib.write_json(slp, sl, mode=0o600 if from_secrets else None, backup=True)
        _record(slp, now, ctx.apply)
        return "   " + summary
    return "   would write " + summary


def _agents_link(name):
    """The target of our link .agents/skills/<name>: relative, so a clone of the repo anywhere
    still resolves. The create check and the prune check both ask this, so they cannot drift."""
    return os.path.join("..", "..", ".claude", "skills", name)


def mirror_for_codex(ctx, prof):
    """Make a project's OWN skills visible to Codex, not just to Claude Code.

    Project-local skills live in <project>/.claude/skills -- the vendored design skills in
    a design-heavy project, a Tauri app's skills, a framework's skills, an interface set. Claude Code
    reads that directory natively. Codex never looks there. Measured with
    `codex debug prompt-input` (renders the model-visible prompt with no model call) run in
    such a project: the eight vendored design skills appeared in NO skill root, while the ~/.codex/skills
    mirror of forge's global skills appeared in full. The project half was silently missing in
    all six projects that have one -- 156 skills.

    Codex's project-level skill roots, both confirmed by the same command after planting one
    symlink in each: <project>/.codex/skills and <project>/.agents/skills. Symlinks are
    followed, so one link per skill is enough and the skill text is never copied.

    `.agents/skills` is the one used here, not .codex/skills: .codex/ carries real secrets
    (lib.ensure_ignored() git-ignores it), and `.agents/skills` is the cross-agent convention
    Kaneo shipped, which is where one project's own `.agents/skills` came from before a
    deletion sweep removed it as a duplicate of the vendored copies -- correct about the
    duplication, and the reason Codex went blind.

    Non-destructive and idempotent, same contract as relink_skills.py: only CREATES and
    REPOINTS links, and PRUNES a link of ours whose skill is gone. A real directory or file in
    .agents/skills is never touched -- if a project ever keeps a real skill there, it stays.
    """
    ppath = prof["project_path"]  # sync.py skips a profile without one before calling this
    src = os.path.join(ppath, ".claude", "skills")
    if not os.path.isdir(src):
        return ""
    # A skill is a directory holding a SKILL.md. This skips the loose notes that sit beside
    # them (README-VENDOR-POLICY.md, AUDIT-SYNTHESIS.md) and any
    # half-made directory that would show up in Codex's listing as a broken entry.
    names = sorted(
        d for d in os.listdir(src)
        if not d.startswith(".")
        and os.path.isfile(os.path.join(src, d, "SKILL.md"))
    )
    dst = os.path.join(ppath, ".agents", "skills")
    # A file where a directory must be: no link could be made, so none is promised in a dry-run,
    # no .gitignore line is added for them, and --apply does not raise out of the run.
    for sub in (".agents", os.path.join(".agents", "skills")):
        where = os.path.join(ppath, sub)
        if names and os.path.lexists(where) and not os.path.isdir(where):
            return "   ! codex sees project skills -> %s NOT linked (%s is not a directory)" % (lib.short(dst), sub)
    # These links are a generated artifact, regenerated every SessionStart, and the
    # Claude/Codex duality they serve is one machine's setup -- a teammate cloning the repo
    # neither needs them nor should meet them in a diff. So .agents/ is git-ignored the same
    # way .codex/ is, EXCEPT where the directory already carries tracked content: the vault's
    # hand-made links (the three tutor ones, left after Copilot's six were removed)
    # are committed on purpose, and an ignore line there would be a
    # lie about a tracked path. `git ls-files` decides, so a project that starts tracking them
    # later stops getting the line. Asked once, before any link: where git would not ignore
    # them, none is made.
    gi = ""
    if names and not lib.gitignore_has(ppath, ".agents/") and not lib.git_tracks(ppath, ".agents"):
        ignored, gi = lib.ensure_ignored(ctx.apply, ppath, ".agents/", lib.repo_owns_tracked_files(prof))
        if not ignored:
            return "   ! codex sees project skills -> %s NOT linked%s" % (lib.short(dst), gi)
    created, repointed, pruned = [], [], []
    existing = set(os.listdir(dst)) if os.path.isdir(dst) else set()

    for name in names:
        link = os.path.join(dst, name)
        want = _agents_link(name)  # .agents/skills/x -> ../../.claude/skills/x
        if os.path.islink(link):
            if os.readlink(link) == want:
                continue
            # An existing link that already lands on the SAME skill is left exactly as it is,
            # spelling and all. The vault reached .agents/skills first, by hand,
            # with absolute links straight to the copilot sources; .claude/skills/<name> there
            # links to those same directories, so repointing would churn thirteen correct links
            # (three now) to say the same thing a different way.
            if os.path.exists(link) and os.path.realpath(link) == os.path.realpath(
                    os.path.join(src, name)):
                continue
            if not ctx.apply:
                repointed.append(name)
                continue
            lib.replace_symlink(want, link)
            repointed.append(name)
            continue
        if os.path.exists(link):
            continue  # a real dir or file -- someone else's, leave it
        if not ctx.apply:
            created.append(name)
            continue
        if not os.path.isdir(dst):
            os.makedirs(dst)
        lib.symlink(want, link)
        created.append(name)

    # Prune only OUR links: a symlink into ../../.claude/skills whose target is gone.
    for name in sorted(existing):
        link = os.path.join(dst, name)
        if not os.path.islink(link):
            continue
        if os.readlink(link) != _agents_link(name):
            continue
        if name in names:
            continue
        if ctx.apply:
            lib.unlink(link)
        pruned.append(name)

    parts = []
    if created:
        parts.append("+%d" % len(created))
    if repointed:
        parts.append("~%d" % len(repointed))
    if pruned:
        parts.append("-%d" % len(pruned))
    state = " ".join(parts) if parts else "already current"
    return "   codex sees project skills -> %s (%d skill(s)%s)%s%s" % (
        lib.short(dst), len(names),
        "" if state == "already current" else ", " + state,
        gi,
        "" if ctx.apply or (state == "already current" and not gi) else "  [dry-run]",
    )
