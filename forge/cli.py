"""forge -- one command for the agent-config platform.

  forge init             first run for a new checkout: config/forge.json, a profile for the checkout itself,
                         an empty registry and secrets file, then sync --apply --all and doctor
  forge add PATH         register a project: config/profiles/NAME.claude.json, then sync --apply --project NAME
  forge sync [--apply]   regenerate every project's config, in a fixed order, one run at a time
  forge doctor [NAME]    one line per check: what is broken, and the command that fixes it;
                         with a project's name, only the checks that concern it, scoped to it
  forge test             run every test_*.py in the repo
  forge toolchain [--fix]  the third-party tools in config/toolchain.json, installed by mise at their pin
                         (and the two files forge writes for mise); --fix writes the files and installs what is missing
  forge metrics NAME     a project's harness metrics from its Claude Code transcripts (--baseline: one session)
  forge session-start    the SessionStart hook: this session's project only, silent unless it wrote
  forge check-public     --staged | --all | --range A..B | --message FILE: personal data that must not be published
  forge commit -m MSG (PATH... | --all)  each changed path to the history that owns it (forge/publish.py)
  forge uninstall [--integration N | --project N] [--apply]  take out what forge wrote (forge/uninstall.py)

Every step is still the script it was (scripts/sync/*.py and the doctors); this is the one place
that says which runs, in what order, and what "healthy" means.
"""
import argparse
import contextlib
import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

from forge import lib, mcp, owned, skills, toolchain

# The order is the contract: skill links come first because the overrides are computed from
# them, the system doc comes last. (name, script, its dry-run flag, its apply flag, user_scope_only.)
# user_scope_only: the step writes only user-scope files and returns 0 at once without ctx.globals
# (relink_skills.main, sync_gsd_runtime.main), so a session start whose lib.session_scope has no
# globals skips it instead of paying an interpreter start for nothing (0.2-0.6 s each, measured in
# a project session). forge sync runs every row.
SYNC = [
    ("skill links", "scripts/sync/relink_skills.py", "--dry-run", None, True),
    ("gsd runtime", "scripts/sync/sync_gsd_runtime.py", None, "--apply", True),
    ("agent config", "scripts/sync/sync_agent_config.py", None, "--apply", False),
    ("system doc", "scripts/sync/sync_system_doc.py", None, "--apply", False),
]
# The integration (lib.INTEGRATIONS) a step belongs to, by name: with it off, forge sync says so and
# does not run the step, and a session start does not either (docs/portable-design.md section 5).
STEP_INTEGRATION = {"gsd runtime": "gsd"}


def skill_name_clashes(only=None):
    """A WARN when a project skill (<project_path>/.claude/skills/<name>) is named like a global
    skill, else a PASS saying how many project skills in how many projects it read. The global names
    are forge's skills/ plus ~/.claude/skills, because some global skills live only there (omarchy and
    diagnose-crash link into /usr/share/omarchy). Frozen profiles are skipped (docs/orchestration.md,
    because a frozen project's own copies of a global skill kept warning); the frozen drift row reports a
    frozen project's divergence. By name a frozen project is a SKIP. The name is project:skill, in
    sorted order. A profile with no project_path, or whose directory is gone, is not read: a WARN naming it, and a FAIL when no project at all was read
    (non-negotiable 7). A project with no .claude/skills is read, and clean. With `only`, that
    project's skills alone (forge doctor NAME)."""
    shared = set(skills.skill_dirs(os.path.join(lib.ROOT, "skills"))) | skills.global_skills()
    profs = lib.profiles()
    if only and profs.get(only, {}).get("frozen"):
        return lib.Result("SKIP", "skill names", "%s: frozen, forge does not read it (the frozen drift row reports it)" % only)
    clashes, unread, read, count = [], [], 0, 0
    for name, prof in profs.items():
        if only not in (None, name) or prof.get("frozen"):
            continue
        if not prof.get("project_path") or not os.path.isdir(prof["project_path"]):
            unread.append(name)
            continue
        found = skills.skill_dirs(os.path.join(prof["project_path"], ".claude", "skills"))
        read, count = read + 1, count + len(found)
        clashes += ["%s:%s" % (name, s) for s in found if s in shared]
    note = "not read, no project_path or no such directory: %s" % ", ".join(sorted(unread)) if unread else ""
    if not read:
        return lib.Result("FAIL", "skill names", "; ".join(["no project read"] + ([note] if note else [])))
    seen = "read %d project skill(s) in %d project(s)" % (count, read)
    if clashes:
        return lib.Result("WARN", "skill names", "; ".join([", ".join(sorted(clashes))] + ([note] if note else [])))
    if unread:
        return lib.Result("WARN", "skill names", "%s; %s" % (note, seen))
    return lib.Result("PASS", "skill names", "%s, none shares a global skill's name" % seen)


def settings_forge_would_write(name, prof, registry):
    """The settings.local.json document the generator would write for `prof` (the dict forge/sync.py
    hands skills.write_settings_local, as if the profile were not frozen), or None when it would write
    nothing because the file is already what it says. Computed in memory: lib.write_json is replaced by
    a recorder for the call, so no byte reaches the project, no .bak and no ownership record either; the
    document is the last one recorded for a path other than the record's (owned.path()). The recorder is
    restored in a finally."""
    from forge import hooks, owned  # not at import: hooks reads config/forge.json
    sel = [s for s in prof.get("servers", []) if s in registry]
    wanted, real = [], lib.write_json
    lib.write_json = lambda path, data, **kw: wanted.append((path, data))
    try:
        skills.write_settings_local(lib.Ctx(True, {name}, False), mcp.with_denied_tools(prof, sel, registry), None, None,
                                    hooks.project_hooks(prof))
    finally:
        lib.write_json = real
    docs = [data for path, data in wanted if path != owned.path()]
    return docs[-1] if docs else None


ABSENT = object()


def drift_size(doc, key):
    """How a key's value is shown in the drift row: its length when it is a list or an object (the
    row never prints a value), "absent" when the key is missing, else "set"."""
    if key not in doc:
        return "absent"
    return str(len(doc[key])) if isinstance(doc[key], (list, dict)) else "set"


def frozen_drift(only=None):
    """A WARN naming, per frozen profile, the settings.local.json keys whose value differs from what
    forge would write there if the profile were not frozen (settings_forge_would_write); a PASS when
    none differs. Always says how many frozen profiles it compared. A frozen profile that cannot be
    compared (no project_path, no such directory, a settings file that does not parse) is named in
    a WARN, and when some profile is frozen and none could be compared the row is a FAIL (non-negotiable
    7); with no frozen profile there is nothing to compare, a PASS. Frozen means forge writes nothing,
    not that the file does not change: Claude Code rewrites settings.local.json itself (approvals,
    permissions), and one frozen project's file approved 5 .mcp.json servers where its profile said none
    (measured). Read-only. With `only`, that project's row (forge doctor NAME)."""
    profs = lib.profiles()
    if only and not profs.get(only, {}).get("frozen"):
        return lib.Result("SKIP", "frozen drift", "%s is not frozen, so forge writes its settings and the generated row covers them" % only)
    frozen = {n: p for n, p in profs.items() if p.get("frozen") and only in (None, n)}
    if not frozen:
        return lib.Result("PASS", "frozen drift", "no profile is frozen, nothing to compare")
    doc = lib.read_json(os.path.join(lib.ROOT, "config", "mcp-registry.json"), quiet=True)
    registry = doc.get("servers") if isinstance(doc, dict) else None
    if not isinstance(registry, dict):
        return lib.Result("FAIL", "frozen drift", "config/mcp-registry.json has no servers object, so nothing was compared")
    drifts, unread, compared = [], [], 0
    for name, prof in sorted(frozen.items()):
        if not prof.get("project_path") or not os.path.isdir(prof["project_path"]):
            unread.append(name)
            continue
        slp = os.path.join(prof["project_path"], ".claude", "settings.local.json")
        try:
            disk = lib.read_owned(slp)
            wanted = settings_forge_would_write(name, prof, registry)
        except lib.Unreadable:
            unread.append(name)
            continue
        compared += 1
        wanted = disk if wanted is None else wanted
        keys = sorted(k for k in set(disk) | set(wanted) if disk.get(k, ABSENT) != wanted.get(k, ABSENT))
        if keys:
            drifts.append("%s: %s" % (name, ", ".join("%s (%s on disk, %s from forge)" % (k, drift_size(disk, k), drift_size(wanted, k))
                                                      for k in keys)))
    count = "compared %d frozen profile(s)" % compared
    note = "not read, no project_path, no such directory or an unreadable settings file: %s" % ", ".join(unread) if unread else ""
    if not compared:
        return lib.Result("FAIL", "frozen drift", "%s, and a check that saw nothing is not a pass; %s" % (count, note))
    if drifts or unread:
        return lib.Result("WARN", "frozen drift", "; ".join(drifts + ([note] if note else []) + [count]))
    return lib.Result("PASS", "frozen drift", "%s, each settings.local.json is what forge would write" % count)


# Tools that write their own block into AGENTS.md or CLAUDE.md when they detect an agent: an
# instruction to every agent that nobody reviewed (docs: research/21-para-forge/07). turbo from
# 2.11.5 (root AGENTS.md, again on every run; older turbo refuses the key below) and `next dev`
# (AGENTS.md and CLAUDE.md beside the app). Markers: node_modules/turbo/docs/reference/
# configuration.mdx (agentGuidance) and node_modules/next/dist/server/lib/generate-agent-files.d.ts.
FOREIGN_BLOCKS = {
    "turborepo-agent-rules": 'set "agentGuidance": false in the root turbo.json and delete the block',
    "nextjs-agent-rules": "set agentRules: false in next.config and delete the block",
}
# Any other <!-- BEGIN:name --> is warned too. forge's own markers (the SYSTEM-POINTER pair,
# ds-readiness:begin) have no colon after BEGIN, so they never match.
FOREIGN_BLOCK = re.compile(r"<!--\s*BEGIN:([\w.-]+)\s*-->")
FOREIGN_FIX = "a tool wrote this block; remove it and switch that tool's setting off"
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")
INSTRUCTION_DEPTH = 3  # levels of directories below project_path: next dev writes beside the app
INSTRUCTION_SKIP = {"node_modules", "dist", "build", "venv", "env", "__pycache__"}  # and every hidden dir


def instruction_not_project():
    """The profile names the instruction-file row does not read: config/forge.json's
    `instruction_files_skip` (a machine's lists `dev`, all of ~/dev: it would repeat every other profile)."""
    return set(lib.settings().get("instruction_files_skip") or [])


def instruction_paths(root):
    """Real paths of the AGENTS.md and CLAUDE.md files up to INSTRUCTION_DEPTH levels under `root`,
    that can be read. A link (AGENTS.md -> CLAUDE.md) is its target, so a file counts once."""
    out = set()
    for d, dirs, files in os.walk(root):
        dirs[:] = [] if d[len(root):].count(os.sep) >= INSTRUCTION_DEPTH else sorted(
            x for x in dirs if not x.startswith(".") and x not in INSTRUCTION_SKIP)
        out.update(os.path.realpath(os.path.join(d, f)) for f in INSTRUCTION_FILES if f in files)
    return sorted(p for p in out if os.path.isfile(p))


def instruction_file_blocks(only=None):
    """WARN lines, one per block a tool wrote into an instruction file of a project (project:file:line
    marker: fix), else a PASS that says how many files it read; a FAIL when it read none, since a
    check that saw nothing is not a pass (non-negotiable 7). Frozen profiles are skipped, and so is
    `dev`; nothing is written. A file read through two paths is one, named by its real path, and
    belongs to the deepest project that holds it (a project nested in another's tree is its own, not the outer one's). With `only`, that
    project's files alone."""
    profs, skip = lib.profiles(), instruction_not_project()
    if only and (profs.get(only, {}).get("frozen") or only in skip):
        return lib.Result("SKIP", "instruction files", "%s: frozen or not a project, forge does not read it" % only)
    roots = sorted(((os.path.realpath(p["project_path"]), n) for n, p in profs.items()
                    if p.get("project_path") and not p.get("frozen") and n not in skip),
                   key=lambda r: (-len(r[0]), r[1]))
    owner, found = {}, []  # real path -> project; (project:file:line, marker, fix)
    for root, name in roots:
        for real in instruction_paths(root):
            if real in owner:
                continue
            try:
                with open(real, encoding="utf-8", errors="replace") as fh:
                    lines = fh.read().splitlines()
            except OSError:
                continue
            owner[real] = name
            rel = os.path.relpath(real, root) if real.startswith(root + os.sep) else real
            for i, line in enumerate(lines, 1):
                for m in FOREIGN_BLOCK.finditer(line):
                    found.append(("%s:%s:%d" % (name, rel, i), "BEGIN:" + m.group(1),
                                  FOREIGN_BLOCKS.get(m.group(1), FOREIGN_FIX)))
    # `only` filters after the attribution, so a nested project's file stays its own.
    owner = {r: n for r, n in owner.items() if only in (None, n)}
    found = [f for f in found if only in (None, f[0].split(":")[0])]
    count = "read %d instruction file(s) in %d project(s)" % (len(owner), len(set(owner.values())))
    if not owner:
        return lib.Result("FAIL", "instruction files", "read 0 instruction files in %d project(s), and a check that saw "
                          "nothing is not a pass (does project_path hold an AGENTS.md or CLAUDE.md?)"
                          % len({n for _, n in roots if only in (None, n)}))
    if found:
        return [lib.Result("WARN", "instruction files", "%s %s: %s" % row) for row in sorted(found)] + [
            lib.Result("WARN", "instruction files", "%s, %d tool-managed block(s)" % (count, len(found)))]
    return lib.Result("PASS", "instruction files", count + ", no tool-managed block")


# The smoke check of docs/command-guard-design.md ("Tests"): for every profile with
# `"command_guard": true`, the guard is wired, its config parses, and the wired command refuses a
# canary and allows a harmless command.
GUARD_KEYS = {"_doc", "secret_paths", "harness_paths"}
GUARD_ENTRY_KEY = {"secret_paths": "pattern", "harness_paths": "path"}
GUARD_CANARY, GUARD_BENIGN = "cat ~/.npmrc", "git status"


def guard_config_error(name):
    """Why config/guard/<name>.json is not usable, or None. A missing file is fine (the core runs
    alone); one that does not parse, has a key the guard does not know, or an entry of the wrong
    shape is not, because the guard refuses every call with such a file."""
    path = os.path.join(lib.ROOT, "config", "guard", name + ".json")
    if not os.path.exists(path):
        return None
    where = "config/guard/%s.json" % name
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        return "%s does not parse (%s)" % (where, e)
    if not isinstance(doc, dict):
        return "%s is not a JSON object" % where
    unknown = sorted(set(doc) - GUARD_KEYS)
    if unknown:
        return "%s has unknown key(s): %s" % (where, ", ".join(unknown))
    for key, field in GUARD_ENTRY_KEY.items():
        entries = doc.get(key, [])
        if not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get(field), str) for e in entries):
            return "%s: %s is not a list of objects with a \"%s\" string" % (where, key, field)
    for e in doc.get("secret_paths", []):
        try:
            re.compile(e["pattern"])
        except re.error as err:
            return "%s: secret_paths pattern %r is not a regex (%s)" % (where, e["pattern"], err)
    return None


# What to do when a guard's canonical command (skills.canonical_hook) sits in any other entry:
# _own_guard (forge/skills.py) keeps the first entry whose command is canonical, whatever its type,
# timeout or async, so `forge sync --apply` alone does not mend it (found with Codex: "type":
# "prompt" and "timeout": 0 both passed this row).
NOT_CANONICAL = ("; an entry with the canonical command but another type, timeout or key is kept by forge sync, "
                 "so delete it by hand from settings.local.json and run forge sync --apply")


def guard_hook_entries(hooks, script):
    """Every hook entry (the dict) in a settings `hooks` object's PreToolUse groups whose command
    runs `script`, with its group's matcher: [(matcher, entry)]."""
    groups = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    return [(g.get("matcher"), h) for g in groups or [] if isinstance(g, dict) for h in g.get("hooks") or []
            if isinstance(h, dict) and isinstance(h.get("command"), str) and script in h["command"]]


def settings_guard_entries(prof, script):
    """The guard entries of the profile's project's settings.local.json: (path, entries, None), the
    entries as guard_hook_entries lists them, or (path, None, why) when the file cannot be read."""
    slp = os.path.join(prof["project_path"], ".claude", "settings.local.json")
    try:
        with open(slp, encoding="utf-8") as fh:
            return slp, guard_hook_entries(json.load(fh).get("hooks"), script), None
    except (OSError, ValueError, AttributeError) as e:
        return slp, None, "%s cannot be read (%s)" % (slp, type(e).__name__)


# The command guard's group has no matcher (skills.GUARDS), so it sees every tool; Claude Code reads
# an empty matcher and "*" the same way. Any other matcher keeps the guard from some tool it covers.
GUARD_ALL_TOOLS = (None, "", "*")


def guard_problem(name, prof):
    """Why this guarded profile's guard would not hold in a session, or None: the first thing wrong
    among the profile's own hooks block, the settings file, the config file and the live command."""
    if guard_hook_entries(prof.get("hooks"), skills.GUARD_SCRIPT):
        return "the profile's hooks block also runs %s; command_guard is the one way to turn it on" % skills.GUARD_SCRIPT
    if not prof.get("project_path"):
        return "the profile has no project_path"
    slp, entries, why = settings_guard_entries(prof, skills.GUARD_SCRIPT)
    if why:
        return why
    found = [h for _, h in entries]
    command = skills.guard_command(name)
    if found != [skills.canonical_hook(command)]:
        return "%s holds %d guard entr%s %s, want exactly one: %s%s" % (
            slp, len(found), "y" if len(found) == 1 else "ies", found or "", skills.canonical_hook(command),
            NOT_CANONICAL if [h.get("command") for h in found] == [command] else "")
    if entries[0][0] not in GUARD_ALL_TOOLS:
        return "%s runs the guard behind matcher %s, want none (every tool): %s" % (slp, entries[0][0], command)
    bad = guard_config_error(name)
    if bad:
        return bad
    env = dict(os.environ, CLAUDE_PROJECT_DIR=prof["project_path"])
    for text, code in ((GUARD_CANARY, 2), (GUARD_BENIGN, 0)):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": text}})
        try:
            r = subprocess.run(command, shell=True, input=payload, env=env, text=True,
                               capture_output=True, timeout=skills.GUARD_TIMEOUT)
        except subprocess.TimeoutExpired:
            return "`%s` did not answer in %d s" % (text, skills.GUARD_TIMEOUT)
        if r.returncode != code:
            return "`%s` exited %d, want %d%s" % (text, r.returncode, code,
                                                   (": " + r.stderr.strip().splitlines()[-1]) if r.stderr.strip() else "")
    return None


def guard_profile_errors(field, only=None):
    """[(project, why)], by name, for every profile lib.profiles leaves out for an error that names
    `field` (command_guard, worktree_guard): a guard the profile asked for must not read as one it
    did not ask for, so the guard's smoke check FAILs a row for each. `only` scopes it to one."""
    skipped = []
    lib.profiles(skipped)
    return sorted((f[:-len(".claude.json")], why) for f, why in skipped
                  if field in why and only in (None, f[:-len(".claude.json")]))


def command_guard_smoke(only=None):
    """One result per profile that sets command_guard (a frozen one gets no settings, so it is not
    guarded), named `guard <project>`; one PASS when none does. With `only`, that profile alone."""
    rows = []
    for name, prof in sorted(lib.profiles().items()):
        if only in (None, name) and prof.get("command_guard") is True and not prof.get("frozen"):
            why = guard_problem(name, prof)
            rows.append(lib.Result("FAIL", "guard " + name, why) if why else lib.Result(
                "PASS", "guard " + name, "one canonical entry, config ok, `%s` refused, `%s` allowed" % (GUARD_CANARY, GUARD_BENIGN)))
    rows += [lib.Result("FAIL", "guard " + n, why) for n, why in guard_profile_errors("command_guard", only)]
    return rows or lib.Result("PASS", "command guard", "%s does not turn it on, or is frozen" % only if only
                              else "no profile turns it on")


# The worktree guard's smoke check (W3 of research/21-para-forge/04-guarda-de-worktrees.md): for
# every profile that turns it on (lib.worktree_guard_on, not frozen), its settings.local.json holds
# exactly the canonical group, matcher included, and the wired command, run from a toy linked
# worktree, refuses a Write into the toy's main checkout and allows one inside the worktree. Unlike
# the command guard's, a profile that asks for it and is frozen is a FAIL (non-negotiable 7); no
# profile asking for it is a SKIP.
WT_SCRIPT, WT_MATCHER = next(row[:2] for row in skills.GUARDS if row[0] == "worktree_guard.py")


def worktree_probe(command):
    """None when `command` refuses a Write from a toy linked worktree into its main checkout, with
    the hook's own BLOCKED line, and allows one inside the worktree; else why not. The toy lives in
    the temp dir, which the hook takes for scratch unless WORKTREE_GUARD_SCRATCH is set empty."""
    tmp = tempfile.mkdtemp(prefix="forge-wtguard-")
    try:
        main, wt = os.path.join(tmp, "main"), os.path.join(tmp, "main", ".claude", "worktrees", "probe")
        os.makedirs(main)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        git_env = dict(env, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "probe"], ["worktree", "add", "-q", "-b", "probe", wt]):
            subprocess.run(["git", "-c", "user.name=forge", "-c", "user.email=forge@localhost"] + args, cwd=main,
                           env=git_env, capture_output=True, check=True)
        for target, code in ((os.path.join(main, "guard-probe.txt"), 2), (os.path.join(wt, "guard-probe.txt"), 0)):
            payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": target, "content": "x"}, "cwd": wt})
            where = "into the main checkout" if code else "inside the worktree"
            try:
                r = subprocess.run(command, shell=True, input=payload, env=dict(env, WORKTREE_GUARD_SCRATCH=""),
                                   text=True, capture_output=True, timeout=skills.GUARD_TIMEOUT)
            except subprocess.TimeoutExpired:
                return "a Write %s did not get an answer in %d s" % (where, skills.GUARD_TIMEOUT)
            last = (r.stderr.strip().splitlines() or [""])[-1]
            if r.returncode != code or (code and not last.startswith("worktree_guard: BLOCKED")):
                return "a Write %s from a toy worktree exited %d, want %d%s%s" % (
                    where, r.returncode, code, " with the hook's BLOCKED line" if code else "",
                    (": " + last) if last else "")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def worktree_guard_problem(name, prof):
    """Why this profile's worktree guard would not hold in a session, or None."""
    if not prof.get("project_path"):
        return "the profile has no project_path"
    slp, found, why = settings_guard_entries(prof, WT_SCRIPT)
    if why:
        return why
    command = skills.guard_command(name, WT_SCRIPT)
    if found != [(WT_MATCHER, skills.canonical_hook(command))]:
        return "%s holds %d worktree guard entr%s %s, want exactly one, behind matcher %s: %s%s" % (
            slp, len(found), "y" if len(found) == 1 else "ies", found or "", WT_MATCHER, skills.canonical_hook(command),
            NOT_CANONICAL if [(m, h.get("command")) for m, h in found] == [(WT_MATCHER, command)] else "")
    return worktree_probe(command)


def worktree_guard_smoke(only=None):
    """One result per profile that turns the worktree guard on (a frozen one gets no settings),
    named `worktree guard <project>`, each saying how many it checked; a FAIL when none does. With
    `only`, that profile alone, and a PASS when it does not turn the guard on."""
    guarded = [(n, p) for n, p in sorted(lib.profiles().items()) if lib.worktree_guard_on(p) and not p.get("frozen")]
    rows = []
    for name, prof in guarded:
        if only in (None, name):
            why = worktree_guard_problem(name, prof)
            rows.append(lib.Result("FAIL", "worktree guard " + name, "%s (%d guarded)" % (why, len(guarded))) if why
                        else lib.Result("PASS", "worktree guard " + name, "one canonical entry; from a toy worktree a Write "
                                        "into its main checkout refused, one inside allowed (%d guarded)" % len(guarded)))
    rows += [lib.Result("FAIL", "worktree guard " + n, why) for n, why in guard_profile_errors("worktree_guard", only)]
    if rows:
        return rows
    if only:
        return lib.Result("PASS", "worktree guard", "%s does not turn it on, or is frozen" % only)
    # A profile that asks for the guard and is frozen is configured and checked by nothing: a FAIL. No
    # profile asking for it is a stranger's legitimate zero, a SKIP (docs/portable-design.md section 6).
    frozen = [n for n, p in sorted(lib.profiles().items()) if lib.worktree_guard_on(p) and p.get("frozen")]
    if frozen:
        return lib.Result("FAIL", "worktree guard", "checked 0 profiles: %s turn(s) it on but frozen, so forge wires "
                          "nothing for them, and a check that saw nothing is not a pass" % ", ".join(frozen))
    return lib.Result("SKIP", "worktree guard", NOT_ARMED + "no profile turns on worktree_guard")


# Ponytail for GSD's executing, debugging and reviewing agents (hooks/ponytail_subagent.py), which a
# profile wires in its own `hooks` block. For each profile that does: exactly one entry under each of
# SubagentStart and UserPromptSubmit (without the second a manual /ponytail never reaches the agents), and
# the SubagentStart command gives gsd-executor Ponytail's ruleset and gsd-planner nothing. The probe runs
# the real install, so a Ponytail update that moved its builder is a FAIL, not a silent no-op.
PONYTAIL_SCRIPT, PONYTAIL_TIMEOUT = "ponytail_subagent.py", 15
PONYTAIL_EVENTS = ("SubagentStart", "UserPromptSubmit")


def ponytail_entries(prof):
    """[(event, command)] of the profile's own hooks that run forge's hooks/ponytail_subagent.py."""
    return [(e, h["command"]) for e, groups in (prof.get("hooks") or {}).items() if skills._groups_ok(groups)
            for g in groups for h in g.get("hooks", []) if skills._runs_forge_guard(h.get("command"), PONYTAIL_SCRIPT)]


def ponytail_problem(prof, entries):
    """Why this profile's Ponytail hook would not scope Ponytail in a session, or None."""
    if prof.get("frozen"):
        return "the profile wires it but is frozen, so forge writes none of its hooks"
    if sorted(e for e, _ in entries) != list(PONYTAIL_EVENTS):
        return "the profile runs %s under %s, want once under each of %s" % (PONYTAIL_SCRIPT, [e for e, _ in entries], list(PONYTAIL_EVENTS))
    command = dict(entries)["SubagentStart"]
    for agent, wanted in (("gsd-executor", True), ("gsd-planner", False)):
        payload = json.dumps({"hook_event_name": "SubagentStart", "agent_type": agent})
        try:
            r = subprocess.run(command, shell=True, input=payload, text=True, capture_output=True, timeout=PONYTAIL_TIMEOUT)
        except subprocess.TimeoutExpired:
            return "%s got no answer in %d s" % (agent, PONYTAIL_TIMEOUT)
        try:
            got = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"].startswith("PONYTAIL MODE ACTIVE")
        except (ValueError, KeyError, TypeError, AttributeError):
            got = False
        if r.returncode != 0 or got != wanted or (not wanted and r.stdout.strip()):
            last = (r.stderr.strip().splitlines() or [""])[-1]
            return "%s %s (exit %d%s)" % (agent, "got no ruleset" if wanted else "got output", r.returncode,
                                          ": " + last if last else "")
    return None


def ponytail_row(only=None):
    """One result per profile that wires hooks/ponytail_subagent.py, named `ponytail <project>`, each
    saying how many are wired; a SKIP when none does. With `only`, that profile alone, and a PASS when it
    does not wire it."""
    wired = [(n, p, e) for n, p in sorted(lib.profiles().items()) for e in [ponytail_entries(p)] if e]
    rows = []
    for name, prof, entries in wired:
        if only in (None, name):
            why = ponytail_problem(prof, entries)
            rows.append(lib.Result("FAIL", "ponytail " + name, "%s (%d wired)" % (why, len(wired))) if why
                        else lib.Result("PASS", "ponytail " + name, "gsd-executor gets the ruleset, gsd-planner "
                                        "nothing (%d wired)" % len(wired)))
    if rows:
        return rows
    if only:
        return lib.Result("PASS", "ponytail", "%s does not wire hooks/%s" % (only, PONYTAIL_SCRIPT))
    return lib.Result("SKIP", "ponytail", NOT_ARMED + "no profile wires hooks/" + PONYTAIL_SCRIPT)


# What each integration needs that forge itself does not ship: a check returning the problem or None,
# and what a PASS says. Hindsight needs nothing from the machine here: its runtime
# has its own doctor row (doctor_extra) and the generator's `!` lines.
NOT_ARMED = lib.NOT_ARMED


def _codex_missing():
    return None if shutil.which("codex") else (
        "codex is on in config/forge.json but not on PATH -- install it or set integrations.codex false")


def _gsd_tool():
    """The tool GSD's install needs: npm for forge's patched copy (sync_gsd_runtime.py), pnpm for the
    unpatched one forge init installs with `pnpm dlx get-shit-done-cc`."""
    return "npm" if lib.gsd_patched() else "pnpm"


def _gsd_missing():
    tool = _gsd_tool()
    return None if shutil.which(tool) else (
        "gsd is on in config/forge.json but %s is not on PATH -- install %s or set integrations.gsd false"
        % (tool, "node" if tool == "npm" else "pnpm"))


INTEGRATION_NEEDS = {"codex": (_codex_missing, "codex found on PATH"), "gsd": (_gsd_missing, lambda: "%s found on PATH" % _gsd_tool()),
                     "hindsight": (None, "no dependency checked here")}


def hook_scripts(command):
    """The files a hook command names: every word after the first that is a path (has a `/` or ends in
    a script extension, and is not an option), plus the first word when it is itself a path. The
    interpreter (`python3`, `node`) is not one. A command that does not split (an open quote) names none."""
    try:
        words = shlex.split(command)
    except ValueError:
        return []
    found = [w for w in words[1:] if not w.startswith("-") and (os.sep in w or w.endswith((".py", ".js", ".mjs", ".sh")))]
    if words and os.sep in words[0]:
        found.insert(0, words[0])
    return [os.path.expanduser(w) for w in found]


def integrations_row():
    """The `integrations` row: one line per integration in config/forge.json (PASS, FAIL when it is on and
    what it needs is missing, SKIP when it is off), one per `user_hooks` row that names a script (FAIL when
    the file is not there: a UserPromptSubmit or PreToolUse command that cannot start exits 2 and refuses
    every prompt or tool call), and a closing line that counts what was checked. A row that checked
    nothing is a FAIL, never a pass (non-negotiable 7), unless nothing at all is configured (every
    integration off, no user_hooks row): a SKIP. The hook rows come through forge.hooks, so the
    command read is the one the generator writes: `<ROOT>` expanded, an `"on": false` row left out."""
    out, checked, unread = [], 0, False
    for name in lib.INTEGRATIONS:
        if not lib.on(name):
            out.append(lib.Result("SKIP", "integrations", "%s%s is off in config/forge.json" % (NOT_ARMED, name)))
            continue
        need, why = INTEGRATION_NEEDS[name]
        why = why() if callable(why) else why
        problem = need() if need else None
        checked += 1
        out.append(lib.Result("FAIL", "integrations", problem) if problem
                   else lib.Result("PASS", "integrations", "%s is on, %s" % (name, why)))
    integrations = checked
    try:
        from forge import hooks  # not at import: it reads config/forge.json
        scopes = []
        rows = hooks._config_rows(scopes)
    except (Exception, SystemExit) as e:
        out.append(lib.Result("FAIL", "integrations", "user_hooks not checked, forge.hooks could not read them: %s: %s"
                              % (type(e).__name__, e)))
        rows, scopes, unread = [], [], True
    for ((event, command, _, marker, _, _), on), scope in zip(rows, scopes):
        scripts = hook_scripts(command)
        if not scripts:
            continue
        if not on:
            out.append(lib.Result("SKIP", "integrations", '%suser_hooks row %s is "on": false in config/forge.json' % (NOT_ARMED, marker)))
            continue
        if scope and not lib.on(scope):  # written per project only while its integration is on (forge.hooks)
            out.append(lib.Result("SKIP", "integrations", "%suser_hooks row %s has scope %s, which is off in config/forge.json"
                                  % (NOT_ARMED, marker, scope)))
            continue
        for script in scripts:
            checked += 1
            if os.path.isfile(script):
                out.append(lib.Result("PASS", "integrations", "user_hooks row %s (%s): %s is there" % (marker, event, script)))
            else:
                out.append(lib.Result("FAIL", "integrations", 'user_hooks row %s (%s): %s does not exist, so the hook cannot start'
                                      ' -- restore it, or set "on": false on the row' % (marker, event, script)))
    if not checked and not rows and not unread:
        # Nothing is configured: every integration off and no user_hooks row at all. A stranger's legitimate zero.
        out.append(lib.Result("SKIP", "integrations", NOT_ARMED + "every integration is off in config/forge.json "
                              "and no user_hooks row is configured, so there is nothing to check"))
    elif not checked:
        out.append(lib.Result("FAIL", "integrations", "checked 0: every integration is off in config/forge.json and no "
                              "user_hooks row names a script, so this row proved nothing"))
    else:
        out.append(lib.Result("PASS", "integrations", "checked %d: %d integration(s) on, %d user_hooks script(s)"
                              % (checked, integrations, checked - integrations)))
    return out


def codex_hooks_row():
    """The `codex hooks` row, by config/forge.json's `codex_harness`. False (the default): Codex gets no hook
    from forge, so ~/.codex/hooks.json holding a command forge wrote (forge.hooks.codex_commands) is a FAIL.
    True: Codex is configured like Claude Code, so the file must hold every row forge writes there, and
    it is a FAIL while forge's own writer (hooks.reconcile, run on a copy) would still change anything, and
    the PASS says how many rows it checked. Either way a file it could not read is a FAIL, and so is an
    entry of the wrong shape where the check looks: with the switch false every entry, with it true only
    the events forge has a row for (reconcile repairs those, and leaves a foreign event's entries alone, as the
    writer does). Never a PASS over what was not looked at; SKIP while codex is off, as forge sync does not
    read the file then, and with the switch true while no row lists codex."""
    if not lib.on("codex"):
        return lib.Result("SKIP", "codex hooks", NOT_ARMED + "codex is off in config/forge.json")
    from forge import hooks  # not at import: it reads config/forge.json
    where = lib.short(hooks.CODEX_HOOKS)
    try:
        doc = lib.read_owned(hooks.CODEX_HOOKS, None)
    except lib.Unreadable as e:
        return lib.Result("FAIL", "codex hooks", "%s is unreadable, so what it holds was not checked: %s" % (where, e))
    if lib.codex_harness():
        n = sum(1 for row in hooks.USER_HOOKS if hooks.CODEX in row[5])
        pending = hooks.reconcile(copy.deepcopy(doc) if doc is not None else {}, hooks.CODEX)
        if pending:
            return lib.Result("FAIL", "codex hooks", "codex_harness is true and %s %s: %s"
                              % (where, "is not there" if doc is None else "is out of date", "; ".join(pending)))
        if not n:
            return lib.Result("SKIP", "codex hooks", NOT_ARMED + "codex_harness is true but no hook row lists codex")
        return lib.Result("PASS", "codex hooks", "codex_harness is true, and %s holds all %d row(s) forge writes there" % (where, n))
    if doc is None:
        return lib.Result("PASS", "codex hooks", "%s is not there, so forge left no hook in it" % where)
    entries, bad = lib.hook_entries(doc)
    if bad:
        return lib.Result("FAIL", "codex hooks", "%s has %d entr%s of the wrong shape, so what it holds was not checked"
                          % (where, bad, "y" if bad == 1 else "ies"))
    ours = hooks.codex_commands()
    found = ["%s %s" % (event, hook.get("command")) for event, _, _, hook in entries if hook.get("command") in ours]
    if found:
        return lib.Result("FAIL", "codex hooks", "%s still holds %d hook(s) forge wrote: %s" % (where, len(found), "; ".join(found)))
    return lib.Result("PASS", "codex hooks", "%d entr%s in %s, none is forge's" % (len(entries), "y" if len(entries) == 1 else "ies", where))


def _loaded(loaded, file, c):
    """The document owned.current wants for claim `c` of `file`, read into `loaded` the first time and reused:
    the parsed JSON for a key, item or hook claim, the text for an ignore line, None for a whole-file claim
    (current reads that one itself) and for a file that is not there (current says so). Raises lib.Unreadable."""
    if c["kind"] == "file":
        return None
    kind = "text" if owned.is_line(c) else "json"
    if kind not in loaded:
        loaded[kind] = owned.read_doc(file, c)
    return loaded[kind]


def owned_row():
    """The ownership record (forge/owned.py): what each writer last put into the files it writes or merges
    into. SKIP while no record exists (nothing has recorded yet), FAIL when it cannot be read or used.
    Otherwise every claim, of every kind, is compared with what its file holds now, read the way its writer
    wrote it (owned.current: a JSON path, a hook entry, an ignore line, a whole file or link): PASS says how
    many files and claims it looked at, WARN names each claim whose value changed or went since forge wrote
    it, and each file that is gone or cannot be read, as file and `at` only, never a value. A record with no
    claim (every writer's rows are gone) is a SKIP, not a PASS over nothing."""
    if not os.path.exists(owned.path()):
        return lib.Result("SKIP", "owned", NOT_ARMED + "no ownership record yet (%s): it is written by the first forge sync --apply"
                          % lib.short(owned.path()))
    claims, warn = owned.load()
    if warn:
        return lib.Result("FAIL", "owned", warn.strip().removeprefix("! "))
    looked, compared, changed, absent, unread = 0, 0, [], [], []
    for file, items in claims.items():
        if not os.path.lexists(file):
            absent.append(lib.short(file))
            continue
        loaded = {}  # the file read once for all its claims: its parsed JSON, and its text for the ignore lines
        try:
            same = [owned.unchanged(file, c, _loaded(loaded, file, c)) for c in items]
        except lib.Unreadable as e:
            unread.append("%s (%s)" % (lib.short(e.path), e.reason))
            continue
        looked += 1
        for c, ok in zip(items, same):
            compared += 1
            if not ok:
                changed.append("%s %s" % (lib.short(file), json.dumps(c["at"], ensure_ascii=False)))
    seen = "%d claim(s) in %d file(s)" % (compared, looked)
    if changed or unread or (absent and not looked):
        said = (["changed since forge wrote them, so a sync leaves or repairs them: " + "; ".join(changed)] if changed else []) + (
            ["could not read: " + "; ".join(unread)] if unread else []) + (
            ["every file it names is not there: " + ", ".join(absent)] if absent and not looked else [])
        return lib.Result("WARN", "owned", "%s; looked at %s" % (" | ".join(said), seen))
    if not claims or not compared:
        return lib.Result("SKIP", "owned", NOT_ARMED + "the ownership record holds no claim")
    return lib.Result("PASS", "owned", "%s%s" % (seen, " (%d file(s) not there: %s)" % (len(absent), ", ".join(absent)) if absent else ""))


def doctor_extra_row():
    """config/forge.json's `doctor_extra`: [name, argv, fix] rows, each a command run from ROOT that
    exits 0 when healthy, shown as a row of its own named `name` (the last line of its output, and the
    fix when it fails), exactly as a command row of CHECKS is. A row that is not that shape is a FAIL
    line, never skipped. None configured: no line."""
    out = []
    for i, row in enumerate(lib.settings().get("doctor_extra") or []):
        if not (isinstance(row, list) and len(row) == 3 and isinstance(row[0], str) and isinstance(row[2], str)
                and isinstance(row[1], list) and row[1] and all(isinstance(w, str) for w in row[1])):
            out.append(lib.Result("FAIL", "doctor_extra", "row %d is not [name, [argv...], fix] -- fix config/forge.json" % i))
            continue
        name, argv, fix = row
        r = lib.run(argv, capture=True)
        last = ((r.stdout or r.stderr).strip().splitlines() or [""])[-1].strip()
        out.append(lib.Result("PASS", name, last) if r.returncode == 0 else lib.Result("FAIL", name, "%s -- %s" % (last, fix)))
    return out


# (name, command, fix). A command exits 0 when healthy. A callable returns a lib.Result instead,
# which is how a check can be a WARN: a command's exit code is only ever PASS or FAIL
# (hindsight_doctor exits with its failure count, argparse with 2). The fix is appended to the
# detail of any result that is not a PASS.
CHECKS = [
    ("skill refs", ["scripts/sync/verify_skill_refs.py"], "fix the profile's skills_keep"),
    ("skill keep", ["scripts/sync/sync_skill_keep.py", "--check"], "python3 scripts/sync/sync_skill_keep.py --apply"),
    ("skill names", skill_name_clashes, "rename the project skill, or delete it if it was meant to be the global one"),
    ("frozen drift", frozen_drift, "forge writes nothing there, and Claude Code rewrites the file itself (approvals, permissions); lift `frozen` in the profile to bring it back to the generator's output"),
    ("instruction files", instruction_file_blocks, "forge never writes in a project: the change is in that project's repo"),
    ("command guard", command_guard_smoke, "forge sync --apply; if the entry is there, hooks/guard_tool_use.py itself does not refuse"),
    ("worktree guard", worktree_guard_smoke, "forge sync --apply; if the entry is there, hooks/worktree_guard.py itself does not refuse"),
    ("ponytail", ponytail_row, "the profile's hooks run hooks/ponytail_subagent.py once under SubagentStart and once under UserPromptSubmit; a probe that fails names Ponytail's install (claude plugin install ponytail@ponytail)"),
    ("memory", ["scripts/sync/memory_doctor.py"], "python3 scripts/sync/memory_doctor.py --verbose"),
    ("toolchain", toolchain.row, "forge toolchain --fix (writes mise's forge.toml, installs what is missing; a pip version that differs is only reported)"),
    ("owned", owned_row, "forge sync --apply rewrites the record from what forge writes (an entry changed by hand is left alone, or repaired when its row still exists)"),
    # Its failures carry their own fix, so the row's is empty.
    ("integrations", integrations_row, ""),
    ("codex hooks", codex_hooks_row, "forge sync --apply brings ~/.codex/hooks.json in line with codex_harness (forge's rows in with it true, out with it false); a file that does not parse is Codex's own to repair"),
    # config/forge.json's `doctor_extra` rows, each with the fix it names; the row's own fix is empty.
    ("doctor_extra", doctor_extra_row, ""),
]

# What `forge sync --project NAME` (a dry-run) prints for a file its --apply would change: one
# alternative per line, beside where it is printed and a sample of the text (grep the text: line
# numbers move). The generators' wording is an API, as for CHANGED below.
WOULD = re.compile(r"""
      \bwould\ (write|create|update|chmod|add)\b  # forge/skills.py "   would write overrides -> <slp> (...)";
                                  # forge/mcp.py "codex mcp -> <p> (0 servers) (would create)", "(would
                                  # update)", "(would chmod 600 config.toml)", "~/.claude.json -> would
                                  # write", "would chmod 600 ~/.claude.json (it carries ...)"; forge/lib.py
                                  # ensure_ignored "+gitignore(would add .codex/)"
    | \[dry-run\]$                # forge/skills.py mirror_for_codex "codex sees project skills -> <dst>
                                  #                (2 skill(s), +2)  [dry-run]"
""", re.X)
# sync_system_doc.py "  ~ <project>  copy:AGENT-SYSTEM.md, create:CLAUDE.md": its items, of which a
# SKIP-<why> one is a file it leaves alone, which no --apply changes.
DOC_CHANGES = re.compile(r"^\s*~ \S+\s+(.*)$")


def pending_writes(lines):
    """How many lines of a sync dry-run's output name a file its --apply would change."""
    n = 0
    for l in lines:
        m = DOC_CHANGES.match(l)
        n += bool(WOULD.search(l) or (m and any(not item.startswith("SKIP-") for item in m.group(1).split(", "))))
    return n


def generated_current(name, prof):
    """PASS when the dry-run of `forge sync --project NAME` exits 0 and would write nothing. Only
    counts are shown, never the generator's lines: `forge sync --project NAME` prints them."""
    if prof.get("frozen"):
        return lib.Result("PASS", "generated", "frozen: forge writes nothing")
    r = lib.run(["bin/forge", "sync", "--project", name], capture=True)
    lines = (r.stdout + r.stderr).splitlines()
    writes, bangs = pending_writes(lines), sum(1 for l in lines if lib.BANG.match(l))
    if not writes and not r.returncode:
        return lib.Result("PASS", "generated", "the dry-run of forge sync --project %s would write nothing" % name)
    problems = (["%d pending write(s)" % writes] if writes else []) + (
        ["the dry-run exits %d with %d '!' line(s), which forge sync --project %s shows" % (r.returncode, bangs, name)]
        if r.returncode else [])
    return lib.Result("FAIL", "generated", "; ".join(problems))


def project_checks(name, prof, why):
    """forge doctor NAME's rows, in CHECKS' shape, each scoped to project `name`. `prof` is its
    profile, or None when lib.profiles left it out for `why`: the profile row is then the only one,
    since every other row reads the profile."""
    where = "config/profiles/%s.claude.json" % name
    if prof is None:
        return [("profile", lambda: lib.Result("FAIL", "profile", "%s: %s" % (where, why)),
                 "fix the file by hand; until then every sync leaves the project out")]
    fix = {row: f for row, _, f in CHECKS}
    frozen = "; frozen: forge writes nothing for it" if prof.get("frozen") else ""
    rows = [
        ("profile", lambda: lib.Result("PASS", "profile", "%s reads, every field well-typed%s" % (where, frozen)), ""),
        ("generated", lambda: generated_current(name, prof), "forge sync --apply --project " + name),
        ("skill names", lambda: skill_name_clashes(name), fix["skill names"]),
        ("instruction files", lambda: instruction_file_blocks(name), fix["instruction files"]),
        ("command guard", lambda: command_guard_smoke(name), fix["command guard"]),
        ("worktree guard", lambda: worktree_guard_smoke(name), fix["worktree guard"]),
        ("ponytail", lambda: ponytail_row(name), fix["ponytail"]),
        ("memory", ["scripts/sync/memory_doctor.py", "--project", name],
         "python3 scripts/sync/memory_doctor.py --project %s --verbose" % name),
    ]
    if prof.get("frozen"):  # only a frozen project has a drift to report; the row follows skill names
        rows.insert(3, ("frozen drift", lambda: frozen_drift(name), fix["frozen drift"]))
    return rows


# A session start in the project config/forge.json's `session_wait` names waits for the local Hindsight
# (memory design, S3): the memory hook of a session that opens before the server answers
# is silently memory-less. Only with the hindsight integration on. The wait has to fit the SessionStart
# hook's 60 s timeout, so it is what is left of it after a 10 s margin and whatever the sync steps
# already took, never more than MEMORY_WAIT. Counting the elapsed time at run time replaces a p95
# estimate: the sync can wait up to 20 s on the lock.
MEMORY_HEALTH = None  # a test points it at a stand-in server; None reads session_wait["health"]
MEMORY_WAIT = 30
MEMORY_POLL = 2
HOOK_TIMEOUT, HOOK_MARGIN = lib.SESSION_START_TIMEOUT, 10


def session_wait():
    """config/forge.json's `session_wait` ({project, health, unit}), or None: the key absent, an
    integration off, or no project and health URL to wait for. Read when asked, never at import."""
    wait = lib.settings().get("session_wait")
    if not lib.on("hindsight") or not isinstance(wait, dict) or not wait.get("project") or not wait.get("health"):
        return None
    return wait


def memory_budget(elapsed):
    """Seconds this session start may still spend waiting for Hindsight, `elapsed` s into the hook."""
    return max(0, min(MEMORY_WAIT, HOOK_TIMEOUT - HOOK_MARGIN - elapsed))


def memory_up():
    import urllib.request  # only the waiting project health-checks; every session start would pay for it
    try:
        with urllib.request.urlopen(MEMORY_HEALTH or session_wait()["health"], timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def memory_unit():
    return (session_wait() or {}).get("unit") or "the memory unit"


def unit_state():
    """`systemctl --user is-active` of the Hindsight unit, or why it could not be asked."""
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", memory_unit()], text=True,
                           capture_output=True, timeout=3)
        return r.stdout.strip() or r.stderr.strip() or "unknown"
    except Exception as e:
        return "unknown (%s)" % type(e).__name__


def memory_note(started):
    """"" when Hindsight answers (waiting up to memory_budget for it), else the one plain line."""
    t = time.monotonic()
    limit = memory_budget(t - started)
    while not memory_up():
        if time.monotonic() - t >= limit:
            return ("memory is starting (%s: %s, waited %d s); this session has no automatic memory: "
                    "hindsight_recall works once the server is up, or open a new session"
                    % (memory_unit(), unit_state(), round(time.monotonic() - t)))
        time.sleep(MEMORY_POLL)
    return ""


def note_writes(log, cmd, step):
    """What the step just wrote, from its write log (lib.record): handed on to the log this process
    itself was given, if any, and to the journal. Returns the (what, path) pairs."""
    with open(log, encoding="utf-8", errors="replace") as fh:
        lines = [l.partition(" ")[::2] for l in fh.read().splitlines()]
    for what, p in lines:
        lib.record(what, p)
    lib.journal(lines, cmd, step)
    return lines


def cmd_sync(a):
    failed = []
    scope = (["--project", a.project] if a.project else []) + (["--all"] if a.all else [])
    log = None
    if a.apply:  # an apply notes each change it makes in the journal; a dry-run makes none
        fd, log = tempfile.mkstemp(prefix="forge-writes-")
        os.close(fd)
    try:
        with lib.lock() if a.apply else contextlib.nullcontext():
            for name, script, dry_flag, apply_flag, _ in SYNC:
                flag = apply_flag if a.apply else dry_flag
                if STEP_INTEGRATION.get(name) and not lib.on(STEP_INTEGRATION[name]):
                    print("== forge: %s == NOT RUN, NOT ARMED (%s off)" % (name, STEP_INTEGRATION[name]), flush=True)
                    print(flush=True)
                    continue
                print("== forge: %s ==" % name, flush=True)
                env = None
                if log:
                    open(log, "w").close()
                    env = dict(os.environ, FORGE_WRITE_LOG=log)
                if lib.run([script] + ([flag] if flag else []) + scope, env=env).returncode:
                    failed.append(name)
                if log:
                    note_writes(log, "sync", name)
                print(flush=True)
    finally:
        if log:
            with contextlib.suppress(OSError):
                os.remove(log)
    if failed:
        print("forge sync: failed -- %s" % ", ".join(failed))
    return 1 if failed else 0


def cmd_log(a):
    """forge log [--since YYYY-MM-DD] [NAME]: the change journal (lib.journal), oldest first, from DATE on,
    and with NAME only the changes under that project's project_path. Reads only."""
    if a.since is not None:
        # Strictly the zero-padded form: the filter compares the journal's text, so 2026-3-1 (which strptime
        # accepts) sorted after every line of March, and an empty value (falsy) was taken for "no --since".
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", a.since):
                raise ValueError(a.since)
            time.strptime(a.since, "%Y-%m-%d")
        except ValueError:
            print("! forge log: --since wants YYYY-MM-DD, got %r" % a.since)
            return 2
    roots = ()
    if a.project:
        skipped = []
        profs = lib.profiles(skipped)
        if a.project not in profs:
            why = {f[:-len(".claude.json")]: (f, w) for f, w in skipped}.get(a.project)
            if why:
                print("! forge log: profile %s cannot be read (%s)" % why)
            else:
                print("! forge log: unknown project: %s (known: %s)" % (a.project, ", ".join(sorted(profs))))
            return 1
        pp = profs[a.project].get("project_path")
        if not pp:
            print("! forge log: %s has no project_path, so no path is its own" % a.project)
            return 1
        roots = {pp.rstrip("/"), os.path.realpath(pp)}
    try:
        with open(lib.JOURNAL, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except FileNotFoundError:
        print("forge log: no journal yet (%s)" % lib.JOURNAL, file=sys.stderr)
        return 0
    for line in lines:
        if not line or (a.since is not None and line[:10] < a.since):
            continue
        path = line.split(" ", 4)[-1]
        if roots and not any(path == r or path.startswith(r + os.sep) for r in roots):
            continue
        print(line)
    return 0


# Lines a generator prints when something is wrong: a warning, a failure, or a write it refused.
# What it wrote is not guessed from its text any more: session start reads each step's write log
# (lib.record). One alternative per line, beside where it is printed and a sample of the text
# (grep the text: line numbers move). What the generators print is an API the refactor keeps byte
# for byte (docs/unify-split-design.md §2).
CHANGED = re.compile(r"""
      ^\s*!                       # a warning or failure: lib.read_json and forge/{sync,mcp,memory,
                                  # skills,hooks}.py; sync_gsd_runtime.py; sync_system_doc.py, whose
                                  # one ERROR line is "  ! <project> ERROR: <why> -- skipped..."
    | ^GSD\ \S+\ is\ published    # sync_gsd_runtime.py npm_nag    "GSD <v> is published (installed <v>).
                                  #                                Update: ...", once a day, exit 0
    | SKIP-                       # sync_system_doc.py             "  ~ <project>  SKIP-agents-md(non-forge
                                  #                                content):AGENTS.md", a file left alone
    | relink_skills:.*(BLOCKED|SKIPPED|failed)  # relink_skills.py "| BLOCKED(real dir in mirror): <link>",
                                  #                                "memory unlink failed: <why>" (exit 0, no
                                  #                                '!'); its FAILED summary starts with '!'
    # lib.may_write refusing (printed by lib.apply_allowed): from master that
    # means a settings.json nobody can parse, and a session start that silently writes nothing
    # would read as up to date.
    | ^forge:\ .*nothing\ written
""", re.X)

# Shown one note per step, never one line per path: the first few and a count.
SHOWN = 3
VERBS = {"wrote": "wrote %d file(s)", "link": "linked %d", "unlink": "unlinked %d", "chmod": "chmod %d",
         "mkdir": "created %d dir(s)", "rmtree": "removed %d tree(s)"}
# forge's own caches: logged, never shown. The gsd step's once-a-day npm check rewrites a stamp
# under it, and a note every day for that would be the noise npm_nag exists to avoid; a restage
# there coincides with the agent and engine writes, which are shown.
CACHE = os.path.join(lib.HOME, ".cache", "forge") + os.sep


def written(lines):
    """The note for what one step recorded (lib.record's lines), or "" when it wrote nothing:
    per kind of change, in the order first seen, each path once."""
    kinds = {}
    for what, p in lines:
        if p and not p.startswith(CACHE):
            kinds.setdefault(what, dict())[p] = None
    return "; ".join("%s: %s%s" % (VERBS.get(what, what + " %d") % len(ps), ", ".join(lib.short(p) for p in list(ps)[:SHOWN]),
                                   " +%d more" % (len(ps) - SHOWN) if len(ps) > SHOWN else "")
                     for what, ps in kinds.items())


def cmd_session_start(a):
    """Bring this session's own project up to date, and in forge the user-scope files too
    (lib.context scopes each generator by CLAUDE_PROJECT_DIR). It says only what changed or
    failed, as a systemMessage the user sees and the model's context never gets, and it always
    exits 0: a broken sync must never block a session. What a step wrote comes from the write log
    it is handed (FORGE_WRITE_LOG, lib.record), and goes on into this process's own log when it
    has one, so a caller of session start sees every path too."""
    started = time.monotonic()
    notes, seen, log = [], set(), None
    session = None
    try:
        session = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        skipped = []
        profs = lib.profiles(skipped)  # a profile nobody can read: this session may be its project
        notes += ["! config/profiles/%s unreadable (%s) -- left out of every sync" % s for s in skipped]
        name = lib.resolve_project(session)
        if name and not profs[name].get("frozen"):
            fd, log = tempfile.mkstemp(prefix="forge-writes-")
            os.close(fd)
            # The steps scope themselves by CLAUDE_PROJECT_DIR alone (lib.context), so they get the
            # directory resolved here: from the cwd, without it, each one ran over every project.
            env = dict(os.environ, CLAUDE_PROJECT_DIR=session, FORGE_WRITE_LOG=log)
            scope = lib.session_scope(name)  # what lib.context gives each step from CLAUDE_PROJECT_DIR
            with lib.lock(timeout=20):
                for step, script, _, apply_flag, user_scope_only in SYNC:
                    if user_scope_only and not scope.globals:
                        continue
                    if STEP_INTEGRATION.get(step) and not lib.on(STEP_INTEGRATION[step]):
                        continue  # said by forge sync; a session start says only what changed or failed
                    open(log, "w").close()
                    r = lib.run([script, apply_flag] if apply_flag else [script], capture=True, env=env)
                    lines = note_writes(log, "session-start", step)
                    note = written(lines)
                    if note:
                        notes.append("%s: %s" % (step, note))
                    new = [l.strip() for l in (r.stdout + r.stderr).splitlines()
                           if CHANGED.search(l) and l.strip() not in seen]  # a refusal, once, not per step
                    seen.update(new)
                    notes += ["%s: %s" % (step, l) for l in new]
                    if r.returncode:
                        notes.append("%s: exit %d -- run `forge sync` in forge to see why" % (step, r.returncode))
    except (Exception, SystemExit) as e:  # lib.settings() exits on a missing config/forge.json
        notes.append("session-start: %s: %s" % (type(e).__name__, e))
    finally:
        if log:
            with contextlib.suppress(OSError):
                os.remove(log)
    try:
        wait = session_wait()
        if wait and session and lib.resolve_project(session) == wait["project"]:
            note = memory_note(started)
            if note:
                notes.append(note)
    except (Exception, SystemExit) as e:
        notes.append("session-start: memory wait: %s: %s" % (type(e).__name__, e))
    if notes:
        print(json.dumps({"systemMessage": "forge -- " + " | ".join(notes)}))
    return 0


def cmd_doctor(a):
    rows, project = CHECKS, getattr(a, "project", None)
    if project is not None:
        skipped = []
        known = lib.profiles(skipped)
        unreadable = {f[:-len(".claude.json")]: why for f, why in skipped}
        if project not in known and project not in unreadable:
            print("! forge doctor: unknown project: %s (known: %s)" % (project, ", ".join(sorted(known))))
            return 1
        rows = project_checks(project, known.get(project), unreadable.get(project))
    results = []
    for name, cmd, fix in rows:
        if callable(cmd):
            try:
                res = cmd()
            except Exception as e:  # a check that cannot run is a failure, and must not hide the rest
                res = lib.Result("FAIL", name, "%s: %s" % (type(e).__name__, e))
            # A callable gives one result, or a list of them (one line per guarded profile).
            results += [r if r.level == "PASS" or not fix or r.detail.startswith(NOT_ARMED)
                        else r._replace(detail="%s -- %s" % (r.detail, fix))
                        for r in (res if isinstance(res, list) else [res])]
            continue
        r = lib.run(cmd, capture=True)
        last = ((r.stdout or r.stderr).strip().splitlines() or [""])[-1].strip()
        results.append(lib.Result("PASS", name, last) if r.returncode == 0
                       else lib.Result("FAIL", name, "%s -- %s" % (last, fix)))
    return lib.report(results)


# Suites `forge test` does not run unless asked (`forge test --mutants`), each with why: the file, relative
# to ROOT, and the reason. hooks/test_guard_mutants.py runs 326 mutants on max(2, cpu_count) workers, each a
# test_guard_tool_use.py of about six cores: it once took a voice detector from 0.3 s to 50+ s.
ON_DEMAND = {"hooks/test_guard_mutants.py": "326 mutants on every core, minutes of full CPU; it stalls the machine"}


def cmd_test(a):
    # A git that fails (not a repository, not installed) or a list with no tests is a FAIL: until
    # an attack round either ran zero tests and printed "0 failures" with exit 0.
    # Two histories own the files once the engine and the private data are split (forge/publish.py): the
    # engine's, and .forge-data.git over the same work tree. Before the split only the first exists, and
    # the second is no failure, just absent.
    from forge import publish
    histories = [("git ls-files", ["git"])]
    if os.path.isdir(os.path.join(lib.ROOT, publish.DATA_GIT)):
        histories.append(("git ls-files (data history)",
                          ["git", "--git-dir", os.path.join(lib.ROOT, publish.DATA_GIT), "--work-tree", lib.ROOT]))
    listed = set()
    for label, git in histories:
        try:
            r = lib.run_low(git + ["ls-files", "-z", "*test_*.py"], cwd=lib.ROOT, text=True, capture_output=True)
        except OSError as e:
            return lib.report([lib.Result("FAIL", label, "git could not run: %s" % e)])
        if r.returncode:
            return lib.report([lib.Result("FAIL", label, "exit %d: %s" % (
                r.returncode, r.stderr.strip() or "(no stderr)"))])
        listed.update(r.stdout.split("\0"))
    # The pathspec's leading * also matches a prefix (contest_helper.py), so the basename is checked here.
    files = sorted(f for f in listed if not f.startswith("benchmarks/")
                   and os.path.basename(f).startswith("test_") and f.endswith(".py"))
    if not files:
        return lib.report([lib.Result("FAIL", "git ls-files", "no tests found in %s" % lib.ROOT)])
    mutants = getattr(a, "mutants", False)
    results = []
    for f in files:
        if f in ON_DEMAND:
            if not mutants:  # said, never a PASS, and not counted in the summary (non-negotiable 7)
                results.append(lib.Result("SKIP", os.path.basename(f), "NOT RUN, on demand (%s): run `forge test --mutants`"
                                          % ON_DEMAND[f]))
                continue
        elif mutants:
            continue
        r = lib.run([f], capture=True, low=True)  # nice 19 and idle I/O: a foreground tool keeps its cores
        if r.returncode == lib.NOT_RUN:
            # A test that lacks a tool or the network says so and exits 77: yellow, never a pass
            # (docs/unify-plan.md, non-negotiable 7). Its last line is why, after "NOT RUN: ".
            why = (r.stdout.strip().splitlines() or [f])[-1].removeprefix("NOT RUN: ")
            results.append(lib.Result("WARN", os.path.basename(f), "NOT RUN, NOT ARMED: %s" % why))
            continue
        results.append(lib.Result("PASS", os.path.basename(f), f) if r.returncode == 0 else
                       lib.Result("FAIL", os.path.basename(f), "python3 %s" % f))
    return lib.report(results)


def transcript_key(project_path):
    """The folder under ~/.claude/projects where Claude Code keeps a project's transcripts: every
    character that is not an ASCII letter or digit becomes `-`, which is Claude Code's own
    `replace(/[^a-zA-Z0-9]/g, "-")` (read from its 2.1.294 binary), one dash per UTF-16
    unit. The real folders agree: `.cache` is `-cache` after the slash's dash, "2 - Sources" is
    `2---Sources`, and no folder yet has an underscore, which that rule makes a dash too. One project's
    harness-baseline.mjs changed only `/`, and read a folder that does not exist for any path with a
    dot or a space. A path over 200 characters gets a hash suffix there, which this does not
    reproduce: its folder is not found, which cmd_metrics says by name."""
    return "".join(c if c.isascii() and c.isalnum() else "-" * (2 if ord(c) > 0xFFFF else 1) for c in project_path)


METRICS = {"metrics": "harness-metrics.mjs", "baseline": "harness-baseline.mjs"}


def cmd_metrics(a):
    """forge metrics NAME: node scripts/metrics/<script> over NAME's transcripts and repository.
    Reads only. A profile with no project_path, a transcript folder that does not exist, or no node
    is a FAIL naming the project: the scripts would otherwise fail on a key nobody can see."""
    profs = lib.profiles()
    if a.project not in profs:
        print("! forge metrics: unknown project: %s (known: %s)" % (a.project, ", ".join(sorted(profs))))
        return 1
    path = profs[a.project].get("project_path")
    projects = os.path.join(lib.HOME, ".claude", "projects")

    def fail(why):
        return lib.report([lib.Result("FAIL", "metrics", "%s: %s" % (a.project, why))])
    if not path:
        return fail("the profile has no project_path")
    key = transcript_key(path)
    if not os.path.isdir(os.path.join(projects, key)):
        return fail("no transcript folder %s (project_path %s)" % (os.path.join(projects, key), path))
    node = shutil.which("node")
    if not node:
        return fail("node is not on PATH")
    if a.baseline:
        if a.since or a.until or a.events_until:
            return fail("--since, --until and --events-until do not apply to --baseline")
        extra = [a.session] if a.session else []
    else:
        if a.session:
            return fail("a session id needs --baseline")
        extra = ["--projects-dir=" + projects] + ["--%s=%s" % (k.replace("_", "-"), v) for k, v in (
            ("since", a.since), ("until", a.until), ("events_until", a.events_until)) if v]
    r = subprocess.run([node, os.path.join(lib.ROOT, "scripts", "metrics", METRICS["baseline" if a.baseline else "metrics"]),
                        "--repo=" + path, "--transcript-key=" + key] + extra + (["--json"] if a.json else []),
                       env=dict(os.environ, HOME=lib.HOME), text=True, capture_output=True)
    print(r.stdout, end="")
    print(r.stderr, end="", file=sys.stderr)
    return r.returncode


# --- forge init and forge add (docs/portable-design.md section 6): what a new checkout and a new project
# need before the generators have anything to read. Both only create: a file that is already there is kept.
EXAMPLES = os.path.join(lib.ROOT, "examples")
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# What init asks about, and what it asks. The others are switched on by hand with --with.
QUESTIONS = {"codex": "Codex found: manage its config too? [Y/n]",
             "gsd": "pnpm found: install GSD (planning skills, unpatched from its package with pnpm dlx get-shit-done-cc)? [Y/n]"}
# GSD's own installer, run by init through pnpm: the package's README names npx
# get-shit-done-cc [options] and bin/install.js's --help lists `--claude` (Claude Code only) and `-g, --global`
# (the config directory); with a runtime and a location given it asks nothing.
GSD_INSTALL = ["pnpm", "dlx", "get-shit-done-cc@latest", "--claude", "--global"]
# Local, never shared: the data history must not take a secret or a file the generators rewrite.
DATA_EXCLUDE = ("credentials/", "config/secrets.json", "config/secrets.*.json", ".claude/settings.local.json", ".claude/AGENT-SYSTEM.md", ".codex/", ".mcp.json", "*.bak")


def names_list(text):
    return [n for n in text.split(",") if n]


def ask_yes(question):
    """The answer to a [Y/n] question: yes unless it starts with n. No input at all is the default."""
    try:
        reply = input(question + " ")
    except EOFError:
        reply = ""
    return not reply.strip().lower().startswith("n")


def init_choices(yes, with_names, without_names, have, ask):
    """({integration: bool} for every name in lib.INTEGRATIONS, None), or (None, why not). Codex and GSD
    default to on when `have` says codex and pnpm were found, and each is asked about (`ask`, True for yes)
    unless --yes, --with or --without already decided it; --with switches on any other offered integration,
    but not what the machine lacks: codex needs codex and gsd needs pnpm on PATH. Pure: no I/O but `ask`."""
    for n in with_names + without_names:
        if n not in lib.INTEGRATIONS:
            return None, "unknown integration %r (one of %s)" % (n, ", ".join(lib.INTEGRATIONS))
    both = sorted(set(with_names) & set(without_names))
    if both:
        return None, "%s is in both --with and --without" % ", ".join(both)
    found = {"codex": have["codex"], "gsd": have["pnpm"]}
    needs = {"codex": "codex", "gsd": "pnpm"}
    for n in with_names:
        if n in found and not found[n]:
            return None, "--with %s needs %s on PATH, and it is not" % (n, needs[n])
    out = {n: n in with_names for n in lib.INTEGRATIONS}
    for n in found:
        if n not in with_names and n not in without_names and found[n]:
            out[n] = True if yes else bool(ask(QUESTIONS[n]))
    return out, None


def init_preflight():
    """Prints one line per tool (python and git must be there, claude is a WARN, pnpm and codex are
    optional) and returns ({"codex": bool, "pnpm": bool}, whether a required tool is missing)."""
    py = sys.version_info
    new_enough = py >= (3, 10)
    rows = [("PASS" if new_enough else "FAIL", "python", "%d.%d.%d%s" % (py[0], py[1], py[2], "" if new_enough else ", 3.10 or newer is needed")),
            ("PASS" if shutil.which("git") else "FAIL", "git", shutil.which("git") or "not on PATH: forge needs it"),
            ("PASS" if shutil.which("claude") else "WARN", "claude", shutil.which("claude") or "not on PATH: install Claude Code to use what forge writes"),
            ("PASS" if shutil.which("pnpm") else "SKIP", "pnpm", shutil.which("pnpm") or "not on PATH: GSD stays off"),
            ("PASS" if shutil.which("codex") else "SKIP", "codex", shutil.which("codex") or "not on PATH: Codex's config stays off")]
    for level, name, detail in rows:
        print("%-4s  %-8s %s" % (level, name, detail))
    return {"codex": bool(shutil.which("codex")), "pnpm": bool(shutil.which("pnpm"))}, any(r[0] == "FAIL" for r in rows)


def example_text(name):
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as fh:
        return fh.read()


def init_write(integrations, track):
    """Writes the checkout's own data, each path printed. config/forge.json is the one that is always
    written (it is what says this checkout is initialised); every other file is kept when it exists, so
    a checkout that already holds data never has any of it replaced."""
    def rel(p):
        return os.path.relpath(p, lib.ROOT)

    def put(path, text, mode=None):
        if os.path.lexists(path):
            print("kept   %s" % rel(path))
            return
        lib.write_text(path, text, mode=mode)
        print("wrote  %s" % rel(path))
    forge_json = json.loads(example_text("forge.json"))
    forge_json["integrations"].update(integrations)
    lib.write_text(lib.SETTINGS, lib.dumps(forge_json) + "\n")
    print("wrote  %s" % rel(lib.SETTINGS))
    profile = json.loads(example_text("profile.claude.json"))
    profile.update(project="forge", project_path=lib.ROOT, writes_tracked_files=False)
    put(os.path.join(lib.PROFILES, "forge.claude.json"), lib.dumps(profile) + "\n")
    put(os.path.join(lib.ROOT, "config", "mcp-registry.json"), example_text("mcp-registry.json"))
    secrets = os.path.join(lib.ROOT, "credentials", "secrets.json")
    os.makedirs(os.path.dirname(secrets), mode=0o700, exist_ok=True)
    put(secrets, "{}\n", mode=0o600)
    link = os.path.join(lib.ROOT, "config", "secrets.json")
    if os.path.lexists(link):
        print("kept   %s" % rel(link))
    else:
        lib.symlink(os.path.join("..", "credentials", "secrets.json"), link)
        print("linked %s" % rel(link))
    put(os.path.join(lib.ROOT, "docs", "AGENT-SYSTEM.md"), example_text("AGENT-SYSTEM.md"))
    skills_dir = os.path.join(lib.ROOT, "skills")
    if not os.path.isdir(skills_dir):
        lib.makedirs(skills_dir)
        print("made   %s/" % rel(skills_dir))
    if lib.in_git_repo(lib.ROOT):
        # The personal-data guard of githooks/ then protects a fork of this checkout as well.
        r = subprocess.run(["git", "-C", lib.ROOT, "config", "core.hooksPath", "githooks"], capture_output=True, text=True)
        print("set    git config core.hooksPath githooks" if r.returncode == 0 else "!      git config core.hooksPath failed: %s" % r.stderr.strip())
    else:
        print("note   %s is not a git repository, so core.hooksPath is not set" % lib.ROOT)
    if track:
        data = os.path.join(lib.ROOT, ".forge-data.git")
        if os.path.exists(data):
            print("kept   .forge-data.git")
        else:
            subprocess.run(["git", "init", "-q", "--bare", data], check=True)
            subprocess.run(["git", "--git-dir", data, "config", "core.bare", "false"], check=True)
            lib.write_text(os.path.join(data, "info", "exclude"), "\n".join(DATA_EXCLUDE) + "\n")
            print("made   .forge-data.git (your data's own history, no remote; forge commit puts each path in the history that owns it)")


def init_step(label, argv, tool=False):
    """Runs one init step and returns its exit code: a forge script by default, an external command
    (argv as given, from the checkout) with tool=True."""
    print("== forge init: %s ==" % label, flush=True)
    code = (subprocess.run(argv, cwd=lib.ROOT) if tool else lib.run(argv)).returncode
    print(flush=True)
    return code


def cmd_init(a):
    have, broken = init_preflight()
    if broken:
        print("! forge init: a required tool is missing -- nothing written")
        return 1
    if os.path.exists(lib.SETTINGS):
        print("! forge init: already initialised -- run forge doctor")
        return 1
    ok, why = lib.may_write()
    if not ok:
        print(why)
        return 1
    integrations, why = init_choices(a.yes, a.with_names, a.without_names, have, ask_yes)
    if integrations is None:
        print("! forge init: %s" % why)
        return 1
    init_write(integrations, a.track)
    # A step that ran and broke exits non-zero and lands here with its code. What could not run (a tool that
    # is not there, an integration that is off) never gets this far: init_choices leaves GSD off without pnpm,
    # and the generators and the doctor print NOT RUN, NOT ARMED / SKIP and exit 0.
    failed = []
    if integrations["gsd"]:
        # The example's gsd_patches is false: GSD straight from its package, nothing staged, patched or pinned.
        code = init_step("gsd", GSD_INSTALL, tool=True)
        if code:
            failed.append(("gsd", code))
    code = init_step("sync", ["bin/forge", "sync", "--apply", "--all"])
    if code:
        failed.append(("sync", code))
    code = init_step("doctor", ["bin/forge", "doctor"])
    if code:
        failed.append(("doctor", code))
    if failed:
        print("! forge init: failed -- %s" % ", ".join("%s (exit %d)" % f for f in failed))
    print("put your own skills in %s/skills/<name>/SKILL.md (git ignores them; forge init --track versions them), "
          "then run forge sync --apply" % lib.ROOT)
    print("next: forge add <path>")
    return 1 if failed else 0


def cmd_add(a):
    if not os.path.exists(lib.SETTINGS):
        print("! forge add: config/forge.json missing -- run bin/forge init")
        return 1
    path = os.path.realpath(os.path.expanduser(a.path))
    if not os.path.isdir(path):
        print("! forge add: %s is not a directory" % a.path)
        return 1
    name = a.name or os.path.basename(path)
    if not KEBAB.match(name):
        print("! forge add: %r is not a kebab-case name (lowercase letters and digits, single dashes between them) "
              "-- pass --name" % name)
        return 1
    target = os.path.join(lib.PROFILES, name + ".claude.json")
    if os.path.lexists(target):
        print("! forge add: %s is already registered (config/profiles/%s.claude.json)" % (name, name))
        return 1
    ok, why = lib.may_write()
    if not ok:
        print(why)
        return 1
    profile = json.loads(example_text("profile.claude.json"))
    profile.update(project=name, project_path=path, writes_tracked_files=bool(a.writes_tracked_files))
    lib.write_text(target, lib.dumps(profile) + "\n")
    print("wrote  %s" % os.path.relpath(target, lib.ROOT), flush=True)
    return lib.run(["bin/forge", "sync", "--apply", "--project", name]).returncode


def _publish():
    """forge.publish, imported when one of its two commands runs: a defect in it cannot break sync,
    doctor or session-start."""
    from forge import publish
    return publish


def _uninstall():
    """forge.uninstall, imported only when it runs, like _publish."""
    from forge import uninstall
    return uninstall


def main(argv=None):
    p = argparse.ArgumentParser(prog="forge", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="regenerate every project's config")
    s.add_argument("--apply", action="store_true", help="write; without it, only show what would change")
    scope = s.add_mutually_exclusive_group()
    scope.add_argument("--project", help="this project only, no user-scope files")
    scope.add_argument("--all", action="store_true", help="every project, even inside a session")
    s.set_defaults(fn=cmd_sync)
    d = sub.add_parser("doctor", help="what is broken")
    d.add_argument("project", nargs="?", help="this project only: each check scoped to it")
    d.set_defaults(fn=cmd_doctor)
    m = sub.add_parser("metrics", help="a project's harness metrics, read from its Claude Code transcripts")
    m.add_argument("project", help="a profile name; its project_path is the repository and gives the transcript folder")
    m.add_argument("session", nargs="?", help="with --baseline: a session id (default: the newest)")
    m.add_argument("--baseline", action="store_true", help="what one session loads before the first user message")
    m.add_argument("--since", help="YYYY-MM-DD, sessions from this day")
    m.add_argument("--until", help="YYYY-MM-DD, sessions up to this day")
    m.add_argument("--events-until", help="ISO instant: drop every transcript line stamped after it")
    m.add_argument("--json", action="store_true")
    m.set_defaults(fn=cmd_metrics)
    t = sub.add_parser("test", help="run every test except the on-demand suites")
    t.add_argument("--mutants", action="store_true", help="run only the on-demand suites (the guard's mutant check)")
    t.set_defaults(fn=cmd_test)
    t = sub.add_parser("toolchain", help="the third-party tools config/toolchain.json pins, installed by mise")
    t.add_argument("--fix", action="store_true", help="install the missing ones at their pinned version; never upgrades what is present")
    t.set_defaults(fn=toolchain.cmd)
    g = sub.add_parser("log", help="the change journal: what forge sync --apply and session start wrote")
    g.add_argument("project", nargs="?", help="this project's paths only")
    g.add_argument("--since", help="YYYY-MM-DD, changes from this day")
    g.set_defaults(fn=cmd_log)
    sub.add_parser("session-start", help="the SessionStart hook").set_defaults(fn=cmd_session_start)
    c = sub.add_parser("check-public", help="scan for personal data that must not be published")
    mode = c.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="the staged files (pre-commit)")
    mode.add_argument("--all", action="store_true", help="every engine file (CI, the gate)")
    mode.add_argument("--range", help="the commits in A..B, messages and content (pre-push)")
    mode.add_argument("--message", help="a commit message file (commit-msg)")
    c.set_defaults(fn=lambda a: _publish().cmd_check_public(a))
    c = sub.add_parser("commit", help="commit each changed path to the history that owns it")
    c.add_argument("-m", "--message", required=True)
    c.add_argument("paths", nargs="*", help="only these paths")
    c.add_argument("--all", action="store_true", help="every change, when no path is named")
    c.set_defaults(fn=lambda a: _publish().cmd_commit(a))
    i = sub.add_parser("init", help="first run for a new checkout: its data, sync --apply --all, doctor")
    i.add_argument("--yes", action="store_true", help="take what init found (Codex, pnpm) without asking")
    i.add_argument("--with", dest="with_names", type=names_list, default=[], metavar="a,b", help="switch these integrations on")
    i.add_argument("--without", dest="without_names", type=names_list, default=[], metavar="a,b", help="leave these integrations off")
    i.add_argument("--track", action="store_true", help="also make .forge-data.git, a local history of your data")
    i.set_defaults(fn=cmd_init)
    i = sub.add_parser("add", help="register a project: its profile, then sync --apply --project")
    i.add_argument("path", help="the project's directory")
    i.add_argument("--name", help="the profile's name (kebab-case; default: the directory's name)")
    i.add_argument("--writes-tracked-files", action="store_true", help="let forge write files that are tracked in the project")
    i.set_defaults(fn=cmd_add)
    u = sub.add_parser("uninstall", help="take out what forge wrote; a dry-run unless --apply")
    u.add_argument("--apply", action="store_true", help="remove; without it, only show what would go")
    scope = u.add_mutually_exclusive_group()
    scope.add_argument("--integration", choices=lib.INTEGRATIONS, help="only this integration's, once it is off in config/forge.json")
    scope.add_argument("--project", help="only this project's, once its profile is frozen or deleted")
    u.set_defaults(fn=lambda a: _uninstall().main(a))
    a = p.parse_args(argv)
    return a.fn(a)
