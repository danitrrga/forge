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
import re
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

check("runner small: the seed gives haiku", main, ["runner", "small"], 0, "haiku\n")
check("runner big: the seed gives haiku", main, ["runner", "big"], 0, "haiku\n")
opus_exec = helpers.toy_repo()
helpers.write(opus_exec, ".claude/fwx.json", '{"schema": 1, "models": {"executor": {"small": "opus"}}}\n')
check("runner small with executor small opus and no runner row: still haiku", opus_exec, ["runner", "small"], 0, "haiku\n")
own = helpers.toy_repo()
helpers.write(own, ".claude/fwx.json", '{"schema": 1, "models": {"runner": {"small": "sonnet"}}}\n')
check("runner small the file sets: that value", own, ["runner", "small"], 0, "sonnet\n")
check("runner normal the file leaves out: the seed", own, ["runner", "normal"], 0, "haiku\n")

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
outside = helpers.mkdtemp_nogit()
r = helpers.fwx(outside, "model", "executor", "small", env={"PYTHONDONTWRITEBYTECODE": "1"})
s.eq("fwx model outside a git repo: exit code", r.returncode, 2)
s.ok("fwx model outside a git repo: no traceback", "Traceback" not in r.stderr, "stderr: %s" % r.stderr)

# the listing says what it does
h = helpers.fwx(main, "help")
s.ok("fwx help lists model", any(line.split()[:2] == ["fwx", "model"] for line in h.stdout.splitlines()), h.stdout)

# style.md: the family table holds every role of config.ROLES once, and the sentence under it counts them right
# (a new role gets a family before it gets a file; the count in the sentence drifted when `runner` was added).
# Seen red on 6047865 (ROLES has 22, the file says 21 and has no `runner` row):
#   FAIL: style.md family table has every role of ROLES exactly once, and the sentence under it says how many:
#         missing ['runner'], repeated or unknown []; says [21], ROLES has 22
sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import config  # noqa: E402


def style_roles(text):
    """The roles named in the family table of style.md (the backticked names in the last column of its rows) and the numbers that
    follow 'all' in the sentence that counts them."""
    rows = [ln for ln in text.splitlines() if ln.startswith("| ") and not ln.startswith(("| Family", "|---"))]
    named = [r for ln in rows for r in re.findall(r"`([a-z-]+)`", ln.split("|")[3])]
    return named, [int(n) for n in re.findall(r"These are all (\d+) roles", text)]


def style_problems(text, roles):
    named, said = style_roles(text)
    out = []
    missing = sorted(set(roles) - set(named))
    repeated = sorted({r for r in named if named.count(r) > 1} | (set(named) - set(roles)))
    if missing or repeated:
        out.append("missing %s, repeated or unknown %s" % (missing, repeated))
    if said != [len(roles)]:
        out.append("says %s, ROLES has %d" % (said, len(roles)))
    return out


with open(os.path.join(helpers.ROOT, "playbooks", "style.md"), encoding="utf-8") as f:
    style = f.read()
probs = style_problems(style, config.ROLES)
s.ok("style.md family table has every role of ROLES exactly once, and the sentence under it says how many", not probs, "; ".join(probs))
ctl = ("| Family | Colour | Roles |\n|---|---|---|\n| a | red | `x`, `y` |\n| b | blue | `y` |\n\nThese are all 3 roles of `ROLES`.\n")
good_ctl = ctl.replace("| b | blue | `y` |\n", "").replace("`x`, `y`", "`x`, `y`, `z`")
s.eq("control: a role missing and one repeated are caught", style_problems(ctl, ("x", "y", "z")), ["missing ['z'], repeated or unknown ['y']"])
s.eq("control: a table that holds every role once with the right count passes", style_problems(good_ctl, ("x", "y", "z")), [])
s.eq("control: a count that does not match is caught", style_problems(good_ctl.replace("all 3", "all 4"), ("x", "y", "z")), ["says [4], ROLES has 3"])

s.done()
