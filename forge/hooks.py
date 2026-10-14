"""User-scope hooks and defaults: ~/.claude/settings.json and ~/.codex/hooks.json.

Every hook forge owns is one USER_HOOKS row, written for both agents from the same table, and
the two plain defaults (model, advisorModel) and the env keys sit beside them in one load and one
write of settings.json. These files are shared by every session on the machine, so only a run
whose scope includes the user files writes them (lib.context's `globals`)."""
import importlib.util
import os
import sys

from forge import lib

ROOT = lib.ROOT
HOME = lib.HOME
USER_SETTINGS = os.path.join(HOME, ".claude", "settings.json")
CODEX_HOOKS = os.path.join(lib.CODEX_HOME, "hooks.json")
HOOK_DIR = os.path.join(ROOT, "hooks")
SYNC_DIR = os.path.join(ROOT, "scripts", "sync")
HINDSIGHT_DIST = os.path.join(HOME, ".hindsight", "coding-agents", "dist")
CLAUDE, CODEX = "claude", "codex"
BOTH = (CLAUDE, CODEX)

# The Jev routers' machine setup (proxy units, base URL, status-line wrap) lives in the skill, so a
# clone of forge can install it without this generator; this one calls the same functions,
# and takes the Jev router's USER_HOOKS row from it.
# Loaded by path, never put on sys.path, and only while the jev integration is on: a checkout
# without skills/jev (config/forge.json integrations.jev false) never reads the file. While on it
# is loaded at import, so a setup.py that does not import fails the run before any project is written.
def _load_jev_setup():
    spec = importlib.util.spec_from_file_location("jev_setup", os.path.join(ROOT, "skills", "jev", "scripts", "setup.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


jev_setup = _load_jev_setup() if lib.on("jev") else None
# The Jev row. Off, setup.py is not loaded, so the row is spelled out here: reconcile() still needs
# its exact command to take forge's own entry out of the files.
JEV_ROW = (("UserPromptSubmit", jev_setup.HOOK_CMD, jev_setup.HOOK_TIMEOUT_S, jev_setup.HOOK_MARKER, None, (CLAUDE,))
           if jev_setup else
           ("UserPromptSubmit", "python3 %s/hooks/jev_router.py" % ROOT, 6, "jev_router.py", None, (CLAUDE,)))

# Every user-scope hook forge's code owns, for both agents, in one table (config/forge.json's
# `user_hooks` rows follow it, see _split):
#   (event, command, timeout, marker, matcher, targets)
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
# WHY ~/.codex/hooks.json GETS THE SAME ROWS (provider independence: not
# locking the whole harness to one AI company). Confirmed portable at the time:
# a project's .codex/hooks/hooks.json and the then-installed Codex plugins (claude-mem, since retired;
# figma, replayio)
# declare "$schema": "https://json.schemastore.org/claude-code-settings.json" and use
# SessionStart, UserPromptSubmit, PreToolUse, PostToolUse and Stop with the exact
# {matcher, hooks:[{type, command, timeout}]} shape, so the rows are shared, not reinvented.
# hooks.json is a dedicated file with no other keys. Claude-only rows say why below; the
# Notification event in particular stays off Codex: no plugin or project here was found using
# it, and an unsupported top-level key risked breaking hooks.json parsing. Confirm first.
_CODE_ROWS = [
    # Caveman house rules. The caveman plugin reads its ruleset from its OWN SKILL.md inside
    # the plugin cache and has no extension point (its config takes `defaultMode` only), so
    # the house additions -- no bureaucracy, never ask for approval by bare identifier -- are a
    # second SessionStart context block instead of a patch to a cache dir that
    # `/plugin update caveman` would silently revert.
    ("SessionStart", "python3 %s/caveman_house_rules.py" % HOOK_DIR, 5,
     "caveman_house_rules.py", None, BOTH),

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
    # ~/.claude/get-shit-done/references/mandatory-initial-read.md, imported by the five GSD
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

    # Caveman level persistence. The plugin treats a level as session state, and the default
    # is pinned per project in the profile env (CAVEMAN_DEFAULT_MODE), so a level the user
    # switched to would silently revert. The script writes it back to the owning profile AND
    # that project's settings.local.json -- both, because Claude Code reads env at session init,
    # before any SessionStart hook, so a generator-only update lands a session late. It does
    # nothing unless the prompt is an explicit /caveman command in a directory a profile owns.
    # Node, to reuse the plugin's own caveman-parse.js instead of re-implementing the grammar.
    ("UserPromptSubmit", "node %s/caveman_persist_level.js" % HOOK_DIR, 10,
     "caveman_persist_level.js", None, BOTH),

    # Omarchy desktop toast on Notification. Claude Code's inputNeededNotifEnabled /
    # agentPushNotifEnabled push to Anthropic's apps; neither reaches the local desktop, so a
    # session waiting for input is invisible unless its window is on screen. The toast's click
    # focuses the exact Hyprland window. Self-gates on `omarchy-notification-send` on PATH and
    # exits 0 on every path. Claude only: see the Notification note above.
    ("Notification", "python3 %s/omarchy_notify.py" % HOOK_DIR, 10,
     "omarchy_notify.py", None, (CLAUDE,)),

    # Jev router. Jev (TypeSafe's System One model, ~0.4 s and a fraction of a cent a prompt)
    # picks which enabled skill fits each prompt instead of Claude guessing from a truncated
    # listing, and the hook injects that one line. On a session's first prompt the same call
    # also picks Sonnet or Opus, which jev-proxy applies (write_jev_proxy): a hook cannot switch
    # the model itself (UserPromptSubmit has no model field, verified on 2.1.280). Fails open:
    # no key, `router off`, or a Jev call over 2 s leaves the prompt untouched and the session
    # on Sonnet. Timeout 6 s covers two calls. Claude only: Codex does not need the feature
    # (by decision).
    JEV_ROW,

    # Session sync. A session brings its OWN project's generated config up to date and nothing
    # else; a forge session also the user-scope files (forge/lib.py context). Once
    # four generators sat in forge's and a sibling project's settings, ran in parallel
    # (Claude Code runs a hook group concurrently), and rewrote all 19 projects from whichever of
    # those sessions started -- hot-reloading another project's running sessions. Silent unless it
    # wrote something, never fails the session. Claude only: Codex hooks carry no
    # CLAUDE_PROJECT_DIR, and a session there would sync everything.
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

    # Hindsight coding-agents: exactly two hooks per agent, never the package's SessionStart one
    # (see HOOK_WARDS). Asserted with their exact commands so a half-removed or relocated wiring
    # self-heals. THE SAME TWO FOR CODEX: the runtime ships codex-sessionstart-hook.js,
    # codex-hook.js and codex-stop-hook.js and nothing here registered them. They are the SAME
    # CODE as the Claude bundles with one string changed -- codex-hook.js differs from
    # claude-hook.js in 43 bytes of 134,560, all `runHarnessPrompt("codex")` -- and
    # `deferInitialReflect` appears four times in both sessionstart bundles, so the ban applies
    # unchanged. Codex takes the Claude manifest verbatim (harness configStyle "nested", same event
    # names, codexPrompt spreads claudePrompt and emits the same additionalContext; only the
    # payload parse differs, inside the bundle). Forge writes them rather than
    # `npx @vectorize-io/hindsight-coding-agents install codex`, because that installer merges into
    # hooks.json and rewrites ~/.codex/config.toml (installer.js:4517-4545), both generated here.
    # Codex gates hooks behind a persisted trust hash: a new entry fires only once trusted.
    ("UserPromptSubmit", 'node "%s/claude-hook.js"' % HINDSIGHT_DIST, 30,
     "coding-agents", None, (CLAUDE,)),
    ("Stop", 'node "%s/claude-stop-hook.js"' % HINDSIGHT_DIST, 60,
     "coding-agents", None, (CLAUDE,)),
    ("UserPromptSubmit", 'node "%s/codex-hook.js"' % HINDSIGHT_DIST, 30,
     "coding-agents", None, (CODEX,)),
    ("Stop", 'node "%s/codex-stop-hook.js"' % HINDSIGHT_DIST, 60,
     "coding-agents", None, (CODEX,)),
]

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
ROW_INTEGRATION = {"caveman_house_rules.py": "caveman", "caveman_persist_level.js": "caveman",
                   "gsd-prompt-guard.js": "gsd", "gsd-read-injection-scanner.js": "gsd",
                   "gsd_output_discipline.py": "gsd", "jev_router.py": "jev", "coding-agents": "hindsight",
                   "memory_doctor.py": "hindsight"}
ROW_PATCHED = ("gsd-prompt-guard.js", "gsd-read-injection-scanner.js", "gsd_output_discipline.py")
ROW_HOUSE = ("ref_corpus_router.py", "omarchy_notify.py")


def _row_on(marker):
    """Whether forge's own row with this marker is written."""
    name = ROW_INTEGRATION.get(marker)
    if name and not lib.on(name):
        return False
    if marker in ROW_PATCHED and not lib.gsd_patched():
        return False
    return not (marker in ROW_HOUSE and lib.settings().get("house_hooks") is not True)


def _config_rows():
    """config/forge.json's `user_hooks` as (table row, on) pairs, `<ROOT>` expanded; `on` is False
    only for "on": false. A row that is not an object with the five keys is an exit 1 with a "!"
    line: a half-read row would write a hook that cannot start."""
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
        if bad:
            sys.exit("! config/forge.json user_hooks[%d] %s" % (i, bad))
        rows.append(((r["event"], r["command"].replace("<ROOT>", ROOT), r["timeout"], r["marker"],
                      r["matcher"], tuple(r["agents"])), r.get("on") is not False))
    return rows


def _split():
    """(rows to write, rows to take out): the code's rows, then config/forge.json's `user_hooks`,
    each in its own order; the rows of an off integration and the `"on": false` ones go to the
    second list."""
    live, off = [], []
    for row in _CODE_ROWS:
        (live if _row_on(row[3]) else off).append(row)
    for row, on in _config_rows():
        (live if on else off).append(row)
    # An off row never takes out what a live row writes with the same command.
    written = {row[1] for row in live}
    return live, [row for row in off if row[1] not in written]


# Every row written, and every row whose entries reconcile() takes out by exact command.
USER_HOOKS, OFF_HOOKS = _split()

# Hooks removed from EVERY event on every run. The hindsight package installs a third hook,
# SessionStart, which writes `deferInitialReflect` into the session cache whenever the bank has
# no knowledge pages -- and this bank has none by design (no seed, no survey,
# manageBankConfig false). With it, the FIRST prompt of every session is injected nothing
# (measured 0 bytes on turn 1 against 9,636 on turn 2), and some projects' sessions are often a single
# exchange. It is warded rather than deleted once because `npx
# @vectorize-io/hindsight-coding-agents install claude-code` is also how the package updates,
# and it re-merges all three hooks without a word.
#
# reap_claude_mem_worker.py: the claude-mem schema audit fired on every SessionStart of both
# agents until claude-mem was retired. Warded, not just dropped from USER_HOOKS,
# because reconcile() never touches an entry no row owns -- a dropped row would leave the
# old entry firing forever against a script that no longer exists.
HOOK_WARDS = {CLAUDE: ("claude-sessionstart-hook.js", "reap_claude_mem_worker.py"),
              CODEX: ("codex-sessionstart-hook.js", "reap_claude_mem_worker.py")}

# Files no Claude session should read, as native permission rules (settings.json permissions.deny),
# so the refusal comes from the harness and not from a hook that can be skipped. Unioned in order
# after whatever deny rules are already there, so one added by hand survives. A Read rule
# refuses Edit, Grep and `cat` of the same path too (measured by T0, docs/hooks-phase-design.md);
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


def _hook_list(g):
    return g.get("hooks") if isinstance(g, dict) and isinstance(g.get("hooks"), list) else None


def _well_formed(h):
    """A hook entry reconcile can read: an object whose command, when it has one, is a string."""
    return isinstance(h, dict) and isinstance(h.get("command", ""), str)


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
            removed = 0
            for g in groups:
                hl = _hook_list(g)
                if hl is None:
                    continue
                # A malformed entry carries no mark: not ours, so left here (the pass below drops it
                # from the events we own).
                kept = [h for h in hl if not (_well_formed(h) and mark in h.get("command", ""))]
                removed += len(hl) - len(kept)
                g["hooks"] = kept
            if removed:
                groups[:] = [g for g in groups if _hook_list(g) != []]
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
            removed = 0
            for g in groups:
                hl = _hook_list(g)
                if hl is None:
                    continue
                kept = [h for h in hl if not (_well_formed(h) and h.get("command") == cmd)]
                removed += len(hl) - len(kept)
                g["hooks"] = kept
            if removed:
                groups[:] = [g for g in groups if _hook_list(g) != []]
                notes.append("dropped %d %s (%s: off in config/forge.json)" % (removed, marker, event))

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
            removed = 0
            for g in groups:
                hl = _hook_list(g)
                if hl is None:
                    continue
                kept = [h for h in hl if not (_well_formed(h) and marker in h.get("command", ""))]
                removed += len(hl) - len(kept)
                g["hooks"] = kept
            if removed:
                groups[:] = [g for g in groups if _hook_list(g) != []]
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
            lib.write_json(path, doc, backup=True)
        line = "   %s%s -> %s" % ("" if ctx.apply else "would write ", short, "; ".join(notes))
    return "\n".join([line] + ["   " + w for w in warnings])


def _not_run(what, integration):
    """The status line of a writer whose integration is off. Jev's says how a machine that had it on
    undoes it: a base URL left pointing at a stopped proxy would break every session."""
    line = "   %s -> NOT RUN, NOT ARMED: %s is off in config/forge.json" % (what, integration)
    if integration == "jev":
        line += " (a machine that had it on runs skills/jev/scripts/setup.py --uninstall --apply)"
    return line


def write_jev_proxy(ctx):
    """Install and start jev-proxy (skills/jev/scripts/setup.py); returns (status line(s), listening).

    The proxy (skills/jev/scripts/routerd.py) is how a session gets the model Jev chose for its
    first prompt: every request goes through it and it rewrites `model`, since nothing inside a
    session can. That puts it in the path of every Claude Code request, so write_user_settings()
    only points ANTHROPIC_BASE_URL at it while the port accepts a connection, and takes the
    variable back out otherwise -- a stopped proxy costs routing, never a working session.

    Jev off (config/forge.json integrations.jev): nothing runs, and the line says so."""
    if jev_setup is None:
        return _not_run("jev-proxy", "jev"), False
    return jev_setup.install_units(ctx.apply)


def write_jev_status_extension(ctx):
    """Symlink the Jev status-bar extension into every VS Code-family host on this machine
    (skills/jev/scripts/setup.py's install_extension) so the terminal's model/skill visibility
    also reaches the graphical VS Code and Antigravity panels, which have no statusLine."""
    if jev_setup is None:
        return _not_run("jev-status extension", "jev")
    return jev_setup.install_extension(ctx.apply)


def write_user_settings(ctx, proxy_up):
    """Everything forge owns in ~/.claude/settings.json, in one load and one write.

    Once thirteen functions each loaded and rewrote this file; now the hooks come
    from USER_HOOKS and the plain keys and env from config/forge.json's `user_settings` (what they
    are on this machine, and why, is that file's). lib.read_owned() preserves every other key
    (enabledPlugins, theme, extraKnownMarketplaces, statusLine...).

    MODEL DEFAULTS. The goal is a cheaper Claude that stays as good. On this
    account (a Team seat on the Max 5x tier) "cheaper" means the 5-hour and weekly limits last
    longer, and Opus spends them far faster than Sonnet. Claude Code 2.1.280 ships a server-side
    advisor (`advisorModel`, `/advisor`, `--advisor`): the session model does the work and
    consults the stronger one at key moments. Measured with sonnet + advisor opus: it
    works from the settings keys alone, and one consult cost $0.15 against $0.05 for the rest of
    the turn, because the advisor reads the whole context uncached -- so nothing nudges Claude to
    consult it; it stays Sonnet's own call. Opus 5.5 is preferred over Fable as the advisor.
    Sonnet is what a session gets unless Jev sends its first prompt to Opus (write_jev_proxy):
    router off, a short or slash first prompt, Jev failing, the proxy down. No project sets either key,
    so user scope reaches all of them. Before this, `model: opus` was hand-set and unowned.

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
    if isinstance(wanted.get("env"), dict) and wanted["env"]:
        env = s.setdefault("env", {})
        if isinstance(env, dict):  # one that is not is left alone, and settings_changes() says so
            for k, v in wanted["env"].items():
                if env.get(k) != v:
                    notes.append("env %s=%s" % (k, v))
                    env[k] = v
    changes, warnings = jev_setup.settings_changes(s, proxy_up) if jev_setup else ([], [])
    notes += changes
    notes += reconcile(s, CLAUDE)
    deny_notes, deny_warnings = deny_secret_files(s)
    notes += deny_notes
    n = sum(1 for row in USER_HOOKS if CLAUDE in row[5])
    current = ["%s=%s" % kv for kv in plain] + [
        "via jev-proxy" if proxy_up else "direct to Anthropic", "%d hooks" % n,
        "%s warded off" % ", ".join(HOOK_WARDS[CLAUDE]), "%d secret-read deny rules" % len(SECRET_DENY)]
    return _commit(ctx, USER_SETTINGS, s, notes, ", ".join(current), list(warnings) + deny_warnings)


def write_codex_hooks(ctx):
    """Mirror the shared USER_HOOKS rows into ~/.codex/hooks.json (see the table's header). Codex
    off (config/forge.json integrations.codex): the file is not read or written, and the line says so."""
    if not lib.on("codex"):
        return _not_run(lib.short(CODEX_HOOKS), "codex")
    s = lib.read_owned(CODEX_HOOKS)
    notes = reconcile(s, CODEX)
    n = sum(1 for row in USER_HOOKS if CODEX in row[5])
    return _commit(ctx, CODEX_HOOKS, s, notes, "%d hooks, %s warded off" % (n, ", ".join(HOOK_WARDS[CODEX])))
