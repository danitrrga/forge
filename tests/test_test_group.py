#!/usr/bin/env python3
"""`forge test fwx`: the plugin's suite run as a group of forge's runner, and `forge test` with no group unchanged.

Every case runs a toy copy of bin/forge and forge/ (so lib.ROOT is the toy) in a toy git repository that holds a
plugins/fwx/tests folder with test_ok.py (exit 0), test_bad.py (exit 1), test_skip.py (exit 77 with its NOT RUN line) and
test_new.py (exit 0, never added to git). The plugin's own runner, `fwx test`, was this code before it moved here; its tests
(test_runner.py of the plugin) are this file's cases, run through `forge test fwx` instead.

Written first, run on master (`forge test` took no group, no --expect-not-run and no --jobs; 95 of 167 checks failed, the first lines):
  FAIL: all four: exit code: got 2, want 1
  FAIL: all four: summary: got '', want '4 test file(s): 2 passed, 1 failed, 1 not run'
  FAIL: unknown group nosuch: one line on stderr that names it and lists the groups: 'usage: forge [-h]\\n ... forge: error: unrecognized arguments: nosuch\\n'
  FAIL: --jobs 2: two files running at once see each other: exit code: got 2, want 0
On master the no-group cases passed but for the SKIP line, which named `python3 plugins/fwx/bin/fwx test`:
  FAIL: no group: one SKIP line says the plugin's 3 files were left to `forge test fwx`
Controls, each on a copy of forge/testgroup.py (or forge/cli.py) changed in one place, the suite run on the copy, first FAIL of each
(the mutations are not kept; the count is how many checks failed):
  - any 77 counts as expected (`elif code == 77 and rel in expect:` -> `elif code == 77:`), 12:
      FAIL: all four: summary: got '4 test file(s): 2 passed, 1 failed, 0 not run, 1 expected not run', want '4 test file(s): 2 passed, 1 failed, 1 not run'
  - zero passed allowed when something was declared (` or (expect and passed == 0)` dropped), 1:
      FAIL: only declared skips ran: zero tests ran is 1: exit code: got 0, want 1
  - the runner ignores the exit code (`if code == 0:` -> `if True:`), 46:
      FAIL: all four: exit code: got 0, want 1
  - 77 counted green (`return 77 if not_run else 0` -> `return 0`), 3:
      FAIL: ok + skip: exit code: got 0, want 77
  - one worker (`max_workers=jobs` -> 1), 6:
      FAIL: --jobs 2: two files running at once see each other: exit code: got 1, want 0
  - printed in start order (`for rel in files:` -> `for rel in start:`), 3:
      FAIL: --jobs 4, set 1: everything: the lines are in the order of the file names: got ['tests/test_big.py', 'tests/test_zeta.py', ...]
  - the group runs in the repository's top folder (cli.py: the group's folder -> lib.ROOT), 73:
      FAIL: all four: summary: got '0 test file(s): 0 passed, 0 failed, 0 not run', want '4 test file(s): 2 passed, 1 failed, 1 not run'
  - an absent folder with a declared path is a SKIP (`if expect: return 1` dropped), 1:
      FAIL: plugin folder absent, a path declared: exit code: got 0, want 1
  - an unknown group is not refused (cli.py: `if group not in GROUPS:` -> `if False:`), 6:
      FAIL: unknown group nosuch: exit code: got 1, want 2
"""
import os
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

FORGE = sandbox.FORGE
PLUGIN = os.path.join("plugins", "fwx")
fails = []
checks = 0


def ok(label, cond, detail=""):
    global checks
    checks += 1
    if not cond:
        fails.append("FAIL: %s%s" % (label, (": " + detail) if detail else ""))
    return bool(cond)


def eq(label, got, want):
    return ok(label, got == want, "got %r, want %r" % (got, want))


def write(repo, rel, text):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def env(**extra):
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1", HOME=HOME)
    e.update(extra)
    return e


HOME = sandbox.mkdtemp("forge-group-home-")


def toy(files, plugin=True, top=None):
    """A git repository holding a toy copy of forge and, under plugins/fwx, `files` ({path under the plugin: text}); `top` is
    files of the repository's own top folder. Everything is committed."""
    repo = sandbox.mkdtemp("forge-group-")
    sandbox.git(repo, "init", "-q", "-b", "master")
    shutil.copytree(os.path.join(FORGE, "forge"), os.path.join(repo, "forge"), ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(repo, "bin"))
    shutil.copy(os.path.join(FORGE, "bin", "forge"), os.path.join(repo, "bin", "forge"))
    if plugin:
        for rel, text in files.items():
            write(repo, os.path.join(PLUGIN, rel), text)
    for rel, text in (top or {}).items():
        write(repo, rel, text)
    sandbox.git(repo, "add", "-A")
    sandbox.git(repo, "commit", "-q", "-m", "toy")
    return repo


def forge(repo, *args, cwd=None, **extra):
    return subprocess.run([sys.executable, os.path.join(repo, "bin", "forge"), "test"] + list(args), cwd=cwd or repo,
                          env=env(**extra), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)


def last(r):
    out = r.stdout.splitlines()
    return out[-1] if out else ""


OK = ('import os, sys\n'
      'bad = [k for k in os.environ if k.startswith("GIT_")]\n'
      'if bad or not os.path.isfile("tests/test_ok.py"):\n'
      '    print("test_ok: not run from the plugin folder, or GIT_* leaked: %s" % bad)\n'
      '    sys.exit(1)\n')
BAD = 'print("FAIL: the broken case")\nraise SystemExit(1)\n'
SKIP = 'print("NOT RUN, NOT ARMED: no such tool")\nraise SystemExit(77)\n'
FILES = {"tests/test_ok.py": OK, "tests/test_bad.py": BAD, "tests/test_skip.py": SKIP}


def case(label, files, want_rc, want_summary, extra_env=None, new=True, lines=(), args=(), top=None):
    repo = toy(files, top=top)
    if new:
        write(repo, os.path.join(PLUGIN, "tests", "test_new.py"), OK.replace("test_ok", "test_new"))
    r = forge(repo, "fwx", *args, **(extra_env or {}))
    eq("%s: exit code" % label, r.returncode, want_rc)
    eq("%s: summary" % label, last(r), want_summary)
    out = r.stdout.splitlines()
    for prefix, name in lines:
        ok("%s: %s %s" % (label, name, prefix), any(l.startswith(prefix) and name in l for l in out), r.stdout + r.stderr)
    return r


# ---- forge test fwx: one line per file, a summary, an exit code that says what happened ------------------------------------
r = case("all four", FILES, 1, "4 test file(s): 2 passed, 1 failed, 1 not run",
         lines=[("PASS", "test_ok"), ("PASS", "test_new"), ("FAIL", "test_bad"), ("NOT RUN, NOT ARMED", "test_skip")])
ok("all four: the failing test's own output is shown", "FAIL: the broken case" in r.stdout, r.stdout)
ok("all four: the NOT RUN line carries the test's reason", "no such tool" in r.stdout, r.stdout)
case("ok + skip", {k: v for k, v in FILES.items() if k != "tests/test_bad.py"}, 77,
     "3 test file(s): 2 passed, 0 failed, 1 not run", lines=[("NOT RUN, NOT ARMED", "test_skip")])
case("ok only", {"tests/test_ok.py": OK}, 0, "2 test file(s): 2 passed, 0 failed, 0 not run", lines=[("PASS", "test_ok")])
case("no test file", {"README": "toy\n"}, 1, "0 test file(s): 0 passed, 0 failed, 0 not run", new=False)
case("a failure and a skip, no pass", {"tests/test_bad.py": BAD, "tests/test_skip.py": SKIP}, 1,
     "2 test file(s): 0 passed, 1 failed, 1 not run", new=False)
other = toy({"tests/test_decoy.py": "raise SystemExit(1)\n"})
case("GIT_DIR in the caller's environment", {"tests/test_ok.py": OK}, 0, "2 test file(s): 2 passed, 0 failed, 0 not run",
     extra_env={"GIT_DIR": os.path.join(other, ".git"), "GIT_INDEX_FILE": os.path.join(other, ".git", "index")})

# The group is the plugin's folder, not the repository's top: a failing test of the top folder and a fixture of the plugin
# (a folder under tests/ with a test of its own) are not part of it, and where it is run from does not matter.
repo = toy({"tests/test_ok.py": OK, "tests/fixtures/app/test_fix.py": BAD},
           top={"tests/test_decoy.py": BAD, "test_top.py": BAD})
r = forge(repo, "fwx", cwd=HOME)
eq("a repository with tests of its own at the top, run from elsewhere: exit code", r.returncode, 0)
eq("a repository with tests of its own at the top: summary", last(r), "1 test file(s): 1 passed, 0 failed, 0 not run")
ok("a repository with tests of its own at the top: the plugin's own test ran, the top level's did not",
   "PASS  tests/test_ok.py" in r.stdout and "decoy" not in r.stdout and "test_top" not in r.stdout and "fix" not in r.stdout,
   r.stdout + r.stderr)

# ---- --expect-not-run: a test the caller declares cannot run here (CI has no key, no private tree). Paths are the plugin folder's --
NO_BAD = {k: v for k, v in FILES.items() if k != "tests/test_bad.py"}
r = case("declared skip", NO_BAD, 0, "3 test file(s): 2 passed, 0 failed, 0 not run, 1 expected not run",
         args=("--expect-not-run", "tests/test_skip.py"), lines=[("EXPECTED NOT RUN", "test_skip")])
ok("declared skip: the expected line carries the test's reason", "no such tool" in r.stdout, r.stdout)
ok("declared skip: no line starts with the unexpected `NOT RUN, NOT ARMED`",
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
     args=("--expect-not-run", "tests/test_skip.py"), lines=[("NOT RUN, NOT ARMED", "test_skip2"), ("EXPECTED NOT RUN", "test_skip.py")])
case("a declared test that runs and passes is fine", NO_BAD, 77, "3 test file(s): 2 passed, 0 failed, 1 not run",
     args=("--expect-not-run", "tests/test_ok.py"))
case("a declared test that fails is 1", FILES, 1, "4 test file(s): 2 passed, 1 failed, 0 not run, 1 expected not run",
     args=("--expect-not-run", "tests/test_bad.py,tests/test_skip.py"), lines=[("FAIL", "test_bad"), ("EXPECTED NOT RUN", "test_skip")])
case("only declared skips ran: zero tests ran is 1", {"tests/test_skip.py": SKIP}, 1,
     "1 test file(s): 0 passed, 0 failed, 0 not run, 1 expected not run", args=("--expect-not-run", "tests/test_skip.py"), new=False)
r = case("a declared path that is no test file is 1", NO_BAD, 1,
         "3 test file(s): 2 passed, 0 failed, 0 not run, 1 expected not run",
         args=("--expect-not-run", "tests/test_skip.py,tests/test_typo.py"))
ok("a declared path that is no test file: named on stderr", "tests/test_typo.py" in r.stderr, r.stderr)

# ---- usage: an unknown group is 2 and lists the groups; the flags belong to a group; nothing runs ----------------------------
repo = toy(FILES, top={"test_top.py": "pass\n"})
for name in ("nosuch", "engine", "hooks"):
    r = forge(repo, name)
    eq("unknown group %s: exit code" % name, r.returncode, 2)
    eq("unknown group %s: nothing on stdout" % name, r.stdout, "")
    ok("unknown group %s: one line on stderr that names it and lists the groups" % name,
       r.stderr.strip().splitlines() == ["forge test: unknown group %s (groups: fwx)" % name], repr(r.stderr))
for label, args in (("--jobs", ("--jobs", "2")), ("--expect-not-run", ("--expect-not-run", "test_top.py"))):
    r = forge(repo, *args)
    eq("%s with no group: exit code" % label, r.returncode, 2)
    ok("%s with no group: says it needs a group, nothing ran" % label,
       "needs a group" in r.stderr and r.stdout == "", r.stdout + r.stderr)
r = forge(repo, "fwx", "--mutants")
eq("a group with --mutants: exit code", r.returncode, 2)
ok("a group with --mutants: one line, nothing ran", r.stdout == "" and "--mutants" in r.stderr, r.stdout + r.stderr)
r = case("a flag with no value is a usage error", NO_BAD, 2, "", args=("--expect-not-run",))
ok("a flag with no value: stderr names the flag", "--expect-not-run" in r.stderr, r.stderr)
r = case("an unknown flag is a usage error", NO_BAD, 2, "", args=("--nope",))
ok("an unknown flag: stderr names it", "--nope" in r.stderr, r.stderr)

# ---- no group: what it did before, the plugin's suite left to the group and said so --------------------------------------------
r = forge(repo)
eq("no group: exit code", r.returncode, 0)
ok("no group: the repository's own tests ran, the plugin's did not (the failing ones would be FAIL lines)",
   "PASS  test_top.py" in r.stdout and "FAIL" not in r.stdout and "test_ok" not in r.stdout, r.stdout + r.stderr)
ok("no group: one SKIP line says the plugin's 3 files were left to `forge test fwx`",
   "SKIP  plugins/fwx" in r.stdout and "3 tracked test_*.py file(s)" in r.stdout and "forge test fwx" in r.stdout
   and "bin/fwx test" not in r.stdout, r.stdout)
eq("no group: the summary is the one it always printed", last(r), "SUMMARY: 1 passed, 0 warnings, 0 failures")
eq("no group: the same lines as before", [l.split()[0] for l in r.stdout.splitlines()], ["SKIP", "PASS", "SUMMARY:"])

# ---- the plugin folder is absent (a checkout without it): a SKIP that says so, exit 0; a declaration makes it 1 -----------------
repo = toy({}, plugin=False, top={"test_top.py": "pass\n"})
r = forge(repo, "fwx")
eq("plugin folder absent: exit code", r.returncode, 0)
ok("plugin folder absent: one SKIP line, NOT RUN, NOT ARMED, naming the folder",
   any(l.startswith("SKIP  plugins/fwx") and "NOT RUN, NOT ARMED" in l and "no plugins/fwx folder" in l for l in r.stdout.splitlines()),
   r.stdout + r.stderr)
ok("plugin folder absent: the top folder's test did not run", "test_top" not in r.stdout, r.stdout)
r = forge(repo, "fwx", "--expect-not-run", "tests/test_linear_live.py")
eq("plugin folder absent, a path declared: exit code", r.returncode, 1)
ok("plugin folder absent, a path declared: the declared path is named", "tests/test_linear_live.py" in r.stderr, r.stderr)

# ---- --jobs: the files run in parallel, each its own process, and nothing a reader sees depends on how many at once -------------
RENDEZVOUS = ('import os, sys, time\n'
              'd, me, other = %(d)r, %(me)r, %(other)r\n'
              'open(os.path.join(d, me), "w").close()\n'
              'open(os.path.join(d, "launch-" + me), "w").close()\n'
              'end = time.time() + %(wait)s\n'
              'while time.time() < end:\n'
              '    if os.path.exists(os.path.join(d, other)):\n'
              '        sys.exit(0)\n'
              '    time.sleep(0.02)\n'
              'print("FAIL: %%s never saw %%s start" %% (me, other))\n'
              'sys.exit(1)\n')


def pair(wait):
    """Two files that each announce themselves and wait for the other's announcement: both pass only if both are alive at the
    same time, which is the definition of parallel, with no clock to compare. `wait` only bounds how long a failing one waits.
    Returns the repository and the folder the announcements are in (each file also leaves a launch-<name> mark: a launch count)."""
    d = sandbox.mkdtemp("forge-group-par-")
    return toy({"tests/test_a.py": RENDEZVOUS % {"d": d, "me": "a", "other": "b", "wait": wait},
                "tests/test_b.py": RENDEZVOUS % {"d": d, "me": "b", "other": "a", "wait": wait}}), d


def launches(d):
    return sorted(f for f in os.listdir(d) if f.startswith("launch-"))


repo, d = pair(60)
r = forge(repo, "fwx", "--jobs", "2")
eq("--jobs 2: two files running at once see each other: exit code", r.returncode, 0)
eq("--jobs 2: summary", last(r), "2 test file(s): 2 passed, 0 failed, 0 not run")
eq("--jobs 2: each file was launched once", launches(d), ["launch-a", "launch-b"])
repo, d = pair(60)
eq("--jobs=2 form: exit code", forge(repo, "fwx", "--jobs=2").returncode, 0)
repo, d = pair(1)
r = forge(repo, "fwx", "--jobs", "1")
eq("--jobs 1: the files run one after the other (the first cannot see the second): exit code", r.returncode, 1)
eq("--jobs 1: summary", last(r), "2 test file(s): 1 passed, 1 failed, 0 not run")
eq("--jobs 1: each file was launched once", launches(d), ["launch-a", "launch-b"])
# The runner's default is the CPUs this process may use (sched_getaffinity), not the host's: gate on the same count. Red under
# `taskset -c 0` with the host count: FAIL: no --jobs on a machine with several cores: parallel: exit code: got 1, want 0
try:
    usable_cpus = len(os.sched_getaffinity(0))
except AttributeError:
    usable_cpus = os.cpu_count() or 1
if usable_cpus > 1:
    repo, d = pair(60)
    eq("no --jobs on a machine with several cores: parallel: exit code", forge(repo, "fwx").returncode, 0)

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
    repo = toy({k: v for k, v in SET.items() if k not in drop})
    one = forge(repo, "fwx", "--jobs", "1", *args)
    four = forge(repo, "fwx", "--jobs", "4", *args)
    ok("--jobs 1 and --jobs 4 print the same, %s: --jobs 1 printed something" % label, len(one.stdout.splitlines()) >= 6, one.stdout + one.stderr)
    eq("--jobs 1 and --jobs 4 print the same, %s: stdout" % label, four.stdout, one.stdout)
    eq("--jobs 1 and --jobs 4 print the same, %s: stderr" % label, four.stderr, one.stderr)
    eq("--jobs 1 and --jobs 4 print the same, %s: exit code" % label, four.returncode, one.returncode)
    names = [l.split()[1] if l.startswith(("PASS", "FAIL")) else l.split(": ")[1] for l in one.stdout.splitlines()[:-1]
             if l.startswith(("PASS", "FAIL", "NOT RUN", "EXPECTED"))]
    eq("--jobs 4, %s: the lines are in the order of the file names" % label, names, sorted(names))
    ok("--jobs 4, %s: a line for every file" % label, len(names) == len(SET) - len(drop), str(names))

# A failing file's output is shown whole, never split by another file's lines.
CHATTY = 'import sys, time\nfor i in range(%d):\n    print("%s line %%d" %% i)\n    sys.stdout.flush()\n    time.sleep(0.002)\nsys.exit(1)\n'
repo = toy({"tests/test_x.py": CHATTY % (150, "x"), "tests/test_y.py": CHATTY % (150, "y"),
            "tests/test_z.py": CHATTY % (150, "z"), "tests/test_ok.py": OK})
r = forge(repo, "fwx", "--jobs", "4")
lines = r.stdout.splitlines()
for tag in "xyz":
    idx = [i for i, l in enumerate(lines) if l.startswith("    %s line " % tag)]
    eq("a failing file's output is contiguous: %s has all its lines" % tag, len(idx), 150)
    ok("a failing file's output is contiguous: %s is one block, right after its FAIL line" % tag,
       bool(idx) and idx == list(range(idx[0], idx[0] + 150)) and lines[idx[0] - 1].startswith("FAIL  tests/test_%s.py" % tag),
       "first lines at %s" % idx[:3])
eq("a failing file's output is contiguous: the summary", last(r), "4 test file(s): 1 passed, 3 failed, 0 not run")

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
    d = sandbox.mkdtemp("forge-group-kill-")
    marks = [os.path.join(d, "m%d" % i) for i in range(2)]
    repo = toy({"tests/test_h%d.py" % i: HOLD % {"f": marks[i]} for i in range(2)})
    runner = subprocess.Popen([sys.executable, os.path.join(repo, "bin", "forge"), "test", "fwx", "--jobs", jobs], cwd=repo, env=env(),
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              start_new_session=True)
    pids = []
    try:
        end = time.time() + 60
        while time.time() < end and not all(os.path.exists(m) for m in marks) and runner.poll() is None:
            time.sleep(0.05)
        for m in marks:
            if os.path.exists(m):
                with open(m) as f:
                    pids += [int(x) for x in f.read().split()]
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
    eq("%s: the runner's children are alive while it runs (the search finds them)" % name, len(before), 4)
    eq("%s: the runner exits with 128 + the signal" % name, rc, 128 + int(sig))
    eq("%s: no test file, no sleep it started is left running" % name, left, [])
    ok("%s: one line on stderr says it was interrupted" % name, "interrupted" in err and len(err.strip().splitlines()) == 1, err)

# Usage errors: exit 2, no traceback, nothing run, the flag named.
for label, args in (("--jobs 0", ("--jobs", "0")), ("--jobs -1", ("--jobs", "-1")), ("--jobs abc", ("--jobs", "abc")),
                    ("--jobs 1.5", ("--jobs", "1.5")), ("--jobs with no value", ("--jobs",)), ("--jobs=", ("--jobs=",)),
                    ("--jobs=0", ("--jobs=0",)), ("--jobs given twice", ("--jobs", "2", "--jobs", "3")),
                    ("--expect-not-run with an empty name", ("--expect-not-run", "tests/test_skip.py,"))):
    r = case("%s is a usage error" % label, NO_BAD, 2, "", args=args, new=False)
    flag = "--expect-not-run" if "expect" in label else "--jobs"
    ok("%s: stderr names the flag, no traceback" % label, flag in r.stderr and "Traceback" not in r.stderr, repr(r.stderr))
    eq("%s: nothing on stdout" % label, r.stdout, "")
# A file git lists but the disk no longer has (deleted, not yet committed): a FAIL line like any file that cannot run, never a traceback
# from the size the start order is taken from.
repo = toy({"tests/test_ok.py": OK, "tests/test_gone.py": OK})
os.remove(os.path.join(repo, PLUGIN, "tests", "test_gone.py"))
for jobs in ("1", "3"):
    r = forge(repo, "fwx", "--jobs", jobs)
    ok("a tracked file missing on disk, --jobs %s: no traceback" % jobs, "Traceback" not in r.stderr, r.stderr[-300:])
    eq("a tracked file missing on disk, --jobs %s: exit code" % jobs, r.returncode, 1)
    ok("a tracked file missing on disk, --jobs %s: it is a FAIL line, the other file passes" % jobs,
       "FAIL  tests/test_gone.py (exit 2)" in r.stdout and "PASS  tests/test_ok.py" in r.stdout
       and last(r) == "2 test file(s): 1 passed, 1 failed, 0 not run", r.stdout + r.stderr)
case("--jobs together with --expect-not-run", NO_BAD, 0, "3 test file(s): 2 passed, 0 failed, 0 not run, 1 expected not run",
     args=("--jobs", "3", "--expect-not-run", "tests/test_skip.py"))
case("--jobs 1 and a failing file: same as before", FILES, 1, "4 test file(s): 2 passed, 1 failed, 1 not run", args=("--jobs", "1"))

sandbox.cleanup(bool(fails))
if checks == 0:
    fails.append("FAIL: no check ran")
for line in fails:
    print(line)
print("%d checks" % checks)
sys.exit(1 if fails else 0)
