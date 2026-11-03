"""The base-context file every agent of a phase is handed at start, and its check: the one writer is `build` (and `seal`, for a
file written by hand).

The file is `<git-common-dir>/fwx/context-base/<phase>.md`, where `<phase>` is the folder's path relative to the checkout that
holds `.fwx/`, with `/` turned into `__`. It is outside the work tree on purpose: `.fwx/` is committed before every wave and a
derived file would dirty it, and every worktree reads the same place. Its parts, in order: the mark (`# Base context · <sha8 of
everything after this line>`), `data/context-map.md` whole, `## Goal` (Intent and What success means of `context.md`, each cut
at 1000 units with a pointer), `## Files` (the absolute paths that exist), `## Decided` (the `decision` column of the `chosen`
and `approved` rows of `decisions.tsv`, none of the open ones) and the `<!-- built ... -->` line the check compares.

Every length is counted in UTF-16 code units (`units`): Claude Code persists an `additionalContext` of more than 10,000 of them
instead of delivering it (measured), and a byte count would refuse a text of 6000 `é`. The cap here is 9000, a warning from 6000.

Imports only the standard library, config and state.
"""
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from fwx import config, state

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "data" / "context-map.md"
TABLE = ROOT / "data" / "context-base.tsv"
COMMANDS = ROOT / "lib" / "fwx" / "commands"
CAP = 9000
WARN = 6000
SECTION = 1000
DECIDED = 2500
DECIDED_LINE = 160
CLOSED = ("chosen", "approved")
MARK = "# Base context · "
_MARK = re.compile(r"# Base context · ([0-9a-f]{8})\Z")
_BUILT = re.compile(r"<!-- built stage=(\S+) context=(\S+) decisions=(\S+) map=(\S+) -->\Z")
_SOURCE = re.compile(r"<!-- source: (.+) @([0-9a-f]{8}) -->\Z")
_FWX_CMD = re.compile(r"`fwx ([a-z][a-z0-9-]*)")
_SECTIONS = ("map", "map+decided", "none")
_NOT_CURRENT = ("stale", "edited", "no mark", "missing")  # the problems that make `refresh` build again


class ContextBaseError(Exception):
    """Something the builder or the check refuses; the message says why and nothing was written."""


def units(s):
    """Length in UTF-16 code units, what Claude Code's 10,000 limit counts: an emoji is 2, an `é` is 1."""
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def cut(s, n):
    """`s` cut at no more than `n` units, never inside a character."""
    if units(s) <= n:
        return s
    out, used = [], 0
    for ch in s:
        u = 2 if ord(ch) > 0xFFFF else 1
        if used + u > n:
            break
        out.append(ch)
        used += u
    return "".join(out)


def sha8(data):
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogatepass")
    return hashlib.sha256(data).hexdigest()[:8]


def _read_bytes(path):
    try:
        with open(str(path), "rb") as f:
            return f.read()
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return None


def _text(path):
    b = _read_bytes(path)
    return None if b is None else b.decode("utf-8", "replace")


def _sha_of(path):
    b = _read_bytes(path)
    return "none" if b is None else sha8(b)


# ---- where things are ---------------------------------------------------------------------------------------------

def _folder(folder):
    f = os.path.realpath(str(folder))
    if not os.path.isdir(f):
        raise ContextBaseError("%s is not a folder" % folder)
    return f


def _phase_name(folder):
    root = os.path.realpath(str(state.plan_root(folder)))
    if not folder.startswith(root + os.sep):
        raise ContextBaseError("%s is not inside the .fwx folder of its repository" % folder)
    return os.path.relpath(folder, os.path.dirname(root)).replace(os.sep, "__")


def base_path(folder):
    """Where the base of a phase, a subphase or a job folder lives: `<git-common-dir>/fwx/context-base/<phase>.md`, the same
    from every worktree. Creates nothing."""
    f = _folder(folder)
    name = _phase_name(f)
    return os.path.join(os.path.dirname(state.sessions_dir(f)), "context-base", name + ".md")


def sections_for(agent_type, table=None):
    """What an `agent_type` gets (`map`, `map+decided` or `none`) from data/context-base.tsv: the exact row, else the `*` row.
    A table with no `*` row, a missing one and an unknown value are errors, never a guess."""
    path = str(table or TABLE)
    text = _text(path)
    if text is None:
        raise ContextBaseError("the table of cases %s is not there" % path)
    rows = {}
    for line in text.splitlines()[1:]:
        cells = line.split("\t")
        if cells and cells[0]:
            rows[cells[0]] = cells[1] if len(cells) > 1 else ""
    if "*" not in rows:
        raise ContextBaseError("%s: no default row (a `*` row is required)" % path)
    got = rows.get(agent_type, rows["*"])
    if got not in _SECTIONS:
        raise ContextBaseError("%s: sections %r is not one of %s" % (path, got, ", ".join(_SECTIONS)))
    return got


# ---- build --------------------------------------------------------------------------------------------------------

def _section(context, title):
    m = re.search(r"^## %s[ \t]*\n(.*?)(?=^## |\Z)" % re.escape(title), context, re.M | re.S)
    return m.group(1).strip() if m else None


def _goal(context_path):
    context = _text(context_path)
    if context is None:
        return ""
    parts = ["## Goal"]
    for title in ("Intent", "What success means"):
        body = _section(context, title)
        if body is None:
            body = "(missing from context.md)"
        elif units(body) > SECTION:
            body = cut(body, SECTION).rstrip() + "\n[cut: the rest is in %s]" % context_path
        parts.append("### %s\n%s" % (title, body))
    return "\n".join(parts) + "\n"


def _files(folder):
    root = state.plan_root(folder)
    paths = state.phase_paths(folder)
    found = [root / "PROJECT.md", root / "durable", paths["context"], paths["decisions"], paths["research"], paths["demo"],
             Path(config.main_checkout(folder)) / ".claude" / "fwx.json"]
    return "## Files\n" + "".join("- %s\n" % p for p in found if os.path.exists(str(p)))


def _decided(decisions_path):
    lines = []
    for row in state.read_rows(decisions_path):
        if row.get("support") in CLOSED and row.get("decision", "").strip():
            lines.append("- " + cut(" ".join(row["decision"].split()), DECIDED_LINE))
    if not lines:
        return "## Decided\n(nothing closed yet)\n"
    if sum(units(l) + 1 for l in lines) > DECIDED:
        return "## Decided\n%d closed decisions, too many to list: read %s\n" % (len(lines), decisions_path)
    return "## Decided\n" + "\n".join(lines) + "\n"


def render(folder, map_path=None):
    """The text of the base file for `folder` and what went into it: `(text, {"map": n, "goal": n, "decided": n})` in units."""
    f = _folder(folder)
    _phase_name(f)
    map_text = _text(map_path or MAP)
    if map_text is None:
        raise ContextBaseError("the map %s is not there" % (map_path or MAP))
    paths = state.phase_paths(f)
    goal, files, decided = _goal(paths["context"]), _files(f), _decided(paths["decisions"])
    built = "<!-- built stage=%s context=%s decisions=%s map=%s -->\n" % (
        state.last_stage(f) or "discuss", _sha_of(paths["context"]), _sha_of(paths["decisions"]), _sha_of(map_path or MAP))
    rest = "\n".join(b for b in (map_text.rstrip("\n") + "\n", goal, files, decided, built) if b)
    text = MARK + sha8(rest) + "\n" + rest
    return text, {"map": units(map_text), "goal": units(goal), "decided": units(decided)}


def build(folder, map_path=None):
    """Write the base of `folder` when its content changed: `{path, units, map, goal, decided, written, warning}`. Over CAP units
    it raises and the previous file stays; from WARN a `warning` string says so. The write is a temporary file renamed."""
    text, parts = render(folder, map_path)
    n = units(text)
    if n > CAP:
        raise ContextBaseError("%d over the cap of %d: shorten data/context-map.md or the Intent section" % (n, CAP))
    path = base_path(folder)
    written = _text(path) != text
    if written:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    warning = "warning: %d units, from %d the base grows long" % (n, WARN) if n >= WARN else ""
    return dict(parts, path=path, units=n, written=written, warning=warning)


def refresh(folder, map_path=None):
    """`build` when the base is missing or stale, otherwise nothing; the same dict, `written` False when it left the file."""
    path = base_path(folder)
    if _text(path) is None or [p for p in inspect(path, folder=folder, map_path=map_path)[1] if p.startswith(_NOT_CURRENT)]:
        return build(folder, map_path)
    text, parts = render(folder, map_path)
    return dict(parts, path=path, units=units(text), written=False, warning="")


# ---- seal ---------------------------------------------------------------------------------------------------------

def seal(path, source=None):
    """Put the mark on the first line of a file written by hand, and with `source` the `<!-- source: <name> @<sha8> -->` line at
    its end, so that `check` can say the source moved on. Returns the new text. Sealing twice gives the same file."""
    text = _text(path)
    if text is None:
        raise ContextBaseError("%s is not there" % path)
    lines = text.split("\n")
    if _MARK.match(lines[0]):
        lines = lines[1:]
    if lines and lines[-1] == "":
        lines.pop()
    if source is not None:
        digest = _read_bytes(source)
        if digest is None:
            raise ContextBaseError("the source %s is not there" % source)
        lines = [l for l in lines if not _SOURCE.match(l)]
        lines.append("<!-- source: %s @%s -->" % (os.path.normpath(str(source)), sha8(digest)))
    rest = "\n".join(lines) + "\n"
    out = MARK + sha8(rest) + "\n" + rest
    if out != text:
        with open(str(path), "w", encoding="utf-8", newline="") as fh:
            fh.write(out)
    return out


# ---- check --------------------------------------------------------------------------------------------------------

def commands():
    """The subcommands of bin/fwx: the files of lib/fwx/commands/, an underscore a dash."""
    return {f[:-3].replace("_", "-") for f in os.listdir(str(COMMANDS)) if f.endswith(".py") and not f.startswith("_")}


def _unknown_commands(text):
    known = commands()
    return ["unknown command: fwx %s" % c for c in dict.fromkeys(_FWX_CMD.findall(text)) if c not in known]


def inspect(path, folder=None, map_path=None, source=None):
    """Look at one base file: `(units, [problem...])`. Always: the mark against the rest, the cap. With a `folder`: the `built`
    line against the folder's stage, context.md, decisions.tsv and the map, and the commands the map names. With `source`: the
    source marker against that file. A file with no problem is current."""
    text = _text(path)
    if text is None:
        return 0, ["missing: no base at %s" % path]
    problems = []
    n = units(text)
    if n > CAP:
        problems.append("over the cap of %d: %d units" % (CAP, n))
    first, _, rest = text.partition("\n")
    m = _MARK.match(first)
    if not m:
        problems.append("no mark on the first line: `fwx context-base seal` it, or build it")
    elif m.group(1) != sha8(rest):
        problems.append("edited since sealed: the mark %s is not the sha of the rest (%s)" % (m.group(1), sha8(rest)))
    lines = [l for l in rest.splitlines() if l.strip()]
    if folder is not None:
        paths = state.phase_paths(folder)
        b = _BUILT.match(lines[-1]) if lines else None
        if not b:
            problems.append("stale: no `built` line, build it again")
        else:
            now_stage = state.last_stage(folder) or "discuss"
            if b.group(1) != now_stage:
                problems.append("stale: stage is %s, the base was built at %s" % (now_stage, b.group(1)))
            for name, then, now in (("context.md", b.group(2), _sha_of(paths["context"])),
                                    ("decisions.tsv", b.group(3), _sha_of(paths["decisions"])),
                                    ("data/context-map.md", b.group(4), _sha_of(map_path or MAP))):
                if then != now:
                    problems.append("stale: %s changed since the build" % name)
        map_text = _text(map_path or MAP)
        problems += _unknown_commands(map_text or "")
    else:
        problems += _unknown_commands(text)
    if source is not None:
        sm = next((_SOURCE.match(l) for l in reversed(lines) if _SOURCE.match(l)), None)
        digest = _read_bytes(source)
        if digest is None:
            problems.append("the source %s is not there" % source)
        elif not sm:
            problems.append("stale: the file has no source marker: seal it with --source")
        elif sm.group(2) != sha8(digest):
            problems.append("stale: %s changed since the file was sealed" % sm.group(1))
    return n, problems


def hook_problems(command, first_line, cwd):
    """Run the hook `command` with a toy SubagentStart input: it must hand `general-purpose` the file's first line and
    `Explore` nothing. Returns the problems found."""
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return ["hook: cannot read the command (%s)" % e]
    problems = []
    for agent, wants in (("general-purpose", True), ("Explore", False)):
        stdin = json.dumps({"hook_event_name": "SubagentStart", "agent_type": agent, "session_id": "toy-session",
                            "agent_id": "toy-agent", "cwd": cwd})
        try:
            r = subprocess.run(argv, input=stdin, capture_output=True, text=True, cwd=cwd, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            problems.append("hook: %s: cannot run (%s)" % (agent, e))
            continue
        if r.returncode:
            problems.append("hook: %s: exit %d: %s" % (agent, r.returncode, (r.stderr.strip().splitlines() or [""])[0]))
            continue
        context = ""
        if r.stdout.strip():
            try:
                context = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
            except (ValueError, KeyError, TypeError):
                problems.append("hook: %s: the output is not a SubagentStart hookSpecificOutput" % agent)
                continue
        if wants and context.split("\n", 1)[0] != first_line:
            problems.append("hook: %s got %s, not the base" % (agent, "nothing" if not context else "other text"))
        if not wants and context:
            problems.append("hook: %s got text, it should get nothing" % agent)
    return problems
