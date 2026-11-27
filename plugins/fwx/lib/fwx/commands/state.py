"""Make, find, bind, record in and check the project's `.fwx/` state: fwx session|phase|subphase|milestone|decision <verb> [args] (`fwx --help` lists them).

A thin layer over lib/fwx/state.py, which holds every rule: this file parses the arguments, calls it, and prints. The
commands are `session` and `session attach`, `phase list|new|remove`, `subphase new`, `milestone new`, and `decision new`. Exit 0 when it is done, 1 when the state layer refuses or the phase cannot be resolved (one line on stderr, `resolve` also lists the open
phases), 2 when it cannot run: outside a git repository, a usage error, an unusable configuration. Never a traceback.
"""
import argparse
import json
import os
import re
import sys

from fwx import config, plan_form, routes, state
from fwx.core import stages

PROG = "fwx state"  # main() sets it to the name the command ran under (`fwx phase new`), for the messages
SUB_OF_PATH = re.compile(r"/" + re.escape(state.PLAN_DIR) + r"/subprojects/([^/]+)/")


class Unresolved(Exception):
    """No phase to act on (none open, or several and none bound): exit 1, with the message on one line."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("%s: %s (%s --help)\n" % (self.prog, message.replace("\n", " "), self.prog))
        sys.exit(2)


def _subproject_of(path):
    m = SUB_OF_PATH.search(os.path.abspath(str(path)).replace(os.sep, "/"))
    return m.group(1) if m else None


def _dump(obj):
    print(json.dumps(obj, indent=2))


# ---- resolve, list, use -----------------------------------------------------------------------------------------

def _unresolved(r):
    if r["candidates"]:
        return ("no phase is bound to this session and %d are open: %s (bind one with `fwx session attach PHASE_DIR`)"
                % (len(r["candidates"]), ", ".join(r["candidates"])))
    return "no open phase in %s (`fwx phase new SLUG` makes one)" % r["plan_root"]


def _bound_to(r, bound):
    return bool(bound and bound["phase_dir"]) and os.path.join(os.path.dirname(r["plan_root"]), bound["phase_dir"]) == r["phase_dir"]


def part_repos(r):
    """What `fwx session --json` prints as `part_repos`: one `{name, path, default_branch, worktree}` per part of the bound phase
    (its subphases in order, or the phase itself), the repository of `project.repos` the part works in and the phase worktree
    to make there, `<repo>-<milestone>-<phase>` so two repositories of one phase never share a folder, or the workspace itself
    (name null) at `<milestone>-<phase>`. A repository the plan names and `project.repos` lacks has a null path and worktree
    (`fwx plan lint` refuses that plan). Null with no phase and with no `project.repos`, where nothing changes."""
    main, phase = r["main_checkout"], r["phase_dir"]
    try:
        cfg = config.load(main, quiet=True)  # the workspace's own, not the nested repo's entry laid over it where the command runs
    except config.UnreadableFile:  # a fwx.json that is no JSON must not stop `fwx session`, as in state.summary
        return None
    # any other ConfigError (a wrong `project.repos` entry) stops the command, as it does from inside the nested repo: null would read as "no nested repos"
    repos = cfg["project"]["repos"]
    if not repos or not phase:
        return None
    base = "%s-%s" % (r["milestone"], os.path.basename(phase))
    if r.get("subproject"):  # two subprojects with a phase of one slug must not share a worktree
        base = "%s-%s" % (r["subproject"], base)
    out = []
    for part in r["subphases"] or [phase]:
        name = plan_form.part_repo(part, cfg)
        if name is None:
            out.append({"name": None, "path": main, "default_branch": cfg["project"]["default_branch"],
                        "worktree": os.path.join(main, ".claude", "worktrees", base)})
        elif name not in repos:
            out.append({"name": name, "path": None, "default_branch": None, "worktree": None})
        else:
            out.append({"name": name, "path": os.path.normpath(os.path.join(main, repos[name]["path"])),
                        "default_branch": repos[name].get("default_branch"),
                        "worktree": os.path.join(main, ".claude", "worktrees", "%s-%s" % (name, base))})
    return out


def cmd_resolve(a):
    sid = state.session_id(a.session)
    bound = state.read_session(session=sid)
    r = state.resolve(session=sid)
    if r["phase_dir"] and sid and not _bound_to(r, bound):  # the one open phase, found with nothing bound: bind it
        state.write_session(session=sid, subproject=r["subproject"], phase_dir=r["phase_dir"])
    if a.json:
        extra = state.summary(r)
        extra["part_repos"] = part_repos(r)
        extra["progress"] = (
            stages.progress(stages.current(r["phase_dir"]), extra["part"], extra["parts"]) if r["phase_dir"] else None)
        _dump(dict(r, **extra))
    elif r["phase_dir"]:
        print("phase_dir: %s" % r["phase_dir"])
        print("subproject: %s" % (r["subproject"] or "root"))
        print("milestone: %s" % r["milestone"])
    if not r["phase_dir"]:
        sys.stderr.write("%s: %s\n" % (PROG, _unresolved(r)))
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
    folder = state.new_phase(a.slug, subproject=a.subproject, milestone=a.milestone, session=a.session)
    print(folder)
    return 0


def cmd_new_subphase(a):
    print(state.new_subphase(a.phase_dir, a.slug))
    return 0


def cmd_new_milestone(a):
    root = state.plan_root()
    if not root.exists():
        raise state.StateError("%s does not exist: `fwx phase new SLUG` makes it with its project.md" % root)
    print(state.new_milestone(state.scope_root(root, a.subproject), a.name))
    return 0


def cmd_cancel(a):
    state.cancel_phase(a.phase_dir)
    print("cancelled %s" % os.path.abspath(a.phase_dir))
    return 0


# ---- decision, check --------------------------------------------------------------------------------------------

def _decision_file(a):
    """The file `decision` writes and `decisions` reads: the phase's decisions.tsv, or with --adr the scope's adr.tsv."""
    if a.phase:
        phase, sub = os.path.abspath(a.phase), _subproject_of(a.phase)
    else:
        r = state.resolve(session=a.session)
        if not r["phase_dir"]:
            raise Unresolved(_unresolved(r))
        phase, sub = r["phase_dir"], r["subproject"]
    return state.scope_root(state.plan_root(), sub) / "adr.tsv" if a.adr else os.path.join(phase, "decisions.tsv")


def cmd_decision(a):
    print(state.append_decision(_decision_file(a), decision=a.decision, why=a.why, support=a.support, rejected=a.rejected or "",
                                source=a.source or "", supersedes=a.supersedes or ""))
    return 0


def parser():
    p = _Parser(prog=PROG, description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True, metavar="subcommand")

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_, description=help_, prog="fwx " + routes.shown("state", [name]))
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
    return p


def main(argv):
    global PROG
    PROG = "fwx " + routes.shown("state", argv)
    try:
        a = parser().parse_args(argv)
    except SystemExit as e:  # a usage error (exit 2) or --help (exit 0)
        return e.code or 0
    try:
        return a.fn(a)
    except (state.StateError, Unresolved) as e:
        sys.stderr.write("%s: %s\n" % (PROG, str(e).replace("\n", " ")))
        return 1
    except config.ConfigError as e:
        sys.stderr.write("%s: %s\n" % (PROG, str(e).replace("\n", " ")))
        return 2
