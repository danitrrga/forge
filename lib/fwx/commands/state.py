"""Make, find, bind, record in and check the project's `.fwx/` state: fwx state <subcommand> [args] (--help lists them).

A thin layer over lib/fwx/state.py, which holds every rule: this file parses the arguments, calls it, and prints. The
subcommands are resolve, list, use, new-phase, new-subphase, new-milestone, cancel, decision and check. Exit 0 when it
is done, 1 when the state layer refuses or the phase cannot be resolved (one line on stderr, `resolve` also lists the open
phases), 2 when it cannot run: outside a git repository, a usage error, an unusable configuration. Never a traceback.
"""
import argparse
import json
import os
import re
import sys

from fwx import config, state

SUB_OF_PATH = re.compile(r"/" + re.escape(state.PLAN_DIR) + r"/subprojects/([^/]+)/")


class Unresolved(Exception):
    """No phase to act on (none open, or several and none bound): exit 1, with the message on one line."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("fwx state: %s (fwx state --help)\n" % message.replace("\n", " "))
        sys.exit(2)


def _subproject_of(path):
    m = SUB_OF_PATH.search(os.path.abspath(str(path)).replace(os.sep, "/"))
    return m.group(1) if m else None


def _dump(obj):
    print(json.dumps(obj, indent=2))


# ---- resolve, list, use -----------------------------------------------------------------------------------------

def _unresolved(r):
    if r["candidates"]:
        return ("no phase is bound to this session and %d are open: %s (bind one with `fwx state use PHASE_DIR`)"
                % (len(r["candidates"]), ", ".join(r["candidates"])))
    return "no open phase in %s (`fwx state new-phase SLUG` makes one)" % r["plan_root"]


def _bound_to(r, bound):
    return bool(bound and bound["phase_dir"]) and os.path.join(os.path.dirname(r["plan_root"]), bound["phase_dir"]) == r["phase_dir"]


def cmd_resolve(a):
    sid = state.session_id(a.session)
    bound = state.read_session(session=sid)
    r = state.resolve(session=sid)
    if r["phase_dir"] and sid and not _bound_to(r, bound):  # the one open phase, found with nothing bound: bind it
        state.write_session(session=sid, subproject=r["subproject"], phase_dir=r["phase_dir"])
    if a.json:
        _dump(r)
    elif r["phase_dir"]:
        print("phase_dir: %s" % r["phase_dir"])
        print("subproject: %s" % (r["subproject"] or "root"))
        print("milestone: %s" % r["milestone"])
    if not r["phase_dir"]:
        sys.stderr.write("fwx state: %s\n" % _unresolved(r))
        return 1
    return 0


def cmd_list(a):
    root = state.plan_root()
    scope = state.scope_root(root, a.subproject)
    out = {"plan_root": str(root), "subproject": a.subproject, "subprojects": state.subprojects(root), "milestones": []}
    for m in state.milestones(scope):
        rows = []
        for p in state.phases(scope, m):
            stage = state.last_stage(p)
            rows.append({"name": p.name, "dir": str(p), "stage": stage, "open": stage not in state.CLOSED_STAGES,
                         "subphases": [x.name for x in state.subphases(p)]})
        out["milestones"].append({"name": m, "phases": rows})
    if a.json:
        _dump(out)
        return 0
    for m in out["milestones"]:
        for p in m["phases"]:
            print("%s/%s  %s  %s" % (m["name"], p["name"], p["stage"] or "-", "open" if p["open"] else "done"))
            for x in p["subphases"]:
                print("    %s" % x)
    return 0


def cmd_use(a):
    if a.root:
        sub, phase = None, None
    elif a.subproject is not None:
        sub, phase = a.subproject, None
    else:
        phase = os.path.abspath(a.phase_dir)
        state._check_phase_dir(phase, "use")  # the state layer's own test of what a phase folder is
        sub = _subproject_of(phase)
    state.write_session(session=a.session, subproject=sub, phase_dir=phase)
    print("session %s: %s, phase %s" % (state.session_id(a.session), sub or "root", os.path.relpath(phase, os.path.dirname(str(state.plan_root()))) if phase else "none"))
    return 0


# ---- making and cancelling --------------------------------------------------------------------------------------

def cmd_new_phase(a):
    print(state.new_phase(a.slug, subproject=a.subproject, milestone=a.milestone, session=a.session))
    return 0


def cmd_new_subphase(a):
    print(state.new_subphase(a.phase_dir, a.slug))
    return 0


def cmd_new_milestone(a):
    root = state.plan_root()
    if not root.exists():
        raise state.StateError("%s does not exist: `fwx state new-phase SLUG` makes it with its PROJECT.md" % root)
    print(state.new_milestone(state.scope_root(root, a.subproject), a.name))
    return 0


def cmd_cancel(a):
    state.cancel_phase(a.phase_dir)
    print("cancelled %s" % os.path.abspath(a.phase_dir))
    return 0


# ---- decision, check --------------------------------------------------------------------------------------------

def cmd_decision(a):
    if a.phase:
        phase, sub = os.path.abspath(a.phase), _subproject_of(a.phase)
    else:
        r = state.resolve(session=a.session)
        if not r["phase_dir"]:
            raise Unresolved(_unresolved(r))
        phase, sub = r["phase_dir"], r["subproject"]
    path = state.scope_root(state.plan_root(), sub) / "adr.tsv" if a.adr else os.path.join(phase, "decisions.tsv")
    print(state.append_decision(path, decision=a.decision, why=a.why, support=a.support, rejected=a.rejected or "",
                                source=a.source or "", supersedes=a.supersedes or ""))
    return 0


def cmd_check(a):
    errors, warnings = (state.check_state if a.kind == "state" else state.check_report)(a.path)
    for w in warnings:
        print("WARN: %s" % w)
    for e in errors:
        sys.stderr.write("fwx state: %s\n" % e.replace("\n", " "))
    if not errors and not warnings:
        print("ok")
    return 1 if errors else 0


def parser():
    p = _Parser(prog="fwx state", description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True, metavar="subcommand")

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.set_defaults(fn=fn)
        return sp

    sp = add("resolve", cmd_resolve, "where the session is: its phase, binding it when exactly one phase is open")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--session")
    sp = add("list", cmd_list, "the milestones and phases of a scope, with each phase's stage")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--subproject")
    sp = add("use", cmd_use, "bind the session to a phase folder, a subproject or the root")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("phase_dir", nargs="?")
    g.add_argument("--subproject")
    g.add_argument("--root", action="store_true")
    sp.add_argument("--session")
    sp = add("new-phase", cmd_new_phase, "make the next phase folder and bind the session to it")
    sp.add_argument("slug")
    sp.add_argument("--subproject")
    sp.add_argument("--milestone")
    sp.add_argument("--session")
    sp = add("new-subphase", cmd_new_subphase, "make the next subphase folder of a phase")
    sp.add_argument("phase_dir")
    sp.add_argument("slug")
    sp = add("new-milestone", cmd_new_milestone, "make the next milestone (or vN) of a scope")
    sp.add_argument("name", nargs="?", metavar="vN")
    sp.add_argument("--subproject")
    sp = add("cancel", cmd_cancel, "delete a phase whose discuss was cancelled, and nothing else")
    sp.add_argument("phase_dir")
    sp = add("decision", cmd_decision, "add a row to the phase's decisions.tsv, or with --adr to the scope's adr.tsv")
    sp.add_argument("--adr", action="store_true")
    sp.add_argument("--decision", required=True)
    sp.add_argument("--why", required=True)
    sp.add_argument("--support", required=True)
    sp.add_argument("--rejected")
    sp.add_argument("--source")
    sp.add_argument("--supersedes")
    sp.add_argument("--phase")
    sp.add_argument("--session")
    sp = add("check", cmd_check, "check a state.md or a phase report: an error for a rule, a WARN line for a length")
    sp.add_argument("kind", choices=("state", "report"))
    sp.add_argument("path")
    return p


def main(argv):
    try:
        a = parser().parse_args(argv)
    except SystemExit as e:  # a usage error (exit 2) or --help (exit 0)
        return e.code or 0
    try:
        return a.fn(a)
    except (state.StateError, Unresolved) as e:
        sys.stderr.write("fwx state: %s\n" % str(e).replace("\n", " "))
        return 1
    except config.ConfigError as e:
        sys.stderr.write("fwx state: %s\n" % str(e).replace("\n", " "))
        return 2
