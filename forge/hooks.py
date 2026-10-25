"""User-scope hooks and defaults: ~/.claude/settings.json and ~/.codex/hooks.json.

Every hook forge owns is one USER_HOOKS row, written for Claude Code and, when config/forge.json's
`codex_harness` is true (lib.codex_harness: Codex configured like Claude Code), for Codex from the same
table. The plain defaults (`model` and the like) and the env keys sit beside the rows in one load and
one write of settings.json. With `codex_harness` off, the default, Codex gets no hook from forge (it is
a reviewer, not an orchestrator): write_codex_hooks only takes out the entries forge wrote there. These
files are shared by every session on the machine, so only a run whose scope includes the user files
writes them (lib.context's `globals`)."""
import os
import sys

from forge import lib, owned

ROOT = lib.ROOT
HOME = lib.HOME
USER_SETTINGS = os.path.join(HOME, ".claude", "settings.json")
CODEX_HOOKS = os.path.join(lib.CODEX_HOME, "hooks.json")
HOOK_DIR = os.path.join(ROOT, "hooks")
# Where scripts/sync/sync_gsd_runtime.py puts gsd-core's own hook scripts (gsd-core's place for them).
GSD_HOOK_DIR = os.path.join(lib.HOME, ".claude", "hooks")
SYNC_DIR = os.path.join(ROOT, "scripts", "sync")
HINDSIGHT_DIST = os.path.join(HOME, ".hindsight", "coding-agents", "dist")
CLAUDE, CODEX = "claude", "codex"
BOTH = (CLAUDE, CODEX)

# Every user-scope hook forge's code owns, in one table (config/forge.json's
# `user_hooks` rows follow it, see _split):
#   (event, command, timeout, marker, matcher, targets)
# `targets` says where forge writes the command: CODEX in it is written into ~/.codex/hooks.json only
# while `codex_harness` is true, and with it false names an entry write_codex_hooks takes out of that file
# (see codex_commands).
# `marker` is the substring that says an entry is ours; reconcile() keeps exactly one
# entry per row per event and never touches one without its marker (herdr's, a plugin's).
#
# WHY USER SCOPE, for all of them: hooks in ~/.claude/settings.json fire in EVERY session
# whatever the project dir, and hook arrays concatenate across scopes, so one entry covers
# every project without touching twenty profiles, and a gate cannot be dodged by opening a
# repo that lacks it (D-03). Emitting them from the generator makes the wiring reproducible on
# a fresh machine and survive SessionStart regeneration (D-04). Every command is an ABSOLUTE
# interpreter + path (Linux interpreter rule, AGENT-SYSTEM.md -- relative paths broke
# historically). Scripts that only matter in one project self-gate inside the script.
#
# WHY ~/.codex/hooks.json GETS NONE BY DEFAULT: a Codex used as a reviewer, not as an orchestrator, should
# not be configured like Claude Code. `codex_harness` (config/forge.json, only read with the codex
# integration on) is the switch: true mirrors the rows that list CODEX into the file, false (the default)
# writes none and write_codex_hooks removes exactly those commands, whether the row is on or off, and
# nothing else.
_CODE_ROWS = [
    # ref/ corpus router. one project carries 1,140 files of third-party
    # reference material under ref/ and, measured, had zero automated touchpoints
    # into planning, research, review or coding; it had been read by hand twice in two phases.
    # Segner (Anthropic, "Steering Claude Code"): an "every time X, always Y" rule
    # belongs in a hook, because a stated rule is the first thing to fail under pressure. The
    # script self-gates on infra/ref/ref-index.tsv, so it is inert in every other project.
    ("UserPromptSubmit", "python3 %s/ref_corpus_router.py" % HOOK_DIR, 10,
     "ref_corpus_router.py", None, BOTH),

    # GSD prompt-injection guards, which shipped installed but unwired. one project
    # reads a 32 MB third-party corpus under ref/, routed into context automatically
    # -- someone else's repository entering an agent's context is the exact threat
    # these were written for, and CLAUDE.md had a "prompt-injection posture" heading with no
    # mechanism under it. Segner: a "never do this" needs a deterministic hook,
    # because a prompted rule fails under prompt injection, which is precisely when it is being
    # attacked. Only these two of the twelve gsd-* hook scripts on disk: the other ten
    # re-litigate a decision this project made (workflow-guard and phase-boundary enforce "no
    # edits outside a GSD workflow", which CLAUDE.md's "Ritmo de trabajo" overrules), duplicate
    # the harness (read-guard: Claude Code already refuses Edit without a prior Read), depend on
    # a statusline that is not installed (context-monitor, statusline, update-banner,
    # check-update x2), or guard a rule with no observed violation (validate-commit). Wiring a
    # hook that fires on nothing is how a warning learns to be ignored. Both are ADVISORY
    # (additionalContext, never block, exit 0 on any internal error): a guard that can deadlock
    # the workflow gets disabled the first time it is wrong, and then guards nothing.
    ("PreToolUse", "node %s/gsd-prompt-guard.js" % HOOK_DIR, 10,
     "gsd-prompt-guard.js", "Write|Edit", BOTH),
    ("PostToolUse", "node %s/gsd-read-injection-scanner.js" % HOOK_DIR, 10,
     "gsd-read-injection-scanner.js", "Read", BOTH),

    # GSD output discipline: names the thing, and cuts repetition. The two rules live in
    # ~/.claude/gsd-core/references/mandatory-initial-read.md, imported by the five GSD
    # agents that write documents; that is doctrine competing with everything else in context,
    # and a stated rule fails exactly under pressure, which is when it matters.
    # It measures only the two mechanical failures on the text just written: an identifier
    # with no meaning next to it (`Blocked on D-48.`) and a long sentence repeated in the same
    # document. Whether a paragraph is a reworded copy stays the agent's judgement.
    # Tuned against the real corpus: a first version required `words (D-20)` and flagged 3778
    # sites across 1220 .planning documents, including correct prose like `D-20 capped guest
    # fields at {status, name, vmid}`; counting adjacent content, treating a code span as
    # content and requiring BOTH signals brought it to 728 with 75% of documents clean.
    # Two surfaces, one detector. PostToolUse(Write|Edit) reads the document. Stop reads the
    # reply: the same failure was corrected twice in one session, both
    # times a chat status table with rows `06-07`, `26R001`, `D6-3` -- a surface no Write
    # touches. (A third, a UserPromptSubmit reminder of ~40 tokens on every prompt, was dropped
    # afterwards: the rule stays in the house rules' "Say the thing" section, and reconcile()
    # removes the entry it left in both agents' files.) Stop is post-display
    # (anthropics/claude-code#83229: no pre-emit event, a Stop block cannot retract streamed
    # text). Advisory on documents, exit 0 on any internal error. On chat
    # it blocks, since Stop has no advisory channel -- only on the unambiguous signal (the
    # identifier is the SUBJECT of a line, bullet, heading or cell) and at most once per turn
    # (`stop_hook_active` lets the retry through). Measured over 3597 real assistant messages:
    # 154 would have been cut, 4.3%. Inert outside .planning/.
    ("PostToolUse", "python3 %s/gsd_output_discipline.py" % HOOK_DIR, 10,
     "gsd_output_discipline.py", "Write|Edit", BOTH),
    ("Stop", "python3 %s/gsd_output_discipline.py" % HOOK_DIR, 10,
     "gsd_output_discipline.py", None, BOTH),

    # Omarchy desktop toast on Notification. Claude Code's inputNeededNotifEnabled /
    # agentPushNotifEnabled push to Anthropic's apps; neither reaches the local desktop, so a
    # session waiting for input is invisible unless its window is on screen. The toast's click
    # focuses the exact Hyprland window. Self-gates on `omarchy-notification-send` on PATH and
    # exits 0 on every path.
    ("Notification", "python3 %s/omarchy_notify.py" % HOOK_DIR, 10,
     "omarchy_notify.py", None, (CLAUDE,)),

    # Session sync. A session brings its OWN project's generated config up to date and nothing
    # else; a forge session also the user-scope files (forge/lib.py context). Once
    # four generators sat in forge's and a sibling project's settings, ran in parallel
    # (Claude Code runs a hook group concurrently), and rewrote all 19 projects from whichever of
    # those sessions started -- hot-reloading another project's running sessions. Silent unless it
    # wrote something, never fails the session.
    ("SessionStart", "python3 %s/bin/forge session-start || printf '%%s\\n' "
     "'{\"systemMessage\": \"forge session-start could not run (is python3 on PATH?)\"}'" % ROOT, lib.SESSION_START_TIMEOUT,
     "forge session-start", "startup", (CLAUDE,)),

    # Memory health gate. It sweeps all nineteen profiles in under a second (--hook took 978 and
    # 831 ms, measured), so running it only in forge would cover the machine -- but
    # the failure is discovered working in another project, when the agent does not know
    # something it knew yesterday, so it fires everywhere like its two sisters above. --hook:
    # silent when healthy, always exit 0 so a broken store never blocks a session, and the known
    # backlog (config/memory-known-empty.json) stays quiet too: a warning printed every session
    # stops being read, the exact failure. Marker without the flag, so a changed flag
    # is repaired.
    ("SessionStart", "python3 %s/memory_doctor.py --hook" % SYNC_DIR, 15,
     "memory_doctor.py", None, (CLAUDE,)),

    # Hindsight coding-agents: exactly two hooks, never the package's SessionStart one (see
    # HOOK_WARDS). Asserted with their exact commands so a half-removed or relocated wiring
    # self-heals. The two Claude rows are _PROJECT_CODE_ROWS below. The two Codex ones below are written
    # only with `codex_harness` true; with it false they are what write_codex_hooks takes out of
    # ~/.codex/hooks.json.
    ("UserPromptSubmit", 'node "%s/codex-hook.js"' % HINDSIGHT_DIST, 30,
     "coding-agents", None, (CODEX,)),
    ("Stop", 'node "%s/codex-stop-hook.js"' % HINDSIGHT_DIST, 60,
     "coding-agents", None, (CODEX,)),
]

# gsd-core's own hooks, wired from GSD_HOOK_DIR (the owner's call: GSD with no cap). Every hook its installer
# registers in settings.json, less six: the two forge keeps its own, hardened files of (above), and four each judged
# on its own -- read-guard (Claude Code enforces read-before-edit itself, so the advisory would be noise on every Edit),
# secret-read-guard (a hard block on reading .env files in EVERY project, not gated to GSD ones), check-update and
# update-banner (`forge update` is the update path, and the banner needs GSD's own statusline). Each of these is gated
# by .planning/config.json or by the project being a GSD one (measured: ~22 ms for a node hook and 3 ms for a shell one,
# silent outside a GSD project), so they cost nothing elsewhere. Claude only. (event, script, matcher, timeout).
GSD_CORE_ROWS = [
    ("SessionStart", "gsd-session-state.sh", None, 10),
    ("PostToolUse", "gsd-context-monitor.js", "Bash|Edit|Write|MultiEdit|Agent|Task", 10),
    ("SubagentStop", "gsd-context-monitor.js", None, 10),
    ("Stop", "gsd-context-monitor.js", None, 10),
    ("PreCompact", "gsd-context-monitor.js", None, 10),
    ("PostToolUse", "gsd-graphify-update.sh", "Bash", 5),
    ("PostToolUse", "gsd-phase-boundary.sh", "Write|Edit", 5),
    ("PreToolUse", "gsd-workflow-guard.js", "Bash|Edit|Write|MultiEdit", 120),
    ("PreToolUse", "gsd-worktree-path-guard.js", "Write|Edit|MultiEdit", 120),
    ("PreToolUse", "gsd-agent-isolation-guard.js", "Agent|Task", 120),
    ("PreToolUse", "gsd-write-guard.js", "Write", 120),
    ("PreToolUse", "gsd-validate-commit.sh", "Bash", 120),
    ("FileChanged", "gsd-config-reload.js", "config.json", 8),
]
_CODE_ROWS += [(event, "%s %s/%s" % ("bash" if script.endswith(".sh") else "node", GSD_HOOK_DIR, script), timeout, script, matcher, (CLAUDE,))
               for event, script, matcher, timeout in GSD_CORE_ROWS]

# Rows written per project, never at user scope: one project uses one memory system, so Hindsight's
# Claude hooks go only into the .claude/settings.local.json of a profile that uses Hindsight (its
# `servers` holds hindsight-coding-agents, SCOPES), through skills.write_settings_local, which owns
# them by exact command there. At user scope they fired on every prompt of every project and only
# Hindsight's own config made them inert outside its projects. config/forge.json's `user_hooks` rows
# with `"scope": "hindsight"` join them (_config_rows). Every one of them is also an OFF_HOOKS row, so
# reconcile() takes forge's old user-scope entry out by its exact command.
_PROJECT_CODE_ROWS = [
    ("UserPromptSubmit", 'node "%s/claude-hook.js"' % HINDSIGHT_DIST, 30,
     "coding-agents", None, (CLAUDE,)),
    ("Stop", 'node "%s/claude-stop-hook.js"' % HINDSIGHT_DIST, 60,
     "coding-agents", None, (CLAUDE,)),
]
# A project scope's name (a `user_hooks` row's `scope`, and the integration that gates it) -> whether
# a profile is in it.
SCOPES = {"hindsight": lambda prof: "hindsight-coding-agents" in (prof.get("servers") or [])}

# The integration (lib.INTEGRATIONS) each gated row belongs to, by marker. A row whose integration
# is off is not written, and reconcile() takes out the entries whose command EQUALS the row's, never
# by marker: `coding-agents` is also what Hindsight's own installer writes, and one a person
# installed themselves stays. HOOK_WARDS, by marker, is for retired rows only.
#
# Two more gates, both off unless the JSON true. The three gsd rows are forge's GSD patches (the same
# file names are GSD's own hooks, which its installer writes with its own commands): they are written
# only with `gsd_patches` true as well (lib.gsd_patched), and with it off they are not written and
# not taken out either, an off row going only by forge's exact command and never by file name.
# `house_hooks` gates the two rows that are this machine's own (ROW_HOUSE).
ROW_INTEGRATION = {"gsd-prompt-guard.js": "gsd", "gsd-read-injection-scanner.js": "gsd",
                   "gsd_output_discipline.py": "gsd", "coding-agents": "hindsight", "memory_doctor.py": "hindsight"}
ROW_PATCHED = ("gsd-prompt-guard.js", "gsd-read-injection-scanner.js", "gsd_output_discipline.py") + tuple(
    dict.fromkeys(script for _, script, _, _ in GSD_CORE_ROWS))
ROW_INTEGRATION.update({m: "gsd" for m in ROW_PATCHED})
ROW_HOUSE = ("ref_corpus_router.py", "omarchy_notify.py")


def _row_on(marker):
    """Whether forge's own row with this marker is written."""
    name = ROW_INTEGRATION.get(marker)
    if name and not lib.on(name):
        return False
    if marker in ROW_PATCHED and not lib.gsd_patched():
        return False
    return not (marker in ROW_HOUSE and lib.settings().get("house_hooks") is not True)


def _config_rows(scopes=None):
    """config/forge.json's `user_hooks` as (table row, on) pairs, `<ROOT>` expanded; `on` is False
    only for "on": false. A row that is not an object with the five keys is an exit 1 with a "!"
    line: a half-read row would write a hook that cannot start. `scopes`, a list, gets each row's
    optional `scope`, in order: None for a user-scope row, or a SCOPES name for one written per
    project instead (`"scope": "hindsight"`: only into the settings.local.json of the profiles that
    use Hindsight, see _PROJECT_CODE_ROWS). A scoped row is Claude's alone: forge writes no
    per-project Codex hooks."""
    rows = []
    for i, r in enumerate(lib.settings().get("user_hooks") or []):
        bad = None
        if not isinstance(r, dict):
            bad = "is not an object"
        else:
            for key, kind in (("event", str), ("command", str), ("timeout", int), ("marker", str)):
                if not isinstance(r.get(key), kind) or isinstance(r.get(key), bool):
                    bad = "has no %s %s" % (key, "number" if kind is int else "string")
                    break
            if bad is None and not (r.get("matcher") is None or isinstance(r["matcher"], str)):
                bad = "has a matcher that is neither a string nor null"
            if bad is None and not (isinstance(r.get("agents"), list) and r["agents"] and set(r["agents"]) <= set(BOTH)):
                bad = "has agents that are not a non-empty list of %s" % " and ".join(BOTH)
            if bad is None and r.get("scope") is not None and not (isinstance(r["scope"], str) and r["scope"] in SCOPES):
                bad = "has a scope that is not one of %s" % ", ".join(SCOPES)
            if bad is None and r.get("scope") is not None and r["agents"] != [CLAUDE]:
                bad = 'has a scope and agents other than ["%s"]: codex has no per-project hooks' % CLAUDE
        if bad:
            sys.exit("! config/forge.json user_hooks[%d] %s" % (i, bad))
        rows.append(((r["event"], r["command"].replace("<ROOT>", ROOT), r["timeout"], r["marker"],
                      r["matcher"], tuple(r["agents"])), r.get("on") is not False))
        if scopes is not None:
            scopes.append(r.get("scope"))
    return rows


def _split():
    """(rows to write, rows to take out, project rows): the code's rows, then config/forge.json's
    `user_hooks`, each in its own order; the rows of an off integration and the `"on": false` ones go
    to the second list. The third holds (row, scope, on) for every row written per project, on or
    off; each of those is in the second list too."""
    live, off, project = [], [], []
    for row in _CODE_ROWS:
        (live if _row_on(row[3]) else off).append(row)
    for row in _PROJECT_CODE_ROWS:
        project.append((row, "hindsight", _row_on(row[3])))
    scopes = []
    for (row, on), scope in zip(_config_rows(scopes), scopes):
        if scope:
            project.append((row, scope, on and lib.on(scope)))
        else:
            (live if on else off).append(row)
    off += [row for row, _, _ in project]
    # An off row never takes out what a live row writes with the same command.
    written = {row[1] for row in live}
    return live, [row for row in off if row[1] not in written], project


# Every row written at user scope, every row whose entries reconcile() takes out of the user-scope
# files by exact command, and the rows written per project instead (project_hooks).
USER_HOOKS, OFF_HOOKS, PROJECT_ROWS = _split()
_PER_PROJECT = {row[1] for row, _, _ in PROJECT_ROWS}


def project_hooks(prof):
    """The rows skills.write_settings_local owns in this profile's settings.local.json, as
    (event, command, timeout, marker, matcher, wanted): `wanted` when the row is on and the profile
    is in its scope. One not wanted is taken out of the file by its exact command."""
    return [(event, cmd, timeout, marker, matcher, on and SCOPES[scope](prof))
            for (event, cmd, timeout, marker, matcher, _), scope, on in PROJECT_ROWS]

# Hooks removed from EVERY event on every run. The hindsight package installs a third hook,
# SessionStart, which writes `deferInitialReflect` into the session cache whenever the bank has
# no knowledge pages -- and this bank has none by design (no seed, no survey,
# manageBankConfig false). With it, the FIRST prompt of every session is injected nothing
# (measured 0 bytes on turn 1 against 9,636 on turn 2), and some projects' sessions are often a single
# exchange. It is warded rather than deleted once because `npx
# @vectorize-io/hindsight-coding-agents install claude-code` is also how the package updates,
# and it re-merges all three hooks without a word.
#
# reap_claude_mem_worker.py: the claude-mem schema audit fired on every SessionStart until claude-mem
# was retired. Warded, not just dropped from USER_HOOKS,
# because reconcile() never touches an entry no row owns -- a dropped row would leave the
# old entry firing forever against a script that no longer exists.
#
# CODEX is warded only while `codex_harness` is true (write_codex_hooks): the Codex package's own
# SessionStart entry has the same flaw, and the claude-mem audit fired there too. With it false forge
# takes out nothing it did not write, by exact command.
HOOK_WARDS = {CLAUDE: ("claude-sessionstart-hook.js", "reap_claude_mem_worker.py"),
              CODEX: ("codex-sessionstart-hook.js", "reap_claude_mem_worker.py")}

# Files no Claude session should read, as native permission rules (settings.json permissions.deny),
# so the refusal comes from the harness and not from a hook that can be skipped. Unioned in order
# after whatever deny rules are already there, so one added by hand survives. A Read rule
# refuses Edit, Grep and `cat` of the same path too (measured by T0, docs/archive/designs/hooks-phase-design.md);
# the generators are unaffected, they read these files as subprocesses. `//` is an absolute path,
# `~/` is HOME, and `*` does not cross a slash.
# ~/.hindsight/ is three rules and not Read(~/.hindsight/*): T0 measured that the
# single rule also refused hs/sub/ok.txt ("File is in a directory that is denied by your permission
# settings."), which would have shut coding-agents/ and coding-agents-logs/. These three refuse the
# top-level files (the .json and its .bak, the .token, the .env) and leave subdirectories readable.
# ~/.hindsight/profiles/ holds the daemon's coding-agent.env and its .bak-* copies: a fourth rule takes
# those, and its lock, log and metadata files stay readable.
SECRET_DENY = [
    "Read(/%s/credentials/**)" % ROOT,
    "Read(/%s/config/secrets*)" % ROOT,
    "Read(~/.claude.json*)",
    "Read(~/.hindsight/*.json*)",
    "Read(~/.hindsight/*.token)",
    "Read(~/.hindsight/*.env)",
    "Read(~/.hindsight/profiles/*.env*)",
    "Read(//**/.mcp.json)",
    "Read(//**/.codex/config.toml)",
    # The machine's credential stores, from a frozen project's tracked .claude/settings.json (npm, gh, git,
    # Vercel, Supabase, aws credentials, kube, docker, the two ssh keys it names; same strings), plus
    # ~/.aws/config and the other two default ssh key names. The ssh keys are named and not `id_*`:
    # a glob would refuse id_*.pub too, and known_hosts and config stay readable. Several of these
    # files do not exist on every machine; a rule for an absent file refuses nothing.
    "Read(~/.npmrc)",
    "Read(~/.config/gh/hosts.yml)",
    "Read(~/.git-credentials)",
    "Read(~/.local/share/com.vercel.cli/**)",
    "Read(~/.vercel/auth.json)",
    "Read(~/.supabase/access-token)",
    "Read(~/.aws/credentials)",
    "Read(~/.aws/config)",
    "Read(~/.kube/config)",
    "Read(~/.docker/config.json)",
    "Read(~/.ssh/id_rsa)",
    "Read(~/.ssh/id_ed25519)",
    "Read(~/.ssh/id_ecdsa)",
    "Read(~/.ssh/id_dsa)",
]


def deny_secret_files(s):
    """Union SECRET_DENY into s["permissions"]["deny"]; returns (notes, warnings). A `permissions`
    that is not an object, or a `deny` that is not a list, is left as it is with a "!" line, the way
    `env` is."""
    perms = s.setdefault("permissions", {})
    if not isinstance(perms, dict):
        return [], ["! permissions is not an object, left alone"]
    deny = perms.setdefault("deny", [])
    if not isinstance(deny, list):
        return [], ["! permissions.deny is not a list, left alone"]
    added = [r for r in SECRET_DENY if r not in deny]
    deny.extend(added)
    return (["permissions.deny +%d (secret files)" % len(added)] if added else []), []


def prune_deny(s, prev, now):
    """Take out of s["permissions"]["deny"] each rule forge claimed last run (`prev`) and no longer declares
    (`now`), while the file still holds it as forge wrote it; returns one note, or none. Called only when
    deny_secret_files found `permissions.deny` a list. A rule forge stopped declaring stayed for good, its
    claim forgotten with the next record (found in an attack round); one forge never claimed is the user's."""
    deny = s["permissions"]["deny"]
    gone = [c["at"][2] for c in owned.stale(prev, now) if c["kind"] == "item" and len(c["at"]) == 3
            and c["at"][:2] == ["permissions", "deny"] and c["at"][2] in deny and owned.removable(c, c["at"][2])]
    if not gone:
        return []
    deny[:] = [r for r in deny if r not in gone]
    if not deny:
        del s["permissions"]["deny"]
        if not s["permissions"]:
            del s["permissions"]
    return ["dropped %d permissions.deny rule(s) (forge stopped declaring them)" % len(gone)]


def _hook_list(g):
    return g.get("hooks") if isinstance(g, dict) and isinstance(g.get("hooks"), list) else None


def _well_formed(h):
    """A hook entry reconcile can read: an object whose command, when it has one, is a string."""
    return isinstance(h, dict) and isinstance(h.get("command", ""), str)


def strip_if(hooks, event, groups, ours):
    """Take out of `groups` (hooks[event]) every well-formed entry for which `ours(group, entry)` holds and
    return how many went. A group that only this emptied goes with them, and so does the event key
    when that left it with no group: a list that was empty before, an empty group that was already
    there and a malformed part are not forge's to change, so nothing of them is touched. `hooks` is
    the caller's copy of doc["hooks"] and the caller iterates over a snapshot of it."""
    removed, emptied = 0, []
    for g in groups:
        hl = _hook_list(g)
        if hl is None:
            continue
        kept = [h for h in hl if not (_well_formed(h) and ours(g, h))]
        if len(kept) == len(hl):
            continue
        removed += len(hl) - len(kept)
        g["hooks"] = kept
        if not kept:
            emptied.append(id(g))
    if emptied:
        groups[:] = [g for g in groups if id(g) not in emptied]
    if removed and not groups:
        del hooks[event]
    return removed


def _strip(hooks, event, groups, ours):
    """strip_if for an `ours` that judges the command alone."""
    return strip_if(hooks, event, groups, lambda g, h: ours(h.get("command", "")))


def reconcile(doc, agent):
    """Make doc["hooks"] carry exactly one conforming entry per USER_HOOKS row for `agent`.

    Per row and event: an entry is OURS when its command contains the row's marker. The first
    one whose command, timeout and group matcher all match is kept untouched and every other
    one of ours is dropped (a relocated script, a changed timeout, a duplicate); with none
    conforming, all of ours go and one fresh group is appended. Entries without a marker are
    never touched. Returns one note per change; no notes means the document is unchanged.

    Two lessons from adversarial testing of the Codex mirror are why it is this
    strict. An exact command under the WRONG matcher, or with a superseded timeout, must count
    as stale: comparing commands only inside groups whose matcher already matched left a
    wrong-matcher copy in place and appended a second one on every run -- and for the curfew
    that copy stops the gate for everything its matcher excludes. And a hand-edited or foreign
    file can hold a non-list event or non-dict entries; `.setdefault(event, [])` does not replace
    a non-list value, so iterating a dict's keys crashed the whole run. Malformed parts of the
    events we own are dropped instead: losing an unreadable array beats a traceback that leaves
    every later hook unwired."""
    notes = []
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict):
        if hooks is not None:
            notes.append("hooks reset (was not an object)")
        hooks = doc["hooks"] = {}

    for mark in HOOK_WARDS[agent]:
        for event, groups in list(hooks.items()):
            if not isinstance(groups, list):
                continue
            # A malformed entry carries no mark: not ours, so left here (the pass below drops it
            # from the events we own).
            removed = _strip(hooks, event, groups, lambda c, mark=mark: mark in c)
            if removed:
                notes.append("warded off %d %s (%s)" % (removed, mark, event))

    # Rows that are off (an integration switched off, a user_hooks row with "on": false): the entries
    # holding exactly the row's command go, whatever their matcher, timeout or event. Never by
    # marker -- see ROW_INTEGRATION.
    for _, cmd, _, marker, _, targets in OFF_HOOKS:
        if agent not in targets:
            continue
        for event, groups in list(hooks.items()):
            if not isinstance(groups, list):
                continue
            removed = _strip(hooks, event, groups, lambda c, cmd=cmd: c == cmd)
            if removed:
                notes.append("dropped %d %s (%s: %s)" % (removed, marker, event, "written per project"
                                                         if cmd in _PER_PROJECT else "off in config/forge.json"))

    # A marker's entries belong to this agent's rows with that marker. One on an event where none of
    # those rows lives is a row that was deleted or moved: the pass below only visits events that
    # still have a row, so without this it would fire forever.
    own = {}
    for event, _, _, marker, _, targets in USER_HOOKS:
        if agent in targets:
            own.setdefault(marker, set()).add(event)
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        for marker, events in own.items():
            if event in events:
                continue
            removed = _strip(hooks, event, groups, lambda c, marker=marker: marker in c)
            if removed:
                notes.append("dropped %d %s (%s: no row on this event)" % (removed, marker, event))

    for event, cmd, timeout, marker, matcher, targets in USER_HOOKS:
        if agent not in targets:
            continue
        groups = hooks.get(event)
        malformed = 0
        if not isinstance(groups, list):
            malformed = int(groups is not None)
            groups = hooks[event] = []
        for g in groups:
            hl = _hook_list(g)
            if hl is not None:
                g["hooks"] = [h for h in hl if _well_formed(h)]
                malformed += len(hl) - len(g["hooks"])
        before = len(groups)
        groups[:] = [g for g in groups if _hook_list(g)]
        malformed += before - len(groups)

        keep, drop = None, 0
        for g in groups:
            for h in list(g["hooks"]):
                if marker not in h.get("command", ""):
                    continue
                if (keep is None and h["command"] == cmd and h.get("timeout") == timeout
                        and g.get("matcher") == matcher):
                    keep = h
                    continue
                g["hooks"].remove(h)
                drop += 1
        groups[:] = [g for g in groups if g["hooks"]]

        label = "%s %s%s" % (event, marker, " [%s]" % matcher if matcher else "")
        if keep is None:
            grupo = {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
            if matcher:
                grupo["matcher"] = matcher
            groups.append(grupo)
            notes.append("%s %s" % ("repaired" if drop else "appended", label))
        elif drop:
            notes.append("dropped %d stale %s" % (drop, label))
        if malformed:
            notes.append("dropped %d malformed or empty part(s) of %s" % (malformed, event))
    return notes


def reconcile_owned(doc, agent, file):
    """reconcile(doc, agent), then the ownership record's part (forge/owned.py) for `file`: returns
    (notes, warnings, claims). `claims` is one hook claim per row for `agent`, at [event, matcher, command],
    owner `core` or the row's integration, over the entry reconcile left in place. A claim the previous
    run recorded and no row wants now (the row was deleted from the code) loses its entry when that is
    still exactly what forge wrote; an edited one stays and is named in `warnings`, as is a record that
    cannot be read. An entry forge never claimed is never touched, and with no previous record nothing is
    taken out. The caller records `claims` once the file is written."""
    notes = reconcile(doc, agent)
    prev, warn = owned.previous(file)
    warnings = [warn.strip()] if warn else []
    now = []
    for event, cmd, _, marker, matcher, targets in USER_HOOKS:
        found = owned.hooks_with(doc, event, cmd, matcher) if agent in targets else []
        if found:  # reconcile left exactly the conforming one
            now.append(owned.claim("hook", [event, matcher, cmd], found[0], ROW_INTEGRATION.get(marker, "core")))
    hooks = doc["hooks"]
    for c in owned.stale(prev, now):
        if c["kind"] != "hook" or len(c["at"]) != 3:
            continue
        event, matcher, cmd = c["at"]
        if not owned.hooks_with(doc, event, cmd, matcher):
            continue
        removed = strip_if(hooks, event, hooks[event], lambda g, h: g.get("matcher") == matcher
                           and h.get("command") == cmd and owned.removable(c, h))
        if removed:
            notes.append("dropped %d %s (%s: its row is gone)" % (removed, cmd, event))
        if owned.hooks_with(doc, event, cmd, matcher):
            warnings.append("! %s: %s [%s] was edited, left in place" % (lib.short(file), cmd, event))
    return notes, warnings, now


def _commit(ctx, path, doc, notes, current, warnings=()):
    """Write `doc` once if anything changed, and return the status line for `path`, then one
    "!" line per warning (a value in a shape left alone). A warning alone writes nothing; its
    own line is what forge/cli.py's CHANGED shows at session start, and it exits the run 1
    (forge/sync.py agent_config's rule)."""
    short = lib.short(path)
    if not notes:
        line = "   %s -> %s (already current)" % (short, current)
    else:
        if ctx.apply:
            # An existing file keeps its mode and its .bak gets the same one: ~/.claude/settings.json can hold an
            # env token and was widened from 0600 to the umask default (found in an attack round). A new file
            # is written at the umask default as before.
            lib.write_json(path, doc, mode="keep" if os.path.exists(path) else None, backup=True)
        line = "   %s%s -> %s" % ("" if ctx.apply else "would write ", short, "; ".join(notes))
    return "\n".join([line] + ["   " + w for w in warnings])


def _not_run(what, integration):
    """The status line of a writer whose integration is off."""
    return "   %s -> NOT RUN, NOT ARMED: %s is off in config/forge.json" % (what, integration)


def write_user_settings(ctx):
    """Everything forge owns in ~/.claude/settings.json, in one load and one write.

    Once thirteen functions each loaded and rewrote this file; now the hooks come
    from USER_HOOKS and the plain keys and env from config/forge.json's `user_settings` (what they
    are on this machine, and why, is that file's). lib.read_owned() preserves every other key
    (enabledPlugins, theme, extraKnownMarketplaces, statusLine...).

    MODEL DEFAULTS. A session defaults to Sonnet; Opus is chosen by hand at launch and never
    mid-session, because a model switch re-reads the whole history uncached. The advisor tool is
    disabled with CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1: each advisor call re-reads the full
    transcript uncached (measured $0.15 a consult against $0.05 for the rest of the turn). Both
    sit in config/forge.json's `user_settings`, so user scope reaches every project.

    MEM_NO_AUTO_ADOPT=1. From v3.13 claude-mem-lite writes a slug-scoped managed block into each
    project's own CLAUDE.md -- a committed file -- on EVERY SessionStart, plus a detail file under
    .claude/. forge owns those files across nineteen directories, so that is a generator fighting
    a generator. The variable is the package's own global escape hatch. User scope is the RIGHT
    scope here, not a leak: it must hold in directories forge does not manage too, because the
    block lands in whatever CLAUDE.md the session finds. Written rather than hand-set because
    its absence is silent -- a committed file simply grows a block nobody wrote.

    ENABLE_CLAUDEAI_MCP_SERVERS=false. Every connector on the claude.ai account (15 on
    when measured: Gmail, Drive, Calendar, Claude Docs, Slack, Notion, Figma...) otherwise loads into
    every project, whatever its profile says, and the connected ones bring their tools and
    instructions into context. Nothing here uses them -- the gmail and calendar skills go through
    forge's own `google` server. Measured: honoured from user-scope `env` (one project
    went from 15 claude.ai entries to 0), NOT overridable from a project's settings.local.json
    (user false + project true still gave 0), so it is all-or-nothing and lives here."""
    s = lib.read_owned(USER_SETTINGS)
    wanted = lib.settings().get("user_settings")
    wanted = wanted if isinstance(wanted, dict) else {}
    plain = [(k, v) for k, v in wanted.items() if k != "env"]
    notes = []
    for k, v in plain:
        if s.get(k) != v:
            notes.append("%s %s -> %s" % (k, s.get(k), v))
            s[k] = v
    key_claims = [owned.claim("key", [k], v, "core") for k, v in plain]  # what is written below is claimed with it
    warnings = []
    if isinstance(wanted.get("env"), dict) and wanted["env"]:
        env = s.setdefault("env", {})
        if not isinstance(env, dict):  # hand-edited into a shape Claude Code rejects too: not ours to fix
            warnings.append("! env is not an object, left alone")
        else:
            for k, v in wanted["env"].items():
                if env.get(k) != v:
                    notes.append("env %s=%s" % (k, v))
                    env[k] = v
                key_claims.append(owned.claim("key", ["env", k], v, "core"))
    hook_notes, hook_warnings, claims = reconcile_owned(s, CLAUDE, USER_SETTINGS)
    notes += hook_notes
    warnings += hook_warnings
    deny_notes, deny_warnings = deny_secret_files(s)
    notes += deny_notes
    if not deny_warnings:  # a permissions or deny of the wrong shape was left alone: nothing of ours is in it
        key_claims += [owned.claim("item", ["permissions", "deny", r], r, "core") for r in SECRET_DENY]
        notes += prune_deny(s, owned.previous(USER_SETTINGS)[0], key_claims)
    n = sum(1 for row in USER_HOOKS if CLAUDE in row[5])
    current = ["%s=%s" % kv for kv in plain] + [
        "%d hooks" % n,
        "%s warded off" % ", ".join(HOOK_WARDS[CLAUDE]), "%d secret-read deny rules" % len(SECRET_DENY)]
    line = _commit(ctx, USER_SETTINGS, s, notes, ", ".join(current), warnings + deny_warnings)
    owned.record(USER_SETTINGS, claims + key_claims, ctx.apply)
    return line


def codex_commands():
    """The commands forge ever wrote into ~/.codex/hooks.json: every row of the code's table and every
    `user_hooks` row of config/forge.json that lists codex, whether the row is on or off."""
    rows = list(_CODE_ROWS) + [row for row, _ in _config_rows()]
    return {row[1] for row in rows if CODEX in row[5]}


def drop_codex_entries(doc):
    """Take out of doc["hooks"] every entry whose command EQUALS one of codex_commands(), whatever its
    matcher, timeout or event; returns one note per event changed. A group or an event left empty by it
    goes too. Everything else stays as it is: a foreign entry (one that only shares a script name
    included), a malformed part, another key."""
    notes = []
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict):
        return notes
    ours = codex_commands()
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        removed = _strip(hooks, event, groups, lambda c: c in ours)
        if removed:
            notes.append("dropped %d forge hook(s) (%s)" % (removed, event))
    return notes


def write_codex_hooks(ctx):
    """~/.codex/hooks.json, by config/forge.json's `codex_harness` (lib.codex_harness).

    True: Codex is configured like Claude Code, the USER_HOOKS rows that list CODEX are mirrored into
    the file (reconcile) and HOOK_WARDS[CODEX] is taken out. False, the default: no row is written and
    the entries forge wrote there are taken out (drop_codex_entries), the rest left as it is; a file that
    is absent stays absent, and one with no entry of forge's is not rewritten. Codex off (integrations.codex):
    the switch is not read, the file is not read or written, and the line says so."""
    if not lib.on("codex"):
        return _not_run(lib.short(CODEX_HOOKS), "codex")
    s = lib.read_owned(CODEX_HOOKS)
    if lib.codex_harness():
        n = sum(1 for row in USER_HOOKS if CODEX in row[5])
        notes, warnings, claims = reconcile_owned(s, CODEX, CODEX_HOOKS)
        line = _commit(ctx, CODEX_HOOKS, s, notes, "%d hooks, %s warded off" % (n, ", ".join(HOOK_WARDS[CODEX])), warnings)
        owned.record(CODEX_HOOKS, claims, ctx.apply)
        return line
    line = _commit(ctx, CODEX_HOOKS, s, drop_codex_entries(s), "no hook of forge's")
    if owned.previous(CODEX_HOOKS)[0]:  # the entries those claims name are out: an empty record, never a first one
        owned.record(CODEX_HOOKS, [], ctx.apply)
    return line
