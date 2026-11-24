# copied-from: marshal-factory hooks/verify.ts, lib/evidence.ts (`runChecks`, `outputTail`) and lib/recipe.ts (`redact`)
# @999ad209598517a4c826073b5a0edc2a4097a4fa, ported to Python.
"""The gate tied to the exact commit: run the project's checks on a clean tree and record what ran.

`verify(cwd, dir=None)` works on the checkout `cwd` is in (`git rev-parse --show-toplevel`, so a linked worktree is
its own checkout): the commit is its HEAD, the tree is clean when `git status` shows nothing outside `.fwx/` (the
documents the checks do not prove; the row this writes lives there, so counting it would make every second run dirty),
and the checks are the effective recipe of `evidence.plan_checks`. A dirty tree, an empty recipe or a folder outside a
repository run nothing and write nothing (exit 2). Every check runs, even after a red one, each with a time limit
(`project.check_timeout_s`, default `CHECK_TIMEOUT_S`, 20 minutes) and its output, stdout and stderr together, kept in its last `KEEP_CHARS`. HEAD is
read again at the end: a HEAD that moved proves neither commit, so the row says `clean: false` and the run exits 2.

The row is written through `state.append_audit`: the sha, `rc` 0 or 1, and as its detail the JSON of the evidence,
`{sha, clean, source, commands: [{cmd, rc}], rc}`, which is the shape of `facts.evidence`. `rc` is null for a check
killed by the limit or never started. It goes to `dir` when given, else to the phase of the session as `state.resolve`
finds it, always in the main checkout whatever worktree the run was launched from; with neither it writes nothing and
says so.

One check is built in, after the project's own: `added_files`. A file the commits since the default branch ADD (or rename to), named like a
one-use file (brief, checkpoint, handoff, tomorrow or scratch, `.md` and `.txt` only) or like an old version (`.bak` or `.orig`;
`-old`, `-copy`, ` copy`, `-backup` or `-v2` only with the living file beside it, any extension), is a red command of the evidence, `fwx added-files`, and each file gets one line
that says what to do instead. Green it is silent and adds no command, so a green run's evidence is what it was. `.fwx/` is
exempt (fwx writes its own state there). With no default branch to measure from it says `NOT RUN, NOT ARMED` and adds nothing.

The whole recipe runs under an exclusive lock on `<git-common-dir>/fwx/gate.lock` (`gate_lock`), so two gates of one repo, from two
worktrees, run one after the other: two at once take twice as long each and fail on load. The second says it waits and its
time limits start once it holds the lock. The lock is a flock, so it goes with the process however that ends. While it is held `FWX_GATE_LOCK=<path>` is in the environment of the
checks, and a `gate_lock` that finds its own path there does not lock again: a check that runs `fwx verify` would otherwise wait for its parent.

The output tail of a red check goes to the terminal, so secrets are taken out of it first: the value of any environment
variable named like a credential, and the shapes of tokens (`redact`). Nothing else of the output is kept or written.

Imports only the standard library, state, config and core.evidence.
"""
import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from fwx import config, state
from fwx.core import evidence

CHECK_TIMEOUT_S = config.DEFAULTS["project"]["check_timeout_s"]  # the default; a project sets its own: project.check_timeout_s
KEEP_CHARS = 64000
TAIL_LINES = 40
TAIL_CHARS = 4000
COMMENT_MARKER = "<!-- fwx:evidence -->"
_SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY|AUTH", re.I)
GATE_LOCK_ENV = "FWX_GATE_LOCK"  # the lock path, exported to the checks while the gate holds the lock
ADDED_FILES_CHECK = "fwx added-files"
_ONE_USE_EXT = (".md", ".txt")
_ONE_USE = {"brief", "checkpoint", "handoff", "tomorrow", "scratch"}  # whole words of a name, split on - _ . and spaces
_BACKUP = re.compile(r"\.(?:bak|orig)(?:\.|\Z)", re.I)
_VERSION = re.compile(r"(?:-old|-copy| copy|-backup|-v\d+)(?=\.|\Z)", re.I)
ADDED_FILE_TIP = ("is never committed: put it in your scratch folder (fwx scratch new), which git ignores; for an old version, "
                  "keep only the living file, since git holds the history. If this file really belongs in the project, rename "
                  "it without the marker.")
_NO_ROOT = os.devnull  # a root with no package.json: `plan_checks` then returns only the project's checks


def redact(text, environ=None):
    """`text` without credentials: the value (8 characters or more) of every environment variable whose name says it is
    one, a bearer, basic or token word followed by its value, the user and password of a URL, the known token prefixes
    (`ghp_`, `github_pat_`, `sk-`, `xox`) and any run of 40 or more token characters."""
    out = text
    for name, value in (os.environ if environ is None else environ).items():
        if len(value) >= 8 and _SECRET_NAME.search(name):
            out = out.replace(value, "[redacted]")
    out = re.sub(r"((?:bearer|basic|token)\s+)[A-Za-z0-9._~+/=-]{8,}", r"\1[redacted]", out, flags=re.I)
    out = re.sub(r"([a-z][a-z0-9+.-]*://)[^\s/@]+@", r"\1[redacted]@", out, flags=re.I)
    out = re.sub(r"\b(?:gh[pousr]_|github_pat_|sk-|xox[abp]-)[A-Za-z0-9_-]{10,}", "[redacted]", out)
    return re.sub(r"\b[A-Za-z0-9_+/=-]{40,}\b", "[redacted]", out)


def tail(output, environ=None):
    """The end of a check's output worth showing: redacted, then the last TAIL_LINES lines and TAIL_CHARS characters."""
    text = redact(output[-KEEP_CHARS:], environ).rstrip()
    return "\n".join(text.split("\n")[-TAIL_LINES:])[-TAIL_CHARS:]


def _shell():
    return shutil.which("bash") or "/bin/sh"


@contextlib.contextmanager
def _child_env():
    """The environment a check runs in. When its temp dir (TMPDIR, else the default) is inside a git work tree, TMPDIR is a fresh folder
    under /tmp for the length of the block and removed after: a test that expects its temp dir outside any repository fails falsely
    otherwise (13 to 17 of forge's did). A TMPDIR outside a checkout is left as it is."""
    env = dict(os.environ)
    here = env.get("TMPDIR") or tempfile.gettempdir()
    probe = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}  # a hook's GIT_DIR would make every folder look inside
    try:
        inside = subprocess.run(["git", "-C", here, "rev-parse", "--is-inside-work-tree"], env=probe, capture_output=True, text=True)
        inside = inside.returncode == 0 and inside.stdout.strip() == "true"
    except OSError:
        inside = False
    if not inside:
        yield env
        return
    made = tempfile.mkdtemp(prefix="fwx-check-", dir="/tmp" if os.path.isdir("/tmp") else None)
    env["TMPDIR"] = made
    try:
        yield env
    finally:
        shutil.rmtree(made, ignore_errors=True)


def run_check(command, cwd, timeout=CHECK_TIMEOUT_S):
    """Run one command with the shell in `cwd`: `{cmd, rc, seconds, output}`. `rc` is the exit status, or None when the
    command was killed by the time limit (its whole process group) or could not start; `output` is the last KEEP_CHARS
    of stdout and stderr together, with the reason appended in those two cases. `timed_out` tells the first from the second:
    a command that ran out of time proved nothing, which is not a red check, and `limit` is the time it had."""
    started = time.monotonic()
    with tempfile.TemporaryFile() as out, _child_env() as env:
        rc, note, timed_out = None, "", False
        try:
            proc = subprocess.Popen([_shell(), "-c", command], cwd=cwd, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, start_new_session=True, env=env)
        except OSError as e:
            proc, note = None, "\ncould not start: %s" % e
        if proc:
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.wait()
                note, timed_out = ("\ntimed out after %d s; raise `project.check_timeout_s` if the check needs longer" % timeout), True
        out.seek(0, os.SEEK_END)
        out.seek(max(0, out.tell() - 4 * KEEP_CHARS))
        text = out.read().decode("utf-8", "replace")[-KEEP_CHARS:]
    return {"cmd": command, "rc": rc, "seconds": time.monotonic() - started, "output": text + note,
            "timed_out": timed_out, "limit": timeout}


@contextlib.contextmanager
def gate_lock(root):
    """Hold the repo's gate lock, `<git-common-dir>/fwx/gate.lock`, for the block: the same file from every worktree of the repo,
    so a second gate waits here. It says so once on stderr, before it blocks. Released on any exit; the kernel frees it if the process dies."""
    r = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if r.returncode or not r.stdout.strip():
        raise state.StateError("cannot find the git directory of %s to lock the gate: %s" % (root, r.stderr.strip()))
    folder = os.path.join(r.stdout.strip(), "fwx")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "gate.lock")
    if os.environ.get(GATE_LOCK_ENV) == path:  # a check of the recipe running `fwx verify`: its own gate already holds the lock
        yield path
        return
    with open(path, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.stderr.write("fwx: waiting for another gate of this repo to finish (lock %s)\n" % path)
            fcntl.flock(f, fcntl.LOCK_EX)
        before = os.environ.get(GATE_LOCK_ENV)
        os.environ[GATE_LOCK_ENV] = path  # the checks inherit it, so a nested gate of this repo does not wait for its own parent
        try:
            yield path
        finally:
            if before is None:
                os.environ.pop(GATE_LOCK_ENV, None)
            else:
                os.environ[GATE_LOCK_ENV] = before
            fcntl.flock(f, fcntl.LOCK_UN)


def _git(root, *args):
    try:
        return subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True)
    except OSError as e:
        raise state.StateError("cannot run git (%s)" % e)


def is_dirty(root):
    """Whether the tree holds more than the commit, not counting `.fwx/`. StateError when git cannot say."""
    r = _git(root, "status", "--porcelain", "--", ".", ":(exclude)%s" % state.PLAN_DIR)
    if r.returncode:
        raise state.StateError("git status failed in %s: %s" % (root, r.stderr.strip()))
    return bool(r.stdout.strip())


def head(root):
    r = _git(root, "rev-parse", "HEAD")
    if r.returncode or not r.stdout.strip():
        raise state.StateError("cannot read HEAD of %s: %s" % (root, r.stderr.strip() or "no commits yet"))
    return r.stdout.strip()


def toplevel(cwd):
    r = _git(cwd, "rev-parse", "--show-toplevel")
    if r.returncode or not r.stdout.strip():
        raise state.StateError("not inside a git repository: %s" % cwd)
    return r.stdout.strip()


def marker(name, exists=lambda path: False):
    """`"one-use"`, `"old"` or None for the file `name` (a path: only its last part is read; `.fwx/` is the caller's). A
    `.bak` or `.orig` is old; `-old`, `-copy`, ` copy`, `-backup` and `-v2` are old only when `exists(<the path without that
    marker>)`: `plan-v2.md` beside `plan.md` is an old version, a lone `api-v2.md` is a living file."""
    base = os.path.basename(name)
    if base.lower().endswith(_ONE_USE_EXT) and _ONE_USE.intersection(re.split(r"[-_. ]+", base.lower())):
        return "one-use"
    if _BACKUP.search(base):
        return "old"
    for m in _VERSION.finditer(base):
        stem = base[:m.start()] + base[m.end():]
        if stem and exists(os.path.join(os.path.dirname(name), stem)):
            return "old"
    return None


def default_names(root, cfg):
    """The names of the default branch: the configuration's, the remote's, else main and master."""
    names = set()
    if cfg["project"].get("default_branch"):
        names.add(cfg["project"]["default_branch"])
    r = _git(root, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    if r.returncode == 0 and r.stdout.strip() and _git(root, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/HEAD^{commit}").returncode == 0:
        names.add(r.stdout.strip().split("/", 1)[-1])
    return names or {"main", "master"}


def _default_refs(root, cfg):
    """The refs of the default branch that exist: its local branch and its `origin/` copy."""
    refs = ["refs/%s/%s" % (kind, n) for n in sorted(default_names(root, cfg)) for kind in ("heads", "remotes/origin")]
    return [ref for ref in refs if _git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode == 0]


def _range_base(root, cfg, rev="HEAD"):
    """The merge base of `rev` with the default branch (the nearest, when the local branch and `origin/` differ), or None."""
    best = None
    for ref in _default_refs(root, cfg):
        mb = _git(root, "merge-base", rev, ref)
        if mb.returncode:
            continue
        n = _git(root, "rev-list", "--count", mb.stdout.strip() + ".." + rev).stdout.strip()
        if n.isdigit() and (best is None or int(n) < best[0]):
            best = (int(n), mb.stdout.strip())
    return best and best[1]


def _committed(root, rev, path):
    """Whether `path` is a file or a symlink of the commit `rev`: not a folder, and not a file only the working tree holds."""
    r = _git(root, "cat-file", "-t", "%s:%s" % (rev, path))
    return r.returncode == 0 and r.stdout.strip() == "blob"


def added_files(root, cfg, rev="HEAD"):
    """`(lines, known)`: one line per file added or renamed to since the merge base with the default branch whose name marks it as one-use or
    an old version, in the commit `rev` (the one verified), and False for `known` when there is no base to measure from."""
    base = _range_base(root, cfg, rev)
    if base is None:
        return [], False
    r = _git(root, "diff", "-z", "--name-only", "--diff-filter=AR", "-M", base, rev)
    if r.returncode:
        raise state.StateError("git diff failed in %s: %s" % (root, r.stderr.strip()))
    lines = []
    for f in sorted(f for f in r.stdout.split("\0") if f):
        kind = None if f.startswith(state.PLAN_DIR.rstrip("/") + "/") else marker(f, lambda p: _committed(root, rev, p))
        if kind:
            lines.append("%s: %s %s" % (f, "a one-use file" if kind == "one-use" else "an old version", ADDED_FILE_TIP))
    return lines, True


def evidence_line(sha, commands):
    """`evidence <sha> <cmd>=<rc> ...`, `none` for a command with no exit status: the line for a phase report."""
    return "evidence %s %s" % (sha, " ".join("%s=%s" % (c["cmd"], "none" if c["rc"] is None else c["rc"])
                                              for c in commands))


def comment_body(sha, commands):
    """The PR comment: the marker, then the evidence line. Only `cmd=rc`, never any output."""
    return "%s\n%s\n" % (COMMENT_MARKER, evidence_line(sha, commands))


def _destination(root, dir):
    """The folder the row goes to: `dir` (it must exist), else the session's phase in the main checkout, else None."""
    if dir is not None:
        if not os.path.isdir(dir):
            raise state.StateError("--dir %s is not a folder" % dir)
        return dir
    return state.resolve(root)["phase_dir"]


def verify(cwd, dir=None, say=lambda line: None, timeout=None, environ=None):
    """Run the gate. Returns `(code, ev)`: code 0 green, 1 a red check, 2 it could not prove the commit; `ev` the evidence
    dict (None when nothing ran). `say` receives each progress line. State and config problems raise
    state.StateError or config.ConfigError before anything runs. `timeout` is each check's limit in seconds, the
    project's `check_timeout_s` when None."""
    root = toplevel(cwd)
    sha = head(root)
    where = _destination(root, dir)
    cfg = config.load(root)
    timeout = timeout or cfg["project"]["check_timeout_s"]
    recipe = evidence.plan_checks(cfg["project"]["checks"], root)
    if is_dirty(root):
        say("the tree has uncommitted changes, so this run could not prove the commit: commit first and run again")
        return 2, None
    if not recipe:
        say("no checks defined: `project.checks` in .claude/fwx.json is empty and package.json has no test, lint, "
            "typecheck or build script")
        return 2, None
    source = "profile" if evidence.plan_checks(cfg["project"]["checks"], _NO_ROOT) else "package"
    say("running %d check%s from the %s at %s" % (len(recipe), "" if len(recipe) == 1 else "s",
                                                   "project" if source == "profile" else "package.json scripts", sha[:7]))
    with gate_lock(root):
        results = [run_check(command, root, timeout) for command in recipe]
    started = time.monotonic()
    marked, known = added_files(root, cfg, sha)
    if not known:
        say("%s: no default branch to measure the added files from" % "NOT RUN, NOT ARMED")
    if marked:
        results.append({"cmd": ADDED_FILES_CHECK, "rc": 1, "seconds": time.monotonic() - started, "output": None, "lines": marked})
    moved = head(root) != sha
    if moved:
        say("HEAD moved while the checks ran, so they prove neither commit")
    for r in results:
        ok = r["rc"] == 0
        say("%s %s · %.1f s%s" % ("passed" if ok else "failed", r["cmd"], r["seconds"],
                                  "" if ok else " · exit %s" % ("none" if r["rc"] is None else r["rc"])))
    for r in results:
        if r["rc"] != 0 and r["output"] is None:
            say("\n--- %s" % r["cmd"])
            for line in r["lines"]:
                say(line)
        elif r["rc"] != 0:
            say("\n--- %s\n%s" % (r["cmd"], tail(r["output"], environ)))
    green = all(r["rc"] == 0 for r in results)
    ev = {"sha": sha, "clean": not moved, "source": source, "commands": [{"cmd": r["cmd"], "rc": r["rc"]} for r in results],
          "rc": 0 if green and not moved else 1}
    say("%s at %s · %d/%d checks" % ("verified" if ev["rc"] == 0 else "not verified", sha[:7],
                                      sum(r["rc"] == 0 for r in results), len(results)))
    if where is None:
        say("no phase folder for this session and no --dir: no evidence row was written")
    else:
        state.append_audit(where, "evidence", detail=json.dumps(ev), rc=ev["rc"], sha=sha)
    return (2 if moved else ev["rc"]), ev
