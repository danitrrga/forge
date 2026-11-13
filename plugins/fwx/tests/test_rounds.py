#!/usr/bin/env python3
"""core.rounds and `fwx rounds`: the per-job round counter, read from the job folder's audit rows.

A round is a distinct SHA with a red `evidence` row, or a `round` row whose detail starts with the word `use`, since the
last `round` row whose detail starts with `reset`. A green SHA does not count; a `round` row with any other detail does
not count. The cap is the configuration's `rounds` (default 3), never a constant in the code. Rows are written with
state.append_audit and read back by the command through state.read_rows; the wiring goes through `bin/fwx rounds` on a
toy repo.

Seen red before the code existed (lib/fwx/core/rounds.py absent; the test stops at the import):
  FAIL: cannot import fwx.core.rounds: cannot import name 'rounds' from 'fwx.core' (.../lib/fwx/core/__init__.py)

Controls, each seen red on a copy of the repo with one thing changed (first FAIL lines shown; 48 checks on the good code):
  - the count is red rows, not distinct SHAs:
      FAIL: the same red sha twice counts once: got 2, want 1
  - the `use` rows are ignored:
      FAIL: two red shas and one use row: got 2, want 3
      FAIL: two red shas and one use row: rounds 3/3, exit 1: got (0, 'rounds 2/3'), want (1, 'rounds 3/3')
  - a green row counts as a round:
      FAIL: a green sha does not count: got 1, want 0
      FAIL: a green sha with a use row counts 1, not 2: got 2, want 1
  - a reset does not stop the count:
      FAIL: after a reset: got 2, want 0
  - the cap is 3 whatever the configuration says:
      FAIL: cap 2 from .claude/fwx.json: got (0, 'rounds 1/3'), want (0, 'rounds 1/2')
  - every round row counts as a use (the detail's first word is not checked):
      FAIL: a round row that is neither use nor reset does not count: got 4, want 0
  - exhausted exits 0:
      FAIL: three red shas: exit 1 and the count: got (0, 'rounds 3/3'), want (1, 'rounds 3/3')
  - a folder with no audit file is read as zero rounds:
      FAIL: a folder with no audit file: exit 2: got 0, want 2
  - --use and --reset both accepted:
      FAIL: --use and --reset together: exit 2: got 0, want 2
  - a blank motive accepted (both checks, in the command and in core.rounds.record):
      FAIL: --use with a blank motive: exit 2: got 0, want 2
  - `--use` takes the next flag as its motive:
      FAIL: --use swallowing the next flag as its motive: exit 2: got 0, want 2
  - the command names the audit file in its own source:
      FAIL: outside state.py, lib/ never names the audit file: got ['lib/fwx/commands/rounds.py'], want []
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx import state  # noqa: E402
    from fwx.core import rounds  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.core.rounds: %s" % e)
    sys.exit(1)

repo = helpers.toy_repo()
helpers.write(repo, ".claude/fwx.json", json.dumps({"schema": 1}))
_n = [0]


def job():
    """A new job folder with no rows."""
    _n[0] += 1
    d = os.path.join(repo, ".fwx", "factory", "KEY-%d" % _n[0])
    os.makedirs(d)
    return d


def red(d, sha, rc="1"):
    state.append_audit(d, "evidence", sha=sha, rc=rc, detail="{}")


def green(d, sha):
    red(d, sha, rc="0")


def use(d, why="merge conflict"):
    state.append_audit(d, "round", detail="use " + why)


def reset(d, why="owner fix"):
    state.append_audit(d, "round", detail="reset " + why)


def run(d, *args):
    r = helpers.fwx(repo, "rounds", d, *args)
    return r.returncode, r.stdout.strip(), r.stderr


def count(d):
    return rounds.count(state.read_rows(state.phase_paths(d)["audit"]))


# ---- the counting rule ---------------------------------------------------------------------------------------------

d = job()
red(d, "a" * 40); red(d, "b" * 40); red(d, "c" * 40)
s.eq("three red shas count 3", count(d), 3)
s.eq("three red shas: exit 1 and the count", run(d)[:2], (1, "rounds 3/3"))

d = job()
red(d, "a" * 40); red(d, "a" * 40)
s.eq("the same red sha twice counts once", count(d), 1)
s.eq("the same red sha twice: exit 0", run(d)[:2], (0, "rounds 1/3"))

d = job()
green(d, "a" * 40)
s.eq("a green sha does not count", count(d), 0)
s.eq("a green sha: exit 0", run(d)[:2], (0, "rounds 0/3"))

d = job()
red(d, "a" * 40); red(d, "b" * 40); reset(d)
s.eq("after a reset", count(d), 0)
s.eq("after --reset's row: rounds 0/3", run(d)[:2], (0, "rounds 0/3"))
red(d, "a" * 40)
s.eq("a sha that was red before the reset counts again after it", count(d), 1)

d = job()
red(d, "a" * 40); red(d, "b" * 40); use(d)
s.eq("two red shas and one use row", count(d), 3)
s.eq("two red shas and one use row: rounds 3/3, exit 1", run(d)[:2], (1, "rounds 3/3"))

d = job()
use(d)
s.eq("a use row with no evidence row counts 1", count(d), 1)

d = job()
green(d, "a" * 40); use(d)
s.eq("a green sha with a use row counts 1, not 2", count(d), 1)

d = job()
red(d, "a" * 40); use(d); use(d, "walk fix"); reset(d)
s.eq("a reset after use rows leaves 0", count(d), 0)
use(d)
s.eq("a use row after the reset counts", count(d), 1)

d = job()
state.append_audit(d, "round", detail="note something")
state.append_audit(d, "round", detail="user fix")
state.append_audit(d, "round", detail="")
state.append_audit(d, "round", detail="resetting nothing")
s.eq("a round row that is neither use nor reset does not count", count(d), 0)

d = job()
state.append_audit(d, "stage", detail="intake")
red(d, "a" * 40, rc="2")
s.eq("a stage row does not count and any non-zero rc is red", count(d), 1)

# ---- the cap comes from the configuration --------------------------------------------------------------------------

helpers.write(repo, ".claude/fwx.json", json.dumps({"schema": 1, "rounds": 2}))
d = job()
red(d, "a" * 40)
s.eq("cap 2 from .claude/fwx.json", run(d)[:2], (0, "rounds 1/2"))
red(d, "b" * 40)
s.eq("cap 2 is exhausted at 2", run(d)[:2], (1, "rounds 2/2"))
helpers.write(repo, ".claude/fwx.json", json.dumps({"schema": 1, "rounds": 0}))
code, out, err = run(d)
s.eq("a cap that is not a positive integer: exit 2", code, 2)
s.ok("a bad cap: the message names the key", "rounds" in err, err)
helpers.write(repo, ".claude/fwx.json", json.dumps({"schema": 1}))

# ---- fwx rounds --use and --reset ----------------------------------------------------------------------------------

d = job()
red(d, "a" * 40); red(d, "b" * 40)
code, out, err = run(d, "--use", "merge conflict")
s.eq("--use as the third round: rounds 3/3, exit 1", (code, out), (1, "rounds 3/3"))
rows = state.read_rows(state.phase_paths(d)["audit"])
s.eq("--use writes one round row with the motive", [(x["kind"], x["detail"]) for x in rows[-1:]],
     [("round", "use merge conflict")])
s.eq("--use adds exactly one row", len(rows), 3)
code, out, err = run(d, "--reset", "owner fixed it")
s.eq("--reset: rounds 0/3, exit 0", (code, out), (0, "rounds 0/3"))
rows = state.read_rows(state.phase_paths(d)["audit"])
s.eq("--reset writes one round row with the motive", [(x["kind"], x["detail"]) for x in rows[-1:]],
     [("round", "reset owner fixed it")])
s.eq("--reset adds exactly one row", len(rows), 4)
s.eq("plain read after the reset", run(d)[:2], (0, "rounds 0/3"))
s.eq("a plain read writes nothing", len(state.read_rows(state.phase_paths(d)["audit"])), 4)

d = job()
before = os.listdir(d)
s.eq("--use and --reset together: exit 2", run(d, "--use", "x", "--reset", "y")[0], 2)
s.eq("--reset with no motive: exit 2", run(d, "--reset")[0], 2)
s.eq("--use with no motive: exit 2", run(d, "--use")[0], 2)
s.eq("--use with a blank motive: exit 2", run(d, "--use", "  ")[0], 2)
s.eq("--reset with an empty motive: exit 2", run(d, "--reset", "")[0], 2)
s.eq("an unknown flag: exit 2", run(d, "--bogus")[0], 2)
s.eq("--use swallowing the next flag as its motive: exit 2", run(d, "--use", "--reset")[0], 2)
s.eq("a refused option writes nothing", os.listdir(d), before)
s.eq("no folder at all: exit 2", helpers.fwx(repo, "rounds").returncode, 2)
s.eq("a folder that is not there: exit 2", run(os.path.join(repo, "nowhere"))[0], 2)
s.eq("--use in a folder that is not there: exit 2", run(os.path.join(repo, "nowhere"), "--use", "x")[0], 2)
s.ok("--use in a folder that is not there makes none", not os.path.exists(os.path.join(repo, "nowhere")))
s.eq("a folder with no audit file: exit 2", run(d)[0], 2)
s.ok("a folder with no audit file: the message says so", "no audit rows" in run(d)[2], run(d)[2])
s.ok("a read makes no audit file", not os.path.exists(state.phase_paths(d)["audit"]))
s.eq("--use in a folder with no rows yet counts 1", run(d, "--use", "first")[:2], (0, "rounds 1/3"))

r = helpers.fwx(repo, "help")
s.ok("`fwx help` lists rounds", any(line.split()[:2] == ["fwx", "rounds"] for line in r.stdout.splitlines()), r.stdout)

# ---- no one else writes or names the audit file --------------------------------------------------------------------

needle = "audit" + ".tsv"
hits, scanned = [], 0
for dirpath, _, files in os.walk(os.path.join(ROOT, "lib")):
    for f in files:
        p = os.path.join(dirpath, f)
        if f.endswith(".py") and os.path.relpath(p, os.path.join(ROOT, "lib")) != os.path.join("fwx", "state.py"):
            scanned += 1
            with open(p, encoding="utf-8") as fh:
                if needle in fh.read():
                    hits.append(os.path.relpath(p, ROOT))
s.ok("the scan looked at the python files of lib/", scanned > 5, "scanned %d" % scanned)
s.eq("outside state.py, lib/ never names the audit file", hits, [])

s.done()
