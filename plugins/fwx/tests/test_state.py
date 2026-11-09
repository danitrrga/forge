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

U3 (new_milestone, new_phase, new_subphase, cancel_phase, check_state, check_report; 236 checks). Seen red before the code
existed, on state.py as of U1:
  AttributeError: module 'fwx.state' has no attribute '_read_template'   (the test hooks that reader to learn which templates are copied)
Controls, each seen red on a copy with state.py (or a template) changed in one place; first FAIL lines shown:
  - mkdir with exist_ok=True: the second "a" would share 01-a; here the exclusive create of context.md stops it:
      FileExistsError: [Errno 17] File exists: '<toy>/.fwx/milestones/v1/phases/01-a/context.md'
  - no look at the numbers in use (the stale-listing case, another slug):
      FAIL: new_phase: a stale listing (number 1 taken, slug differs) tries the next, never two phases with one number: got '02-a', want '03-a'
  - cancel_phase deleting the parent:
      FAIL: cancel_phase: neighbour phase 02-b missing
  - cancel_phase without the premortem.md / plan.md refusal:
      FAIL: cancel_phase refuses once premortem.md exists: returned None
  - cancel_phase not unbinding sessions:
      FAIL: cancel_phase unbinds the session that pointed to it, keeping its subproject: got ({'subproject': None, 'phase_dir': '.fwx/milestones/v1/phases/01-a'}, ...)
  - cancel_phase accepting any folder: the run crashes (FileNotFoundError: '<tmp>' -> '<toy>/.fwx/milestones/v1/phases/20-link') after deleting src/01-x
  - check_report without the sha search, and with the first evidence row instead of the last:
      FAIL: check_report: a report without the evidence sha is an error (report without evidence sha passed): []
      FAIL: check_report: the full sha of the last evidence row passes: got (['<tmp>/report-1.md does not cite the sha of the last evidence row (ffffffffffff)'], []), want ([], [])
  - the length never warning / the length an error:
      FAIL: check_state: 112 lines warns, no error: got ([], []), want ([], ['112 lines, target 100'])
      FAIL: check_report: 41 lines is a warning, not an error: got (['41 lines, target 40'], []), want ([], ['41 lines, target 40'])
  - the leading referent comment kept in a copy:
      FAIL: a copied template loses its leading referent comment line (context.md): <!-- referent: none, own text: ...
  - TSV headers not written at creation:
      FAIL: new_phase: decisions.tsv holds exactly its header: got '', want 'date\tid\tdecision\t...'
  - no PROJECT.md (FileNotFoundError, the test reads it), no fallback to the session's subproject
    (FAIL: new_phase without --subproject keeps the session's subproject ...), session not bound
    (FAIL: new_phase binds the session (from the environment): got None, ...), next number not highest + 1
    ("got '06-n', want '08-n'"), subphase number taken like a phase's ("got ('03.1-a', '03.4-b'), want ('03.1-a', '03.2-b')"),
    new_milestone overwriting (raised FileExistsError, not StateError), slug not validated (9 FAILs, "bad slug '': returned ...").
  - templates: a trailing comma in plan.md's JSON ("FAIL: templates/phase/plan.md: frontmatter is JSON: templates/phase/plan.md:
    frontmatter is not JSON"), a heading dropped from postmortem.md ("the section headings of 3.3, in order: got [...]"), a
    copied template renamed (StateError: the template <tmp>/templates/phase/context.md cannot be read ...).
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


# ======================================================================================================================
# U3: new_milestone, new_phase, new_subphase, cancel_phase, check_state, check_report
# ======================================================================================================================
TEMPLATES = os.path.join(helpers.ROOT, "templates")
HEADERS = {"decisions.tsv": "\t".join(state.DECISION_COLUMNS) + "\n", "audit.tsv": "\t".join(state.AUDIT_COLUMNS) + "\n"}

# ---- new_phase in an empty repo -------------------------------------------------------------------------------------
read_templates = []
_real_read_template = state._read_template
state._read_template = lambda name: (read_templates.append(name), _real_read_template(name))[1]  # which templates are copied

nm = helpers.toy_repo()
nw = helpers.add_worktree(nm, "np")
os.environ["CLAUDE_CODE_SESSION_ID"] = "np1"
p1 = state.new_phase("a", cwd=nw)
os.environ.pop("CLAUDE_CODE_SESSION_ID")
fr = os.path.join(nm, ".fwx")
s.eq("new_phase in an empty repo: the folder is <main>/.fwx/milestones/v1/phases/01-a", str(p1),
     os.path.join(fr, "milestones", "v1", "phases", "01-a"))
s.ok("new_phase: .fwx/PROJECT.md is created from the template", os.path.isfile(os.path.join(fr, "PROJECT.md")))
s.ok("new_phase: milestones/v1/MILESTONE.md is created", os.path.isfile(os.path.join(fr, "milestones", "v1", "MILESTONE.md")))
s.ok("new_phase: context.md is copied", os.path.isfile(os.path.join(str(p1), "context.md")))
for f, head in HEADERS.items():
    s.eq("new_phase: %s holds exactly its header" % f, read(os.path.join(str(p1), f)).decode(), head)
s.ok("new_phase writes nothing in the worktree it was run from", not os.path.exists(os.path.join(nw, ".fwx")))
s.eq("new_phase binds the session (from the environment)", state.read_session(cwd=nm, session="np1"),
     {"subproject": None, "phase_dir": os.path.join(".fwx", "milestones", "v1", "phases", "01-a")})
s.eq("new_phase: the second one is 02-b", os.path.basename(str(state.new_phase("b", cwd=nm))), "02-b")
s.eq("new_phase without a session id binds nothing and is no error", state.read_session(cwd=nm, session="nobody"), None)
s.eq("new_phase: the folder name of context.md is filled in", [l for l in read(os.path.join(str(p1), "context.md")).decode().splitlines() if l.startswith("# ")],
     ["# Context: 01-a"])
for f in ("context.md",):
    first = read(os.path.join(str(p1), f)).decode().splitlines()[0]
    s.ok("a copied template loses its leading referent comment line (%s)" % f, "referent" not in first and "copied-from" not in first, first)
s.ok("PROJECT.md loses its leading referent comment line", "<!-- referent" not in read(os.path.join(fr, "PROJECT.md")).decode())

# a number that is already taken is skipped, never shared. Two seams stand in for the two ways it happens: a listing gone
# stale (`_next_number`), and a rival that creates the folder between the free-number look and the mkdir (`_number_taken`).
real_next, real_taken = state._next_number, state._number_taken
state._next_number = lambda parent, subphases=False: 1
q = state.new_phase("a", cwd=nm)  # 01-a, 02-b exist: a different slug must not reuse number 02 either
state._next_number = real_next
s.eq("new_phase: a stale listing (number 1 taken, slug differs) tries the next, never two phases with one number",
     os.path.basename(str(q)), "03-a")
rm2 = helpers.toy_repo()
r2a = state.new_phase("a", cwd=rm2)
state._next_number, state._number_taken = (lambda parent, subphases=False: 1), (lambda parent, n, subphases=False: False)
q2 = state.new_phase("a", cwd=rm2)  # same slug, same number, the free-number look fooled: only the mkdir can refuse
state._next_number, state._number_taken = real_next, real_taken
s.eq("new_phase: the same folder made twice is not shared, the second takes the next number (exist_ok would share 01-a)",
     (os.path.basename(str(r2a)), os.path.basename(str(q2))), ("01-a", "02-a"))
s.ok("new_phase: 01-a is untouched by the retries", os.path.isfile(os.path.join(str(p1), "context.md")))
s.eq("new_phase: the folders in order", [os.path.basename(str(x)) for x in state.phases(fr, "v1")], ["01-a", "02-b", "03-a"])
dm = state.new_phase("dec", cwd=nm)
state.append_decision(os.path.join(str(dm), "decisions.tsv"), decision="d", why="w", support="chosen")
s.eq("a decision appended to the new decisions.tsv: header once", read(os.path.join(str(dm), "decisions.tsv")).decode().count("date\tid"), 1)

# a number gap: the next number follows the highest
mk(fr, "milestones", "v1", "phases", "07-far")
s.eq("new_phase: next is highest + 1", os.path.basename(str(state.new_phase("n", cwd=nm))), "08-n")
mk(fr, "milestones", "v1", "phases", "12.2-conv")
s.eq("new_phase: a converted NN.M phase counts by its NN", os.path.basename(str(state.new_phase("m", cwd=nm))), "13-m")

# milestone and subproject choices
s.eq("new_phase: an explicit milestone that exists", os.path.basename(os.path.dirname(os.path.dirname(str(
    state.new_phase("x", milestone="v1", cwd=nm))))), "v1")
refuses("new_phase: a milestone that does not exist", lambda: state.new_phase("x", milestone="v9", cwd=nm), "v9")
refuses("new_phase: a bad milestone name", lambda: state.new_phase("x", milestone="../v1", cwd=nm))
for bad in ("", "Has Space", "a/b", "..", "-x", "A", "a--b", "a_b"):
    refuses("new_phase: bad slug %r" % bad, lambda bad=bad: state.new_phase(bad, cwd=nm))
state.new_milestone(state.scope_root(fr), "v2")
s.eq("new_phase goes to the current milestone: v2 now, numbering restarts", str(state.new_phase("f", cwd=nm)),
     os.path.join(fr, "milestones", "v2", "phases", "01-f"))
sp1 = state.new_phase("w", subproject="web", cwd=nm)
s.eq("new_phase in a subproject", str(sp1), os.path.join(fr, "subprojects", "web", "milestones", "v1", "phases", "01-w"))
s.ok("a subproject phase does not touch the root's numbering", os.path.basename(str(state.new_phase("g", cwd=nm))) == "02-g")
refuses("new_phase: a subproject name that is a path", lambda: state.new_phase("x", subproject="../x", cwd=nm))
state.write_session(cwd=nm, session="np2", subproject="web", phase_dir=None)
s.eq("new_phase without --subproject keeps the session's subproject (never falls back to the flat root)",
     str(state.new_phase("h", session="np2", cwd=nm)), os.path.join(fr, "subprojects", "web", "milestones", "v1", "phases", "02-h"))
s.eq("... and binds the session to it", state.read_session(cwd=nm, session="np2")["subproject"], "web")

# nothing half-made when a template is missing
bm = helpers.toy_repo()
real_tpl = state._TEMPLATES
state._TEMPLATES = state.Path(helpers.mkdtemp("fwx-notpl-"))
refuses("new_phase with the templates folder missing", lambda: state.new_phase("a", cwd=bm), "templates")
state._TEMPLATES = real_tpl
s.ok("... leaves nothing behind", not os.path.exists(os.path.join(bm, ".fwx")))

# ---- new_milestone ----------------------------------------------------------------------------------------------------
mm = helpers.toy_repo()
mroot = state.scope_root(os.path.join(mm, ".fwx"))
m1 = state.new_milestone(mroot)
s.eq("new_milestone in an empty scope is v1", str(m1), os.path.join(mm, ".fwx", "milestones", "v1"))
s.ok("new_milestone writes MILESTONE.md from the template", os.path.isfile(os.path.join(str(m1), "MILESTONE.md")))
s.ok("MILESTONE.md carries its own name and loses the referent line", "# Milestone v1:" in read(os.path.join(str(m1), "MILESTONE.md")).decode()
     and "<!-- referent" not in read(os.path.join(str(m1), "MILESTONE.md")).decode())
mk(mm, ".fwx", "milestones", "v9")
s.eq("new_milestone: the next one follows the highest (v9 -> v10)", os.path.basename(str(state.new_milestone(mroot))), "v10")
s.eq("new_milestone with a name", os.path.basename(str(state.new_milestone(mroot, "v12"))), "v12")
refuses("new_milestone that already exists", lambda: state.new_milestone(mroot, "v12"), "v12")
refuses("new_milestone with a bad name", lambda: state.new_milestone(mroot, "release-1"))
refuses("new_milestone outside .fwx", lambda: state.new_milestone(helpers.mkdtemp("fwx-outside-")))
s.eq("new_milestone in a subproject scope", str(state.new_milestone(state.scope_root(os.path.join(mm, ".fwx"), "api"))),
     os.path.join(mm, ".fwx", "subprojects", "api", "milestones", "v1"))

# ---- new_subphase -----------------------------------------------------------------------------------------------------
um = helpers.toy_repo()
ux = mk(um, ".fwx", "milestones", "v1", "phases", "03-x")
sa = state.new_subphase(ux, "a")
sb = state.new_subphase(ux, "b")
s.eq("new_subphase twice: 03.1-a and 03.2-b", (os.path.basename(str(sa)), os.path.basename(str(sb))), ("03.1-a", "03.2-b"))
s.eq("subphases returns them in that order", [os.path.basename(str(x)) for x in state.subphases(ux)], ["03.1-a", "03.2-b"])
s.ok("new_subphase copies plan.md", os.path.isfile(os.path.join(str(sa), "plan.md")))
s.eq("new_subphase writes the audit.tsv header", read(os.path.join(str(sa), "audit.tsv")).decode(), HEADERS["audit.tsv"])
s.ok("the subphase plan.md loses its referent comment line", "<!-- referent" not in read(os.path.join(str(sa), "plan.md")).decode())
s.ok("new_subphase makes no decisions.tsv (it stays in the phase)", not os.path.exists(os.path.join(str(sa), "decisions.tsv")))
for k in range(8):
    state.new_subphase(ux, "s%d" % k)
s.eq("new_subphase: the tenth is 03.10 and sorts after 03.2", [os.path.basename(str(x)) for x in state.subphases(ux)][-1], "03.10-s7")
state._next_number = lambda parent, subphases=False: 1
stale = state.new_subphase(ux, "a")  # 03.1-a exists, and 03.2-b: another slug must not reuse number 2 either
state._next_number = real_next
s.eq("new_subphase: a stale listing tries the next number", os.path.basename(str(stale)), "03.11-a")
uy = mk(um, ".fwx", "milestones", "v1", "phases", "04-y")
uy1 = state.new_subphase(uy, "a")
state._next_number, state._number_taken = (lambda parent, subphases=False: 1), (lambda parent, n, subphases=False: False)
uy2 = state.new_subphase(uy, "a")
state._next_number, state._number_taken = real_next, real_taken
s.eq("new_subphase: the same folder made twice is not shared (exist_ok would share 04.1-a)",
     (os.path.basename(str(uy1)), os.path.basename(str(uy2))), ("04.1-a", "04.2-a"))
refuses("new_subphase: a phase folder that does not exist", lambda: state.new_subphase(os.path.join(um, ".fwx", "milestones", "v1", "phases", "09-no"), "a"))
refuses("new_subphase: a folder that is not a phase", lambda: state.new_subphase(mk(um, "elsewhere", "03-x"), "a"))
refuses("new_subphase: inside a subphase", lambda: state.new_subphase(str(sa), "a"))
refuses("new_subphase: a converted NN.M phase takes no subphases", lambda: state.new_subphase(mk(um, ".fwx", "milestones", "v1", "phases", "12.2-c"), "a"))
refuses("new_subphase: a bad slug", lambda: state.new_subphase(ux, "Bad Slug"))

# ---- cancel_phase -----------------------------------------------------------------------------------------------------
cm = helpers.toy_repo()
c1 = state.new_phase("a", cwd=cm)
c2 = state.new_phase("b", cwd=cm)
state.write_session(cwd=cm, session="c1", subproject=None, phase_dir=c1)
state.write_session(cwd=cm, session="c2", subproject="web", phase_dir=c1)
state.write_session(cwd=cm, session="c3", subproject=None, phase_dir=c2)
mk(str(c1), "research")
helpers.write(str(c1), "research/x.md", "notes\n")
state.cancel_phase(c1)
s.ok("cancel_phase deletes its folder", not os.path.exists(str(c1)))
s.ok("cancel_phase: neighbour phase 02-b missing", os.path.isfile(os.path.join(str(c2), "context.md")))
s.ok("cancel_phase: milestones/v1/phases still there", os.path.isdir(os.path.dirname(str(c2))))
s.eq("cancel_phase unbinds the session that pointed to it, keeping its subproject",
     (state.read_session(cwd=cm, session="c1"), state.read_session(cwd=cm, session="c2")),
     ({"subproject": None, "phase_dir": None}, {"subproject": "web", "phase_dir": None}))
s.eq("cancel_phase leaves a session on another phase alone", state.read_session(cwd=cm, session="c3")["phase_dir"],
     os.path.join(".fwx", "milestones", "v1", "phases", "02-b"))
for doc in ("premortem.md", "plan.md"):
    d3 = state.new_phase("p" + doc[:2], cwd=cm)
    helpers.write(str(d3), doc, "x\n")
    refuses("cancel_phase refuses once %s exists" % doc, lambda d3=d3: state.cancel_phase(d3), doc)
    s.ok("... and deletes nothing (%s)" % doc, os.path.isfile(os.path.join(str(d3), "context.md")) and os.path.isfile(os.path.join(str(d3), doc)))
refuses("cancel_phase: a folder outside .fwx", lambda: state.cancel_phase(mk(cm, "src", "01-x")))
refuses("cancel_phase: .fwx itself", lambda: state.cancel_phase(os.path.join(cm, ".fwx")))
refuses("cancel_phase: a milestone folder", lambda: state.cancel_phase(os.path.join(cm, ".fwx", "milestones", "v1")))
refuses("cancel_phase: a subphase folder", lambda: state.cancel_phase(str(state.new_subphase(c2, "z"))))
refuses("cancel_phase: a folder that does not exist", lambda: state.cancel_phase(os.path.join(cm, ".fwx", "milestones", "v1", "phases", "09-no")))
link = os.path.join(cm, ".fwx", "milestones", "v1", "phases", "20-link")
os.symlink(helpers.mkdtemp("fwx-target-"), link)
refuses("cancel_phase: a symlink is not followed", lambda: state.cancel_phase(link))
cs = state.new_phase("w", subproject="web", cwd=cm)
state.cancel_phase(cs)
s.ok("cancel_phase works inside a subproject", not os.path.exists(str(cs)) and os.path.isdir(os.path.join(cm, ".fwx", "subprojects", "web")))

# ---- check_state -------------------------------------------------------------------------------------------------------
kd = helpers.mkdtemp("fwx-check-")
helpers.write(kd, "state.md", "# State\n" + "line\n" * 99)  # 100 lines
s.eq("check_state: 100 lines is on target", state.check_state(os.path.join(kd, "state.md")), ([], []))
helpers.write(kd, "state.md", "# State\n" + "line\n" * 111)  # 112 lines
s.eq("check_state: 112 lines warns, no error", state.check_state(os.path.join(kd, "state.md")), ([], ["112 lines, target 100"]))
errs, _ = state.check_state(os.path.join(kd, "missing.md"))
s.ok("check_state: a missing file is an error", len(errs) == 1 and "missing.md" in errs[0], str(errs))
helpers.write(kd, "empty.md", "\n\n")
s.ok("check_state: an empty state.md is an error", len(state.check_state(os.path.join(kd, "empty.md"))[0]) == 1)

# ---- check_report ------------------------------------------------------------------------------------------------------
rd = helpers.mkdtemp("fwx-report-")
SHA = "0123456789abcdef0123456789abcdef01234567"
state.append_audit(rd, "evidence", "old run", rc=0, sha="f" * 40)
state.append_audit(rd, "evidence", "pytest -q", rc=0, sha=SHA)
state.append_audit(rd, "round", "review")
report = os.path.join(rd, "report-1.md")
helpers.write(rd, "report-1.md", "# Report 1\n\n## Evidence\nCommit `%s`, pytest -q, exit 0.\n" % SHA)
s.eq("check_report: the full sha of the last evidence row passes", state.check_report(report), ([], []))
helpers.write(rd, "report-1.md", "# Report 1\n\n## Evidence\nCommit `%s`, pytest -q, exit 0.\n" % SHA[:7])
s.eq("check_report: an abbreviated sha (7 chars) passes", state.check_report(report), ([], []))
helpers.write(rd, "report-1.md", "# Report 1\n\n## Evidence\nCommit `%s`, an older run.\n" % ("f" * 40))
errs, warns = state.check_report(report)
s.ok("check_report: the sha of an older evidence row is not the last one (report without evidence sha passed)", len(errs) == 1 and "0123456" in errs[0], str(errs))
helpers.write(rd, "report-1.md", "# Report 1\n\nDone.\n")
errs, warns = state.check_report(report)
s.ok("check_report: a report without the evidence sha is an error (report without evidence sha passed)", len(errs) == 1, str(errs))
helpers.write(rd, "report-1.md", "# Report\n" + "Commit %s\n" % SHA + "line\n" * 39)  # 41 lines
s.eq("check_report: 41 lines is a warning, not an error", state.check_report(report), ([], ["41 lines, target 40"]))
helpers.write(rd, "report-1.md", "# Report\n" + "Commit %s\n" % SHA + "line\n" * 38)  # 40 lines
s.eq("check_report: 40 lines is on target", state.check_report(report), ([], []))
nr = helpers.mkdtemp("fwx-noaudit-")
helpers.write(nr, "report-1.md", "# Report\nCommit %s\n" % SHA)
s.ok("check_report: no audit.tsv, so no evidence to cite: an error", len(state.check_report(os.path.join(nr, "report-1.md"))[0]) == 1)
state.append_audit(nr, "round", "review")
s.ok("check_report: audit.tsv with no evidence row: an error", len(state.check_report(os.path.join(nr, "report-1.md"))[0]) == 1)
s.ok("check_report: a missing report is an error", len(state.check_report(os.path.join(nr, "report-9.md"))[0]) == 1)
state.append_audit(rd, "evidence", "later", rc=1, sha="b" * 40)
helpers.write(rd, "report-1.md", "# Report\nCommit %s\n" % SHA)
s.ok("check_report: a newer evidence row makes the old sha stale", len(state.check_report(report)[0]) == 1)

# ---- the templates ------------------------------------------------------------------------------------------------------
state._read_template = _real_read_template
for name in sorted(set(read_templates)):
    s.ok("the template %s that state.py copies exists in templates/" % name, os.path.isfile(os.path.join(TEMPLATES, name)), name)
s.eq("the templates copied by new_phase, new_subphase and new_milestone", sorted(set(read_templates)),
     ["MILESTONE.md", "PROJECT.md", "phase/context.md", "phase/plan.md"])
SECTIONS = {"premortem.md": ["## Verdict", "## Failure reasons", "## Size"],
            "plan.md": ["## Goal", "## Approach", "## Size"],
            "postmortem.md": ["## Verdict", "## Findings", "## Criteria", "## Checked", "## Needs from the owner before executing",
                              "## Not found wrong"]}


def frontmatter(path):
    """(the JSON between the two `---` lines of a template, the body) or (None, error)."""
    text = read(path).decode()
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        return None, "%s: no frontmatter between two --- lines" % rel(path, helpers.ROOT)
    end = lines.index("---", 1)
    try:
        return json.loads("\n".join(lines[1:end])), "\n".join(lines[end + 1:])
    except ValueError:
        return None, "%s: frontmatter is not JSON" % rel(path, helpers.ROOT)


for name, heads in SECTIONS.items():
    path = os.path.join(TEMPLATES, "phase", name)
    data, body = frontmatter(path)
    s.ok("templates/phase/%s: frontmatter is JSON" % name, data is not None, body)
    if data is not None:
        s.ok("templates/phase/%s: the frontmatter is an object" % name, isinstance(data, dict))
        found = [l for l in body.splitlines() if l.startswith("## ")]
        s.eq("templates/phase/%s: the section headings of 3.3, in order" % name, found, heads)
plan_fm = frontmatter(os.path.join(TEMPLATES, "phase", "plan.md"))[0] or {}
s.ok("templates/phase/plan.md: every task carries `part`", plan_fm.get("tasks") and all("part" in t for t in plan_fm["tasks"]))
bad = helpers.mkdtemp("fwx-badtpl-")
helpers.write(bad, "plan.md", '---\n{"a": 1,}\n---\n## Goal\n')
s.eq("control: a trailing comma in the frontmatter is caught", frontmatter(os.path.join(bad, "plan.md"))[1].endswith("frontmatter is not JSON"), True)

s.done()
