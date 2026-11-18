"""forge new NAME: a project made from the terminal.

`forge new PATH` on an existing directory registers it (forge/cli.py cmd_new). When the argument is no
directory, it is the NAME of a project to make, and this module makes it: its folder under `projects_dir` (config/forge.json)
or `--path`, `git init`, `.gitignore` first, a one-line README.md, the project file, the project's skill_keep.extras row,
and `forge sync --apply NAME`. Without --apply it prints the plan and writes nothing.

A missing answer never leaves a half-made project: every answer is checked, and every missing one named in one error,
before the first write. A failure after that removes what this run made (and only that); a failed sync does not, because
the project is by then complete and registered, and the exit says what to run.

What the project gets is asked or given by flags (forge/ask.py: profiles, skills, servers, memory, what the stack asks); the answers add the
profile definitions under config/profile-defs/, the project's `profiles` row and servers, and the words of its skill_keep.extras row, all
under the same all-or-nothing rule. `forge new @NAME`, run in a project's folder, makes one profile of it (create_profile): the definition,
when there is none, and the `profiles` row; a profile row is read at a session start, so it syncs nothing.

Only the folder of the project and forge's own project files are written. Never a CLAUDE.md, never anything outside
`projects_dir` or `--path`. Never inside the forge checkout, and in a toy HOME never outside its world.

Which of the two an argument is: written as a path (a `/`, or a leading `.` or `~`) it is a directory to register; a bare word
that is no directory here is a name to make; a bare word that is a directory here is registered, and the first line says so
(with a flag that belongs to making, it is refused instead).

Two runs at once take turns: the checks are repeated and the files written under one lock (STATE/new.lock, an flock the
kernel frees when its holder dies), so the folder is claimed by one run and forge.json is read again before its row is added.
TERM, INT and HUP during --apply roll back like a failure."""
import contextlib
import copy
import fcntl
import json
import os
import pwd
import re
import shutil
import signal
import subprocess
import time

from forge import ask, configure, framework, lib, profiles, suggest

INTERRUPTED = "interrupted (Ctrl-C) -- nothing written"  # exit 130, the shell's code for it
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\Z")  # \Z, not $: `$` also matches before one trailing newline

# A stack is a folder of the checkout's examples/stacks/: stack.json and gitignore, each complete on its own (no code or text is
# shared between stacks). The files are copied as they are with {{KEY}} replaced; the README text has no folder, so it is here.
STACKS_DIR = os.path.join(lib.ROOT, "examples", "stacks")
STACK_KEYS = ("description", "servers", "plugins", "checks", "skill_sets")
PLACEHOLDER = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}")
README = "# {{NAME}}\n"


def stack_names():
    return sorted(n for n in os.listdir(STACKS_DIR) if os.path.isdir(os.path.join(STACKS_DIR, n))) if os.path.isdir(STACKS_DIR) else []


def substitute(stack, files, values):
    """(files with every {{KEY}} replaced, errors, warnings). `files` is {file name: text}, `values` {KEY: text}. A {{KEY}} with
    no value is an error (`unresolved {{KEY}} in stacks/<stack>/<file>`) and is left in the text, which is then never written;
    a value that no file used is a warning."""
    out, errors, used = {}, [], set()
    for fn, text in files.items():
        unresolved = []

        def put(m):
            if m.group(1) in values:
                used.add(m.group(1))
                return values[m.group(1)]
            if m.group(0) not in unresolved:
                unresolved.append(m.group(0))
            return m.group(0)
        out[fn] = PLACEHOLDER.sub(put, text)
        if unresolved:
            errors.extend("unresolved %s in stacks/%s/%s" % (u, stack, fn) for u in unresolved)
    unused = sorted(set(values) - used)
    warnings = ["{{%s}} was given and nothing in stacks/%s used it" % (k, stack) for k in unused] if unused else []
    return out, errors, warnings


def load_stack(stack, name):
    """(stack.json read and checked, {gitignore, README.md} with the project's NAME in, warnings) of one stack. ValueError, with one
    line, when a file is missing or wrong or a {{KEY}} has no value: that is found before anything is written."""
    where = "stacks/%s" % stack
    texts = {}
    for fn in ("stack.json", "gitignore"):
        try:
            with open(os.path.join(STACKS_DIR, stack, fn), encoding="utf-8") as fh:
                texts[fn] = fh.read()
        except (OSError, ValueError) as e:
            raise ValueError("%s/%s cannot be read: %s" % (where, fn, e))
    try:
        doc = json.loads(texts["stack.json"])
    except ValueError as e:
        raise ValueError("%s/stack.json is not valid JSON: %s" % (where, e))
    if not isinstance(doc, dict):
        raise ValueError("%s/stack.json is not a JSON object" % where)
    missing = [k for k in STACK_KEYS if k not in doc]
    if missing:
        raise ValueError("%s/stack.json lacks %s" % (where, ", ".join(missing)))
    extra = sorted(set(doc) - set(STACK_KEYS))
    if extra:
        raise ValueError("%s/stack.json has %s, which is no key of a stack (the keys: %s)" % (where, ", ".join(extra), ", ".join(STACK_KEYS)))
    if not isinstance(doc["description"], str) or not all(isinstance(doc[k], list) and all(isinstance(x, str) for x in doc[k]) for k in STACK_KEYS[1:]):
        raise ValueError("%s/stack.json: description is a text and servers, plugins, checks and skill_sets are lists of texts" % where)
    files, errors, warnings = substitute(stack, {"gitignore": texts["gitignore"], "README.md": README}, {"NAME": name})
    if errors:
        raise ValueError("; ".join(errors))
    return doc, files, warnings


def path_like(arg):
    """Whether `arg` is written as a path (a name never is): it holds a separator or starts with . or ~."""
    return "/" in arg or os.sep in arg or arg[:1] in (".", "~")


def answer_flags(a):
    """Whether a flag that answers one of the questions (forge/ask.py) was given."""
    return any(getattr(a, k, None) for k in ("profiles", "sets", "skills", "server", "memory", "check", "plugin", "ui", "command_guard"))


def creation_flags(a):
    """Whether a flag that belongs to making a project was given."""
    return a.parent_dir is not None or a.stack is not None or a.framework or a.yes or a.apply or answer_flags(a)


def route(a):
    """What `forge new ARG` does with ARG: None means register the directory (cmd_new goes on), a number is the exit code
    of a run that is already over (a project made, or a refusal)."""
    arg = a.path
    if arg.startswith("@"):
        return create_profile(a)
    isdir = os.path.isdir(os.path.expanduser(arg))
    if path_like(arg):
        if isdir and creation_flags(a):
            return refuse(2, "%s is a directory, so forge new registers it, and --path, --stack, --framework, --yes, --apply and the answer flags "
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
    for kind, path, *rest in reversed(steps):
        try:
            if kind == "restore":  # a file that existed: put back what it held
                lib.write_text(path, rest[0])
                lib.record("wrote", path)
                continue
            elif kind == "file":
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


def confirmed(asker, a):
    """Whether the owner, who has just answered questions in a terminal, says yes to writing them (without --apply). False without a
    terminal or with --yes: that is the dry-run it always was."""
    if not asker.interactive or a.yes:
        return False
    if configure._ask("make it? [y/N] "):
        return True
    print("nothing written")
    return False


def unanswered(a, name, stack, asker):
    """The problems of the answers when nothing can be asked (no terminal, or --yes): what the flags give, checked as create() checks
    it, so one error names these together with the missing --stack or folder. [] when nothing is wrong or forge.json cannot be read."""
    doc, _ = skills_doc("%s.claude.json" % name)
    if doc is None:
        return []
    from forge import cli
    ctx = ask.Context(name, doc, json.loads(cli.example_text("project.claude.json")), None if stack is None else dict(stack, name=a.stack))
    ans, problems = ask.gather(a, ctx, asker)
    return problems if problems else ask.apply(ctx, ans)[2]


def describe(ctx, ans, rows, new_defs):
    """The lines of the plan that show each answer (none when nothing beyond the old plan was answered)."""
    out = []
    for scope, target in ans.targets.items():
        whole, names = ask.skill_items(ctx, target)
        what = ["@" + s for s in whole] + names
        if scope is None and not (what or target["servers"]):
            continue
        if scope is not None:
            row = rows.get(scope, {})
            out.append("  profile     @%s: %s" % (scope, "definition config/profile-defs/%s.json is made" % scope if scope in new_defs
                                                    else "definition config/profile-defs/%s.json is used as it is" % scope))
            out.append("              skills %s; servers %s" % (", ".join(row.get("skills", [])) or "none",
                                                              ", ".join("%s=%s" % kv for kv in row.get("servers", {}).items()) or "none"))
        else:
            out.append("  skills      %s" % (", ".join(what) or "none"))
            out.append("  servers     %s" % (", ".join(sorted(set(target["servers"]))) or "none"))
    if ans.profiles:
        out.append("  default     the project's own lists are the profile %r; the profiles are offered beside it" % ask.DEFAULT_LABEL)
    if ans.memory:
        out.append("  memory      %s (servers %s)" % (ans.memory, ", ".join(ask.MEMORY[ans.memory])))
    st = ans.stack or {}
    if st.get("checks"):
        out.append("  checks      %s" % ", ".join(st["checks"]))
    if st.get("plugins"):
        out.append("  plugins     only %s (besides the common ones)" % ", ".join(st["plugins"]))
    if st.get("ui") or st.get("command_guard"):
        out.append("  options     %s" % ", ".join(k for k in ("ui", "command_guard") if st.get(k)))
    return out


def write_definitions(undo, new_defs):
    """config/profile-defs/<name>.json for each new definition, its folder first when it is not there. Each is on the undo list before
    the call that can fail."""
    if not new_defs:
        return
    folder = os.path.dirname(profiles.definition_path("x"))
    if not os.path.isdir(folder):
        undo.append(("dir", folder))
        os.mkdir(folder)
        lib.record("mkdir", folder)
    for pname, d in new_defs.items():
        write_file(undo, folder, pname + ".json", lib.dumps(d) + "\n")


def create_profile(a):
    """`forge new @NAME`, run in a project's folder: a session profile NAME for that project, with the questions of `forge new` that
    belong to a profile (skills by sets and the final list, servers). Writes the definition (config/profile-defs/NAME.json, when there
    is none) and the project's `profiles` row; a profile row is read when a session starts, so nothing is synced. Exit 0 made (or
    planned), 1 a step failed or was cancelled, 2 a refusal or a missing answer."""
    name = a.path[1:]
    wrong = [flag for flag, given in (("--path", a.parent_dir is not None), ("--stack", a.stack is not None), ("--framework", a.framework),
                                      ("--name", a.name), ("--writes-tracked-files", a.writes_tracked_files)) if given]
    if wrong:
        return refuse(2, "%s belong to making a project from a name, not to a profile" % ", ".join(wrong))
    why = profiles.name_error(name)
    if why:
        return refuse(2, "%s is not a profile name: %s" % (a.path, why))
    try:
        project, _ = configure.project_here()
    except configure.Refusal as e:
        return refuse(2, str(e))
    project_file = os.path.join(lib.PROJECTS, project + ".claude.json")
    try:
        text = lib.read_text(project_file)
        doc = json.loads(text)
    except (lib.Unreadable, ValueError, TypeError) as e:
        return refuse(1, "%s cannot be read (%s)" % (lib.short(project_file), e))
    if doc.get("frozen"):
        return refuse(2, "project %s is frozen: forge writes nothing for it, so a profile here would do nothing" % project)
    if lib.dumps(doc) + "\n" != text:
        return refuse(1, "%s is not in the form forge writes it (two-space JSON, one final newline): a change would reformat all of it" % lib.short(project_file))
    given = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {"default": ask.DEFAULT_LABEL, "offered": {}}
    if name == given["default"]:
        return refuse(2, "%s is the label of project %s's own lists (profiles.default), so it cannot also be a profile" % (name, project))
    if name in given["offered"]:
        return refuse(2, "project %s already offers @%s: change it with forge config %s @%s" % (project, name, project, name))
    lib.settings.cache_clear()
    forge = copy.deepcopy(lib.settings())
    ctx = ask.Context(project, forge, doc, None)
    asker = ask.make_asker()
    try:
        ans, bad = ask.gather(a, ctx, asker, profile=name)
        rows, new_defs = {}, {}
        if not bad:
            rows, new_defs, bad = ask.apply(ctx, ans)
    except KeyboardInterrupt:
        return refuse(130, INTERRUPTED)
    except ask.Cancelled as e:
        return refuse(1, "%s -- nothing written" % e)
    if bad:
        return refuse(2, "nothing written, %s" % "; ".join(bad))
    doc["profiles"] = {"default": given["default"], "offered": {**given["offered"], name: rows[name]}}
    why = lib.project_error(doc)
    if why:
        return refuse(2, "nothing written, the project file would not be valid: %s" % why)
    print("forge new @%s: %s in project %s" % (name, "APPLY" if a.apply else "PLAN, nothing written (--apply makes it)", project))
    for line in describe(ctx, ans, rows, new_defs):
        print(line)
    print("  project     config/projects/%s.claude.json: profiles.offered.%s%s" % (
        project, name, "" if isinstance(json.loads(text).get("profiles"), dict) else
        " (and profiles.default %r: the project's own lists)" % given["default"]))
    try:
        if not (a.apply or confirmed(asker, a)):
            return 0
    except KeyboardInterrupt:
        return refuse(130, INTERRUPTED)
    writable, reason = lib.may_write()
    if not writable:
        print(reason)
        return 1
    undo = []
    try:
        with creation_lock(), stopped_means_rollback():
            if lib.read_text(project_file) != text:
                return refuse(2, "%s changed while the answers were asked; nothing written. Run the command again" % lib.short(project_file))
            taken = [n for n in new_defs if os.path.lexists(profiles.definition_path(n))]
            if taken:
                return refuse(2, "config/profile-defs/%s.json exists now; nothing written. Run the command again" % taken[0])
            write_definitions(undo, new_defs)
            undo.append(("restore", project_file, text))  # before the write that can fail: the file is put back as it was
            lib.write_text(project_file, lib.dumps(doc) + "\n", mode="keep")
            print("wrote  %s" % os.path.relpath(project_file, lib.ROOT))
    except BaseException as e:
        made = bool(undo)
        rollback(steps=undo)
        if not isinstance(e, Exception):
            print("! forge new: stopped%s" % (" -- what this run made was removed" if made else ""))
            raise
        print("! forge new: %s%s" % (e, " -- what this run made was removed" if made else ""))
        return 2 if isinstance(e, TimeoutError) else 1
    print("start it: forge start @%s" % name)
    return 0


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
    names = stack_names()
    stack = files = warnings = None
    if not names:
        problems.append("there are no stacks (no folder in %s)" % STACKS_DIR)
    elif a.stack is None:
        problems.append("--stack is missing (one of: %s)" % ", ".join(names))
    elif a.stack not in names:
        problems.append("--stack: %s" % suggest.message("stack", a.stack, names))
    else:
        try:
            stack, files, warnings = load_stack(a.stack, name)
        except ValueError as e:
            problems.append(str(e))
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
    asker = ask.make_asker()
    if problems:
        if not asker.interactive or a.yes:  # nothing will be asked, so every missing answer is named now, in the same error
            problems += unanswered(a, name, stack, asker)
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
    ctx = ask.Context(name, doc, project, dict(stack, name=a.stack))
    try:
        ans, bad = ask.gather(a, ctx, asker)
        rows, new_defs = {}, {}
        if not bad:
            rows, new_defs, bad = ask.apply(ctx, ans)
    except KeyboardInterrupt:
        return refuse(130, INTERRUPTED)
    except ask.Cancelled as e:
        return refuse(1, "%s -- nothing written" % e)
    if bad:
        return refuse(2, "nothing written, %s" % "; ".join(bad))
    if rows:
        project["profiles"] = {"default": ask.DEFAULT_LABEL, "offered": rows}
    why = lib.project_error(project)
    if why:
        return refuse(2, "nothing written, the project file would not be valid: %s" % why)
    extras = list(doc["skill_keep"]["extras"][key])

    print("forge new %s: %s" % (name, "APPLY" if a.apply else "PLAN, nothing written (--apply makes it)"))
    print("  folder      %s%s" % (target, " (exists, empty)" if exists else ""))
    print("  .gitignore  stack %s, written first" % a.stack)
    print("  stack       %s" % stack["description"])
    for label, field in (("servers", "servers"), ("plugins", "plugins"), ("checks", "checks"), ("skill sets", "skill_sets")):
        print("  %-11s %s" % (label, ", ".join(stack[field]) or "none"))
    print("              (what the stack lists is shown here only: the project file does not get it)")
    for warning in warnings:
        print("  warning     %s" % warning)
    print("  git init, README.md")
    print("  project     config/projects/%s%s" % (key, " (framework on)" if a.framework else ""))
    print("  skills row  config/forge.json skill_keep.extras %s%s" % ("gets %s" % key if row else "already has %s" % key,
                                                                         ": %s" % ", ".join(extras) if extras else ""))
    for line in describe(ctx, ans, rows, new_defs):
        print(line)
    print("  then        forge sync --apply %s" % name)
    if not a.apply:
        try:
            if not confirmed(asker, a):
                return 0
        except KeyboardInterrupt:
            return refuse(130, INTERRUPTED)
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
            if doc["skill_keep"].get("sets") != ctx.forge["skill_keep"].get("sets"):
                return refuse(2, "another forge new got there first: skill_keep.sets of config/forge.json changed meanwhile")
            doc["skill_keep"]["extras"][key] = extras
            taken = [n for n in new_defs if os.path.lexists(profiles.definition_path(n))]
            if taken:
                return refuse(2, "another forge new got there first: config/profile-defs/%s.json exists now" % taken[0])
            if not exists:
                os.mkdir(target)
                undo.append(("dir", target))  # before anything else that can fail or be interrupted
                lib.record("mkdir", target)
                print("made   %s/" % target)
            write_file(undo, target, ".gitignore", files["gitignore"])
            undo.append(("tree", os.path.join(target, ".git")))
            git_init(target)
            text = files["README.md"]
            write_file(undo, target, "README.md", text)
            write_definitions(undo, new_defs)
            undo.append(("file", project_file))  # absent until the write: checked above, under the lock
            lib.write_text(project_file, lib.dumps(project) + "\n")
            print("wrote  %s" % os.path.relpath(project_file, lib.ROOT))
            if row or extras:
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
