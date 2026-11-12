"""Run every tests/test_*.py of the working folder and summarise: PASS, FAIL, or NOT RUN, NOT ARMED.

The repo's checks recipe. Each test is a plain script that runs itself, prints its FAIL lines and
exits 1 on any; one that cannot run (a tool, a key or the network is missing) prints
`NOT RUN, NOT ARMED: <reason>` as its last line and exits 77.

Exit 0 when every file passed. Exit 1 when one failed, or when there was no test file at all
(looking at zero is a failure). Exit 77 when none failed but one did not run: neither green nor red,
because a CI job that skips its tests would otherwise end green. Whoever wants 0 lets them run.

`--expect-not-run PATH[,PATH...]` (repeatable, also `--expect-not-run=PATH`) declares tests that cannot run
where this is called from (CI has no key, no private tree). A declared test that exits 77 prints
`EXPECTED NOT RUN: PATH: reason` and no longer turns the exit to 77; an undeclared 77 still does. A declared test that
runs counts as any other, so a failing one is still 1. The declaration widens nothing else: a run in which no
test passed is 1 (everything declared away proves nothing), and so is a declared path that is no test file (a typo
would silently un-declare it). Why a flag and not a list file: the reason sits beside the command in the workflow,
and there is no second file to forget. Exit 2 on a usage error.

`--jobs N` runs up to N files at once (default: the CPUs this process may use, at most 8; `--jobs 1` is one file after another,
as before). Each file is still its own process with its own exit code, its output captured whole, so a failing file's lines are
never mixed with another's. What a reader sees does not depend on N: the per-file lines and the summary are printed in the order
of the file names, each as soon as it and every file before it has finished, so for a given set of results the output and the
exit code are the same at any N. Start order is largest file first (the slowest files of a suite are mostly its largest; a
longest-first order keeps the last worker from starting the one long file; a duration table would have to be written somewhere
and would rot, and the size costs one `stat`). Each child runs in its own session: SIGINT, SIGTERM or SIGHUP to the runner sends
SIGTERM to every running child's whole process group (the test's own cleanup runs), SIGKILL to what is left after 5 s, and exits
128 + the signal, so nothing a test started outlives the run. SIGKILL of the runner itself cannot be caught and leaves them.
"""
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

NOT_RUN = "NOT RUN, NOT ARMED"
EXPECTED = "EXPECTED NOT RUN"
USAGE = "usage: fwx test [--expect-not-run PATH[,PATH...]] [--jobs N]\n"
MAX_DEFAULT_JOBS = 8
GRACE_S = 5
STOP = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def clean_env():
    """The environment without GIT_*: inside a git hook GIT_DIR and GIT_INDEX_FILE point at the
    repo being committed, and a test that builds its own repos must not reach it."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def test_files(root, env):
    """tests/test_*.py that git tracks or would add: a new test counts before its first commit."""
    out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         env=env, capture_output=True, text=True, check=True).stdout
    return sorted(f for f in out.split("\0")
                  if os.path.dirname(f) == "tests" and os.path.basename(f).startswith("test_") and f.endswith(".py"))


def reason(output):
    """What a test says after `NOT RUN, NOT ARMED:` on its last line."""
    lines = [l for l in output.strip().splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    return last.split(NOT_RUN + ":", 1)[1].strip() if (NOT_RUN + ":") in last else "no reason printed"


def parse(argv):
    """(declared paths, jobs) or an error line. `jobs` is None when --jobs was not given."""
    out = set()
    jobs = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--expect-not-run":
            i += 1
            if i >= len(argv):
                return None, None, USAGE.strip()
            value = argv[i]
        elif a.startswith("--expect-not-run="):
            value = a.split("=", 1)[1]
        elif a == "--jobs" or a.startswith("--jobs="):
            if jobs is not None:
                return None, None, "fwx test: --jobs given twice"
            if a == "--jobs":
                i += 1
                value = argv[i] if i < len(argv) else ""
            else:
                value = a.split("=", 1)[1]
            if not (value.isascii() and value.isdigit() and int(value) >= 1):
                return None, None, "fwx test: --jobs wants a whole number of 1 or more, got %r" % value
            jobs = int(value)
            i += 1
            continue
        else:
            return None, None, USAGE.strip()
        names = [n.strip() for n in value.split(",")]
        if not all(names):
            return None, None, USAGE.strip()
        out.update(names)
        i += 1
    return out, jobs, None


def default_jobs():
    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:
        cpus = os.cpu_count() or 1
    return max(1, min(cpus, MAX_DEFAULT_JOBS))


class Interrupted(Exception):
    def __init__(self, signum):
        Exception.__init__(self, signum)
        self.signum = signum


class Children:
    """The running test processes, each the leader of its own process group, so that one call can end them all."""

    def __init__(self):
        self.lock = threading.Lock()
        self.live = {}
        self.stopped = False

    def run(self, rel, root, env):
        """(exit code, output) of one test file; its stdout and stderr in one string, as a single `subprocess.run` gave."""
        with self.lock:
            if self.stopped:
                return None, ""
            p = subprocess.Popen([sys.executable, rel], cwd=root, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            self.live[p.pid] = p
        try:
            out, _ = p.communicate()
        finally:
            with self.lock:
                self.live.pop(p.pid, None)
        return p.returncode, out

    def kill_all(self):
        """SIGTERM to every group, SIGKILL to what is still there after GRACE_S. Returns how many were running."""
        with self.lock:
            self.stopped = True
            groups = list(self.live)
        for sig, wait in ((signal.SIGTERM, GRACE_S), (signal.SIGKILL, 0)):
            for pgid in groups:
                try:
                    os.killpg(pgid, sig)
                except OSError:
                    pass
            end = time.monotonic() + wait
            while time.monotonic() < end and any(_group_alive(g) for g in groups):
                time.sleep(0.02)
        return len(groups)


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except OSError:
        return False
    return True


def main(argv):
    expect, jobs, error = parse(argv)
    if error:
        sys.stderr.write(error + "\n")
        return 2
    jobs = jobs or default_jobs()
    env = clean_env()
    # The folder it is run from, not the repository's top level: this plugin is a folder of a bigger repository
    # (forge's plugins/fwx), and the top level's tests are not its own. `git ls-files` run there lists only that folder.
    root = os.getcwd()
    if subprocess.run(["git", "-C", root, "rev-parse", "--git-dir"], env=env, capture_output=True).returncode:
        sys.stderr.write("fwx test: not inside a git repository\n")
        return 1
    passed = failed = not_run = expected = 0
    files = test_files(root, env)
    unknown = sorted(expect - set(files))
    for rel in unknown:
        sys.stderr.write("fwx test: --expect-not-run names %s, which is no tests/test_*.py file\n" % rel)
    children = Children()
    pool = ThreadPoolExecutor(max_workers=jobs)

    def stop(signum, frame):
        raise Interrupted(signum)

    old = {s: signal.signal(s, stop) for s in STOP}  # before the first child starts: no window in which a signal leaves one running
    try:
        # largest first, ties by name: the order the files start in; the order they are printed in is `files`
        start = sorted(files, key=lambda f: (-os.path.getsize(os.path.join(root, f)), f))
        futures = {rel: pool.submit(children.run, rel, root, env) for rel in start}
        for rel in files:
            code, output = futures[rel].result()
            if code == 0:
                passed += 1
                print("PASS  " + rel)
            elif code == 77 and rel in expect:
                expected += 1
                print("%s: %s: %s" % (EXPECTED, rel, reason(output)))
            elif code == 77:
                not_run += 1
                print("%s: %s: %s" % (NOT_RUN, rel, reason(output)))
            else:
                failed += 1
                print("FAIL  %s (exit %d)" % (rel, code))
                for line in output.splitlines():
                    print("    " + line)
            sys.stdout.flush()
    except Interrupted as e:
        for s in STOP:  # no second signal may cut the cleanup short
            signal.signal(s, signal.SIG_IGN)
        n = children.kill_all()
        pool.shutdown(wait=True, cancel_futures=True)
        sys.stderr.write("fwx test: interrupted by %s; ended %d running test file(s)\n" % (signal.Signals(e.signum).name, n))
        return 128 + e.signum
    except BaseException:  # a child that could not start, a closed stdout: leave nothing running either
        children.kill_all()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    pool.shutdown(wait=True)
    total = passed + failed + not_run + expected
    print("%d test file(s): %d passed, %d failed, %d not run%s"
          % (total, passed, failed, not_run, ", %d expected not run" % expected if expected else ""))
    if failed or total == 0 or unknown or (expect and passed == 0):
        return 1
    return 77 if not_run else 0
