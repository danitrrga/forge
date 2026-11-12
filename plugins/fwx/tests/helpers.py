"""What the tests share: git that ignores the machine's settings and the caller's GIT_* variables,
toy repos and worktrees, temp dirs that do not outlive the run, pass or fail, and `Suite`, which counts
what a test looked at.

copied-from: forge tests/sandbox.py @2c95776, adapted (git(), mkdtemp(), cleanup(); the rest is new)

The name does not match test_*.py, so `fwx test` never runs it; the tests import it.
"""
import atexit
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
_made = []


def clean_env(**extra):
    """This process's environment without GIT_* (a hook or a test run inside a repo exports GIT_DIR
    and GIT_INDEX_FILE, which would send a toy repo's commit into that repo) plus the two variables
    that turn off the user's and the system's git configuration. `extra` goes on top."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(GIT_ENV)
    e.update(extra)
    return e


def git(cwd, *args):
    """git in cwd with no user or system config, no hooks and no signing, and no automatic
    maintenance (a background repack can write into a directory while it is being removed).
    Returns stdout; a failure raises with git's stderr."""
    r = subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t",
                        "-c", "init.defaultBranch=master", "-c", "core.hooksPath=/dev/null",
                        "-c", "commit.gpgsign=false", "-c", "maintenance.auto=false", "-c", "gc.auto=0"]
                       + list(args), env=clean_env(), capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("git %s failed (%d): %s" % (" ".join(args), r.returncode, r.stderr.strip()))
    return r.stdout


_ports = []  # the reservations of this process, held until it ends
PORT_LOW, PORT_HIGH = 12000, 32000  # below Linux's ephemeral range (32768 and up): outgoing connections and `bind(0)` never land here


def free_port():
    """A local TCP port that nothing listens on and that no other process of the test run is given. The port is picked at random
    below the ephemeral range and claimed under a name in the abstract Unix socket namespace (kernel-wide, no file, released when
    this process ends), so two test files running at once never receive the same one; the claim is held for the life of the
    process, the port itself is closed again for the caller to bind. Without abstract sockets (not Linux) it is `bind(0)`."""
    for _ in range(500):
        port = random.randint(PORT_LOW, PORT_HIGH)
        claim = socket.socket(socket.AF_UNIX)
        try:
            claim.bind("\0fwx-test-port-%d" % port)
        except OSError:
            claim.close()
            continue
        except (AttributeError, ValueError):
            claim.close()
            break
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            claim.close()  # something outside the test run has it: not ours to give
            continue
        finally:
            probe.close()
        _ports.append(claim)
        return port
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


KEEP_ENV = "FWX_TEST_KEEP"


def keeping():
    """Whether the run was asked to keep its temp dirs for a look: FWX_TEST_KEEP=1 in the environment. Off by default:
    /tmp is RAM on this machine, so a failing run must not leave its toy repos there."""
    return os.environ.get(KEEP_ENV) == "1"


def mkdtemp(prefix):
    """A temp dir removed when the process ends however it ends (cleanup(), a failing check, an uncaught exception,
    sys.exit, SIGTERM), unless FWX_TEST_KEEP=1. SIGKILL and os._exit skip it."""
    d = os.path.realpath(tempfile.mkdtemp(prefix=prefix))
    _made.append(d)
    return d


def rmtree(d):
    """shutil.rmtree that also removes a tree holding a directory without write permission."""
    def writable(func, p, exc):
        try:
            os.chmod(os.path.dirname(p), 0o700)
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(d, onexc=lambda func, p, exc: writable(func, p, exc))
    else:
        shutil.rmtree(d, onerror=writable)


def remove(d):
    """Remove one dir mkdtemp made now, for a test that makes many (the peak in /tmp is what fills the RAM); kept with
    FWX_TEST_KEEP=1."""
    if not keeping():
        rmtree(d)
        if d in _made:
            _made.remove(d)


def cleanup(failed=False, label="kept:"):
    """Remove every dir mkdtemp made so far. With FWX_TEST_KEEP=1 they are printed instead, so they can be looked at.
    `failed` is accepted for the callers that pass it and changes nothing: a failing run cleans too."""
    if keeping():
        if _made:
            print(label, " ".join(_made))
    else:
        for d in _made:
            rmtree(d)
    del _made[:]


@atexit.register
def _unfinished():  # a test that crashed or exited before cleanup()
    if _made:
        cleanup(True, "kept (the run did not finish):")


def _on_sigterm(signum, frame):
    sys.exit(128 + signum)  # a SystemExit, so atexit runs: a timeout's `kill` must not leave the toy repos behind


if signal.getsignal(signal.SIGTERM) == signal.SIG_DFL:
    signal.signal(signal.SIGTERM, _on_sigterm)


def write(root, rel, text, mode=None):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    if mode:
        os.chmod(p, mode)
    return p


def toy_repo(files=None):
    """A new repo on master with one commit holding `files` ({path: text}, default one README)."""
    repo = mkdtemp("fwx-toy-")
    git(repo, "init", "-q", "-b", "master")
    for rel, text in (files or {"README": "toy\n"}).items():
        write(repo, rel, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "toy")
    return repo


def add_worktree(repo, name):
    """A linked worktree of `repo` on a new branch `name`, in its own temp dir."""
    wt = os.path.join(mkdtemp("fwx-wt-"), name)
    git(repo, "worktree", "add", "-q", "-b", name, wt)
    return os.path.realpath(wt)


def fwx(cwd, *args, input=None, env=None):
    """This repo's bin/fwx run in cwd with clean_env(**env). The CompletedProcess, whatever its exit."""
    return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx")] + list(args), cwd=cwd,
                          env=clean_env(**(env or {})), input=input, capture_output=True, text=True)


class Found(BaseException):
    """Raised by FirstFail to end a control run at the FAIL it was waiting for. A BaseException, so that a case's own
    `except Exception` does not swallow it; its `finally` blocks still run."""


class FirstFail:
    """The Suite of a control run (a mutant), which has to show one thing: a FAIL that `want` accepts. At the first such FAIL it
    raises Found, because the rest of the case would only add FAILs the control never reads. Same interface as Suite where
    cases use it (ok, eq, not_run); `fails` holds every FAIL up to and including the matching one and `checks` what ran.
    `want` is a function of one FAIL line. Use `run(case, *args)`: it catches Found and says whether the match was seen."""

    def __init__(self, want):
        self.want = want
        self.checks = 0
        self.fails = []
        self.seen = False

    def ok(self, label, cond, detail=""):
        self.checks += 1
        if not cond:
            self.fails.append("FAIL: %s%s" % (label, (": " + detail) if detail else ""))
            if self.want(self.fails[-1]):
                self.seen = True
                raise Found()
        return bool(cond)

    def eq(self, label, got, want):
        return self.ok(label, got == want, "got %r, want %r" % (got, want))

    def run(self, case, *args):
        try:
            case(*args)
        except Found:
            pass
        return self.seen


class Suite:
    """Counts what a test looked at. done() prints the FAIL lines and `N checks`, and exits 1 on a
    failure or on zero checks (a test that looked at nothing proves nothing)."""

    def __init__(self):
        self.checks = 0
        self.fails = []

    def ok(self, label, cond, detail=""):
        self.checks += 1
        if not cond:
            self.fails.append("FAIL: %s%s" % (label, (": " + detail) if detail else ""))
        return bool(cond)

    def eq(self, label, got, want):
        return self.ok(label, got == want, "got %r, want %r" % (got, want))

    def not_run(self, reason):
        """The test cannot run here: neither pass nor fail, exit 77."""
        cleanup(False)
        print("NOT RUN, NOT ARMED: %s" % reason)
        sys.exit(77)

    def done(self):
        if self.checks == 0:
            self.fails.append("FAIL: no check ran")
        for line in self.fails:
            print(line)
        print("%d checks" % self.checks)
        cleanup(bool(self.fails))
        sys.exit(1 if self.fails else 0)
