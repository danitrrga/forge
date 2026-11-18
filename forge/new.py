"""forge new NAME: a project made from the terminal.

`forge new PATH` on an existing directory registers it (forge/cli.py cmd_new). When the argument is no
directory, it is the NAME of a project to make, and this module makes it: its folder under `projects_dir` (config/forge.json)
or `--path`, `git init`, `.gitignore` first, a one-line README.md, the project file, the project's skill_keep.extras row,
and `forge sync --apply NAME`. Without --apply it prints the plan and writes nothing.

A missing answer never leaves a half-made project: every answer is checked, and every missing one named in one error,
before the first write. A failure after that removes what this run made (and only that); a failed sync does not, because
the project is by then complete and registered, and the exit says what to run.

Only the folder of the project and forge's own project files are written. Never a CLAUDE.md, never anything outside
`projects_dir` or `--path`."""
import json
import os
import re
import shutil
import subprocess

from forge import lib

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

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


def refuse(code, text):
    print("! forge new: %s" % text)
    return code


def write_file(undo, folder, filename, text):
    path = os.path.join(folder, filename)
    lib.write_text(path, text)
    undo.append(("file", path))
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
        return refuse(2, "nothing written, %s" % "; ".join(problems))

    parent = os.path.realpath(parent)
    target = os.path.join(parent, name)
    key = "%s.claude.json" % name
    project_file = os.path.join(lib.PROJECTS, key)
    if os.path.lexists(project_file):
        return refuse(1, "%s is already registered (config/projects/%s)" % (name, key))
    exists = os.path.lexists(target)
    if os.path.islink(target):
        return refuse(1, "%s is a link, and forge new does not write through one" % target)
    if exists:
        if not os.path.isdir(target):
            return refuse(1, "%s exists and is not a folder" % target)
        if os.listdir(target):
            return refuse(1, "%s exists and is not empty, so nothing is written into it" % target)
    doc = lib.settings()
    table = doc.setdefault("skill_keep", {})
    extras = table.setdefault("extras", {}) if isinstance(table, dict) else None
    if not isinstance(extras, dict):
        return refuse(1, "config/forge.json skill_keep (or its extras) is not a JSON object -- fix it by hand first")
    row = key not in extras
    extras.setdefault(key, [])
    project = json.loads(cli.example_text("project.claude.json"))
    project.update(project=name, project_path=target, writes_tracked_files=False)
    if a.framework:
        project["framework"] = True

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
        if not exists:
            os.mkdir(target)
            lib.record("mkdir", target)
            undo.append(("dir", target))
            print("made   %s/" % target)
        stack = STACKS[a.stack]  # looked up here, after the folder: the check above is what keeps a missing stack from getting this far
        write_file(undo, target, ".gitignore", stack["gitignore"])
        undo.append(("tree", os.path.join(target, ".git")))
        git_init(target)
        text = stack["readme"].format(name=name)
        write_file(undo, target, "README.md", text)
        lib.write_text(project_file, lib.dumps(project) + "\n")
        undo.append(("file", project_file))
        print("wrote  %s" % os.path.relpath(project_file, lib.ROOT))
        if row:
            lib.write_text(lib.SETTINGS, lib.dumps(doc) + "\n")  # atomic: when it fails, forge.json is as it was
            print("wrote  config/forge.json (skill_keep.extras row %s)" % key)
    except BaseException as e:
        rollback(undo)
        if not isinstance(e, Exception):
            raise
        print("! forge new: %s -- what this run made was removed" % e)
        return 1
    print(flush=True)
    code = lib.run(["bin/forge", "sync", "--apply", name]).returncode
    if code:
        print("! forge new: %s is made and registered, but forge sync --apply %s failed (exit %d) -- fix the cause and run that again"
              % (name, name, code))
    return code
