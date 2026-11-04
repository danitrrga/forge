"""Check the plan files of a phase: fwx plan check <dir> [--json].

`check` reads `<dir>/plan.md`, the `plan.md` of each subphase and the frontmatter of `premortem.md` and `postmortem.md`
(plan.py says what is an error and what a warning), prints each problem on a line and always the count line
`checked <n> plan file(s): <t> tasks, <w> waves, <p> parts; <e> errors, <k> warnings`. Exit 0 with no error (warnings are
printed), 1 with errors (a plan with no task is one), 2 when it cannot run: a usage error or `<dir>` not a folder. With
`--json` the output is one JSON object: check_phase's result and the count line as `summary`.
"""
import json
import sys

from fwx import plan

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


SUBCOMMANDS = {"check": check}


def main(argv):
    if not argv or argv[0] not in SUBCOMMANDS:
        sys.stderr.write("usage: fwx plan <%s> ...\n" % "|".join(SUBCOMMANDS))
        return 2
    return SUBCOMMANDS[argv[0]](argv[1:])
