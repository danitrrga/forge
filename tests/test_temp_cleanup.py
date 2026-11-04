#!/usr/bin/env python3
"""A test that leaves a folder in /tmp is a bug in that test (ORDERS 14): /tmp is RAM on this machine, and 113 `fwx-*`
folders (`fwx-exrun-*`, `fwx-exmut-*`, `fwx-toy-*`, `fwx-plan-*`, ...) had piled up there from failing, crashed and
killed runs of the suites.

Every case runs a suite in a child with a private TMPDIR (so it cannot race another run) and looks at what the child
left there. The private TMPDIR is made under the real temp root, outside any git repo: a test that needs /tmp outside
a repo (tests/test_config.py, test_model.py) fails when TMPDIR is inside the worktree. The toy suites use tests/helpers.py
the way the real ones do (helpers.mkdtemp, toy_repo, add_worktree, Suite.done); the real one is test_wave_brief, whose
generated python made its own `tempfile.mkdtemp()` per case.

Seen failing on 1bdcc0a (helpers.cleanup kept every dir of a failing run; a crash or a SIGTERM kept them silently), this
file run against that checkout's tests/helpers.py and test_wave_brief.py, 11 FAIL:
  fail: left in TMPDIR = ['cleanup-fail-k5cprno5', 'cleanup-fail-lyxx62pn'], want []
  suite (toy_repo + add_worktree + a failing Suite.done): left ['fwx-toy-l470f7n0', 'fwx-wt-ueyoesl2'], want []
  raise: ['raise-6im92hfy'] ; exit: ['exit-la7ef817'] ; readonly: ['readonly-9zh1z5sb']
  remove: AttributeError: module 'helpers' has no attribute 'remove' (exit code 1, want 0)
  term: exit code is 128+SIGTERM = -15, want 143 ; left in TMPDIR = ['fwx-toy-q0q21e0v']
  real test_wave_brief: left in TMPDIR = 21 dirs `tmp*` holding context.x decisions.x plan.x, want []
  static: tests/test_wave_brief.py makes a temp dir nothing removes at exit: "d = tempfile.mkdtemp()\n"
One full `fwx test` under a private TMPDIR on that base left those same 21 `tmp*` dirs, all from test_wave_brief. The
`fwx-exrun-*` / `fwx-exmut-*` dirs of test_execute_workflow were only ever left by runs that failed or were killed (a
passing run removed them at its end, but 500+ of them at once at the peak: helpers.remove frees each one after its run).
Controls: FWX_TEST_KEEP=1 must leave the dir (a left-over is visible to this very check, and the switch is opt-in), the
passing case is clean on the base too (this check sees a clean run as clean), and the static scan must flag a planted
bare tempfile.mkdtemp line."""
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import helpers  # noqa: E402

KEEP_ENV = "FWX_TEST_KEEP"
failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


TOY = "import os, sys, time\nsys.path.insert(0, %r)\nimport helpers\n" % HERE
# name -> (body of the toy suite, exit code). Every one makes dirs through helpers and must leave none behind.
CASES = {
    "pass": ("d = helpers.mkdtemp('cleanup-pass-')\nhelpers.cleanup(False)\n", 0),
    "fail": ("helpers.mkdtemp('cleanup-fail-'); helpers.mkdtemp('cleanup-fail-')\nhelpers.cleanup(True)\nsys.exit(1)\n", 1),
    "suite": ("s = helpers.Suite()\nrepo = helpers.toy_repo()\nhelpers.add_worktree(repo, 'side')\n"
              "s.ok('a check that fails', False, 'on purpose')\ns.done()\n", 1),
    "raise": ("helpers.mkdtemp('raise-')\nraise RuntimeError('a check blew up')\n", 1),
    "exit": ("helpers.mkdtemp('exit-')\nsys.exit(1)\n", 1),
    "not-run": ("s = helpers.Suite()\nhelpers.toy_repo()\ns.not_run('a tool is missing')\n", 77),
    "remove": ("d = helpers.mkdtemp('remove-')\nhelpers.remove(d)\nprint(os.path.exists(d))\nsys.exit(0 if not os.path.exists(d) else 1)\n", 0),
    "readonly": ("d = helpers.mkdtemp('readonly-')\nos.makedirs(d + '/sub')\nopen(d + '/sub/f', 'w').close()\n"
                 "os.chmod(d + '/sub', 0o500)\nhelpers.cleanup(True)\nsys.exit(1)\n", 1),
}
SLEEPER = "helpers.toy_repo()\nopen(sys.argv[1], 'w').close()\ntime.sleep(60)\n"


def child_env(tmp, **extra):
    env = {k: v for k, v in os.environ.items() if k != KEEP_ENV}
    env.update(TMPDIR=tmp, PYTHONDONTWRITEBYTECODE="1", **extra)
    return env


def left(tmp):
    return sorted(os.listdir(tmp))


# The private root: under the real temp root (this process's TMPDIR may itself be a private one), outside any repo.
with tempfile.TemporaryDirectory(prefix="temp-cleanup-") as top:
    scripts = os.path.join(top, "scripts")
    os.makedirs(scripts)
    n = 0

    def run_toy(name, body, tmp, *args, **extra):
        p = os.path.join(scripts, name.replace("-", "_") + ".py")
        with open(p, "w") as fh:
            fh.write(TOY + body)
        return subprocess.run([sys.executable, p] + list(args), env=child_env(tmp, **extra), capture_output=True,
                              text=True, timeout=120)

    for name, (body, want_rc) in CASES.items():
        tmp = os.path.join(top, "tmp-" + name)
        os.makedirs(tmp)
        r = run_toy(name, body, tmp)
        n += 1
        want("%s: exit code" % name, r.returncode, want_rc)
        want("%s: left in TMPDIR (stderr %r)" % (name, r.stderr.strip()[-120:]), left(tmp), [])

    # SIGTERM: a timeout's kill must not leave the world behind. The suite says it is up, then sleeps.
    tmp = os.path.join(top, "tmp-term")
    os.makedirs(tmp)
    ready = os.path.join(top, "ready")
    with open(os.path.join(scripts, "term.py"), "w") as fh:
        fh.write(TOY + SLEEPER)
    p = subprocess.Popen([sys.executable, os.path.join(scripts, "term.py"), ready], env=child_env(tmp),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 30
    while not os.path.exists(ready) and time.time() < deadline:
        time.sleep(0.05)
    want("term: the suite got as far as making its repo", len(left(tmp)), 1)
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=30)
    n += 1
    want("term: exit code is 128+SIGTERM", p.returncode, 128 + signal.SIGTERM)
    want("term: left in TMPDIR", left(tmp), [])

    # Control: the opt-in switch keeps, so a left-over is something this check can see.
    tmp = os.path.join(top, "tmp-keep")
    os.makedirs(tmp)
    r = run_toy("keep", CASES["fail"][0], tmp, **{KEEP_ENV: "1"})
    n += 1
    want("control FWX_TEST_KEEP=1: the failing run keeps its two dirs", [x.rsplit("-", 1)[0] for x in left(tmp)],
         ["cleanup-fail", "cleanup-fail"])
    want("control FWX_TEST_KEEP=1: it says where they are", "kept:" in r.stdout, True)

    # The real suite that made temp dirs in a child process of its own.
    tmp = os.path.join(top, "tmp-real")
    os.makedirs(tmp)
    r = subprocess.run([sys.executable, os.path.join(HERE, "test_wave_brief.py")], env=child_env(tmp),
                       capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    n += 1
    want("real test_wave_brief: it passed (else this looked at a failing run)", r.returncode, 0)
    want("real test_wave_brief: it looked at something", bool(re.search(r"\b[1-9]\d* checks\b", r.stdout)), True)
    want("real test_wave_brief: left in TMPDIR", left(tmp), [])

# Static: no test makes a temp dir that only a happy path removes. tempfile.mkdtemp / mkstemp in a test file (generated
# python in a string included) is a bug unless helpers.py (the one place that registers a dir for removal at exit) made
# it; a TemporaryDirectory removes itself.
BARE = re.compile(r"\btempfile\.(mkdtemp|mkstemp)\(")


def bare_lines(text):
    return [l.strip() for l in text.splitlines() if BARE.search(l) and not l.lstrip().startswith("#")]


want("control: a planted bare tempfile.mkdtemp is flagged", len(bare_lines('d = tempfile.mkdtemp(prefix="x-")\n')), 1)
want("control: a planted helpers.mkdtemp is not", len(bare_lines('d = helpers.mkdtemp("x-")\n')), 0)
looked = 0
for f in sorted(os.listdir(HERE)):
    if f in ("helpers.py", "test_temp_cleanup.py") or not (f.startswith("test_") and f.endswith(".py")):
        continue
    with open(os.path.join(HERE, f), encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    looked += 1
    for line in bare_lines(text):
        failures.append("tests/%s makes a temp dir nothing removes at exit: %s" % (f, line[:100]))
want("static: looked at some test files", looked > 20, True)

for f in failures:
    print("FAIL", f)
print("%d toy/real runs, %d test files scanned, %d failure(s)" % (n, looked, len(failures)))
sys.exit(1 if failures else 0)
