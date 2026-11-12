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

# --jobs: the files run in parallel, each its own process, and nothing a reader sees depends on how many at once.
# Seen red before --jobs existed (the flag was unknown, exit 2, and the runner went one file after another):
#   FAIL: --jobs 2: two files running at once see each other: exit code: got 2, want 0
#   FAIL: --jobs 1: the files run one after the other (the first cannot see the second): exit code: got 2, want 1
#   FAIL: --jobs 1 and --jobs 4 print the same, set 1: stdout: got '', want what --jobs 1 printed
#   FAIL: a failing file's output is contiguous: x has all its lines: got 0, want 150
#   FAIL: SIGTERM: the runner's children are alive while it runs (the search finds them): got 0, want 4
#   FAIL: --jobs 0 is a usage error: one line on stderr, naming --jobs (the generic usage line names the flag, but --jobs is unknown)
# Controls, each on a copy of lib/fwx/commands/test.py changed in one place (first FAIL of each):
#   one worker (`max_workers=jobs` -> 1):  FAIL: --jobs 2: two files running at once see each other: exit code: got 1, want 0   (6 FAIL lines)
#   printed in start order, not file-name order (`for rel in files:` -> `for rel in start:`):
#       FAIL: --jobs 4, set 1: everything: the lines are in the order of the file names: got ['tests/test_big.py', 'tests/test_zeta.py', ...]   (3)
#   only the leader of a group killed (`os.killpg` -> `os.kill`):  FAIL: SIGTERM: no test file, no sleep it started is left running: got [891171, 891172], want []   (6)
#   no session of its own (`start_new_session=True` dropped):  FAIL: SIGTERM: no test file, no sleep it started is left running: got [920365, 920371, 920367, 920372], want []   (6)
#   no signal handlers (`old = {}`):  FAIL: SIGTERM: the runner exits with 128 + the signal: got -15, want 143, and the four processes left   (5)
#   --jobs 0 accepted (`>= 1` -> `>= 0`):  FAIL: --jobs 0 is a usage error: exit code: got 77, want 2   (8)
#   --jobs given twice accepted:  FAIL: --jobs given twice is a usage error: exit code: got 77, want 2   (4)
import signal
import subprocess
import time

RENDEZVOUS = ('import os, sys, time\n'
              'd, me, other = %(d)r, %(me)r, %(other)r\n'
              'open(os.path.join(d, me), "w").close()\n'
              'end = time.time() + %(wait)s\n'
              'while time.time() < end:\n'
              '    if os.path.exists(os.path.join(d, other)):\n'
              '        sys.exit(0)\n'
              '    time.sleep(0.02)\n'
              'print("FAIL: %%s never saw %%s start" %% (me, other))\n'
              'sys.exit(1)\n')


def pair(wait):
    """Two files that each announce themselves and wait for the other's announcement: both pass only if both are alive at
    the same time, which is the definition of parallel, with no clock to tune. `wait` is how long one waits for the other."""
    d = helpers.mkdtemp("fwx-par-")
    return helpers.toy_repo({"tests/test_a.py": RENDEZVOUS % {"d": d, "me": "a", "other": "b", "wait": wait},
                             "tests/test_b.py": RENDEZVOUS % {"d": d, "me": "b", "other": "a", "wait": wait}})


def last(r):
    out = r.stdout.splitlines()
    return out[-1] if out else ""


r = helpers.fwx(pair(60), "test", "--jobs", "2")
s.eq("--jobs 2: two files running at once see each other: exit code", r.returncode, 0)
s.eq("--jobs 2: summary", last(r), "2 test file(s): 2 passed, 0 failed, 0 not run")
r = helpers.fwx(pair(60), "test", "--jobs=2")
s.eq("--jobs=2 form: exit code", r.returncode, 0)
r = helpers.fwx(pair(1), "test", "--jobs", "1")
s.eq("--jobs 1: the files run one after the other (the first cannot see the second): exit code", r.returncode, 1)
s.eq("--jobs 1: summary", last(r), "2 test file(s): 1 passed, 1 failed, 0 not run")
if (os.cpu_count() or 1) > 1:
    r = helpers.fwx(pair(60), "test")
    s.eq("no --jobs on a machine with several cores: parallel: exit code", r.returncode, 0)

# The same results at any width: same lines, same order, same exit code, for a set with a pass, a fail, a 77, an expected 77
# and files of different sizes (the start order follows the size, the print order never does).
big = OK + "# padding\n" * 400
SET = {"tests/test_ok.py": OK, "tests/test_big.py": big.replace("test_ok", "test_big"), "tests/test_bad.py": BAD,
       "tests/test_skip.py": SKIP, "tests/test_skip2.py": SKIP.replace("no such tool", "other tool"),
       "tests/test_zeta.py": OK.replace("test_ok", "test_zeta")}
for label, drop, args in (("set 1: everything", (), ()),
                          ("set 2: no failing file, a declared skip", ("tests/test_bad.py",), ("--expect-not-run", "tests/test_skip.py")),
                          ("set 3: both skips declared, no failing file", ("tests/test_bad.py",),
                           ("--expect-not-run", "tests/test_skip.py,tests/test_skip2.py"))):
    repo = helpers.toy_repo({k: v for k, v in SET.items() if k not in drop})
    one = helpers.fwx(repo, "test", "--jobs", "1", *args)
    four = helpers.fwx(repo, "test", "--jobs", "4", *args)
    s.ok("--jobs 1 and --jobs 4 print the same, %s: --jobs 1 printed something" % label, len(one.stdout.splitlines()) >= 6, one.stdout + one.stderr)
    s.eq("--jobs 1 and --jobs 4 print the same, %s: stdout" % label, four.stdout, one.stdout)
    s.eq("--jobs 1 and --jobs 4 print the same, %s: stderr" % label, four.stderr, one.stderr)
    s.eq("--jobs 1 and --jobs 4 print the same, %s: exit code" % label, four.returncode, one.returncode)
    names = [l.split()[1] if l.startswith(("PASS", "FAIL")) else l.split(": ")[1] for l in one.stdout.splitlines()[:-1]
             if l.startswith(("PASS", "FAIL", "NOT RUN", "EXPECTED"))]
    s.eq("--jobs 4, %s: the lines are in the order of the file names" % label, names, sorted(names))
    s.ok("--jobs 4, %s: a line for every file" % label, len(names) == len(SET) - len(drop), str(names))

# A failing file's output is shown whole, never split by another file's lines.
CHATTY = 'import sys, time\nfor i in range(%d):\n    print("%s line %%d" %% i)\n    sys.stdout.flush()\n    time.sleep(0.002)\nsys.exit(1)\n'
repo = helpers.toy_repo({"tests/test_x.py": CHATTY % (150, "x"), "tests/test_y.py": CHATTY % (150, "y"),
                         "tests/test_z.py": CHATTY % (150, "z"), "tests/test_ok.py": OK})
r = helpers.fwx(repo, "test", "--jobs", "4")
lines = r.stdout.splitlines()
for tag in "xyz":
    idx = [i for i, l in enumerate(lines) if l.startswith("    %s line " % tag)]
    s.eq("a failing file's output is contiguous: %s has all its lines" % tag, len(idx), 150)
    s.ok("a failing file's output is contiguous: %s is one block, right after its FAIL line" % tag,
         bool(idx) and idx == list(range(idx[0], idx[0] + 150)) and lines[idx[0] - 1].startswith("FAIL  tests/test_%s.py" % tag),
         "first lines at %s" % idx[:3])
s.eq("a failing file's output is contiguous: the summary", last(r), "4 test file(s): 1 passed, 3 failed, 0 not run")

# Killing the runner kills every child and its group: nothing is left running.
HOLD = ('import os, subprocess, sys, time\n'
        'child = subprocess.Popen(["sleep", "300"])\n'
        'tmp = %(f)r + ".tmp"\n'
        'open(tmp, "w").write("%%d %%d" %% (os.getpid(), child.pid))\n'
        'os.rename(tmp, %(f)r)\n'
        'time.sleep(300)\n')


def state(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def alive(pid):
    return state(pid) not in (None, "Z", "X")


def gone(pids, within=10):
    end = time.time() + within
    while time.time() < end and any(alive(p) for p in pids):
        time.sleep(0.05)
    return [p for p in pids if alive(p)]


def killed_runner(sig, jobs="2"):
    """Start the runner on two files that each park a child and sleep; send `sig` once all four processes exist."""
    d = helpers.mkdtemp("fwx-kill-")
    marks = [os.path.join(d, "m%d" % i) for i in range(2)]
    repo = helpers.toy_repo({"tests/test_h%d.py" % i: HOLD % {"f": marks[i]} for i in range(2)})
    runner = subprocess.Popen([sys.executable, os.path.join(helpers.ROOT, "bin", "fwx"), "test", "--jobs", jobs], cwd=repo,
                              env=helpers.clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, start_new_session=True)
    pids = []
    try:
        end = time.time() + 60
        while time.time() < end and not all(os.path.exists(m) for m in marks) and runner.poll() is None:
            time.sleep(0.05)
        for m in marks:
            if os.path.exists(m):
                pids += [int(x) for x in open(m).read().split()]
        before = [p for p in pids if alive(p)]
        if runner.poll() is None:
            runner.send_signal(sig)
        try:
            out, err = runner.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            runner.kill()
            out, err = runner.communicate()
            err += " [the runner did not exit within 30 s of the signal]"
        return pids, before, runner.returncode, out, err, gone(pids)
    finally:
        for p in pids:
            if alive(p):
                os.kill(p, signal.SIGKILL)
        if runner.poll() is None:
            runner.kill()
            runner.wait()
        for pipe in (runner.stdout, runner.stderr):
            if pipe:
                pipe.close()


for sig, name in ((signal.SIGTERM, "SIGTERM"), (signal.SIGINT, "SIGINT")):
    pids, before, rc, out, err, left = killed_runner(sig)
    s.eq("%s: the runner's children are alive while it runs (the search finds them)" % name, len(before), 4)
    s.eq("%s: the runner exits with 128 + the signal" % name, rc, 128 + int(sig))
    s.eq("%s: no test file, no sleep it started is left running" % name, left, [])
    s.ok("%s: one line on stderr says it was interrupted" % name, "interrupted" in err and len(err.strip().splitlines()) == 1, err)

# Usage errors: one line on stderr, exit 2, no traceback, nothing run.
for label, args in (("--jobs 0", ("--jobs", "0")), ("--jobs -1", ("--jobs", "-1")), ("--jobs abc", ("--jobs", "abc")),
                    ("--jobs 1.5", ("--jobs", "1.5")), ("--jobs with no value", ("--jobs",)), ("--jobs=", ("--jobs=",)),
                    ("--jobs=0", ("--jobs=0",)), ("--jobs given twice", ("--jobs", "2", "--jobs", "3"))):
    r = case("%s is a usage error" % label, NO_BAD, 2, "", args=args, new=False)
    err = r.stderr.strip().splitlines()
    s.ok("%s: one line on stderr, naming --jobs, no traceback" % label,
         len(err) == 1 and "--jobs" in err[0] and "Traceback" not in r.stderr, repr(r.stderr))
    s.eq("%s: nothing on stdout" % label, r.stdout, "")
# A file git lists but the disk no longer has (deleted, not yet committed): a FAIL line like any file that cannot run, never a traceback
# from the size the start order is taken from. Seen red before the size was read with a fallback:
#   FAIL: a tracked file missing on disk: exit code: got 1, want 1 ... FAIL: a tracked file missing on disk: no traceback: Traceback (most recent call last): ... FileNotFoundError
repo = helpers.toy_repo({"tests/test_ok.py": OK, "tests/test_gone.py": OK})
os.remove(os.path.join(repo, "tests", "test_gone.py"))
for jobs in ("1", "3"):
    r = helpers.fwx(repo, "test", "--jobs", jobs)
    s.ok("a tracked file missing on disk, --jobs %s: no traceback" % jobs, "Traceback" not in r.stderr, r.stderr[-300:])
    s.eq("a tracked file missing on disk, --jobs %s: exit code" % jobs, r.returncode, 1)
    s.ok("a tracked file missing on disk, --jobs %s: it is a FAIL line, the other file passes" % jobs,
         "FAIL  tests/test_gone.py (exit 2)" in r.stdout and "PASS  tests/test_ok.py" in r.stdout and last(r) == "2 test file(s): 1 passed, 1 failed, 0 not run", r.stdout + r.stderr)
case("--jobs together with --expect-not-run", NO_BAD, 0, "3 test file(s): 2 passed, 0 failed, 0 not run, 1 expected not run",
     args=("--jobs", "3", "--expect-not-run", "tests/test_skip.py"))
case("--jobs 1 and a failing file: same as before", FILES, 1, "4 test file(s): 2 passed, 1 failed, 1 not run", args=("--jobs", "1"))

s.done()
