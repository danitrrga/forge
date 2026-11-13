"""forge -- one command for the agent-config platform.

  forge init             first run for a new checkout: config/forge.json, a profile for the checkout itself,
                         an empty registry and secrets file, then sync --apply --all and doctor
  forge new PATH         register a project: config/profiles/NAME.claude.json, then sync --apply NAME
  forge sync [NAME | --all] [--apply]  regenerate every project's config (or NAME's), in a fixed order, one run at a time
  forge skills [--apply] the skill links (~/.claude/skills) and the GSD runtime, which belong to the machine, not to a project
  forge doctor [NAME]    one line per check: what is broken, and the command that fixes it;
                         with a project's name, only the checks that concern it, scoped to it
  forge test             run every test_*.py in the repo
  forge toolchain [--fix]  the third-party tools in config/toolchain.json, installed by mise at their pin
                         (and the two files forge writes for mise); --fix writes the files and installs what is missing
  forge start NAME [ARGS...]  claude started with the environment the launcher NAME of config/forge.json declares
  forge lock [--apply]   config/forge.lock.json: the plugin, outside-skill, GSD and MCP package versions this machine runs
  forge versions [--md]  those and the mise pins of config/toolchain.json, for release notes
  forge metrics NAME     a project's harness metrics from its Claude Code transcripts (--baseline: one session)
  forge session-start    the SessionStart hook: this session's project only, then a note if the GSD runtime or the toolchain is off;
                         silent unless it wrote or has one
  forge lint             [--root DIR] --staged | --all | --range A..B | --message FILE: personal data that must not be published
  forge commit -m MSG (PATH... | --all)  each changed path to the history that owns it (forge/publish.py)
  forge uninstall [NAME | --integration N] [--apply]  take out what forge wrote (forge/uninstall.py)

Every step is still the script it was (scripts/sync/*.py and the doctors); this is the one place
that says which runs, in what order, and what "healthy" means.
"""
import argparse
import contextlib
import copy
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

from forge import launch, lib, lockfile, mcp, owned, skills, toolchain, usage

# The order is the contract: the system doc comes last. (name, script, its dry-run flag, its apply flag,
# extra arguments.) A session start runs these for its own project and nothing else; what it says about
# the machine (the GSD runtime, the toolchain) is check_and_tell.
SYNC = [
    ("agent config", "scripts/sync/sync_agent_config.py", None, "--apply", []),
    ("system doc", "scripts/sync/sync_system_doc.py", None, "--apply", []),
]
# forge skills: the user-scope steps, run on their own (docs/toolchain-design.md section 5). The skill links come
# last: they link what the two steps before them wrote, and the first apply of a newly shipped skill linked none of
# it while the links ran first.
SKILLS = [
    ("online skills", "scripts/sync/materialise_skills.py", None, "--apply", []),
    ("gsd runtime", "scripts/sync/sync_gsd_runtime.py", None, "--apply", ["--skills"]),
    ("skill links", "scripts/sync/relink_skills.py", "--dry-run", None, []),
]
# The integration (lib.INTEGRATIONS) a step belongs to, by name: with it off, the command says so and
# does not run the step (docs/portable-design.md section 5).
STEP_INTEGRATION = {"gsd runtime": "gsd"}


def skill_name_clashes(only=None):
    """A WARN when a project skill (<project_path>/.claude/skills/<name>) is named like a global
    skill, else a PASS saying how many project skills in how many projects it read. The global names
    are forge's skills/ plus ~/.claude/skills, because some global skills live only there (omarchy and
    diagnose-crash link into /usr/share/omarchy). Frozen profiles are skipped (docs/archive/orchestration-history.md,
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


def nested_project_roots(only=None, profs=None):
    """A FAIL when a project with skills of its own lives inside the git repository of another profile. forge switches the
    enclosing project's neighbours' skills off (skills.neighbour_skills), Claude Code applies those settings inside the nested
    directory too, and an inner "on" does not override an outer "off" (tested with claude -p), so the nested
    project's own skills never appear. The standard is one git repository per project. A nested project without skills of its
    own, one with its own repository, and one nested in a repository no profile owns are fine. Frozen profiles and profiles with
    no directory are not read, and a run that read no project at all is a FAIL (non-negotiable 7). With `only`, that project
    alone."""
    profs = lib.profiles() if profs is None else profs
    bad, read, unread = [], 0, []
    for name, prof in sorted(profs.items()):
        if only not in (None, name) or prof.get("frozen"):
            continue
        pp = prof.get("project_path")
        if not pp or not os.path.isdir(pp):
            unread.append(name)
            continue
        read += 1
        here = os.path.realpath(pp)
        root = skills._repo_root(here)
        if root is None or root == here:
            continue
        outer = [n for n, o in profs.items() if n != name and o.get("project_path") and os.path.isdir(o["project_path"])
                 and here.startswith(os.path.realpath(o["project_path"]) + os.sep)
                 and skills._repo_root(os.path.realpath(o["project_path"])) == root]
        own = skills.skill_dirs(os.path.join(pp, ".claude", "skills"))
        if outer and own:
            bad.append("%s (%d skill(s) of its own) is inside %s's repository" % (name, len(own), ", ".join(sorted(outer))))
    note = "; not read, no project_path or no such directory: %s" % ", ".join(sorted(unread)) if unread else ""
    if not read:
        return lib.Result("FAIL", "project roots", "no project read" + note)
    if bad:
        return lib.Result("FAIL", "project roots", "; ".join(bad) + note)
    return lib.Result("PASS", "project roots", "read %d project(s), none hides its own skills behind an enclosing profile%s" % (read, note))


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
    unpatched one forge init installs with `pnpm dlx @opengsd/gsd-core`."""
    return "npm" if lib.gsd_patched() else "pnpm"


def _gsd_missing():
    tool = _gsd_tool()
    return None if shutil.which(tool) else (
        "gsd is on in config/forge.json but %s is not on PATH -- install %s or set integrations.gsd false"
        % (tool, "node" if tool == "npm" else "pnpm"))


def _agent_browser_missing():
    return None if shutil.which("agent-browser") else (
        "agent_browser is on in config/forge.json but agent-browser is not on PATH -- run `forge toolchain --fix`, then "
        "open a new shell, or set integrations.agent_browser false")


INTEGRATION_NEEDS = {"codex": (_codex_missing, "codex found on PATH"), "gsd": (_gsd_missing, lambda: "%s found on PATH" % _gsd_tool()),
                     "hindsight": (None, "no dependency checked here"),
                     "consent": (None, "its own row, `consent`, looks at the adapter, the profiles and the hook"),
                     "agent_browser": (_agent_browser_missing, "agent-browser found on PATH")}
# An integration whose check does not exist yet: a SKIP, NOT RUN, NOT ARMED, on or off, never a PASS that looked at
# nothing. The value says when the check arrives (7.1 of the framework plan puts MemPalace's).
INTEGRATION_PENDING = {"mempalace": "its check arrives with the MemPalace part"}


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
    out, checked, unread, pending_on = [], 0, False, False
    for name in lib.INTEGRATIONS:
        on = lib.on(name)
        if name in INTEGRATION_PENDING:
            pending_on = pending_on or on
            out.append(lib.Result("SKIP", "integrations", "%s%s is %s in config/forge.json%s %s" % (
                NOT_ARMED, name, "on" if on else "off", ", but" if on else ";", INTEGRATION_PENDING[name])))
            continue
        if not on:
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
        out.append(lib.Result("SKIP", "integrations", NOT_ARMED + (
            "no integration with a check is on in config/forge.json" if pending_on else "every integration is off in config/forge.json")
            + " and no user_hooks row is configured, so there is nothing to check"))
    elif not checked:
        out.append(lib.Result("FAIL", "integrations", "checked 0: %s and no "
                              "user_hooks row names a script, so this row proved nothing" % (
                                  "no integration with a check is on in config/forge.json" if pending_on
                                  else "every integration is off in config/forge.json")))
    else:
        out.append(lib.Result("PASS", "integrations", "checked %d: %d integration(s) on, %d user_hooks script(s)"
                              % (checked, integrations, checked - integrations)))
    return out


# The `consent` row (1.1 U4). The hook row is written with "onFailure": "block", so an entry that is there but
# whose command no longer starts (python moved by a mise upgrade, forge moved) leaves every session without Bash
# and MCP: that the entry exists proves nothing, so the row runs the installed command on two payloads.
CONSENT_MARKER = "guard_tool_use.py --consent"
CONSENT_SMOKE_BENIGN = "git status"


def _consent_guard():
    """hooks/guard_tool_use.py of this checkout, loaded by path: it holds consent_config and production_error,
    the one definition of what gateway.json and a profile's `production` may say."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("forge_consent_guard", os.path.join(lib.ROOT, "hooks", "guard_tool_use.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def consent_probe(command, cwd, payload_command, timeout, want_code, want_text=None):
    """None when the installed hook `command` (shell=True, `timeout` seconds as the hook's cap, FORGE_CONSENT=unattended
    so that no window ever opens, and a private XDG_STATE_HOME so that the probe leaves no line in the real consent
    log) answers a Bash payload for `payload_command` with exit `want_code` (and `want_text` in stderr); else why not."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": payload_command}, "cwd": cwd,
                          "session_id": "forge-doctor", "hook_event_name": "PreToolUse"})
    state = tempfile.mkdtemp(prefix="forge-consent-probe-")
    try:
        env = dict(os.environ, FORGE_CONSENT="unattended", XDG_STATE_HOME=state)
        env.pop("CLAUDE_PROJECT_DIR", None)
        try:
            r = subprocess.run(command, shell=True, input=payload, env=env, text=True, capture_output=True,
                               timeout=timeout, cwd=cwd if os.path.isdir(cwd) else lib.ROOT)
        except subprocess.TimeoutExpired:
            return "`%s` did not answer in %d s" % (payload_command, timeout)
    finally:
        shutil.rmtree(state, ignore_errors=True)
    last = (r.stderr.strip().splitlines() or [""])[-1]
    if r.returncode != want_code:
        return "`%s` exited %d, want %d%s" % (payload_command, r.returncode, want_code, (": " + last) if last else "")
    if want_text and want_text not in r.stderr:
        return "`%s` exited %d as wanted but its stderr has no %s%s" % (payload_command, r.returncode, want_text,
                                                                        (": " + last) if last else "")
    return None


def consent_row():
    """The `consent` row: SKIP (NOT RUN, NOT ARMED) while integrations.consent is off. On, the first problem found is
    a FAIL that names its fix, in this order: config/gateway.json missing or invalid (the guard's consent_config);
    the adapter missing or not executable, or the built-in one without `gum` or the Omarchy launcher; no profile
    declares `production` (looking at zero is a failure: the window would never open); ~/.claude/settings.json
    without the `--consent` entry or with it lacking "onFailure": "block"; consent.timeout_s not below the entry's
    timeout; the smoke test, which runs the entry's exact command on `git status` (must exit 0) and on a push to
    a production branch with no one to ask (must exit 2 with CONSENT_UNATTENDED:). The PASS says how much it looked at."""
    from forge import hooks  # not at import: it reads config/forge.json
    if not lib.on("consent"):
        return lib.Result("SKIP", "consent", NOT_ARMED + "consent is off in config/forge.json, so the window was not looked at")
    fail = lambda why: lib.Result("FAIL", "consent", why)
    gateway = os.path.join(lib.ROOT, "config", "gateway.json")
    try:
        guard = _consent_guard()
        cfg = guard.consent_config(lib.ROOT)
    except Exception as e:
        return fail("%s -- fix config/gateway.json (examples/gateway.json is the template: cp examples/gateway.json config/gateway.json), "
                    "or set integrations.consent false and run forge sync --apply" % e)
    adapter, limit = cfg["adapter"], cfg["timeout_s"]
    if not os.path.isfile(adapter) or not os.access(adapter, os.X_OK):
        return fail("the adapter %s is %s -- restore it (git checkout scripts/consent/) and chmod +x it, or point consent.adapter in %s at one that is"
                    % (lib.short(adapter), "not executable" if os.path.isfile(adapter) else "not there", lib.short(gateway)))
    if adapter == os.path.realpath(os.path.join(lib.ROOT, "scripts", "consent", "omarchy")):
        for tool, fix in (("gum", "install gum (pacman -S gum)"), ("omarchy-launch-floating-terminal-with-presentation", "this is not an Omarchy session: use another adapter")):
            if not shutil.which(tool):
                return fail("the omarchy adapter needs `%s` on PATH and it is not there -- %s" % (tool, fix))
    declared = [p for p in cfg["profiles"] if "production" in p]
    if not declared:
        return fail("no profile in config/profiles declares `production`, so no call would ever match and the window would never open -- "
                    'add "production": {"branches": [...], "commands": [...]} to the profile of a project that deploys')
    for p in declared:
        why = guard.production_error(p["production"])
        if why:
            return fail("%s: %s -- fix the profile; the guard refuses every call from that project while it is invalid" % (lib.short(p["file"]), why))
    where = lib.short(hooks.USER_SETTINGS)
    try:
        doc = lib.read_owned(hooks.USER_SETTINGS, None)
    except lib.Unreadable as e:
        return fail("%s is unreadable, so the --consent entry was not looked for: %s" % (where, e))
    entries = [e for e in lib.hook_entries(doc)[0] if CONSENT_MARKER in str(e[3].get("command"))] if doc is not None else []
    if not entries:
        return fail("%s holds no `%s` entry, so the window is not wired -- forge sync --apply" % (where, CONSENT_MARKER))
    for event, _, _, hook in entries:
        if hook.get("onFailure") != "block":
            return fail('the %s entry under %s has onFailure %s, want "block": a hook that hangs or breaks would let the call through '
                        "-- forge sync --apply" % (CONSENT_MARKER, event, json.dumps(hook.get("onFailure"))))
    command, cap = entries[0][3].get("command"), entries[0][3].get("timeout")
    if isinstance(cap, bool) or not isinstance(cap, int) or limit >= cap:
        return fail("consent.timeout_s is %d and the hook entry's timeout is %s: the adapter must give up before the hook is killed, so "
                    "timeout_s must be below it -- lower timeout_s in %s, or forge sync --apply to restore the entry's 300"
                    % (limit, json.dumps(cap), lib.short(gateway)))
    branch_profile = next((p for p in declared if p["production"].get("branches")), None)
    if branch_profile:
        cwd, push = branch_profile["project_path"], "git push origin %s" % branch_profile["production"]["branches"][0]
    else:  # production lists commands only: a command entry stands in for the push
        stand_in = next(((p, c) for p in declared for c in p["production"].get("commands", []) if not c.startswith("mcp__")), None)
        if not stand_in:
            return fail("no profile's `production` lists a branch or a command the smoke test can send, so the --consent entry was not run -- "
                        "list a branch in production.branches")
        cwd, push = stand_in[0]["project_path"], stand_in[1]
    for text, code, marker in ((CONSENT_SMOKE_BENIGN, 0, None), (push, 2, "CONSENT_UNATTENDED:")):
        why = consent_probe(command, cwd, text, cap, code, marker)
        if why:
            return fail("the installed command `%s` fails its smoke test: %s -- forge sync --apply; if the entry is right, "
                        "hooks/guard_tool_use.py --consent itself does not answer" % (command, why))
    return lib.Result("PASS", "consent", "adapter %s, timeout_s %d below the hook's %d s, %d profile(s) with production, `%s` exits 0 and "
                      "`%s` exits 2 with CONSENT_UNATTENDED: through `%s`" % (lib.short(adapter), limit, cap, len(declared),
                                                                            CONSENT_SMOKE_BENIGN, push, command))


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


def gsd_isolation_guard_row():
    """The `gsd isolation guard` row: config/forge.json's `gsd_isolation_guard` switches off the one user-scope
    row `gsd-agent-isolation-guard.js` (forge.hooks.ROW_OPTIONAL). A value that is not true or false is a
    FAIL (forge reads it as true). SKIP (NOT RUN, NOT ARMED) while forge writes no GSD row at all (gsd off, or
    gsd_patches not true) and while the key is false, the line naming how to turn it on. Otherwise the entry
    with forge's exact command must be in ~/.claude/settings.json: PASS says it was there, a missing file, a
    file that does not parse or an entry that is not in it is a FAIL naming `forge sync --apply`."""
    from forge import hooks  # not at import: it reads config/forge.json
    marker = hooks.ISOLATION_GUARD
    key = hooks.ROW_OPTIONAL[marker]
    value = lib.settings().get(key)
    if key in lib.settings() and not isinstance(value, bool):
        return lib.Result("FAIL", "gsd isolation guard", "%s is %s in config/forge.json, not true or false, so forge reads it as true -- "
                          "set it to true or false" % (key, json.dumps(value)))
    if not lib.on("gsd") or not lib.gsd_patched():
        return lib.Result("SKIP", "gsd isolation guard", NOT_ARMED + "forge writes no GSD hook row (the gsd integration is off, "
                          "or gsd_patches is not true, in config/forge.json), so %s was not looked at" % key)
    if value is False:
        return lib.Result("SKIP", "gsd isolation guard", NOT_ARMED + "%s is false in config/forge.json, so forge writes no %s row "
                          "and takes its entry out; set it to true (or delete the key) and run forge sync --apply to wire it"
                          % (key, marker))
    row = next((r for r in hooks.USER_HOOKS if r[3] == marker), None)
    where = lib.short(hooks.USER_SETTINGS)
    if row is None:  # unreachable while the gates above agree with forge.hooks._row_on
        return lib.Result("FAIL", "gsd isolation guard", "forge.hooks holds no %s row although %s is not false" % (marker, key))
    try:
        doc = lib.read_owned(hooks.USER_SETTINGS, None)
    except lib.Unreadable as e:
        return lib.Result("FAIL", "gsd isolation guard", "%s is unreadable, so %s was not looked for: %s" % (where, marker, e))
    if doc is None:
        return lib.Result("FAIL", "gsd isolation guard", "%s is not there, so the %s entry is missing -- forge sync --apply" % (where, marker))
    entries, _ = lib.hook_entries(doc)
    found = [e for e in entries if e[0] == row[0] and e[3].get("command") == row[1]]
    if not found:
        return lib.Result("FAIL", "gsd isolation guard", "%s holds no %s entry under %s with forge's command -- forge sync --apply "
                          "(or set %s to false to leave it out)" % (where, marker, row[0], key))
    return lib.Result("PASS", "gsd isolation guard", "%d %s entr%s under %s in %s" % (
        len(found), marker, "y" if len(found) == 1 else "ies", row[0], where))


# How long the `gsd engine` row waits for `gsd-tools.cjs --help`, which prints its usage and returns in well under a second.
GSD_ENGINE_TIMEOUT = 20
GSD_ENGINE_FIX = "python3 bin/forge skills --apply"


def gsd_engine_row():
    """The `gsd engine` row: with the gsd integration on, `node <HOME>/.claude/gsd-core/bin/gsd-tools.cjs --help`
    (it renders the usage and exits 0 without reading a project) must exit 0. Nothing else ran the installed
    engine, and a gsd-tools.cjs that died on a missing required module was green in every other row. A non-zero
    exit, a timeout or a missing gsd-core is a FAIL naming the fix, with the first error line of what node
    printed. SKIP while gsd is off, and SKIP (NOT RUN, NOT ARMED) with no node on PATH, as neither looked at
    the engine."""
    if not lib.on("gsd"):
        return lib.Result("SKIP", "gsd engine", NOT_ARMED + "gsd is off in config/forge.json")
    script = os.path.join(lib.HOME, ".claude", "gsd-core", "bin", "gsd-tools.cjs")
    where = lib.short(script)
    node = shutil.which("node")
    if not node:
        return lib.Result("SKIP", "gsd engine", NOT_ARMED + "node is not on PATH, so the engine was not run")
    if not os.path.isfile(script):
        return lib.Result("FAIL", "gsd engine", "gsd is on and %s is not there -- %s" % (where, GSD_ENGINE_FIX))
    try:
        r = subprocess.run([node, script, "--help"], capture_output=True, text=True, timeout=GSD_ENGINE_TIMEOUT,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return lib.Result("FAIL", "gsd engine", "node %s --help did not return in %s s -- %s" % (where, GSD_ENGINE_TIMEOUT, GSD_ENGINE_FIX))
    except OSError as e:
        return lib.Result("FAIL", "gsd engine", "node %s --help could not start: %s -- %s" % (where, e, GSD_ENGINE_FIX))
    if r.returncode == 0:
        return lib.Result("PASS", "gsd engine", "node %s --help exited 0" % where)
    lines = [l.strip() for l in (r.stderr or r.stdout).splitlines() if l.strip()]
    first = next((l for l in lines if "Error" in l), lines[0] if lines else "no output")
    return lib.Result("FAIL", "gsd engine", "node %s --help exited %d: %s -- %s" % (where, r.returncode, first, GSD_ENGINE_FIX))


# The `research expiry` row: a research file under <project>/.planning/research/ may say, in its first
# HEADER_LINES lines, when it must be re-checked (README.md, "research expiry").
RESEARCH_DIR = os.path.join(".planning", "research")
RESEARCH_HEADER_LINES = 20
RESEARCH_MAX_BYTES = 1024 * 1024
RESEARCH_NAMED = 10
RESEARCH_FIX = "re-check the research and move its expires date, or delete it"
EXPIRES_LINE = re.compile(r"^\s*expires\s*:\s*(.*?)\s*$", re.I)
VOLATILITY_LINE = re.compile(r"^\s*volatility\s*:\s*(high|medium|low)\s*$", re.I)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def today():
    """The day the `research expiry` row compares with; a test replaces it."""
    return datetime.date.today()


def research_header(path):
    """(expires, volatility, raw) of a research file's first RESEARCH_HEADER_LINES lines: `expires` a date, or
    None with `raw` the text after `expires:` when it is not a YYYY-MM-DD date, or None with no `expires:` line
    at all; `volatility` high, medium or low, lower-cased, or None. The first `expires:` line wins. Raises OSError."""
    expires = volatility = raw = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for _, line in zip(range(RESEARCH_HEADER_LINES), fh):
            m = EXPIRES_LINE.match(line)
            if m and raw is None:
                raw = m.group(1).strip("'\"")
                if ISO_DATE.fullmatch(raw):
                    try:
                        expires = datetime.date.fromisoformat(raw)
                    except ValueError:
                        pass
            m = VOLATILITY_LINE.match(line)
            if m and volatility is None:
                volatility = m.group(1).lower()
    return expires, volatility, raw


def research_expiry(only=None):
    """The `research expiry` row: every markdown file under <project_path>/.planning/research/ of each profile
    (frozen ones too, since stale research is not forge drift; a path two profiles share is read once, by the
    first) with an `expires: YYYY-MM-DD` line in its first 20 lines (a bare line, any case, or inside `---`
    front matter; an optional `volatility: high|medium|low`). The date is the last day the research stands, so
    a file is expired the day after, by today(). WARN names each expired file as `project/path (expired DATE,
    volatility V)` and each malformed date as `(unreadable expiry: 'text')`, ten at most and then `and N more`;
    a file with no header is only counted. A file over 1 MB and a link are skipped, and said. No research file
    in the scope is a PASS that says so (zero is possible here). Reads only; with `only`, that project alone."""
    seen, files, dated, skipped, projects = set(), 0, 0, 0, set()
    expired, unreadable = [], []  # (project/relative path, text)
    for name, prof in lib.profiles().items():
        root = prof.get("project_path")
        if only not in (None, name) or not root or not os.path.isdir(os.path.join(root, RESEARCH_DIR)):
            continue
        real = os.path.realpath(root)
        if real in seen:
            continue
        seen.add(real)
        for d, dirs, names in os.walk(os.path.join(root, RESEARCH_DIR)):
            dirs.sort()
            for n in sorted(names):
                path = os.path.join(d, n)
                if not n.lower().endswith(".md"):
                    continue
                label = "%s/%s" % (name, os.path.relpath(path, root).replace(os.sep, "/"))
                try:
                    if os.path.islink(path) or os.path.getsize(path) > RESEARCH_MAX_BYTES:
                        skipped += 1
                        continue
                    expires, volatility, raw = research_header(path)
                except OSError as e:
                    files, projects = files + 1, projects | {name}
                    unreadable.append((label, "could not be read: %s" % e.strerror))
                    continue
                files, projects = files + 1, projects | {name}
                if raw is not None and expires is None:
                    unreadable.append((label, "unreadable expiry: %r" % raw))
                elif expires is not None:
                    dated += 1
                    if expires < today():
                        expired.append((label, "expired %s%s" % (expires.isoformat(), ", volatility " + volatility if volatility else "")))
    if not files and not skipped:
        return lib.Result("PASS", "research expiry", "0 research file(s) in 0 project(s), no .planning/research/*.md to check")
    seen_n = "%d research file(s) in %d project(s), %d with an expiry" % (files, len(projects), dated)
    note = ", %d skipped (over 1 MB or a link)" % skipped if skipped else ""
    if not (expired or unreadable):
        return lib.Result("PASS", "research expiry", seen_n + ", none expired" + note)
    named = ["%s (%s)" % row for row in sorted(expired) + sorted(unreadable)]
    more = ["and %d more" % (len(named) - RESEARCH_NAMED)] if len(named) > RESEARCH_NAMED else []
    return lib.Result("WARN", "research expiry", "; ".join(
        ["%s, %d expired, %d unreadable expiry%s" % (seen_n, len(expired), len(unreadable), note)] + named[:RESEARCH_NAMED] + more))


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


# How long the `context base` row waits for one `fwx context` call. The audit reads subagent transcripts, which are
# megabytes, and a check with --hook-command runs the hook once.
CONTEXT_BASE_TIMEOUT = 120
CONTEXT_BASE_HOOK = "subagent_context.py"
CONTEXT_BASE_LAST = "3"  # sessions the audit reads: enough to see a regression, few enough to be quick


def _fwx_context_base(fwx, args):
    """(exit code or None on a timeout, stdout lines, stderr lines) of `python3 <fwx> context ARGS`."""
    try:
        r = subprocess.run([sys.executable, fwx, "context"] + args, cwd=lib.ROOT, text=True, capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=CONTEXT_BASE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, [], []
    return r.returncode, r.stdout.strip().splitlines(), r.stderr.strip().splitlines()


def _context_base_target(label, fwx, steps):
    """One result for one target. `steps` is [(kind, args)], each run through fwx: any exit but 0 and 77 is a FAIL that
    quotes what fwx printed (every FAIL line of an audit, so the agent and its type are there) and the command that
    reproduces it; 77 is NOT RUN, NOT ARMED; 0 is a PASS with fwx's last line. A target any of whose steps failed is a FAIL
    whatever the others did; one with only 77s is a SKIP; one with a 0 and a 77 is a PASS that says which step did not run."""
    failed, unarmed, passed = [], [], []
    for kind, args in steps:
        code, out, err = _fwx_context_base(fwx, args)
        # fwx's summary (`audited ...`, `checked ...`) is the line to quote; the audit prints it first, its FAIL lines after
        last = next((l for l in out if l.startswith(("audited ", "checked "))), out[-1] if out else (err[-1] if err else ""))
        if code == 0:
            passed.append("%s: %s" % (kind, last))
        elif code == lib.NOT_RUN:
            unarmed.append((kind, last[len(NOT_ARMED):] if last.startswith(NOT_ARMED) else last))
        else:
            fails = [l for l in out if l.startswith("FAIL ")]
            said = ([last] if last and last not in fails else []) + fails[:5] + (
                ["+%d more FAIL line(s)" % (len(fails) - 5)] if len(fails) > 5 else []) + err[:5]
            why = "did not answer in %d s" % CONTEXT_BASE_TIMEOUT if code is None else "exit %d" % code
            failed.append("%s %s (%s) -- %s" % (kind, why, " | ".join(said) or "no output",
                                               shlex.join(["python3", fwx, "context"] + args)))
    if failed:
        return lib.Result("FAIL", "context base", "%s: %s" % (label, "; ".join(failed)))
    if not passed:
        return lib.Result("SKIP", "context base", "%s%s: %s" % (NOT_ARMED, label, "; ".join("%s: %s" % u for u in unarmed)))
    return lib.Result("PASS", "context base", "%s: %s" % (label, "; ".join(passed + ["%s: %s%s" % (k, NOT_ARMED, t) for k, t in unarmed])))


def context_base_row():
    """The `context base` row (2.5): did every subagent get the base context it should? Targets, one result each:
    every entry of ~/.claude/settings.json whose command runs `subagent_context.py --file F [--source S]`, and every
    profile with `framework: true`. For an entry, `fwx context lint --file F --source S --hook-command CMD` (the
    file is sealed and current, the hook answers a general-purpose agent and not an Explore one) and `audit --project
    <this checkout> --last 3 --file F` (the subagent transcripts of the last three sessions here); for a profile,
    `lint --project P` and `audit --project P --last 3`. fwx is `bin/fwx` of framework.plugin_source.path. Exit 0 is a
    PASS, 77 a SKIP, anything else a FAIL naming the command to run by hand. No fwx, or nothing to look at: a SKIP, NOT RUN,
    NOT ARMED. The audit reads transcripts written before the hook existed, so it FAILs until three newer sessions with
    subagents have passed; that is the row working, not a reason to weaken it."""
    from forge import framework, hooks  # not at import: hooks reads config/forge.json
    src, why = framework._source()
    fwx = os.path.join(src["path"], "bin", "fwx") if src else None
    if not fwx or not os.path.isfile(fwx):
        return lib.Result("SKIP", "context base", NOT_ARMED + "no bin/fwx to run (%s), so no subagent's base context was looked at"
                          % (why or "%s is not there" % lib.short(fwx)))
    where = lib.short(hooks.USER_SETTINGS)
    try:
        doc = lib.read_owned(hooks.USER_SETTINGS, None)
    except lib.Unreadable as e:
        return lib.Result("FAIL", "context base", "%s is unreadable, so its %s entries were not looked for: %s" % (where, CONTEXT_BASE_HOOK, e))
    out = []
    for event, _, _, hook in (lib.hook_entries(doc)[0] if doc is not None else []):
        command = hook.get("command")
        if not isinstance(command, str) or CONTEXT_BASE_HOOK not in command:
            continue
        try:
            words = shlex.split(command)
        except ValueError as e:
            out.append(lib.Result("FAIL", "context base", "the %s entry under %s in %s does not parse (%s) -- fix the entry, or forge sync --apply"
                                  % (CONTEXT_BASE_HOOK, event, where, e)))
            continue
        opts = {w: words[i + 1] for i, w in enumerate(words[:-1]) if w in ("--file", "--source")}
        if "--file" not in opts:
            out.append(lib.Result("FAIL", "context base", "the %s entry under %s in %s has no --file, so there is no base to check -- "
                                  "forge sync --apply, or add --file F to the entry" % (CONTEXT_BASE_HOOK, event, where)))
            continue
        check = ["lint", "--file", opts["--file"]] + (["--source", opts["--source"]] if "--source" in opts else []) + ["--hook-command", command]
        audit = ["audit", "--project", lib.ROOT, "--last", CONTEXT_BASE_LAST, "--file", opts["--file"]]
        out.append(_context_base_target("hook %s" % lib.short(opts["--file"]), fwx, [("check", check), ("audit", audit)]))
    for name, prof in sorted(lib.profiles().items()):
        if prof.get("framework") is True and prof.get("project_path"):
            project = prof["project_path"]
            out.append(_context_base_target("profile %s" % name, fwx, [
                ("check", ["lint", "--project", project]), ("audit", ["audit", "--project", project, "--last", CONTEXT_BASE_LAST])]))
    return out or lib.Result("SKIP", "context base", NOT_ARMED + "no %s entry in %s and no profile with framework true, so no subagent's base "
                             "context was looked at" % (CONTEXT_BASE_HOOK, where))


def framework_ignore_row(only=None):
    """The `framework ignore` row: in every profile with `framework: true` (just `only`, when given) git answers as the
    framework needs for four sample paths (.fwx/x/y.md and .fwx/decisions.tsv not ignored, .claude/<plugin>.json and
    .claude/worktrees/x ignored), by `git check-ignore -v --no-index` asked of a scratch repository with the project's real
    layout (forge/fwxignore.py: the same function the sync uses, so the two agree). A FAIL names the path and the rule
    with file:line, and says when the rule is the machine's global ignore file. How many projects it looked at is in the detail; zero where a framework
    profile exists is a FAIL, and no framework profile at all is a SKIP, NOT RUN, NOT ARMED. A profile with
    `framework_ignore_block: false` is switched off: not looked at, and a SKIP of the same wording when no other is."""
    from forge import framework, fwxignore
    wanted = {n: p for n, p in sorted(lib.profiles().items()) if p.get("framework") is True and (only is None or n == only)}
    off = [n for n, p in wanted.items() if p.get("framework_ignore_block") is False]
    wanted = {n: p for n, p in wanted.items() if n not in off}
    if not wanted:
        why = ("framework_ignore_block is false in %s (the project keeps its framework documents out of its git on purpose)" % ", ".join(off)
               if off else "no profile has framework: true")
        return lib.Result("SKIP", "framework ignore", NOT_ARMED + "%s, so no project's ignore rules were looked at" % why)
    looked, bad, skipped = [], [], []
    for name, prof in wanted.items():
        pp = prof.get("project_path")
        plan = framework.plan(prof, name)
        if prof.get("frozen"):
            skipped.append("%s (frozen: forge writes nothing there)" % name)
        elif plan.error or not plan.on:
            skipped.append("%s (%s)" % (name, plan.error or "framework is off"))
        elif not pp or not lib.in_git_repo(pp):
            skipped.append("%s (not a git repository)" % name)
        else:
            try:
                wrong = fwxignore.check(pp, plan.name)
            except lib.Unreadable as e:  # an ignore file of the project's layout
                skipped.append("%s (%s unreadable: %s)" % (name, lib.short(e.path), e.reason))
                continue
            if wrong is None:
                skipped.append("%s (git did not answer)" % name)
                continue
            looked.append(name)
            if wrong:
                bad.append("%s: %s -- %s" % (name, fwxignore._says(wrong), fwxignore.advice(wrong, lib.repo_owns_tracked_files(prof))))
    skipped += ["%s (framework_ignore_block is false: switched off)" % n for n in off]
    note = "; not looked at: %s" % ", ".join(skipped) if skipped else ""
    if bad:
        return lib.Result("FAIL", "framework ignore", "looked at %d project(s)%s: %s" % (len(looked), note, " | ".join(bad)))
    if not looked:
        return lib.Result("FAIL", "framework ignore", "looked at 0 of %d framework project(s)%s" % (len(wanted), note))
    return lib.Result("PASS", "framework ignore", "looked at %d project(s) (%s): the four sample paths are as the framework needs%s"
                      % (len(looked), ", ".join(looked), note))


def local_plugins_row():
    """The `local plugins` row: every folder of config/forge.json `local_plugins` is registered in the machine's marketplace
    registry at its path (forge/marketplace.py); a SKIP, NOT RUN, NOT ARMED, with the key empty or missing."""
    from forge import marketplace
    return marketplace.row()


# (name, command, fix). A command exits 0 when healthy. A callable returns a lib.Result instead,
# which is how a check can be a WARN: a command's exit code is only ever PASS or FAIL
# (hindsight_doctor exits with its failure count, argparse with 2). The fix is appended to the
# detail of any result that is not a PASS.
CHECKS = [
    ("skill refs", ["scripts/sync/verify_skill_refs.py"], "fix the profile's skills_keep"),
    ("skill keep", ["scripts/sync/sync_skill_keep.py", "--check"], "python3 scripts/sync/sync_skill_keep.py --apply"),
    ("skill names", skill_name_clashes, "rename the project skill, or delete it if it was meant to be the global one"),
    ("project roots", nested_project_roots, "git init in the nested project's directory and ignore it from the outer repository: an outer profile's skill overrides switch the inner project's skills off, and an inner 'on' does not win (skills/new-project makes every project its own repository)"),
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
    # Its failures carry their own fix, so the row's is empty.
    ("consent", consent_row, ""),
    ("codex hooks", codex_hooks_row, "forge sync --apply brings ~/.codex/hooks.json in line with codex_harness (forge's rows in with it true, out with it false); a file that does not parse is Codex's own to repair"),
    # Its failures and its SKIP carry their own fix, so the row's is empty.
    ("gsd isolation guard", gsd_isolation_guard_row, ""),
    # Its failures carry their own fix (python3 bin/forge skills --apply), so the row's is empty.
    ("gsd engine", gsd_engine_row, ""),
    ("research expiry", research_expiry, RESEARCH_FIX),
    # Its failures carry the command that reproduces them, so the row's fix is empty.
    ("context base", context_base_row, ""),
    # Its failures carry their own fix, so the row's is empty.
    ("framework ignore", framework_ignore_row, ""),
    # config/forge.json's `doctor_extra` rows, each with the fix it names; the row's own fix is empty.
    ("doctor_extra", doctor_extra_row, ""),
    # Its failures carry their own fix (python3 bin/forge sync --apply), so the row's is empty.
    ("local plugins", local_plugins_row, ""),
]

# What `forge sync NAME` (a dry-run) prints for a file its --apply would change: one
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
    """PASS when the dry-run of `forge sync NAME` exits 0 and would write nothing. Only
    counts are shown, never the generator's lines: `forge sync NAME` prints them."""
    if prof.get("frozen"):
        return lib.Result("PASS", "generated", "frozen: forge writes nothing")
    r = lib.run(["bin/forge", "sync", name], capture=True)
    lines = (r.stdout + r.stderr).splitlines()
    writes, bangs = pending_writes(lines), sum(1 for l in lines if lib.BANG.match(l))
    if not writes and not r.returncode:
        return lib.Result("PASS", "generated", "the dry-run of forge sync %s would write nothing" % name)
    problems = (["%d pending write(s)" % writes] if writes else []) + (
        ["the dry-run exits %d with %d '!' line(s), which forge sync %s shows" % (r.returncode, bangs, name)]
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
        ("generated", lambda: generated_current(name, prof), "forge sync --apply " + name),
        ("skill names", lambda: skill_name_clashes(name), fix["skill names"]),
        ("project roots", lambda: nested_project_roots(name), fix["project roots"]),
        ("instruction files", lambda: instruction_file_blocks(name), fix["instruction files"]),
        ("command guard", lambda: command_guard_smoke(name), fix["command guard"]),
        ("worktree guard", lambda: worktree_guard_smoke(name), fix["worktree guard"]),
        ("ponytail", lambda: ponytail_row(name), fix["ponytail"]),
        ("research expiry", lambda: research_expiry(name), RESEARCH_FIX),
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
GSD_DIFFERS = 2  # sync_gsd_runtime.py's DIFFERS


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


def run_steps(command, steps, apply, scope):
    """`forge <command>`: each of `steps` as its script, in order, one run at a time, noting what an apply wrote
    in the journal. Returns 1 when a step failed."""
    failed = []
    log = None
    if apply:  # an apply notes each change it makes in the journal; a dry-run makes none
        fd, log = tempfile.mkstemp(prefix="forge-writes-")
        os.close(fd)
    try:
        with lib.lock() if apply else contextlib.nullcontext():
            for name, script, dry_flag, apply_flag, extra in steps:
                flag = apply_flag if apply else dry_flag
                if STEP_INTEGRATION.get(name) and not lib.on(STEP_INTEGRATION[name]):
                    print("== forge: %s == NOT RUN, NOT ARMED (%s off)" % (name, STEP_INTEGRATION[name]), flush=True)
                    print(flush=True)
                    continue
                print("== forge: %s ==" % name, flush=True)
                env = None
                if log:
                    open(log, "w").close()
                    env = dict(os.environ, FORGE_WRITE_LOG=log)
                if lib.run([script] + ([flag] if flag else []) + extra + scope, env=env).returncode:
                    failed.append(name)
                if log:
                    note_writes(log, command, name)
                print(flush=True)
    finally:
        if log:
            with contextlib.suppress(OSError):
                os.remove(log)
    if failed:
        print("forge %s: failed -- %s" % (command, ", ".join(failed)))
    return 1 if failed else 0


def cmd_sync(a):
    """forge sync [NAME | --all] [--apply]. A NAME no profile has is refused here, before any generator runs: only some
    generators refuse a name they do not know, so without this a misspelling would run the others for nothing.
    A profile that cannot be read is let through: the generators name it ('! could not read')."""
    if a.project:
        skipped = []
        known = lib.profiles(skipped)
        if a.project not in known and a.project not in {f[:-len(".claude.json")] for f, _ in skipped}:
            print("! forge sync: unknown project: %s (known: %s)" % (a.project, ", ".join(sorted(known))))
            return 1
    return run_steps("sync", SYNC, a.apply, (["--project", a.project] if a.project else []) + (["--all"] if a.all else []))


def cmd_skills(a):
    return run_steps("skills", SKILLS, a.apply, ["--all"])  # --all: not scoped to the session that happens to run it


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
# for byte (docs/archive/designs/unify-split-design.md §2).
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


def check_and_tell():
    """What a session start says about the machine, and fixes nothing (docs/toolchain-design.md section 5): one
    note when the GSD runtime differs from forge's staged, patched copy (`sync_gsd_runtime.py --check`,
    which never restages), the check's own '!' lines when it failed, and one for a failing `toolchain` row.
    Every session says it, whatever its project: a runtime or a python that lost its libraries breaks them all."""
    notes = []
    if lib.on("gsd"):
        r = lib.run(["scripts/sync/sync_gsd_runtime.py", "--check", "--all"], capture=True)
        if r.returncode == GSD_DIFFERS:
            notes.append("GSD runtime differs from forge's patched copy -- run `forge skills --apply`")
        elif r.returncode:
            why = " | ".join(l.strip() for l in (r.stdout + r.stderr).splitlines() if CHANGED.search(l)) or "check exit %d" % r.returncode
            notes.append("gsd runtime: %s -- run `forge skills` to see why" % why)
    row = toolchain.row()
    if row.level == "FAIL":
        notes.append("toolchain: %s -- run `forge toolchain --fix`" % row.detail)
    return notes


def cmd_session_start(a):
    """Bring this session's own project up to date (lib.context scopes each generator by CLAUDE_PROJECT_DIR),
    then say what is wrong with the machine without fixing it (check_and_tell). It says only what changed or
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
            with lib.lock(timeout=20):
                for step, script, _, apply_flag, extra in SYNC:
                    open(log, "w").close()
                    r = lib.run([script] + ([apply_flag] if apply_flag else []) + extra, capture=True, env=env)
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
        notes += check_and_tell()
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
FWX_PREFIX = "plugins/fwx/"


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
    found = sorted(f for f in listed if not f.startswith("benchmarks/")
                   and os.path.basename(f).startswith("test_") and f.endswith(".py"))
    # fwx (plugins/fwx) has its own runner, `fwx test`: its exit codes (77, --expect-not-run) and its minutes of work
    # are its own, and CI runs it as a job of its own.
    fwx_owned = [f for f in found if f.startswith(FWX_PREFIX)]
    files = [f for f in found if f not in fwx_owned]
    if not files:
        return lib.report([lib.Result("FAIL", "git ls-files", "no tests found in %s" % lib.ROOT)])
    mutants = getattr(a, "mutants", False)
    results = []
    if fwx_owned and not mutants:  # said, never a PASS, and not counted in the summary
        results.append(lib.Result("SKIP", FWX_PREFIX.rstrip("/"), "NOT RUN here, %d tracked test_*.py file(s) with their own runner: run "
                                  "`python3 %sbin/fwx test`" % (len(fwx_owned), FWX_PREFIX)))
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
            # (CLAUDE.md, rule 4). Its last line is why, after "NOT RUN: ".
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


def metrics_usage(a, prof, projects, fail, others):
    """forge metrics NAME --usage: forge/usage.py's report over every folder of the project's sessions. A FAIL (rc 1)
    for what makes cmd_metrics fail today, and for zero sessions, which is never read as "0 uses"."""
    path = prof.get("project_path")
    if not path:
        return fail("the profile has no project_path")
    if a.baseline or a.session or a.until or a.events_until:
        return fail("--usage takes only --since and --json")
    if a.since and not usage.date_ok(a.since):
        return fail("--since is not a YYYY-MM-DD date: %s" % a.since)
    try:
        names, left_out = usage.folders(projects, path, usage.worktree_dir_specs(prof, lib.HOME), usage.git_worktrees(path),
                                        transcript_key, others)
        sessions, counts = usage.collect(projects, names, a.since)
    except usage.UsageError as e:
        return fail(str(e))
    if not sessions:
        return lib.report([lib.Result("FAIL", "usage", "%s: 0 sessions in %s, usage unknown" % (
            a.project, ", ".join(names) or os.path.join(projects, transcript_key(path))))])
    rep = usage.report(a.project, sessions, counts, names, usage.project_skill_names(path), left_out)
    few = len(sessions) < usage.MIN_SESSIONS
    rep["few_sessions"] = few
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        look = rep["looked_at"]
        print("looked at %d sessions (%s to %s), %d subagent files, %d unreadable lines, in %d folders" % (
            look["sessions"], look["first"], look["last"], look["subagent_files"], look["unreadable_lines"], len(names)))
        if look["left_out_other_projects"]:
            print("left out as other projects' folders: %d" % look["left_out_other_projects"])
        print("%-14s %-34s %5s %8s  %-10s %s" % ("kind", "name", "calls", "sessions", "last seen", "listed bytes"))
        for i in rep["items"]:
            print("%-14s %-34s %5d %8d  %-10s %d" % (i["kind"], i["name"], i["calls"], i["sessions"], i["last_seen"] or "-", i["listed_bytes"]))
        for p in rep["plugins"] or []:
            print("plugin %s: %d bytes of SessionStart output" % (p["plugin"], p["startup_bytes"]))
        if rep["unlisted_commands"]:
            print("commands that are no listed skill (built-in, a plugin's or the project's): " + ", ".join(
                "%s x%d" % kv for kv in rep["unlisted_commands"].items()))
    if rep["plugins"] is None:
        un = rep["startup_unattributed"]
        print("NOT RUN, NOT ARMED: plugin startup_bytes: %d SessionStart hooks (%d bytes) and none names its plugin "
              "(the transcript keeps ${CLAUDE_PLUGIN_ROOT} unexpanded), so no per-plugin cost" % (un["hooks"], un["bytes"]),
              file=sys.stderr if a.json else sys.stdout)
    if few:
        print("few sessions (%d)" % len(sessions), file=sys.stderr if a.json else sys.stdout)
    return 0


def metrics_init_diff(a, init_diff, answers, use):
    """forge metrics NAME --init-diff BEFORE AFTER --answers F: 0 when the applied profile is what the answers say, 1
    for a fault, 2 for a usage error or an empty capture (see usage.init_diff)."""
    def bad(why):
        print("! forge metrics: %s" % why)
        return 2
    if use or a.baseline or a.session or a.since or a.until or a.events_until or a.json:
        print("! forge metrics: --init-diff takes no other option than --answers")
        return 1
    if not init_diff or not answers:
        return bad("--init-diff BEFORE AFTER needs --answers FILE (and --answers needs --init-diff)")
    try:
        before, after, marks = usage.load_capture(init_diff[0]), usage.load_capture(init_diff[1]), usage.load_answers(answers)
    except usage.UsageError as e:
        return bad(str(e))
    print(usage.count_line("before", before))
    print(usage.count_line("after", after))
    code, lines = usage.init_diff(before, after, marks)
    if code == 2:
        return bad(lines[0])
    return lib.report([lib.Result("FAIL", "init-diff", l) for l in lines] or [
        lib.Result("PASS", "init-diff", "%s: %d dropped, %d kept, nothing else changed" % (
            a.project, sum(m == "drop" for m in marks.values()), sum(m == "keep" for m in marks.values())))])


def cmd_metrics(a):
    """forge metrics NAME: node scripts/metrics/<script> over NAME's transcripts and repository.
    --usage and --init-diff are forge/usage.py's (metrics_usage, metrics_init_diff).
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
    init_diff, use, answers = getattr(a, "init_diff", None), getattr(a, "usage", False), getattr(a, "answers", None)
    if init_diff or answers:
        return metrics_init_diff(a, init_diff, answers, use)
    if use:
        return metrics_usage(a, profs[a.project], projects, fail, [p.get("project_path") for n, p in profs.items() if n != a.project and p.get("project_path")])
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


# --- forge init and forge new (docs/portable-design.md section 6): what a new checkout and a new project
# need before the generators have anything to read. Both only create: a file that is already there is kept.
EXAMPLES = os.path.join(lib.ROOT, "examples")
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# What init asks about, and what it asks. The others are switched on by hand with --with.
QUESTIONS = {"codex": "Codex found: manage its config too? [Y/n]",
             "gsd": "pnpm found: install GSD (planning skills, unpatched from its package with pnpm dlx @opengsd/gsd-core)? [Y/n]"}
# GSD's own installer, run by init through pnpm: the package's README names npx
# @opengsd/gsd-core [options] and bin/install.js's --help lists `--claude` (Claude Code only) and `-g, --global`
# (the config directory); with a runtime and a location given it asks nothing.
GSD_INSTALL = ["pnpm", "dlx", "@opengsd/gsd-core@latest", "--claude", "--global"]
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
    put(os.path.join(lib.ROOT, "config", "gateway.json"), example_text("gateway.json"))
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
    code = init_step("skills", ["bin/forge", "skills", "--apply"])  # the skill mirror used to come from sync
    if code:
        failed.append(("skills", code))
    code = init_step("sync", ["bin/forge", "sync", "--apply", "--all"])
    if code:
        failed.append(("sync", code))
    code = init_step("doctor", ["bin/forge", "doctor"])
    if code:
        failed.append(("doctor", code))
    if failed:
        print("! forge init: failed -- %s" % ", ".join("%s (exit %d)" % f for f in failed))
    print("put your own skills in %s/skills/<name>/SKILL.md (git ignores them; forge init --track versions them), "
          "then run forge skills --apply" % lib.ROOT)
    print("next: forge new <path>")
    return 1 if failed else 0


def cmd_new(a):
    if not os.path.exists(lib.SETTINGS):
        print("! forge new: config/forge.json missing -- run bin/forge init")
        return 1
    path = os.path.realpath(os.path.expanduser(a.path))
    if not os.path.isdir(path):
        print("! forge new: %s is not a directory" % a.path)
        return 1
    name = a.name or os.path.basename(path)
    if not KEBAB.match(name):
        print("! forge new: %r is not a kebab-case name (lowercase letters and digits, single dashes between them) "
              "-- pass --name" % name)
        return 1
    target = os.path.join(lib.PROFILES, name + ".claude.json")
    if os.path.lexists(target):
        print("! forge new: %s is already registered (config/profiles/%s.claude.json)" % (name, name))
        return 1
    ok, why = lib.may_write()
    if not ok:
        print(why)
        return 1
    profile = json.loads(example_text("profile.claude.json"))
    profile.update(project=name, project_path=path, writes_tracked_files=bool(a.writes_tracked_files))
    lib.write_text(target, lib.dumps(profile) + "\n")
    print("wrote  %s" % os.path.relpath(target, lib.ROOT), flush=True)
    return lib.run(["bin/forge", "sync", "--apply", name]).returncode


def _publish():
    """forge.publish, imported when one of its two commands runs: a defect in it cannot break sync,
    doctor or session-start."""
    from forge import publish
    return publish


def _uninstall():
    """forge.uninstall, imported only when it runs, like _publish."""
    from forge import uninstall
    return uninstall


# The names these commands had before the grammar of tool, object, verb. Removed, not aliased: an old name
# refuses with one line naming the new one and runs nothing, so a script that still calls it fails loudly.
RENAMED = {"add": "new", "launch": "start", "check-public": "lint"}
# `--project NAME` of these two commands is now the argument NAME, as in doctor, metrics and log. Cut, not aliased.
PROJECT_ARGUMENT = ("sync", "uninstall")


def old_project_flag(args):
    """The one line refusing `forge sync|uninstall --project NAME` (also `--project=NAME` and any abbreviation of the flag), or None."""
    if not args or args[0] not in PROJECT_ARGUMENT:
        return None
    for i, arg in enumerate(args[1:], 1):
        flag, eq, value = arg.partition("=")
        if len(flag) >= 3 and "--project".startswith(flag):
            given = value if eq else args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("-") else None
            return "forge %s --project%s: now 'forge %s %s'" % (args[0], " " + given if given else "", args[0], given or "NAME")
    return None


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] in RENAMED:
        print("forge %s: now 'forge %s'" % (args[0], RENAMED[args[0]]), file=sys.stderr)
        return 2
    refusal = old_project_flag(args)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    p = argparse.ArgumentParser(prog="forge", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="regenerate every project's config")
    s.add_argument("--apply", action="store_true", help="write; without it, only show what would change")
    scope = s.add_mutually_exclusive_group()
    scope.add_argument("project", nargs="?", help="this project only, no user-scope files")
    scope.add_argument("--all", action="store_true", help="every project, even inside a session")
    s.set_defaults(fn=cmd_sync)
    k = sub.add_parser("skills", help="the skill links and the GSD runtime (a dry-run unless --apply)")
    k.add_argument("--apply", action="store_true", help="write")
    k.set_defaults(fn=cmd_skills)
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
    m.add_argument("--usage", action="store_true", help="which skills, MCP servers, plugins and agents the project really uses, and what each costs at start-up (with --since, --json)")
    m.add_argument("--init-diff", nargs=2, metavar=("BEFORE", "AFTER"), help="check an applied profile: two system/init captures of `claude -p` against --answers")
    m.add_argument("--answers", help="with --init-diff: the review's answers (keep, drop, add per name)")
    m.set_defaults(fn=cmd_metrics)
    t = sub.add_parser("test", help="run every test except the on-demand suites")
    t.add_argument("--mutants", action="store_true", help="run only the on-demand suites (the guard's mutant check)")
    t.set_defaults(fn=cmd_test)
    t = sub.add_parser("toolchain", help="the third-party tools config/toolchain.json pins, installed by mise")
    t.add_argument("--fix", action="store_true", help="install the missing ones at their pinned version; never upgrades what is present")
    t.set_defaults(fn=toolchain.cmd)
    t = sub.add_parser("start", help="start claude with the environment a named launcher of config/forge.json declares")
    t.add_argument("name", nargs="?", help="a key of `launchers`; none lists them")
    t.add_argument("args", nargs=argparse.REMAINDER, help="passed to claude untouched")
    t.set_defaults(fn=launch.cmd)
    t = sub.add_parser("lock", help="record the plugin, outside-skill, GSD and MCP package versions (a dry-run unless --apply)")
    t.add_argument("--apply", action="store_true", help="write config/forge.lock.json")
    t.set_defaults(fn=lockfile.cmd_lock)
    t = sub.add_parser("versions", help="the toolchain pins and the lock together, for release notes")
    t.add_argument("--md", action="store_true", help="markdown tables")
    t.set_defaults(fn=lockfile.cmd_versions)
    g = sub.add_parser("log", help="the change journal: what forge sync --apply and session start wrote")
    g.add_argument("project", nargs="?", help="this project's paths only")
    g.add_argument("--since", help="YYYY-MM-DD, changes from this day")
    g.set_defaults(fn=cmd_log)
    sub.add_parser("session-start", help="the SessionStart hook").set_defaults(fn=cmd_session_start)
    c = sub.add_parser("lint", help="scan for personal data that must not be published")
    mode = c.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="the staged files (pre-commit)")
    mode.add_argument("--all", action="store_true", help="every engine file (CI, the gate)")
    mode.add_argument("--range", help="the commits in A..B, messages and content (pre-push)")
    mode.add_argument("--message", help="a commit message file (commit-msg)")
    c.add_argument("--root", help="scan this other git repository instead of the checkout (its tracked files, forge's lists)")
    c.set_defaults(fn=lambda a: _publish().cmd_lint(a))
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
    i = sub.add_parser("new", help="register a project: its profile, then sync --apply NAME")
    i.add_argument("path", help="the project's directory")
    i.add_argument("--name", help="the profile's name (kebab-case; default: the directory's name)")
    i.add_argument("--writes-tracked-files", action="store_true", help="let forge write files that are tracked in the project")
    i.set_defaults(fn=cmd_new)
    u = sub.add_parser("uninstall", help="take out what forge wrote; a dry-run unless --apply")
    u.add_argument("--apply", action="store_true", help="remove; without it, only show what would go")
    scope = u.add_mutually_exclusive_group()
    scope.add_argument("--integration", choices=lib.INTEGRATIONS, help="only this integration's, once it is off in config/forge.json")
    scope.add_argument("project", nargs="?", help="only this project's, once its profile is frozen or deleted")
    u.set_defaults(fn=lambda a: _uninstall().main(a))
    a = p.parse_args(args)
    return a.fn(a)
