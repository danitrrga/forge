#!/usr/bin/env python3
"""hooks/hooks.json, hooks/subagent_context.py and data/context-base.tsv (2.5 U3): the plugin's SubagentStart hook, which
reads the phase's base-context file (the one writer is `fwx context-base build`, U2) and hands it to the agent that starts,
by the table of cases (Apéndice C of plan/2.5-contexto-base.md), and never writes.

Not covered here: the live run with Claude Code and Haiku (it is in the PR; the transcript is its evidence, not the model's
answer), the wiring in `new-phase` and `stage` (U4), the audit (U5).

Also here, because the hook is where it shows: `## Decided` leaves out a row that a closed row superseded (lib/fwx/context_base.py).

Seen red before the code existed (no hooks/, no data/context-base.tsv):
  FAIL: data/context-base.tsv: the table of cases is there: ... is not there
  FAIL: hooks/hooks.json is valid JSON: [Errno 2] No such file or directory

Controls, each seen red on a copy of the repo with one thing changed (first FAIL lines; 246 checks on the good code):
  - the hook ignores the table and delivers everything (41 FAIL):
      FAIL: fwx:reviewer received a decided row            (and fwx:pre-mortem: the text up to `## Decided`: got ...)
  - a `none` row delivers (15 FAIL):
      FAIL: fwx:decisions: nothing is written: got '{"hookSpecificOutput": ...
  - the hook takes the first open phase:
      FAIL: two open phases and none bound: injected with 2 open phases: got (0, '{"hookSpecificOutput": ...
  - the hook finds no base from a worktree:
      FAIL: fwx:planner from a worktree: the same bytes (no base found from worktree): got '', want '{"hookSpecificOutput": ...
  - no cap in the hook / the cap in bytes / the cap in code points:
      FAIL: a file of 9501 units: exit 1, nothing on stdout: got (0, '{"hookSpecificOutput": ...
      FAIL: a file of 9500 units is delivered: got (1, 'context-base: 9501 units over the cap\n', 0), want (0, '', 9500)   [bytes]
      FAIL: 4,800 emoji (4,800 code points, 9,600 units): exit 1, the cap is not in code points: got 0, want 1   [code points]
  - --file ignores the repository of the cwd:
      FAIL: --file with a cwd of another repository: empty, exit 0: got (0, '{"hookSpecificOutput": ...
  - the table needs no `*` row (sections_for, U2's code):
      FAIL: ... no default row: context-base: KeyError: '*'
  - `## Decided` takes superseded rows / any row supersedes, an open one too:
      FAIL: a superseded decision is not in Decided: OLDCHOICE-postgres: ## Decided ...
      FAIL: a decision superseded only by an open row stays closed: KEPT-redis: ## Decided ...
  - hooks.json with another matcher / another timeout:
      FAIL: hooks.json: the matcher is `*` (...): got '^fwx:', want '*'
      FAIL: hooks.json: the timeout is 10: got 60, want 10
  - a failure exits 0 (15 FAIL) / an unexpected exception is swallowed:
      FAIL: a file of 9501 units: exit 1, nothing on stdout: got (0, ''), want (1, '')
      FAIL: an input whose cwd is a list (a TypeError nobody planned for): exit 1, nothing on stdout: got (0, ''), want (1, '')
  - the TSV row of the reviewer says map+decided / the row of Explore says map:
      FAIL: data/context-base.tsv: says what the Apéndice C says, a row per type: got {'*': 'map', ...
  - --source is not checked:
      FAIL: --file --source: the source changed since the seal: exit 1, nothing delivered: got (0, '{"hookSpecificOutput": ...
  - the session id is not read (two open phases, the bound one is never found):
      FAIL: two open phases and none bound: injected with 2 open phases ...   (7 FAIL)
  - the hook writes (next to the base file / next to the --file file):
      FAIL: the hook wrote nothing in the repository or the common dir: got ({'/tmp/fwx-toy-.../README': ...
      FAIL: --file wrote nothing either: got ({'/tmp/fwx-toy-.../hand.md.x': ...
The live run (control 7 of the plan) is not in this file: it needs Claude Code and a login. Its script is
$XDG_CACHE_HOME/fwx-measure/context-base-u3/live.py and its transcript evidence is in the commit message and the PR.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
from fwx import context_base as cb  # noqa: E402
from fwx import state  # noqa: E402

HOOK = os.path.join(ROOT, "hooks", "subagent_context.py")
HOOKS_JSON = os.path.join(ROOT, "hooks", "hooks.json")
TABLE = os.path.join(ROOT, "data", "context-base.tsv")
SCRATCH = helpers.mkdtemp("fwx-sc-")

# The table of cases, written out here from the Apéndice C and not read from the TSV: the TSV must say exactly this.
MAP_DECIDED = ("fwx:planner", "fwx:executor")
INDEPENDENT = ("fwx:pre-mortem", "fwx:post-mortem", "fwx:reviewer", "fwx:security-reviewer")
THINKERS = ("fwx:researcher", "fwx:state", "fwx:skill-proposer", "fwx:intake")
NARROW = ("fwx:decisions", "fwx:demo", "fwx:vision", "fwx:detector", "fwx:classifier", "fwx:ui-walker", "fwx:ui-verifier",
          "fwx:review-verifier", "fwx:analytics-verifier")
BUILT_IN_NONE = ("Explore", "claude-code-guide", "statusline-setup", "fork")
BUILT_IN_MAP = ("Plan", "general-purpose", "claude", "workflow-subagent")
EXPECT = {}
EXPECT.update({a: "map+decided" for a in MAP_DECIDED})
EXPECT.update({a: "map" for a in INDEPENDENT + THINKERS + BUILT_IN_MAP})
EXPECT.update({a: "none" for a in NARROW + BUILT_IN_NONE})
EXPECT["*"] = "map"

MAP_WORD = "MAPWORD-quokka"
DECIDED_WORD = "DECIDEDWORD-zebrafinch"
OPEN_WORD = "OPENWORD-unclosed"
CONTEXT = "# Context: 01-alpha\n\n## Intent\nMake the toy work.\n\n## What success means\nThe toy works.\n\n## Surfaces\nnone\n"
TOY_MAP = "fwx is a framework. %s\nUse `fwx state` and `fwx stage` to move.\n" % MAP_WORD
toy_map = helpers.write(SCRATCH, "toy-map.md", TOY_MAP)


def run(cwd, agent_type, session="toy-session", root=ROOT, args=(), env=None, raw=None):
    """The hook of `root`, run in `cwd` with a SubagentStart input; the CompletedProcess."""
    payload = raw if raw is not None else json.dumps({"hook_event_name": "SubagentStart", "agent_type": agent_type,
                                                       "session_id": session, "agent_id": "a1", "cwd": cwd})
    return subprocess.run([sys.executable, os.path.join(root, "hooks", "subagent_context.py")] + list(args), input=payload,
                          cwd=cwd, env=helpers.clean_env(**(env or {})), capture_output=True, text=True)


def delivered(r):
    """The additionalContext a finished hook printed, '' for no output; None when the output is not a SubagentStart output."""
    if not r.stdout.strip():
        return ""
    try:
        out = json.loads(r.stdout)["hookSpecificOutput"]
    except (ValueError, KeyError, TypeError):
        return None
    return out["additionalContext"] if out.get("hookEventName") == "SubagentStart" else None


def phase(repo=None, decisions=True):
    """A toy repo with one phase whose base is built from the toy map; (repo, folder, base text)."""
    repo = repo or helpers.toy_repo()
    d = str(state.new_phase("alpha", cwd=repo))
    helpers.write(d, "context.md", CONTEXT)
    if decisions:
        dec = os.path.join(d, "decisions.tsv")
        state.append_decision(dec, decision=DECIDED_WORD, why="because", support="chosen")
        state.append_decision(dec, decision=OPEN_WORD, why="because", support="agent-assumption")
    r = helpers.fwx(repo, "context-base", "build", d, "--map", toy_map)
    s.eq("the toy base builds", r.returncode, 0)
    with open(cb.base_path(d), encoding="utf-8") as f:
        return repo, d, f.read()


def copy_plugin(name, table=None, hook_patch=None):
    """A copy of this plugin's hook, lib and data in the scratch dir (the plugin root is derived from the script's own path),
    with `table` as data/context-base.tsv and `hook_patch(text)` applied to the script."""
    dest = os.path.join(SCRATCH, name)
    for part in ("hooks", "lib", "data"):
        shutil.copytree(os.path.join(ROOT, part), os.path.join(dest, part), ignore=shutil.ignore_patterns("__pycache__"))
    if table is not None:
        with open(os.path.join(dest, "data", "context-base.tsv"), "w", encoding="utf-8") as f:
            f.write(table)
    if hook_patch:
        p = os.path.join(dest, "hooks", "subagent_context.py")
        with open(p, encoding="utf-8") as f:
            text = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(hook_patch(text))
    return dest


def table_rows():
    with open(TABLE, encoding="utf-8") as f:
        lines = f.read().split("\n")
    return [l.split("\t") for l in lines[1:] if l], lines[0]


# ---- the files the plugin ships -----------------------------------------------------------------------------------
try:
    with open(HOOKS_JSON, encoding="utf-8") as f:
        hooks = json.load(f)
    s.ok("hooks/hooks.json is valid JSON", True)
except (OSError, ValueError) as e:
    hooks = {}
    s.ok("hooks/hooks.json is valid JSON", False, str(e))
rows = (hooks.get("hooks") or {}).get("SubagentStart") or []
s.eq("hooks.json: one SubagentStart entry", len(rows), 1)
entry = rows[0] if rows else {}
s.eq("hooks.json: the matcher is `*` (it fires for general-purpose, workflow-subagent and plugin agents, measured)",
     entry.get("matcher"), "*")
cmds = entry.get("hooks") or [{}]
s.eq("hooks.json: one command hook", [c.get("type") for c in cmds], ["command"])
s.eq("hooks.json: the command", cmds[0].get("command"), "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/subagent_context.py")
s.eq("hooks.json: the timeout is 10", cmds[0].get("timeout"), 10)
s.eq("hooks.json: nothing else is hooked", sorted(hooks.get("hooks") or {}), ["SubagentStart"])

# ---- the table: one row per type, the default row, and exactly the cases of the Apéndice C ----------------------------
try:
    trows, header = table_rows()
except OSError as e:
    trows, header = [], ""
    s.ok("data/context-base.tsv: the table of cases is there", False, str(e))
s.eq("data/context-base.tsv: the header", header, "agent_type\tsections\twhy")
s.ok("data/context-base.tsv: every row has three cells and a reason", all(len(r) == 3 and r[2].strip() for r in trows),
     str([r for r in trows if len(r) != 3 or not r[2].strip()]))
s.eq("data/context-base.tsv: no type twice", len({r[0] for r in trows}), len(trows))
s.eq("data/context-base.tsv: says what the Apéndice C says, a row per type", {r[0]: r[1] for r in trows}, EXPECT)


def sections(t):
    try:
        return cb.sections_for(t)
    except cb.ContextBaseError as e:
        return "error: %s" % e


for t in list(EXPECT):
    s.eq("sections_for(%s)" % t, sections(t), EXPECT[t])
s.eq("sections_for: a type with no row gets the default row", sections("some-project-agent"), "map")
s.eq("sections_for: a prefix is not a match", sections("fwx:planner-2"), "map")

# ---- one case per row of the table, in a toy world --------------------------------------------------------------------
repo, folder, base = phase()
s.ok("the toy base has the map word, the decided word, and not the open one",
     MAP_WORD in base and DECIDED_WORD in base and OPEN_WORD not in base, base)
head = base[:base.index("## Decided\n")]
s.ok("the toy base: the head holds the goal and no decision", "## Goal" in head and DECIDED_WORD not in head and "## Decided" not in head)
for agent in list(EXPECT) + ["projagent"]:
    sections = EXPECT.get(agent, EXPECT["*"])
    r = run(repo, agent)
    got = delivered(r)
    s.eq("%s (%s): exit 0, no stderr" % (agent, sections), (r.returncode, r.stderr), (0, ""))
    if sections == "none":
        s.eq("%s: nothing is written" % agent, r.stdout, "")
    elif sections == "map":
        s.eq("%s: the text up to `## Decided`" % agent, got, head)
        s.ok("%s received a decided row" % agent, DECIDED_WORD not in (got or "") and "## Decided" not in (got or ""))
    else:
        s.eq("%s: the whole file" % agent, got, base)
        s.ok("%s: the decided row is there" % agent, DECIDED_WORD in (got or ""))
    if sections != "none":
        s.ok("%s: the first line is the mark the audit looks for" % agent, (got or "").split("\n", 1)[0].startswith(cb.MARK))
        s.eq("%s: the output is a SubagentStart hookSpecificOutput" % agent, got is not None and bool(got), True)

# The four independence roles never see `## Decided`, whatever the table or the file say (a test of its own).
for agent in INDEPENDENT:
    got = delivered(run(repo, agent)) or ""
    s.ok("%s received a decided row" % agent, DECIDED_WORD not in got and "## Decided" not in got and "closed decisions" not in got)
    s.ok("%s still got the map" % agent, MAP_WORD in got)
repo_m, folder_m, base_m = phase(repo=helpers.toy_repo(), decisions=False)
for i in range(40):
    state.append_decision(os.path.join(folder_m, "decisions.tsv"), decision="%s %d %s" % (DECIDED_WORD, i, "z" * 100),
                          why="w", support="chosen")
r = helpers.fwx(repo_m, "context-base", "build", folder_m, "--map", toy_map)
s.eq("a base with 40 long decisions builds", r.returncode, 0)
for agent in INDEPENDENT:
    got = delivered(run(repo_m, agent)) or ""
    s.ok("%s received a decided row (the count line included)" % agent, DECIDED_WORD not in got and "closed decisions" not in got)
s.ok("the planner gets the count line", "40 closed decisions" in (delivered(run(repo_m, "fwx:planner")) or ""))

# ---- `## Decided` leaves out what a closed row superseded -------------------------------------------------------------
repo_s, folder_s, _ = phase(decisions=False)
dec = os.path.join(folder_s, "decisions.tsv")
state.append_decision(dec, decision="OLDCHOICE-postgres", why="w", support="chosen")                       # D1, replaced by D2
state.append_decision(dec, decision="NEWCHOICE-sqlite", why="w", support="approved", supersedes="D1")      # D2
state.append_decision(dec, decision="KEPT-redis", why="w", support="chosen")                               # D3, replaced only by an open row
state.append_decision(dec, decision="GUESS-memcached", why="w", support="agent-assumption", supersedes="D3")  # D4
state.append_decision(dec, decision="MID-v1", why="w", support="chosen")                                   # D5 -> D6 -> D7
state.append_decision(dec, decision="MID-v2", why="w", support="chosen", supersedes="D5")                  # D6
state.append_decision(dec, decision="MID-v3", why="w", support="chosen", supersedes="D6")                  # D7
helpers.fwx(repo_s, "context-base", "build", folder_s, "--map", toy_map)
got = delivered(run(repo_s, "fwx:planner")) or ""
decided = got[got.index("## Decided"):] if "## Decided" in got else ""
s.ok("a superseded decision is not in Decided: OLDCHOICE-postgres", "OLDCHOICE-postgres" not in decided, decided)
s.ok("the decision that replaced it is: NEWCHOICE-sqlite", "NEWCHOICE-sqlite" in decided, decided)
s.ok("a decision superseded only by an open row stays closed: KEPT-redis", "KEPT-redis" in decided, decided)
s.ok("the open row that tried to replace it does not enter: GUESS-memcached", "GUESS-memcached" not in decided, decided)
s.ok("a chain of three shows the last one only", "MID-v3" in decided and "MID-v1" not in decided and "MID-v2" not in decided, decided)
s.eq("Decided lists three lines", [l for l in decided.splitlines() if l.startswith("- ")],
     ["- NEWCHOICE-sqlite", "- KEPT-redis", "- MID-v3"])
# a replaced row does not count towards the 40-row count line either
repo_c, folder_c, _ = phase(decisions=False)
for i in range(20):
    state.append_decision(os.path.join(folder_c, "decisions.tsv"), decision="OLD %d %s" % (i, "q" * 100), why="w", support="chosen")
for i in range(20):
    state.append_decision(os.path.join(folder_c, "decisions.tsv"), decision="NEW %d" % i, why="w", support="chosen", supersedes="D%d" % (i + 1))
helpers.fwx(repo_c, "context-base", "build", folder_c, "--map", toy_map)
got = delivered(run(repo_c, "fwx:planner")) or ""
s.ok("20 long rows replaced by 20 short ones: listed one by one, no count line",
     "closed decisions" not in got and "OLD 0 " not in got and "NEW 19" in got, got[got.find("## Decided"):])

# ---- no phase, several phases, no framework, no file: nothing, and exit 0 -----------------------------------------------
bare = helpers.toy_repo()
r = run(bare, "fwx:planner")
s.eq("plugin on, no phase open (no .fwx at all): empty, exit 0", (r.returncode, r.stdout, r.stderr), (0, "", ""))
os.makedirs(os.path.join(bare, ".fwx", "milestones", "v1", "phases"))
r = run(bare, "fwx:planner")
s.eq("plugin on, .fwx with no phase: empty, exit 0", (r.returncode, r.stdout, r.stderr), (0, "", ""))
outside = helpers.mkdtemp("fwx-outside-")
r = run(outside, "fwx:planner")
s.eq("a folder that is no repository (a project without the framework): empty, exit 0", (r.returncode, r.stdout, r.stderr), (0, "", ""))

repo2 = helpers.toy_repo()
folders = []
for slug in ("alpha", "beta"):
    d = str(state.new_phase(slug, cwd=repo2))
    helpers.write(d, "context.md", CONTEXT)
    state.append_decision(os.path.join(d, "decisions.tsv"), decision="%s-%s" % (DECIDED_WORD, slug), why="w", support="chosen")
    helpers.fwx(repo2, "context-base", "build", d, "--map", toy_map)
    folders.append(d)
r = run(repo2, "fwx:planner")
s.eq("two open phases and none bound: injected with 2 open phases", (r.returncode, r.stdout, r.stderr), (0, "", ""))
r = run(repo2, "fwx:planner", session="no-such-session")
s.eq("two open phases, a session that is bound to nothing: empty", (r.returncode, r.stdout), (0, ""))
state.write_session(repo2, "toy-session", phase_dir=os.path.relpath(folders[1], repo2))
r = run(repo2, "fwx:planner")
s.ok("two open phases, the session is bound to the second: it gets that base", "zebrafinch-beta" in (delivered(r) or "") and
     "zebrafinch-alpha" not in (delivered(r) or ""), r.stdout[:200])
os.remove(cb.base_path(folders[1]))
r = run(repo2, "fwx:planner")
s.eq("a phase with no base file: empty, exit 0, nothing written", (r.returncode, r.stdout, r.stderr, os.path.exists(cb.base_path(folders[1]))),
     (0, "", "", False))
repo3, folder3, _ = phase(helpers.toy_repo())
os.remove(cb.base_path(folder3))
r = run(repo3, "fwx:planner")
s.eq("one open phase with no base: empty, exit 0, the hook did not build it", (r.returncode, r.stdout, os.path.exists(cb.base_path(folder3))),
     (0, "", False))

# ---- from a worktree: the same bytes ---------------------------------------------------------------------------------
repo4, folder4, base4 = phase()
wt = helpers.add_worktree(repo4, "wt-branch")
os.makedirs(os.path.join(wt, "sub", "dir"))
for agent in ("fwx:planner", "fwx:reviewer"):
    main_out = run(repo4, agent).stdout
    s.ok("%s from the main checkout delivers" % agent, bool(main_out))
    s.eq("%s from a worktree: the same bytes (no base found from worktree)" % agent, run(wt, agent).stdout, main_out)
    s.eq("%s from a folder inside the worktree: the same bytes" % agent, run(os.path.join(wt, "sub", "dir"), agent).stdout, main_out)
before = sorted(os.listdir(os.path.join(wt)))
run(wt, "fwx:planner")
s.eq("the hook wrote nothing into the worktree", sorted(os.listdir(wt)), before)

# ---- the cap: 9500 units is delivered, above it exit 1 with a line on stderr, nothing on stdout ------------------------
repo5, folder5, _ = phase(decisions=False)
base_file = cb.base_path(folder5)


def put_base(n_units, ch="x"):
    """A base file of exactly `n_units` UTF-16 units written by hand (a mark line first), in the right place."""
    first = cb.MARK + "00000000\n"
    unit = 2 if ord(ch) > 0xFFFF else 1
    body = ch * ((n_units - len(first)) // unit)
    text = first + body
    s.eq("the toy file is %d units" % n_units, cb.units(text), n_units)
    with open(base_file, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return text


for n in (9500,):
    put_base(n)
    r = run(repo5, "fwx:planner")
    s.eq("a file of %d units is delivered" % n, (r.returncode, r.stderr, cb.units(delivered(r) or "")), (0, "", n))
put_base(9501)
r = run(repo5, "fwx:planner")
s.eq("a file of 9501 units: exit 1, nothing on stdout", (r.returncode, r.stdout), (1, ""))
s.eq("9501: the line on stderr", r.stderr.strip(), "context-base: 9501 units over the cap")
put_base(9600)
r = run(repo5, "fwx:planner")
s.eq("a file of 9600 units: exit 1", r.returncode, 1)
s.eq("9600: context-base: 9600 units over the cap", r.stderr.strip(), "context-base: 9600 units over the cap")
s.eq("9600: nothing is delivered", r.stdout, "")
s.eq("the same file to a `none` agent: nothing, exit 0 (it is not read)", (run(repo5, "Explore").returncode, run(repo5, "Explore").stdout, run(repo5, "Explore").stderr), (0, "", ""))
put_base(9500, "é")
r = run(repo5, "fwx:planner")
s.eq("9500 `é` (19,000 bytes, 9,500 units) is delivered: the cap is not in bytes", (r.returncode, cb.units(delivered(r) or "")), (0, 9500))
put_base(9600, "\U0001F600")
r = run(repo5, "fwx:planner")
s.eq("4,800 emoji (4,800 code points, 9,600 units): exit 1, the cap is not in code points", r.returncode, 1)
s.eq("emoji: context-base: 9600 units over the cap", r.stderr.strip(), "context-base: 9600 units over the cap")
# the cap is on what is delivered: a `map` agent gets the head, so an oversize decided part does not refuse it
head_text = cb.MARK + "00000000\n" + "m" * 2000 + "\n## Decided\n" + "d" * 8000 + "\n"
with open(base_file, "w", encoding="utf-8", newline="") as fh:
    fh.write(head_text)
s.eq("a 10,000-unit file whose decided part is 8,000: the reviewer gets the head, exit 0",
     (run(repo5, "fwx:reviewer").returncode, cb.units(delivered(run(repo5, "fwx:reviewer")) or "")), (0, 2000 + len(cb.MARK) + 9 + 1))
s.eq("the planner gets the whole and it is over the cap: exit 1", run(repo5, "fwx:planner").returncode, 1)

# ---- a failure is never silent: exit 1 with `context-base: <error>` ------------------------------------------------------
repo6, folder6, _ = phase()
sess_dir = state.sessions_dir(repo6)
os.makedirs(sess_dir, exist_ok=True)
helpers.write(sess_dir, "broken.json", "{not json")
r = run(repo6, "fwx:planner", session="broken")
s.eq("a session file that cannot be read: exit 1, nothing on stdout", (r.returncode, r.stdout), (1, ""))
s.ok("it says context-base: and the file", r.stderr.startswith("context-base: ") and "broken.json" in r.stderr, r.stderr)
s.eq("the error is one line", len(r.stderr.strip().splitlines()), 1)
r = run(repo6, "fwx:planner", raw="not json at all")
s.eq("an input that is not JSON: exit 1", r.returncode, 1)
s.ok("... with context-base: on stderr", r.stderr.startswith("context-base: "), r.stderr)
r = run(repo6, "fwx:planner", raw=json.dumps({"hook_event_name": "SubagentStart", "session_id": "x", "cwd": repo6}))
s.eq("an input without agent_type: exit 1", r.returncode, 1)
r = run(repo6, "fwx:planner", session="../etc/passwd")
s.eq("a session id that is a path: exit 1", r.returncode, 1)
s.ok("... with context-base: on stderr", r.stderr.startswith("context-base: "), r.stderr)

# ---- a table with no `*` row, or a value it does not know: the hook fails, it does not guess -------------------------------
no_star = "agent_type\tsections\twhy\nfwx:planner\tmap+decided\tbuilds\n"
r = run(repo, "fwx:planner", root=copy_plugin("no-star", table=no_star))
s.eq("a table with no `*` row: exit 1 even for a type it lists", (r.returncode, r.stdout), (1, ""))
s.ok("... no default row", "no default row" in r.stderr and r.stderr.startswith("context-base: "), r.stderr)
bad_value = "agent_type\tsections\twhy\n*\teverything\tx\n"
r = run(repo, "fwx:planner", root=copy_plugin("bad-value", table=bad_value))
s.eq("a table with a value it does not know: exit 1", (r.returncode, r.stdout), (1, ""))
s.ok("... it names the value", "everything" in r.stderr, r.stderr)
only_star = "agent_type\tsections\twhy\n*\tmap\tdefault\n"
r = run(repo, "fwx:planner", root=copy_plugin("only-star", table=only_star))
s.eq("a table with only `*`: the planner gets the map, no decided", (r.returncode, DECIDED_WORD in (delivered(r) or ""), MAP_WORD in (delivered(r) or "")), (0, False, True))
exact_first = "agent_type\tsections\twhy\n*\tnone\tdefault\nfwx:planner\tmap\tx\n"
r = run(repo, "fwx:planner", root=copy_plugin("exact-first", table=exact_first))
s.ok("the exact row wins over `*`", MAP_WORD in (delivered(r) or ""))

# ---- the hook command from hooks.json, as Claude Code runs it -----------------------------------------------------------
cmd = cmds[0].get("command", "") if cmds else ""
if cmd:
    r = subprocess.run(["sh", "-c", cmd], input=json.dumps({"hook_event_name": "SubagentStart", "agent_type": "general-purpose",
                                                           "session_id": "toy-session", "agent_id": "a1", "cwd": repo}),
                       cwd=repo, env=helpers.clean_env(CLAUDE_PLUGIN_ROOT=ROOT), capture_output=True, text=True)
    s.eq("the hooks.json command, with CLAUDE_PLUGIN_ROOT set, delivers the head", (r.returncode, delivered(r)), (0, head))
    r = subprocess.run(["sh", "-c", cmd], input="{}", cwd=repo, env=helpers.clean_env(CLAUDE_PLUGIN_ROOT=ROOT), capture_output=True, text=True)
    s.eq("... and an empty input fails loud", r.returncode, 1)

# ---- --file F [--source F]: the construction's hand-written file ---------------------------------------------------------
fdir = helpers.toy_repo()
hand = os.path.join(fdir, "hand.md")
src = helpers.write(fdir, "long-doc.md", "the long document\n")
helpers.write(fdir, "hand.md", "# hand-written\nHAND-MAP-WORD one\n## Decided\nHAND-DECIDED-WORD\n")
cb.seal(hand, source=src)
with open(hand, encoding="utf-8") as fh:
    hand_text = fh.read()
hand_head = hand_text[:hand_text.index("## Decided\n")]
r = run(fdir, "general-purpose", args=["--file", hand, "--source", src])
s.eq("--file, same repository, no phase: delivers the head to a `map` agent", (r.returncode, delivered(r)), (0, hand_head))
r = run(fdir, "fwx:planner", args=["--file", hand, "--source", src])
s.eq("--file: a `map+decided` agent gets the whole file", (r.returncode, delivered(r)), (0, hand_text))
r = run(fdir, "Explore", args=["--file", hand])
s.eq("--file: a `none` agent gets nothing", (r.returncode, r.stdout), (0, ""))
other = helpers.toy_repo()
r = run(other, "general-purpose", args=["--file", hand, "--source", src])
s.eq("--file with a cwd of another repository: empty, exit 0", (r.returncode, r.stdout, r.stderr), (0, "", ""))
r = run(outside, "general-purpose", args=["--file", hand])
s.eq("--file with a cwd that is no repository: empty, exit 0", (r.returncode, r.stdout, r.stderr), (0, "", ""))
wt2 = helpers.add_worktree(fdir, "wt-file")
r = run(wt2, "general-purpose", args=["--file", hand, "--source", src])
s.eq("--file from a worktree of the same repository: delivers", (r.returncode, delivered(r)), (0, hand_head))
helpers.write(fdir, "long-doc.md", "the long document, edited\n")
r = run(fdir, "general-purpose", args=["--file", hand, "--source", src])
s.eq("--file --source: the source changed since the seal: exit 1, nothing delivered", (r.returncode, r.stdout), (1, ""))
s.ok("... stale, on stderr", r.stderr.startswith("context-base: ") and "stale" in r.stderr, r.stderr)
r = run(fdir, "general-purpose", args=["--file", os.path.join(fdir, "no-such.md")])
s.eq("--file naming a file that is not there: exit 1", r.returncode, 1)
s.ok("... context-base: on stderr", r.stderr.startswith("context-base: "), r.stderr)
r = run(fdir, "general-purpose", args=["--frobnicate"])
s.eq("an option the hook does not know: exit 1", r.returncode, 1)
with open(hand, "a", encoding="utf-8") as fh:
    fh.write("edited by hand\n")
r = run(fdir, "general-purpose", args=["--file", hand, "--source", src])
s.eq("--file --source: edited since sealed, exit 1", r.returncode, 1)

# ---- the hook never writes ---------------------------------------------------------------------------------------------
repo7, folder7, _ = phase()


def snapshot(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != ".git"]
        for f in fn:
            p = os.path.join(dp, f)
            out[p] = (os.path.getmtime(p), os.path.getsize(p))
    return out


common = os.path.dirname(state.sessions_dir(repo7))
snap_repo, snap_common = snapshot(repo7), snapshot(common)
for agent in ("fwx:planner", "fwx:reviewer", "Explore", "projagent"):
    run(repo7, agent)
s.eq("the hook wrote nothing in the repository or the common dir", (snapshot(repo7), snapshot(common)), (snap_repo, snap_common))
fdir2 = helpers.toy_repo()
src2 = helpers.write(fdir2, "long-doc.md", "the long document\n")
hand2 = helpers.write(fdir2, "hand.md", "# hand-written\nHAND-MAP-WORD\n## Decided\nHAND-DECIDED-WORD\n")
cb.seal(hand2, source=src2)
snap_file, snap_file_common = snapshot(fdir2), snapshot(os.path.dirname(state.sessions_dir(fdir2)))
for agent in ("fwx:planner", "general-purpose", "Explore"):
    s.eq("--file, %s: delivers or is silent, exit 0" % agent, run(fdir2, agent, args=["--file", hand2, "--source", src2]).returncode, 0)
s.eq("--file wrote nothing either", (snapshot(fdir2), snapshot(os.path.dirname(state.sessions_dir(fdir2)))), (snap_file, snap_file_common))

# an exception nobody expected is still a line on stderr and exit 1, never a quiet exit 0
r = run(repo7, "fwx:planner", raw=json.dumps({"hook_event_name": "SubagentStart", "agent_type": "fwx:planner", "session_id": "s", "cwd": ["x"]}))
s.eq("an input whose cwd is a list (a TypeError nobody planned for): exit 1, nothing on stdout", (r.returncode, r.stdout), (1, ""))
s.ok("... one line, context-base: <the kind of error>", r.stderr.startswith("context-base: ") and len(r.stderr.strip().splitlines()) == 1, r.stderr)

s.done()
