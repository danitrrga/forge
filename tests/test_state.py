#!/usr/bin/env python3
"""lib/fwx/state.py, the core: where `.fwx/` is, its subproject, milestone, phase and subphase folders, the session
file, and the TSV writers (decisions and the single writer of audit.tsv).

Seen red before state.py existed (the file was not there):
  ImportError: cannot import name 'state' from 'fwx' (lib/fwx/__init__.py)

Controls, each seen red on a copy of the repo with state.py changed in one place (128 checks each, first FAIL line shown):
  - plan_root resolved against the cwd's top level, not the main checkout (the plan's control; the run is cut after the
    plan_root section because later sections build on it):
      FAIL: plan_root from a subfolder of a linked worktree is <main>/.fwx: got '<wt>/feature/.fwx', want '<main>/.fwx'
  - plan_root always the main checkout (the variant's control):
      FAIL: protected + tracked: plan_root from the session worktree is <wt>/.fwx: got '<main>/.fwx', want '<wt>/phase-branch/.fwx'
  - the variant taken without the protection signal / without `.fwx/` being tracked:
      FAIL: not protected + tracked: stays <main>/.fwx: got '<wt>/phase-branch/.fwx', want '<main>/.fwx'
      FAIL: protected + not tracked: stays <main>/.fwx: got '<wt>/other/.fwx', want '<main>/.fwx'
  - no support validation:
      FAIL: support 'maybe' raises StateError (row with support 'maybe' was written): returned 'D3'
      FAIL: support 'maybe': the file is byte for byte the same: got b'date\tid\t...
  - no cell cleaning / cleaning without the quote:
      FAIL: tab, newline and CR become spaces: got {'a': 't', 'b': 'ab'}, want {'a': 't ab', 'b': 'line break  and cr'}
      FAIL: a leading = gets a quote: got '=1+1', want "'=1+1"
  - stage without sha not filled in:
      FAIL: stage without sha writes the HEAD of the repo (sha empty, expected <HEAD>): got '', want '<HEAD>'
  - subphases in alphabetical order:
      FAIL: subphases: 03.2-b before 03.10-c, folders NN.M-slug only: got ['03.1-a', '03.10-c', '03.2-b'], want [...]
  - phases pattern `^\d+(\.\d+)?-` (NN and NN.M only), and phases in alphabetical order:
      FAIL: phases: numeric tuple order, NN, NN.M and NN.M.K: got ['03-x', '12.2-a', '12.3-c', '12.10-d'], want ['03-x', '12.2-a', '12.2.1-b', ...]
      FAIL: phases: numeric tuple order, NN, NN.M and NN.M.K: got ['03-x', '12.10-d', '12.2-a', '12.2.1-b', '12.3-c'], want [...]
  - has_subprojects always false, and always true (both directions):
      FAIL: has_subprojects: true with a subfolder
      FAIL: has_subprojects: false when subprojects/ is empty
  - open_phases keeps a closed phase, and keeps a cancelled one:
      FAIL: open_phases: not closed, not cancelled, a new phase is open, a reopened one too: got ['01-done', '02-new', ...]
  - the session file in the worktree's own git dir instead of the common dir:
      FAIL: a session written from a worktree lands in the main checkout's git dir: <main>/.git/fwx/sessions/s1.json
  - no kind check, no stage-word check, evidence accepted without a sha, no supersedes check, no header check, a session
    phase outside `.fwx/` accepted, a path-like session id accepted, next_report always 1, milestones in lexical order,
    resolve never picking the only open phase: each fails the check named by its label ("a kind outside AUDIT_KINDS: returned
    None", "evidence without a sha: returned None", "supersedes an id that does not exist: returned 'D3'", "append_row against
    a file with another header: returned None", "write_session with a phase outside .fwx: returned None", "a session id that is
    a path: returned '../evil'", "next_report is the first free number: got 'report-1.md', want 'report-2.md'", "milestones in
    numeric order...: got ['v1', 'v10', 'v2']", "resolve without a binding returns the only open phase: got (None, [...])").
  - header and row in two os.write calls:
      FAIL: first write (header and row): os.write calls: got 2, want 1
"""
import json
import os
import re
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import state  # noqa: E402

for k in [k for k in os.environ if k.startswith("GIT_")]:  # a hook run exports GIT_DIR: not for these toy repos
    del os.environ[k]
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)

s = helpers.Suite()


def refuses(label, fn, needle=None):
    """fn raises StateError (whose message holds `needle`); anything else, or nothing, is a FAIL."""
    try:
        r = fn()
    except state.StateError as e:
        return s.ok(label, needle is None or needle in str(e), "message %r lacks %r" % (str(e), needle))
    except Exception as e:  # noqa: BLE001
        return s.ok(label, False, "raised %s, not StateError: %s" % (type(e).__name__, e))
    return s.ok(label, False, "returned %r" % (r,))


def read(p):
    with open(p, "rb") as f:
        return f.read()


def jread(p):
    try:
        return json.loads(read(p))
    except (OSError, ValueError):
        return None


def mk(*parts):
    p = os.path.join(*parts)
    os.makedirs(p, exist_ok=True)
    return p


def rel(p, base):
    return os.path.relpath(str(p), base)


# ---- plan_root: against the main checkout -------------------------------------------------------------------------
main = helpers.toy_repo()
wt = helpers.add_worktree(main, "feature")
sub = mk(wt, "deep", "er")
s.eq("plan_root from the main checkout", str(state.plan_root(cwd=main)), os.path.join(main, ".fwx"))
s.eq("plan_root from a subfolder of a linked worktree is <main>/.fwx",
     str(state.plan_root(cwd=sub)), os.path.join(main, ".fwx"))
s.eq("plan_root from the worktree root", str(state.plan_root(cwd=wt)), os.path.join(main, ".fwx"))
s.ok("plan_root creates nothing", not os.path.exists(os.path.join(main, ".fwx")) and not os.path.exists(os.path.join(wt, ".fwx")))
try:
    state.plan_root(cwd=helpers.mkdtemp("fwx-nogit-"))
    s.ok("plan_root outside a git repository raises", False, "returned")
except state.config.ConfigError as e:
    s.ok("plan_root outside a git repository raises ConfigError naming the folder", "not in a git repository" in str(e))

# ---- plan_root, the protected-default-branch variant ---------------------------------------------------------------
# `.fwx/` is tracked and the profile says the default branch is protected: the session's worktree holds the live copy.
pmain = helpers.toy_repo({"README": "toy\n", ".fwx/PROJECT.md": "# toy\n"})
pwt = helpers.add_worktree(pmain, "phase-branch")
psub = mk(pwt, "src")
helpers.write(pmain, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"default_branch_protected": True}}))
s.eq("protected + tracked: plan_root from the session worktree is <wt>/.fwx",
     str(state.plan_root(cwd=pwt)), os.path.join(pwt, ".fwx"))
s.eq("protected + tracked: from a subfolder of the session worktree", str(state.plan_root(cwd=psub)), os.path.join(pwt, ".fwx"))
s.eq("protected + tracked: from the main checkout itself", str(state.plan_root(cwd=pmain)), os.path.join(pmain, ".fwx"))
helpers.write(pmain, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"default_branch_protected": False}}))
s.eq("not protected + tracked: stays <main>/.fwx", str(state.plan_root(cwd=pwt)), os.path.join(pmain, ".fwx"))
os.remove(os.path.join(pmain, ".claude", "fwx.json"))
s.eq("no signal at all (no fwx.json): stays <main>/.fwx", str(state.plan_root(cwd=pwt)), os.path.join(pmain, ".fwx"))
helpers.write(pmain, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"default_branch_protected": True}}))
umain = helpers.toy_repo()  # protected, but `.fwx/` is not tracked: the main checkout keeps it
uwt = helpers.add_worktree(umain, "other")
helpers.write(umain, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"default_branch_protected": True}}))
s.eq("protected + not tracked: stays <main>/.fwx", str(state.plan_root(cwd=uwt)), os.path.join(umain, ".fwx"))

# ---- subprojects, scope_root ----------------------------------------------------------------------------------------
sp = helpers.toy_repo()
root = os.path.join(sp, ".fwx")
s.ok("has_subprojects: false when .fwx/ is missing", state.has_subprojects(root) is False)
mk(root)
s.ok("has_subprojects: false when subprojects/ is missing", state.has_subprojects(root) is False)
mk(root, "subprojects")
s.ok("has_subprojects: false when subprojects/ is empty", state.has_subprojects(root) is False)
helpers.write(root, "subprojects/README", "a file is not a subproject\n")
s.ok("has_subprojects: a file in subprojects/ is not an entry", state.has_subprojects(root) is False)
mk(root, "subprojects", "web")
mk(root, "subprojects", "api")
s.ok("has_subprojects: true with a subfolder", state.has_subprojects(root) is True)
s.eq("subprojects lists the subfolders, sorted", state.subprojects(root), ["api", "web"])
s.eq("subprojects of a root with none", state.subprojects(os.path.join(sp, "nothing")), [])
s.eq("scope_root without subproject is the root", str(state.scope_root(root)), root)
s.eq("scope_root of a subproject", str(state.scope_root(root, "web")), os.path.join(root, "subprojects", "web"))
refuses("scope_root refuses a path in the subproject name", lambda: state.scope_root(root, "../x"))
refuses("scope_root refuses a slash in the subproject name", lambda: state.scope_root(root, "a/b"))

# ---- milestones -------------------------------------------------------------------------------------------------------
scope = mk(sp, "ms")
s.eq("milestones of a scope with none", state.milestones(scope), [])
s.eq("current_milestone of a scope with none", state.current_milestone(scope), None)
for m in ("v2", "v10", "v1"):
    mk(scope, "milestones", m)
mk(scope, "milestones", "notes")
helpers.write(scope, "milestones/v3", "a file\n")
s.eq("milestones in numeric order, only vN folders", state.milestones(scope), ["v1", "v2", "v10"])
s.eq("current_milestone is the highest number (v10, not v2)", state.current_milestone(scope), "v10")

# ---- phases, subphases ----------------------------------------------------------------------------------------------
ph = mk(sp, "ph")
pdir = os.path.join(ph, "milestones", "v1", "phases")
for n in ("12.10-d", "12.3-c", "12.2.1-b", "12.2-a", "03-x"):
    mk(pdir, n)
mk(pdir, "notes")
mk(pdir, "7-")
helpers.write(pdir, "05-file", "a file\n")
got = [os.path.basename(str(p)) for p in state.phases(ph, "v1")]
s.eq("phases: numeric tuple order, NN, NN.M and NN.M.K", got, ["03-x", "12.2-a", "12.2.1-b", "12.3-c", "12.10-d"])
s.eq("phases of a milestone that does not exist", state.phases(ph, "v9"), [])
s.ok("phases returns Paths under the milestone", all(os.path.dirname(str(p)) == pdir for p in state.phases(ph, "v1")))
refuses("phases refuses a milestone name that climbs out", lambda: state.phases(ph, "../v1"))
x = mk(pdir, "03-x")
for n in ("03.10-c", "03.2-b", "03.1-a"):
    mk(x, n)
mk(x, "research")
mk(x, "3-nodot")
got = [os.path.basename(str(p)) for p in state.subphases(x)]
s.eq("subphases: 03.2-b before 03.10-c, folders NN.M-slug only", got, ["03.1-a", "03.2-b", "03.10-c"])
s.eq("subphases of a phase with none", state.subphases(mk(pdir, "12.3-c")), [])

# ---- phase_paths ------------------------------------------------------------------------------------------------------
pp = state.phase_paths(x)
s.eq("phase_paths keys", sorted(pp), sorted(["context", "decisions", "research", "demo", "premortem", "plan", "postmortem",
                                              "state", "audit", "next_report"]))
s.eq("phase_paths names", {k: os.path.basename(str(v)) for k, v in pp.items()},
     {"context": "context.md", "decisions": "decisions.tsv", "research": "research", "demo": "demo",
      "premortem": "premortem.md", "plan": "plan.md", "postmortem": "postmortem.md", "state": "state.md",
      "audit": "audit.tsv", "next_report": "report-1.md"})
s.ok("phase_paths values are Paths inside the folder", all(os.path.dirname(str(v)) == x for v in pp.values()))
helpers.write(x, "report-1.md", "r\n")
helpers.write(x, "report-3.md", "r\n")
s.eq("next_report is the first free number", os.path.basename(str(state.phase_paths(x)["next_report"])), "report-2.md")
s.ok("phase_paths creates nothing", not os.path.exists(os.path.join(x, "context.md")))

# ---- append_row / read_rows, the cell cleaning ----------------------------------------------------------------------
tw = helpers.mkdtemp("fwx-tsv-")
f = os.path.join(tw, "t.tsv")
state.append_row(f, ("a", "b"), ["plain", "x"])
s.eq("header on the first write, then the row", read(f), b"a\tb\nplain\tx\n")
state.append_row(f, ("a", "b"), {"b": "dict", "a": "keyed"})
s.eq("a dict of values is placed by column", state.read_rows(f)[1], {"a": "keyed", "b": "dict"})
state.append_row(f, ("a", "b"), ["t\tab", "line\nbreak\r\nand cr"])
state.append_row(f, ("a", "b"), ["=1+1", "ok"])
state.append_row(f, ("a", "b"), ["+x", "-y"])
state.append_row(f, ("a", "b"), ["@z", '"q'])
state.append_row(f, ("a", "b"), [-9, 0])
rows = state.read_rows(f)
s.eq("tab, newline and CR become spaces", rows[2], {"a": "t ab", "b": "line break  and cr"})
s.eq("a leading = gets a quote", rows[3]["a"], "'=1+1")
s.eq("a leading + - @ \" each get a quote", [rows[4]["a"], rows[4]["b"], rows[5]["a"], rows[5]["b"]],
     ["'+x", "'-y", "'@z", "'\"q"])
s.eq("a number is not a formula: int -9 stays -9", rows[6], {"a": "-9", "b": "0"})
lines = read(f).decode().split("\n")
s.eq("every row is one line with one fewer tab than the columns", [l.count("\t") for l in lines[:-1]], [1] * 8)
s.eq("read_rows of a missing file", state.read_rows(os.path.join(tw, "nope.tsv")), [])
before = read(f)
refuses("append_row with the wrong cell count", lambda: state.append_row(f, ("a", "b"), ["only one"]))
refuses("append_row against a file with another header", lambda: state.append_row(f, ("a", "c"), ["1", "2"]), "header")
s.eq("a refused append leaves the file byte for byte", read(f), before)
refuses("append_row into a folder that does not exist", lambda: state.append_row(os.path.join(tw, "no", "t.tsv"), ("a",), ["1"]))
# one os.write per row, header included (the row is one record: a concurrent writer cannot split it)
real_write, calls = os.write, []
os.write = lambda fd, data: (calls.append(data), real_write(fd, data))[1]
try:
    f2 = os.path.join(tw, "one.tsv")
    state.append_row(f2, ("a", "b"), ["1", "2"])
    first = len(calls)
    state.append_row(f2, ("a", "b"), ["3", "4"])
    second = len(calls) - first
finally:
    os.write = real_write
s.eq("first write (header and row): os.write calls", first, 1)
s.eq("later write: os.write calls", second, 1)
# many threads appending: no row is torn
f3 = os.path.join(tw, "many.tsv")
state.append_row(f3, ("w", "i", "pad"), ["-", "-", "p" * 300])  # the header exists: see append_row's docstring


def burst(n):
    for i in range(40):
        state.append_row(f3, ("w", "i", "pad"), [str(n), str(i), "p" * 300])


ts = [threading.Thread(target=burst, args=(n,)) for n in range(6)]
[t.start() for t in ts]
[t.join() for t in ts]
rows = state.read_rows(f3)
s.eq("6 threads x 40 rows: every row arrived whole", len(rows) - 1, 240)
s.ok("6 threads x 40 rows: no torn row", all(len(r["pad"]) == 300 for r in rows[1:]))
s.eq("6 threads x 40 rows: one header", sum(1 for l in read(f3).decode().split("\n") if l.startswith("w\ti\t")), 1)

# ---- append_decision --------------------------------------------------------------------------------------------------
dd = helpers.mkdtemp("fwx-dec-")
dec = os.path.join(dd, "decisions.tsv")
i1 = state.append_decision(dec, decision="use sqlite", why="one file", support="chosen", rejected="postgres", source="turn 3")
s.eq("first decision id", i1, "D1")
s.eq("header is the decision columns", read(dec).decode().split("\n")[0], "\t".join(state.DECISION_COLUMNS))
i2 = state.append_decision(dec, decision="no cache", why="not needed yet", support="agent-assumption")
s.eq("second decision id", i2, "D2")
row = state.read_rows(dec)[0]
s.eq("the row holds what was passed", [row[k] for k in ("id", "decision", "why", "rejected", "support", "source", "supersedes")],
     ["D1", "use sqlite", "one file", "postgres", "chosen", "turn 3", ""])
s.ok("date is ISO 8601 UTC with seconds", re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["date"]) is not None, row["date"])
before = read(dec)
refuses("support 'maybe' raises StateError (row with support 'maybe' was written)",
        lambda: state.append_decision(dec, decision="d", why="w", support="maybe"), "support")
s.eq("support 'maybe': the file is byte for byte the same", read(dec), before)
for what, kw in (("empty decision", {"decision": "", "why": "w"}), ("blank decision", {"decision": "  ", "why": "w"}),
                 ("empty why", {"decision": "d", "why": ""})):
    refuses(what, lambda kw=kw: state.append_decision(dec, support="chosen", **kw))
refuses("supersedes an id that does not exist", lambda: state.append_decision(dec, decision="d", why="w", support="chosen", supersedes="D9"), "D9")
s.eq("every refusal left the file byte for byte", read(dec), before)
i3 = state.append_decision(dec, decision="postgres after all", why="scale", support="approved", supersedes="D1")
s.eq("a correction supersedes an existing row", (i3, state.read_rows(dec)[2]["supersedes"]), ("D3", "D1"))
fresh = os.path.join(dd, "fresh.tsv")
refuses("a refused first write creates no file", lambda: state.append_decision(fresh, decision="d", why="w", support="maybe"))
s.ok("a refused first write: the file does not exist", not os.path.exists(fresh))
adr = os.path.join(dd, "adr.tsv")
s.eq("adr.tsv ids are A<n>", [state.append_decision(adr, decision="d%d" % n, why="w", support="chosen") for n in (1, 2)], ["A1", "A2"])
for sup in state.SUPPORT:
    state.append_decision(dec, decision="s", why="w", support=sup)
s.eq("every SUPPORT value is accepted", len(state.read_rows(dec)), 7)

# ---- append_audit, last_stage ----------------------------------------------------------------------------------------
ar = helpers.toy_repo()
head = helpers.git(ar, "rev-parse", "HEAD").strip()
ad = mk(ar, ".fwx", "milestones", "v1", "phases", "01-a")
aud = os.path.join(ad, "audit.tsv")
s.eq("last_stage without an audit.tsv", state.last_stage(ad), None)
state.append_audit(ad, "stage", "executing go", cwd=ar)
rows = state.read_rows(aud)
s.eq("stage without sha writes the HEAD of the repo (sha empty, expected <HEAD>)", rows[0]["sha"], head)
s.eq("the kind and the detail are kept", (rows[0]["kind"], rows[0]["detail"]), ("stage", "executing go"))
s.eq("header is the audit columns", read(aud).decode().split("\n")[0], "\t".join(state.AUDIT_COLUMNS))
s.eq("last_stage is the first word of the last stage row", state.last_stage(ad), "executing")
state.append_audit(ad, "round", "fix round 1", rc=0)
state.append_audit(ad, "evidence", "checks", rc=1, sha="abc1234")
s.eq("round and evidence rows do not change last_stage", state.last_stage(ad), "executing")
rows = state.read_rows(aud)
s.eq("evidence keeps its sha and rc", (rows[2]["sha"], rows[2]["rc"]), ("abc1234", "1"))
s.eq("round needs no sha: empty", rows[1]["sha"], "")
state.append_audit(ad, "stage", "reviewing", sha="deadbee")
s.eq("an explicit sha is kept on a stage row", state.read_rows(aud)[3]["sha"], "deadbee")
state.append_audit(ad, "stage", "closed", cwd=ar)
s.eq("last_stage follows the last stage row", state.last_stage(ad), "closed")
s.eq("cwd=None takes the current directory's HEAD: a stage from inside the repo",
     (lambda: (os.chdir(ar), state.append_audit(ad, "stage", "executing again"), state.read_rows(aud)[-1]["sha"])[2])(), head)
os.chdir(helpers.ROOT)
state.append_audit(ad, "round", "a\tb\nc =x", rc="-1")
s.eq("audit cells are cleaned", state.read_rows(aud)[-1]["detail"], "a b c =x")
before = read(aud)
refuses("stage with an empty detail", lambda: state.append_audit(ad, "stage", "", cwd=ar))
refuses("stage with a detail that does not start with a stage word", lambda: state.append_audit(ad, "stage", "Executing go", cwd=ar), "stage")
refuses("stage with a detail starting with a digit", lambda: state.append_audit(ad, "stage", "2 go", cwd=ar))
refuses("stage with a detail starting with a space", lambda: state.append_audit(ad, "stage", " executing", cwd=ar))
refuses("evidence without a sha", lambda: state.append_audit(ad, "evidence", "checks", rc=0), "sha")
refuses("evidence with an empty sha", lambda: state.append_audit(ad, "evidence", "checks", sha=""), "sha")
refuses("stage without a sha outside a repository",
        lambda: state.append_audit(ad, "stage", "executing", cwd=helpers.mkdtemp("fwx-nogit-")), "HEAD")
refuses("a kind outside AUDIT_KINDS", lambda: state.append_audit(ad, "note", "hello"), "note")
s.eq("every refusal left audit.tsv byte for byte", read(aud), before)
nf = mk(ar, "other-dir")
refuses("an unknown kind writes no file", lambda: state.append_audit(nf, "bogus", "x"))
s.ok("an unknown kind: audit.tsv was not created", not os.path.exists(os.path.join(nf, "audit.tsv")))
s.eq("AUDIT_KINDS", state.AUDIT_KINDS, ("evidence", "stage", "round"))
s.eq("AUDIT_COLUMNS", state.AUDIT_COLUMNS, ("date", "kind", "sha", "detail", "rc"))

# ---- open_phases ------------------------------------------------------------------------------------------------------
op = helpers.mkdtemp("fwx-open-")
phd = os.path.join(op, "milestones", "v1", "phases")
for n, stages in (("01-done", ["executing", "closed"]), ("02-new", []), ("03-live", ["executing"]),
                  ("04-dropped", ["discuss", "cancelled"]), ("05-reopened", ["closed", "executing"])):
    d = mk(phd, n)
    for st in stages:
        state.append_audit(d, "stage", st, sha="abc1234")
mk(op, "milestones", "v0", "phases", "01-old")  # an older milestone is not looked at
state.append_audit(os.path.join(op, "milestones", "v0", "phases", "01-old"), "stage", "executing", sha="abc1234")
got = [os.path.basename(str(p)) for p in state.open_phases(op)]
s.eq("open_phases: not closed, not cancelled, a new phase is open, a reopened one too", got, ["02-new", "03-live", "05-reopened"])
s.eq("open_phases of an empty scope", state.open_phases(mk(op, "empty")), [])

# ---- session ids and the session file -------------------------------------------------------------------------------
s.eq("session_id explicit wins", state.session_id("abc"), "abc")
os.environ["CLAUDE_CODE_SESSION_ID"] = "from-env"
s.eq("session_id from CLAUDE_CODE_SESSION_ID", state.session_id(), "from-env")
s.eq("explicit beats the environment", state.session_id("x1"), "x1")
del os.environ["CLAUDE_CODE_SESSION_ID"]
s.eq("session_id with neither", state.session_id(), None)
refuses("a session id that is a path", lambda: state.session_id("../evil"))

sm = helpers.toy_repo()
sw = helpers.add_worktree(sm, "sess")
swsub = mk(sw, "a", "b")
s.eq("read_session before any write", state.read_session(cwd=sm, session="s1"), None)
s.eq("read_session without a session id", state.read_session(cwd=sm), None)
phase = mk(sm, ".fwx", "milestones", "v1", "phases", "01-a")
state.write_session(cwd=swsub, session="s1", subproject="web", phase_dir=phase)
fpath = os.path.join(sm, ".git", "fwx", "sessions", "s1.json")
s.ok("a session written from a worktree lands in the main checkout's git dir", os.path.isfile(fpath), fpath)
s.eq("the file holds exactly {subproject, phase_dir}", jread(fpath),
     {"subproject": "web", "phase_dir": os.path.join(".fwx", "milestones", "v1", "phases", "01-a")})
s.eq("the session read from the main checkout", state.read_session(cwd=sm, session="s1"),
     {"subproject": "web", "phase_dir": os.path.join(".fwx", "milestones", "v1", "phases", "01-a")})
s.eq("the session read from another worktree folder", state.read_session(cwd=swsub, session="s1")["subproject"], "web")
s.ok("nothing .fwx or fwx-state is written in the worktree", not os.path.exists(os.path.join(sw, ".fwx")))
s.eq("no temp file is left next to the session", sorted(os.listdir(os.path.dirname(fpath))) if os.path.isdir(os.path.dirname(fpath)) else None, ["s1.json"])
state.write_session(cwd=sm, session="s1", subproject=None, phase_dir=None)
s.eq("a root session with no phase is two nulls", jread(fpath), {"subproject": None, "phase_dir": None})
os.environ["CLAUDE_CODE_SESSION_ID"] = "s2"
state.write_session(cwd=sm, subproject=None, phase_dir=phase)
s.ok("write_session takes the id from the environment", os.path.isfile(os.path.join(sm, ".git", "fwx", "sessions", "s2.json")))
del os.environ["CLAUDE_CODE_SESSION_ID"]
refuses("write_session without a session id", lambda: state.write_session(cwd=sm, subproject=None, phase_dir=phase), "session")
refuses("write_session with a phase outside .fwx", lambda: state.write_session(cwd=sm, session="s3", subproject=None, phase_dir=helpers.mkdtemp("fwx-out-")))
helpers.write(os.path.dirname(fpath), "s1.json", "{not json")
refuses("a corrupt session file", lambda: state.read_session(cwd=sm, session="s1"), "s1.json")

# ---- resolve ----------------------------------------------------------------------------------------------------------
rm = helpers.toy_repo()
rw = helpers.add_worktree(rm, "res")
r0 = state.resolve(cwd=rw, session="r1")
s.eq("resolve with nothing in .fwx", (r0["main_checkout"], r0["plan_root"], r0["has_subprojects"], r0["subproject"],
                                       r0["milestone"], r0["phase_dir"], r0["subphases"], r0["candidates"]),
     (rm, os.path.join(rm, ".fwx"), False, None, None, None, [], []))
a = mk(rm, ".fwx", "milestones", "v1", "phases", "01-a")
b = mk(rm, ".fwx", "milestones", "v2", "phases", "01-b")
c = mk(rm, ".fwx", "milestones", "v2", "phases", "02-c")
state.append_audit(c, "stage", "executing", sha="abc1234")
r1 = state.resolve(cwd=rw, session="r1")
s.eq("resolve: the current milestone is the highest", r1["milestone"], "v2")
s.eq("resolve with two open phases and no binding: candidates named, no phase", (r1["phase_dir"], r1["candidates"]), (None, [b, c]))
state.append_audit(b, "stage", "closed", sha="abc1234")
r2 = state.resolve(cwd=rw, session="r1")
s.eq("resolve without a binding returns the only open phase", (r2["phase_dir"], r2["candidates"]), (c, [c]))
s.eq("resolve writes nothing: the session is still unbound", state.read_session(cwd=rm, session="r1"), None)
s.eq("resolve paths are those of the phase", r2["paths"].get("state"), os.path.join(c, "state.md"))
s.eq("resolve: no subphases yet", r2["subphases"], [])
mk(c, "02.1-sub")
s.eq("resolve lists the subphases of the open phase", state.resolve(cwd=rw, session="r1")["subphases"], [os.path.join(c, "02.1-sub")])
state.write_session(cwd=rw, session="r1", subproject=None, phase_dir=a)
r3 = state.resolve(cwd=rw, session="r1")
s.eq("resolve: a bound phase wins over the open one", (r3["phase_dir"], r3["milestone"]), (a, "v1"))
mk(a, "01.1-first")
s.eq("resolve lists the subphases of the bound phase", state.resolve(cwd=rm, session="r1")["subphases"], [os.path.join(a, "01.1-first")])
mk(rm, ".fwx", "subprojects", "web", "milestones", "v1", "phases", "01-w")
state.write_session(cwd=rw, session="r1", subproject="web", phase_dir=None)
r4 = state.resolve(cwd=rw, session="r1")
s.eq("resolve: a bound subproject sets the scope", (r4["has_subprojects"], r4["subproject"], r4["milestone"], r4["phase_dir"]),
     (True, "web", "v1", os.path.join(rm, ".fwx", "subprojects", "web", "milestones", "v1", "phases", "01-w")))
state.write_session(cwd=rw, session="r1", subproject=None, phase_dir=a)
os.rename(a, a + "-gone")
r5 = state.resolve(cwd=rw, session="r1")
s.eq("resolve: a session whose phase folder is gone falls back to the open phase", r5["phase_dir"], c)

s.done()
