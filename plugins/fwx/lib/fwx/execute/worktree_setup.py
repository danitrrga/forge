"""`fwx wave setup`: make a fresh worktree able to run the project's checks, by running `project.worktree_setup` in it.

A worktree is a checkout of the tracked files and nothing else: the project's installed dependencies (a `node_modules`, a
virtual environment) are not in it, so its own checks cannot run and every task would fail its gate for a reason that has
nothing to do with the task. `project.worktree_setup` is a list of shell commands (`["npm ci"]`); this module is the one place
that runs them, and `fwx wave setup`, `fwx wave check-base` (the first step of every executor) and `fwx wave prepare` (the phase
worktree, before its base runs) all call it, so that no agent has to remember it. It was chosen over a link to the main checkout's
dependencies (a task that changes the dependency file would write through the link into the main tree, and the link is an
untracked file that makes every clean-tree check refuse) and over a copy (hundreds of megabytes per worktree): a real install
is correct after a dependency change and shares nothing between concurrent tasks.

`run(cwd, commands, force=False, timeout=TIMEOUT_S, log_cap=LOG_CAP)` works in the linked worktree `cwd` is in (WaveError for the main checkout:
a command like `npm ci` there would replace the owner's own dependencies) and returns `{state, ran, log}`:
  none  no command is configured; nothing is touched
  noop  the marker says this worktree was set up against this list and these dependency files; nothing ran
  ran   every command ran, in order, each with a time limit of `timeout` seconds and an output limit of `log_cap` bytes
A command that fails, runs past either limit or leaves files behind raises SetupFailed, whose text is the one line a report quotes:
`worktree setup failed: <command> (exit N, log PATH)`. The commands after a failing one do not run, and no marker is written, so
the next call runs everything again. Another failure (the log or the marker cannot be written) is a WaveError, one line too.

At a limit the command's process group is killed, and so is every descendant found through the process table (`/proc`, Linux only):
a child that left the group with `setsid` while its parent, the shell, was still running is covered. What stays uncovered, because
nothing links it to the command any more: a descendant that detached and whose parent had already exited (init's now), anything a
command that exited by itself left running (a daemonising tool such as a build server is the project's own business), and, off
Linux, every child outside the process group.

The output of every command goes to `<worktree>/.fwx-agent/worktree-setup.log` (rewritten by each run; `base.agent_root` makes
the folder and its `.gitignore`, which hides the log and the marker from git), through a pipe this module drains, so that the log
holds about `log_cap` bytes at most for the whole run (LOG_CAP, 32 MiB; the lines this module adds itself are not counted): a
command that writes past it is killed and the setup fails. After the last command `git status --porcelain`
(not counting `.fwx/`) must show nothing: a file the setup left that git does not ignore (the project's `.gitignore` must cover
what its setup creates), or a tracked file it changed, would make every later clean-tree check refuse the worktree, so it is named
and refused here instead. That holds for a tree that was already dirty too: its checks would refuse it all the same.

The marker `<worktree>/.fwx-agent/worktree-setup.json` holds the command list, a digest of the files that define the
dependencies (the lockfiles and manifests of DEPENDENCY_FILES, wherever they are in the tree, as they are on disk, the tracked ones
and the untracked ones git does not ignore) and `made`, the git-ignored files and folders (`node_modules/`) that appeared during the
setup (a rerun keeps what the marker it replaces said was made and is still there; a run that failed forgets it): a changed list, a
changed or a new dependency file, or a folder of `made` that is gone runs the setup again, anything else is
a no-op, and `force` runs it regardless. What it does not see: a dependency file that is not in DEPENDENCY_FILES (a `.tool-versions`), a
folder that was already there before the setup (it is not in `made`), and a change to the dependency file made after the setup in a
worktree nobody calls this in again (an executor's own `npm install` is its own business). The phase worktree is covered: `prepare`
calls this once at the start of a run and `integrate` after the merges of every wave, before its checks, and `fwx wave setup` is
the call anywhere else.

Imports only the standard library and execute.base.
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time

from fwx.execute.base import AGENT_DIR, WaveError, agent_root, git, linked, toplevel

TIMEOUT_S = 15 * 60
LOG_CAP = 32 * 1024 * 1024
LOG = "worktree-setup.log"
MARKER = "worktree-setup.json"
# The files whose content says which dependencies the worktree needs. Names, not paths: each is looked for at any depth.
DEPENDENCY_FILES = ("package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb",
                    "pyproject.toml", "uv.lock", "poetry.lock", "Pipfile.lock", "requirements*.txt",
                    "Gemfile.lock", "Cargo.lock", "go.sum", "composer.lock", ".nvmrc", ".npmrc")


class SetupFailed(Exception):
    """The setup did not leave a worktree that can run its checks; the text is the reason, in one line (or, for left files,
    one line then the files)."""


def _dependency_digest(top):
    """A digest of the dependency files of the worktree, tracked or untracked and not ignored: their paths and their content on disk."""
    r = git(top, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *[":(glob)**/" + name for name in DEPENDENCY_FILES])
    if r.returncode:
        raise WaveError("git ls-files failed in %s: %s" % (top, r.stderr.strip()))
    h = hashlib.sha256()
    for rel in sorted({p for p in r.stdout.split("\0") if p}):
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


def _ignored(top):
    """The git-ignored files and folders of the worktree, a folder that is all ignored as one entry (`deps/`), not counting the
    folders of this tool and of `.fwx/`."""
    r = git(top, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory")
    if r.returncode:
        raise WaveError("git ls-files failed in %s: %s" % (top, r.stderr.strip()))
    return {p for p in r.stdout.split("\0") if p and p.split("/")[0] not in (AGENT_DIR, ".fwx")}


def _read_marker(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _valid(marker, fingerprint, top):
    """Whether the marker vouches for this worktree: the same list, the same dependency files, and what the setup made still there."""
    if not isinstance(marker, dict):
        return False
    made = marker.get("made", [])
    return (marker.get("commands") == fingerprint["commands"] and marker.get("dependencies") == fingerprint["dependencies"]
            and isinstance(made, list) and all(isinstance(m, str) and os.path.exists(os.path.join(top, m)) for m in made))


def _descendants(pid):
    """The pids below `pid` in the process table (Linux `/proc`; empty where there is none)."""
    kids = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return []
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % name, "rb") as f:
                ppid = int(f.read().rsplit(b")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(name))
    found, todo = [], [pid]
    while todo:
        for kid in kids.get(todo.pop(), ()):
            found.append(kid)
            todo.append(kid)
    return found


def _kill_tree(pid):
    """SIGKILL to the process group of the command and to every descendant the process table links to it, a child that left the
    group included (the descendants are listed before anything dies, while the links are there)."""
    below = _descendants(pid)
    for kill, target in [(os.killpg, pid)] + [(os.kill, p) for p in below]:
        try:
            kill(target, signal.SIGKILL)
        except OSError:
            pass


class _Pump(threading.Thread):
    """Copies the command's output from the pipe into the log, at most `cap` bytes of it, and says when there was more (it kills
    the command then). A child that kept the pipe open past the end of the command is let go of: `stop` ends the writing."""

    def __init__(self, src, log, cap, written, proc):
        super().__init__(daemon=True)
        self.src, self.log, self.cap, self.written, self.proc = src, log, cap, written, proc
        self.over = False
        self.lock = threading.Lock()
        self.stopped = False

    def run(self):
        try:
            while True:
                chunk = os.read(self.src, 1 << 16)
                if not chunk:
                    return
                with self.lock:
                    if self.stopped:
                        return
                    room = self.cap - self.written
                    if len(chunk) > room and not self.over:
                        self.over = True
                        _kill_tree(self.proc.pid)
                    if room > 0:
                        self.log.write(chunk[:room])
                        self.log.flush()
                        self.written += min(len(chunk), room)
        except (OSError, ValueError):
            return

    def stop(self):
        with self.lock:
            self.stopped = True


def _run_one(command, cwd, log, timeout, cap, written):
    """Run `command` with the shell in `cwd`, its output appended to the open file `log` (the log holds `written` bytes so far and
    never more than `cap`). Returns (why it failed or None when it exited 0, the bytes of the log). The command and everything it
    started live in one process group, which is killed at a limit and, as a last step, after a normal exit too; at a limit the
    descendants outside the group are killed too (`_kill_tree`)."""
    log.write(("$ %s\n" % command).encode("utf-8"))
    log.flush()
    try:
        proc = subprocess.Popen([shutil.which("bash") or "/bin/sh", "-c", command], cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        return "could not start: %s" % e, written
    pump = _Pump(proc.stdout.fileno(), log, cap, written + len(("$ %s\n" % command).encode("utf-8")), proc)
    pump.start()
    why = None
    try:
        rc = proc.wait(timeout=timeout)
        if rc:
            why = "exit %d" % rc
    except subprocess.TimeoutExpired:
        why = "timed out after %d s" % timeout
        _kill_tree(proc.pid)
    _kill_tree(proc.pid)
    proc.wait()
    pump.join(2)  # the pipe closes with the last process that holds it; a child that outlives the group is let go of
    pump.stop()
    proc.stdout.close()
    if pump.over:
        why = "output past %d bytes" % cap
    return why, pump.written


def run(cwd, commands, force=False, timeout=TIMEOUT_S, log_cap=LOG_CAP):
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
    if not force and _valid(_read_marker(marker_path), fingerprint, top):
        return {"state": "noop", "ran": 0, "log": log_path}
    old = _read_marker(marker_path)
    kept = [m for m in (old.get("made") if isinstance(old, dict) else None) or [] if isinstance(m, str)]
    try:
        os.remove(marker_path)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise WaveError("cannot remove %s: %s" % (marker_path, e))
    before = _ignored(top)
    try:
        with open(log_path, "wb") as log:
            written = 0
            for command in commands:
                started = time.monotonic()
                why, written = _run_one(command, top, log, timeout, log_cap, written)
                log.write(("# %.1f s\n" % (time.monotonic() - started)).encode("utf-8"))
                if why:
                    raise SetupFailed("worktree setup failed: %s (%s, log %s)" % (command, why, log_path))
    except OSError as e:
        raise WaveError("cannot write the log of the setup, %s: %s" % (log_path, e))
    left = sorted(_status(top))
    if left:
        raise SetupFailed("worktree setup failed: the worktree is not clean after the commands, which every clean-tree check would "
                          "refuse; what they create must be in the project's .gitignore (log %s):\n%s"
                          % (log_path, "\n".join("  " + line for line in left)))
    after = _ignored(top)
    try:
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(dict(fingerprint, made=sorted((after - before) | (set(kept) & after))), f)
            f.write("\n")
    except OSError as e:
        raise WaveError("cannot write the marker of the setup, %s: %s" % (marker_path, e))
    return {"state": "ran", "ran": len(commands), "log": log_path}


def summary(result):
    """The line that says what `run` did."""
    if result["state"] == "none":
        return "worktree setup: no worktree_setup configured"
    if result["state"] == "noop":
        return "worktree setup: already done for this worktree and its dependency files; `fwx wave setup --force` runs it again"
    n = result["ran"]
    return "worktree setup: %d command%s ran (log %s)" % (n, "" if n == 1 else "s", result["log"])
