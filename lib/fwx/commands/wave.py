"""Prepare a part for `execute` and check an executor's base: fwx wave prepare|check-base ...

`prepare --part-dir D --plane session|factory --branch W [--unattended] [--security] [--fix F] [--revert IDS]
[--control-findings F]` validates the part `D` from the integration checkout (the current folder, on branch `W`) and prints
the `args` of `execute` as one JSON object (execute/prepare.py says what it checks and what it leaves out). Exit 0, 1 when
the base fails its own checks (a needs-owner JSON line on stdout, `rounds <used>/<cap>` on stderr, no round spent), 2 for
anything that must stop the run before it starts, with the reason on stderr and nothing written.

`check-base <sha> [--worktree P]` is step 0 of every agent that writes: exit 0 when the current folder is a linked worktree
(the one at `P`, when given) whose HEAD is `<sha>`, 42 when it is not (`wrong base: HEAD <x>, expected <sha>` or `not a linked
worktree: <path>` on stderr), 2 for a usage error. `<sha>` is 7 to 40 hex digits.

`integrate`, `fix-round`, `revert`, `cleanup` and `summary` are not built yet (3.4 U3): exit 2.
"""
import json
import os
import sys

from fwx import config, plan_step, state
from fwx.execute import base, prepare as prep

PREPARE_USAGE = ("usage: fwx wave prepare --part-dir D --plane session|factory --branch W [--unattended] [--security] "
                 "[--fix F] [--revert IDS] [--control-findings F]\n")
CHECK_USAGE = "usage: fwx wave check-base <sha> [--worktree P]   (sha: 7 to 40 hex digits)\n"
NOT_BUILT = ("integrate", "fix-round", "revert", "cleanup", "summary")


def _parse(argv, flags, valued):
    """({name: value or True}, [positionals]) or None for an option nobody knows or a valued one with no value."""
    got, pos, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
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
    parsed = _parse(argv, ("--unattended", "--security"), ("--part-dir", "--plane", "--branch", "--fix", "--revert", "--control-findings"))
    if parsed is None or parsed[1] or any(k not in parsed[0] for k in ("--part-dir", "--plane", "--branch")):
        sys.stderr.write(PREPARE_USAGE)
        return 2
    got = parsed[0]
    revert = [i.strip() for i in got["--revert"].split(",") if i.strip()] if "--revert" in got else None

    def say(line):
        sys.stderr.write("fwx wave prepare: %s\n" % line)
    try:
        args = prep.prepare(".", got["--part-dir"], got["--plane"], got["--branch"], "--unattended" in got, "--security" in got,
                            got.get("--fix"), revert, got.get("--control-findings"), say=say)
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
    return code


def main(argv):
    if argv and argv[0] == "prepare":
        return do_prepare(argv[1:])
    if argv and argv[0] == "check-base":
        return do_check_base(argv[1:])
    if argv and argv[0] in NOT_BUILT:
        sys.stderr.write("fwx wave %s: not built yet (3.4 U3)\n" % argv[0])
        return 2
    sys.stderr.write("usage: fwx wave <prepare|check-base|%s> ...\n" % "|".join(NOT_BUILT))
    return 2
