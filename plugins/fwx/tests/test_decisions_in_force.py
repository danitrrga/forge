#!/usr/bin/env python3
"""Which rows of a decisions.tsv (or adr.tsv) are in force: `state.decisions_in_force`, pure, and over files read with
`state.read_decision_rows`. (`fwx decision list` is gone: its refusal is checked in test_commands_table.py.)

The writer (`state.append_decision`) only adds rows; a later row names the id it replaces in `supersedes`.

Control, seen red on lib/fwx/state.py changed in one place (put back after): "in force" looks one hop only, so a chain of three
leaves two (the row whose replacer is itself replaced stays in force; 7 failed):
  FAIL: pure: ids in order, in_force: got [('D1', True), ('D2', False), ('D3', True), ('D4', True)], want [('D1', False), ...
  FAIL: a chain of three, written by the writer: in force: got ['D1', 'D3'], want ['D3']
"""
import os
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
    return helpers.fwx(cwd, *args, env=e)


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

# ---- files: the writer's chain of three, and the ones it refuses to read ------------------------------------------------
folder = helpers.mkdtemp("fwx-decisions-")
dec = os.path.join(folder, "decisions.tsv")
d1 = state.append_decision(dec, decision="use JSON for the logs", why="readable", support="chosen", rejected="CSV", source="chat 1")
d2 = state.append_decision(dec, decision="use TSV for the logs", why="greppable and cheap", support="approved", supersedes=d1)
d3 = state.append_decision(dec, decision="use TSV with a checked header", why="an old reader broke", support="chosen", supersedes=d2)
s.eq("setup: the writer made D1, D2, D3", (d1, d2, d3), ("D1", "D2", "D3"))
got = in_force(state.read_decision_rows(dec))
s.eq("a chain of three, written by the writer: in force", [r["id"] for r in got if r["in_force"]], ["D3"])
s.eq("a chain of three: superseded_by", [r["superseded_by"] for r in got], ["D2", "D3", ""])
s.eq("a file with only its header: no rows", in_force(state.read_decision_rows(planted(folder, "empty.tsv", []))), [])
helpers.write(folder, "zero.tsv", "")
s.eq("a file of zero bytes: no rows", in_force(state.read_decision_rows(os.path.join(folder, "zero.tsv"))), [])
s.eq("a file that does not exist: no rows", state.read_decision_rows(os.path.join(folder, "no-such.tsv")), [])
for label, name, rows, header, word in (
        ("a supersedes naming an id that does not exist", "dangling.tsv", [row("D1", "a"), row("D2", "b", supersedes="D7")], HEADER, "D7"),
        ("a supersedes cycle", "cycle.tsv", [row("D1", "a", supersedes="D2"), row("D2", "b", supersedes="D1")], HEADER, "loops back"),
        ("a bad header", "badhead.tsv", [row("D1", "a")], "date\tid\tdecision", "badhead.tsv")):
    try:
        in_force(state.read_decision_rows(planted(folder, name, rows, header=header)))
        s.ok("%s is refused" % label, False, "no StateError")
    except state.StateError as e:
        s.ok("%s is refused, naming %s" % (label, word), word in str(e), str(e))
f = planted(folder, "branch.tsv", [row("D1", "old"), row("D2", "left", supersedes="D1"), row("D3", "right", supersedes="D1")])
s.eq("two rows replacing one: both stay in force, D1 points at the one written last",
     [(r["id"], r["in_force"], r["superseded_by"]) for r in in_force(state.read_decision_rows(f))], [("D1", False, "D3"), ("D2", True, ""), ("D3", True, "")])

s.done()
