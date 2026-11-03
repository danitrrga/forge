#!/usr/bin/env python3
"""fwx model <role> <size>: the model for a role, from .claude/fwx.json of the main checkout or the seed.

Seen red before commands/model.py existed (23 of 51 checks failed):
  FAIL: fwx model executor small: exit code: got 2, want 0
  FAIL: fwx model executor small: stdout: got '', want 'haiku\\n'
  (bin/fwx printed "fwx: unknown command: model" and exited 2)

Control seen red, on a copy of commands/model.py that lets ConfigError escape (no try/except), 8 failed:
  FAIL: fwx model nosuch small: exit code: got 1, want 2
  FAIL: fwx model executor huge: exit code: got 1, want 2
  FAIL: fwx model with a schema it does not know: exit code: got 1, want 2
  FAIL: fwx model outside a git repo: exit code: got 1, want 2
  and for each of them "no traceback: stderr: Traceback (most recent call last): ...".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()


def run(cwd, *args):
    r = helpers.fwx(cwd, "model", *args, env={"PYTHONDONTWRITEBYTECODE": "1"})
    return r


def check(label, cwd, args, code, out=None, err_has=()):
    r = run(cwd, *args)
    s.eq("fwx model %s: exit code" % label, r.returncode, code)
    if out is not None:
        s.eq("fwx model %s: stdout" % label, r.stdout, out)
    for needle in err_has:
        s.ok("fwx model %s: stderr names %r" % (label, needle), needle in r.stderr, "stderr: %s" % r.stderr)
    s.ok("fwx model %s: no traceback" % label, "Traceback" not in r.stderr, "stderr: %s" % r.stderr)
    return r


main = helpers.toy_repo()
wt = helpers.add_worktree(main, "side")
sub = os.path.join(wt, "src")
os.makedirs(sub)
helpers.write(main, ".claude/fwx.json", '{"schema": 1, "models": {"executor": {"small": "haiku"}}}\n')

check("executor small", main, ["executor", "small"], 0, "haiku\n")
check("executor small from a worktree subfolder", sub, ["executor", "small"], 0, "haiku\n")
check("a size the file lacks gives the seed", main, ["executor", "big"], 0, "sonnet\n")
check("a role the file lacks gives the seed", main, ["planner", "normal"], 0, "opus\n")

check("nosuch small", main, ["nosuch", "small"], 2, "", ("nosuch", "executor", "planner", "vision"))
check("executor huge", main, ["executor", "huge"], 2, "", ("huge", "small", "normal", "big"))
check("without arguments", main, [], 2, "", ("usage",))
check("with one argument", main, ["executor"], 2, "", ("usage",))
check("with three arguments", main, ["executor", "small", "x"], 2, "", ("usage",))

# no file in the main checkout: the seed, and the warning on stderr only
bare = helpers.toy_repo()
r = check("with no file", bare, ["planner", "big"], 0, "opus\n", ("no .claude/fwx.json",))
s.eq("with no file: one stderr line", len(r.stderr.strip().splitlines()), 1)

# a bad file and a folder outside git are refusals too
bad = helpers.toy_repo()
helpers.write(bad, ".claude/fwx.json", '{"schema": 2}\n')
check("with a schema it does not know", bad, ["executor", "small"], 2, "", ("schema", "forge sync"))
outside = helpers.mkdtemp("fwx-nogit-")
r = helpers.fwx(outside, "model", "executor", "small", env={"PYTHONDONTWRITEBYTECODE": "1",
                                                           "GIT_CEILING_DIRECTORIES": outside})
s.eq("fwx model outside a git repo: exit code", r.returncode, 2)
s.ok("fwx model outside a git repo: no traceback", "Traceback" not in r.stderr, "stderr: %s" % r.stderr)

# the listing says what it does
h = helpers.fwx(main, "help")
s.ok("fwx help lists model", any(line.split()[:1] == ["model"] for line in h.stdout.splitlines()), h.stdout)

s.done()
