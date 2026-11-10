#!/usr/bin/env python3
"""A test that leaves a folder in /tmp is a bug in that test (ORDERS 14): /tmp is RAM on this machine, and a failing
run of tests/test_sync_fixture.py alone left 14 `forge-s0-*` toy worlds of ~115 MB each, 71 of them at once, with
`uninstall-test-*`, `fwdeny-test-*`, `guard-test-consent-*` (hundreds) and more beside them until /tmp filled up and
the session broke.

Every case runs a suite in a child with a private TMPDIR (so it cannot race another run) and looks at what the
child left there. The toy suites use tests/sandbox.py the way the real ones do; the real one is test_sync_fixture,
run to a FAILING end (--compare against a dump that cannot match), the path that kept its worlds.

Seen failing on 584fb80 (sandbox.cleanup kept every dir of a failing run and said nothing for a crash), this file
run against that checkout's sandbox.py plus one KEEP_ENV line, 11 FAIL:
  fail: left in TMPDIR = ['cleanup-fail-8e0rr05n', 'cleanup-fail-zpsriopg'], want []
  raise: left in TMPDIR = ['raise-zuot__de'] ; exit: ['exit-01kka26i'] ; readonly: ['readonly-hj1kyj5n']
  term: exit code is 128+SIGTERM = -15, want 143 ; left in TMPDIR = ['term-i1f9py1y']
  real test_sync_fixture, failing: left in TMPDIR = ['forge-s0-ac99_yjc', 'forge-s0-aw0db_sd', 'forge-s0-xuarkukn'], want []
  static: tests/test_consent_adapter.py, tests/test_sync_fixture.py, hooks/test_ponytail_subagent.py and
  hooks/test_worktree_guard.py make a temp dir nothing removes at exit
  bench verdict: left in TMPDIR = ['tmp69u8oyxh', 'tmpg6hhc_4c', 'tmpho00zjld', 'tmpvdtfimsc'], want []
  test_skill_bench_project: left in TMPDIR = ['skillbench-l3faz6wa', 'skillbench-xf4nbej9', 'skillbench-zr1bof79'], want []
The passing case was clean on master too (it is the control that the harness sees a clean run as clean).
Controls: FORGE_TEST_KEEP=1 must leave the dir (a left-over is visible to this very check, and the switch is
opt-in), and the static scan must flag a planted bare tempfile.mkdtemp line."""
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
FORGE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sandbox  # noqa: E402

failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


TOY = "import os, sys\nsys.path.insert(0, %r)\nimport sandbox\n" % HERE
# name -> (body of the toy suite, expected number of dirs left by the default run, expected exit code)
CASES = {
    "pass": ("d = sandbox.mkdtemp('cleanup-pass-')\nsandbox.cleanup(False)\n", 0, 0),
    "fail": ("sandbox.mkdtemp('cleanup-fail-'); sandbox.mkdtemp('cleanup-fail-')\nsandbox.cleanup(True)\nsys.exit(1)\n", 0, 1),
    "raise": ("sandbox.mkdtemp('raise-')\nraise RuntimeError('a check blew up')\n", 0, 1),
    "exit": ("sandbox.mkdtemp('exit-')\nsys.exit(1)\n", 0, 1),
    "readonly": ("d = sandbox.mkdtemp('readonly-')\nos.makedirs(d + '/sub')\nopen(d + '/sub/f', 'w').close()\n"
                 "os.chmod(d + '/sub', 0o500)\nsandbox.cleanup(True)\nsys.exit(1)\n", 0, 1),
}
SLEEPER = "d = sandbox.mkdtemp('term-')\nopen(sys.argv[1], 'w').close()\ntime.sleep(60)\n"


def child_env(tmp, **extra):
    env = {k: v for k, v in os.environ.items() if k != sandbox.KEEP_ENV}
    env.update(TMPDIR=tmp, PYTHONDONTWRITEBYTECODE="1", **extra)
    return env


def left(tmp):
    return sorted(os.listdir(tmp))


with tempfile.TemporaryDirectory(prefix="temp-cleanup-") as top:
    scripts = os.path.join(top, "scripts")
    os.makedirs(scripts)
    n = 0

    def run_toy(name, body, tmp, *args, **extra):
        p = os.path.join(scripts, name + ".py")
        with open(p, "w") as fh:
            fh.write(TOY.replace("import os, sys", "import os, sys, time") + body)
        return subprocess.run([sys.executable, p] + list(args), env=child_env(tmp, **extra), capture_output=True,
                              text=True, timeout=120)

    for name, (body, want_left, want_rc) in CASES.items():
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
        fh.write(TOY.replace("import os, sys", "import os, sys, time") + SLEEPER)
    p = subprocess.Popen([sys.executable, os.path.join(scripts, "term.py"), ready], env=child_env(tmp),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 30
    while not os.path.exists(ready) and time.time() < deadline:
        time.sleep(0.05)
    want("term: the suite got as far as making its dir", len(left(tmp)), 1)
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=30)
    n += 1
    want("term: exit code is 128+SIGTERM", p.returncode, 128 + signal.SIGTERM)
    want("term: left in TMPDIR", left(tmp), [])

    # Control: the opt-in switch keeps, so a left-over is something this check can see.
    tmp = os.path.join(top, "tmp-keep")
    os.makedirs(tmp)
    r = run_toy("keep", CASES["fail"][0], tmp, **{sandbox.KEEP_ENV: "1"})
    n += 1
    want("control FORGE_TEST_KEEP=1: the failing run keeps its two dirs", [x.rsplit("-", 1)[0] for x in left(tmp)],
         ["cleanup-fail", "cleanup-fail"])
    want("control FORGE_TEST_KEEP=1: it says where they are", "kept:" in r.stdout, True)

    # The bench: skill_bench.verdict on the two tasks whose oracle code makes temp dirs of its own (2 per run), and the
    # one suite that called skill_bench.fresh and never removed its dir.
    tmp = os.path.join(top, "tmp-bench")
    os.makedirs(tmp)
    probe = ("import os, sys\nsys.path.insert(0, %r)\nimport skill_bench as sb\n"
             "for t in ('arch-dependency-02', 'arch-refactor-01'):\n"
             "    res, err = sb.verdict(os.path.join(sb.DEFAULT_BENCH, 'tasks', t), None, '', 120)\n"
             "    print(t, err, len(res or []))\n" % os.path.join(FORGE, "scripts", "bench"))
    r = subprocess.run([sys.executable, "-c", probe], env=child_env(tmp), capture_output=True, text=True, timeout=300)
    n += 1
    want("bench verdict: it ran both tasks to a result (else it looked at nothing)", r.stdout.split(), ["arch-dependency-02", "None", "4", "arch-refactor-01", "None", "4"])
    want("bench verdict: left in TMPDIR (stderr %r)" % r.stderr.strip()[-120:], left(tmp), [])
    tmp = os.path.join(top, "tmp-bench-project")
    os.makedirs(tmp)
    r = subprocess.run([sys.executable, os.path.join(HERE, "test_skill_bench_project.py")], env=child_env(tmp),
                       capture_output=True, text=True, timeout=300)
    n += 1
    want("test_skill_bench_project: it passed (else this looked at a failing run)", (r.returncode, r.stdout.strip().splitlines()[-1:]), (0, ["0 failure(s)"]))
    want("test_skill_bench_project: left in TMPDIR", left(tmp), [])

    # The real suite that kept its worlds: a run that FAILS (its dump holds a file the run cannot reproduce).
    ok, why = sandbox.unshare_ok()
    if ok:
        dump = os.path.join(top, "dump")
        os.makedirs(dump)
        with open(os.path.join(dump, "never-produced.txt"), "w") as fh:
            fh.write("x\n")
        tmp = os.path.join(top, "tmp-real")
        os.makedirs(tmp)
        r = subprocess.run([sys.executable, os.path.join(HERE, "test_sync_fixture.py"), "--compare", dump],
                           env=child_env(tmp), capture_output=True, text=True, timeout=900)
        n += 1
        want("real test_sync_fixture: it failed (else this looked at a passing run)", r.returncode, 1)
        want("real test_sync_fixture: it reached the compare, after its first sandbox existed",
             "FAIL  output and writes identical to" in r.stdout, True)
        want("real test_sync_fixture, failing: left in TMPDIR", left(tmp), [])
    else:
        print("NOT RUN, NOT ARMED: the failing test_sync_fixture case needs an empty network namespace (%s)" % why)

# Static: no test makes a temp dir that only a happy path removes. tempfile.mkdtemp in a test file is a bug unless
# sandbox.py (the one place that registers a dir for removal at exit) made it; a TemporaryDirectory removes itself.
BARE = re.compile(r"\btempfile\.mkdtemp\(")


def bare_lines(text):
    return [l.strip() for l in text.splitlines() if BARE.search(l) and not l.lstrip().startswith("#")]


want("control: a planted bare tempfile.mkdtemp is flagged", len(bare_lines('d = tempfile.mkdtemp(prefix="x-")\n')), 1)
want("control: a planted sandbox.mkdtemp is not", len(bare_lines('d = sandbox.mkdtemp("x-")\n')), 0)
looked = 0
for top_dir in ("tests", "hooks", "scripts"):
    for d, dirs, files in os.walk(os.path.join(FORGE, top_dir)):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", "node_modules", ".git")]
        for f in files:
            if f == "sandbox.py" or f == "test_temp_cleanup.py" or not (f.startswith("test_") or f.startswith("test-")):
                continue
            with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            looked += 1
            for line in bare_lines(text):
                failures.append("%s makes a temp dir nothing removes at exit: %s" % (os.path.relpath(os.path.join(d, f), FORGE), line[:100]))
want("static: looked at some test files", looked > 20, True)

for f in failures:
    print("FAIL", f)
print("%d toy/real runs, %d test files scanned, %d failure(s)" % (n, looked, len(failures)))
sys.exit(1 if failures else 0)
