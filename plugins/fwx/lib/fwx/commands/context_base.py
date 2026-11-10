"""Build, seal, check and audit the base-context file every agent of a phase is handed: fwx context-base build|seal|check|audit.

  build <dir> [--map F]      write the base of a phase, subphase or job folder (`<git-common-dir>/fwx/context-base/<phase>.md`)
                             when it changed; prints `wrote <path> <n> units (map <m>, goal <g>, decided <d>)`, or `unchanged ...`
  seal <file> [--source F]   put the mark on a file written by hand, and with --source the sha of the document it shortens
  check <dir> | --file F | --project P   [--source F] [--map F] [--hook-command CMD]
                             exit 1 when the base is missing (with a context.md), over the cap, edited since sealed, stale
                             (stage, context.md, decisions.tsv, the map or --source moved on) or names an `fwx` command that
                             does not exist; --hook-command runs CMD with a toy SubagentStart input and wants the base for
                             general-purpose and nothing for Explore; always prints how much it looked at
  audit (--session ID | --project P [--last N]) [--projects-dir D] [--file F]
                             read the subagent transcripts of a session (or of the N newest sessions of a project that have
                             any, default 1) and say which agent did not get the base its type should get: one line
                             `FAIL <agent_id> <type>: <verdict>` per failure (missing, over-cap, wrong, double), `WARN` for a
                             stale one, and `audited <n> subagent(s) in <s> session(s): <ok> ok, <w> stale, <k> not armed`.
                             What is owed comes from data/context-base.tsv and from the base file of today: --file F, else the
                             open phase of the session's cwd (of P); with neither, an agent that got nothing is `not armed`.
                             --projects-dir defaults to ${CLAUDE_CONFIG_DIR:-~/.claude}/projects. Exit 1 on any FAIL.

Lengths are UTF-16 units, cap 9000 (lib/fwx/context_base.py says why). --map points at another map than data/context-map.md.
Exit 0 ok, 1 refused or failed, 2 usage or an unusable folder, 77 `NOT RUN, NOT ARMED` (check --project: no open phase; audit: no
subagent transcript found).
"""
import os
import sys

from fwx import config, context_audit as ca, context_base as cb, state

USAGE = ("usage: fwx context-base build <dir> [--map F]\n"
         "       fwx context-base seal <file> [--source F]\n"
         "       fwx context-base check (<dir> | --file F | --project P) [--source F] [--map F] [--hook-command CMD]\n"
         "       fwx context-base audit (--session ID | --project P [--last N]) [--projects-dir D] [--file F]\n")
NOT_RUN = "NOT RUN, NOT ARMED"


def _options(args, names):
    """`(positional, {--name: value})`, or None when an option is unknown, repeated or has no value."""
    pos, opts, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a in names:
            if a in opts or i + 1 >= len(args):
                return None
            opts[a] = args[i + 1]
            i += 2
        elif a.startswith("--"):
            return None
        else:
            pos.append(a)
            i += 1
    return pos, opts


def _usage(why=""):
    sys.stderr.write((("fwx context-base: %s\n" % why) if why else "") + USAGE)
    return 2


def _build(args):
    got = _options(args, ("--map",))
    if got is None or len(got[0]) != 1:
        return _usage()
    (folder,), opts = got
    r = cb.build(folder, opts.get("--map"))
    print("%s %s %d units (map %d, goal %d, decided %d)" % ("wrote" if r["written"] else "unchanged", r["path"], r["units"],
                                                           r["map"], r["goal"], r["decided"]))
    if r["warning"]:
        sys.stderr.write("context-base: %s\n" % r["warning"])
    return 0


def _seal(args):
    got = _options(args, ("--source",))
    if got is None or len(got[0]) != 1:
        return _usage()
    (path,), opts = got
    cb.seal(path, opts.get("--source"))
    print("sealed %s" % path)
    return 0


def _check(args):
    got = _options(args, ("--file", "--project", "--source", "--map", "--hook-command"))
    if got is None:
        return _usage()
    pos, opts = got
    if len(pos) + sum(k in opts for k in ("--file", "--project")) != 1:
        return _usage("exactly one of <dir>, --file or --project")
    map_path, source = opts.get("--map"), opts.get("--source")
    folder = pos[0] if pos else None
    if "--project" in opts:
        res = state.resolve(opts["--project"])
        folder = res["phase_dir"]
        if folder is None:
            print("%s: no open phase" % NOT_RUN)
            return 77
    if folder is not None:
        path = cb.base_path(folder)
        if cb._text(path) is None and not os.path.exists(state.phase_paths(folder)["context"]):
            print("checked 0 files, 0 units, nothing built yet (no base and no context.md in %s)" % folder)
            return 0
    else:
        path = opts["--file"]
        if cb._text(path) is None:
            sys.stderr.write("fwx context-base: %s is not there\n" % path)
            return 2
    n, problems = cb.inspect(path, folder=folder, map_path=map_path, source=source)
    if "--hook-command" in opts and not problems:
        first = (cb._text(path) or "").split("\n", 1)[0]
        problems += cb.hook_problems(opts["--hook-command"], first, folder or os.getcwd())
    for p in problems:
        sys.stderr.write("context-base: %s\n" % p)
    print("checked 1 file, %d units, %s" % (n, "sources current" if not problems else "%d problem(s)" % len(problems)))
    return 1 if problems else 0


def _audit(args):
    got = _options(args, ("--session", "--project", "--last", "--projects-dir", "--file"))
    if got is None or got[0]:
        return _usage()
    opts = got[1]
    if ("--session" in opts) == ("--project" in opts):
        return _usage("exactly one of --session or --project")
    if "--last" in opts and "--project" not in opts:
        return _usage("--last goes with --project")
    last = opts.get("--last", "1")
    if not last.isdigit() or int(last) < 1:
        return _usage("--last wants a number of sessions, 1 or more")
    try:
        sessions = ca.find_sessions(ca.projects_dir(opts.get("--projects-dir")), session=opts.get("--session"),
                                    project=opts.get("--project"), last=int(last))
        lines, rc = ca.report(ca.audit(sessions, file=opts.get("--file"), project=opts.get("--project")))
    except ca.AuditError as e:
        sys.stderr.write("fwx context-base: %s\n" % e)
        return 2
    print("\n".join(lines))
    return rc


def main(argv):
    if not argv or argv[0] not in ("build", "seal", "check", "audit"):
        return _usage()
    try:
        return {"build": _build, "seal": _seal, "check": _check, "audit": _audit}[argv[0]](list(argv[1:]))
    except cb.ContextBaseError as e:
        sys.stderr.write("context-base: %s\n" % e)
        return 1 if argv[0] == "build" and "over the cap" in str(e) else 2
    except (state.StateError, config.ConfigError) as e:
        sys.stderr.write("fwx context-base: %s\n" % e)
        return 2
