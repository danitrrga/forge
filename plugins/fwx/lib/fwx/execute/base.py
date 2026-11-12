"""Where a checkout stands: git, and `check-base`, step 0 of every agent that writes.

`check_base(sha, cwd, worktree)` says whether the directory is a linked worktree whose HEAD is exactly `sha`: an agent
that starts from the default branch, from a moved phase branch or in the main checkout (a Bash call from an isolated agent
can write there, so one writer per worktree is not assumed) must stop before it touches anything. It compares the HEAD,
never the merge-base: a worktree that is ahead of the base is not on it. `sha` is 7 to 40 hex digits, never a name that
git resolves (`HEAD` would always match).

`scratch(cwd, run, unit)` makes the folder where an agent writes its report and its TMPDIR: `<worktree>/.fwx-agent/<run>/<unit>/`
(and its `tmp/`), inside the worktree the agent starts in, with a `.gitignore` of `*` beside it so that git sees none of it, the
`.gitignore` included. Nothing is written under `.git`: Claude Code asks permission for it as a sensitive path under
`acceptEdits`, and refuses an isolated agent's write outside its worktree. The ignore file is written once and never rewritten.

Imports only the standard library.
"""
import os
import re
import subprocess

WRONG_BASE = 42  # the exit of check-base for "do not start"
SETUP_FAILED = 43  # the exit of check-base when the base is right but the worktree's setup failed: do not start either
SHA = re.compile(r"[0-9a-f]{7,40}\Z")
AGENT_DIR = ".fwx-agent"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")  # a run or a unit: one folder name, never a path


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


def agent_root(top):
    """`<worktree>/.fwx-agent`, made, with its `.gitignore` of `*` (written once, never rewritten): what an agent or the worktree's
    setup keeps in the worktree, and git sees none of it, the `.gitignore` included. OSError when it cannot be made, or when it is a link."""
    root = os.path.join(os.path.realpath(top), AGENT_DIR)
    if os.path.islink(root):  # a tracked link merged from a branch: nothing is written through it
        raise OSError("%s is a symbolic link" % root)
    os.makedirs(root, exist_ok=True)
    ignore = os.path.join(root, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as f:
            f.write("*\n")
    return root


def scratch(cwd, run, unit):
    """The folder `<worktree>/.fwx-agent/<run>/<unit>` (made, with its `tmp/`) of the worktree `cwd` is in."""
    for what, name in (("run", run), ("unit", unit)):
        if not NAME.match(name):
            raise WaveError("the %s %r cannot name a folder" % (what, name))
    top = toplevel(cwd)
    if top is None:
        raise WaveError("not inside a git repository: %s" % cwd)
    folder = os.path.join(os.path.realpath(top), AGENT_DIR, run, unit)
    try:
        agent_root(top)
        os.makedirs(os.path.join(folder, "tmp"), exist_ok=True)
    except OSError as e:
        raise WaveError("cannot make %s: %s" % (folder, e))
    return folder
