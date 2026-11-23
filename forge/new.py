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

Four flags carry what the `new-project` skill's old script gave a project. --account-server SERVICE[=PIN] adds the registry entry
`<service>-NAME` (forge/accounts.py) and lists it in the project's servers; the registry is written before the project file and put back
with it when a later step fails. --memory lite adds the claude-mem-lite plugin to plugins_keep (the generator derives its store from the
name). --worktree-guard writes `worktree_guard: true`. --no-baseline leaves out the skill_keep.extras row, and --no-git the `git init`.

With --framework the project file also gets `framework: true`, `factory: "off"`, the stack's checks and its plugins as `plugins_keep`
(the plugin is turned on through it). protected_paths, checks_quick and app_run need a look at the project, so they are left out.
With --framework, after the sync, `forge doctor NAME` runs, then the handover (examples/new-handoff.md, printed and written nowhere)
is printed for an agent in the project's folder to settle those three; the last line says how to open a session.

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
import shlex
import shutil
import signal
import subprocess
import time
import types

from forge import accounts, ask, configure, framework, lib, memory, profiles, suggest

INTERRUPTED = "interrupted (Ctrl-C) -- nothing written"  # exit 130, the shell's code for it
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\Z")  # \Z, not $: `$` also matches before one trailing newline

# A stack is a folder of the checkout's examples/stacks/: stack.json and gitignore, each complete on its own (no code or text is
# shared between stacks). The files are copied as they are with {{KEY}} replaced; the README text has no folder, so it is here.
STACKS_DIR = os.path.join(lib.ROOT, "examples", "stacks")
STACK_KEYS = ("description", "servers", "plugins", "checks", "skill_sets")
PLACEHOLDER = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}")
README = "# {{NAME}}\n"
REGISTRY = os.path.join(lib.ROOT, "config", "mcp-registry.json")


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


HANDOFF = "new-handoff.md"


def handoff_text(name, folder, stack_name, checks):
    """The handover document, examples/new-handoff.md with {{NAME}}, {{FOLDER}}, {{STACK}} and {{CHECKS}} filled in. ValueError, with one
    line, when the file cannot be read or a {{KEY}} has no value: that is found before anything is written."""
    from forge import cli  # at call time: forge/cli.py imports this module
    try:
        text = cli.example_text(HANDOFF)
    except OSError as e:
        raise ValueError("examples/%s cannot be read: %s" % (HANDOFF, e))
    out, errors, _ = substitute("handover", {HANDOFF: text}, {"NAME": name, "FOLDER": folder, "STACK": stack_name,
                                                              "CHECKS": ", ".join("`%s`" % c for c in checks) or "none"})
    if errors:
        raise ValueError("; ".join(errors).replace("stacks/handover/", "examples/"))
    return out[HANDOFF]


def framework_plugins(stack_plugins, forge):
    """What `plugins_keep` holds for a framework project that did not choose its plugins (--plugin): every plugin the same project
    would have on without it. A project with no plugins_keep has no plugin map and so inherits the user scope's, so those come first;
    then the stack's, then skill_keep.common_plugins (sync adds those to a project that keeps plugins). Turning the framework on never
    turns a plugin off; the framework plugin itself is turned on by forge, not listed."""
    user = lib.read_json(os.path.join(lib.HOME, ".claude", "settings.json"), quiet=True).get("enabledPlugins")
    on = [p for p, enabled in user.items() if enabled is True] if isinstance(user, dict) else []
    common = ((forge.get("skill_keep") or {}).get("common_plugins") or [])
    return list(dict.fromkeys(on + list(stack_plugins) + [p for p in common if isinstance(p, str)]))


EXPECTED_DOCTOR_FAIL = "instruction files"  # a fresh project has no CLAUDE.md or AGENTS.md, and forge never writes one
EXPECTED_MEMORY_FAIL = "FAIL  %s/lite-store-has-rows: no claude-mem-lite.db yet \u2014 nothing has been written"  # a fresh lite project has no store yet


def fresh_store_only(name):
    """Whether the `memory` doctor row fails for project `name` only because its claude-mem-lite store has no database yet, which every
    project just made has until its first session. Read from memory_doctor.py's own report: its FAIL lines are that one, by exact text."""
    r = lib.run(["scripts/sync/memory_doctor.py", "--project", name], capture=True)
    return [l for l in r.stdout.splitlines() if l.startswith("FAIL")] == [EXPECTED_MEMORY_FAIL % name]


def closing(name, target, handoff, profiles_made):
    """After the sync of a framework project: `forge doctor NAME`'s report, the handover, and how to open a session. 0, or 1 when
    doctor has a FAIL row other than the one every fresh project has (the project is made either way, and the message says so)."""
    print("\n== forge doctor %s ==" % name, flush=True)
    r = lib.run(["bin/forge", "doctor", name], capture=True)
    print(r.stdout, end="")
    if r.stderr:
        print(r.stderr, end="")
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    other = [l for l in fails if l[6:28].strip() != EXPECTED_DOCTOR_FAIL]
    if any(l[6:28].strip() == "memory" for l in other) and fresh_store_only(name):
        other = [l for l in other if l[6:28].strip() != "memory"]
    if r.returncode and not fails:
        other = ["forge doctor exited %d and printed no FAIL row" % r.returncode]
    print("\n== handover: paste this into claude, started in %s ==\n" % target)
    print(handoff.rstrip("\n"))
    if other:
        print("\n! forge new: %s is made and registered, but forge doctor %s fails beyond `%s`: %s" % (
            name, name, EXPECTED_DOCTOR_FAIL, " | ".join(l.strip() for l in other)), flush=True)
    else:
        print("\nopen a new session in the folder: cd %s && claude%s" % (shlex.quote(target), "".join(" (or claude @%s)" % p for p in profiles_made)), flush=True)
    return 1 if other else 0


def registry_read():
    """(text, document) of config/mcp-registry.json, for an entry to be added. ValueError, with one line, when it cannot take one: it is no
    object with a `servers` object, or it is not in the form forge writes (a change would reformat all of it). OSError when unreadable."""
    text = lib.read_text(REGISTRY)
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise ValueError("%s is not valid JSON (%s)" % (lib.short(REGISTRY), e))
    if not isinstance(doc, dict) or not isinstance(doc.get("servers"), dict):
        raise ValueError("%s is not an object with a `servers` object" % lib.short(REGISTRY))
    if lib.dumps(doc) + "\n" != text:
        raise ValueError("%s is not in the form forge writes it (two-space JSON, one final newline): adding an entry would reformat all of it"
                         % lib.short(REGISTRY))
    return text, doc


def path_like(arg):
    """Whether `arg` is written as a path (a name never is): it holds a separator or starts with . or ~."""
    return "/" in arg or os.sep in arg or arg[:1] in (".", "~")


def answer_flags(a):
    """Whether a flag that answers one of the questions (forge/ask.py) was given."""
    return any(getattr(a, k, None) for k in ("profiles", "sets", "skills", "server", "memory", "check", "plugin", "ui", "command_guard", "worktree_guard"))


def creation_flags(a):
    """Whether a flag that belongs to making a project was given."""
    return (a.parent_dir is not None or a.stack is not None or a.framework or a.yes or a.apply or bool(a.account_server) or a.no_baseline
            or a.no_git or answer_flags(a))


def route(a):
    """What `forge new ARG` does with ARG: None means register the directory (cmd_new goes on), a number is the exit code
    of a run that is already over (a project made, or a refusal)."""
    arg = a.path
    if arg.startswith("@"):
        return create_profile(a)
    isdir = os.path.isdir(os.path.expanduser(arg))
    if path_like(arg):
        if isdir and creation_flags(a):
            return refuse(2, "%s is a directory, so forge new registers it, and --path, --stack, --framework, --yes, --apply, --account-server, "
                             "--no-baseline, --no-git and the answer flags belong to making a project from a name" % arg)
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


def save_copy(path, text):
    """A copy of `text` (what `path` holds now) beside the journal, mode 0600: when putting the file back fails, it is the way back.
    OSError when it cannot be made, before anything is written."""
    os.makedirs(lib.STATE, exist_ok=True)
    copy_path = os.path.join(lib.STATE, "new-restore-%s-%d-%s" % (time.strftime("%Y%m%dT%H%M%S"), os.getpid(), os.path.basename(path)))
    lib.write_text(copy_path, text, mode=0o600)
    return copy_path


def forget(copy_path):
    try:
        os.unlink(copy_path)
    except OSError:
        pass


def rollback(steps):
    """Takes out what this run made, newest first. A folder only while it is empty: it never removes what it did not put there. A file
    that existed is put back from its text; if that fails the file keeps what this run wrote, its saved copy is kept, and the message
    says how to put it back (it is never to be removed: it is the project's registration). True when everything was undone."""
    stuck, unrestored = [], []
    for kind, path, *rest in reversed(steps):
        try:
            if kind == "restore":  # a file that existed: put back what it held
                try:
                    lib.write_text(path, rest[0])
                except OSError as e:
                    unrestored.append((path, rest[1], e))
                    continue
                forget(rest[1])
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
    for path, copy_path, why in unrestored:
        print("! forge new: could not put back %s (%s), so it still holds what this run wrote. Its original content is saved; "
              "put it back with: cp %s %s" % (lib.short(path), why, shlex.quote(copy_path), shlex.quote(path)))
    return not (stuck or unrestored)


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


def skills_read(doc, key):
    """What the skill answers for project `key` were decided from in config/forge.json: the sets, the common lists, and this project's
    opt-out, exclusion and extras rows. The plan and the locked reread must agree on it."""
    keep = doc["skill_keep"]
    return (keep.get("sets"), keep.get("common_skills"), (keep.get("common_opt_out") or {}).get(key),
            key in (keep.get("common_exclude") or []), (keep.get("extras") or {}).get(key))


def opt_out_row(doc, key):
    return (doc["skill_keep"].get("common_opt_out") or {}).get(key)


def definition_changed(ctx):
    """The name of an existing profile definition that is not what the answers were checked against (changed, gone or unreadable now), or None."""
    for name, was in ctx.defs_read.items():
        try:
            if profiles.definition(name) != was:
                return name
        except profiles.ProfileError:
            return name
    return None


def end_note(made, complete):
    return "" if not made else " -- what this run made was removed" if complete else " -- the rollback is incomplete (see above)"


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
    if ans.memory == ask.LITE:
        out.append("  memory      lite: the %s plugin (plugins_keep); its store %s is derived by the generator" % (
            memory.LITE_PLUGIN, os.path.join(os.path.relpath(memory.LITE_ROOT, lib.ROOT), memory.lite_store_name(ctx.proj, ctx.name) or ctx.name)))
    elif ans.memory:
        out.append("  memory      %s (servers %s)" % (ans.memory, ", ".join(ask.MEMORY[ans.memory])))
    st = ans.stack or {}
    if st.get("checks"):
        out.append("  checks      %s" % ", ".join(st["checks"]))
    if st.get("plugins"):
        out.append("  plugins     only %s (besides the common ones)" % ", ".join(st["plugins"]))
    if st.get("ui") or st.get("command_guard") or st.get("worktree_guard"):
        out.append("  options     %s" % ", ".join(k for k in ("ui", "command_guard", "worktree_guard") if st.get(k)))
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
                                      ("--name", a.name), ("--writes-tracked-files", a.writes_tracked_files),
                                      ("--account-server", a.account_server), ("--no-baseline", a.no_baseline), ("--no-git", a.no_git)) if given]
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
    undo, made, complete = [], False, True
    try:
        with creation_lock(), stopped_means_rollback():
            try:
                if lib.read_text(project_file) != text:
                    return refuse(2, "%s changed while the answers were asked; nothing written. Run the command again" % lib.short(project_file))
                taken = [n for n in new_defs if os.path.lexists(profiles.definition_path(n))]
                if taken:
                    return refuse(2, "config/profile-defs/%s.json exists now; nothing written. Run the command again" % taken[0])
                changed = definition_changed(ctx)
                if changed:
                    return refuse(2, "config/profile-defs/%s.json changed meanwhile; nothing written. Run the command again" % changed)
                write_definitions(undo, new_defs)
                saved = save_copy(project_file, text)
                undo.append(("restore", project_file, text, saved))  # before the write that can fail: the file is put back as it was
                lib.write_text(project_file, lib.dumps(doc) + "\n", mode="keep")
                print("wrote  %s" % os.path.relpath(project_file, lib.ROOT))
                forget(saved)
            except BaseException:
                made = bool(undo)
                complete = rollback(steps=undo)  # still under the lock: the next forge new reads the committed state or the restored one
                raise
    except BaseException as e:
        if not isinstance(e, Exception):
            print("! forge new: stopped%s" % end_note(made, complete))
            raise
        print("! forge new: %s%s" % (e, end_note(made, complete)))
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
    account = None  # what --account-server gives: names, new (registry entries to add), unpinned, and the registry as read: text, doc
    if a.account_server:
        try:
            reg_text, reg_doc = registry_read()
        except (OSError, ValueError) as e:
            return refuse(1, "--account-server: %s -- nothing written" % e)
        try:
            account = types.SimpleNamespace(**dict(zip(("names", "new", "unpinned"), accounts.plan(a.account_server, name, reg_doc["servers"]))),
                                            text=reg_text, doc=reg_doc)
        except ValueError as e:
            return refuse(2, "nothing written, %s" % e)
    project = json.loads(cli.example_text("project.claude.json"))
    project.update(project=name, project_path=target, writes_tracked_files=False)
    handoff = None
    if a.framework:
        # What a framework project needs: the stack's checks, and plugins_keep (the plugin is turned on through it) holding every plugin a
        # plain project of the stack has on. --check and --plugin choose among these later (ask.check_stack).
        project.update(framework=True, factory="off", checks=list(stack["checks"]), plugins_keep=framework_plugins(stack["plugins"], doc))
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
    if a.framework and not (ans.stack or {}).get("plugins"):  # no plugins chosen: read the user's again, they may have changed while asking
        project["plugins_keep"] = ask.with_memory_plugin(framework_plugins(stack["plugins"], doc), ans)
    if account:  # after the --server answers, as the script listed them
        project["servers"] = list(project["servers"]) + [n for n in account.names if n not in project["servers"]]
    if a.framework:  # the checks the project file holds, after --check chose among the stack's
        try:
            handoff = handoff_text(name, target, a.stack, project["checks"])
        except ValueError as e:
            return refuse(2, "nothing written, %s" % e)
    why = lib.project_error(project)
    if why:
        return refuse(2, "nothing written, the project file would not be valid: %s" % why)
    extras = list(doc["skill_keep"]["extras"][key])
    held = list(ctx.draft.start["forge"]["skill_keep"]["extras"][key])
    if a.no_baseline and not row:  # a row left from an earlier project of this name, even an empty one: the project would still be enrolled (it gets the common skills and is trimmed), and the row is never deleted here
        return refuse(2, "nothing written, --no-baseline: config/forge.json skill_keep.extras already has a row %s (%s) that would still "
                         "enrol this project in skill trimming; remove the row by hand, or drop --no-baseline" % (key, ", ".join(held) or "empty"))
    if a.no_baseline and extras != held:
        return refuse(2, "nothing written, --no-baseline leaves out the skill_keep.extras row of %s, and the skills answered go into it (%s): "
                         "drop --no-baseline, or give those skills to a profile" % (key, ", ".join(extras)))

    print("forge new %s: %s" % (name, "APPLY" if a.apply else "PLAN, nothing written (--apply makes it)"))
    print("  folder      %s%s" % (target, " (exists, empty)" if exists else ""))
    print("  .gitignore  stack %s, written first" % a.stack)
    print("  stack       %s" % stack["description"])
    for label, field in (("servers", "servers"), ("plugins", "plugins"), ("checks", "checks"), ("skill sets", "skill_sets")):
        print("  %-11s %s" % (label, ", ".join(stack[field]) or "none"))
    print("              (%s)" % ("with --framework the project file gets the stack's checks and plugins; the rest is shown here only" if a.framework
                                      else "what the stack lists is shown here only: the project file does not get it"))
    for warning in warnings:
        print("  warning     %s" % warning)
    print("  README.md (--no-git: no git init)" if a.no_git else "  git init, README.md")
    print("  project     config/projects/%s%s" % (key, " (framework on, factory off)" if a.framework else ""))
    if a.framework:
        print("  framework   checks %s; plugins_keep %s" % (", ".join(project["checks"]) or "none", ", ".join(project["plugins_keep"]) or "none"))
        print("              %s are left unarmed: the handover, printed after the run, hands them to an agent" % ", ".join(framework.wanted_fields(project)))
    if account:
        for reg_name in account.names:
            print("  registry    %s -> %s%s" % (
                reg_name, (account.new.get(reg_name) or account.doc["servers"][reg_name])["url"],
                "  UNPINNED: add the pin before the first /mcp login" if reg_name in account.unpinned else
                "" if reg_name in account.new else " (already in config/mcp-registry.json, used as it is)"))
    if a.no_baseline:
        print("  skills row  skipped (--no-baseline): no skill_keep.extras row")
    else:
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

    undo, made, complete, saved = [], False, True, None  # saved: the recovery copy of the registry, kept until every step has succeeded
    try:
        with stopped_means_rollback(), creation_lock():
            try:
                # Under the lock again: another run may have made this name, or taken the folder, since the checks above.
                why = ("%s is registered" % name if os.path.lexists(project_file) else None) or target_error(target)
                if why:
                    return refuse(2, "another forge new got there first: %s" % why)
                exists = os.path.lexists(target)
                doc, row = skills_doc(key)  # read again: another run may have added its row to forge.json meanwhile
                if doc is None:
                    raise OSError("config/forge.json skill_keep (or its extras) is not a JSON object")
                if skills_read(doc, key) != skills_read(ctx.draft.start["forge"], key):  # what the plan read, not what it changed
                    return refuse(2, "another forge new got there first: skill_keep of config/forge.json (the sets, the common lists, or the "
                                     "rows of %s) changed meanwhile" % key)
                if a.no_baseline:
                    if row:
                        del doc["skill_keep"]["extras"][key]  # the row skills_doc made in this copy: --no-baseline leaves it out
                else:
                    doc["skill_keep"]["extras"][key] = extras
                planned_opt = opt_out_row(ctx.forge, key)  # a skill the owner chose that the project's opt-out switched off: the opt-out is lifted
                lifted = planned_opt != opt_out_row(ctx.draft.start["forge"], key)
                if lifted:
                    table = doc["skill_keep"].setdefault("common_opt_out", {})
                    if planned_opt:
                        table[key] = planned_opt
                    else:
                        table.pop(key, None)
                taken = [n for n in new_defs if os.path.lexists(profiles.definition_path(n))]
                if taken:
                    return refuse(2, "another forge new got there first: config/profile-defs/%s.json exists now" % taken[0])
                changed = definition_changed(ctx)
                if changed:
                    return refuse(2, "config/profile-defs/%s.json changed meanwhile; nothing written. Run the command again" % changed)
                if account and lib.read_text(REGISTRY) != account.text:
                    return refuse(2, "config/mcp-registry.json changed meanwhile; nothing written. Run the command again")
                if not exists:
                    os.mkdir(target)
                    undo.append(("dir", target))  # before anything else that can fail or be interrupted
                    lib.record("mkdir", target)
                    print("made   %s/" % target)
                write_file(undo, target, ".gitignore", files["gitignore"])
                if not a.no_git:
                    undo.append(("tree", os.path.join(target, ".git")))
                    git_init(target)
                text = files["README.md"]
                write_file(undo, target, "README.md", text)
                write_definitions(undo, new_defs)
                if account and account.new:
                    saved = save_copy(REGISTRY, account.text)
                    undo.append(("restore", REGISTRY, account.text, saved))  # before the write that can fail: the registry is put back as it was
                    lib.write_text(REGISTRY, lib.dumps({**account.doc, "servers": {**account.doc["servers"], **account.new}}) + "\n", mode="keep")
                    print("wrote  config/mcp-registry.json (%s)" % ", ".join(account.new))
                undo.append(("file", project_file))  # absent until the write: checked above, under the lock
                lib.write_text(project_file, lib.dumps(project) + "\n")
                print("wrote  %s" % os.path.relpath(project_file, lib.ROOT))
                if (not a.no_baseline and (row or extras)) or lifted:
                    lib.write_text(lib.SETTINGS, lib.dumps(doc) + "\n")  # atomic: when it fails, forge.json is as it was
                    print("wrote  config/forge.json (%s)" % ", ".join(
                        (["skill_keep.extras row %s" % key] if not a.no_baseline else []) + (["common_opt_out row"] if lifted else [])))
            except BaseException:
                made = bool(undo)
                complete = rollback(undo)  # still under the lock: the next forge new reads the committed state or the restored one
                raise
    except BaseException as e:
        if not isinstance(e, Exception):
            print("! forge new: stopped%s" % end_note(made, complete))
            raise
        print("! forge new: %s%s" % (e, end_note(made, complete)))
        return 2 if isinstance(e, TimeoutError) else 1
    if saved:
        forget(saved)  # every step has succeeded: the recovery copy of the registry is not needed any more
    print(flush=True)
    code = lib.run(["bin/forge", "sync", "--apply", name]).returncode
    if code:
        print("! forge new: %s is made and registered, but forge sync --apply %s failed (exit %d) -- fix the cause and run that again"
              % (name, name, code))
        return code
    if not a.framework:
        return 0
    return closing(name, target, handoff, list(rows))
