"""The groups of `forge test GROUP`: a suite that is run on its own, with its own exit codes. `fwx` is the plugin's suite (plugins/fwx/tests).

`forge test` with no group never reaches this file. A group runs every tests/test_*.py of its folder and summarises: PASS, FAIL, or
NOT RUN, NOT ARMED. Each test is a plain script that runs itself, prints its FAIL lines and exits 1 on any; one that cannot run (a tool,
a key or the network is missing) prints `NOT RUN, NOT ARMED: <reason>` as its last line and exits 77. Each test runs with the group's
folder as working directory, so every path here (the listing, `--expect-not-run`) is relative to it: `tests/test_x.py`.

Exit 0 when every file passed. Exit 1 when one failed, or when there was no test file at all (looking at zero is a failure). Exit 77
when none failed but one did not run: neither green nor red, because a CI job that skips its tests would otherwise end green. Whoever
wants 0 lets them run. Exit 2 on a usage error. A group whose folder is absent (a checkout without the plugin) is one SKIP line,
`NOT RUN, NOT ARMED`, exit 0, as with any optional part, unless a path was declared: that path is then no test file, which is 1.

`--expect-not-run PATH[,PATH...]` (repeatable, also `--expect-not-run=PATH`) declares tests that cannot run where this is called from
(CI has no key, no private tree). A declared test that exits 77 prints `EXPECTED NOT RUN: PATH: reason` and no longer turns the exit to
77; an undeclared 77 still does. A declared test that runs counts as any other, so a failing one is still 1. The declaration widens
nothing else: a run in which no test passed is 1 (everything declared away proves nothing; a `--shard` slice is exempt, the others carry the passes), and so is a declared path that is no test
file (a typo would silently un-declare it). Why a flag and not a list file: the reason sits beside the command in the workflow, and
there is no second file to forget.

`--shard I/N` runs only the I-th of N slices of the files (1 <= I <= N), so CI can run the slices on separate runners: a suite that is
CPU-bound on one runner gets shorter only with more runners, never with more files at once. The files are dealt one by one, largest
first, to slices 1, 2, .. N, 1, 2, ..: the slices together are every file, once, and the few big files land in different slices. The
first line printed says how much the slice looked at (`shard I/N: K of M test file(s)`); a slice that gets no file is a failure.
`--shard` is a usage error (exit 2) for anything but `I/N` of whole numbers, and given twice.

`--jobs N` runs up to N files at once (default: the CPUs this process may use, at most 8; `--jobs 1` is one file after another).
Each file is still its own process with its own exit code, its output captured whole, so a failing file's lines are never mixed with
another's. What a reader sees does not depend on N: the per-file lines and the summary are printed in the order of the file names, each
as soon as it and every file before it has finished, so for a given set of results the output and the exit code are the same at any N.
Start order is the FWX_SLOW_FIRST files, then the largest file first (the slowest files of a suite are mostly its largest; a longest-first order keeps the last worker from
starting the one long file; a duration table would have to be written somewhere and would rot, and the size costs one `stat`). Each
child runs in its own session: SIGINT, SIGTERM or SIGHUP to the runner sends SIGTERM to every running child's whole process group (the
test's own cleanup runs), SIGKILL to what is left after 5 s, and exits 128 + the signal, so nothing a test started outlives the run.
SIGKILL of the runner itself cannot be caught and leaves them.
"""
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

NOT_RUN = "NOT RUN, NOT ARMED"
EXPECTED = "EXPECTED NOT RUN"
NAME = "forge test fwx"  # what the messages say: the group is the only one there is
MAX_DEFAULT_JOBS = 8
GRACE_S = 5
STOP = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def clean_env():
    """The environment without GIT_*: inside a git hook GIT_DIR and GIT_INDEX_FILE point at the
    repo being committed, and a test that builds its own repos must not reach it."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def inside_checkout(directory):
    """Whether `directory` is inside a git work tree. A test that makes a temp dir and expects to be outside any repository (it builds
    its own, or asks git where it is) fails falsely when TMPDIR sits in a checkout: 13 to 17 of forge's files did (DTC-119)."""
    try:
        r = subprocess.run(["git", "-C", directory, "rev-parse", "--is-inside-work-tree"], env=clean_env(),
                           capture_output=True, text=True)
    except OSError:  # no git, or no such folder: nothing there to be inside of
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


@contextlib.contextmanager
def private_tmp(env):
    """The environment for test children, a copy of `env`. When its temp dir (TMPDIR, else the default) is
    inside a git work tree, TMPDIR is a fresh folder under /tmp for the length of the with block, removed after; otherwise TMPDIR is left as it is."""
    env = dict(env)
    here = env.get("TMPDIR") or tempfile.gettempdir()
    if not inside_checkout(here):
        yield env
        return
    made = tempfile.mkdtemp(prefix="forge-test-", dir="/tmp" if os.path.isdir("/tmp") else None)
    env["TMPDIR"] = made
    try:
        yield env
    finally:
        shutil.rmtree(made, ignore_errors=True)


def failed_lines(failed):
    """The lines that end a run's output when files failed: `failed` is [(name, output)]; one line each, the name and the first FAIL
    line of its output (else its last line) with a count of the others, so a tail of the output names every failed file. [] for none."""
    if not failed:
        return []
    out = ["Failed files (%d):" % len(failed)]
    for name, output in failed:
        lines = [l.strip() for l in output.splitlines() if l.strip()]
        marks = [l for l in lines if l.startswith("FAIL")]
        why = (marks[0] if marks else lines[-1] if lines else "(no output)")
        out.append("  %s: %s%s" % (name, why[:140], " (+%d more FAIL lines)" % (len(marks) - 1) if len(marks) > 1 else ""))
    return out


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


def check(expect_values, jobs_values):
    """(declared paths, jobs, None) from what argparse collected, or (None, None, one error line). `jobs` is None when --jobs was not given."""
    out = set()
    for value in expect_values or []:
        names = [n.strip() for n in value.split(",")]
        if not all(names):
            return None, None, "%s: --expect-not-run takes PATH[,PATH...], got %r" % (NAME, value)
        out.update(names)
    jobs = None
    if len(jobs_values or []) > 1:
        return None, None, "%s: --jobs given twice" % NAME
    for value in jobs_values or []:
        if not (value.isascii() and value.isdigit() and int(value) >= 1):
            return None, None, "%s: --jobs wants a whole number of 1 or more, got %r" % (NAME, value)
        jobs = int(value)
    return out, jobs, None


def parse_shard(values):
    """((I, N) or None, None) from what argparse collected for --shard, or (None, one error line); None for "not given"."""
    if not values:
        return None, None
    if len(values) > 1:
        return None, "%s: --shard wants I/N, given twice" % NAME
    parts = values[0].split("/")
    if len(parts) == 2 and all(p.isascii() and p.isdigit() for p in parts) and 1 <= int(parts[0]) <= int(parts[1]):
        return (int(parts[0]), int(parts[1])), None
    return None, "%s: --shard wants I/N with 1 <= I <= N (both whole numbers), got %r" % (NAME, values[0])


# The fwx files that take minutes (measured on the 4-CPU CI runner, 4 files at once: 461 s, 332 s, 200 s; the next is 94 s) are dealt first, in
# this order, so with 3 shards each gets one: by size alone test_walk and test_ui_walk_workflow land in the same shard. A stale name costs
# minutes, never a result (tests/test_test_shard.py checks that every name is a tracked file).
FWX_SLOW_FIRST = ("tests/test_walk.py", "tests/test_execute_workflow.py", "tests/test_ui_walk_workflow.py")


def start_order(files, root):
    """The order the files start in and are dealt to the slices in: FWX_SLOW_FIRST, then the largest first, ties by name."""
    return sorted(files, key=lambda f: (f not in FWX_SLOW_FIRST, FWX_SLOW_FIRST.index(f) if f in FWX_SLOW_FIRST else 0,
                                        -_size(os.path.join(root, f)), f))


def take_shard(order, shard):
    """The files of slice (I, N) of `order`: every N-th from the I-th, so `order`'s big files at its head are spread over the slices.
    None is the whole list."""
    if shard is None:
        return list(order)
    i, n = shard
    return list(order)[i - 1::n]


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


def _size(path):
    """Bytes of a file; 0 for one the listing has and the disk no longer has: it still gets its FAIL line from running it."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except OSError:
        return False
    return True


def main(root, expect_values, jobs_values, label, shard_values=None):
    """Run the group whose folder is `root` (an absolute path; `label` is its path as the listing names it, for the SKIP line).
    The children get a TMPDIR outside any checkout (private_tmp)."""
    with private_tmp(clean_env()) as env:
        return run_group(root, expect_values, jobs_values, label, shard_values, env)


def run_group(root, expect_values, jobs_values, label, shard_values, env):
    expect, jobs, error = check(expect_values, jobs_values)
    if error:
        sys.stderr.write(error + "\n")
        return 2
    shard, error = parse_shard(shard_values)
    if error:
        sys.stderr.write(error + "\n")
        return 2
    jobs = jobs or default_jobs()
    if not os.path.isdir(root):
        # A checkout without the plugin: nothing to look at is a SKIP that says so, unless the caller named a test of it, which is
        # a declared path that is no test file.
        for rel in sorted(expect):
            sys.stderr.write("%s: --expect-not-run names %s, which is no tests/test_*.py file: there is no %s folder here\n"
                             % (NAME, rel, label))
        if expect:
            return 1
        print("SKIP  %-22s %sno %s folder here, so its tests were not looked at" % (label, NOT_RUN + ": ", label))
        return 0
    # The group's folder, not the repository's top level: the plugin is a folder of a bigger repository (forge's plugins/fwx), and the
    # top level's tests are not its own. `git ls-files` run there lists only that folder.
    try:
        if subprocess.run(["git", "-C", root, "rev-parse", "--git-dir"], env=env, capture_output=True).returncode:
            sys.stderr.write("%s: %s is not inside a git repository\n" % (NAME, root))
            return 1
        files = test_files(root, env)
    except (OSError, subprocess.CalledProcessError) as e:  # git missing, or a listing that failed: one line, never a green run
        sys.stderr.write("%s: git could not list the tests of %s: %s\n" % (NAME, root, e))
        return 1
    passed = failed = not_run = expected = 0
    failures = []  # (file, output) of each failed file, for the lines that end the run
    unknown = sorted(expect - set(files))
    for rel in unknown:
        sys.stderr.write("%s: --expect-not-run names %s, which is no tests/test_*.py file\n" % (NAME, rel))
    # the order the files start in (and are dealt to the slices in); the order they are printed in is `files`
    start = start_order(files, root)
    mine = set(take_shard(start, shard))
    if shard:
        print("shard %d/%d: %d of %d test file(s)" % (shard[0], shard[1], len(mine), len(files)))
        sys.stdout.flush()
        files = [f for f in files if f in mine]
        start = [f for f in start if f in mine]
    children = Children()
    pool = ThreadPoolExecutor(max_workers=jobs)

    def stop(signum, frame):
        raise Interrupted(signum)

    old = {s: signal.signal(s, stop) for s in STOP}  # before the first child starts: no window in which a signal leaves one running
    try:
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
                failures.append((rel, output))
            sys.stdout.flush()
    except Interrupted as e:
        for s in STOP:  # no second signal may cut the cleanup short
            signal.signal(s, signal.SIG_IGN)
        n = children.kill_all()
        pool.shutdown(wait=True, cancel_futures=True)
        sys.stderr.write("%s: interrupted by %s; ended %d running test file(s)\n" % (NAME, signal.Signals(e.signum).name, n))
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
    for line in failed_lines(failures):  # the last lines of the output: a tail of it names every failed file
        print(line)
    print("%d test file(s): %d passed, %d failed, %d not run%s"
          % (total, passed, failed, not_run, ", %d expected not run" % expected if expected else ""))
    # Everything declared away proves nothing, of a whole run. A slice has no such rule: it may hold only declared files (CI's two, dealt
    # together) while the other slices carry the passes; a slice that looked at nothing (total 0), failed or could not run still is 1 or 77.
    if failed or total == 0 or unknown or (expect and passed == 0 and not shard):
        return 1
    return 77 if not_run else 0
