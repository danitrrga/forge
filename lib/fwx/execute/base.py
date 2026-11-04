"""Where a checkout stands: git, and `check-base`, step 0 of every agent that writes.

`check_base(sha, cwd, worktree)` says whether the directory is a linked worktree whose HEAD is exactly `sha`: an agent
that starts from the default branch, from a moved phase branch or in the main checkout (a Bash call from an isolated agent
can write there, so one writer per worktree is not assumed) must stop before it touches anything. It compares the HEAD,
never the merge-base: a worktree that is ahead of the base is not on it. `sha` is 7 to 40 hex digits, never a name that
git resolves (`HEAD` would always match).

Imports only the standard library.
"""
import os
import re
import subprocess

WRONG_BASE = 42  # the exit of check-base for "do not start"
SHA = re.compile(r"[0-9a-f]{7,40}\Z")


class WaveError(Exception):
    """Something `wave` cannot work with: the command prints it and exits 2, having written nothing."""


def git(cwd, *args, input=None):
    try:
        return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, input=input)
    except OSError as e:
        raise WaveError("cannot run git (%s)" % e)


def out(cwd, *args):
    """Stdout of a git call, stripped; None when it failed."""
    r = git(cwd, *args)
    return r.stdout.strip() if r.returncode == 0 else None


def toplevel(cwd):
    """The working tree `cwd` is in, or None outside a repository."""
    return out(cwd, "rev-parse", "--show-toplevel")


def linked(top):
    """Whether `top` is a linked worktree: its git dir is not the common one."""
    gitdir = out(top, "rev-parse", "--path-format=absolute", "--git-dir")
    common = out(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return bool(gitdir and common) and os.path.realpath(gitdir) != os.path.realpath(common)


def check_base(sha, cwd, worktree=None):
    """(0, "") when `cwd` is a linked worktree (that is `worktree`, when given) with HEAD `sha`; else (42, why)."""
    top = toplevel(cwd)
    if top is None:
        return WRONG_BASE, "not a linked worktree: %s" % cwd
    if not linked(top):
        return WRONG_BASE, "not a linked worktree: %s" % top
    if worktree is not None and os.path.realpath(worktree) != os.path.realpath(top):
        return WRONG_BASE, "wrong worktree: %s, expected %s" % (top, worktree)
    head = out(top, "rev-parse", "HEAD") or ""
    if not head.startswith(sha):
        return WRONG_BASE, "wrong base: HEAD %s, expected %s" % (head or "none", sha)
    return 0, ""
