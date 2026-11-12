"""Prepare a part for `execute`, check an executor's base, and join, fix, undo and clean up its waves:
fwx wave prepare|check-base|integrate|fix-round|revert|cleanup|summary ...

`prepare --part-dir D --plane session|factory --branch W [--unattended] [--security] [--fix F] [--revert IDS]
[--control-findings F] [--from gate]` validates the part `D` from the integration checkout (the current folder, on branch `W`) and prints
the `args` of `execute` as one JSON object (execute/prepare.py says what it checks and what it leaves out). Exit 0, 1 when
the base fails its own checks (a needs-owner JSON line on stdout, `rounds <used>/<cap>` on stderr, no round spent), 2 for
anything that must stop the run before it starts, with the reason on stderr and nothing written. `--from gate` is the way back
into the checks once every task is on the phase branch (the tree's n_C7F loops to n_C7): execute/prepare.py says what it changes.

`check-base <sha> [--worktree P]` is step 0 of every agent that writes: exit 0 when the current folder is a linked worktree
(the one at `P`, when given) whose HEAD is `<sha>`, 42 when it is not (`wrong base: HEAD <x>, expected <sha>` or `not a linked
worktree: <path>` on stderr), 2 for a usage error. `<sha>` is 7 to 40 hex digits. With the base right it then runs the project's
`worktree_setup` (below), so that the agent's own checks find the dependencies: exit 43 when that fails, with `worktree setup
failed: <command> (exit N, log PATH)` on stderr, which is the reason the agent reports, and in `.fwx-agent/worktree-setup-failed.json`
of the worktree, which the workflow reads to end the job; nothing configured prints nothing. It reads
that one field of the configuration (`config.setup_commands`) and no other value: a project that never set it behaves as before,
and a configuration file that cannot be read is 43 too, naming the file (it cannot say whether a setup is owed).

`setup [--force]` runs `project.worktree_setup` in the current linked worktree (execute/worktree_setup.py says how, and what it
refuses): exit 0 with a line on stdout saying how many commands ran, that it was already done, or that none is configured; 1 when a
command failed, ran past its limit or left files git does not ignore (the reason on stderr); 2 in the main checkout, outside a
repository, for a configuration it cannot read and for a usage error. `prepare` calls it in the phase worktree before the base runs,
and `integrate` after the merges and before its checks, and `revert` after the reverts (a merged or reverted lockfile needs the
dependencies again; a failure is exit 1 and `setup` in the JSON).

`scratch <run> <unit>` makes the folder an agent writes its report and its TMPDIR in, inside its own worktree and ignored by git, and
prints its path (execute/base.py says why it is not under `.git`): exit 0, 2 for a usage error or outside a repository.

The rest is 3.4 U3 (execute/integrate.py and execute/cleanup.py say what each does); each prints its result as one JSON
object on stdout and also writes it, with the exit code and its arguments, to `<git-common-dir>/fwx/runs/<run>/<n>-<step>.json`
(`n` counts the run's files; `prepare` and `check-base` write none, and neither does a call that stops on a usage error or on
something that must stop it before it starts, exit 2 with a reason on stderr):
  integrate --part-dir D --run R (--branches B... | --final) [--findings IDS] [--final]
      with no branch (only with --final) nothing is merged and the gate runs on the head as it is;
      exit 0 merged and green, 1 a conflict or a red check, 2 refused (a live agent holds a branch, the commits are not one per
      finding, the checkout is dirty, a usage error), 77 NOT RUN, NOT ARMED: no /proc (a lock cannot be read)
  fix-round --part-dir D --why TEXT [--run R]     (a file in the run only with --run; the factory's job has none)
      exit 0 the failure may be fixed (a round spent, or the evidence already counted), 1 the
      rounds are spent and nothing was spent now, 2 usage
  revert --part-dir D --run R --findings IDS     exit 0, 1 a revert conflicted (aborted), 2 an id with no single commit
  cleanup --run R     exit 0; 77 without /proc. It reads the branches `integrate` named from the run's files
  summary --run R [--part-dir D]     exit 0 gate pass, 1 fail, 2 none; the part comes from the run's files unless given. A run
      that merged branches passes only when its own last `integrate --final` was green (`why` says when it was not): the evidence
      row is the part's, so another run's green gate on the same head is not this run's
"""
import json
import os
import re
import sys

from fwx import config, plan_step, state
from fwx.execute import base, cleanup, integrate, prepare as prep, worktree_setup

PREPARE_USAGE = ("usage: fwx wave prepare --part-dir D --plane session|factory --branch W [--unattended] [--security] "
                 "[--fix F] [--revert IDS] [--control-findings F] [--from gate]\n")
CHECK_USAGE = "usage: fwx wave check-base <sha> [--worktree P]   (sha: 7 to 40 hex digits)\n"
SETUP_USAGE = "usage: fwx wave setup [--force]\n"
SCRATCH_USAGE = "usage: fwx wave scratch <run> <unit>   (each one folder name: letters, digits, `.`, `_`, `-`)\n"
USAGES = {
    "integrate": "usage: fwx wave integrate --part-dir D --run R (--branches B... | --final) [--findings IDS] [--final]\n",
    "fix-round": "usage: fwx wave fix-round --part-dir D --why TEXT [--run R]\n",
    "revert": "usage: fwx wave revert --part-dir D --run R --findings IDS\n",
    "cleanup": "usage: fwx wave cleanup --run R\n",
    "summary": "usage: fwx wave summary --run R [--part-dir D]\n",
}
_RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


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


def do_prepare(argv):
    parsed = _parse(argv, ("--unattended", "--security"), ("--part-dir", "--plane", "--branch", "--fix", "--revert", "--control-findings", "--from"))
    if parsed is None or parsed[1] or any(k not in parsed[0] for k in ("--part-dir", "--plane", "--branch")):
        sys.stderr.write(PREPARE_USAGE)
        return 2
    got = parsed[0]
    revert = [i.strip() for i in got["--revert"].split(",") if i.strip()] if "--revert" in got else None

    def say(line):
        sys.stderr.write("fwx wave prepare: %s\n" % line)
    try:
        args = prep.prepare(".", got["--part-dir"], got["--plane"], got["--branch"], "--unattended" in got, "--security" in got,
                            got.get("--fix"), revert, got.get("--control-findings"), got.get("--from"), say=say)
    except prep.RedBase as e:
        print(json.dumps(e.status))
        sys.stderr.write("fwx wave prepare: %s\n%s\nrounds %s\n" % (e, e.shown, e.status["rounds"]))
        return 1
    except (base.WaveError, config.ConfigError, state.StateError, plan_step.CannotRun) as e:
        sys.stderr.write("fwx wave prepare: %s\n" % e)
        return 2
    print(json.dumps(args))
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
        sys.stderr.write("fwx wave check-base: %s\n" % why)
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
        sys.stderr.write("fwx wave scratch: %s\n" % e)
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


def _recorded_branches(top, run):
    found = set()
    for rec in _steps(top, run):
        if rec.get("step") == "integrate":
            found.update(rec.get("args", {}).get("branches") or [])
    return found


def do_step(step, argv):
    """integrate, fix-round, revert, cleanup and summary: parse, run, print the JSON, record it."""
    flags = ("--final",) if step == "integrate" else ()
    valued = {"integrate": ("--part-dir", "--run", "--findings"), "fix-round": ("--part-dir", "--why", "--run"),
              "revert": ("--part-dir", "--run", "--findings"), "cleanup": ("--run",), "summary": ("--run", "--part-dir")}[step]
    parsed = _parse(argv, flags, valued, many=("--branches",) if step == "integrate" else ())
    need = {"integrate": ("--part-dir", "--run") + (() if parsed and "--final" in parsed[0] else ("--branches",)), "fix-round": ("--part-dir", "--why"),
            "revert": ("--part-dir", "--run", "--findings"), "cleanup": ("--run",), "summary": ("--run",)}[step]
    if parsed is None or parsed[1] or any(k not in parsed[0] for k in need) \
            or ("--run" in parsed[0] and not _RUN_NAME.match(parsed[0]["--run"])) \
            or ("--findings" in parsed[0] and not _ids(parsed[0]["--findings"])):
        sys.stderr.write(USAGES[step])
        return 2
    got = parsed[0]
    run, part = got.get("--run"), got.get("--part-dir")
    findings = _ids(got["--findings"]) if "--findings" in got else []

    def say(line):
        sys.stderr.write("fwx wave %s: %s\n" % (step, line))
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
        elif step == "cleanup":
            args = {"run": run}
            result = cleanup.cleanup(".", run, _recorded_branches(top, run))
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
        sys.stderr.write("fwx wave %s: %s\n" % (step, e))
        return 2
    print(json.dumps(result))
    return code


def main(argv):
    if argv and argv[0] == "prepare":
        return do_prepare(argv[1:])
    if argv and argv[0] == "check-base":
        return do_check_base(argv[1:])
    if argv and argv[0] == "scratch":
        return do_scratch(argv[1:])
    if argv and argv[0] == "setup":
        return do_setup(argv[1:])
    if argv and argv[0] in USAGES:
        return do_step(argv[0], argv[1:])
    sys.stderr.write("usage: fwx wave <prepare|check-base|scratch|setup|%s> ...\n" % "|".join(USAGES))
    return 2
