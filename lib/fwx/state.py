"""The state of `.fwx/`: where it is, its subproject, milestone, phase and subphase folders, the session file, and the
TSV writers. The single writer of audit.tsv is `append_audit`; nothing else in the framework writes that file.

referent: pstack plugins/pstack/skills/show-me-your-work/scripts/log.sh @36885ea, rules reimplemented in Python (tab,
newline and CR become a space; a quote in front of a cell that starts with `= + - @ "`; one write per row), not copied.

Every path resolves against the main checkout (config.main_checkout), never against the folder the caller stands in:
a linked worktree has none of the ignored files. The one exception is `plan_root` in a repository whose default
branch is protected and whose `.fwx/` is tracked: there the session's own worktree holds the live copy and reaches
the default branch through the phase's pull request. The signal is `project.default_branch_protected: true` in
`.claude/fwx.json`; without it `plan_root` never leaves the main checkout.

Reading creates nothing. Rejections raise StateError before anything is written. A path outside a git repository is
config.ConfigError, whose message names the fix.

Imports only the standard library and config: `fwx statusline` has to finish in under 100 ms.
"""
import contextlib
import io
import json
import os
import re
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

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_MILESTONE = re.compile(r"v(\d+)\Z")
_PHASE = re.compile(r"\d+(\.\d+)*-.+\Z")  # NN-slug, NN.M-slug, NN.M.K-slug
_SUBPHASE = re.compile(r"\d+\.\d+-.+\Z")  # NN.M-slug inside a phase
_STAGE_WORD = re.compile(r"[a-z][a-z-]*(\s|\Z)")
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_FORMULA = "=+-@\""


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


def _sessions_dir(cwd):
    config.main_checkout(cwd)  # ConfigError outside a repository, with its message
    r = _git(os.getcwd() if cwd is None else cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.join(r.stdout.strip(), "fwx", "sessions")


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
    d = _sessions_dir(cwd)
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


def resolve(cwd=None, session=None):
    """Where the session is: `{main_checkout, plan_root, has_subprojects, subproject, milestone, phase_dir, subphases,
    candidates, paths}`, every path a string, nothing written. The subproject and the phase come from the session file;
    with no phase bound (or a bound one that is gone) the only open phase of the scope's current milestone is the
    phase, and with several or none `phase_dir` is None and `candidates` lists the open ones. Binding is the caller's."""
    main = config.main_checkout(cwd)
    root = plan_root(cwd)
    bound = read_session(cwd, session)
    subproject = bound["subproject"] if bound else None
    scope = scope_root(root, subproject)
    candidates = [str(p) for p in open_phases(scope)]
    phase, milestone = None, current_milestone(scope)
    if bound and bound["phase_dir"]:
        p = os.path.join(str(root.parent), bound["phase_dir"])
        if os.path.isdir(p):
            phase, milestone = p, os.path.basename(os.path.dirname(os.path.dirname(p)))
    if phase is None and len(candidates) == 1:
        phase = candidates[0]
    return {"main_checkout": main, "plan_root": str(root), "has_subprojects": has_subprojects(root),
            "subproject": subproject, "milestone": milestone, "phase_dir": phase,
            "subphases": [str(p) for p in subphases(phase)] if phase else [],
            "candidates": candidates,
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
