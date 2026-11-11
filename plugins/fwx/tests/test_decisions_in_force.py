#!/usr/bin/env python3
"""`fwx state decisions`: which rows of a decisions.tsv (or adr.tsv) are in force, and which rows a topic touches.

The writer (`state.append_decision`) only adds rows; a later row names the id it replaces in `supersedes`. These
checks are the read side: state.decisions_in_force (pure) and the CLI around it, in toy repos and toy files.

Seen red before the command existed (123 checks; the pure-function checks fail on the missing attribute, the CLI ones on
the usage error, first FAIL lines):
  FAIL: state.decisions_in_force exists: module 'fwx.state' has no attribute 'decisions_in_force'
  FAIL: an empty log: exit code: got 2, want 0
  FAIL: an empty log: nothing on stderr: got "fwx state: argument subcommand: invalid choice: 'decisions', maybe you meant 'decision'? ...
  FAIL: a chain of three: the count line: got '', want '1 in force of 3 row(s)'

Controls, each seen red on lib/fwx/state.py changed in one place (put back after each):
  - "in force" looks one hop only, so a chain of three leaves two (the row whose replacer is itself replaced stays in force; 10 failed):
      FAIL: pure: ids in order, in_force: got [('D1', True), ('D2', False), ('D3', True), ('D4', True)], want [('D1', False), ...
      FAIL: a chain of three: the count line: got '2 in force of 3 row(s)', want '1 in force of 3 row(s)'
      FAIL: --json: only what is in force: got [('D1', True, 'D2'), ('D3', True, '')], want [('D3', True, '')]
  - --grep follows one hop to the end of the chain instead of all of it (5 failed):
      FAIL: --grep on D1's words: the row in force, D3, comes out: ['D2  ...  approved  [superseded by D3] use TSV for the logs', '    matched superseded D1', '0 in force of 3 row(s)']
      FAIL: --grep --json: D3 and the superseded id that matched: got [('D2', ['D1'])], want [('D3', ['D1'])]
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import state  # noqa: E402

s = helpers.Suite()
HEADER = "\t".join(state.DECISION_COLUMNS)


def st(cwd, *args, session="sess-1", env=None):
    e = {"CLAUDE_CODE_SESSION_ID": session} if session else {"CLAUDE_CODE_SESSION_ID": ""}
    e.update(env or {})
    return helpers.fwx(cwd, "state", *args, env=e)


def clean(label, r, code):
    s.eq("%s: exit code" % label, r.returncode, code)
    s.ok("%s: no traceback" % label, "Traceback" not in r.stderr, r.stderr[-300:])
    if code:
        s.ok("%s: one line on stderr" % label, len(r.stderr.strip().splitlines()) == 1, repr(r.stderr[-300:]))
    else:
        s.eq("%s: nothing on stderr" % label, r.stderr, "")
    return r.returncode == code


def lines(r):
    return r.stdout.splitlines()


def planted(folder, name, rows, header=HEADER):
    """A decisions file written directly, so a row the writer refuses (a dangling `supersedes`) can exist."""
    text = header + "\n" + "".join("\t".join(r) + "\n" for r in rows)
    helpers.write(folder, name, text)
    return os.path.join(folder, name)


def row(i, decision, why="because", supersedes="", support="chosen", rejected="", source="", date="day-0"):
    return (date, i, decision, why, rejected, support, source, supersedes)


# ---- the pure function ----------------------------------------------------------------------------------------------
def in_force(rows):
    """state.decisions_in_force, or [] and a failed check where it does not exist (so the CLI checks below still run red)."""
    fn = getattr(state, "decisions_in_force", None)
    if fn is None:
        s.ok("state.decisions_in_force exists", False, "module 'fwx.state' has no attribute 'decisions_in_force'")
        return []
    return fn(rows)


def rows3():
    return [dict(zip(state.DECISION_COLUMNS, r)) for r in (
        row("D1", "a"), row("D2", "b", supersedes="D1"), row("D3", "c", supersedes="D2"), row("D4", "d"))]


got = in_force(rows3())
s.eq("pure: ids in order, in_force", [(r["id"], r["in_force"]) for r in got], [("D1", False), ("D2", False), ("D3", True), ("D4", True)])
s.eq("pure: superseded_by", [r["superseded_by"] for r in got], ["D2", "D3", "", ""])
s.eq("pure: the input rows are not changed", sorted(rows3()[0]), sorted(state.DECISION_COLUMNS))
s.eq("pure: no rows, no result", in_force([]), [])
for label, bad, word in (
        ("a dangling supersedes", [dict(zip(state.DECISION_COLUMNS, row("D1", "a", supersedes="D9")))], "D9"),
        ("a supersedes cycle", [dict(zip(state.DECISION_COLUMNS, row("D1", "a", supersedes="D2"))),
                                dict(zip(state.DECISION_COLUMNS, row("D2", "b", supersedes="D1")))], "loops back"),
        ("a row superseding itself", [dict(zip(state.DECISION_COLUMNS, row("D1", "a", supersedes="D1")))], "D1"),
        ("a repeated id", [dict(zip(state.DECISION_COLUMNS, row("D1", "a"))), dict(zip(state.DECISION_COLUMNS, row("D1", "b")))], "D1")):
    try:
        in_force(bad)
        s.ok("pure: %s is refused" % label, False, "no StateError")
    except state.StateError as e:
        s.ok("pure: %s is refused, naming %s" % (label, word), word in str(e), str(e))

# ---- a phase with a chain of three, through the session -----------------------------------------------------------
repo = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
clean("new-phase", st(repo, "new-phase", "alpha"), 0)
phase = os.path.join(repo, ".fwx", "milestones", "v1", "phases", "01-alpha")
dec = os.path.join(phase, "decisions.tsv")

r = st(repo, "decisions")
clean("an empty log", r, 0)
s.eq("an empty log: says it looked at nothing", lines(r), ["0 in force of 0 row(s)"])
clean("an empty log, --json", st(repo, "decisions", "--json"), 0)
s.eq("an empty log, --json: []", json.loads(st(repo, "decisions", "--json").stdout or "null"), [])

d1 = state.append_decision(dec, decision="use JSON for the logs", why="readable", support="chosen", rejected="CSV", source="chat 1")
d2 = state.append_decision(dec, decision="use TSV for the logs", why="greppable and cheap", support="approved", supersedes=d1)
d3 = state.append_decision(dec, decision="use TSV with a checked header", why="an old reader broke", support="chosen", supersedes=d2)
s.eq("setup: the writer made D1, D2, D3", (d1, d2, d3), ("D1", "D2", "D3"))

r = st(repo, "decisions")
clean("a chain of three", r, 0)
out = lines(r)
s.eq("a chain of three: one row and the count line", len(out), 2)
s.ok("a chain of three: the row is D3, `id  date  support  decision`",
     re.fullmatch(r"D3  \d{4}-\d\d-\d\dT\S+  chosen  use TSV with a checked header", out[0] if out else "") is not None, repr(out))
s.eq("a chain of three: the count line", out[-1] if out else "", "1 in force of 3 row(s)")

r = st(repo, "decisions", "--all")
clean("--all", r, 0)
out = lines(r)
s.eq("--all: three rows and the count line", len(out), 4)
s.ok("--all: D1 is marked with D2", len(out) > 0 and out[0].startswith("D1  ") and "[superseded by D2] use JSON" in out[0], repr(out[:1]))
s.ok("--all: D2 is marked with D3", len(out) > 1 and out[1].startswith("D2  ") and "[superseded by D3] use TSV for" in out[1], repr(out[1:2]))
s.ok("--all: D3 is not marked", len(out) > 2 and out[2].startswith("D3  ") and "superseded" not in out[2], repr(out[2:3]))
s.eq("--all: the count line", out[-1] if out else "", "1 in force of 3 row(s)")

got = json.loads(st(repo, "decisions", "--all", "--json").stdout or "[]")
s.eq("--all --json: id, in_force, superseded_by", [(x.get("id"), x.get("in_force"), x.get("superseded_by")) for x in got],
     [("D1", False, "D2"), ("D2", False, "D3"), ("D3", True, "")])
s.ok("--all --json: full rows (every column)", all(set(state.DECISION_COLUMNS) <= set(x) for x in got), repr(got[:1]))
got = json.loads(st(repo, "decisions", "--json").stdout or "[]")
s.eq("--json: only what is in force", [(x.get("id"), x.get("in_force"), x.get("superseded_by")) for x in got], [("D3", True, "")])

# --grep: words only the superseded row has lead to the row in force
r = st(repo, "decisions", "--grep", "json")
clean("--grep on words only D1 has", r, 0)
out = lines(r)
s.ok("--grep on D1's words: the row in force, D3, comes out", len(out) > 0 and out[0].startswith("D3  "), repr(out))
s.ok("--grep on D1's words: D1 itself is not printed as a row", not any(l.startswith("D1  ") for l in out), repr(out))
s.ok("--grep on D1's words: the matched superseded id is named", any("D1" in l and "match" in l for l in out[1:-1]), repr(out))
s.eq("--grep on D1's words: D3 once, and the count", (sum(l.startswith("D3  ") for l in out), out[-1] if out else ""), (1, "1 in force of 3 row(s)"))
j = json.loads(st(repo, "decisions", "--grep", "json", "--json").stdout or "[]")
s.eq("--grep --json: D3 and the superseded id that matched", [(x.get("id"), x.get("matched_superseded")) for x in j], [("D3", ["D1"])])
s.ok("--grep: the match is on `rejected` (CSV)", any(l.startswith("D3  ") for l in lines(st(repo, "decisions", "--grep", "csv"))))
s.ok("--grep: the match is on `source` (chat 1)", any(l.startswith("D3  ") for l in lines(st(repo, "decisions", "--grep", "CHAT 1"))))
s.ok("--grep: the match is on `why` (greppable), case-insensitive", any(l.startswith("D3  ") for l in lines(st(repo, "decisions", "--grep", "GREPPABLE"))))

# two terms: both must match, on the same row
r = st(repo, "decisions", "--grep", "tsv", "--grep", "greppable")
out = lines(r)
s.ok("--grep tsv --grep greppable: only D2 has both, so D3 comes out naming D2",
     len(out) > 1 and out[0].startswith("D3  ") and any("D2" in l and "D1" not in l for l in out[1:-1]), repr(out))
r = st(repo, "decisions", "--grep", "tsv", "--grep", "json")
clean("--grep with two terms no row has together", r, 0)
s.eq("--grep tsv --grep json: no single row has both: zero, said", lines(r), ["0 in force of 3 row(s)"])
r = st(repo, "decisions", "--grep", "json", "--all")
out = lines(r)
s.eq("--grep --all: only the matching row, as written, marked", [l.split("  ")[0] for l in out[:-1]], ["D1"])
s.eq("--grep --all: the count", out[-1] if out else "", "0 in force of 3 row(s)")

# ---- two independent rows are both in force; a chain beside them ---------------------------------------------------
f = planted(repo, "indep.tsv", [row("D1", "one"), row("D2", "two")])
r = st(repo, "decisions", "--file", f)
clean("two independent rows", r, 0)
out = lines(r)
s.eq("two independent rows: both are in force", ([l.split("  ")[0] for l in out[:-1]], out[-1] if out else ""), (["D1", "D2"], "2 in force of 2 row(s)"))
f = planted(repo, "mixed.tsv", [row("D1", "old"), row("D2", "new", supersedes="D1"), row("D3", "apart")])
s.eq("a chain and an independent row", [l.split("  ")[0] for l in lines(st(repo, "decisions", "--file", f))], ["D2", "D3", "2 in force of 3 row(s)"])

# a branch: two rows replace the same row; the one written last is the row it points at, both stay in force
f = planted(repo, "branch.tsv", [row("D1", "old"), row("D2", "left", supersedes="D1"), row("D3", "right", supersedes="D1")])
out = lines(st(repo, "decisions", "--file", f))
s.eq("two rows replacing one: both are in force", ([l.split("  ")[0] for l in out[:-1]], out[-1] if out else ""), (["D2", "D3"], "2 in force of 3 row(s)"))

# ---- --file reads any path, cells keep their text -------------------------------------------------------------------
os.makedirs(os.path.join(repo, "elsewhere"))
f = planted(repo, "elsewhere/log.tsv", [row("D1", "x"), row("D2", "y", supersedes="D1")])
outside = helpers.mkdtemp("fwx-outside-")
r = st(outside, "decisions", "--file", f, session=None)
clean("--file from a folder that is no repository", r, 0)
s.eq("--file from a folder that is no repository: the row", [l.split("  ")[0] for l in lines(r)], ["D2", "1 in force of 2 row(s)"])

# ---- --phase and --adr resolve the way the writer does ---------------------------------------------------------------
clean("a second phase", st(repo, "new-phase", "beta", session="sess-b"), 0)
state.append_decision(os.path.join(repo, ".fwx", "milestones", "v1", "phases", "02-beta", "decisions.tsv"), decision="in beta", why="w",
                      support="unexamined")
s.eq("the session's phase, not beta, is read", [l.split("  ")[0] for l in lines(st(repo, "decisions", session="sess-b"))][:-1], ["D1"])
r = st(repo, "decisions", "--phase", phase, session="sess-b")
s.eq("--phase reads that phase's file", [l.split("  ")[0] for l in lines(r)], ["D3", "1 in force of 3 row(s)"])

adr = os.path.join(repo, ".fwx", "adr.tsv")
a1 = state.append_decision(adr, decision="keep TSV", why="hard to undo", support="chosen")
a2 = state.append_decision(adr, decision="keep TSV, checked", why="drift", support="chosen", supersedes=a1)
r = st(repo, "decisions", "--adr", session="sess-b")
clean("--adr", r, 0)
s.eq("--adr: the scope's adr.tsv, A2 in force", ([l.split("  ")[0] for l in lines(r)], (a1, a2)), (["A2", "1 in force of 2 row(s)"], ("A1", "A2")))

repo2 = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
clean("new-phase in a second repo, then none is bound", st(repo2, "new-phase", "one", session="s1"), 0)
clean("new-phase, a second one", st(repo2, "new-phase", "two", session="s1"), 0)
r = st(repo2, "decisions", session="other")
clean("no phase bound and two open", r, 1)
s.ok("no phase bound: the message is the writer's", "no phase is bound" in r.stderr, r.stderr)

# ---- errors: one line, exit 1 --------------------------------------------------------------------------------------
f = planted(repo, "dangling.tsv", [row("D1", "a"), row("D2", "b", supersedes="D7")])
r = st(repo, "decisions", "--file", f)
clean("a supersedes naming an id that does not exist", r, 1)
s.ok("a dangling supersedes: the line names the row and the missing id", "D2" in r.stderr and "D7" in r.stderr, r.stderr)
s.eq("a dangling supersedes: nothing on stdout", r.stdout, "")
r = st(repo, "decisions", "--file", f, "--all")
clean("a dangling supersedes, --all", r, 1)
f = planted(repo, "badhead.tsv", [row("D1", "a")], header="date\tid\tdecision")
r = st(repo, "decisions", "--file", f)
clean("a bad header", r, 1)
s.ok("a bad header: the line names the file", "badhead.tsv" in r.stderr, r.stderr)
f = planted(repo, "cycle.tsv", [row("D1", "a", supersedes="D2"), row("D2", "b", supersedes="D1")])
clean("a supersedes cycle", st(repo, "decisions", "--file", f), 1)
r = st(repo, "decisions", "--file", os.path.join(repo, "no-such.tsv"))
clean("--file naming a file that does not exist", r, 1)
s.ok("--file missing: the line names it", "no-such.tsv" in r.stderr, r.stderr)
f = planted(repo, "empty.tsv", [])
s.eq("a file with only its header", lines(st(repo, "decisions", "--file", f)), ["0 in force of 0 row(s)"])
helpers.write(repo, "zero.tsv", "")
r = st(repo, "decisions", "--file", os.path.join(repo, "zero.tsv"))
clean("a file of zero bytes", r, 0)
s.eq("a file of zero bytes: 0 of 0", lines(r), ["0 in force of 0 row(s)"])
clean("--file with --phase", st(repo, "decisions", "--file", f, "--phase", phase), 2)
clean("--file with --adr", st(repo, "decisions", "--file", f, "--adr"), 2)
clean("an unknown flag", st(repo, "decisions", "--nope"), 2)

# ---- width: cut on a terminal only ----------------------------------------------------------------------------------
LONG = "a very long decision that goes on and on " * 8
f = planted(repo, "long.tsv", [row("D1", LONG.strip())])
r = st(repo, "decisions", "--file", f, env={"COLUMNS": "40"})
out = lines(r)
s.eq("piped: the decision is whole, whatever COLUMNS says", out[0].endswith(LONG.strip()) if out else None, True)
s.eq("piped: the count line", out[-1] if out else "", "1 in force of 1 row(s)")
try:
    import pty
except ImportError:
    pty = None
if pty is None:
    s.ok("on a terminal: truncation checked", False, "no pty module here")
else:
    master, slave = pty.openpty()
    e = helpers.clean_env(CLAUDE_CODE_SESSION_ID="", COLUMNS="40")
    p = subprocess.run([sys.executable, os.path.join(helpers.ROOT, "bin", "fwx"), "state", "decisions", "--file", f], cwd=repo, env=e,
                       stdout=slave, stderr=subprocess.PIPE, text=True)
    os.close(slave)
    raw = b""
    try:
        while True:
            chunk = os.read(master, 4096)
            if not chunk:
                break
            raw += chunk
    except OSError:  # EIO: the other end is closed
        pass
    os.close(master)
    tout = [l for l in raw.decode("utf-8", "replace").replace("\r", "").split("\n") if l]
    s.eq("on a terminal: exit code", p.returncode, 0)
    s.ok("on a terminal: the row is cut to the width", bool(tout) and 0 < len(tout[0]) <= 40 and LONG.strip() not in tout[0], repr(tout[:1]))
    s.ok("on a terminal: the row still starts with its id", bool(tout) and tout[0].startswith("D1  "), repr(tout[:1]))
    s.eq("on a terminal: the count line is whole", tout[-1] if tout else "", "1 in force of 1 row(s)")

s.done()
