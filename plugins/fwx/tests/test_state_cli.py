#!/usr/bin/env python3
"""`fwx state`: the subcommands of lib/fwx/commands/state.py, end to end through `bin/fwx` in toy repos, each with
CLAUDE_CODE_SESSION_ID in the environment (an empty one where a test needs no session: the real one of the machine
running the test must not leak in).

Exit codes the plan fixes: 0 done, 1 refused or unresolved, 2 cannot run (outside a git repository, wrong usage).

Seen red before the command existed (bin/fwx has no `state`; 291 checks, 189 failed; the usage-error checks passed
anyway, because an unknown command also exits 2; first FAIL lines):
  FAIL: bin/fwx help lists `state`: usage: fwx <command> [args] ... commands: budget, model, stage, statusline, test
  FAIL: new-phase from a linked worktree: exit code: got 2, want 0
  FAIL: new-phase from a worktree: the folder is in the main checkout

Controls, each seen red on lib/fwx/commands/state.py changed in one place (the file put back after each; first FAIL lines):
  - a StateError exits 0 (the plan's wiring control; 22 failed):
      FAIL: decision --support maybe: exit code: got 0, want 1
      FAIL: new-phase: a bad slug: exit code: got 0, want 1
      FAIL: cancel after the pre-mortem: exit code: got 0, want 1
  - resolve does not bind the session (3 failed):
      FAIL: resolve binds the session to the only open phase: got None, want {'subproject': None, 'phase_dir': '.fwx/milestones/v1/phases/01-a'}
  - resolve names no candidates (2 failed):
      FAIL: resolve, two open phases: the message names both: fwx state: no phase is bound to this session and 2 are open: ? (...)
  - resolve exits 0 when it cannot resolve (3 failed):
      FAIL: resolve, no phase bound, two open phases: exit code: got 0, want 1
  - cancel handed the parent folder (the CLI's wiring; the deletion itself is state.py's, seen red in test_state.py; 4 failed):
      FAIL: cancel: exit code: got 1, want 0
      FAIL: cancel: its folder is gone
  - check ignores errors (4 failed):
      FAIL: check report that does not cite the evidence sha: exit code: got 0, want 1
  - check fails on a length warning (2 failed):
      FAIL: check report that cites the sha but is long: only a warning: exit code: got 1, want 0
  - --adr writes decisions.tsv (4 failed):
      FAIL: decision --adr: stdout: got 'D3', want 'A1'
  - `use PHASE_DIR` does not take the subproject from the path (2 failed):
      FAIL: use PHASE_DIR of a subproject: the session file: got {'subproject': None, ...}, want {'subproject': 'web', ...}
  - ConfigError not caught (18 failed):
      FAIL: outside a repository: resolve: exit code: got 1, want 2
      FAIL: outside a repository: resolve: no traceback: ... config.py", line 82, in main_checkout
  - a usage error exits 1 (9 failed):
      FAIL: usage: no subcommand: exit code: got 1, want 2
  - new-milestone without the missing-`.fwx` guard (3 failed):
      FAIL: new-milestone with no .fwx: refused, nothing made: exit code: got 0, want 1
  - list marks every phase open (1 failed):
      FAIL: list --json: a closed phase and its stage: got ('01-login', 'closed', True), want ('01-login', 'closed', False)

2.5 U4 (new-phase builds the base context), seen red on lib/fwx/commands/state.py at master (296 checks):
  FAIL: new-phase: the base file is made, with the map: .../.git/fwx/context-base/fwx__milestones__v1__phases__01-alpha.md
  FAIL: new-phase with a map over the cap: one `fwx state new-phase: context-base: ... over the cap` line: ''
  - new-phase exits 1 when the refresh fails (2 failed):
      FAIL: new-phase with a map over the cap: exit 0: got 1, want 0
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import state  # noqa: E402

s = helpers.Suite()
NOSESSION = {"CLAUDE_CODE_SESSION_ID": ""}


def st(cwd, *args, session="sess-1", env=None):
    e = {"CLAUDE_CODE_SESSION_ID": session} if session else dict(NOSESSION)
    e.update(env or {})
    return helpers.fwx(cwd, "state", *args, env=e)


def clean(label, r, code, out=None):
    """The exit code; a refusal or a failure to run is one line on stderr and no traceback."""
    s.eq("%s: exit code" % label, r.returncode, code)
    s.ok("%s: no traceback" % label, "Traceback" not in r.stderr, r.stderr[-300:])
    if code:
        s.ok("%s: one line on stderr" % label, len(r.stderr.strip().splitlines()) == 1, repr(r.stderr[-300:]))
    if out is not None:
        s.eq("%s: stdout" % label, r.stdout.strip(), out)
    return r.returncode == code


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def session_file(repo, sid):
    p = os.path.join(repo, ".git", "fwx", "sessions", sid + ".json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def js(text):
    try:
        got = json.loads(text)
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def audit(folder, kind, detail, sha, rc=""):
    """A row through the one writer; a folder the command under test failed to make is a failed check, not a crash."""
    try:
        state.append_audit(folder, kind, detail, rc=rc, sha=sha)
    except state.StateError as e:
        s.ok("setup: audit row in %s" % os.path.basename(folder), False, str(e))


def ls(d):
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def tree(root):
    """Every path under root (files and folders), relative; to tell what a command wrote and what it left."""
    found = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        found += [os.path.relpath(os.path.join(d, n), root) for n in dirs + files]
    return sorted(found)


# ---- bin/fwx lists it, and misuse exits 2 --------------------------------------------------------------------------
r = helpers.fwx(helpers.ROOT, "help")
s.ok("bin/fwx help lists `state`", re.search(r"^\s+state\s+\S", r.stdout, re.M) is not None, r.stdout)

repo = helpers.toy_repo()
for label, args in (("no subcommand", []), ("an unknown subcommand", ["frobnicate"]), ("new-phase without a slug", ["new-phase"]),
                    ("an unknown flag", ["resolve", "--nope"]), ("decision without --why", ["decision", "--decision", "x", "--support", "chosen"]),
                    ("use with nothing", ["use"]), ("check with an unknown kind", ["check", "plan", "x.md"]),
                    ("use with a phase and --root", ["use", "x", "--root"])):
    clean("usage: %s" % label, st(repo, *args), 2)
s.eq("usage errors write nothing", tree(repo), ["README"])

# ---- new-phase: from a worktree, in the main checkout, binds the session ---------------------------------------------
main = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
wt = helpers.add_worktree(main, "feat")
before_wt = tree(wt)
r = st(wt, "new-phase", "alpha", session="sess-a")
phase1 = os.path.join(main, ".fwx", "milestones", "v1", "phases", "01-alpha")
clean("new-phase from a linked worktree", r, 0, phase1)
s.ok("new-phase from a worktree: the folder is in the main checkout", os.path.isdir(phase1))
s.eq("new-phase from a worktree: nothing in the worktree", tree(wt), before_wt)
s.ok("new-phase: PROJECT.md and the milestone are made", os.path.exists(os.path.join(main, ".fwx", "PROJECT.md"))
     and os.path.exists(os.path.join(main, ".fwx", "milestones", "v1", "MILESTONE.md")))
s.eq("new-phase: the phase folder holds context.md, decisions.tsv and audit.tsv",
     ls(phase1), ["audit.tsv", "context.md", "decisions.tsv"])
# 2.5 U4: the base context is built with the phase, before any context.md of the owner's
sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import context_base as cb  # noqa: E402

base1 = cb.base_path(phase1)
def text_of(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


btext = text_of(base1) if os.path.exists(base1) else ""
s.ok("new-phase: the base file is made, with the map", os.path.exists(base1) and text_of(os.path.join(helpers.ROOT, "data", "context-map.md")).strip() in btext,
     base1)
s.ok("new-phase: the base lists the phase's files", "## Files" in btext and os.path.join(phase1, "decisions.tsv") in btext, btext[-400:])
s.ok("new-phase: the base is in the discuss stage", "<!-- built stage=discuss " in btext, btext[-200:])
s.eq("new-phase: nothing of the base inside the worktree", tree(wt), before_wt)

s.eq("new-phase: binds the session", session_file(main, "sess-a"), {"subproject": None, "phase_dir": ".fwx/milestones/v1/phases/01-alpha"})
s.eq("new-phase: the session file is in the main checkout's git dir, not the worktree's",
     os.path.exists(os.path.join(main, ".git", "fwx", "sessions", "sess-a.json")), True)

clean("new-phase: a second phase takes the next number", st(main, "new-phase", "beta", session="sess-a"), 0,
      os.path.join(main, ".fwx", "milestones", "v1", "phases", "02-beta"))
s.eq("new-phase: --session binds that id, not the environment's",
     (st(main, "new-phase", "gamma", "--session", "sess-g", session="sess-a").returncode, (session_file(main, "sess-g") or {}).get("phase_dir")),
     (0, ".fwx/milestones/v1/phases/03-gamma"))
before = tree(main)
clean("new-phase: a bad slug", st(main, "new-phase", "Bad Slug"), 1)
s.eq("new-phase: a bad slug writes nothing", tree(main), before)
clean("new-phase: a milestone that does not exist", st(main, "new-phase", "delta", "--milestone", "v9"), 1)
s.eq("new-phase: a missing milestone writes nothing", tree(main), before)
r = st(main, "new-phase", "delta", session="")
clean("new-phase: with no session id it still makes the phase", r, 0)
s.ok("new-phase: with no session id, no session file is written", not os.path.exists(os.path.join(main, ".git", "fwx", "sessions", ".json")))

# ---- decision ------------------------------------------------------------------------------------------------------
clean("use PHASE_DIR (so the decisions below go to 01-alpha)", st(main, "use", phase1, session="sess-a"), 0)
dec = os.path.join(phase1, "decisions.tsv")
head = read(dec)
r = st(main, "decision", "--decision", "use TSV", "--why", "greppable", "--support", "maybe", "--session", "sess-a")
clean("decision --support maybe", r, 1)
s.ok("decision --support maybe: the message names the bad value", "maybe" in r.stderr, r.stderr)
s.eq("decision --support maybe: the file is byte for byte the same", read(dec), head)
r = st(main, "decision", "--decision", "use TSV", "--why", "greppable", "--support", "chosen", "--rejected", "json", "--source", "d:1",
       session="sess-a")
clean("decision on the session's phase", r, 0, "D1")
rows = state.read_rows(dec)
s.eq("decision: the row", [(x["id"], x["decision"], x["why"], x["support"], x["rejected"], x["source"]) for x in rows],
     [("D1", "use TSV", "greppable", "chosen", "json", "d:1")])
mid = read(dec)
clean("decision --supersedes", st(main, "decision", "--decision", "use TSV and JSON", "--why", "both", "--support", "approved",
                                  "--supersedes", "D1", session="sess-a"), 0, "D2")
s.eq("decision --supersedes: the column", [x["supersedes"] for x in state.read_rows(dec)], ["", "D1"])
after = read(dec)
clean("decision --supersedes an id that does not exist", st(main, "decision", "--decision", "x", "--why", "y", "--support", "chosen",
                                                            "--supersedes", "D9", session="sess-a"), 1)
clean("decision with an empty why", st(main, "decision", "--decision", "x", "--why", " ", "--support", "chosen", session="sess-a"), 1)
s.eq("decision: the refusals leave the file as it was", read(dec), after)
beta_dec = os.path.join(main, ".fwx", "milestones", "v1", "phases", "02-beta", "decisions.tsv")
clean("decision --phase", st(main, "decision", "--decision", "in beta", "--why", "w", "--support", "unexamined", "--phase",
                             os.path.dirname(beta_dec), session="sess-a"), 0, "D1")
s.eq("decision --phase writes that phase's file and not the session's", (len(state.read_rows(beta_dec)), len(state.read_rows(dec))), (1, 2))
adr = os.path.join(main, ".fwx", "adr.tsv")
clean("decision --adr", st(main, "decision", "--adr", "--decision", "keep TSV", "--why", "hard to undo", "--support", "chosen",
                           session="sess-a"), 0, "A1")
s.eq("decision --adr: .fwx/adr.tsv has the row", [(x["id"], x["decision"]) for x in state.read_rows(adr)], [("A1", "keep TSV")])
adr_before = read(adr)
clean("decision --adr with a bad support", st(main, "decision", "--adr", "--decision", "x", "--why", "y", "--support", "maybe",
                                              session="sess-a"), 1)
s.eq("decision --adr with a bad support: adr.tsv is unchanged", read(adr), adr_before)

# ---- resolve --------------------------------------------------------------------------------------------------------
rv = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
st(rv, "new-phase", "a", session="s-a")
st(rv, "new-phase", "b", session="s-a")
pa = os.path.join(rv, ".fwx", "milestones", "v1", "phases", "01-a")
pb = os.path.join(rv, ".fwx", "milestones", "v1", "phases", "02-b")
r = st(rv, "resolve", session="sess-new")
clean("resolve, no phase bound, two open phases", r, 1)
s.ok("resolve, two open phases: the message names both", "01-a" in r.stderr and "02-b" in r.stderr, r.stderr)
s.ok("resolve, two open phases: the session is not bound", session_file(rv, "sess-new") is None)
r = st(rv, "decision", "--decision", "x", "--why", "y", "--support", "chosen", session="sess-new")
clean("decision with no phase to resolve (new session, two open phases)", r, 1)
s.ok("decision with no phase to resolve: names both candidates", "01-a" in r.stderr and "02-b" in r.stderr, r.stderr)
r = st(rv, "resolve", "--json", session="sess-new")
s.eq("resolve --json, two open phases: exit code", r.returncode, 1)
got = js(r.stdout)
s.eq("resolve --json, two open phases: the candidates are listed and the phase is null",
     (got.get("phase_dir"), [os.path.basename(c) for c in got.get("candidates", [])]), (None, ["01-a", "02-b"]))

audit(pb, "stage", "closed", sha="a" * 40)
r = st(rv, "resolve", "--json", session="sess-new")
clean("resolve with one open phase left (the other closed)", r, 0)
got = js(r.stdout)
s.eq("resolve --json: phase_dir, subproject, milestone", (got.get("phase_dir"), got.get("subproject"), got.get("milestone")),
     (pa, None, "v1"))
s.ok("resolve --json: the keys of state.resolve",
     {"main_checkout", "plan_root", "has_subprojects", "subproject", "milestone", "phase_dir", "subphases", "candidates", "paths"} <= set(got),
     str(sorted(got)))
s.eq("resolve --json: paths are absolute strings", got.get("paths", {}).get("audit"), os.path.join(pa, "audit.tsv"))
s.eq("resolve binds the session to the only open phase", session_file(rv, "sess-new"),
     {"subproject": None, "phase_dir": ".fwx/milestones/v1/phases/01-a"})
r = st(rv, "resolve", session="sess-new")
clean("resolve (plain)", r, 0)
s.ok("resolve (plain): prints the phase folder", pa in r.stdout, r.stdout)
r = st(rv, "resolve", "--session", "sess-flag", session="")
clean("resolve --session ID with no environment session", r, 0)
s.eq("resolve --session ID binds that id", (session_file(rv, "sess-flag") or {}).get("phase_dir"), ".fwx/milestones/v1/phases/01-a")
r = st(rv, "resolve", session="")
clean("resolve with no session id at all and one open phase", r, 0)
s.ok("resolve with no session id: prints the phase", pa in r.stdout, r.stdout)

# a bound session is not rebound to whatever else is open
audit(pb, "stage", "discuss", sha="a" * 40)
bound_before = session_file(rv, "sess-new")
r = st(rv, "resolve", "--json", session="sess-new")
s.eq("resolve with a bound session returns the bound phase", js(r.stdout).get("phase_dir"), pa)
s.eq("resolve with a bound session leaves the file alone", session_file(rv, "sess-new"), bound_before)

empty = helpers.toy_repo()
r = st(empty, "resolve")
clean("resolve with no .fwx", r, 1)
s.eq("resolve with no .fwx creates nothing", tree(empty), ["README"])

# ---- use ------------------------------------------------------------------------------------------------------------
clean("use PHASE_DIR", st(main, "use", phase1, session="sess-u"), 0)
s.eq("use PHASE_DIR binds", session_file(main, "sess-u"), {"subproject": None, "phase_dir": ".fwx/milestones/v1/phases/01-alpha"})
clean("use --subproject", st(main, "use", "--subproject", "web", session="sess-u"), 0)
s.eq("use --subproject binds the subproject and no phase", session_file(main, "sess-u"), {"subproject": "web", "phase_dir": None})
clean("use --root", st(main, "use", "--root", session="sess-u"), 0)
s.eq("use --root binds the root and no phase", session_file(main, "sess-u"), {"subproject": None, "phase_dir": None})
clean("use --root with --session", st(main, "use", "--subproject", "api", "--session", "sess-v", session=""), 0)
s.eq("use --session ID", session_file(main, "sess-v"), {"subproject": "api", "phase_dir": None})
clean("use with no session id", st(main, "use", "--root", session=""), 1)
fixed = session_file(main, "sess-u")
clean("use a phase that does not exist", st(main, "use", os.path.join(main, ".fwx", "milestones", "v1", "phases", "09-no"), session="sess-u"), 1)
clean("use a folder outside .fwx", st(main, "use", main, session="sess-u"), 1)
clean("use a bad subproject name", st(main, "use", "--subproject", "../x", session="sess-u"), 1)
s.eq("use: the refusals leave the session as it was", session_file(main, "sess-u"), fixed)

# ---- subprojects: new-phase keeps the bound one, `use --root` leaves it -----------------------------------------------
sub = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
clean("new-phase --subproject creates the subproject's own tree",
      st(sub, "new-phase", "login", "--subproject", "web", session="s-web"), 0,
      os.path.join(sub, ".fwx", "subprojects", "web", "milestones", "v1", "phases", "01-login"))
s.eq("new-phase --subproject binds subproject and phase", session_file(sub, "s-web"),
     {"subproject": "web", "phase_dir": ".fwx/subprojects/web/milestones/v1/phases/01-login"})
clean("new-phase with no flag keeps the bound subproject", st(sub, "new-phase", "logout", session="s-web"), 0,
      os.path.join(sub, ".fwx", "subprojects", "web", "milestones", "v1", "phases", "02-logout"))
clean("use --root, then new-phase, lands in the root", st(sub, "use", "--root", session="s-web"), 0)
clean("new-phase after use --root", st(sub, "new-phase", "top", session="s-web"), 0,
      os.path.join(sub, ".fwx", "milestones", "v1", "phases", "01-top"))
sphase = os.path.join(sub, ".fwx", "subprojects", "web", "milestones", "v1", "phases", "01-login")
clean("use PHASE_DIR of a subproject binds the subproject too", st(sub, "use", sphase, session="s-u2"), 0)
s.eq("use PHASE_DIR of a subproject: the session file", session_file(sub, "s-u2"),
     {"subproject": "web", "phase_dir": ".fwx/subprojects/web/milestones/v1/phases/01-login"})
clean("decision --adr in a subproject writes that subproject's adr.tsv",
      st(sub, "decision", "--adr", "--decision", "d", "--why", "w", "--support", "chosen", session="s-u2"), 0, "A1")
s.ok("decision --adr in a subproject: the file", os.path.exists(os.path.join(sub, ".fwx", "subprojects", "web", "adr.tsv"))
     and not os.path.exists(os.path.join(sub, ".fwx", "adr.tsv")))

# ---- list -----------------------------------------------------------------------------------------------------------
r = st(sub, "list", "--json")
clean("list --json", r, 0)
got = js(r.stdout)
s.eq("list --json: the root's phases", [(m["name"], [(p["name"], p["stage"], p["open"]) for p in m["phases"]]) for m in got.get("milestones", [])],
     [("v1", [("01-top", None, True)])])
s.eq("list --json: the subprojects and the scope", (got.get("subprojects"), got.get("subproject")), (["web"], None))
r = st(sub, "list", "--json", "--subproject", "web")
got = js(r.stdout)
s.eq("list --json --subproject: its phases", [(p["name"], p["open"]) for m in got.get("milestones", []) for p in m["phases"]],
     [("01-login", True), ("02-logout", True)])
audit(sphase, "stage", "closed", sha="b" * 40)
real = st(sub, "new-subphase", sphase, "part", session="s-u2")
got = js(st(sub, "list", "--json", "--subproject", "web").stdout)
first = (got.get("milestones") or [{"phases": [{}]}])[0]["phases"][0]
s.eq("list --json: a closed phase and its stage", (first.get("name"), first.get("stage"), first.get("open")), ("01-login", "closed", False))
s.eq("list --json: subphases by name", first.get("subphases"), ["01.1-part"])
r = st(sub, "list", "--subproject", "web")
clean("list (plain)", r, 0)
s.ok("list (plain): one line per phase with its stage",
     any("01-login" in l and "closed" in l for l in r.stdout.splitlines()) and any("02-logout" in l for l in r.stdout.splitlines()), r.stdout)
clean("list with no .fwx", st(empty, "list"), 0)
s.eq("list --json with no .fwx: no milestones", js(st(empty, "list", "--json").stdout).get("milestones"), [])
s.eq("list --json with no .fwx creates nothing", tree(empty), ["README"])
clean("list --subproject with a bad name", st(sub, "list", "--subproject", "a/b"), 1)

# ---- new-subphase, new-milestone ------------------------------------------------------------------------------------
clean("new-subphase", real, 0, os.path.join(sphase, "01.1-part"))
s.eq("new-subphase: folder content", ls(os.path.join(sphase, "01.1-part")), ["audit.tsv", "plan.md"])
clean("new-subphase: the next M", st(sub, "new-subphase", sphase, "next"), 0, os.path.join(sphase, "01.2-next"))
clean("new-subphase on a folder that is not a phase", st(sub, "new-subphase", sub, "x"), 1)
clean("new-subphase with a bad slug", st(sub, "new-subphase", sphase, "No Good"), 1)
clean("new-milestone (the next number)", st(sub, "new-milestone"), 0, os.path.join(sub, ".fwx", "milestones", "v2"))
s.ok("new-milestone: MILESTONE.md", os.path.exists(os.path.join(sub, ".fwx", "milestones", "v2", "MILESTONE.md")))
clean("new-milestone vN", st(sub, "new-milestone", "v5", "--subproject", "web"), 0, os.path.join(sub, ".fwx", "subprojects", "web", "milestones", "v5"))
clean("new-milestone that exists", st(sub, "new-milestone", "v5", "--subproject", "web"), 1)
clean("new-milestone with a bad name", st(sub, "new-milestone", "x1"), 1)
clean("new-phase now lands in the highest milestone", st(sub, "new-phase", "m2", session="s-w2"), 0,
      os.path.join(sub, ".fwx", "milestones", "v2", "phases", "01-m2"))
bare = helpers.toy_repo()
clean("new-milestone with no .fwx: refused, nothing made", st(bare, "new-milestone"), 1)
s.eq("new-milestone with no .fwx writes nothing", tree(bare), ["README"])

# ---- cancel ---------------------------------------------------------------------------------------------------------
c = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
st(c, "new-phase", "one", session="s-c")
st(c, "new-phase", "two", session="s-c")
one = os.path.join(c, ".fwx", "milestones", "v1", "phases", "01-one")
two = os.path.join(c, ".fwx", "milestones", "v1", "phases", "02-two")
two_before = tree(two)
st(c, "use", one, session="s-other")
clean("cancel", st(c, "cancel", one), 0)
s.ok("cancel: its folder is gone", not os.path.exists(one))
s.eq("cancel: the neighbour is intact", tree(two), two_before)
s.ok("cancel: PROJECT.md and the milestone stay", os.path.exists(os.path.join(c, ".fwx", "PROJECT.md"))
     and os.path.exists(os.path.join(c, ".fwx", "milestones", "v1", "MILESTONE.md")))
s.eq("cancel: the session that pointed at it is unbound", session_file(c, "s-other"), {"subproject": None, "phase_dir": None})
s.eq("cancel: the other session keeps its phase", session_file(c, "s-c"), {"subproject": None, "phase_dir": ".fwx/milestones/v1/phases/02-two"})
helpers.write(two, "premortem.md", "x\n")
two_before = tree(two)
r = st(c, "cancel", two)
clean("cancel after the pre-mortem", r, 1)
s.ok("cancel after the pre-mortem: names the file", "premortem.md" in r.stderr, r.stderr)
s.eq("cancel after the pre-mortem: nothing deleted", tree(two), two_before)
for label, target in (("the milestones folder", os.path.join(c, ".fwx", "milestones")), (".fwx itself", os.path.join(c, ".fwx")),
                      ("the repository", c), ("a phase that is not there", one)):
    clean("cancel %s" % label, st(c, "cancel", target), 1)
s.ok("cancel of a wrong target deleted nothing", os.path.isdir(os.path.join(c, ".fwx", "milestones")) and os.path.exists(os.path.join(c, "README")))
clean("cancel without an argument", st(c, "cancel"), 2)

# ---- check ----------------------------------------------------------------------------------------------------------
k = helpers.mkdtemp("fwx-check-")
sha = "c0ffee1" + "0" * 33
report = os.path.join(k, "report-1.md")
helpers.write(k, "report-1.md", "# Report 1\n\nDone.\n")
r = st(k, "check", "report", report, session="")  # outside a repository, but check reads only the files
clean("check report with no audit.tsv", r, 1)
audit(k, "evidence", "bin/fwx test", rc="0", sha=sha)
r = st(k, "check", "report", report)
clean("check report that does not cite the evidence sha", r, 1)
s.ok("check report: the message names the sha", sha[:7] in r.stderr, r.stderr)
helpers.write(k, "report-1.md", "# Report 1\n\nEvidence: commit %s\n" % sha[:12])
clean("check report that cites the sha", st(k, "check", "report", report), 0)
s.eq("check report: nothing to warn about, nothing printed besides ok", "WARN" in st(k, "check", "report", report).stdout, False)
helpers.write(k, "report-1.md", "# Report 1\n\nEvidence: commit %s\n" % sha[:12] + "line\n" * 50)
r = st(k, "check", "report", report)
clean("check report that cites the sha but is long: only a warning", r, 0)
s.ok("check report: the warning line", re.search(r"^WARN: 53 lines, target 40$", r.stdout, re.M) is not None, r.stdout)
state_md = os.path.join(k, "state.md")
helpers.write(k, "state.md", "line\n" * 112)
r = st(k, "check", "state", state_md)
clean("check state of 112 lines: only a warning", r, 0)
s.ok("check state: WARN: 112 lines, target 100", re.search(r"^WARN: 112 lines, target 100$", r.stdout, re.M) is not None, r.stdout)
helpers.write(k, "state.md", "short\n")
r = st(k, "check", "state", state_md)
clean("check state of a short file", r, 0)
s.ok("check state of a short file: no warning", "WARN" not in r.stdout, r.stdout)
helpers.write(k, "state.md", "")
clean("check state of an empty file", st(k, "check", "state", state_md), 1)
clean("check state of a file that is not there", st(k, "check", "state", os.path.join(k, "none.md")), 1)

# a map over the cap: the phase is made and bound, the exit stays 0, one line on stderr says why (2.5 U4)
import shutil  # noqa: E402
import subprocess  # noqa: E402

big = helpers.mkdtemp("fwx-bigmap-")
for sub in ("bin", "lib", "data", "templates"):
    shutil.copytree(os.path.join(helpers.ROOT, sub), os.path.join(big, sub), ignore=shutil.ignore_patterns("__pycache__"))
helpers.write(big, "data/context-map.md", "x" * 9500 + "\n")
big_repo = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
r = subprocess.run([sys.executable, os.path.join(big, "bin", "fwx"), "state", "new-phase", "alpha"], cwd=big_repo,
                   env=helpers.clean_env(CLAUDE_CODE_SESSION_ID="sess-big"), capture_output=True, text=True)
bigphase = os.path.join(big_repo, ".fwx", "milestones", "v1", "phases", "01-alpha")
s.eq("new-phase with a map over the cap: exit 0", r.returncode, 0)
s.eq("new-phase with a map over the cap: stdout is still the folder", r.stdout.strip(), bigphase)
s.ok("new-phase with a map over the cap: one `fwx state new-phase: context-base: ... over the cap` line",
     re.fullmatch(r"fwx state new-phase: context-base: .*over the cap.*\n", r.stderr) is not None, repr(r.stderr))
s.eq("new-phase with a map over the cap: the phase is bound", (session_file(big_repo, "sess-big") or {}).get("phase_dir"),
     ".fwx/milestones/v1/phases/01-alpha")

# ---- `fwx state commit`: the documents of a phase go where their history is ---------------------------------------------
# A project whose default branch takes changes only by pull request keeps `.fwx/` on the phase branch: the command, run from the phase's
# worktree, moves the files the worktree lacks out of the main checkout (the first phase: everything; a later one: the new phase's folder),
# commits `.fwx/` there and leaves the default branch alone. Without the protection it commits on the main checkout's branch; with `.fwx/`
# ignored by git (its history is on the data side) it refuses and names `forge commit`.
# Seen red on master (no `commit` subcommand; 25 FAIL lines, first ones):
#   FAIL: protected, first phase: commit from the phase worktree: exit code: got 2, want 0
#   FAIL: protected, first phase: the phase branch's tree holds the phase documents: ['README']
# Controls, each seen red on lib/fwx/state.py changed in one place (put back after each):
#   - the protection ignored, so the commit goes to the main checkout as the skill's old line did (18 failed):
#       FAIL: protected: from the main checkout: exit code: got 0, want 1
#       FAIL: protected: from the main checkout, nothing was committed: got <a new sha>, want <the base sha>
#   - the files not moved into the worktree (14 failed):
#       FAIL: protected, first phase: commit from the phase worktree: exit code: got 1, want 0
#   - the default-branch guard dropped (4 failed):
#       FAIL: protected: a worktree on the default branch: exit code: got 0, want 1
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
PHASE_REL = ".fwx/milestones/v1/phases/%s"


def commit(cwd, message):
    return st(cwd, "commit", "-m", message, session=None, env=IDENT)


def toy(protected, files=None):
    repo = helpers.toy_repo(dict({"README": "toy\n"}, **(files or {})))
    helpers.write(repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"default_branch_protected": protected}}))
    return repo


def head_files(cwd):
    return helpers.git(cwd, "ls-tree", "-r", "--name-only", "HEAD").splitlines()


def show(cwd, spec):
    try:
        return helpers.git(cwd, "show", spec)
    except RuntimeError:  # the path is not in the commit: a FAIL line, not a crash
        return ""


def subjects(cwd, rev="HEAD"):
    return helpers.git(cwd, "log", "--format=%s", rev).splitlines()


# a protected default branch, a first phase: `.fwx/` is untracked in the main checkout
main = toy(True)
wt = helpers.add_worktree(main, "fwx-phase")
st(main, "new-phase", "alpha", session=None)
base = helpers.git(main, "rev-parse", "master").strip()
r = commit(main, "from the main checkout")
clean("protected: from the main checkout", r, 1)
s.ok("protected: from the main checkout, the message names the phase worktree", "worktree" in r.stderr, r.stderr)
s.eq("protected: from the main checkout, nothing was committed", helpers.git(main, "rev-parse", "master").strip(), base)
s.ok("protected: from the main checkout, `.fwx/` is where it was", os.path.isfile(os.path.join(main, PHASE_REL % "01-alpha", "context.md")))
r = commit(wt, "fwx: part 1 starts")
clean("protected, first phase: commit from the phase worktree", r, 0)
s.ok("protected, first phase: stdout names the commit and the folder", re.match(r"committed [0-9a-f]{7,} on fwx-phase in \S+\Z", r.stdout.strip()), r.stdout)
s.eq("protected, first phase: the phase branch's log shows the commit", subjects(wt)[0], "fwx: part 1 starts")
s.ok("protected, first phase: the phase branch's tree holds the phase documents",
     all("%s/%s" % (PHASE_REL % "01-alpha", f) in head_files(wt) for f in ("context.md", "decisions.tsv")) and ".fwx/PROJECT.md" in head_files(wt), str(head_files(wt)))
s.eq("protected, first phase: nothing was committed on the default branch", helpers.git(main, "rev-parse", "master").strip(), base)
s.ok("protected, first phase: the default branch's log does not hold the message", "fwx: part 1 starts" not in subjects(main, "master"))
s.ok("protected, first phase: the main checkout keeps no second copy", not os.path.exists(os.path.join(main, ".fwx")))
r = st(wt, "resolve", "--json", session=None)
s.eq("protected, first phase: the live phase folder is the worktree's", os.path.realpath(json.loads(r.stdout)["phase_dir"]) if r.stdout else None,
     os.path.realpath(os.path.join(wt, PHASE_REL % "01-alpha")))
# a later commit: the live copy is the worktree's, so a stage row written there is what the next commit takes
helpers.fwx(wt, "stage", os.path.join(wt, PHASE_REL % "01-alpha"), "premortem", "--why", "light critique")
clean("protected: a second commit", commit(wt, "fwx: critique"), 0)
s.eq("protected: a second commit is a second commit on the phase branch", subjects(wt)[:2], ["fwx: critique", "fwx: part 1 starts"])
s.ok("protected: the stage row is in the commit", "premortem" in show(wt, "HEAD:%s/audit.tsv" % (PHASE_REL % "01-alpha")))
r = commit(wt, "fwx: nothing changed")
clean("protected: nothing changed", r, 0, "nothing to commit in %s" % wt)
s.eq("protected: nothing changed, no commit was made", subjects(wt)[0], "fwx: critique")
s.eq("protected: the default branch is still untouched", helpers.git(main, "rev-parse", "master").strip(), base)

# a protected default branch whose `.fwx/` is already tracked (a later phase): the new phase was made in the main checkout
main2 = toy(True, {".fwx/PROJECT.md": "# p\n", PHASE_REL % "01-old" + "/context.md": "old\n"})
wt2 = helpers.add_worktree(main2, "fwx-phase")
st(main2, "new-phase", "next", session=None)
base2 = helpers.git(main2, "rev-parse", "master").strip()
clean("protected, later phase: commit from the phase worktree", commit(wt2, "fwx: part 1 starts"), 0)
s.ok("protected, later phase: the new phase is in the branch and the old one is still there",
     PHASE_REL % "02-next" + "/context.md" in head_files(wt2) and PHASE_REL % "01-old" + "/context.md" in head_files(wt2), str(head_files(wt2)))
s.ok("protected, later phase: the new phase left the main checkout", not os.path.exists(os.path.join(main2, PHASE_REL % "02-next")))
s.eq("protected, later phase: nothing was committed on the default branch", helpers.git(main2, "rev-parse", "master").strip(), base2)

# a worktree that is itself on the default branch (the main checkout is on another one) is no place for it either
main5 = toy(True)
helpers.write(main5, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"default_branch": "master", "default_branch_protected": True}}))
st(main5, "new-phase", "alpha", session=None)
helpers.git(main5, "checkout", "-q", "-b", "other")
wt5 = os.path.join(helpers.mkdtemp("fwx-wt-"), "on-default")
helpers.git(main5, "worktree", "add", "-q", wt5, "master")
r = commit(wt5, "fwx: part 1 starts")
clean("protected: a worktree on the default branch", r, 1)
s.ok("protected: a worktree on the default branch, the message says so", "default branch" in r.stderr, r.stderr)
s.eq("protected: a worktree on the default branch, nothing was committed", subjects(main5, "master"), ["toy"])

# a move that fails (the worktree's `.fwx/` cannot be written) is one line and no traceback, and running it again takes the rest
if os.geteuid() != 0:  # root writes into a read-only folder
    main6 = toy(True)
    wt6 = helpers.add_worktree(main6, "fwx-phase")
    st(main6, "new-phase", "alpha", session=None)
    os.makedirs(os.path.join(wt6, ".fwx"))
    os.chmod(os.path.join(wt6, ".fwx"), 0o500)
    r = commit(wt6, "fwx: part 1 starts")
    clean("protected: a move that fails", r, 1)
    s.ok("protected: a move that fails, the message says to run it again", "run it again" in r.stderr, r.stderr)
    os.chmod(os.path.join(wt6, ".fwx"), 0o700)
    clean("protected: run again after the fix", commit(wt6, "fwx: part 1 starts"), 0)
    s.ok("protected: run again after the fix, the phase documents are committed", PHASE_REL % "01-alpha" + "/context.md" in head_files(wt6))

# not protected: the main checkout's own branch, as the skill's old line did
main3 = toy(False)
st(main3, "new-phase", "alpha", session=None)
clean("not protected: commit", commit(main3, "fwx: part 1 starts"), 0)
s.eq("not protected: the commit is on the main checkout's branch", subjects(main3)[0], "fwx: part 1 starts")
s.ok("not protected: the phase documents are in it", PHASE_REL % "01-alpha" + "/context.md" in head_files(main3))
r = commit(main3, "again")
clean("not protected: nothing changed", r, 0, "nothing to commit in %s" % main3)

# `.fwx/` ignored by the project's git: its history is elsewhere, so the command refuses and names the other one
main4 = toy(False, {".gitignore": ".fwx/\n"})
st(main4, "new-phase", "alpha", session=None)
base4 = helpers.git(main4, "rev-parse", "master").strip()
r = commit(main4, "fwx: part 1 starts")
clean("ignored: refused", r, 1)
s.ok("ignored: the message names `forge commit`", "forge commit" in r.stderr, r.stderr)
s.eq("ignored: nothing was committed", helpers.git(main4, "rev-parse", "master").strip(), base4)
clean("no `.fwx/` at all: refused", commit(toy(False), "x"), 1)
clean("commit with no -m: usage error", st(main3, "commit", session=None, env=IDENT), 2)

# ---- outside a git repository: exit 2 -------------------------------------------------------------------------------
nogit =helpers.mkdtemp("fwx-nogit-")
for args in (["resolve"], ["list"], ["use", "--root"], ["new-phase", "x"], ["new-milestone"], ["decision", "--decision", "a", "--why", "b",
             "--support", "chosen"]):
    r = st(nogit, *args)
    clean("outside a repository: %s" % " ".join(args), r, 2)
    s.ok("outside a repository: %s names git" % args[0], "git" in r.stderr.lower(), r.stderr)
s.eq("outside a repository: nothing written", tree(nogit), [])

s.done()
