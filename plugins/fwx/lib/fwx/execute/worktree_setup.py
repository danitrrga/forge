"""`fwx wave setup`: make a fresh worktree able to run the project's checks, by running `project.worktree_setup` in it.

A worktree is a checkout of the tracked files and nothing else: the project's installed dependencies (a `node_modules`, a
virtual environment) are not in it, so its own checks cannot run and every task would fail its gate for a reason that has
nothing to do with the task. `project.worktree_setup` is a list of shell commands (`["npm ci"]`); this module is the one place
that runs them, and `fwx wave setup`, `fwx wave check-base` (the first step of every executor) and `fwx wave prepare` (the phase
worktree, before its base runs) all call it, so that no agent has to remember it. It was chosen over a link to the main checkout's
dependencies (a task that changes the dependency file would write through the link into the main tree, and the link is an
untracked file that makes every clean-tree check refuse) and over a copy (hundreds of megabytes per worktree): a real install
is correct after a dependency change and shares nothing between concurrent tasks.

`run(cwd, commands, force=False, timeout=TIMEOUT_S)` works in the linked worktree `cwd` is in (WaveError for the main checkout:
a command like `npm ci` there would replace the owner's own dependencies) and returns `{state, ran, log}`:
  none  no command is configured; nothing is touched
  noop  the marker says this worktree was set up against this list and these dependency files; nothing ran
  ran   every command ran, in order, each with a time limit of `timeout` seconds and its whole process group killed at the limit
A command that fails, runs past the limit or leaves files behind raises SetupFailed, whose text is the one line a report quotes:
`worktree setup failed: <command> (exit N, log PATH)`. The commands after a failing one do not run, and no marker is written, so
the next call runs everything again.

The output of every command goes to `<worktree>/.fwx-agent/worktree-setup.log` (rewritten by each run; `base.agent_root` makes
the folder and its `.gitignore`, which hides the log and the marker from git). After the last command `git status --porcelain`
(not counting `.fwx/`) must show nothing: a file the setup left that git does not ignore (the project's `.gitignore` must cover
what its setup creates), or a tracked file it changed, would make every later clean-tree check refuse the worktree, so it is named
and refused here instead. That holds for a tree that was already dirty too: its checks would refuse it all the same.

The marker `<worktree>/.fwx-agent/worktree-setup.json` holds the command list and a digest of the files that define the
dependencies (the lockfiles and manifests of DEPENDENCY_FILES, wherever they are in the tree, as they are on disk): a changed list
or a changed lockfile runs the setup again, anything else is a no-op, and `force` runs it regardless. What it does not see: a
dependency file that is not in DEPENDENCY_FILES, and a change to the dependency file made after the setup in a worktree nobody
calls this in again (an executor's own `npm install` is its own business; the phase worktree is covered because `prepare` calls
this at the start of every wave and `fwx wave setup` is the call after a merge that changed one).

Imports only the standard library and execute.base.
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time

from fwx.execute.base import WaveError, agent_root, git, linked, toplevel

TIMEOUT_S = 15 * 60
LOG = "worktree-setup.log"
MARKER = "worktree-setup.json"
# The files whose content says which dependencies the worktree needs. Names, not paths: each is looked for at any depth.
DEPENDENCY_FILES = ("package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb",
                    "pyproject.toml", "uv.lock", "poetry.lock", "Pipfile.lock", "requirements*.txt",
                    "Gemfile.lock", "Cargo.lock", "go.sum", "composer.lock")


class SetupFailed(Exception):
    """The setup did not leave a worktree that can run its checks; the text is the reason, in one line (or, for left files,
    one line then the files)."""


def _dependency_digest(top):
    """A digest of the dependency files of the worktree: their paths and their content on disk."""
    r = git(top, "ls-files", "-z", "--", *[":(glob)**/" + name for name in DEPENDENCY_FILES])
    h = hashlib.sha256()
    for rel in sorted(p for p in r.stdout.split("\0") if p):
        h.update(rel.encode("utf-8") + b"\0")
        try:
            with open(os.path.join(top, rel), "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


def _status(top):
    """The lines of `git status --porcelain` with every untracked file listed by itself, not counting `.fwx/` (the documents the
    clean-tree checks do not count either, core.verify.is_dirty)."""
    r = git(top, "status", "--porcelain", "-uall", "--", ".", ":(exclude).fwx")
    if r.returncode:
        raise WaveError("git status failed in %s: %s" % (top, r.stderr.strip()))
    return {line for line in r.stdout.splitlines() if line.strip()}


def _read_marker(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _run_one(command, cwd, log, timeout):
    """Run `command` with the shell in `cwd`, its output appended to the open file `log`. Returns why it failed, or None when it
    exited 0. The command and everything it started live in one process group, which is killed at the limit and, as a last step,
    after a normal exit too: a setup leaves no process behind."""
    log.write(("$ %s\n" % command).encode("utf-8"))
    log.flush()
    try:
        proc = subprocess.Popen([shutil.which("bash") or "/bin/sh", "-c", command], cwd=cwd, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        return "could not start: %s" % e
    why = None
    try:
        rc = proc.wait(timeout=timeout)
        if rc:
            why = "exit %d" % rc
    except subprocess.TimeoutExpired:
        why = "timed out after %d s" % timeout
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    proc.wait()
    return why


def run(cwd, commands, force=False, timeout=TIMEOUT_S):
    top = toplevel(cwd)
    if top is None:
        raise WaveError("not inside a git repository: %s" % cwd)
    if not commands:
        return {"state": "none", "ran": 0, "log": None}
    if not linked(top):
        raise WaveError("worktree setup runs only in a linked worktree, and %s is the main checkout" % top)
    try:
        root = agent_root(top)
    except OSError as e:
        raise WaveError("cannot make the .fwx-agent folder of %s: %s" % (top, e))
    log_path, marker_path = os.path.join(root, LOG), os.path.join(root, MARKER)
    fingerprint = {"commands": list(commands), "dependencies": _dependency_digest(top)}
    if not force and _read_marker(marker_path) == fingerprint:
        return {"state": "noop", "ran": 0, "log": log_path}
    try:
        os.remove(marker_path)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise WaveError("cannot remove %s: %s" % (marker_path, e))
    with open(log_path, "wb") as log:
        for command in commands:
            started = time.monotonic()
            why = _run_one(command, top, log, timeout)
            log.write(("# %.1f s\n" % (time.monotonic() - started)).encode("utf-8"))
            if why:
                raise SetupFailed("worktree setup failed: %s (%s, log %s)" % (command, why, log_path))
    left = sorted(_status(top))
    if left:
        raise SetupFailed("worktree setup failed: the worktree is not clean after the commands, which every clean-tree check would "
                          "refuse; what they create must be in the project's .gitignore (log %s):\n%s"
                          % (log_path, "\n".join("  " + line for line in left)))
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(fingerprint, f)
        f.write("\n")
    return {"state": "ran", "ran": len(commands), "log": log_path}


def summary(result):
    """The line that says what `run` did."""
    if result["state"] == "none":
        return "worktree setup: no worktree_setup configured"
    if result["state"] == "noop":
        return "worktree setup: already done for this worktree and its dependency files; `fwx wave setup --force` runs it again"
    n = result["ran"]
    return "worktree setup: %d command%s ran (log %s)" % (n, "" if n == 1 else "s", result["log"])
