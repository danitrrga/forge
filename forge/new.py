"""forge new NAME: a project made from the terminal.

`forge new PATH` on an existing directory registers it (forge/cli.py cmd_new). When the argument is no
directory, it is the NAME of a project to make, and this module makes it: its folder under `projects_dir` (config/forge.json)
or `--path`, `git init`, `.gitignore` first, a one-line README.md, the project file, the project's skill_keep.extras row,
and `forge sync --apply NAME`. Without --apply it prints the plan and writes nothing.

A missing answer never leaves a half-made project: every answer is checked, and every missing one named in one error,
before the first write. A failure after that removes what this run made (and only that); a failed sync does not, because
the project is by then complete and registered, and the exit says what to run.

Only the folder of the project and forge's own project files are written. Never a CLAUDE.md, never anything outside
`projects_dir` or `--path`. Never inside the forge checkout, and in a toy HOME never outside its world.

Which of the two an argument is: written as a path (a `/`, or a leading `.` or `~`) it is a directory to register; a bare word
that is no directory here is a name to make; a bare word that is a directory here is registered, and the first line says so
(with a flag that belongs to making, it is refused instead).

Two runs at once take turns: the checks are repeated and the files written under one lock (STATE/new.lock, an flock the
kernel frees when its holder dies), so the folder is claimed by one run and forge.json is read again before its row is added.
TERM, INT and HUP during --apply roll back like a failure."""
import contextlib
import fcntl
import json
import os
import pwd
import re
import shutil
import signal
import subprocess
import time

from forge import framework, lib

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\Z")  # \Z, not $: `$` also matches before one trailing newline

# The stacks, as data the next unit moves into files: the .gitignore text and the README text of each ({name} is the project's).
GENERIC_GITIGNORE = """# secrets
.env
.env.*
!.env.example

# editors
.idea/
.vscode/
*.swp
*~

# OS
.DS_Store
Thumbs.db
"""
STACKS = {"generic": {"gitignore": GENERIC_GITIGNORE, "readme": "# {name}\n"}}


def path_like(arg):
    """Whether `arg` is written as a path (a name never is): it holds a separator or starts with . or ~."""
    return "/" in arg or os.sep in arg or arg[:1] in (".", "~")


def creation_flags(a):
    """Whether a flag that belongs to making a project was given."""
    return a.parent_dir is not None or a.stack is not None or a.framework or a.yes or a.apply


def route(a):
    """What `forge new ARG` does with ARG: None means register the directory (cmd_new goes on), a number is the exit code
    of a run that is already over (a project made, or a refusal)."""
    arg = a.path
    isdir = os.path.isdir(os.path.expanduser(arg))
    if path_like(arg):
        if isdir and creation_flags(a):
            return refuse(2, "%s is a directory, so forge new registers it, and --path, --stack, --framework, --yes and --apply "
                             "belong to making a project from a name" % arg)
        if not isdir and creation_flags(a):
            return refuse(1, "%s is not a directory (a path is only ever registered; to make a project give its name alone, "
                             "and --path DIR for where)" % arg)
        return None
    if not isdir:
        return create(a)
    here = os.path.realpath(arg)
    for name, prof in sorted(lib.projects().items()):
        if prof.get("project_path") and os.path.realpath(os.path.expanduser(prof["project_path"])) == here:
            return refuse(1, "%s already exists here (./%s) and is registered as the project %s (config/projects/%s.claude.json)"
                          % (arg, arg, name, name))
    if creation_flags(a):
        return refuse(2, "./%s exists here, so it is not made again. To register it: forge new ./%s. To make a new project "
                         "named %s elsewhere: run forge new from another folder, or give --path DIR" % (arg, arg, arg))
    print("forge new: ./%s exists here, registering it (nothing is created; to create a new project named %s elsewhere, "
          "run it from another folder or give --path)" % (arg, arg))
    return None


def refuse(code, text):
    print("! forge new: %s" % text)
    return code


def write_file(undo, folder, filename, text):
    path = os.path.join(folder, filename)
    undo.append(("file", path))  # first: a write cut short by a signal still rolls back (rollback skips a file that is not there)
    lib.write_text(path, text)
    print("wrote  %s" % path)


def git_init(folder):
    try:
        subprocess.run(["git", "-C", folder, "init", "-q"], check=True, capture_output=True, text=True, env=lib.git_env())
    except FileNotFoundError:
        raise OSError("git init failed: git is not on PATH")
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip().splitlines()
        raise OSError("git init failed: %s" % (detail[-1] if detail else "exit %d" % e.returncode))
    print("ran    git init")


def rollback(steps):
    """Takes out what this run made, newest first. A folder only while it is empty: it never removes what it did not put there."""
    stuck = []
    for kind, path in reversed(steps):
        try:
            if kind == "file":
                os.unlink(path)
            elif kind == "tree":
                shutil.rmtree(path)
            else:
                os.rmdir(path)
            lib.record("rmtree" if kind == "tree" else "unlink", path)
        except FileNotFoundError:
            pass
        except OSError:
            stuck.append(path)
    if stuck:
        print("! forge new: could not remove %s -- remove by hand" % ", ".join(stuck))


@contextlib.contextmanager
def creation_lock(timeout=60):
    """One `forge new` at a time on this machine, from the checks to the last file. An flock on a file that stays: a run that
    dies frees it, so no stale lock is ever left to remove. Waiting past `timeout` is a TimeoutError."""
    os.makedirs(lib.STATE, exist_ok=True)
    with open(os.path.join(lib.STATE, "new.lock"), "a") as fh:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError("another forge new still holds %s after %ds" % (fh.name, timeout))
                time.sleep(0.1)
        yield


@contextlib.contextmanager
def stopped_means_rollback():
    """TERM, INT and HUP end the run as an exception, so what it made is taken out like after a failure."""
    def stop(signum, frame):
        raise SystemExit(128 + signum)
    old = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        yield
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


def skills_doc(key):
    """(config/forge.json read afresh with `key` in its skill_keep.extras, whether it was missing there), or (None, None) when
    skill_keep or its extras is not a JSON object."""
    lib.settings.cache_clear()
    doc = lib.settings()
    table = doc.setdefault("skill_keep", {})
    extras = table.setdefault("extras", {}) if isinstance(table, dict) else None
    if not isinstance(extras, dict):
        return None, None
    row = key not in extras
    extras.setdefault(key, [])
    return doc, row


def target_error(target):
    """Why `target` cannot be the project's folder, or None (also when it is an empty folder that is already there)."""
    if os.path.islink(target):
        return "%s is a link, and forge new does not write through one" % target
    if os.path.lexists(target):
        if not os.path.isdir(target):
            return "%s exists and is not a folder" % target
        if os.listdir(target):
            return ("%s exists and is not empty, so nothing is written into it (if it is a project to register: forge new %s)"
                    % (target, target))
    return None


def world_error(target):
    """In a toy HOME (one that is not the uid's own) a project is made inside its world only: may_write() looks at the projects
    that exist, and this one does not exist yet. Same rule as there, for the new folder."""
    try:
        real_home = pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        return "uid %d has no passwd entry, so whether HOME is a sandbox is unknown" % os.getuid()
    if os.path.realpath(lib.HOME) == os.path.realpath(real_home):
        return None
    world = os.path.dirname(os.path.realpath(lib.ROOT)) + os.sep
    if not (os.path.realpath(target) + os.sep).startswith(world):
        return "HOME is a sandbox (%s) and %s is outside its world (%s)" % (lib.HOME, target, world)
    return None


def create(a):
    """The creation side of `forge new ARG`, ARG being a name. Exit 0 made (or planned), 1 the world refuses or a step failed,
    2 an answer is wrong or missing."""
    from forge import cli  # at call time: forge/cli.py imports this module
    name = a.path
    if a.name or a.writes_tracked_files:
        return refuse(2, "--name and --writes-tracked-files register an existing directory, and %s is not one" % name)
    if not KEBAB.match(name):
        return refuse(2, "%r is not a project name (lowercase letters and digits, single dashes between them; "
                         "it cannot start with @ or -)" % name)
    problems = []
    if a.stack is None:
        problems.append("--stack is missing (one of: %s)" % ", ".join(sorted(STACKS)))
    elif a.stack not in STACKS:
        problems.append("--stack %r is not a stack (one of: %s)" % (a.stack, ", ".join(sorted(STACKS))))
    parent = None
    if a.parent_dir is not None:
        if not a.parent_dir.strip():
            return refuse(2, "--path is empty: give the folder to make the project in")
        parent = os.path.abspath(os.path.expanduser(a.parent_dir))
        source = "--path %s" % a.parent_dir
    else:
        configured = lib.settings().get("projects_dir")
        source = "projects_dir"
        if configured is None:
            problems.append("no folder to make it in: pass --path DIR or set projects_dir in config/forge.json")
        elif not isinstance(configured, str) or not os.path.isabs(os.path.expanduser(configured)):
            problems.append("projects_dir in config/forge.json must be an absolute path or start with ~ (it is %r)" % (configured,))
        else:
            parent = os.path.expanduser(configured)
    if parent is not None and not os.path.isdir(parent):
        problems.append("%s is not a directory (it is not made for you)" % source)
        parent = None
    if problems:
        return refuse(2, "nothing written, %s (no directory %s here: to register a directory, give its path)" % ("; ".join(problems), name))

    parent = os.path.realpath(parent)
    target = os.path.join(parent, name)
    if (target + os.sep).startswith(os.path.realpath(lib.ROOT) + os.sep):
        return refuse(2, "%s is inside the forge checkout (%s): a project is never made there" % (target, lib.ROOT))
    why = world_error(target)
    if why:
        return refuse(1, "%s -- nothing written" % why)
    key = "%s.claude.json" % name
    project_file = os.path.join(lib.PROJECTS, key)
    if os.path.lexists(project_file):
        return refuse(1, "%s is already registered (config/projects/%s)" % (name, key))
    why = target_error(target)
    if why:
        return refuse(1, why)
    exists = os.path.lexists(target)
    doc, row = skills_doc(key)
    if doc is None:
        return refuse(1, "config/forge.json skill_keep (or its extras) is not a JSON object -- fix it by hand first")
    project = json.loads(cli.example_text("project.claude.json"))
    project.update(project=name, project_path=target, writes_tracked_files=False)
    if a.framework:
        project["framework"] = True
        why = lib.project_error(project) or framework.plan(project, name).error
        if why:
            return refuse(2, "nothing written, --framework would make a project every forge sync refuses: %s" % why)

    print("forge new %s: %s" % (name, "APPLY" if a.apply else "PLAN, nothing written (--apply makes it)"))
    print("  folder      %s%s" % (target, " (exists, empty)" if exists else ""))
    print("  .gitignore  stack %s, written first" % a.stack)
    print("  git init, README.md")
    print("  project     config/projects/%s%s" % (key, " (framework on)" if a.framework else ""))
    print("  skills row  config/forge.json skill_keep.extras %s" % ("gets %s" % key if row else "already has %s" % key))
    print("  then        forge sync --apply %s" % name)
    if not a.apply:
        return 0
    ok, why = lib.may_write()
    if not ok:
        print(why)
        return 1

    undo = []
    try:
        with stopped_means_rollback(), creation_lock():
            # Under the lock again: another run may have made this name, or taken the folder, since the checks above.
            why = ("%s is registered" % name if os.path.lexists(project_file) else None) or target_error(target)
            if why:
                return refuse(2, "another forge new got there first: %s" % why)
            exists = os.path.lexists(target)
            doc, row = skills_doc(key)  # read again: another run may have added its row to forge.json meanwhile
            if doc is None:
                raise OSError("config/forge.json skill_keep (or its extras) is not a JSON object")
            if not exists:
                os.mkdir(target)
                undo.append(("dir", target))  # before anything else that can fail or be interrupted
                lib.record("mkdir", target)
                print("made   %s/" % target)
            stack = STACKS[a.stack]  # looked up here, after the folder: the check above is what keeps a missing stack from getting this far
            write_file(undo, target, ".gitignore", stack["gitignore"])
            undo.append(("tree", os.path.join(target, ".git")))
            git_init(target)
            text = stack["readme"].format(name=name)
            write_file(undo, target, "README.md", text)
            undo.append(("file", project_file))  # absent until the write: checked above, under the lock
            lib.write_text(project_file, lib.dumps(project) + "\n")
            print("wrote  %s" % os.path.relpath(project_file, lib.ROOT))
            if row:
                lib.write_text(lib.SETTINGS, lib.dumps(doc) + "\n")  # atomic: when it fails, forge.json is as it was
                print("wrote  config/forge.json (skill_keep.extras row %s)" % key)
    except BaseException as e:
        made = bool(undo)
        rollback(undo)
        if not isinstance(e, Exception):
            print("! forge new: stopped%s" % (" -- what this run made was removed" if made else ""))
            raise
        print("! forge new: %s%s" % (e, " -- what this run made was removed" if made else ""))
        return 2 if isinstance(e, TimeoutError) else 1
    print(flush=True)
    code = lib.run(["bin/forge", "sync", "--apply", name]).returncode
    if code:
        print("! forge new: %s is made and registered, but forge sync --apply %s failed (exit %d) -- fix the cause and run that again"
              % (name, name, code))
    return code
