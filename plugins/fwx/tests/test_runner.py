"""`fwx test`: one line per tests/test_*.py, a summary, and an exit code that says what happened.

Runs bin/fwx in toy repos holding tests/test_ok.py (exit 0), test_bad.py (exit 1), test_skip.py (exit 77
with its NOT RUN line) and test_new.py (exit 0, never added to git). `--expect-not-run` is checked in the same toy repos.

Seen red before `--expect-not-run` existed (the flag was ignored, so every declared skip still exited 77), 51 checks:
      FAIL: declared skip: exit code: got 77, want 0
      FAIL: a declared path that is no test file is 1: exit code: got 77, want 1
      FAIL: a flag with no value is a usage error: exit code: got 77, want 2
Controls for --expect-not-run, each on a copy of lib/fwx/commands/test.py changed in one place:
  - any 77 counts as expected, declared or not (`and rel in expect` dropped; an undeclared skip must still end 77):
      FAIL: all four: summary: got '4 test file(s): 2 passed, 1 failed, 0 not run, 1 expected not run', want '4 test file(s): 2 passed, 1 failed, 1 not run'
  - a declared test that fails counts as expected (`returncode != 0 and rel in expect`):
      FAIL: a declared test that fails is 1: exit code: got 0, want 1
  - zero passed is allowed when something was declared (`expect and passed == 0` dropped):
      FAIL: only declared skips ran: zero tests ran is 1: exit code: got 0, want 1
  - a declared path that is no test file is ignored (`or unknown` dropped):
      FAIL: a declared path that is no test file is 1: exit code: got 0, want 1
  - the expected ones left out of the total:
      FAIL: declared skip: summary: got '2 test file(s): 2 passed, ...', want '3 test file(s): 2 passed, ...'

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


def case(label, files, want_rc, want_summary, env=None, new=True, lines=(), args=()):
    repo = helpers.toy_repo(files)
    if new:
        helpers.write(repo, "tests/test_new.py", OK.replace("test_ok", "test_new"))
    r = helpers.fwx(repo, "test", *args, env=env)
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

# A folder of a bigger repository (fwx lives in plugins/fwx of forge): the tests are the ones of the folder it is run from,
# not those of the repository's top level. Seen red before `test_files` and the run were rooted at the working folder
# (`git rev-parse --show-toplevel`), on forge's checkout:
#   FAIL: a folder of a bigger repo: exit code: got 1, want 0
#   FAIL: a folder of a bigger repo: summary: got '1 test file(s): 0 passed, 1 failed, 0 not run', want '1 test file(s): 1 passed, 0 failed, 0 not run'
#   FAIL: a folder of a bigger repo: its own test ran, the top level's did not: FAIL  tests/test_decoy.py (exit 1)
parent = helpers.toy_repo({"tests/test_decoy.py": BAD, "sub/tests/test_ok.py": OK})
r = helpers.fwx(os.path.join(parent, "sub"), "test")
s.eq("a folder of a bigger repo: exit code", r.returncode, 0)
out = r.stdout.splitlines()
s.eq("a folder of a bigger repo: summary", out[-1] if out else "", "1 test file(s): 1 passed, 0 failed, 0 not run")
s.ok("a folder of a bigger repo: its own test ran, the top level's did not",
     "PASS  tests/test_ok.py" in r.stdout and "test_decoy" not in r.stdout, r.stdout + r.stderr)

# --expect-not-run: a test the caller declares cannot run here (CI has no key, no private tree).
NO_BAD = {k: v for k, v in FILES.items() if k != "tests/test_bad.py"}
r = case("declared skip", NO_BAD, 0, "3 test file(s): 2 passed, 0 failed, 0 not run, 1 expected not run",
         args=("--expect-not-run", "tests/test_skip.py"), lines=[("EXPECTED NOT RUN", "test_skip")])
s.ok("declared skip: the expected line carries the test's reason", "no such tool" in r.stdout, r.stdout)
s.ok("declared skip: no line starts with the unexpected `NOT RUN, NOT ARMED`",
     not any(l.startswith("NOT RUN, NOT ARMED") for l in r.stdout.splitlines()), r.stdout)
case("declared skip, comma list", {**NO_BAD, "tests/test_skip2.py": SKIP}, 0,
     "4 test file(s): 2 passed, 0 failed, 0 not run, 2 expected not run",
     args=("--expect-not-run", "tests/test_skip.py,tests/test_skip2.py"))
case("declared skip, flag given twice", {**NO_BAD, "tests/test_skip2.py": SKIP}, 0,
     "4 test file(s): 2 passed, 0 failed, 0 not run, 2 expected not run",
     args=("--expect-not-run", "tests/test_skip.py", "--expect-not-run", "tests/test_skip2.py"))
case("declared skip, = form", NO_BAD, 0, "3 test file(s): 2 passed, 0 failed, 0 not run, 1 expected not run",
     args=("--expect-not-run=tests/test_skip.py",))
# negative controls: the declaration must not widen what counts as green
case("an undeclared skip still exits 77", {**NO_BAD, "tests/test_skip2.py": SKIP}, 77,
     "4 test file(s): 2 passed, 0 failed, 1 not run, 1 expected not run",
     args=("--expect-not-run", "tests/test_skip.py"), lines=[("NOT RUN, NOT ARMED", "test_skip2"),
                                                           ("EXPECTED NOT RUN", "test_skip.py")])
case("a declared test that runs and passes is fine", NO_BAD, 77,
     "3 test file(s): 2 passed, 0 failed, 1 not run", args=("--expect-not-run", "tests/test_ok.py"))
case("a declared test that fails is 1", FILES, 1, "4 test file(s): 2 passed, 1 failed, 0 not run, 1 expected not run",
     args=("--expect-not-run", "tests/test_bad.py,tests/test_skip.py"), lines=[("FAIL", "test_bad"),
                                                                              ("EXPECTED NOT RUN", "test_skip")])
case("only declared skips ran: zero tests ran is 1", {"tests/test_skip.py": SKIP}, 1,
     "1 test file(s): 0 passed, 0 failed, 0 not run, 1 expected not run",
     args=("--expect-not-run", "tests/test_skip.py"), new=False)
r = case("a declared path that is no test file is 1", NO_BAD, 1, "3 test file(s): 2 passed, 0 failed, 0 not run, 1 expected not run",
         args=("--expect-not-run", "tests/test_skip.py,tests/test_typo.py"))
s.ok("a declared path that is no test file: named on stderr", "tests/test_typo.py" in r.stderr, r.stderr)
r = case("a flag with no value is a usage error", NO_BAD, 2, "", args=("--expect-not-run",))
s.ok("a flag with no value: usage on stderr", "usage: fwx test" in r.stderr, r.stderr)
r = case("an unknown flag is a usage error", NO_BAD, 2, "", args=("--nope",))

s.done()
