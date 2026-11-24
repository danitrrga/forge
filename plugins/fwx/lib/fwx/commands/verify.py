"""Run the project's checks on a clean tree at the exact commit and record the evidence: fwx verify [--json] [--pr N] [--dir PATH].

The checks are the recipe of `project.checks` in `.claude/fwx.json`, or the package.json scripts test, lint, typecheck and build
(core.verify says how a run goes). Progress and the tail of every red check go to stderr; stdout gets the line
`evidence <sha> <cmd>=<rc> ...` for the phase report, or with `--json` the evidence as JSON, `{sha, clean, source, commands,
rc}`, the shape of `facts.evidence`. The row is written to `--dir` (the factory passes the job's folder) or to the session's
phase. `--pr N` creates or edits in place the PR's comment marked `<!-- fwx:evidence -->`; if `gh` fails the row stays written
and the exit is 2 with gh's error. Exit 0 green, 1 a check is red, 2 it could not prove the commit (dirty tree, no checks,
HEAD moved, no git repository, a bad option, or gh failed).
"""
import json
import sys

from fwx import config, state
from fwx.core import gh, verify

USAGE = "usage: fwx verify [--json] [--pr N] [--dir PATH]\n"


def _say(line):
    sys.stderr.write(line + "\n" if line.startswith("\n") else "fwx verify: %s\n" % line)


def _parse(argv):
    """`(as_json, pr, dir)`, or an error message."""
    as_json, pr, dir_, args = False, None, None, list(argv)
    while args:
        a = args.pop(0)
        if a == "--json":
            as_json = True
        elif a in ("--pr", "--dir"):
            if not args or args[0].startswith("-"):
                return "%s needs a value" % a
            v = args.pop(0)
            if a == "--dir":
                dir_ = v
            elif not v.isdigit() or int(v) < 1:
                return "--pr takes a PR number, got %r" % v
            else:
                pr = int(v)
        else:
            return "unknown argument %r" % a
    return as_json, pr, dir_


def main(argv):
    parsed = _parse(argv)
    if isinstance(parsed, str):
        sys.stderr.write("fwx verify: %s\n%s" % (parsed, USAGE))
        return 2
    as_json, pr, dir_ = parsed
    try:
        code, ev = verify.verify(".", dir_, _say)
    except (state.StateError, config.ConfigError) as e:
        sys.stderr.write("fwx verify: %s\n" % e)
        return 2
    if ev is None:
        return code
    line = verify.evidence_line(ev["sha"], ev["commands"])
    if as_json:
        print(json.dumps(ev))
        sys.stderr.write(line + "\n")
    else:
        print(line)
    if pr is not None:
        try:
            done = gh.upsert_comment(pr, verify.COMMENT_MARKER, verify.comment_body(ev["sha"], ev["commands"]),
                                     cwd=verify.toplevel("."))
        except (gh.GhError, state.StateError) as e:
            sys.stderr.write("fwx verify: the evidence row is written, but the comment on PR %d is not: %s\n" % (pr, e))
            return 2
        _say("comment on PR %d %s" % (pr, done))
    return code
