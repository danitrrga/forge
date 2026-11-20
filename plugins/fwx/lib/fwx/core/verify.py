# copied-from: marshal-factory hooks/verify.ts, lib/evidence.ts (`runChecks`, `outputTail`) and lib/recipe.ts (`redact`)
# @999ad209598517a4c826073b5a0edc2a4097a4fa, ported to Python.
"""The gate tied to the exact commit: run the project's checks on a clean tree and record what ran.

`verify(cwd, dir=None)` works on the checkout `cwd` is in (`git rev-parse --show-toplevel`, so a linked worktree is
its own checkout): the commit is its HEAD, the tree is clean when `git status` shows nothing outside `.fwx/` (the
documents the checks do not prove; the row this writes lives there, so counting it would make every second run dirty),
and the checks are the effective recipe of `evidence.plan_checks`. A dirty tree, an empty recipe or a folder outside a
repository run nothing and write nothing (exit 2). Every check runs, even after a red one, each with a time limit
(`CHECK_TIMEOUT_S`, 20 minutes) and its output, stdout and stderr together, kept in its last `KEEP_CHARS`. HEAD is
read again at the end: a HEAD that moved proves neither commit, so the row says `clean: false` and the run exits 2.

The row is written through `state.append_audit`: the sha, `rc` 0 or 1, and as its detail the JSON of the evidence,
`{sha, clean, source, commands: [{cmd, rc}], rc}`, which is the shape of `facts.evidence`. `rc` is null for a check
killed by the limit or never started. It goes to `dir` when given, else to the phase of the session as `state.resolve`
finds it, always in the main checkout whatever worktree the run was launched from; with neither it writes nothing and
says so.

One check is built in, after the project's own: `added_files`. A file the commits since the default branch ADD, named like a
one-use file (a brief, a prompt, a checkpoint, a handoff, a todo, notes, a dated file, `.md` and `.txt` only) or like an old
version (`.bak`, `-old`, `-v2`, any extension), is a red command of the evidence, `fwx added-files`, and each file gets one line
that says what to do instead. Green it is silent and adds no command, so a green run's evidence is what it was. `.fwx/` is
exempt (fwx writes its own state there). With no default branch to measure from it says `NOT RUN, NOT ARMED` and adds nothing.

The output tail of a red check goes to the terminal, so secrets are taken out of it first: the value of any environment
variable named like a credential, and the shapes of tokens (`redact`). Nothing else of the output is kept or written.

Imports only the standard library, state, config and core.evidence.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time

from fwx import config, state
from fwx.core import evidence

CHECK_TIMEOUT_S = 20 * 60
KEEP_CHARS = 64000
TAIL_LINES = 40
TAIL_CHARS = 4000
COMMENT_MARKER = "<!-- fwx:evidence -->"
_SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY|AUTH", re.I)
ADDED_FILES_CHECK = "fwx added-files"
_ONE_USE_EXT = (".md", ".txt")
_ONE_USE = re.compile(r"brief|prompt|checkpoint|handoff|tomorrow|todo|scratch|notes-|\d{4}-\d{2}-\d{2}", re.I)
_OLD_VERSION = re.compile(r"\.(?:bak|orig)(?:\.|\Z)|(?:-old|-copy| copy|-backup|-v\d+)(?:\.|\Z)", re.I)
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


def run_check(command, cwd, timeout=CHECK_TIMEOUT_S):
    """Run one command with the shell in `cwd`: `{cmd, rc, seconds, output}`. `rc` is the exit status, or None when the
    command was killed by the time limit (its whole process group) or could not start; `output` is the last KEEP_CHARS
    of stdout and stderr together, with the reason appended in those two cases."""
    started = time.monotonic()
    with tempfile.TemporaryFile() as out:
        rc, note = None, ""
        try:
            proc = subprocess.Popen([_shell(), "-c", command], cwd=cwd, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, start_new_session=True)
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
                note = "\ntimed out after %d s" % timeout
        out.seek(0, os.SEEK_END)
        out.seek(max(0, out.tell() - 4 * KEEP_CHARS))
        text = out.read().decode("utf-8", "replace")[-KEEP_CHARS:]
    return {"cmd": command, "rc": rc, "seconds": time.monotonic() - started, "output": text + note}


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


def marker(name):
    """`"one-use"`, `"old"` or None for the file `name` (a path: only its last part is read; `.fwx/` is the caller's)."""
    base = os.path.basename(name)
    if base.lower().endswith(_ONE_USE_EXT) and _ONE_USE.search(base):
        return "one-use"
    return "old" if _OLD_VERSION.search(base) else None


def _default_refs(root, cfg):
    """The refs of the default branch that exist: its local branch and its `origin/` copy, for the names `cfg` or the remote
    gives, else main and master."""
    names = set()
    if cfg["project"].get("default_branch"):
        names.add(cfg["project"]["default_branch"])
    r = _git(root, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    if r.returncode == 0 and r.stdout.strip():
        names.add(r.stdout.strip().split("/", 1)[-1])
    refs = ["refs/%s/%s" % (kind, n) for n in sorted(names or {"main", "master"}) for kind in ("heads", "remotes/origin")]
    return [ref for ref in refs if _git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode == 0]


def _range_base(root, cfg):
    """The merge base of HEAD with the default branch (the nearest, when the local branch and `origin/` differ), or None."""
    best = None
    for ref in _default_refs(root, cfg):
        mb = _git(root, "merge-base", "HEAD", ref)
        if mb.returncode:
            continue
        n = _git(root, "rev-list", "--count", mb.stdout.strip() + "..HEAD").stdout.strip()
        if n.isdigit() and (best is None or int(n) < best[0]):
            best = (int(n), mb.stdout.strip())
    return best and best[1]


def added_files(root, cfg):
    """`(lines, known)`: one line per file added since the merge base with the default branch whose name marks it as one-use or
    an old version, and False for `known` when there is no base to measure from."""
    base = _range_base(root, cfg)
    if base is None:
        return [], False
    r = _git(root, "diff", "-z", "--name-only", "--diff-filter=A", "-M", base, "HEAD")
    if r.returncode:
        raise state.StateError("git diff failed in %s: %s" % (root, r.stderr.strip()))
    lines = []
    for f in sorted(f for f in r.stdout.split("\0") if f):
        kind = None if f.startswith(state.PLAN_DIR.rstrip("/") + "/") else marker(f)
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


def verify(cwd, dir=None, say=lambda line: None, timeout=CHECK_TIMEOUT_S, environ=None):
    """Run the gate. Returns `(code, ev)`: code 0 green, 1 a red check, 2 it could not prove the commit; `ev` the evidence
    dict (None when nothing ran). `say` receives each progress line. State and config problems raise
    state.StateError or config.ConfigError before anything runs."""
    root = toplevel(cwd)
    sha = head(root)
    where = _destination(root, dir)
    cfg = config.load(root)
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
    results = [run_check(command, root, timeout) for command in recipe]
    started = time.monotonic()
    marked, known = added_files(root, cfg)
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
