"""The state of `.fwx/`: where it is, its subproject, milestone, phase and subphase folders, the session file, the
TSV writers, and the making, cancelling and checking of those folders. The single writer of audit.tsv is
`append_audit`; nothing else in the framework writes that file.

referent: pstack plugins/pstack/skills/show-me-your-work/scripts/log.sh @36885ea, rules reimplemented in Python (tab,
newline and CR become a space; a quote in front of a cell that starts with `= + - @ "`; one write per row), not copied.

Every path resolves against the main checkout (config.main_checkout), never against the folder the caller stands in:
a linked worktree has none of the ignored files. The one exception is `plan_root` in a repository whose default
branch is protected and whose `.fwx/` is tracked: there the session's own worktree holds the live copy and reaches
the default branch through the phase's pull request. The signal is `project.default_branch_protected: true` in
`.claude/fwx.json`; without it `plan_root` never leaves the main checkout. `commit_plan` (`fwx state commit`) is what
tracks it there: it moves the files the main checkout holds into the worktree and commits them on the phase branch.

Reading creates nothing. Rejections raise StateError before anything is written. A path outside a git repository is
config.ConfigError, whose message names the fix.

Imports only the standard library and config: `fwx statusline` has to finish in under 100 ms.
"""
import contextlib
import filecmp
import io
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fwx import config

PLAN_DIR = ".fwx"
DECISION_COLUMNS = ("date", "id", "decision", "why", "rejected", "support", "source", "supersedes")
SUPPORT = ("chosen", "approved", "unexamined", "agent-assumption")
AUDIT_COLUMNS = ("date", "kind", "sha", "detail", "rc")
AUDIT_KINDS = ("evidence", "stage", "round")
CLOSED_STAGES = ("closed", "cancelled")
STATE_LINES = 100   # state.md: the length of GSD's template; over it only warns
REPORT_LINES = 40   # a phase report: one terminal screen; over it only warns

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_MILESTONE = re.compile(r"v(\d+)\Z")
_PHASE = re.compile(r"\d+(\.\d+)*-.+\Z")  # NN-slug, NN.M-slug, NN.M.K-slug
_SUBPHASE = re.compile(r"\d+\.\d+-.+\Z")  # NN.M-slug inside a phase
_STAGE_WORD = re.compile(r"[a-z][a-z-]*(\s|\Z)")
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_FORMULA = "=+-@\""
_SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*\Z")
# `.fwx/[subprojects/<name>/]milestones/vN/phases/NN-slug`: the only folders cancel and new-subphase act on
_PHASE_PATH = re.compile(r"(^|/)" + re.escape(PLAN_DIR) + r"/(subprojects/[^/]+/)?milestones/v\d+/phases/\d+(\.\d+)*-[^/]+\Z")
_SCOPE_PATH = re.compile(r"(^|/)" + re.escape(PLAN_DIR) + r"(/subprojects/[^/]+)?\Z")
_TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
_TEMPLATE_NOTE = re.compile(r"<!-- (referent|copied-from)\b.*-->\s*\Z")


class StateError(Exception):
    """A write or a lookup the state layer refuses; the message says why and nothing was written."""


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(cwd, *args):
    try:
        return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True)
    except OSError as e:
        raise StateError("cannot run git (%s)" % e)


def _num_key(name):
    """Sort key of a folder name `NN[.M[.K]]-slug`: the numbers as a tuple, then the name (12.2 < 12.2.1 < 12.3 < 12.10)."""
    return (tuple(int(n) for n in re.match(r"\d+(\.\d+)*", name).group(0).split(".")), name)


def _dirs(parent, pattern):
    try:
        names = os.listdir(parent)
    except (FileNotFoundError, NotADirectoryError):
        return []
    return [n for n in names if pattern.match(n) and os.path.isdir(os.path.join(parent, n))]


# ---- where things are ---------------------------------------------------------------------------------------------

def _protected_worktree(main, cwd):
    """The worktree holding the live `.fwx/` when the default branch is protected and `.fwx/` is tracked there, else
    None. The cheap tests come first: the common case (no worktree, or nothing tracked) reads no configuration."""
    r = _git(os.getcwd() if cwd is None else cwd, "rev-parse", "--show-toplevel")
    top = r.stdout.strip()
    if r.returncode or not top or os.path.realpath(top) == os.path.realpath(main):
        return None
    if not _git(top, "ls-files", "--", PLAN_DIR).stdout.strip():
        return None
    with contextlib.redirect_stderr(io.StringIO()):  # the missing-file line is for the commands that need the file
        cfg = config.load(cwd)
    return top if cfg["project"].get("default_branch_protected") is True else None


def plan_root(cwd=None):
    """`<main checkout>/.fwx`, from any folder of the main tree or of a linked worktree. Creates nothing. In the
    protected-default-branch variant (module docstring) it is the session worktree's `.fwx`."""
    main = config.main_checkout(cwd)
    return Path(_protected_worktree(main, cwd) or main) / PLAN_DIR


_DOC_EXT = (".md", ".tsv")
_OTHER_WORK = re.compile(r"(?:^|/)((?:milestones/v\d+/phases/[^/]+)|(?:factory/[^/]+))/")  # a phase folder or a factory job
_PHASE_REL = re.compile(r"(?:subprojects/[^/]+/)?milestones/v\d+/phases/[^/]+\Z")


def _is_protected(cwd):
    with contextlib.redirect_stderr(io.StringIO()):  # the missing-file line is for the commands that need the file
        return config.load(cwd)["project"].get("default_branch_protected") is True


def _documents(plan_dir, phase_rel):
    """The documents under `plan_dir` (a `.fwx/` folder) as paths relative to it, with `/`: regular files, not links, named `*.md` or
    `*.tsv`, with no name or folder starting with a dot; of the phase folders and factory jobs, only the one at `phase_rel`."""
    out = []
    for here, dirs, files in os.walk(plan_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            p = os.path.join(here, f)
            if f.startswith(".") or not f.endswith(_DOC_EXT) or os.path.islink(p) or not os.path.isfile(p):
                continue
            rel = os.path.relpath(p, plan_dir).replace(os.sep, "/")
            m = _OTHER_WORK.search(rel)
            if not m or rel[:m.end(1)] == phase_rel:
                out.append(rel)
    return sorted(out)


def _phase_branch(audit):
    """The branch of the last `stage` row of an audit file that names one (`... branch <name>`), or None."""
    found = None
    for row in read_rows(audit):
        m = re.search(r"\bbranch (\S+)", row.get("detail", "")) if row.get("kind") == "stage" else None
        found = m.group(1) if m else found
    return found


def commit_plan(message, cwd=None, phase=None, session=None):
    """Commit the documents of one phase (and the root ones of `.fwx/`) where their history is: (folder it was committed in, its
    branch, the short sha or None when nothing changed). The documents are `_documents`; nothing else under `.fwx/` is added, and the
    phase is `phase`, else the session's. Refused with a StateError, and nothing moved: `.fwx/` ignored by git (its history is on
    the data side); a protected default branch with `cwd` not in a linked worktree, on the default branch, on a detached HEAD or on a
    branch other than the phase's; a document in both places with different text. Without the protection it is the main checkout.
    With it, it is the worktree `cwd` is in, which first takes the documents the main checkout holds and it lacks, so the phase branch
    carries them and the live copy is the worktree's. The move and the commit are one step: if the commit fails, the documents are put
    back where they were."""
    cwd = os.getcwd() if cwd is None else cwd
    main = config.main_checkout(cwd)
    if _git(main, "check-ignore", "-q", PLAN_DIR + "/PROJECT.md").returncode == 0:
        raise StateError("%s/ is ignored by git (its history is on the data side): commit it with `forge commit -m MESSAGE %s` from %s"
                         % (PLAN_DIR, PLAN_DIR, main))
    if phase is None:
        phase = resolve(cwd, session)["phase_dir"]
        if phase is None:
            raise StateError("which phase? none is bound to this session and open: pass --phase PHASE_DIR (or bind one with `fwx state use PHASE_DIR`)")
    parts = os.path.abspath(str(phase)).replace(os.sep, "/").rsplit("/" + PLAN_DIR + "/", 1)
    phase_rel = parts[1] if len(parts) == 2 else ""
    if not _PHASE_REL.match(phase_rel):
        raise StateError("%s is not a phase folder of %s/" % (phase, PLAN_DIR))
    where, main_plan, protected = main, os.path.join(main, PLAN_DIR), _is_protected(cwd)
    if protected:
        where = _git(cwd, "rev-parse", "--show-toplevel").stdout.strip()
        if not where or os.path.realpath(where) == os.path.realpath(main):
            raise StateError("the default branch is protected: run it from the phase's worktree, where %s/ is committed on the phase branch" % PLAN_DIR)
        on = _git(where, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if on == "HEAD":
            raise StateError("%s is on a detached HEAD: check out the phase's branch there first" % where)
        if on == config.load(cwd)["project"].get("default_branch"):
            raise StateError("%s is on the default branch, which is protected: run it from the phase's worktree" % where)
        audits = [os.path.join(r, PLAN_DIR, phase_rel, "audit.tsv") for r in (where, main)]
        want = _phase_branch(next((a for a in audits if os.path.isfile(a)), audits[0]))
        if want and want != on:
            raise StateError("%s is on branch %s, not the phase's branch %s: check it out there first" % (where, on, want))
    where_plan = os.path.join(where, PLAN_DIR)
    movable = _documents(main_plan, phase_rel) if protected and os.path.isdir(main_plan) else []
    clash = [r for r in movable if os.path.lexists(os.path.join(where_plan, r)) and not _same(os.path.join(main_plan, r), os.path.join(where_plan, r))]
    if clash:
        raise StateError("%s exist(s) in %s and in %s with different text: compare them, remove one, and run it again"
                         % (", ".join(clash), main_plan, where_plan))
    moved, made = [], []
    files = []

    def undo(why):
        if files:
            _git(where, "reset", "-q", "--", *files)
        for r in reversed(moved):
            try:
                shutil.move(os.path.join(where_plan, r), os.path.join(main_plan, r))
            except OSError as e:
                raise StateError("%s; and %s could not be put back (%s): it is in %s" % (why, r, e, where_plan))
        for d in sorted(made, key=len, reverse=True):
            try:
                os.rmdir(d)
            except OSError:
                pass
        raise StateError("%s; the documents are %s in %s" % (why, "back" if moved else "still", main_plan))

    try:
        for r in movable:
            dst = os.path.join(where_plan, r)
            if os.path.lexists(dst):
                continue  # the same text: the main copy goes once the commit is made
            d = os.path.dirname(dst)
            while not os.path.isdir(d):
                made.append(d)
                d = os.path.dirname(d)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(os.path.join(main_plan, r), dst)
            moved.append(r)
    except OSError as e:
        undo("cannot move %s/ from %s into %s (%s)" % (PLAN_DIR, main, where, e))
    files = [PLAN_DIR + "/" + r for r in _documents(where_plan, phase_rel)]
    branch = _git(where, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    sha = None
    if files:
        r = _git(where, "add", "--", *files)
        if r.returncode:
            undo("git add %s failed in %s: %s" % (PLAN_DIR, where, (r.stderr or r.stdout).strip()))
        if _git(where, "diff", "--cached", "--quiet", "--", *files).returncode:
            r = _git(where, "commit", "-q", "-m", message, "--", *files)
            if r.returncode:
                undo("git commit failed in %s: %s" % (where, (r.stderr or r.stdout).strip()))
            sha = _git(where, "rev-parse", "--short", "HEAD").stdout.strip()
    for r in movable:  # committed: the copies the main checkout still holds are the same text
        if os.path.isfile(os.path.join(main_plan, r)) and r not in moved:
            os.remove(os.path.join(main_plan, r))
    for here, _, _ in os.walk(main_plan, topdown=False):
        try:
            os.rmdir(here)
        except OSError:  # not empty: something stays
            pass
    return where, branch, sha


def _same(a, b):
    return os.path.isfile(a) and os.path.isfile(b) and not os.path.islink(b) and filecmp.cmp(a, b, shallow=False)


def subprojects(root):
    """The subfolders of `<root>/subprojects/`, sorted; a file there is not a subproject."""
    return sorted(n for n in _dirs(os.path.join(str(root), "subprojects"), re.compile(r"[^.]")))


def has_subprojects(root):
    """A project has subprojects if and only if `subprojects/` has entries: deduced, never declared."""
    return bool(subprojects(root))


def scope_root(root, subproject=None):
    """`root`, or `root/subprojects/<name>`; the name is a single folder name, never a path."""
    if subproject is None:
        return Path(root)
    if not _NAME.match(subproject):
        raise StateError("bad subproject name %r: a single folder name of letters, digits, . _ -" % (subproject,))
    return Path(root) / "subprojects" / subproject


def milestones(scope):
    """The `vN` folders of `<scope>/milestones/`, in numeric order (v2 before v10)."""
    return sorted(_dirs(os.path.join(str(scope), "milestones"), _MILESTONE), key=lambda n: int(n[1:]))


def current_milestone(scope):
    """The highest milestone, or None."""
    found = milestones(scope)
    return found[-1] if found else None


def phases(scope, milestone):
    """The phase folders of a milestone, as Paths, in numeric tuple order. The pattern takes `NN-slug`, `NN.M-slug` and
    `NN.M.K-slug`: the last two only come from the 4.1 converter, but a milestone may hold them."""
    if not _MILESTONE.match(milestone):
        raise StateError("bad milestone name %r: vN" % (milestone,))
    parent = Path(scope) / "milestones" / milestone / "phases"
    return [parent / n for n in sorted(_dirs(str(parent), _PHASE), key=_num_key)]


def subphases(phase_dir):
    """The `NN.M-slug` folders inside a phase, as Paths, in numeric order (03.2 before 03.10)."""
    return [Path(phase_dir) / n for n in sorted(_dirs(str(phase_dir), _SUBPHASE), key=_num_key)]


def phase_paths(dir):
    """The files of a phase, a subphase or any working folder (also `factory/<KEY>/`), as Paths. Nothing is created;
    `next_report` is `report-<n>.md` with the first free n."""
    d = Path(dir)
    n = 1
    while (d / ("report-%d.md" % n)).exists():
        n += 1
    return {"context": d / "context.md", "decisions": d / "decisions.tsv", "research": d / "research", "demo": d / "demo",
            "premortem": d / "premortem.md", "plan": d / "plan.md", "postmortem": d / "postmortem.md",
            "state": d / "state.md", "audit": d / "audit.tsv", "next_report": d / ("report-%d.md" % n)}


def last_stage(dir):
    """The target stage of the last `stage` row of the folder's audit.tsv (the first word of its detail), or None."""
    found = None
    for row in read_rows(os.path.join(str(dir), "audit.tsv")):
        if row.get("kind") == "stage" and row.get("detail", "").split(" ", 1)[0]:
            found = row["detail"].split(" ", 1)[0]
    return found


def open_phases(scope):
    """The phases of the current milestone whose last stage is neither `closed` nor `cancelled`; a phase with no stage
    row yet (a new discuss) is open."""
    m = current_milestone(scope)
    return [] if m is None else [p for p in phases(scope, m) if last_stage(p) not in CLOSED_STAGES]


# ---- sessions -----------------------------------------------------------------------------------------------------

def session_id(explicit=None):
    """`explicit`, else $CLAUDE_CODE_SESSION_ID, else None. It becomes a file name, so a path-like id is refused."""
    sid = explicit if explicit is not None else os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    if sid is not None and not _SESSION.match(sid):
        raise StateError("bad session id %r: letters, digits, . _ - only" % (sid,))
    return sid


def sessions_dir(cwd=None):
    """`<git-common-dir>/fwx/sessions`, the same folder from every worktree. Creates nothing."""
    config.main_checkout(cwd)  # ConfigError outside a repository, with its message
    r = _git(os.getcwd() if cwd is None else cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.join(r.stdout.strip(), "fwx", "sessions")


_sessions_dir = sessions_dir  # the name `fwx statusline` and `fwx budget` import


def read_session(cwd=None, session=None):
    """`{subproject, phase_dir}` of the session (phase_dir relative to the checkout that holds `.fwx/`), or None when
    there is no session id or no file. The file lives in the git common dir, so every worktree reads the same one."""
    sid = session_id(session)
    if sid is None:
        return None
    path = os.path.join(_sessions_dir(cwd), sid + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as e:
        raise StateError("%s cannot be read (%s); delete it or run `fwx state use` again" % (path, e))
    if not isinstance(data, dict) or set(data) != {"subproject", "phase_dir"}:
        raise StateError("%s is not {subproject, phase_dir}; delete it or run `fwx state use` again" % path)
    return data


def write_session(cwd=None, session=None, *, subproject=None, phase_dir=None):
    """Bind the session to a subproject (None: the root) and a phase folder (None: no phase). `phase_dir` is stored
    relative to the checkout that holds `.fwx/` and must be inside it. Written to a temp file and renamed into place."""
    sid = session_id(session)
    if sid is None:
        raise StateError("no session id: pass one or run inside Claude Code (CLAUDE_CODE_SESSION_ID)")
    if subproject is not None:
        scope_root("x", subproject)
    stored = None
    if phase_dir is not None:
        root = plan_root(cwd)
        full = os.path.normpath(os.path.join(str(root.parent), str(phase_dir)))
        if not full.startswith(str(root) + os.sep):
            raise StateError("%s is not inside %s" % (phase_dir, root))
        stored = os.path.relpath(full, str(root.parent))
    _put_session(_sessions_dir(cwd), sid, subproject, stored)


def _put_session(d, sid, subproject, stored):
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + ".json")
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"subproject": subproject, "phase_dir": stored}, f)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _resolve_in(root, bound):
    """(subproject, milestone, phase, candidates, bound_hit) of the `.fwx/` folder `root`: the phase the session is bound to when it is
    there, else the only open one."""
    subproject = bound["subproject"] if bound else None
    scope = scope_root(root, subproject)
    candidates = [str(p) for p in open_phases(scope)]
    phase, milestone, hit = None, current_milestone(scope), False
    if bound and bound["phase_dir"]:
        p = os.path.join(str(root.parent), bound["phase_dir"])
        if os.path.isdir(p):
            phase, milestone, hit = p, os.path.basename(os.path.dirname(os.path.dirname(p))), True
    if phase is None and len(candidates) == 1:
        phase = candidates[0]
    return subproject, milestone, phase, candidates, hit


def phase_worktrees(cwd=None):
    """The `.fwx/` folders of the linked worktrees of a project whose default branch is protected: there the documents of a phase live
    on its branch, so the main checkout may hold none. [] for any other project or when no worktree has a `.fwx/`."""
    main = config.main_checkout(cwd)
    try:
        if not _is_protected(cwd):
            return []
    except config.ConfigError:
        return []
    listed = _git(os.getcwd() if cwd is None else cwd, "worktree", "list", "--porcelain").stdout.splitlines()
    return [Path(l[9:]) / PLAN_DIR for l in listed if l.startswith("worktree ") and os.path.realpath(l[9:]) != os.path.realpath(main)
            and os.path.isdir(os.path.join(l[9:], PLAN_DIR))]


def resolve(cwd=None, session=None):
    """Where the session is: `{main_checkout, plan_root, has_subprojects, subproject, milestone, phase_dir, subphases,
    candidates, where, worktree, paths}`, every path a string, nothing written. The subproject and the phase come from the session
    file; with no phase bound (or a bound one that is gone) the only open phase of the scope's current milestone is the phase, and
    with several or none `phase_dir` is None and `candidates` lists the open ones. When the main checkout holds no open phase and
    the project's default branch is protected, the phases open in its worktrees are looked at the same way (their documents live on
    the phase branch): `where` is then `worktree` and `worktree` that folder (`main` and None otherwise). Binding is the caller's."""
    main = config.main_checkout(cwd)
    root = plan_root(cwd)
    bound = read_session(cwd, session)
    subproject, milestone, phase, candidates, _ = _resolve_in(root, bound)
    roots = phase_worktrees(cwd) if root.parent == Path(main) else []
    if roots:  # a phase folder here with no audit file is what is left of one whose documents moved to its worktree
        stub = lambda p: not phase_paths(p)["audit"].is_file()
        candidates = [c for c in candidates if not stub(c)]
        phase = None if phase and stub(phase) else phase
        phase = candidates[0] if phase is None and len(candidates) == 1 else phase
    if roots and phase is None and not candidates:
        found = []
        for wroot in roots:
            sub, ms, ph, cands, hit = _resolve_in(wroot, bound)
            if hit:
                root, subproject, milestone, phase = wroot, sub, ms, ph
                break
            found += cands
        candidates = found if phase is None else candidates + found
        if phase is None and len(found) == 1:
            root = next(w for w in roots if found[0].startswith(str(w) + os.sep))
            subproject, milestone, phase, _, _ = _resolve_in(root, bound)
    inside = os.path.realpath(str(root.parent)) != os.path.realpath(main)
    return {"main_checkout": main, "plan_root": str(root), "has_subprojects": has_subprojects(root),
            "subproject": subproject, "milestone": milestone, "phase_dir": phase,
            "subphases": [str(p) for p in subphases(phase)] if phase else [],
            "candidates": candidates, "where": "worktree" if inside else "main", "worktree": str(root.parent) if inside else None,
            "paths": {k: str(v) for k, v in phase_paths(phase).items()} if phase else {}}


# ---- TSV ----------------------------------------------------------------------------------------------------------

def _clean(v):
    """One cell: tab, newline and CR become a space, and a cell starting with `= + - @ "` gets a quote in front (a
    spreadsheet would read it as a formula). A real number is not text: -9 stays -9."""
    if v is None:
        return ""
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    t = re.sub(r"[\t\r\n]", " ", str(v))
    return "'" + t if t[:1] and t[0] in _FORMULA else t


def append_row(path, columns, values):
    """Add one row, with the header first when the file is new or empty. `values` is a sequence in column order or a dict
    by column. The row goes in one `os.write` on an O_APPEND descriptor, so a concurrent writer cannot split it. An
    existing file with another header is refused. Two writers each creating the same new file at the same moment can
    both write the header: a folder's TSVs are created with their header when the folder is made."""
    path, cols = str(path), tuple(columns)
    if isinstance(values, dict):
        missing = [c for c in cols if c not in values]
        extra = [k for k in values if k not in cols]
        if missing or extra:
            raise StateError("%s: values do not match the columns (missing %s, unknown %s)" % (path, missing, extra))
        values = [values[c] for c in cols]
    values = list(values)
    if len(values) != len(cols):
        raise StateError("%s: %d values for %d columns" % (path, len(values), len(cols)))
    header = "\t".join(cols)
    try:
        with open(path, "rb") as f:
            first = f.readline().decode("utf-8", "replace").rstrip("\n")
    except FileNotFoundError:
        first = ""
    except OSError as e:
        raise StateError("%s cannot be read (%s)" % (path, e.strerror))
    if first and first != header:
        raise StateError("%s has the header %r, not %r" % (path, first, header))
    if not os.path.isdir(os.path.dirname(os.path.abspath(path))):
        raise StateError("%s: the folder does not exist" % path)
    line = "\t".join(_clean(v) for v in values) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    except OSError as e:
        raise StateError("%s cannot be written (%s)" % (path, e.strerror))
    try:
        data = ((header + "\n" if os.fstat(fd).st_size == 0 else "") + line).encode("utf-8")
        if os.write(fd, data) != len(data):
            raise StateError("%s: the row was cut short" % path)
    finally:
        os.close(fd)


def read_rows(path):
    """The rows of a TSV as dicts by header column; [] when the file is missing or empty. Cells are returned as written."""
    try:
        with open(str(path), encoding="utf-8", newline="") as f:
            lines = f.read().split("\n")
    except FileNotFoundError:
        return []
    cols = lines[0].split("\t") if lines and lines[0] else []
    rows = []
    for line in lines[1:]:
        if line:
            cells = line.split("\t")
            rows.append(dict(zip(cols, cells + [""] * (len(cols) - len(cells)))))
    return rows


def append_decision(path, *, decision, why, support, rejected="", source="", supersedes=""):
    """Add a row to a decisions.tsv or an adr.tsv and return its id (`D<n>`, or `A<n>` for adr.tsv). Refused, and the
    file left as it was: `support` outside SUPPORT, an empty `decision` or `why`, a `supersedes` that is not an id in
    this file."""
    if support not in SUPPORT:
        raise StateError("support %r is not one of %s" % (support, ", ".join(SUPPORT)))
    if not str(decision).strip() or not str(why).strip():
        raise StateError("a decision needs a decision text and a why")
    rows = read_rows(path)
    prefix = "A" if os.path.basename(str(path)) == "adr.tsv" else "D"
    if supersedes and supersedes not in {r.get("id") for r in rows}:
        raise StateError("supersedes %r: no such id in %s" % (supersedes, path))
    nums = [int(r["id"][1:]) for r in rows if re.fullmatch(prefix + r"\d+", r.get("id", ""))]
    new_id = "%s%d" % (prefix, max(nums, default=0) + 1)
    append_row(path, DECISION_COLUMNS, [_now(), new_id, decision, why, rejected, support, source, supersedes])
    return new_id


def read_decision_rows(path):
    """The rows of a decisions.tsv or an adr.tsv; [] when the file is missing or empty. A header that is not
    DECISION_COLUMNS is refused (`append_row` refuses it too), so a read never takes another table for a decision log."""
    try:
        with open(str(path), encoding="utf-8", newline="") as f:
            first = f.readline().rstrip("\r\n")
    except FileNotFoundError:
        return []
    except OSError as e:
        raise StateError("%s cannot be read (%s)" % (path, e.strerror))
    if first and first != "\t".join(DECISION_COLUMNS):
        raise StateError("%s has the header %r, not %r" % (path, first, "\t".join(DECISION_COLUMNS)))
    return read_rows(path)


def decisions_in_force(rows):
    """Every row of a decision log as a copy with `in_force` and `superseded_by` added: a row is in force when no other
    row names its id in `supersedes`, so in a chain A <- B <- C only C is. `superseded_by` is the id of the row that
    replaced it ("" when in force; the last one written when two rows replace the same id, and then both stay in force).
    Refused with a StateError, and nothing returned: an id that appears twice, a `supersedes` naming an id no row has,
    a `supersedes` that loops back on itself."""
    seen, by = set(), {}
    for r in rows:
        if r.get("id", "") in seen:
            raise StateError("the id %s appears twice" % r.get("id", ""))
        seen.add(r.get("id", ""))
    for r in rows:
        old = r.get("supersedes", "")
        if old:
            if old not in seen:
                raise StateError("%s supersedes %r: no such id in this file" % (r.get("id", ""), old))
            by[old] = r["id"]
    for start in by:
        walked, i = [], start
        while i in by:
            if i in walked:
                raise StateError("supersedes loops back on itself through %s" % i)
            walked.append(i)
            i = by[i]
    return [dict(r, in_force=r.get("id", "") not in by, superseded_by=by.get(r.get("id", ""), "")) for r in rows]


def decision_matches(row, terms):
    """Whether every term (case-insensitive) is in the row's decision, why, rejected or source text."""
    text = "\n".join(str(row.get(k, "")) for k in ("decision", "why", "rejected", "source")).lower()
    return all(str(t).lower() in text for t in terms)


def decisions_for_topic(rows, terms):
    """The rows of `decisions_in_force` output that touch a topic, as the rows in force today: a row matching every term
    is itself when in force, else the row at the end of its chain, once however many rows of the chain match. Each
    result is a copy with `matched_superseded`, the ids of the superseded rows that matched. Order of first match."""
    by_id = {r["id"]: r for r in rows}
    found = {}
    for r in rows:
        if not decision_matches(r, terms):
            continue
        end = r
        while end["superseded_by"]:
            end = by_id[end["superseded_by"]]
        hit = found.setdefault(end["id"], dict(end, matched_superseded=[]))
        if r is not end:
            hit["matched_superseded"].append(r["id"])
    return list(found.values())


def append_audit(dir, kind, detail="", rc="", sha=None, cwd=None):
    """Add a row to `<dir>/audit.tsv`: the one writer of that file. `kind` is in AUDIT_KINDS. A `stage` row's detail starts
    with the target stage (`^[a-z][a-z-]*$`; whether the transition is legal is for the caller to check) and, with no `sha`,
    gets the HEAD of `cwd` (default: the current folder) now. `evidence` needs a `sha`. Everything is checked before the
    file is touched."""
    if kind not in AUDIT_KINDS:
        raise StateError("kind %r is not one of %s" % (kind, ", ".join(AUDIT_KINDS)))
    detail = "" if detail is None else str(detail)
    if kind == "stage":
        if not _STAGE_WORD.match(detail):
            raise StateError("a stage row's detail starts with the target stage (lower-case letters and -), got %r" % detail)
        if sha is None:
            r = _git(os.getcwd() if cwd is None else cwd, "rev-parse", "HEAD")
            if r.returncode or not r.stdout.strip():
                raise StateError("cannot read HEAD of %s for the stage row: %s" % (cwd or os.getcwd(), r.stderr.strip() or "no output"))
            sha = r.stdout.strip()
    elif kind == "evidence" and (sha is None or not str(sha).strip()):
        raise StateError("an evidence row needs the sha it ran against")
    append_row(os.path.join(str(dir), "audit.tsv"), AUDIT_COLUMNS, [_now(), kind, "" if sha is None else sha, detail, rc])


# ---- creating, cancelling and checking ----------------------------------------------------------------------------

def _read_template(name):
    """A template of `templates/` (`phase/plan.md`, ...) as text, without its leading `<!-- referent ...` or
    `<!-- copied-from ...` line: that line says where the template came from, not what a real document says."""
    path = _TEMPLATES / name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise StateError("the template %s cannot be read (%s): the framework's templates/ folder is incomplete" % (path, e.strerror))
    return "".join(l for l in text.splitlines(True) if not _TEMPLATE_NOTE.match(l))


def _check_slug(slug):
    if not isinstance(slug, str) or not _SLUG.match(slug):
        raise StateError("bad slug %r: lower-case letters and digits, words joined by single hyphens" % (slug,))


def _new_tsv(path, columns):
    """A TSV made with its header, so that a writer never has to. `x`: an existing file is an error, not overwritten."""
    with open(str(path), "x", encoding="utf-8") as f:
        f.write("\t".join(columns) + "\n")


def _write_new(path, text):
    with open(str(path), "x", encoding="utf-8") as f:
        f.write(text)


def _numbers(parent, subphases):
    """The numbers the folders of `parent` use: the first number of each `NN-slug` phase, the last of each `NN.M-slug`."""
    found = _dirs(str(parent), _SUBPHASE if subphases else _PHASE)
    return [int(re.match(r"\d+(\.\d+)*", n).group(0).split(".")[-1 if subphases else 0]) for n in found]


def _next_number(parent, subphases=False):
    """The number a new folder in `parent` takes first: the highest in use plus one. A seam: a test stands in for a
    listing that went stale."""
    return max(_numbers(parent, subphases), default=0) + 1


def _number_taken(parent, n, subphases=False):
    """Whether a folder in `parent` already uses the number n, whatever its slug (a seam, like `_next_number`)."""
    return n in _numbers(parent, subphases)


def _claim(parent, make_name, first, subphases=False):
    """`os.mkdir` the first folder `make_name(n)`, n from `first` up, whose number is free. A number another writer took
    since the listing is skipped by a fresh look, and one taken between that look and the mkdir makes the mkdir fail
    (it creates or fails, it never shares): both move on to the next number."""
    os.makedirs(str(parent), exist_ok=True)
    for n in range(first, first + 1000):
        if _number_taken(parent, n, subphases):
            continue
        d = Path(parent) / make_name(n)
        try:
            os.mkdir(str(d))
            return d
        except FileExistsError:
            continue
    raise StateError("no free number in %s after 1000 tries" % parent)


def _check_scope(scope):
    p = os.path.abspath(str(scope))
    if not _SCOPE_PATH.search(p.replace(os.sep, "/")):
        raise StateError("%s is not a scope: expected .fwx or .fwx/subprojects/<name>" % scope)
    return Path(p)


def _check_phase_dir(phase_dir, what):
    """`phase_dir` as a Path, if it is an existing, non-linked phase folder of a `.fwx/` tree; else StateError."""
    p = os.path.abspath(str(phase_dir))
    if not _PHASE_PATH.search(p.replace(os.sep, "/")):
        raise StateError("%s is not a phase folder (.fwx/milestones/vN/phases/NN-slug): %s refused" % (phase_dir, what))
    if os.path.islink(p) or not os.path.isdir(p):
        raise StateError("%s is not an existing phase folder: %s refused" % (phase_dir, what))
    return Path(p)


def new_milestone(scope, name=None):
    """Make `<scope>/milestones/vN/` with its MILESTONE.md and return it. `name` is `vN`, default the next number after
    the highest (v1 in an empty scope); one that exists is refused. `scope` is `.fwx` or `.fwx/subprojects/<name>`."""
    scope = _check_scope(scope)
    if name is not None and not _MILESTONE.match(name):
        raise StateError("bad milestone name %r: vN" % (name,))
    text = _read_template("MILESTONE.md")
    if name is None:
        name = "v%d" % (max((int(m[1:]) for m in milestones(scope)), default=0) + 1)
    d = scope / "milestones" / name
    os.makedirs(str(d.parent), exist_ok=True)
    try:
        os.mkdir(str(d))
    except FileExistsError:
        raise StateError("milestone %s already exists in %s" % (name, scope))
    _write_new(d / "MILESTONE.md", text.replace("<vN>", name))
    return d


def new_phase(slug, subproject=None, milestone=None, cwd=None, session=None):
    """Make the next phase folder `NN-slug` of the scope's milestone, with `context.md` and the headers of
    `decisions.tsv` and `audit.tsv`, and bind the session to it (when there is a session id). Returns the folder.
    Missing pieces are made: `.fwx/` with PROJECT.md, the subproject folder, milestone v1. The scope is `subproject`, or
    else the one the session is bound to, or else the root: a forgotten argument never drops a session out of its
    subproject. `milestone` defaults to the highest and must exist."""
    _check_slug(slug)
    if milestone is not None and not _MILESTONE.match(milestone):
        raise StateError("bad milestone name %r: vN" % (milestone,))
    bound = read_session(cwd, session)
    if subproject is None and bound:
        subproject = bound["subproject"]
    root = plan_root(cwd)
    for wroot in phase_worktrees(cwd) if root.parent == Path(config.main_checkout(cwd)) else []:
        for sub in [None] + subprojects(wroot):
            for p in open_phases(scope_root(wroot, sub)):
                raise StateError("the phase %s is open in the worktree %s: continue it there, or close it, before starting another"
                                 % (p.name, wroot.parent))
    scope = scope_root(root, subproject)
    texts = {n: _read_template(n) for n in ("PROJECT.md", "MILESTONE.md", "phase/context.md")}  # all of them, before any folder
    if not root.exists():
        os.makedirs(str(root))
        _write_new(root / "PROJECT.md", texts["PROJECT.md"])
    m = milestone or current_milestone(scope)
    if m is None:
        m = new_milestone(scope).name
    elif not (scope / "milestones" / m).is_dir():
        raise StateError("milestone %s does not exist in %s: `fwx state new-milestone` makes it" % (m, scope))
    parent = scope / "milestones" / m / "phases"
    d = _claim(parent, lambda n: "%02d-%s" % (n, slug), _next_number(parent))
    _write_new(d / "context.md", texts["phase/context.md"].replace("<phase folder name>", d.name))
    _new_tsv(d / "decisions.tsv", DECISION_COLUMNS)
    _new_tsv(d / "audit.tsv", AUDIT_COLUMNS)
    if session_id(session) is not None:
        write_session(cwd, session, subproject=subproject, phase_dir=d)
    return d


def new_subphase(phase_dir, slug):
    """Make `<phase>/<NN>.<M>-<slug>/` with the next M, a `plan.md` for its internal plans and the header of its
    `audit.tsv`; returns it. Only a phase folder `NN-slug` takes subphases (not a converted `NN.M-slug`)."""
    _check_slug(slug)
    phase = _check_phase_dir(phase_dir, "new subphase")
    nn = re.match(r"\d+", phase.name)
    if not re.match(r"\d+-", phase.name):
        raise StateError("%s is a converted NN.M phase: it takes no subphases" % phase)
    text = _read_template("phase/plan.md")
    d = _claim(phase, lambda m: "%s.%d-%s" % (nn.group(0), m, slug), _next_number(phase, True), True)
    _write_new(d / "plan.md", text)
    _new_tsv(d / "audit.tsv", AUDIT_COLUMNS)
    return d


def cancel_phase(phase_dir):
    """Delete a phase folder whose discuss was cancelled, and nothing else, and unbind the sessions that pointed to it
    (their subproject stays). Refused, with nothing deleted, when the folder is not a phase of a `.fwx/` tree, is a link,
    or holds `premortem.md` or `plan.md`: the discuss closed, and the record is kept."""
    phase = _check_phase_dir(phase_dir, "cancel")
    for f in ("premortem.md", "plan.md"):
        if (phase / f).exists():
            raise StateError("%s holds %s: the discuss already closed, so the phase is kept, not cancelled" % (phase, f))
    base = os.path.dirname(str(phase).replace(os.sep, "/").split("/" + PLAN_DIR + "/")[0] + "/" + PLAN_DIR)
    stored = os.path.relpath(str(phase), base or os.sep)
    sessions = sessions_dir(str(phase))
    shutil.rmtree(str(phase))
    try:
        names = sorted(os.listdir(sessions))
    except OSError:
        return
    for n in names:
        if not n.endswith(".json") or n.endswith(".budget.json"):
            continue
        try:
            with open(os.path.join(sessions, n), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("phase_dir") == stored:
            _put_session(sessions, n[:-5], data.get("subproject"), None)


def _length_warning(lines, target):
    return ["%d lines, target %d" % (lines, target)] if lines > target else []


def _read_text(path):
    try:
        with open(str(path), encoding="utf-8") as f:
            return f.read(), None
    except OSError as e:
        return None, "%s cannot be read (%s)" % (path, e.strerror)


def check_state(path):
    """`(errors, warnings)` of a `state.md`: a file that is missing or empty is an error; more than STATE_LINES lines is
    a warning only (short is wanted, but a long file is not refused)."""
    text, err = _read_text(path)
    if err:
        return [err], []
    if not text.strip():
        return ["%s is empty" % path], []
    return [], _length_warning(len(text.splitlines()), STATE_LINES)


def check_report(path):
    """`(errors, warnings)` of a phase report: an error when it does not cite the sha of the last `evidence` row of the
    `audit.tsv` next to it (the full sha, or an abbreviation of 7 or more hex digits), or when that file has no such row;
    more than REPORT_LINES lines is a warning only."""
    text, err = _read_text(path)
    if err:
        return [err], []
    rows = [r for r in read_rows(os.path.join(os.path.dirname(os.path.abspath(str(path))), "audit.tsv")) if r.get("kind") == "evidence"]
    errors = []
    if not rows:
        errors.append("%s: audit.tsv has no evidence row, so the report has no evidence to cite" % path)
    else:
        sha = rows[-1].get("sha", "")
        cited = bool(sha) and (sha in text or any(sha.lower().startswith(t.lower())
                                                  for t in re.findall(r"\b[0-9A-Fa-f]{7,40}\b", text)))
        if not cited:
            errors.append("%s does not cite the sha of the last evidence row (%s)" % (path, sha[:12] or "empty"))
    return errors, _length_warning(len(text.splitlines()), REPORT_LINES)
