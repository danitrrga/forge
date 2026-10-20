"""What every forge component shares: where forge is, the profiles, reads and writes, the git
helpers, a run's scope and the write guard, one lock, one result format."""
import collections
import contextlib
import copy
import fcntl
import functools
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".local", "state", "forge")
LOCK = os.path.join(STATE, "sync.lock")
JOURNAL = os.path.join(STATE, "journal.log")
JOURNAL_KEEP = 10000
PROFILES = os.path.join(ROOT, "config", "profiles")
# Codex's own convention for relocating ~/.codex. memory_doctor.py honoured it while the generator
# wrote ~/.codex/hooks.json regardless, so the two could read and write different files.
CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
SETTINGS = os.path.join(ROOT, "config", "forge.json")
# The names `on()` accepts: what a stranger's forge may switch off (docs/portable-design.md section 5).
INTEGRATIONS = ("codex", "gsd", "hindsight", "caveman")


@functools.lru_cache(maxsize=None)
def _settings(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        sys.exit("! config/forge.json missing -- run bin/forge init")
    except Exception as e:
        sys.exit("! config/forge.json unreadable (%s)" % e)
    if not isinstance(doc, dict):
        sys.exit("! config/forge.json unreadable (top level is %s, not an object)" % type(doc).__name__)
    return doc


def settings():
    """config/forge.json, the one data file the engine reads (docs/portable-design.md section 4),
    parsed once per path. Missing or unreadable is an exit 1 with a `!` line, never {}: an engine
    that read {} would switch every integration off and write from nothing. Each caller gets its own
    copy, so one that expands a table in place does not hand the next an expanded one. Not expanded
    here: `~`, `<ROOT>` and `@NAME` belong to the reader of the table that carries them."""
    return copy.deepcopy(_settings(SETTINGS))


settings.cache_clear = _settings.cache_clear


def on(name):
    """Whether the integration `name` is switched on: the key is the JSON true, and anything else,
    absent included, is off. A name that is not in INTEGRATIONS is a ValueError, so a typo in a
    caller does not read as a quiet off."""
    if name not in INTEGRATIONS:
        raise ValueError("unknown integration %r (one of %s)" % (name, ", ".join(INTEGRATIONS)))
    table = settings().get("integrations")
    return isinstance(table, dict) and table.get(name) is True


def gsd_patched():
    """Whether GSD is forge's own patched, staged copy: the key `gsd_patches` is the JSON true, and
    anything else, absent included, is off. Off is a stranger's GSD, installed by GSD's own installer
    (pnpm dlx) and left alone by sync_gsd_runtime.py. Meaningful only with the `gsd` integration on."""
    return settings().get("gsd_patches") is True


def codex_harness():
    """Whether Codex is configured like Claude Code: the integration `codex` is on AND the key
    `codex_harness` is the JSON true (anything else, absent included, is off). On, forge writes its hook
    rows into ~/.codex/hooks.json and each project's MCP servers into .codex/config.toml; off, it writes
    neither and takes out only what it wrote itself. The key is not read while codex is off."""
    return on("codex") and settings().get("codex_harness") is True


def profiles(skipped=None):
    """{project name: profile} for every config/profiles/*.claude.json. A directory that is there
    but cannot be listed raises: glob swallowed the PermissionError and answered "no projects".
    One that is not there has none (a toy checkout, e.g. test_rotate_secret.py's).

    A profile that cannot be read or is not a JSON object is left out: every caller calls .get on
    each profile, and one `null` file raised AttributeError in may_write and resolve_project, so
    in every session start. Left out is not silent: each one is appended to `skipped` as
    (file name, reason), which session start shows, and the generator names it too ('! could not
    read'). So is one with a field of the wrong type (profile_error): a `project_path` of 5 raised
    TypeError in resolve_project's realpath, in every session start too."""
    out = {}
    try:
        names = sorted(os.listdir(PROFILES))
    except FileNotFoundError:
        names = []
    for n in names:
        if n.endswith(".claude.json"):
            try:
                prof = read_owned(os.path.join(PROFILES, n))
                why = profile_error(prof)
            except Unreadable as e:
                why = e.reason
            if why is None:
                out[n[:-len(".claude.json")]] = prof
            elif skipped is not None:
                skipped.append((n, why))
    return out


# The type of every profile field the generator reads, when the field is present: absent is each
# reader's own default, and null is never one. A pair is a container and the type of its items (a
# list) or of its values (an object); a frozenset is a choice of types. profile_error checks a
# profile against it once, so the components can trust what they .get(); a field forge starts
# reading gets its row here.
PROFILE_FIELDS = {
    "project": str, "project_path": str,
    "servers": (list, str), "skills_keep": (list, str), "plugins_keep": (list, str),
    "mcpjson_approved": (list, str), "mcpjson_disabled": (list, str),
    "env": (dict, str), "permissions": dict, "hooks": dict,
    "frozen": bool, "writes_tracked_files": bool, "enableAllProjectMcpServers": bool, "command_guard": bool,
    "worktree_guard": frozenset({bool, dict}),
}
_TYPE_NAMES = {str: "string", bool: "boolean", list: "list", dict: "JSON object"}


def worktree_guard_on(prof):
    """Whether forge wires the worktree guard for this profile: `"worktree_guard": true`, or an
    object (its parameters, which hooks/worktree_guard.py reads) unless it says `"on": false`. An
    object with "on": false declares where the project's worktrees live without the guard."""
    v = prof.get("worktree_guard")
    return v is True or (isinstance(v, dict) and v.get("on", True) is True)


def profile_error(prof):
    """None when every PROFILE_FIELDS field `prof` carries has its type, else the first that does
    not, as "<field> is not a <type>"."""
    if not isinstance(prof, dict):
        return "the profile is not a JSON object"
    for field, kind in PROFILE_FIELDS.items():
        if field not in prof:
            continue
        if isinstance(kind, frozenset):
            if not isinstance(prof[field], tuple(kind)):
                return "%s is not a %s" % (field, " or a ".join(sorted(_TYPE_NAMES[k] for k in kind)))
            continue
        kind, item = kind if isinstance(kind, tuple) else (kind, None)
        v = prof[field]
        if not isinstance(v, kind) or (item and not all(isinstance(x, item) for x in (
                v.values() if isinstance(v, dict) else v))):
            return "%s is not a %s%s" % (field, _TYPE_NAMES[kind], " of %ss" % _TYPE_NAMES[item] if item else "")
    # `on` of a worktree_guard object is read as `is True`, so "true" or 1 would silently be off.
    wt = prof.get("worktree_guard")
    if isinstance(wt, dict) and "on" in wt and not isinstance(wt["on"], bool):
        return "worktree_guard.on is not a boolean"
    # A guard's command is `--project <project>` (skills.guard_command), and the hook reads the
    # profile or guard config by that name: without it sync wrote `--project None`.
    for guard, on in (("command_guard", prof.get("command_guard") is True), ("worktree_guard", worktree_guard_on(prof))):
        if on and not prof.get("project"):
            return "project is missing, and %s is on (its command names the project)" % guard
    return None


def short(path):
    """`path` with HOME written ~, the form every status line prints it in."""
    return path.replace(HOME, "~")


def dumps(data, ensure_ascii=False):
    """The JSON text forge compares documents in, to tell whether there is anything to write: the
    bytes write_json writes by default (two-space indent, non-ASCII kept, no trailing newline)."""
    return json.dumps(data, ensure_ascii=ensure_ascii, indent=2)


class Unreadable(ValueError):
    """A file forge merges into and rewrites whole, or must read to decide, could not be read: the
    caller leaves it alone. A ValueError, so may_write()'s `except (OSError, ValueError)` still
    refuses on one (no handler in the generator (forge/sync.py and its components) catches ValueError broadly). Callers print
    their own line from .path and .reason: each wording is output, and the path appears once."""

    def __init__(self, path, reason):
        super().__init__("%s unreadable (%s)" % (path, reason))
        self.path, self.reason = path, reason


def read_json(path, default=None, quiet=False):
    """A source forge reads and does not rewrite (the registry, a profile): missing is `default`
    ({} when None), and so is one that cannot be read or parsed, after a warning line -- one bad
    source must not stop the run. `quiet` drops the line, for a caller that must print nothing
    (a doctor's --hook). Never for a file forge merges into and writes back: that is read_owned."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default if default is not None else {}
    except Exception as e:
        if not quiet:
            print("  ! could not read %s: %s" % (path, e))
        return default if default is not None else {}


def read_owned(path, missing={}):
    """read_json for a file whose other keys belong to someone else (~/.claude.json, settings.json,
    ~/.codex/hooks.json, settings.local.json): missing is a copy of `missing` (callers mutate what
    they get, and the default is shared), anything else unreadable raises Unreadable, and the
    caller leaves the file alone. It used to be that a truncated ~/.claude.json came back from the
    lenient load() as {} and --apply wrote back only forge's keys -- oauthAccount, trust and every
    other project's history gone, with a once-ever .bak long stale. A top level that is not an
    object is unreadable too: a null ~/.claude.json crashed the run, and a null hooks.json was
    replaced whole. The exception read_owned caught is the Unreadable's __cause__."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return copy.copy(missing)
    except Exception as e:
        raise Unreadable(path, str(e)) from e
    if not isinstance(doc, dict):
        raise Unreadable(path, "top level is %s, not an object" % type(doc).__name__)
    return doc


def hook_entries(doc):
    """Every hook a hooks.json manifest registers, as ([(event, group index, hook index, hook)],
    malformed). The indexes are positions in the ORIGINAL arrays -- Codex builds its trust key
    "<manifest>:<event>:<group>:<hook>" from them -- so a bad entry is skipped and counted, never
    filtered out first. A falsy `hooks`, event or group list is no entries; a value of the wrong
    type at any depth counts as one malformed entry and is not descended into. The caller decides
    what a nonzero count means (a doctor: the manifest is unreadable)."""
    out, bad = [], 0
    if not isinstance(doc, dict):
        return out, 1
    hooks = doc.get("hooks")
    if not hooks:
        return out, 0
    if not isinstance(hooks, dict):
        return out, 1
    for event, groups in hooks.items():
        if not groups:
            continue
        if not isinstance(groups, list):
            bad += 1
            continue
        for gi, group in enumerate(groups):
            if not isinstance(group, dict):
                bad += 1
                continue
            entries = group.get("hooks")
            if not entries:
                continue
            if not isinstance(entries, list):
                bad += 1
                continue
            for hi, hook in enumerate(entries):
                if isinstance(hook, dict):
                    out.append((event, gi, hi, hook))
                else:
                    bad += 1
    return out, bad


def record(what, path):
    """One line, `what` and `path`, appended to the file FORGE_WRITE_LOG names, for a change forge
    just made on disk: wrote, chmod, link, unlink, mkdir or rmtree. forge session-start and
    forge sync --apply set it for each step, and journal() keeps what it noted; session-start also
    tells the user what the step wrote from it: it once guessed from
    the printed text, and a session start could rewrite a project's settings.local.json and say
    nothing. Nothing is printed, so every generator's output stays what it was. Unset, nothing
    happens. It never raises: the change it records has already been made.

    A path that is not UTF-8 (a file name Python surrogate-escaped) is written backslash-escaped,
    caf\\udce9 for the byte 0xe9: a display form, the original bytes not recoverable from it. Not
    surrogateescape: that writes the raw bytes back, and forge/cli.py's cmd_session_start reads
    the log as strict UTF-8, so the crash would only move there. Until attack round 3 such a path
    raised UnicodeEncodeError here, after the write it recorded."""
    log = os.environ.get("FORGE_WRITE_LOG")
    if log:
        try:
            with open(log, "a", encoding="utf-8", errors="backslashreplace") as fh:
                fh.write("%s %s\n" % (what, path))
        except OSError:
            pass


def journal(lines, cmd, step):
    """`lines`, the (what, path) pairs lib.record noted for one step, appended to JOURNAL as
    `<ISO8601 local time> <cmd> <step> <what> <path>`, one per change; the last JOURNAL_KEEP lines
    are kept. Paths only, never content, so never a secret. `step` has its spaces made hyphens, so
    the first four fields are single words and the path is the rest of the line. Nothing to note,
    or a checkout that may not write (may_write), writes nothing: a dry-run has no lines and never
    creates the journal. It never raises on a disk error, as record never does. Callers hold the sync lock, so the read-append-write is not racing."""
    if not lines or not may_write()[0]:
        return
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    stamp = stamp[:-2] + ":" + stamp[-2:]
    step = "-".join(step.split()) or "-"
    new = ["%s %s %s %s %s" % (stamp, cmd, step, what, str(path).replace("\n", "\\n")) for what, path in lines]
    try:
        try:
            with open(JOURNAL, encoding="utf-8", errors="replace") as fh:
                old = fh.read().split("\n")
            if old[-1] == "":
                old.pop()
        except FileNotFoundError:
            old = []
        write_text(JOURNAL, "\n".join((old + new)[-JOURNAL_KEEP:]) + "\n")
    except OSError:
        pass  # like record: the changes it notes are already made, and a full disk must not fail the run


def chmod(path, mode):
    """os.chmod, recorded."""
    os.chmod(path, mode)
    record("chmod", path)


def symlink(target, link):
    """os.symlink, recorded. A link that must never be briefly absent is replace_symlink's."""
    os.symlink(target, link)
    record("link", os.path.abspath(link))


def unlink(path):
    """os.unlink, recorded (the link's own path, never where it pointed)."""
    os.unlink(path)
    record("unlink", os.path.abspath(path))


def makedirs(path):
    """os.makedirs(exist_ok=True), recorded when it made `path`: for a directory that is the change
    itself (a memory store, a staging tree). One made only to hold a file or link needs no line of
    its own; that file's line says it."""
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        record("mkdir", os.path.abspath(path))


def _create(path, mode):
    """A descriptor on a new `path` that has `mode` from its first byte (umask applied, as
    open() does). Creating the file at the umask default and chmodding it once it held the text
    left a secret-bearing temp file 644 in between. Any leftover at the name is removed first;
    O_EXCL never writes through a link planted there."""
    _remove(path)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else mode)


def _put(tmp, text, mode, fsync, check):
    """`text` into a new `tmp` with `mode`, synced to disk when `fsync`, then shown to `check`."""
    with open(_create(tmp, mode), "w", encoding="utf-8") as fh:
        fh.write(text)
        if fsync:
            fh.flush()
            os.fsync(fh.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    if check is not None:
        check(tmp)


def holds(path, text):
    """Whether `path` already holds `text`, byte for byte: newline="" keeps a CRLF file from
    reading as its LF text. A file that is missing, unreadable, a directory or not UTF-8 does not."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read() == text
    except (OSError, UnicodeDecodeError):
        return False


def write_text(path, text, mode=None, backup=False, fsync=False, check=None):
    """`path` holds `text`, or keeps what it held: written to a temp file and renamed over it.
    Extracted from sync_agent_config.py's write_atomic() so the Codex TOML writer got
    the same crash/retry safety net as every JSON config, instead of the bare os.replace() it
    started with (an adversarial-testing haiku agent caught the gap: a cross-device or
    permission-denied os.replace() there left a `.tmp` file behind and crashed with no retry),
    and moved here in S1 of docs/audits/simplify.md. The caller validates `text` (write_json
    does); this only makes the write itself atomic.

    `mode` is applied to the temp file BEFORE the swap, never to the live file afterwards:
    chmod-ing after os.replace() leaves a window, however short, where a file holding real
    tokens is readable by anyone on the machine. The rendered hindsight config has been written
    0600 since it was introduced; ~/.claude.json carries resolved secrets for every MCP server and
    was once 644 -- seven of the twenty-eight values in credentials/secrets.json
    appear in it in plain text. None is the umask default. "keep" is the target's own mode, 0600
    when there is no target (rotate_secret.py's rule for credentials/, which has no .bak).

    `backup` keeps a once-ever `path.bak` of the first content replaced, with the stricter mode.
    `fsync` syncs the temp file before the rename and the directory after it: old content or new
    survives a power cut, not an empty file (rotate_secret.py's secrets.json, whose loss makes
    every SessionStart generator exit 1). `check(tmp)` sees the written temp file before it is
    renamed into place, and raises to refuse it (register_project.py validates a profile that
    way); the retries rename the same bytes without checking them again. Whatever raises, no
    temp file is left behind: until S1 a write that raised left `path.tmp.<pid>`."""
    # One policy for a `path` that is a symlink: its target is replaced and the link kept, as
    # scripts/tools/rotate_secret.py's own writer did before it came here. Replacing the link with
    # a regular file silently detaches, say, a dotfiles-managed ~/.claude.json from its
    # repository, and the target is the file the link says is meant. A secret-bearing file whose
    # link could be planted checks where it resolves before calling this (write_codex_project_mcp).
    path = os.path.realpath(path)
    if mode == "keep":
        try:
            mode = os.stat(path).st_mode & 0o777
        except FileNotFoundError:
            mode = 0o600
    bak = path + ".bak"
    # A .bak that is itself a link is never copied to, chmodded or written through: its target is
    # someone else's file, and os.chmod follows links.
    bak_ours = backup and not os.path.islink(bak)
    if mode is not None and bak_ours and os.path.exists(bak) and os.stat(bak).st_mode & 0o777 & ~mode:
        # A .bak made before its file was written with a mode (~/.hindsight/coding-agent.json.bak
        # was 644, holding the bearer). Checked before the unchanged-content return:
        # so was every project's .codex/config.toml.bak was 644 beside a current file.
        try:
            chmod(bak, mode)
        except OSError:
            pass
    # Unchanged content is not rewritten: most runs change nothing, and a rewrite still costs a
    # temp file, a rename and an mtime that tells every watcher the file moved. holds() is
    # byte-exact: with universal newlines a target holding b'a\r\nb' read as 'a\nb' and was never
    # rewritten to it, and CRLF text was rewritten on every run (attack round 3).
    if holds(path, text):
        try:
            if mode is None or (os.stat(path).st_mode & 0o777) == mode:
                return
        except OSError:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if bak_ours and os.path.exists(path) and not os.path.exists(bak):
        # The once-ever backup of a secret-bearing file holds the same tokens. Found in use:
        # ~/.claude.json.bak was 644, because copyfile does not carry permissions.
        try:
            with open(path, "rb") as src, open(_create(bak, mode), "wb") as dst:
                shutil.copyfileobj(src, dst)
            if mode is not None:
                os.chmod(bak, mode)
            record("wrote", bak)
            from forge import owned  # lazily: owned imports lib
            owned.claim_backup(bak, True)  # write_text only runs for a real write; claim_backup asks may_write
        except Exception:
            pass
    # Suffixed with our own pid: two SessionStart runs racing on the same path (opening a second
    # editor window while the first is still starting up, e.g. VS Code and Antigravity together)
    # used to share one fixed ".tmp" name -- one process's os.replace() would rename the file out
    # from under the other's os.chmod(), which then raised FileNotFoundError. Reproduced
    # with two concurrent `claude` sessions.
    temps = ["%s.tmp.%d" % (path, os.getpid())]
    try:
        _put(temps[0], text, mode, fsync, check)
        try:
            os.replace(temps[0], path)
        except OSError:
            # WR-06: os.replace failed (e.g. cross-device / Windows sharing). NEVER re-open the live
            # file with "w" -- a crash mid-write truncates it and silently unwires whatever it
            # guards (fail-OPEN). Instead retry the ATOMIC swap via a second temp in the SAME dir,
            # then fail LOUDLY rather than risk a partial file.
            last_err = None
            for n in range(3):
                temps.append("%s.tmp%d.%d" % (path, n, os.getpid()))
                try:
                    _put(temps[-1], text, mode, fsync, None)
                    os.replace(temps[-1], path)  # atomic
                    break
                except OSError as e:
                    last_err = e
                    _remove(temps[-1])
            else:
                raise OSError("write_text: could not atomically replace %s (no in-place write to "
                              "avoid a truncated file that would unwire whatever it guards): %s" % (path, last_err))
    finally:
        for t in temps:  # the one renamed into place is already gone; the others are ours (pid)
            _remove(t)
    if fsync:
        dfd = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    record("wrote", path)


def write_json(path, data, mode=None, backup=False, newline=False, ensure_ascii=False, check=None):
    """`data` as JSON through write_text: by default the bytes sync_agent_config.py's write_atomic
    wrote (dumps' form); json.dumps raises on anything it cannot serialise, before anything touches
    disk. `newline` ends the file with one,
    `ensure_ascii` escapes non-ASCII, for writers whose files have always had that form."""
    text = dumps(data, ensure_ascii) + ("\n" if newline else "")
    write_text(path, text, mode=mode, backup=backup, check=check)


def replace_symlink(target, link):
    """`link` -> `target`, swapped in through a temp link `link.tmp.<pid>` and os.replace, so there
    is no moment when `link` is absent (sync_system_doc.py's AGENTS.md swap). The unlink-then-
    symlink pairs in relink_skills.py and the codex skill mirror lose the link when
    symlink() then fails, and since 781b620 relink keeps going past that. A leftover at the temp
    name is removed first; whatever raises, no temp link is left. A real directory at `link` is
    never replaced: os.replace refuses it."""
    tmp = "%s.tmp.%d" % (link, os.getpid())
    _remove(tmp)
    os.symlink(target, tmp)
    try:
        os.replace(tmp, link)
    except BaseException:
        _remove(tmp)
        raise
    record("link", os.path.abspath(link))


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def git_dir(path):
    """(the nearest .git above path, whether it is a linked worktree's .git file), or (None, False)."""
    d = os.path.abspath(path)
    while True:
        g = os.path.join(d, ".git")
        if os.path.exists(g):
            return g, os.path.isfile(g)
        if d == os.path.dirname(d):
            return None, False
        d = os.path.dirname(d)


def in_git_repo(path):
    """True when path sits inside a git working tree. Walks up rather than shelling out to git:
    this runs once per profile on every SessionStart, and a subprocess per project to answer a
    question about a directory entry is not worth 18 forks."""
    return git_dir(path)[0] is not None


def git_ignores(path, rel):
    """True when git in `path` ignores `rel` (any pattern, not just a literal line)."""
    try:
        r = subprocess.run(["git", "-C", path, "check-ignore", "-q", "--", rel],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    return r.returncode == 0


def git_tracks(path, sub):
    """True if git has ANY tracked file under <path>/<sub>: a generated directory (safe to
    ignore) told from one whose contents someone committed on purpose. Fails closed -- where git
    cannot answer, the answer is "tracked", and the caller touches nothing."""
    try:
        out = subprocess.run(["git", "-C", path, "ls-files", "--", sub],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return True
    if out.returncode != 0:
        return True
    return bool(out.stdout.strip())


def _read_gitignore(path):
    """<path>/.gitignore's text, or None when there is none. One that cannot be read (not UTF-8,
    a directory) raises Unreadable: whether an entry is ignored is then unknown, so the project
    gets nothing under it. It used to abort the run before the next profile."""
    gi = os.path.join(path, ".gitignore")
    try:
        with open(gi, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable(gi, str(e)) from e


def _has_line(text, entry):
    return any(l.strip() in (entry, entry.rstrip("/")) for l in text.splitlines())


def gitignore_has(path, entry):
    """True when <path>/.gitignore already carries `entry` (or it without its trailing /). Checked
    before `git ls-files`, so the fork only happens in a project that still lacks the line (1 of 7
    when measured). A line in a .gitignore that is a symlink proves nothing: git does not read one
    (2.55: "warning: unable to access '.gitignore': Too many levels of symbolic links")."""
    if os.path.islink(os.path.join(path, ".gitignore")):
        return False
    cur = _read_gitignore(path)
    return cur is not None and _has_line(cur, entry)


def repo_owns_tracked_files(prof):
    """True when the profile says forge must never write a file git tracks in this project
    (`writes_tracked_files: false`). A project that opts out: its CLAUDE.md, AGENTS.md and
    .gitignore are versioned and owned by the repo, which must keep working without forge.
    Forge still writes the machine-local files the repo ignores."""
    return prof.get("writes_tracked_files") is False


def _git_out(ppath, *args):
    """What `git -C ppath <args>` prints without its final newline, or None when git cannot answer."""
    try:
        r = subprocess.run(["git", "-C", ppath] + list(args), capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def exclude_site(ppath, entry):
    """(the repository's info/exclude file, the line that hides `entry` there) for the project at `ppath`,
    or None when git does not answer. `--git-common-dir` is the main repository's directory for a linked
    worktree too (`--git-path` resolves a link before this could see it), and `--show-prefix` is where
    ppath sits in the repository, so a project that is a directory of a larger repository does not hide
    `entry` in all of it."""
    common = _git_out(ppath, "rev-parse", "--path-format=absolute", "--git-common-dir")
    prefix = _git_out(ppath, "rev-parse", "--show-prefix")
    if not common or prefix is None:
        return None
    return os.path.join(common, "info", "exclude"), "/" + prefix + entry


def _exclude_entry(apply, ppath, entry):
    """Add `entry`, anchored to the project's directory, to the repository's info/exclude (git's
    per-clone ignore file, which no commit carries) for a project whose .gitignore the repo owns.
    Returns the summary suffix ("" when the line is already there), or None when it cannot be done:
    git does not answer (exclude_site), or the file is a link (write_text would replace its target) or is
    not UTF-8; the caller then refuses as it always did."""
    site = exclude_site(ppath, entry)
    if site is None:
        return None
    ex, line = site
    if os.path.islink(ex):
        return None
    try:
        with open(ex, encoding="utf-8") as fh:
            cur = fh.read()
    except FileNotFoundError:
        cur = None
    except (OSError, UnicodeDecodeError):
        return None
    if cur is not None and _has_line(cur, line):
        return ""
    if not apply:
        return " +exclude(would add %s)" % line
    new = cur or ""
    if new and not new.endswith("\n"):
        new += "\n"
    new += line + "\n"
    os.makedirs(os.path.dirname(ex), exist_ok=True)
    write_text(ex, new, mode="keep" if cur is not None else None)
    return " +exclude(created)" if cur is None else " +exclude"


def ensure_ignored(apply, ppath, entry, repo_owned):
    """Idempotently ensure <ppath>/.gitignore blocks `entry` before this generator ever
    writes a secret into it. Returns (whether git ignores `entry` once this has run, a short
    suffix for the summary line, "" if already present); a caller writes nothing under `entry`
    when the first is False. One boolean, because callers used to test the suffix for a prefix
    and the symlinked-.gitignore refusal did not carry it, so the resolved-secret config.toml
    was written un-ignored anyway (found in an attack round). Same shape as sync_system_doc.py's
    ensure_gitignore().

    Used for two directories the generator owns: .codex/ (carries real tokens) and
    .agents/ (the Codex skill links). Both are regenerated on every SessionStart, so
    neither belongs in a repo -- the dual-agent setup is one machine's setup, not
    something a teammate cloning the repo needs or should see in a diff.

    A directory under no git repository gets nothing. Every profile was a checkout until the
    ~/dev one, which is a plain directory holding the other projects; writing a
    .gitignore there creates a file that no git will ever read, to hide a directory from a
    repository that does not exist."""
    if not in_git_repo(ppath):
        return True, " (no repo, no gitignore)"
    gi = os.path.join(ppath, ".gitignore")
    if repo_owned or os.path.islink(gi):
        # The repo owns its .gitignore. Its own ignore rules decide; when they do not cover the
        # generated path, a repo-owned project gets the line in .git/info/exclude (local, never
        # tracked: docs/portable-design.md section 5), and one that cannot get it is not written
        # at all rather than left to show up in git.
        # A .gitignore that is a symlink is never written through either (adversarial testing found it:
        # one pointing outside the project would edit a file elsewhere), and git
        # itself does not read one (2.55: "warning: unable to access '.gitignore': Too many
        # levels of symbolic links"), so only git's own answer counts.
        if gitignore_has(ppath, entry) or git_ignores(ppath, entry.rstrip("/")):
            return True, ""
        if repo_owned:
            added = _exclude_entry(apply, ppath, entry)
            if added is not None:
                return True, added
        why = (".gitignore is a symlink, which git does not read; it" if os.path.islink(gi)
               else "repo-owned .gitignore")
        return False, " !not-git-ignored(SKIPPED: %s does not ignore %s)" % (why, entry)
    cur = _read_gitignore(ppath)
    if cur is not None and _has_line(cur, entry):
        return True, ""
    if not apply:
        return True, " +gitignore(would add %s)" % entry
    new = cur or ""
    if new and not new.endswith("\n"):
        new += "\n"
    new += entry + "\n"
    # Atomic now; the mode is the one the old in-place write kept (the file's own, or the umask
    # default for a new one).
    write_text(gi, new, mode="keep" if os.path.exists(gi) else None)
    return True, " +gitignore(created)" if cur is None else " +gitignore"


def resolve_project(path):
    """The profile a session started in `path` belongs to, or None.

    The deepest profile whose project_path contains `path` wins (a project nested in another is its own, not
    the outer one). A linked worktree belongs to no profile: a session there must not write the
    main checkout's config. Neither does an unregistered repository nested inside a profile's
    directory, e.g. a new repo under ~/dev, which the catch-all `dev` profile would otherwise
    claim."""
    path = os.path.realpath(path)
    g, linked = git_dir(path)
    if linked:
        return None
    best = None
    for name, prof in profiles().items():
        pp = os.path.realpath(prof.get("project_path") or "/nonexistent")
        if (path == pp or path.startswith(pp + os.sep)) and (best is None or len(pp) > len(best[1])):
            best = (name, pp)
    if best is None:
        return None
    if g and len(os.path.dirname(g)) > len(best[1]):
        return None  # a repository of its own below the profile's directory
    return best[0]


# A hook command that runs some checkout's `forge session-start`; group 1 is that checkout. The end
# matters: `forge session-start-audit` is another command. installed_root and uninstall share it.
SESSION_START = re.compile(r"(\S+)/bin/forge session-start(?:\s|$)")


def installed_root():
    """The forge checkout this machine runs: the realpath of the one whose bin/forge the
    SessionStart hook in ~/.claude/settings.json calls (forge/hooks.py's USER_HOOKS row).
    None when there is no such checkout -- no settings.json, no forge entry (a fresh machine, or
    the sandbox harness's toy HOME before its first apply, which is what installs the hook), or an
    entry whose bin/forge is gone (forge relocated; the new checkout's apply repoints the hook).

    A settings.json that is there but cannot be read or parsed, or that names two checkouts,
    raises ValueError or OSError: which checkout is installed is then unknown, and guessing either
    way lets a copy write. may_write() refuses, the installed checkout included, until the file is
    fixed by hand -- which costs nothing forge could do anyway, since the generator already
    refuses to rewrite a settings.json it cannot parse (read_owned). A fresh machine is unaffected:
    it has no file, or one without the entry."""
    settings = os.path.join(HOME, ".claude", "settings.json")
    try:
        doc = read_owned(settings, missing=None)
    except Unreadable as e:  # each case keeps the text it had before read_owned
        if isinstance(e.__cause__, OSError):
            raise e.__cause__
        raise ValueError("%s is not valid JSON (%s)" % (settings, e.reason) if e.__cause__
                         else "%s is not a JSON object" % settings)
    if doc is None:
        return None

    def strings(x):  # every string under x, whatever shape the hooks are in
        x = list(x.values()) if isinstance(x, dict) else x
        return [s for v in x for s in strings(v)] if isinstance(x, list) else [x] if isinstance(x, str) else []
    roots = {os.path.realpath(m.group(1)) for m in (SESSION_START.search(s)
                                                     for s in strings(doc.get("hooks"))) if m}
    roots = sorted(r for r in roots if os.path.isfile(os.path.join(r, "bin", "forge")))
    if len(roots) > 1:
        raise ValueError("%s runs two checkouts: %s" % (settings, ", ".join(roots)))
    return roots[0] if roots else None


def may_write():
    """(whether this checkout may write, why not). On a machine where forge is installed only the
    installed checkout writes: every generated file names the checkout that wrote it. A linked
    worktree never does -- relink_skills run from one repointed all 176 skill links at it.
    Nor does a plain copy: two copies in /tmp rewrote ~20 projects' CLAUDE.md
    pointers with their own path, and one registered a project in master."""
    if git_dir(ROOT)[1]:
        return False, "forge: %s is a linked worktree -- nothing written; apply from the main checkout" % ROOT
    try:
        installed = installed_root()
    except (OSError, ValueError) as e:
        return False, ("forge: cannot tell which checkout this machine runs: %s -- nothing written; "
                       "fix it by hand" % e)
    if installed not in (None, os.path.realpath(ROOT)):
        return False, ("forge: %s is not the checkout this machine runs (%s) -- nothing written; apply from %s"
                       % (ROOT, installed, installed))
    # A toy HOME only writes a toy world. The incident's agents set HOME to a scratch dir, so no
    # settings.json named a checkout, while the copy's profiles still named the real projects. The
    # sandbox harness keeps forge/, home/ and projects/ side by side, which is the shape allowed.
    # (Under `unshare -r` the uid is 0, so the real HOME counts as a toy one there too.)
    # A uid with no passwd entry (a container, an unmapped namespace) has no real HOME to compare
    # with, so whether HOME is a toy one is unknown: refused, never the KeyError it raised before.
    try:
        real_home = pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        return False, ("forge: uid %d has no passwd entry, so whether HOME (%s) is a sandbox is unknown "
                       "-- nothing written" % (os.getuid(), HOME))
    if os.path.realpath(HOME) != os.path.realpath(real_home):
        world = os.path.dirname(os.path.realpath(ROOT)) + os.sep
        out = [n for n, p in profiles().items()
               if p.get("project_path") and not os.path.realpath(p["project_path"]).startswith(world)]
        if out:
            return False, ("forge: HOME is a sandbox (%s) but profiles point outside it (%s) -- nothing written"
                           % (HOME, ", ".join(out[:3])))
    return True, ""


def apply_allowed(applying):
    """`applying`, unless may_write() refuses: then the reason is printed and the run is a dry-run."""
    ok, why = may_write() if applying else (False, "")
    if why:
        print(why)
    return ok


def require_write():
    """Exit 1 with may_write()'s refusal, for a script whose apply must not fall through to a
    dry-run (apply_allowed downgrades to one instead)."""
    ok, why = may_write()
    if not ok:
        sys.exit(why)


# (project names to write, None meaning all; whether to write the user-scope files too).
# session_scope returns one, and context unpacks it into its Ctx.
Scope = collections.namedtuple("Scope", "only globals")


class Ctx(collections.namedtuple("Ctx", "apply only globals")):
    """One run's answer to "do I write, and what": `apply` is the flag already downgraded by the
    one may_write() call, `only` and `globals` are context's."""

    def wants(self, name):
        """Whether project `name` is in this run's scope."""
        return self.only is None or name in self.only


def _project_arg(argv):
    """(argv with --project=X split in two, the --project name or None). A missing or mistyped
    name exits: it used to scope the run to nobody and still print OK, which reads as proof that
    a sync ran. So does a second --project (index() took the first, argparse the last)."""
    argv = [p for a in argv for p in (a.split("=", 1) if a.startswith("--project=") else [a])]
    if argv.count("--project") > 1:
        sys.exit("forge: --project given more than once")
    if "--project" not in argv:
        return argv, None
    i = argv.index("--project")
    name = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
    known = profiles()
    if name not in known:
        sys.exit("forge: unknown project: %s (known: %s)" % (name or "(none given)", ", ".join(sorted(known))))
    return argv, name


def session_scope(name):
    """The Scope of a session whose project resolved to `name` (None: nobody's, so nothing): its
    own project, and in forge's session the user-scope files too."""
    return Scope({name} if name else set(), name == "forge")


def context(argv, flag="--apply", invert=False):
    """A generator's Ctx from its argv: applying is `flag` given (absent, with `invert`:
    relink_skills applies unless --dry-run), downgraded by the one may_write() call, which prints
    the refusal once. sync_agent_config called may_write() a second time to downgrade its APPLY,
    on the reasoning that two writes happen before any profile is looked at (the ~/.claude.json
    chmod and the key relocations). Only the chmod needed it: a refused apply writes nothing and
    looks at no project, and the relocations are already skipped by the Ctx's only=set().

    When a SessionStart hook runs a generator without --project/--all, the session's own project
    is the whole scope (session_scope): Claude Code sets CLAUDE_PROJECT_DIR for hooks only, never
    for a Bash command. It once happened that every forge or sibling-project session start rewrote all 19
    projects -- hot-reloading another project's sessions -- and a session in a forge worktree ran
    master's generators over all of them."""
    applying = (flag in argv) != invert
    argv, name = _project_arg(argv)
    # Only the installed checkout writes, however it is run (may_write). Dry-runs stay allowed.
    if applying and not apply_allowed(True):
        return Ctx(False, set(), False)
    if name is not None:
        return Ctx(applying, {name}, False)
    session = os.environ.get("CLAUDE_PROJECT_DIR")
    if "--all" in argv or not session:
        return Ctx(applying, None, True)
    return Ctx(applying, *session_scope(resolve_project(session)))


# agent_config's exit rule: a line whose first non-space character is '!'.
BANG = re.compile(r"^\s*!")


class Rule:
    """The run's stdout, for agent_config's exit rule: every write passes straight through, and a
    finished line whose first non-space character is '!' sets `failed`."""

    def __init__(self, out):
        self.out, self.rest, self.failed = out, "", False

    def write(self, text):
        self.out.write(text)
        *done, self.rest = (self.rest + text).split("\n")
        self.failed = self.failed or any(BANG.match(l) for l in done)
        return len(text)

    def flush(self):
        self.out.flush()

    def __getattr__(self, name):
        return getattr(self.out, name)


# level is PASS, WARN or FAIL; a FAIL's detail ends with the command that fixes it.
Result = collections.namedtuple("Result", "level name detail")


@contextlib.contextmanager
def lock(timeout=60):
    """One sync at a time on this machine, whichever checkout or session starts it. Claude Code
    runs a hook group's commands in parallel, which is how two generators came to race on the
    same files (the PID-suffixed temp files in write_text are the scar)."""
    os.makedirs(STATE, exist_ok=True)
    with open(LOCK, "a") as f:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError("another forge sync still holds %s after %ds" % (LOCK, timeout))
                time.sleep(0.2)
        yield


def _lowest_cpu_priority():
    os.setpriority(os.PRIO_PROCESS, 0, 19)  # absolute, whatever the parent's nice is; raising it needs no privilege


def run_low(argv, **kw):
    """subprocess.run(argv, **kw) at the lowest CPU priority (nice 19) and, where `ionice` exists, in the
    idle I/O class: the one place forge starts a heavy child that must not take the machine from a
    foreground tool (forge test; a voice detector once went from 0.3 s to 50+ s under it).
    The priority is inherited by the child's own children."""
    ionice = shutil.which("ionice")
    return subprocess.run(([ionice, "-c3"] if ionice else []) + list(argv), preexec_fn=_lowest_cpu_priority, **kw)


def run(args, capture=False, env=None, low=False):
    """A forge script, run with this interpreter from ROOT (and `env`, when given); low=True: run_low."""
    return (run_low if low else subprocess.run)([sys.executable] + args, cwd=ROOT, text=True,
                                                capture_output=capture, env=env)


# The exit code of a test that could not run (automake's "skipped"): shown as a WARN.
NOT_RUN = 77
# The `forge session-start` hook's timeout in seconds: forge.hooks writes it into the hook row and
# cli.memory_budget fits Hindsight's wait inside it, so the two cannot drift apart.
SESSION_START_TIMEOUT = 60


def report(results):
    """One line per result, then the summary line /gm and /sec-audit grep for. Exit 1 on a FAIL."""
    for r in results:
        print("%-4s  %-22s %s" % (r.level, r.name, r.detail))
    n = collections.Counter(r.level for r in results)
    print("SUMMARY: %d passed, %d warnings, %d failures" % (n["PASS"], n["WARN"], n["FAIL"]))
    return 1 if n["FAIL"] else 0
