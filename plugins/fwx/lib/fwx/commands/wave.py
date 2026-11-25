"""Prepare a part, run it, check an executor's base, and join, fix, undo and clean up its waves:
fwx wave [new|run|list|merge|fix|revert|remove|setup] ..., `fwx base`, `fwx scratch new`. `fwx wave` alone is the summary.
The steps keep their old names inside: in the run's files (`<n>-<step>.json`), in the `step` of a call, in this file's functions.

`wave new --part-dir D --plane session|factory --branch W [--unattended] [--security] [--fix F] [--revert IDS]
[--control-findings F] [--from gate]` validates the part `D` from the integration checkout (the current folder, on branch `W`) and prints
the `args` of `execute` as one JSON object (execute/prepare.py says what it checks and what it leaves out). Exit 0, 1 when
the base fails its own checks (a needs-owner JSON line on stdout, `rounds <used>/<cap>` on stderr, no round spent), 77 when a
base check ran out of time and none is red (`NOT RUN: ...` on stderr, nothing on stdout, no round spent: the machine was too slow,
the base is not red; run it again), 2 for anything that must stop the run before it starts, with the reason on stderr and nothing
written. A base that ran green is recorded as an `evidence` row of the part, and a second `wave new` on the same base and checks
reuses it. `--from gate` is the way back
into the checks once every task is on the phase branch (the tree's n_C7F loops to n_C7): execute/prepare.py says what it changes.

`wave run` takes the flags of `wave new` (or `--resume R`) and `--orchestrator orca_session_id:<uuid>` (the chat that started it: the run sends it each worker's question
and escalation, one line per wave and one at the end, and the chat answers a worker with `orca orchestration send --to dispatch:<D>`; saved with the run, accepted again
on `--resume` to refresh it, refused with `--plane factory` and `--unattended`; execute/run.py says how), prepares the part in process, exits as `wave new` does (1, 77, 2) before it
starts anyone, then drives the part to its end with every agent an Orca worker (execute/run.py says how, execute/orca.py is the one module that
talks to Orca) and prints one line, `run <R> <done|failed|needs-owner>: <why>`, exit 0, 1 and 3 for the three; it exits 2 when a live run already
holds the branch (naming it and `--resume`) and when there is no base context to give a worker. `wave list` prints one line per run (id, part,
branch, state, pid and whether it lives, open workers of the total, last step).

`fwx base <sha> [--worktree P]` is step 0 of every agent that writes: exit 0 when the current folder is a linked worktree
(the one at `P`, when given) whose HEAD is `<sha>` (a fresh worktree, as Claude Code made it and nothing written in it, is first moved there: execute/base.py `_fresh`),
42 when it is not (`wrong base: HEAD <x>, expected <sha>` or `not a linked
worktree: <path>` on stderr), 2 for a usage error. `<sha>` is 7 to 40 hex digits. With the base right it then runs the project's
`worktree_setup` (below), so that the agent's own checks find the dependencies: exit 43 when that fails, with `worktree setup
failed: <command> (exit N, log PATH)` on stderr, which is the reason the agent reports, and in `.fwx-agent/worktree-setup-failed.json`
of the worktree, which the workflow reads to end the job; nothing configured prints nothing. It reads
that one field of the configuration (`config.setup_commands`) and no other value: a project that never set it behaves as before,
and a configuration file that cannot be read is 43 too, naming the file (it cannot say whether a setup is owed).

`wave setup [--force]` runs `project.worktree_setup` in the current linked worktree (execute/worktree_setup.py says how, and what it
refuses): exit 0 with a line on stdout saying how many commands ran, that it was already done, or that none is configured; 1 when a
command failed, ran past its limit or left files git does not ignore (the reason on stderr); 2 in the main checkout, outside a
repository, for a configuration it cannot read and for a usage error. `wave new` calls it in the phase worktree before the base runs,
and `wave merge` after the merges and before its checks, and `wave revert` after the reverts (a merged or reverted lockfile needs the
dependencies again; a failure is exit 1 and `setup` in the JSON).

`fwx scratch new <run> <unit>` makes the folder an agent writes its report and its TMPDIR in, inside its own worktree and ignored by git, and
prints its path (execute/base.py says why it is not under `.git`): exit 0, 2 for a usage error or outside a repository.

The rest is 3.4 U3 (execute/integrate.py and execute/cleanup.py say what each does); each prints its result as one JSON
object on stdout and also writes it, with the exit code and its arguments, to `<git-common-dir>/fwx/runs/<run>/<n>-<step>.json`
(`n` counts the run's files; `wave new` and `base` write none, and neither does a call that stops on a usage error or on
something that must stop it before it starts, exit 2 with a reason on stderr):
  wave merge --part-dir D --run R (--branches B... | --final) [--findings IDS] [--final]
      with no branch (only with --final) nothing is merged and the gate runs on the head as it is;
      exit 0 merged and green, 1 a conflict or a red check, 2 refused (a live agent holds a branch, the commits are not one per
      finding, the checkout is dirty, a usage error), 77 NOT RUN, NOT ARMED: no /proc (a lock cannot be read)
  wave fix --part-dir D --why TEXT [--run R]     (a file in the run only with --run; the factory's job has none)
      exit 0 the failure may be fixed (a round spent, or the evidence already counted), 1 the
      rounds are spent and nothing was spent now, 2 usage
  wave revert --part-dir D --run R --findings IDS     exit 0, 1 a revert conflicted (aborted), 2 an id with no single commit
  wave remove --run R     exit 0; 77 without /proc. It reads the branches `wave merge` named and the worktrees `wave run` made from the run's files
  wave report --part-dir D --run R --unit U --line "<last line of the reply>" --plane session|factory
      exit 0 with `next` merge|relaunch|retry|owner|stop (execute/report.py says what each means and what it reads); a miss is
      counted from the run's own files, so each call is recorded; 2 a usage error, an unreadable plan or configuration
  wave review --part-dir D --run R --from A --to B [--security]
      exit 0 with `next` launch: the briefs of the pass's reviewer, and of the security reviewer when `--security`, the post-mortem or a
      protected path of the run's last final merge asks for it (execute/review.py); 2 a ref that is no commit, an unreadable plan, a usage error
  wave findings --run R (--report "<last line of a reviewer's reply>"... | --verdicts "<last line of the verifier's reply>") [--control-findings F]
      exit 0 with `next` relaunch|stop|verify|fix|owner|done (execute/review.py says what each means): the findings numbered by the pass, the
      verifier only above three items, the verdicts routed; the part is the one the run's `wave review` named; 2 a call with no pass to read
  wave --run R [--part-dir D] [--json]  exit 0 gate pass, 1 fail, 2 none; the part comes from the run's files unless given. A run
      that merged branches passes only when its own last `wave merge --final` was green (`why` says when it was not): the evidence
      row is the part's, so another run's green gate on the same head is not this run's
"""
import json
import os
import re
import sys

from fwx import config, plan_step, routes, state
from fwx.execute import base, cleanup, integrate, prepare as prep, report, review, run as run_mod, worktree_setup

PREPARE_USAGE = ("usage: fwx wave new --part-dir D --plane session|factory --branch W [--unattended] [--security] "
                 "[--fix F] [--revert IDS] [--control-findings F] [--from gate]\n")
RUN_USAGE = ("usage: fwx wave run --part-dir D --plane session|factory --branch W [--unattended] [--security] [--fix F] [--revert IDS] "
             "[--control-findings F] [--from gate] [--orchestrator orca_session_id:<uuid>]   |   fwx wave run --resume R [--orchestrator orca_session_id:<uuid>]\n")
LIST_USAGE = "usage: fwx wave list\n"
CHECK_USAGE = "usage: fwx base <sha> [--worktree P]   (sha: 7 to 40 hex digits)\n"
SETUP_USAGE = "usage: fwx wave setup [--force]\n"
SCRATCH_USAGE = "usage: fwx scratch new <run> <unit>   (each one folder name: letters, digits, `.`, `_`, `-`)\n"
USAGES = {
    "integrate": "usage: fwx wave merge --part-dir D --run R (--branches B... | --final) [--findings IDS] [--final]\n",
    "fix-round": "usage: fwx wave fix --part-dir D --why TEXT [--run R]\n",
    "revert": "usage: fwx wave revert --part-dir D --run R --findings IDS\n",
    "cleanup": "usage: fwx wave remove --run R\n",
    "summary": "usage: fwx wave --run R [--part-dir D] [--json]\n",
    "report": "usage: fwx wave report --part-dir D --run R --unit U --line \"<last line of the reply>\" --plane session|factory\n",
    "review": "usage: fwx wave review --part-dir D --run R --from A --to B [--security]\n",
    "findings": "usage: fwx wave findings --run R (--report \"<last line of a reviewer's reply>\"... | --verdicts \"<last line of the verifier's reply>\") [--control-findings F]\n",
}
_RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_ORCHESTRATOR = re.compile(r"orca_session_id:[0-9A-Za-z][0-9A-Za-z-]*\Z")


def _parse(argv, flags, valued, many=()):
    """({name: value or True}, [positionals]) or None for an option nobody knows or a valued one with no value. An option of
    `many` takes every word up to the next option (a list)."""
    got, pos, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in many:
            j = i + 1
            while j < len(argv) and not argv[j].startswith("-"):
                j += 1
            if j == i + 1:
                return None
            got[a] = argv[i + 1:j]
            i = j
            continue
        if a in valued:
            if i + 1 >= len(argv):
                return None
            got[a] = argv[i + 1]
            i += 2
            continue
        if a in flags:
            got[a] = True
        elif a.startswith("-"):
            return None
        else:
            pos.append(a)
        i += 1
    return got, pos


def prepared(got, say):
    """(exit code, args) for the flags of `wave new`: the args of the part, or the code `wave new` exits with and nothing else (the
    reason is on stderr, a red base's JSON on stdout)."""
    revert = [i.strip() for i in got["--revert"].split(",") if i.strip()] if "--revert" in got else None
    try:
        args = prep.prepare(".", got["--part-dir"], got["--plane"], got["--branch"], "--unattended" in got, "--security" in got,
                            got.get("--fix"), revert, got.get("--control-findings"), got.get("--from"), say=say)
    except prep.RedBase as e:
        print(json.dumps(e.status))
        sys.stderr.write("fwx wave new: %s\n%s\nrounds %s\n" % (e, e.shown, e.status["rounds"]))
        return 1, None
    except prep.NotRun as e:
        sys.stderr.write("fwx wave new: %s\n" % e)
        return 77, None
    except (base.WaveError, config.ConfigError, state.StateError, plan_step.CannotRun) as e:
        sys.stderr.write("fwx wave new: %s\n" % e)
        return 2, None
    return 0, args


def do_prepare(argv):
    parsed = _parse(argv, ("--unattended", "--security"), ("--part-dir", "--plane", "--branch", "--fix", "--revert", "--control-findings", "--from"))
    if parsed is None or parsed[1] or any(k not in parsed[0] for k in ("--part-dir", "--plane", "--branch")):
        sys.stderr.write(PREPARE_USAGE)
        return 2

    def say(line):
        sys.stderr.write("fwx wave new: %s\n" % line)
    code, args = prepared(parsed[0], say)
    if code:
        return code
    print(json.dumps(args))
    return 0


def do_run(argv):
    """`wave run`: the flags of `wave new`, or `--resume R`. Exit 0 a run that ended done, 1 failed, 3 needs-owner (its line on stdout);
    before any worker: what `wave new` exits with (1 a red base, 77 a base check out of time, 2 a refusal), and 2 for a live run on the branch."""
    parsed = _parse(argv, ("--unattended", "--security"), ("--part-dir", "--plane", "--branch", "--fix", "--revert", "--control-findings", "--from", "--resume", "--orchestrator"))
    if parsed is None or parsed[1] or ("--resume" not in parsed[0] and any(k not in parsed[0] for k in ("--part-dir", "--plane", "--branch"))):
        sys.stderr.write(RUN_USAGE)
        return 2
    got = parsed[0]
    orch = got.get("--orchestrator")
    if orch is not None and not _ORCHESTRATOR.match(orch):
        sys.stderr.write("fwx wave run: --orchestrator takes orca_session_id:<uuid> (the address of the chat that starts the run), not %r\n" % orch)
        return 2
    if orch and ("--unattended" in got or got.get("--plane") == "factory"):
        sys.stderr.write("fwx wave run: --orchestrator is for the session plane with its owner present: a factory or unattended run has nobody to steer it\n")
        return 2

    def say(line):
        sys.stderr.write("fwx wave run: %s\n" % line)
    try:
        top = base.toplevel(os.getcwd())
        if top is None:
            raise base.WaveError("not inside a git repository: %s" % os.getcwd())
        saved = None
        if "--resume" in got:
            if not _RUN_NAME.match(got["--resume"]) or run_mod.load_state(top, got["--resume"]) is None:
                raise base.WaveError("--resume %s: no such run (`fwx wave list`)" % got["--resume"])
            saved = run_mod.load_state(top, got["--resume"])
            if saved["state"] != "active":
                raise base.WaveError("run %s ended %s: there is nothing to resume" % (saved["run"], saved["state"]))
            if orch and (saved["args"].get("plane") == "factory" or saved["args"].get("unattended")):
                raise base.WaveError("--orchestrator: run %s is a factory or unattended run, which has nobody to steer it" % saved["run"])
        branch = saved["branch"] if saved else got["--branch"]
        if saved:  # `prepare` refuses a checkout that is not on the branch for a new run; a resumed run merges into whatever is checked out
            on = base.out(top, "symbolic-ref", "--short", "-q", "HEAD")
            if on != branch:
                raise base.WaveError("run %s works on %s and the checkout %s is on %s: check %s out first" % (saved["run"], branch, top, on or "no branch (detached HEAD)", branch))
        live = run_mod.holder(top, branch)
        if live:
            raise base.WaveError("run %s is already running on %s (pid %s): wait for it, or start again with `fwx wave run --resume %s` once it ended"
                                 % (live["run"], branch, live.get("pid"), live["run"]))
        lock = run_mod.lock_branch(top, branch)  # held to the end of the process: a second command that passed the check above before this run was recorded stops here
        if saved:
            args, flags = saved["args"], saved["flags"]
            if orch:  # a resumed run goes on to the address given now: the session that started it may be another chat
                flags["orchestrator"] = orch
        else:
            code, args = prepared(got, lambda line: sys.stderr.write("fwx wave new: %s\n" % line))
            if code:
                return code
            ctrl = got.get("--control-findings")
            flags = {"control": os.path.abspath(ctrl) if ctrl else None, "orchestrator": orch}
        status, line, kept = run_mod.drive(args, top, flags, saved)
    except (base.WaveError, config.ConfigError, state.StateError) as e:
        sys.stderr.write("fwx wave run: %s\n" % e)
        return 2
    for k in kept:
        say("kept %s: %s" % (k["worktree"], k["why"]))
    print(line)
    return {"done": 0, "failed": 1, "needs-owner": 3}[status]


def do_list(argv):
    if argv:
        sys.stderr.write(LIST_USAGE)
        return 2
    try:
        top = base.toplevel(os.getcwd())
        if top is None:
            raise base.WaveError("not inside a git repository: %s" % os.getcwd())
        rows = run_mod.listing(top)
    except base.WaveError as e:
        sys.stderr.write("fwx wave list: %s\n" % e)
        return 2
    for row in rows:
        print(row)
    return 0


def do_check_base(argv):
    parsed = _parse(argv, (), ("--worktree",))
    if parsed is None or len(parsed[1]) != 1 or not base.SHA.match(parsed[1][0]):
        sys.stderr.write(CHECK_USAGE)
        return 2
    try:
        code, why = base.check_base(parsed[1][0], os.getcwd(), parsed[0].get("--worktree"))
    except base.WaveError as e:
        code, why = base.WRONG_BASE, str(e)
    if why:
        sys.stderr.write("fwx base: %s\n" % why)
    if code:
        return code
    # The base is right: the agent's checks need the project's dependencies in this worktree, so the setup is part of step 0.
    try:
        result = worktree_setup.run(os.getcwd(), config.setup_commands(os.getcwd()))
    except worktree_setup.SetupFailed as e:
        return _setup_failed(str(e))
    except (base.WaveError, config.ConfigError) as e:
        return _setup_failed("worktree setup failed: %s" % e)
    worktree_setup.clear_failure(os.getcwd())
    if result["state"] != "none":
        sys.stderr.write(worktree_setup.summary(result) + "\n")
    return 0


def _setup_failed(line):
    """Exit 43: the line on stderr, and as a record in the worktree for the workflow (worktree_setup.record_failure)."""
    sys.stderr.write("%s\n" % line)
    worktree_setup.record_failure(os.getcwd(), line)
    return base.SETUP_FAILED


def do_setup(argv):
    parsed = _parse(argv, ("--force",), ())
    if parsed is None or parsed[1]:
        sys.stderr.write(SETUP_USAGE)
        return 2
    try:
        top = base.toplevel(os.getcwd())
        if top is None:
            raise base.WaveError("not inside a git repository: %s" % os.getcwd())
        result = worktree_setup.run(top, config.setup_commands(top), force="--force" in parsed[0])
    except worktree_setup.SetupFailed as e:
        sys.stderr.write("fwx wave setup: %s\n" % e)
        return 1
    except (base.WaveError, config.ConfigError) as e:
        sys.stderr.write("fwx wave setup: %s\n" % e)
        return 2
    print(worktree_setup.summary(result))
    return 0


def do_scratch(argv):
    parsed = _parse(argv, (), ())
    if parsed is None or len(parsed[1]) != 2 or not all(base.NAME.match(w) for w in parsed[1]):
        sys.stderr.write(SCRATCH_USAGE)
        return 2
    try:
        print(base.scratch(os.getcwd(), *parsed[1]))
    except base.WaveError as e:
        sys.stderr.write("fwx scratch new: %s\n" % e)
        return 2
    return 0


def _ids(text):
    return [i.strip() for i in text.split(",") if i.strip()]


def _record(top, run, step, args, result, code):
    """Write the call's result to <git-common-dir>/fwx/runs/<run>/<n>-<step>.json and return the path."""
    common = base.out(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        raise base.WaveError("cannot find the git common dir of %s" % top)
    folder = os.path.join(common, "fwx", "runs", run)
    os.makedirs(folder, exist_ok=True)
    n = 1 + max([int(m.group(1)) for m in (re.match(r"(\d+)-", f) for f in os.listdir(folder)) if m], default=0)
    path = os.path.join(folder, "%d-%s.json" % (n, step))
    try:
        with open(path, "x", encoding="utf-8") as f:
            json.dump({"step": step, "exit": code, "args": args, "result": result}, f, indent=1)
            f.write("\n")
    except OSError as e:
        raise base.WaveError("cannot write %s: %s" % (path, e))
    return path


def _steps(top, run):
    """The calls the run's own files record, oldest first: [{step, exit, args, result}]; a file that cannot be read is left out."""
    common = base.out(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    folder = os.path.join(common or "", "fwx", "runs", run)
    names = sorted((f for f in os.listdir(folder) if re.match(r"\d+-", f)), key=lambda f: int(f.split("-")[0])) if os.path.isdir(folder) else []
    found = []
    for name in names:
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            found.append(rec)
    return found


def _part_of(top, run):
    """The part folder the run's own files name (the newest call that had one), or None."""
    for rec in reversed(_steps(top, run)):
        if rec.get("args", {}).get("part_dir"):
            return rec["args"]["part_dir"]
    return None


def do_step(step, argv):
    """integrate, fix-round, revert, cleanup, summary, report, review and findings: parse, run, print the JSON, record it."""
    flags = {"integrate": ("--final",), "review": ("--security",), "summary": ("--json",)}.get(step, ())  # summary: JSON is its only output
    valued = {"integrate": ("--part-dir", "--run", "--findings"), "fix-round": ("--part-dir", "--why", "--run"),
              "revert": ("--part-dir", "--run", "--findings"), "cleanup": ("--run",), "summary": ("--run", "--part-dir"),
              "report": ("--part-dir", "--run", "--unit", "--line", "--plane"), "review": ("--part-dir", "--run", "--from", "--to"),
              "findings": ("--run", "--verdicts", "--control-findings")}[step]
    parsed = _parse(argv, flags, valued, many={"integrate": ("--branches",), "findings": ("--report",)}.get(step, ()))
    need = {"integrate": ("--part-dir", "--run") + (() if parsed and "--final" in parsed[0] else ("--branches",)), "fix-round": ("--part-dir", "--why"),
            "revert": ("--part-dir", "--run", "--findings"), "cleanup": ("--run",), "summary": ("--run",),
            "report": ("--part-dir", "--run", "--unit", "--line", "--plane"), "review": ("--part-dir", "--run", "--from", "--to"), "findings": ("--run",)}[step]
    if parsed is None or parsed[1] or any(k not in parsed[0] for k in need) \
            or (step == "findings" and (("--report" in parsed[0]) == ("--verdicts" in parsed[0]))) \
            or ("--run" in parsed[0] and not _RUN_NAME.match(parsed[0]["--run"])) \
            or ("--findings" in parsed[0] and not _ids(parsed[0]["--findings"])) \
            or (step == "report" and (not base.NAME.match(parsed[0]["--unit"]) or parsed[0]["--plane"] not in ("session", "factory"))):
        sys.stderr.write(USAGES[step])
        return 2
    got = parsed[0]
    run, part = got.get("--run"), got.get("--part-dir")
    findings = _ids(got["--findings"]) if "--findings" in got else []

    def say(line):
        sys.stderr.write("fwx %s: %s\n" % (routes.shown("wave", [step]), line))
    try:
        top = base.toplevel(os.getcwd())
        if top is None:
            raise base.WaveError("not inside a git repository: %s" % os.getcwd())
        if step == "integrate":
            branches = got.get("--branches", [])
            args = {"part_dir": part, "run": run, "branches": branches, "findings": findings, "final": "--final" in got}
            code, result = integrate.integrate(".", part, run, branches, findings, "--final" in got, say)
        elif step == "fix-round":
            args = {"part_dir": part, "why": got["--why"]}
            code, result = integrate.fix_round(".", part, got["--why"])
            sys.stderr.write("rounds %s\n" % result["rounds"])
        elif step == "revert":
            args = {"part_dir": part, "run": run, "findings": findings}
            code, result = integrate.revert(".", part, findings, say)
        elif step == "report":
            args = {"part_dir": part, "run": run, "unit": got["--unit"], "line": got["--line"], "plane": got["--plane"]}
            code, result = report.judge(".", part, run, got["--unit"], got["--line"], got["--plane"], _steps(top, run))
        elif step == "review":
            args = {"part_dir": part, "run": run, "from": got["--from"], "to": got["--to"], "security": "--security" in got}
            code, result = review.review(".", part, run, got["--from"], got["--to"], "--security" in got, _steps(top, run))
        elif step == "findings":
            part = _part_of(top, run)
            if part is None:
                raise base.WaveError("no call of run %s names a part: `fwx wave review` comes first" % run)
            args = {"part_dir": part, "run": run, "report": got.get("--report"), "verdicts": got.get("--verdicts"), "control_findings": got.get("--control-findings")}
            code, result = review.findings(".", part, run, got.get("--report"), got.get("--verdicts"), got.get("--control-findings"), _steps(top, run))
        elif step == "cleanup":
            args = {"run": run}
            result = cleanup.cleanup(".", run, *cleanup.recorded_of(base.out(top, "rev-parse", "--path-format=absolute", "--git-common-dir"), run))
            code = 0
        else:
            part = part or _part_of(top, run)
            args = {"run": run, "part_dir": part}
            code, result = integrate.summary(".", part, run, _steps(top, run))
            if part is None:
                say("no --part-dir and no call of run %s names one: gate none" % run)
        if run:
            _record(top, run, step, args, result, code)
    except cleanup.NoProc as e:
        sys.stderr.write("%s\n" % e)
        return 77
    except (base.WaveError, config.ConfigError, state.StateError) as e:
        sys.stderr.write("fwx %s: %s\n" % (routes.shown("wave", [step]), e))
        return 2
    print(json.dumps(result))
    return code


def main(argv):
    if argv and argv[0] == "prepare":
        return do_prepare(argv[1:])
    if argv and argv[0] == "run":
        return do_run(argv[1:])
    if argv and argv[0] == "list":
        return do_list(argv[1:])
    if argv and argv[0] == "check-base":
        return do_check_base(argv[1:])
    if argv and argv[0] == "scratch":
        return do_scratch(argv[1:])
    if argv and argv[0] == "setup":
        return do_setup(argv[1:])
    if argv and argv[0] in USAGES:
        return do_step(argv[0], argv[1:])
    sys.stderr.write("usage: fwx wave [new|run|list|merge|fix|revert|remove|setup] ...   (fwx base and fwx scratch new are their own commands)\n")
    return 2
