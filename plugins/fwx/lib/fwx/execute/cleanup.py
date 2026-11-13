"""Which worktrees a run owns, whether an agent still lives in one, and `fwx wave remove` (3.4 U3; shape in C.2 of the plan).

Liveness is not `locked`. Claude Code locks the worktree of an agent with the reason `claude agent <id> (pid P start T)`, where
`P` is the `claude` process and `T` is field 22 of `/proc/P/stat`; `kill -9` leaves the lock behind (research/execute-measures.md,
measured), and a pid can be reused. So `lock_state` is `live` only when `/proc/P/stat` exists and its start time is `T`; `stale`
when the pid is gone or has another start time; `unknown` for a lock whose reason is not that form (it is never taken for
stale: it cannot be shown dead); `none` for an unlocked worktree. Without `/proc` nothing can be said: NoProc.

A worktree belongs to run `R` when a commit on its branch that the base does not have carries `Fwx-Run: R`, or when an
`integrate` call of the run named its branch (`recorded`). The base is the sha in the run id (`<part>-<sha7>-<n>`).

`cleanup(cwd, run, recorded)` removes what is safe and says why for the rest: an unlocked, clean worktree whose branch is merged
into the checkout's branch goes (`git worktree remove`, never `--force`, then `git branch -d`); a live one, a dirty one, one with
commits that are not merged and one whose lock could not be cleared stay, in `kept` with the reason. A stale lock is cleared
(`git worktree unlock`) and then the worktree is treated like any other. `leftover` lists the processes whose current directory
is inside a worktree of the run (a runaway shell of an agent was the largest thing left running); none is killed. The phase
branch, the main checkout and a worktree of another run are never candidates.

The folder `fwx scratch new <run> <unit>` makes in the checkout (`<top>/.fwx-agent/<run>/`, where the reviewers, which have no
worktree of their own, write) is removed with the run's worktrees: it is git-ignored, so nothing else would ever clear it. The
folders of other runs and the ignore file stay; `scratch` in the result lists what was removed.

Imports the standard library and execute.base.
"""
import os
import re
import shutil

from fwx.execute.base import AGENT_DIR, WaveError, git, out

PROC = "/proc"
_LOCK = re.compile(r"\(pid (\d+) start (\d+)\)\s*\Z")
_RUN = re.compile(r"-([0-9a-f]{7,40})-\d+\Z")


class NoProc(WaveError):
    """No /proc: liveness cannot be told. The command prints NOT RUN, NOT ARMED and exits 77."""


def base_of(top, run):
    """The commit named by the sha in the run id."""
    m = _RUN.search(run)
    sha = m and out(top, "rev-parse", "--verify", "--quiet", m.group(1) + "^{commit}")
    if not sha:
        raise WaveError("run %r does not end in -<sha>-<n> of a commit of this repository" % run)
    return sha


def worktrees(top):
    """Every worktree of the repository: [{path, branch (short name or None), locked (None, or the reason, possibly '')}]; the
    first is the main checkout."""
    r = git(top, "worktree", "list", "--porcelain", "-z")
    if r.returncode:
        raise WaveError("git worktree list failed in %s: %s" % (top, r.stderr.strip()))
    found, cur = [], None
    for field in r.stdout.split("\0"):
        if not field:
            cur = None
            continue
        key, _, value = field.partition(" ")
        if key == "worktree":
            cur = {"path": os.path.realpath(value), "branch": None, "locked": None}
            found.append(cur)
        elif cur is not None and key == "branch":
            cur["branch"] = value[len("refs/heads/"):] if value.startswith("refs/heads/") else value
        elif cur is not None and key == "locked":
            cur["locked"] = value
    return found


def _need_proc():
    if not os.path.isdir(PROC):
        raise NoProc("NOT RUN, NOT ARMED: no /proc")


def alive(pid, start):
    """Whether process `pid` runs with the start time `start` (field 22 of its stat)."""
    _need_proc()
    try:
        with open(os.path.join(PROC, str(pid), "stat"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return False
    fields = text.rsplit(")", 1)[-1].split()  # the name holds spaces and parentheses: count from its end
    return len(fields) > 19 and fields[19] == str(start)


def lock_state(wt):
    """`none`, `live`, `stale` or `unknown` (see the module text) for a worktree of `worktrees`."""
    if wt["locked"] is None:
        return "none"
    m = _LOCK.search(wt["locked"])
    if not m:
        return "unknown"
    pid, start = int(m.group(1)), m.group(2)
    return "live" if alive(pid, start) else "stale"


def pid_of(wt):
    m = _LOCK.search(wt["locked"] or "")
    return int(m.group(1)) if m else None


def _owned(top, base, branch):
    r = git(top, "log", "%s..refs/heads/%s" % (base, branch), "--format=%(trailers:key=Fwx-Run,valueonly)")
    return {line.strip() for line in r.stdout.splitlines() if line.strip()} if r.returncode == 0 else set()


def of_run(top, base, run, branch, recorded):
    """Whether the branch belongs to the run."""
    owned = run in _owned(top, base, branch)
    return bool(owned) or branch in recorded


def dirty(wt_path):
    r = git(wt_path, "status", "--porcelain")
    return r.returncode != 0 or bool(r.stdout.strip())


def merged(top, branch):
    """Whether the branch is an ancestor of the checkout's HEAD."""
    return git(top, "merge-base", "--is-ancestor", "refs/heads/" + branch, "HEAD").returncode == 0


def remove(top, wt):
    """Remove an unlocked, clean, merged worktree and its branch: None when it is gone, else why it stayed. Never forces."""
    if dirty(wt["path"]):
        return "dirty: uncommitted or untracked files"
    if wt["branch"] and not merged(top, wt["branch"]):
        return "unmerged commits on %s" % wt["branch"]
    r = git(top, "worktree", "remove", wt["path"])
    if r.returncode:
        return "git worktree remove refused: %s" % r.stderr.strip()
    if wt["branch"]:
        r = git(top, "branch", "-d", wt["branch"])
        if r.returncode:
            return "worktree removed, branch kept: %s" % r.stderr.strip()
    return None


def leftover(paths):
    """The processes whose current directory is inside one of `paths`: [{pid, cwd, worktree, cmd}]."""
    _need_proc()
    found = []
    for name in sorted(os.listdir(PROC), key=lambda n: (not n.isdigit(), int(n) if n.isdigit() else 0)):
        if not name.isdigit() or int(name) == os.getpid():
            continue
        try:
            cwd = os.readlink(os.path.join(PROC, name, "cwd"))
        except OSError:
            continue
        cwd = cwd[:-len(" (deleted)")] if cwd.endswith(" (deleted)") else cwd
        for p in paths:
            if cwd == p or cwd.startswith(p + os.sep):
                try:
                    with open(os.path.join(PROC, name, "cmdline"), "rb") as f:
                        cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
                except OSError:
                    cmd = ""
                found.append({"pid": int(name), "cwd": cwd, "worktree": p, "cmd": cmd[:200]})
                break
    return found


def _scratch(top, run):
    """Remove `<top>/.fwx-agent/<run>`; the list of the folders removed (empty when there was none or it could not go)."""
    folder = os.path.join(top, AGENT_DIR, run)
    if not os.path.isdir(folder):
        return []
    shutil.rmtree(folder, ignore_errors=True)
    root = os.path.dirname(folder)
    try:
        if os.listdir(root) == [".gitignore"]:  # no other run's folder: leave nothing behind
            os.remove(os.path.join(root, ".gitignore"))
            os.rmdir(root)
    except OSError:
        pass
    return [] if os.path.exists(folder) else [folder]


def cleanup(cwd, run, recorded=()):
    """`{removed, kept, leftover, scratch}` for the run's worktrees, from the checkout `cwd` is in (on the phase branch)."""
    _need_proc()
    top = out(cwd, "rev-parse", "--show-toplevel")
    if top is None:
        raise WaveError("not inside a git repository: %s" % cwd)
    top = os.path.realpath(top)
    phase = out(top, "symbolic-ref", "--short", "-q", "HEAD")
    if phase is None:
        raise WaveError("the checkout %s is on no branch: cleanup runs from the phase branch's checkout" % top)
    base = base_of(top, run)
    every = worktrees(top)
    mine = [w for w in every[1:] if w["path"] != top and w["branch"] and w["branch"] != phase
            and of_run(top, base, run, w["branch"], set(recorded))]
    scratch = _scratch(top, run)
    result = {"removed": [], "kept": [], "leftover": leftover([w["path"] for w in mine]), "scratch": scratch}
    for w in mine:
        item = {"worktree": w["path"], "branch": w["branch"]}
        state, was_stale = lock_state(w), False
        if state == "live":
            result["kept"].append(dict(item, why="live agent (pid %s)" % pid_of(w)))
            continue
        if state == "unknown":
            result["kept"].append(dict(item, why="locked, and the lock does not name a process (%s)" % w["locked"]))
            continue
        if state == "stale":
            r = git(top, "worktree", "unlock", w["path"])
            if r.returncode:
                result["kept"].append(dict(item, why="stale lock, could not unlock: %s" % r.stderr.strip()))
                continue
            was_stale = True
        why = remove(top, w)
        if why is None:
            result["removed"].append(item)
        else:
            result["kept"].append(dict(item, why=("stale lock cleared; " if was_stale else "") + why))
    return result
