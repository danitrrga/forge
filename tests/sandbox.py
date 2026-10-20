"""What the tests that build their own world share: a copy of this checkout or a few of its
files, a toy HOME's pieces, an empty network namespace, and temp dirs that do not outlive a
passing run. Each helper is the strongest of the copies the suites used to carry.

The name does not match `*test_*.py`, so `forge test` never runs it; the suites import it.
A suite under skills/ is also reached through the ~/.claude/skills links, so it finds this file
through a realpath-derived root, never an abspath one (that would be ~/.claude)."""
import atexit
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

FORGE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# In a forge worktree both are untracked links to master's real secrets and memory stores.
NEVER_COPY = {"credentials", "data"}
# Skipped by default for speed, not safety: design/ is 57 MB of the checkout's 61 (354 tracked
# files), and no code these suites run reads it -- grepped, the only mentions are
# comments and sync_skill_keep.py's permission strings, which name the real path. It cost each
# fixture sandbox ~6 s of `git add -A` and test_write_guard 6.9 of its 13.3 s in manifests.
# forge/cli.py's CHECKS runs scripts/design/design.py doctor, so a suite that starts running
# `forge doctor` or scripts/design/* must pass skip=() or drop the name from here.
ASSETS = {"design"}
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
UNSHARE = ("unshare", "-rn")
# Run inside the namespace under test, with the port of a listener the parent holds on the host's loopback:
# an empty network namespace cannot reach it, the host's own can.
PROBE = ("import socket, sys\ntry:\n    socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=0.2)\n"
         "    print('reachable')\nexcept OSError:\n    print('unreachable')")
_made = []


def git(cwd, *args):
    """git in cwd with no user or system config, no hooks and no signing: the user's own
    settings (status.renames, core.quotePath, a hooks template) must not decide what a test sees.
    No automatic maintenance either: git 2.55 repacks a commit of ~1000 loose objects (a sandbox's
    whole checkout) in a detached background process, which wrote .git/info/refs and
    .git/objects/info/packs into a sandbox while rmtree was deleting it -- test_sync_fixture failed
    one run in three with "OSError: [Errno 39] Directory not empty: .../forge/.git"."""
    return subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t",
                           "-c", "init.defaultBranch=master", "-c", "core.hooksPath=/dev/null",
                           "-c", "commit.gpgsign=false", "-c", "maintenance.auto=false",
                           "-c", "gc.auto=0"] + list(args),
                          env=dict(os.environ, **GIT_ENV), capture_output=True, text=True, check=True).stdout


def mkdtemp(prefix):
    """A temp dir that cleanup() removes after a passing run, or keeps and names after a failing one.
    Until a fix test_rotate_secret.py left 14 per run and test_security_audit.py 13, never
    removed: one day /tmp held 642 rotate-test-* dirs, each a partial forge checkout."""
    d = os.path.realpath(tempfile.mkdtemp(prefix=prefix))
    _made.append(d)
    return d


def cleanup(failed, label="kept:"):
    """Remove every mkdtemp() dir, or, when the run failed, print them so they can be looked at.
    A dir the test made read-only is its own to restore first."""
    if failed:
        if _made:
            print(label, " ".join(_made))
    else:
        for d in _made:
            shutil.rmtree(d)
    del _made[:]


@atexit.register
def _unfinished():  # a suite that crashed before cleanup(): kept, and said so
    if _made:
        print("kept (the run did not finish):", " ".join(_made))


def bare_env(home, tmp, bin_dir=None, **extra):
    """An environment built from nothing: no CLAUDE_PROJECT_DIR, which scopes every generator to
    one project, and no DBUS_SESSION_BUS_ADDRESS or XDG_RUNTIME_DIR, since a network namespace
    does not stop a unix socket to the real bus. `bin_dir` (stub_systemctl's) goes first on PATH."""
    path = os.environ.get("PATH", "/usr/bin:/bin")
    e = {"HOME": home, "PATH": bin_dir + os.pathsep + path if bin_dir else path,
         "LANG": "C.UTF-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": tmp}
    e.update(GIT_ENV)
    e.update(extra)
    return e


def stub_systemctl(bin_dir, log):
    """A systemctl that only appends its argv to `log`: forge asks `systemctl --user` about the Hindsight
    unit, and the real one would answer for this machine's session, not the toy world's."""
    os.makedirs(bin_dir, exist_ok=True)
    p = os.path.join(bin_dir, "systemctl")
    with open(p, "w") as f:
        f.write('#!/bin/sh\necho "$@" >> %s\n' % log)
    os.chmod(p, 0o755)
    return bin_dir


def unshare_ok(ns=UNSHARE):
    """(whether `ns` gives an empty network namespace, what the probe said). It proves a loopback
    listener the host holds unreachable from inside, not merely that unshare ran."""
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            r = subprocess.run(list(ns) + [sys.executable, "-c", PROBE, str(listener.getsockname()[1])],
                               capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.stdout.strip() == "unreachable", (r.stdout + r.stderr).strip()


def mini_root(root, *scripts):
    """A toy checkout at root: forge/__init__.py and forge/lib.py (every writer's guard) and each
    of `scripts`, a path relative to this checkout, at the same path."""
    for rel in [os.path.join("forge", "__init__.py"), os.path.join("forge", "lib.py")] + list(scripts):
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        shutil.copy(os.path.join(FORGE, rel), os.path.join(root, rel))
    return root


def _copy_files(rels, dst, left_out):
    """Each of `rels` (paths under this checkout) into dst, less the top-level directories in
    `left_out`. A link that resolves outside the checkout is refused, not dropped: copied, it
    would reach the real file from inside the sandbox, and dropped, the copy would silently differ."""
    for rel in dict.fromkeys(rels):
        src, out = os.path.join(FORGE, rel), os.path.join(dst, rel)
        if rel.split("/")[0] in left_out or not os.path.lexists(src):
            continue  # not lexists: deleted on disk, not yet in git
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if os.path.islink(src):
            if not os.path.realpath(src).startswith(FORGE + os.sep):
                sys.exit("refusing to copy %s: it links outside the checkout" % rel)
            os.symlink(os.readlink(src), out)
        else:
            shutil.copy2(src, out)


DATA_GIT = ".forge-data.git"


def histories():
    """The git argv prefix of each history that owns this checkout's files: `.git`, and after the
    split (docs/portable-design.md section 11) `.forge-data.git` over the same work tree. Before the
    split there is one. A prefix goes before the subcommand."""
    out = [["-C", FORGE]]
    if os.path.isdir(os.path.join(FORGE, DATA_GIT)):
        out.append(["--git-dir", os.path.join(FORGE, DATA_GIT), "--work-tree", FORGE])
    return out


def data_history():
    """The prefix of the history that holds the private files (repo-kit, skills, config, ...): the
    data history after the split, the one `.git` before it."""
    return histories()[-1]


def ls_files(*args):
    """`git ls-files -z *args` over every history, as one sorted list of paths: before the split
    the one `.git`, after it `.git` and `.forge-data.git`, so a copy built from this list holds the
    private files too. A path both list (none does) comes out once."""
    out = set()
    for h in histories():
        r = subprocess.run(["git"] + h + ["ls-files", "-z"] + list(args),
                           env=dict(os.environ, **GIT_ENV), capture_output=True, text=True, check=True)
        out.update(f for f in r.stdout.split("\0") if f and f.split("/")[0] not in (".git", DATA_GIT))
    return sorted(out)


def copy_checkout(dst, untracked=True, skip=ASSETS):
    """This checkout as it is on disk into dst: the tracked files of every history (ls_files), plus
    with `untracked` the ones git does not ignore (uncommitted work), less the top-level directories
    in `skip`. credentials/ and data/ are never copied."""
    files = ls_files("--cached", *(["--others", "--exclude-standard"] if untracked else []))
    _copy_files(files, dst, NEVER_COPY | set(skip))
    if len(histories()) > 1:  # a split checkout: this copy holds its private files too
        _unsplit_gitignore(dst)


# split.sh appends the .gitignore the checkout had before the split under this line, in the
# engine's .gitignore (publish/engine.gitignore, which becomes the checkout's .gitignore).
GITIGNORE_MARK = "# ---- today's .gitignore, verbatim ----\n"


def _unsplit_gitignore(dst):
    """A copy of a split checkout carries the engine's allowlist .gitignore, which ignores every
    private file the copy holds: the sandbox's `git add -A` would commit the engine files only, and a
    worktree made from it would lack config/forge.json. Put back the .gitignore the checkout had
    before the split: what follows the mark. Not for an engine copy, which has no private files to keep."""
    p = os.path.join(dst, ".gitignore")
    if not os.path.isfile(p):
        return
    with open(p, encoding="utf-8") as f:
        text = f.read()
    if GITIGNORE_MARK in text:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text.split(GITIGNORE_MARK, 1)[1])


def copy_engine(dst):
    """The engine files only, as they are on disk: what git tracks (`ls-files -c`) less what
    publish/engine.gitignore leaves out (`ls-files -c -i --exclude-from=...`), which is what a
    stranger's checkout holds (docs/portable-design.md section 10). No config/forge.json, no
    profiles, no skills/. Not a git repo: a suite that needs one runs `git init` itself. Where there is
    no publish/engine.gitignore (a checkout that is already an engine, after the split, or a copy of one
    that a suite is running in) every tracked file is an engine file: copy_checkout(untracked=False)."""
    if not os.path.exists(os.path.join(FORGE, "publish", "engine.gitignore")):
        return copy_checkout(dst, untracked=False, skip=())

    def listed(*args):
        return {f for f in git(FORGE, "ls-files", "-z", "-c", *args).split("\0") if f}
    _copy_files(sorted(listed() - listed("-i", "--exclude-from=publish/engine.gitignore")), dst, NEVER_COPY)


def seed(dst):
    """Gives a copy a world to run in, from fixtures and never from this machine's data: examples/
    into dst/examples/ and tests/fixtures/config/ into dst/config/, except that AGENT-SYSTEM.md goes
    to dst/docs/, where the engine looks for it. Files already there are overwritten."""
    for src, out in (("examples", "examples"), (os.path.join("tests", "fixtures", "config"), "config")):
        base = os.path.join(FORGE, src)
        for d, _, files in os.walk(base):
            for n in files:
                rel = os.path.relpath(os.path.join(d, n), base)
                target = os.path.join(dst, "docs" if rel == "AGENT-SYSTEM.md" and out == "config" else out, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(os.path.join(d, n), target)


def manifest(root, tops=("",), skip=(), mask=False):
    """{path under root: (type, mode, sha256 or link target, mtime_ns)} for each of `tops` (paths
    relative to root), .git and the paths in `skip` left out. With `mask` the root is written @S@
    in contents and link targets, so two sandboxes compare equal."""
    out, rb = {}, root.encode()
    for top in tops:
        for d, dirs, files in os.walk(os.path.join(root, top)):
            dirs[:] = [x for x in dirs if x != ".git"]
            for n in dirs + files:
                p = os.path.join(d, n)
                if p in skip:
                    continue
                st = os.lstat(p)
                rel = os.path.relpath(p, root)
                mode = "%o" % (st.st_mode & 0o7777)
                if stat.S_ISLNK(st.st_mode):
                    target = os.readlink(p)
                    out[rel] = ("l", "", target.replace(root, "@S@") if mask else target, st.st_mtime_ns)
                elif stat.S_ISDIR(st.st_mode):
                    out[rel] = ("d", mode, "", st.st_mtime_ns)
                else:
                    with open(p, "rb") as f:
                        body = f.read()
                    out[rel] = ("f", mode, hashlib.sha256(body.replace(rb, b"@S@") if mask else body).hexdigest(),
                                st.st_mtime_ns)
    return out


def installed_settings(home, *roots, hooks=None, **top):
    """home's ~/.claude/settings.json with a SessionStart hook that runs each root's bin/forge, in
    the form of forge/hooks.py's USER_HOOKS row, which lib.installed_root() parses. `hooks`
    adds other events, `top` other top-level keys. Returns the file's path."""
    p = os.path.join(home, ".claude", "settings.json")
    groups = [{"hooks": [{"type": "command", "command": "python3 %s/bin/forge session-start || printf '%%s\\n' x" % r}]}
              for r in roots]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(dict({"hooks": dict({"SessionStart": groups}, **(hooks or {}))}, **top), f)
    return p


# Runs argv[1] as __main__ with io.open and builtins.open (separate names) patched: the first file
# opened for writing whose name starts with PREFIX (any, when None) gets half its text, then the
# process is SIGKILLed, so the write itself dies. os.fdopen goes through io.open too. os.open is
# patched to remember each descriptor's path: a writer that opens by fd (io.open(os.open(...)),
# as lib.write_text's _create does) hands io.open a number, and a filter on str(file) never
# matched it -- the kill never fired, and the test said so only because it checks that it did.
_KILL_MID_WRITE = """import builtins, io, os, runpy, signal, sys
real_open, real_os_open, fd_path = io.open, os.open, {}
def os_open(path, flags, *a, **k):
    fd = real_os_open(path, flags, *a, **k)
    fd_path[fd] = os.fsdecode(path)
    return fd
class HalfThenDie:
    def __init__(self, fh): self.fh = fh
    def __enter__(self): return self
    def __exit__(self, *a): return self.fh.__exit__(*a)
    def __getattr__(self, n): return getattr(self.fh, n)
    def write(self, text):
        self.fh.write(text[:len(text) // 2]); self.fh.flush()
        os.kill(os.getpid(), signal.SIGKILL)
def patched(file, mode="r", *a, **k):
    fh = real_open(file, mode, *a, **k)
    name = fd_path.get(file, "") if isinstance(file, int) else os.fsdecode(file)
    hit = "w" in mode and (PREFIX is None or os.path.basename(name).startswith(PREFIX))
    return HalfThenDie(fh) if hit else fh
io.open = builtins.open = patched
os.open = os_open
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def kill_mid_write(prefix=None):
    """The `python3 -c` wrapper above, for files whose basename starts with `prefix`."""
    return "PREFIX = %r\n" % prefix + _KILL_MID_WRITE


def tail(out, n=3):
    return " | ".join(out.strip().splitlines()[-n:])
