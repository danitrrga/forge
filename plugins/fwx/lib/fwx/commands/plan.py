"""Check, brief and judge the plan files of a phase: fwx plan check|brief|status <dir> ...

`brief` and `status` are the plan block's steps (plan_step.py), after the text on `check`.

`check` reads `<dir>/plan.md`, the `plan.md` of each subphase and the frontmatter of `premortem.md` and `postmortem.md`
(plan.py says what is an error and what a warning), prints each problem on a line and always the count line
`checked <n> plan file(s): <t> tasks, <w> waves, <p> parts; <e> errors, <k> warnings`. Exit 0 with no error (warnings are
printed), 1 with errors (a plan with no task is one), 2 when it cannot run: a usage error or `<dir>` not a folder. With
`--json` the output is one JSON object: check_phase's result and the count line as `summary`.

`brief <dir> <step> [--unattended] [--diff BASE..BRANCH] [--head]` (step: premortem, plan or postmortem) prints the brief the
agent of that step runs as its first action; with `--head` only `{agent, model, round}` as one JSON line, which is what the
step's skill reads so the brief never passes through the orchestrator. Exit 0, 1 when what the step needs is missing (the
reason on stderr, nothing on stdout), 2 for a usage error or a folder or configuration that cannot be used.
`status <dir> <step> [--unattended]` prints `{status, reason, phase_dir}` as one JSON line once the step has run: `done`,
`failed`, `back-to-discuss` or `needs-owner`; the first word of `reason` is the verdict. Exit 0, or 2 when it cannot read.
"""
import json
import sys

from fwx import plan, plan_step

USAGE = "usage: fwx plan check <dir> [--json]\n"


def check(argv):
    args = [a for a in argv if a != "--json"]
    if len(args) != 1 or args[0].startswith("-") or any(a.startswith("-") and a != "--json" for a in argv):
        sys.stderr.write(USAGE)
        return 2
    try:
        r = plan.check_phase(args[0])
    except plan.PlanError as e:
        sys.stderr.write("fwx plan: %s\n" % e)
        return 2
    summary = "checked %d plan file(s): %d tasks, %d waves, %d parts; %d errors, %d warnings" % (
        r["plans"], r["tasks"], r["waves"], r["parts"], len(r["errors"]), len(r["warnings"]))
    if "--json" in argv:
        print(json.dumps(dict(r, summary=summary), indent=2))
    else:
        for e in r["errors"]:
            print("error: " + e)
        for w in r["warnings"]:
            print("warning: " + w)
        print(summary)
    return 1 if r["errors"] else 0


BRIEF_USAGE = "usage: fwx plan brief <dir> <premortem|plan|postmortem> [--unattended] [--diff BASE..BRANCH] [--head]\n"
STATUS_USAGE = "usage: fwx plan status <dir> <premortem|plan|postmortem> [--unattended]\n"


def _parse(argv, usage, flags, valued=()):
    """(positionals, {flag: value or True}) or None after printing the usage."""
    pos, got, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a in valued:
            if i + 1 >= len(argv):
                break
            got[a] = argv[i + 1]
            i += 2
            continue
        if a in flags:
            got[a] = True
        elif a.startswith("-"):
            break
        else:
            pos.append(a)
        i += 1
    else:
        if len(pos) == 2:
            return pos, got
    sys.stderr.write(usage)
    return None


def _run(call):
    try:
        return call()
    except plan_step.Missing as e:
        sys.stderr.write("fwx plan: %s\n" % e)
        return 1
    except plan_step.CannotRun as e:
        sys.stderr.write("fwx plan: %s\n" % e)
        return 2


def brief(argv):
    parsed = _parse(argv, BRIEF_USAGE, ("--unattended", "--head"), ("--diff",))
    if parsed is None:
        return 2
    (folder, step), got = parsed

    def go():
        if "--head" in got:
            print(json.dumps(plan_step.head(folder, step)))
        else:
            sys.stdout.write(plan_step.brief(folder, step, "--unattended" in got, got.get("--diff")))
        return 0
    return _run(go)


def status(argv):
    parsed = _parse(argv, STATUS_USAGE, ("--unattended",))
    if parsed is None:
        return 2
    (folder, step), got = parsed

    def go():
        print(plan_step.status_line(plan_step.status(folder, step, "--unattended" in got)))
        return 0
    return _run(go)


SUBCOMMANDS = {"check": check, "brief": brief, "status": status}


def main(argv):
    if not argv or argv[0] not in SUBCOMMANDS:
        sys.stderr.write("usage: fwx plan <%s> ...\n" % "|".join(SUBCOMMANDS))
        return 2
    return SUBCOMMANDS[argv[0]](argv[1:])
