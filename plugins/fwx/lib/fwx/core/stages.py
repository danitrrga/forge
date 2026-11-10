"""The stage machines of data/stages.json, their validator, and the one way to change a stage: `advance`.

Two machines, `session` (one supervised phase) and `factory` (one factory job): `{start, terminal, transitions}` each,
`transitions` being `{from: [to, ...]}`. Only scripts change a stage, and the table is the check. A legal change is
recorded through `state.append_audit`, which this module never bypasses; the stage a folder is in is
`state.last_stage` (the target of its last `stage` row) or, with no row yet, the machine's start.

The machine follows the path: a folder under `.fwx/factory/` is a factory job, every other folder is a session phase.
A phase's start is `discuss`, except in a subphase nested in a phase (`phases/<NN-slug>/<NN.M-slug>`): its discuss and
its plan were done in the phase, so it starts in `executing`. An `NN.M-slug` folder directly under `phases/` (the
converter's) is a phase of its own and starts in `discuss`; the parent tells them apart, never the folder's own name.

`advance` reads the current stage and writes the new one in two steps, with no lock: two scripts changing the same folder
at the same moment are not serialised (one folder has one driver at a time).

Imports only the standard library and `state`.
"""
import json
import os
import re

from fwx import state

TABLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))),
                     "data", "stages.json")
MACHINES = ("session", "factory")
_STAGE = re.compile(r"[a-z][a-z-]*\Z")  # what state.append_audit takes as a target stage


class Refused(state.StateError):
    """The table does not allow the change. A StateError too: callers that only care that nothing was written catch that."""


def load(path=None):
    """The table, validated. A table with a problem raises StateError naming every problem."""
    try:
        with open(path or TABLE, encoding="utf-8") as f:
            table = json.load(f)
    except (OSError, ValueError) as e:
        raise state.StateError("%s cannot be read (%s)" % (path or TABLE, e))
    problems = validate(table)
    if problems:
        raise state.StateError("%s is not a valid stage table: %s" % (path or TABLE, "; ".join(problems)))
    return table


def validate(table):
    """The problems of a table, as a list of sentences ([] is a good table). Checked: exactly the machines `session` and
    `factory`; per machine a `start`, a non-empty list of `terminal` stages, `transitions` as `{from: [to, ...]}` with
    stage names `audit rows can carry`, no target twice, no terminal stage with a way out, no target that is neither
    terminal nor has transitions of its own (a dead end), every stage reachable from the start, and a terminal stage
    reachable."""
    if not isinstance(table, dict):
        return ["the table is not a JSON object"]
    problems = []
    for name in MACHINES:
        if name not in table:
            problems.append("machine %s is missing" % name)
    for name in table:
        if name not in MACHINES:
            problems.append("machine %s is not one of %s" % (name, ", ".join(MACHINES)))
    for name in MACHINES:
        if isinstance(table.get(name), dict):
            problems += ["%s: %s" % (name, p) for p in _machine(table[name])]
        elif name in table:
            problems.append("%s: not an object" % name)
    return problems


def _machine(m):
    start, terminal, trans = m.get("start"), m.get("terminal"), m.get("transitions")
    if not isinstance(start, str):
        return ["start is missing or not a string"]
    if not isinstance(terminal, list) or not terminal or not all(isinstance(t, str) for t in terminal):
        return ["terminal must be a non-empty list of stages"]
    if not isinstance(trans, dict):
        return ["transitions must be an object {from: [to, ...]}"]
    problems = []
    for frm, tos in trans.items():
        if not isinstance(tos, list) or not all(isinstance(t, str) for t in tos):
            problems.append("transitions of %s must be a list of stages" % frm)
    if problems:
        return problems
    names = {start, *terminal, *trans, *(t for tos in trans.values() for t in tos)}
    for n in sorted(names):
        if not _STAGE.match(n):
            problems.append("stage name %r is not lower-case letters and -" % n)
    for frm, tos in trans.items():
        for t in sorted({t for t in tos if tos.count(t) > 1}):
            problems.append("%s -> %s is listed twice" % (frm, t))
    for t in terminal:
        if trans.get(t):
            problems.append("terminal stage %s has transitions" % t)
    if start not in trans:
        problems.append("start %s is not a stage with transitions" % start)
    for t in sorted(names):
        if t not in terminal and not trans.get(t):
            problems.append("stage %s is a dead end: not terminal and nowhere to go" % t)
    seen, todo = {start}, [start]
    while todo:
        for t in trans.get(todo.pop(), []):
            if t not in seen:
                seen.add(t)
                todo.append(t)
    for n in sorted(names - seen):
        problems.append("stage %s is not reachable from the start %s" % (n, start))
    if not seen & set(terminal):
        problems.append("no terminal stage is reachable from the start")
    return problems


def allowed(machine, frm, to, table=None):
    """Whether `frm -> to` is in the machine's transitions. An unknown machine or stage is False."""
    m = (table or load()).get(machine)
    if not isinstance(m, dict):
        return False
    return to in m["transitions"].get(frm, ())


def machine_of(dir):
    """`factory` for a folder under `.fwx/factory/`, else `session`."""
    parts = os.path.abspath(str(dir)).split(os.sep)
    return "factory" if any(a == ".fwx" and b == "factory" for a, b in zip(parts, parts[1:])) else "session"


def start_of(dir, table=None):
    """The stage a folder with no stage row is in: the machine's start, but `executing` for a subphase nested in a phase."""
    table = table or load()
    machine = machine_of(dir)
    if machine == "session":
        p = os.path.abspath(str(dir))
        if state._SUBPHASE.match(os.path.basename(p)) and state._PHASE.match(os.path.basename(os.path.dirname(p))):
            return "executing"
    return table[machine]["start"]


def current(dir, table=None):
    """The stage a folder is in: the target of its last `stage` row, else `start_of`."""
    return state.last_stage(dir) or start_of(dir, table)


def advance(dir, to, why="", cwd=None, table=None):
    """Move the folder to stage `to` if its machine allows it, and return the stage it left. The row is written by
    `state.append_audit` with the HEAD of `cwd` (default: the folder itself) and the detail `<to> <why>`. A change the
    table does not allow raises Refused (a StateError) `<from> -> <to> is not in data/stages.json (<machine>)` and writes nothing."""
    if not os.path.isdir(str(dir)):
        raise state.StateError("%s is not a folder" % dir)
    table = table or load()
    machine, frm = machine_of(dir), current(dir, table)
    if not allowed(machine, frm, to, table):
        raise Refused("%s -> %s is not in data/stages.json (%s)" % (frm, to, machine))
    detail = ("%s %s" % (to, why or "")).strip()
    state.append_audit(dir, "stage", detail=detail, cwd=str(dir) if cwd is None else cwd)
    return frm
