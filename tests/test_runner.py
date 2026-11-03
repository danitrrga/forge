"""`fwx test`: one line per tests/test_*.py, a summary, and an exit code that says what happened.

Runs bin/fwx in toy repos holding tests/test_ok.py (exit 0), test_bad.py (exit 1), test_skip.py (exit 77
with its NOT RUN line) and test_new.py (exit 0, never added to git).

Controls seen red, each on a copy of lib/fwx/commands/test.py changed in one place (20 checks each):
  - a runner that ignores the exit code (every file counts as passed):
      FAIL: all four: exit code: got 0, want 1
      FAIL: all four: summary: got '4 test file(s): 4 passed, 0 failed, 0 not run', want '4 test file(s): 2 passed, 1 failed, 1 not run'
      FAIL: all four: test_bad FAIL: PASS  tests/test_bad.py
  - a runner that exits 0 with no test file:
      FAIL: no test file: exit code: got 0, want 1
  - a runner that counts exit 77 as green (test_skip present, no test_bad):
      FAIL: ok + skip: exit code: got 0, want 77
  - a runner that treats 77 as an ordinary failure:
      FAIL: ok + skip: summary: got '3 test file(s): 2 passed, 1 failed, 0 not run', want '3 test file(s): 2 passed, 0 failed, 1 not run'
  - a runner that lists with `--cached` alone (the untracked test_new is missed):
      FAIL: all four: summary: got '3 test file(s): 1 passed, 1 failed, 1 not run', want '4 test file(s): 2 passed, 1 failed, 1 not run'
  - a runner that hands its own environment, GIT_* included, to the tests (test_ok checks it):
      FAIL: ok only: summary: got '2 test file(s): 0 passed, 2 failed, 0 not run', want '2 test file(s): 2 passed, 0 failed, 0 not run'
  - a runner whose git listing keeps the caller's GIT_DIR (it lists another repo's index):
      FAIL: GIT_DIR in the caller's environment: summary: got '3 test file(s): 2 passed, 1 failed, 0 not run', want '2 test file(s): 2 passed, 0 failed, 0 not run'
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()
OK = ('import os, sys\n'
      'bad = [k for k in os.environ if k.startswith("GIT_")]\n'
      'if bad or not os.path.isfile("tests/test_ok.py"):\n'
      '    print("test_ok: not run from the repo root, or GIT_* leaked: %s" % bad)\n'
      '    sys.exit(1)\n')
BAD = 'print("FAIL: the broken case")\nraise SystemExit(1)\n'
SKIP = 'print("NOT RUN, NOT ARMED: no such tool")\nraise SystemExit(77)\n'
FILES = {"tests/test_ok.py": OK, "tests/test_bad.py": BAD, "tests/test_skip.py": SKIP}


def case(label, files, want_rc, want_summary, env=None, new=True, lines=()):
    repo = helpers.toy_repo(files)
    if new:
        helpers.write(repo, "tests/test_new.py", OK.replace("test_ok", "test_new"))
    r = helpers.fwx(repo, "test", env=env)
    s.eq("%s: exit code" % label, r.returncode, want_rc)
    out = r.stdout.splitlines()
    s.eq("%s: summary" % label, out[-1] if out else "", want_summary)
    for prefix, name in lines:
        s.ok("%s: %s %s" % (label, name, prefix), any(l.startswith(prefix) and name in l for l in out), r.stdout + r.stderr)
    return r


r = case("all four", FILES, 1, "4 test file(s): 2 passed, 1 failed, 1 not run",
         lines=[("PASS", "test_ok"), ("PASS", "test_new"), ("FAIL", "test_bad"),
                ("NOT RUN, NOT ARMED", "test_skip")])
s.ok("all four: the failing test's own output is shown", "FAIL: the broken case" in r.stdout, r.stdout)
s.ok("all four: the NOT RUN line carries the test's reason", "no such tool" in r.stdout, r.stdout)

case("ok + skip", {k: v for k, v in FILES.items() if k != "tests/test_bad.py"}, 77,
     "3 test file(s): 2 passed, 0 failed, 1 not run", lines=[("NOT RUN, NOT ARMED", "test_skip")])
case("ok only", {"tests/test_ok.py": OK}, 0, "2 test file(s): 2 passed, 0 failed, 0 not run", lines=[("PASS", "test_ok")])
case("no test file", {"README": "toy\n"}, 1, "0 test file(s): 0 passed, 0 failed, 0 not run", new=False)
case("a failure and a skip, no pass", {"tests/test_bad.py": BAD, "tests/test_skip.py": SKIP}, 1,
     "2 test file(s): 0 passed, 1 failed, 1 not run", new=False)

other = helpers.toy_repo({"tests/test_decoy.py": "raise SystemExit(1)\n"})
case("GIT_DIR in the caller's environment", {"tests/test_ok.py": OK}, 0,
     "2 test file(s): 2 passed, 0 failed, 0 not run",
     env={"GIT_DIR": os.path.join(other, ".git"), "GIT_INDEX_FILE": os.path.join(other, ".git", "index")})

s.done()
