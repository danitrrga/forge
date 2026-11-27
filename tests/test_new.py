#!/usr/bin/env python3
"""4.4 U4: `forge new NAME` makes a project from the terminal; `forge new PATH` on an existing directory still
registers it, exactly as before. Everything runs in a toy world of tests/sandbox.py: W/forge (an engine-only copy with
its own config/forge.json), W/home, W/projects (the `projects_dir` of that forge.json) and W/cwd (an empty directory
every command runs from, so no argument names a directory by accident).

Assertions, each seen failing once (the control of each is run on every run, in a world whose engine copy is mutated
in one line; the control's failure message is what is quoted here, and the assertion must produce it):
  - no terminal and no --stack: exit 2 naming --stack, nothing created, with and without --apply.
      control (the check ahead of the first write, and the cleanup, taken out):
      `left a partial folder: <W>/projects/demo`
  - `forge new demo --stack generic --apply` creates in the project folder only .git/, .gitignore, README.md and what
    forge sync writes there (.claude/settings.local.json), and outside it only the project file, the skill_keep.extras row,
    and what sync writes (HOME, forge's own state).
      control (a CLAUDE.md written): `wrote outside the allowed list: <W>/projects/demo/CLAUDE.md`
  - the dry-run leaves the world's fingerprint unchanged.
      control (a dry-run that goes on): `dry-run changed the tree`
  - a project named `list` can be created.
      control (a reserved list of verbs): `project named 'list' rejected`
  - a name starting with `@`, or with `-`, or not kebab-case, is refused, exit 2, nothing created.
      control (no name check): `project named '-x' created`
  - an argument that looks like a path and does not exist is refused as a path (exit 1, "is not a directory", as
    before), never taken for a name.
      control (no path check): `'./nope' was not refused as a path`
  - a target folder that is not empty, or is a link, is refused and never written into.
      control (no check): `wrote into a non-empty folder`, `wrote through a link`
  - a GIT_DIR in the caller's environment does not decide where `git init` goes.
      control (no scrubbed environment): `git init followed GIT_DIR`
  - a failure halfway (a git that fails; a forge.json that cannot be written after the project file) leaves nothing this
    run made, and nothing else is touched.
      control (no cleanup): `left behind: <paths>`
  - an existing directory behaves as on master: output and files compared with the base revision's cli.py.
      control (one more key in the project file): `differs from master`
4.4 U5, the stacks as data (examples/stacks/<stack>/stack.json and gitignore, read by forge/new.py):
  - every one of the six stacks creates a project whose .gitignore ignores .env.
      control (rust's .env line taken out of its file): `.gitignore of stack rust does not ignore .env`
  - a {{X}} with no value in a stack file: exit 2, `unresolved {{X}} in stacks/generic/gitignore`, nothing written.
      control (a substituter that lets it through): `placeholder left in .gitignore`
  - every stack.json parses and has exactly the five keys; the reader refuses one that lacks a key before the first write.
      controls (a key renamed in tauri's file; the reader's check taken out): `stack tauri: stack.json has the keys`,
      `a stack.json without checks`
  - an unknown stack exits 2 and names the six; a value nothing used is a warning (control: `an unused argument not warned about`).
  - `--stack generic` writes the .gitignore and README of 182's head byte for byte (control: a changed line, `differs from 182's head`).
  Seen failing first, before the stacks and the reader existed: `stack generic: exit 2`... for the five new stacks `no project`,
  `examples/stacks holds [], want [...]`, and the unknown stack named only generic.
Also: the missing answers are named in ONE error (--stack and projects_dir together), --path puts the folder under it
and nowhere else, `forge new --help` lists every flag.

Seen failing first (this file, before forge/new.py existed): `forge new demo --stack generic --apply` died with
`forge new: ... is not a directory` exit 1 (the old command), every creation assertion failed, and every control
said `control anchor not found in forge/new.py`."""
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

BASE = "2ffe5bf"  # master before this unit: the registration side is compared with its forge/cli.py
HEAD_182 = "68576e8"  # the head of pull request 182: its forge/new.py holds the generic .gitignore text this unit moved into a file
failures, notrun, n_checks = [], [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))


def tail(text, n=6):
    return " | ".join(text.strip().splitlines()[-n:])


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


# forge new's own lock file and the folders above it: made by any apply, kept by design (an flock a dying run frees), so a
# run that failed and rolled back still shows them.
QUIET = {os.path.join("home", ".local"), os.path.join("home", ".local", "state"), os.path.join("home", ".local", "state", "forge"),
         os.path.join("home", ".local", "state", "forge", "new.lock")}


class World:
    def __init__(self, tag, mutate=(), projects_dir=True, framework=False):
        self.top = sandbox.mkdtemp("new-%s-" % tag)
        self.root = os.path.join(self.top, "forge")
        self.home = os.path.join(self.top, "home")
        self.projects = os.path.join(self.top, "projects")
        self.cwd = os.path.join(self.top, "cwd")
        self.tmp = os.path.join(self.top, "tmp")
        self.logs = os.path.join(self.top, "log")
        for d in (self.home, os.path.join(self.home, ".claude"), self.projects, self.cwd, self.tmp, self.logs):
            os.makedirs(d)
        sandbox.copy_engine(self.root)
        sandbox.git(self.root, "init", "-q")
        sandbox.git(self.root, "add", "-A")
        sandbox.git(self.root, "commit", "-q", "-m", "engine")
        self.anchors_missing = []
        for rel, old, new, *every in mutate:  # a fourth item True: every occurrence is replaced (at least one)
            p = os.path.join(self.root, rel)
            text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
            if text.count(old) < 1 or (text.count(old) != 1 and not every):
                self.anchors_missing.append("control anchor not found in %s: %r" % (rel, old))
                continue
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text.replace(old, new))
        # What `forge init` writes, less its sync and doctor: forge.json (the example), the empty registry, the secrets
        # link and the system doc. A stranger's world: no project but the ones a test makes.
        cfg = os.path.join(self.root, "config")
        os.makedirs(os.path.join(cfg, "projects"))
        doc = read_json(os.path.join(self.root, "examples", "forge.json"))
        doc.pop("projects_dir", None)
        if projects_dir:
            doc["projects_dir"] = self.projects
        self.plugin = None
        if framework:  # a directory marketplace of one plugin, so the framework step can serve a project, and a `claude` that only logs
            self.plugin = os.path.join(self.top, "plug", "toyfw")
            os.makedirs(os.path.join(self.plugin, ".claude-plugin"))
            write_json(os.path.join(self.plugin, ".claude-plugin", "marketplace.json"), {"name": "toyfw", "plugins": [{"name": "toyfw"}]})
            doc["framework"]["plugin_source"] = {"source": "directory", "path": self.plugin}
            doc["skill_keep"]["common_plugins"] = ["common@mk"]
            # the plugins a project without plugins_keep has on: the user scope's (a project that names none inherits them)
            write_json(os.path.join(self.home, ".claude", "settings.json"), {"enabledPlugins": {"mine@mk": True, "off@mk": False}})
        write_json(os.path.join(cfg, "forge.json"), doc)
        for name in ("mcp-registry.json", "gateway.json"):
            shutil.copy(os.path.join(self.root, "examples", name), os.path.join(cfg, name))
        os.makedirs(os.path.join(self.root, "credentials"), mode=0o700)
        with open(os.path.join(self.root, "credentials", "secrets.json"), "w") as fh:
            fh.write("{}\n")
        os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(cfg, "secrets.json"))
        shutil.copy(os.path.join(self.root, "examples", "AGENT-SYSTEM.md"), os.path.join(cfg, "AGENT-SYSTEM.md"))
        bin_dir = sandbox.stub_claude(os.path.join(self.top, "bin"), os.path.join(self.logs, "claude.log")) if framework else None
        self.env = sandbox.bare_env(self.home, self.tmp, bin_dir, FORGE_WRITE_LOG=os.path.join(self.logs, "writes.log"),
                                    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

    def close(self):
        sandbox.rmtree(self.top)
        if self.top in sandbox._made:
            sandbox._made.remove(self.top)

    def forge(self, *args, env=None, cwd=None):
        """(exit code, stdout and stderr) of `bin/forge args`, run from W/cwd (or `cwd`) with no terminal."""
        r = subprocess.run([sys.executable, os.path.join(self.root, "bin", "forge")] + list(args), cwd=cwd or self.cwd,
                           env=env or self.env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr

    def start(self, *args, env=None, cwd=None):
        """The same, started and not waited for."""
        return subprocess.Popen([sys.executable, os.path.join(self.root, "bin", "forge")] + list(args), cwd=cwd or self.cwd,
                                env=env or self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                stdin=subprocess.DEVNULL)

    def start_together(self, jobs, at=1.0):
        """Starts every job (a list of argv tails) so that each begins the same instant, `at` seconds ahead: the interpreters
        are up and wait, then all run `bin/forge`, so their checks overlap."""
        t = time.time() + at
        code = "import runpy,sys,time; time.sleep(max(0.0, float(sys.argv[1]) - time.time())); sys.argv = sys.argv[2:]; runpy.run_path(sys.argv[0], run_name='__main__')"
        return [subprocess.Popen([sys.executable, "-c", code, repr(t), os.path.join(self.root, "bin", "forge")] + list(job["args"]),
                                 cwd=self.cwd, env=job.get("env") or self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, stdin=subprocess.DEVNULL) for job in jobs]

    def slow_env(self, secs):
        """The environment with a `git` in front that sleeps `secs` seconds on `init` and otherwise is the real git."""
        d = os.path.join(self.top, "slowbin")
        os.makedirs(d, exist_ok=True)
        real = shutil.which("git")
        with open(os.path.join(d, "git"), "w") as fh:
            fh.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = init ] && sleep %s; done\nexec %s "$@"\n' % (secs, real))
        os.chmod(os.path.join(d, "git"), 0o755)
        return dict(self.env, PATH=d + os.pathsep + self.env["PATH"])

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def project(self, name):
        return os.path.join(self.projects, name)

    def snapshot(self):
        """Every file of the world by kind, mode and content (not mtime), the write log left out; .git directories
        are not walked by sandbox.manifest, so their paths are added."""
        snap = {k: v[:3] for k, v in sandbox.manifest(self.top).items() if k != "log" and not k.startswith("log" + os.sep)
                and k not in QUIET}
        for d, dirs, _ in os.walk(self.top):
            if ".git" in dirs:
                snap[os.path.relpath(os.path.join(d, ".git"), self.top) + "/"] = ("dir-git",)
                dirs.remove(".git")
        return snap

    def fingerprint(self):
        return hashlib.sha256(repr(sorted(self.snapshot().items())).encode()).hexdigest()

    def register_demo(self, name="regdemo"):
        d = self.project(name)
        os.makedirs(d)
        with open(os.path.join(d, "README.md"), "w") as fh:
            fh.write("%s\n" % name)
        sandbox.git(d, "init", "-q")
        sandbox.git(d, "add", "-A")
        sandbox.git(d, "commit", "-q", "-m", name)
        return d


def changed(before, after):
    return sorted(k for k, v in after.items() if before.get(k) != v)


def fake_git(top):
    """A PATH of only a `git` that fails, and python3 (order 10 of ORDERS.md: no system dirs behind it)."""
    d = os.path.join(top, "fakebin")
    os.makedirs(d)
    with open(os.path.join(d, "git"), "w") as fh:
        fh.write("#!/bin/sh\necho 'fake git: refused' >&2\nexit 1\n")
    os.chmod(os.path.join(d, "git"), 0o755)
    os.symlink(sys.executable, os.path.join(d, "python3"))
    return d


# ---------------------------------------------------------------- the assertions, one function per behaviour.
# Each returns the list of what is wrong; [] means it holds. The controls run the same function on a mutated world.

ALLOWED_IN_PROJECT = {".gitignore", "README.md", ".claude", os.path.join(".claude", "settings.local.json")}


def a_missing_stack(w):
    bad = []
    for extra in ([], ["--apply"], ["--yes"], ["--yes", "--apply"]):
        before = w.snapshot()
        code, out = w.forge("new", "demo", *extra)
        if "register" not in out:
            bad.append("the missing --stack%s does not say a directory is registered by its path: %s" % (" ".join([""] + extra), tail(out)))
        if code != 2 or "--stack" not in out:
            bad.append("no --stack%s: exit %d, want 2 naming --stack: %s" % (" ".join([""] + extra), code, tail(out)))
        if os.path.lexists(w.project("demo")):
            bad.append("left a partial folder: %s" % w.project("demo"))
        if w.snapshot() != before:
            bad.append("wrote something with no --stack%s: %s" % (" ".join([""] + extra), changed(before, w.snapshot())[:4]))
    return bad


def a_one_error(w):
    """The missing answers are named together: --stack, and the folder (projects_dir or --path)."""
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--apply")
    bad = []
    if code != 2 or "--stack" not in out or "projects_dir" not in out:
        bad.append("both missing answers should be named in one error, exit 2: exit %d: %s" % (code, tail(out)))
    if len([l for l in out.splitlines() if l.strip()]) != 1:
        bad.append("not ONE error line: %s" % tail(out))
    if w.snapshot() != before:
        bad.append("wrote something: %s" % changed(before, w.snapshot())[:4])
    return bad


def a_generic_created(w):
    bad = []
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    target = w.project("demo")
    if code != 0:
        return ["forge new demo --stack generic --apply: exit %d: %s" % (code, tail(out, 10))]
    after = w.snapshot()
    entries = set(os.listdir(target)) if os.path.isdir(target) else set()
    if entries != {".git", ".gitignore", "README.md", ".claude"}:
        bad.append("the project folder holds %s, want .git .gitignore README.md and .claude (sync's)" % sorted(entries))
    outside = []
    for path in changed(before, after):
        if path.endswith("/") and path.startswith(os.path.join("projects", "demo", ".git")):
            continue
        parts = path.rstrip("/").split(os.sep)
        if parts[:2] == ["projects", "demo"]:
            rel = os.sep.join(parts[2:])
            if rel and rel not in ALLOWED_IN_PROJECT and rel != ".git":
                outside.append(path)
        elif path in (os.path.join("projects", "demo"), os.path.join("forge", "config", "projects", "demo.claude.json"),
                      os.path.join("forge", "config", "forge.json")):
            continue
        elif parts[0] == "home":
            if "/".join(parts[1:]) in (".claude.json", ".local", ".local/state", ".local/state/forge") or \
                    "/".join(parts[1:]).startswith(".local/state/forge/"):
                continue  # what sync writes (and the lock of forge new)
            outside.append(path)
        else:
            outside.append(path)
    if outside:
        bad.append("wrote outside the allowed list: %s" % ", ".join(os.path.join(w.top, p) for p in outside[:6]))
    if not os.path.isdir(os.path.join(target, ".git")):
        bad.append("no .git/ in %s" % target)
    else:
        r = subprocess.run(["git", "-C", target, "rev-parse", "--git-dir"], capture_output=True, text=True, env=dict(w.env))
        if r.returncode != 0:
            bad.append("%s/.git is not a repository: %s" % (target, r.stderr.strip()))
    gi = open(os.path.join(target, ".gitignore")).read().splitlines() if os.path.exists(os.path.join(target, ".gitignore")) else []
    if ".env" not in gi or ".DS_Store" not in gi:
        bad.append(".gitignore lacks .env or .DS_Store: %s" % gi)
    rd = open(os.path.join(target, "README.md")).read() if os.path.exists(os.path.join(target, "README.md")) else ""
    if rd != "# demo\n":
        bad.append("README.md is %r, want '# demo\\n'" % rd)
    pf = read_json(w.path("config", "projects", "demo.claude.json")) or {}
    got = {k: pf.get(k) for k in ("project", "project_path", "writes_tracked_files", "servers")}
    want = {"project": "demo", "project_path": os.path.realpath(target), "writes_tracked_files": False, "servers": []}
    if got != want or "framework" in pf:
        bad.append("project file %s, want %s with no framework key" % (got, want))
    fj = read_json(w.path("config", "forge.json")) or {}
    if (fj.get("skill_keep") or {}).get("extras", {}).get("demo.claude.json") != []:
        bad.append("no skill_keep.extras row for demo.claude.json in forge.json")
    orig = read_json(os.path.join(w.root, "examples", "forge.json"))
    orig["projects_dir"] = w.projects
    fj.get("skill_keep", {}).get("extras", {}).pop("demo.claude.json", None)
    if fj != orig:
        bad.append("forge.json changed beyond the extras row")
    keys = (read_json(os.path.join(w.home, ".claude.json")) or {}).get("projects", {})
    if os.path.realpath(target) not in keys:
        bad.append("forge sync --apply demo did not run: no key for the project in the world's ~/.claude.json")
    return bad


def a_dry_run(w):
    before = w.fingerprint()
    code, out = w.forge("new", "demo", "--stack", "generic")
    bad = []
    if code != 0 or w.project("demo") not in out or "--apply" not in out:
        bad.append("dry-run: exit %d, want 0 and a plan naming the folder and --apply: %s" % (code, tail(out)))
    if w.fingerprint() != before or os.path.lexists(w.project("demo")):
        bad.append("dry-run changed the tree")
    return bad


def a_list_created(w):
    code, out = w.forge("new", "list", "--stack", "generic", "--apply")
    pf = read_json(w.path("config", "projects", "list.claude.json")) or {}
    if code != 0 or pf.get("project") != "list" or not os.path.isdir(os.path.join(w.project("list"), ".git")):
        return ["project named 'list' rejected: exit %d: %s" % (code, tail(out))]
    return []


def a_bad_names(w):
    bad = []
    # "@x" is no longer here: with 4.4 U6 an argument that starts with @ is a profile of the project in the folder (`forge new @x`), not a
    # name; tests/test_ask.py refuses its bad names (@-x, @@x, @Bad) with the reason.
    for name in ("-x", "My_Project", "a--b", "x-", "demo\n"):
        before = w.snapshot()
        argv = ["new", "--stack", "generic", "--apply"] + (["--", name] if name.startswith("-") else [name])
        code, out = w.forge(*argv)
        made = [p for p in changed(before, w.snapshot())]
        if code != 2 or made:
            what = "project named %r created" % name if made else "project named %r not refused" % name
            bad.append("%s: exit %d, want 2 and nothing written: %s %s" % (what, code, tail(out), made[:3]))
        elif "project name" not in out:
            bad.append("%r refused without saying why: %s" % (name, tail(out)))
    return bad


def a_bad_registration_name(w):
    """`forge new DIR --name 'other\n'` (registering an existing directory) refuses a name with a trailing newline:
    exit 1, "kebab-case", no project file. Same KEBAB object as creation, so a regex that lets `\n` through fails here too."""
    d = w.register_demo("regdemo")
    before = w.snapshot()
    code, out = w.forge("new", d, "--name", "other\n")
    bad = []
    if code != 1 or "kebab-case" not in out:
        bad.append("registered under a name with a trailing newline: exit %d, want 1 naming kebab-case: %s" % (code, tail(out)))
    if w.snapshot() != before:
        bad.append("a name with a trailing newline wrote %s" % changed(before, w.snapshot())[:3])
    return bad


def a_path_not_name(w):
    bad = []
    for arg in ("./nope", "sub/nope", "~/nope", ".nope", "~nope"):
        before = w.snapshot()
        code, out = w.forge("new", arg, "--stack", "generic", "--apply")
        if code != 1 or "is not a directory" not in out:
            bad.append("%r was not refused as a path: exit %d: %s" % (arg, code, tail(out)))
        elif "give its name alone" not in out:
            bad.append("%r refused as a path without saying how to make a project: %s" % (arg, tail(out)))
        if w.snapshot() != before:
            bad.append("%r taken for a name, created %s" % (arg, changed(before, w.snapshot())[:3]))
    return bad


def a_target_exists(w):
    bad = []
    d = w.project("demo")
    os.makedirs(d)
    with open(os.path.join(d, "keep.txt"), "w") as fh:
        fh.write("mine\n")
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    if code != 1 or w.snapshot() != before:
        bad.append("wrote into a non-empty folder: exit %d, changed %s: %s" % (code, changed(before, w.snapshot())[:4], tail(out)))
    elif "not empty" not in out:
        bad.append("refused without saying the folder is not empty: %s" % tail(out))
    elif "forge new %s" % d not in out:
        bad.append("a non-empty folder refused without saying that `forge new %s` registers it: %s" % (d, tail(out)))
    # A link, even to an empty directory outside, is not a folder this run may write into.
    outside = os.path.join(w.top, "outside")
    os.makedirs(outside)
    os.symlink(outside, w.project("linked"))
    before = w.snapshot()
    code, out = w.forge("new", "linked", "--stack", "generic", "--apply")
    if code != 1 or os.listdir(outside) or w.snapshot() != before:
        bad.append("wrote through a link: exit %d, %s now holds %s: %s" % (code, outside, os.listdir(outside), tail(out)))
    return bad


def a_registered(w):
    with open(w.path("config", "projects", "taken.claude.json"), "w") as fh:
        fh.write("{}\n")
    before = w.snapshot()
    code, out = w.forge("new", "taken", "--stack", "generic", "--apply")
    if code != 1 or "already registered" not in out or w.snapshot() != before:
        return ["a registered name: exit %d, changed %s: %s" % (code, changed(before, w.snapshot())[:3], tail(out))]
    return []


def left_behind(before, after):
    return changed(before, after) + [k for k in before if k not in after]


def a_git_fails(w):
    env = dict(w.env, PATH=fake_git(w.top))
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply", env=env)
    bad = []
    if code != 1 or "git init" not in out:
        bad.append("a failing git init: exit %d, want 1 naming git init: %s" % (code, tail(out)))
    if w.snapshot() != before or os.path.lexists(w.project("demo")):
        bad.append("left behind: %s" % ", ".join(os.path.join(w.top, p) for p in left_behind(before, w.snapshot())[:6]))
    return bad


def a_git_env(w):
    """A GIT_DIR in the caller's environment (a git hook runs with one) must not decide where `git init` goes."""
    elsewhere = os.path.join(w.top, "elsewhere-git")
    env = dict(w.env, GIT_DIR=elsewhere, GIT_WORK_TREE=w.cwd)
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply", env=env)
    # The exit code is not asserted: the sync that follows reads the same variables and may refuse them; the init is what is looked at.
    if not os.path.isdir(os.path.join(w.project("demo"), ".git")) or os.path.lexists(elsewhere):
        return ["git init followed GIT_DIR: exit %d, project .git %s, %s %s: %s" % (
            code, os.path.isdir(os.path.join(w.project("demo"), ".git")), elsewhere, "made" if os.path.lexists(elsewhere) else "not made", tail(out))]
    return []


def a_record_fails_after_mkdir(w):
    """The world's lib.record raises when it is told `mkdir` (the mutation FAIL_RECORD): the folder was made one line
    earlier and must still be rolled back, exit 1, nothing left, the message saying what was removed."""
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    bad = []
    if code != 1 or "record failed" not in out:
        bad.append("a record that fails after mkdir: exit %d, want 1 with its message: %s" % (code, tail(out)))
    if w.snapshot() != before or os.path.lexists(w.project("demo")):
        bad.append("left behind: %s" % ", ".join(os.path.join(w.top, p) for p in left_behind(before, w.snapshot())[:6]))
    return bad


def a_forge_json_fails(w):
    """The project file is written, then forge.json cannot be (its folder is read-only): the project file, the
    README, .gitignore, .git and the folder this run made go; a pre-existing empty folder stays, empty; a neighbour stays."""
    if os.geteuid() == 0:
        notrun.append("forge.json failing after the project file: a read-only folder does not stop root")
        return []
    bad = []
    os.makedirs(w.project("demo"))  # empty, already there: allowed, and kept
    with open(os.path.join(w.projects, "neighbour.txt"), "w") as fh:
        fh.write("n\n")
    before = w.snapshot()
    cfg = w.path("config")
    os.chmod(cfg, 0o555)
    try:
        code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    finally:
        os.chmod(cfg, 0o755)
    if code != 1 or "forge.json" not in out:
        bad.append("forge.json not writable: exit %d, want 1 naming forge.json: %s" % (code, tail(out)))
    after = w.snapshot()
    if after != before or os.listdir(w.project("demo")):
        bad.append("left behind: %s" % ", ".join(os.path.join(w.top, p) for p in left_behind(before, after)[:6]))
    return bad


def a_sync_fails(w):
    """What sync cannot do is not undone: the project is made and registered, the exit is not 0 and the line says what to run."""
    with open(w.path("config", "mcp-registry.json"), "w") as fh:
        fh.write("[]\n")  # sync refuses a registry that is no object
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    bad = []
    if code == 0 or "forge sync --apply demo" not in out:
        bad.append("a failing sync: exit %d, want non-zero naming `forge sync --apply demo`: %s" % (code, tail(out)))
    if not os.path.isfile(w.path("config", "projects", "demo.claude.json")) or not os.path.isdir(w.project("demo")):
        bad.append("a failing sync removed the project it had made")
    return bad


def a_path_flag(w):
    bad = []
    elsewhere = os.path.join(w.top, "elsewhere")
    os.makedirs(elsewhere)
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply", "--path", elsewhere)
    if code != 0 or not os.path.isdir(os.path.join(elsewhere, "demo", ".git")) or os.path.lexists(w.project("demo")):
        bad.append("--path: exit %d, the folder is not %s/demo (or is also under projects_dir): %s" % (code, elsewhere, tail(out)))
    before = w.snapshot()
    code, out = w.forge("new", "other", "--stack", "generic", "--apply", "--path", os.path.join(w.top, "no-such-dir"))
    if code != 2 or w.snapshot() != before or os.path.lexists(os.path.join(w.top, "no-such-dir")):
        bad.append("--path of a missing folder: exit %d, changed %s: %s" % (code, changed(before, w.snapshot())[:3], tail(out)))
    return bad


def a_flags_by_mode(w):
    """Each flag belongs to one side: --name and --writes-tracked-files register, the others create."""
    bad = []
    d = w.register_demo("regdemo")
    before = w.snapshot()
    for argv in (["new", "demo", "--stack", "generic", "--name", "x"], ["new", "demo", "--stack", "generic", "--writes-tracked-files"],
                 ["new", d, "--stack", "generic"], ["new", d, "--apply"], ["new", d, "--path", w.projects], ["new", d, "--framework"],
                 ["new", d, "--yes"]):
        code, out = w.forge(*argv)
        if code != 2 or w.snapshot() != before:
            bad.append("%s: exit %d, want 2 and nothing written: %s" % (" ".join(argv[:1] + argv[2:]), code, tail(out)))
    return bad


def a_framework(w):
    """--framework on a checkout whose framework plugin cannot be served (no plugin_source here) would make a project every
    `forge sync` and `forge doctor` refuse: so the run is refused before the first write, exit 2, in one line that names what is
    missing. Control (the check taken out): `--framework wrote a project that sync refuses`."""
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--framework", "--apply")
    bad = []
    if os.path.lexists(w.path("config", "projects", "demo.claude.json")) or os.path.lexists(w.project("demo")):
        bad.append("--framework wrote a project that sync refuses: %s" % tail(out, 4))
    if code != 2 or "plugin_source" not in out or len([l for l in out.splitlines() if l.strip()]) != 1:
        bad.append("--framework: exit %d, want 2 and ONE line naming plugin_source: %s" % (code, tail(out, 4)))
    if w.snapshot() != before:
        bad.append("--framework wrote something: %s" % changed(before, w.snapshot())[:4])
    return bad


UNARMED = ("protected_paths", "checks_quick", "app_run")  # what cannot be known without looking at the project (3.6)
HANDOFF_START = "# Finish setting up demo for the agent framework"
NODE = read_json(os.path.join(sandbox.FORGE, "examples", "stacks", "node", "stack.json"))


def a_framework_made(w):
    """4.4 U8. `--framework` writes `framework: true`, `factory: "off"`, the stack's `checks` and its plugins as `plugins_keep` (the
    plugin is turned on through plugins_keep), and leaves protected_paths, checks_quick and app_run out. After the sync, `forge doctor demo`
    runs and says `NOT RUN, NOT ARMED` for those three; a handover document that names them is printed (and written nowhere); the last
    line says how to open a session. Without --framework none of the handover is printed. The dry-run writes nothing."""
    bad = []
    before = w.fingerprint()
    code, out = w.forge("new", "demo", "--stack", "node", "--framework")
    if code != 0 or w.fingerprint() != before or HANDOFF_START in out:
        bad.append("--framework dry-run: exit %d, tree changed %s, handover printed %s: %s" % (
            code, w.fingerprint() != before, HANDOFF_START in out, tail(out, 4)))
    code, out = w.forge("new", "demo", "--stack", "node", "--framework", "--apply")
    if code != 0:
        return bad + ["--framework --apply: exit %d: %s" % (code, tail(out, 6))]
    pf = read_json(w.path("config", "projects", "demo.claude.json")) or {}
    # plugins_keep: what a project without it has on (the user scope's), the stack's, and common_plugins, in that order
    for key, want in (("framework", True), ("factory", "off"), ("checks", NODE["checks"]),
                      ("plugins_keep", ["mine@mk"] + NODE["plugins"] + ["common@mk"])):
        if pf.get(key) != want:
            bad.append("project file: %s is %r, want %r" % (key, pf.get(key), want))
    for key in UNARMED:
        if key in pf:
            bad.append("%s was written into the project file: it is left unarmed" % key)
    if HANDOFF_START not in out:
        bad.append("no handover printed (a line `%s`): %s" % (HANDOFF_START, tail(out, 4)))
        handoff = ""
    else:
        handoff = out[out.index(HANDOFF_START):]
    for key in UNARMED:
        if key not in handoff:
            bad.append("handoff misses %s" % key)
    if w.project("demo") not in handoff or " ".join(NODE["checks"]) not in handoff:
        bad.append("the handover does not name the project's folder or the stack's checks")
    row = [l for l in out.splitlines() if l.startswith(("SKIP", "PASS", "FAIL", "WARN")) and "framework fields" in l]
    if len(row) != 1 or "NOT RUN, NOT ARMED" not in row[0] or any(k not in row[0] for k in UNARMED[:2]) or "app_run" in row[0]:
        bad.append("forge doctor demo: want one `framework fields` row, NOT RUN, NOT ARMED, naming protected_paths and checks_quick "
                   "and not app_run (the project has no screen): %s" % row)
    if out.find("SUMMARY:") == -1 or not out.rstrip().splitlines()[-1].startswith("open a new session in the folder"):
        bad.append("the last line is not `open a new session in the folder ...`: %s" % tail(out, 2))
    elif out.find("SUMMARY:") > out.find(HANDOFF_START) >= 0:
        bad.append("the handover came before forge doctor's report")
    entries = sorted(os.listdir(w.project("demo")))
    if entries != [".claude", ".git", ".gitignore", "README.md"] or sorted(os.listdir(os.path.join(w.project("demo"), ".claude"))) != ["settings.local.json", "toyfw.json"]:
        bad.append("the project folder holds %s (.claude: %s), want what sync writes and nothing else" % (
            entries, sorted(os.listdir(os.path.join(w.project("demo"), ".claude")))))
    code, out = w.forge("new", "plain", "--stack", "node", "--apply")
    plain_out = out
    pf = read_json(w.path("config", "projects", "plain.claude.json")) or {}
    if code != 0 or "handoff" in out.lower() or HANDOFF_START.replace("demo", "plain") in out or "framework" in pf or "checks" in pf \
            or "plugins_keep" in pf:
        bad.append("without --framework: exit %d, handover printed or framework keys written (%s): %s" % (code, sorted(pf), tail(out, 3)))
    # Without --framework the output is what it was: no doctor report, no closing line (4.4 U8 is the framework's hand-over).
    if any(m in plain_out for m in ("SUMMARY:", "forge doctor", "open a new session")):
        bad.append("without --framework: forge doctor's report or the closing line was printed: %s" % tail(plain_out, 3))
    # Turning the framework on never turns a plugin off: what the plain project has on is in the framework project's map.
    def enabled(name):
        sl = read_json(os.path.join(w.project(name), ".claude", "settings.local.json")) or {}
        user = read_json(os.path.join(w.home, ".claude", "settings.json")) or {}
        if "enabledPlugins" not in sl:  # no map: the project inherits the user scope's
            return {p for p, on in user.get("enabledPlugins", {}).items() if on}
        return {p for p, on in sl["enabledPlugins"].items() if on}
    lost = enabled("plain") - enabled("demo")
    if lost or not set(NODE["plugins"]) <= enabled("demo") or "off@mk" in enabled("demo") or "common@mk" not in enabled("demo"):
        bad.append("--framework turned plugins off: plain has %s on, the framework project %s (lost %s)" % (
            sorted(enabled("plain")), sorted(enabled("demo")), sorted(lost)))
    return bad


ANSWERS = ["--profiles", "none", "--skills", "none", "--server", "none", "--memory", "none"]  # every question answered: --check and --ui are two of them


def a_framework_checks(w):
    """The handover names the checks the project file holds: `--check pytest` narrows the stack's two, and the handover must not
    tell the agent to run the one that was dropped."""
    code, out = w.forge("new", "demo", "--stack", "python", "--framework", "--check", "pytest", *ANSWERS, "--apply")
    pf = read_json(w.path("config", "projects", "demo.claude.json")) or {}
    if code != 0 or pf.get("checks") != ["pytest"]:
        return ["--check pytest: exit %d, checks %s: %s" % (code, pf.get("checks"), tail(out, 3))]
    handoff = out[out.index(HANDOFF_START):] if HANDOFF_START in out else ""
    if "`pytest`" not in handoff or "ruff check" in handoff:
        return ["handover names a check the project file does not hold (checks %s): %s" % (pf["checks"], [l for l in handoff.splitlines() if "ruff" in l or "already set" in l])]
    return []


def a_framework_fields(w):
    """The `framework fields` row can PASS: with protected_paths and checks_quick set it is a PASS for a project without a screen
    (app_run is not asked of it), and with `ui: true` it is NOT ARMED until app_run is set too."""
    bad = []
    row = lambda name: [l for l in w.forge("doctor", name)[1].splitlines() if "framework fields" in l and l[:4] in ("SKIP", "PASS", "FAIL", "WARN")]
    for name, extra in (("shut", []), ("screen", ["--ui"])):
        code, out = w.forge("new", name, "--stack", "node", "--framework", *extra, *ANSWERS, "--apply")
        if code != 0:
            return ["forge new %s --framework: exit %d: %s" % (name, code, tail(out, 3))]
    path = w.path("config", "projects", "%s.claude.json")
    for name in ("shut", "screen"):
        pf = read_json(path % name)
        pf.update(protected_paths=["package.json"], checks_quick=["pnpm tsc --noEmit"])
        write_json(path % name, pf)
    got = row("shut")
    if len(got) != 1 or not got[0].startswith("PASS"):
        bad.append("framework fields, a project without a screen and two fields set: want PASS, got %s" % got)
    got = row("screen")
    if len(got) != 1 or not got[0].startswith("SKIP") or "app_run" not in got[0]:
        bad.append("framework fields, a project with ui true and no app_run: want NOT RUN, NOT ARMED naming app_run, got %s" % got)
    pf = read_json(path % "screen")
    pf["app_run"] = {"up": "true", "run": "", "down": "true", "url": "http://192.0.2.1:1"}
    write_json(path % "screen", pf)
    got = row("screen")
    if len(got) != 1 or not got[0].startswith("PASS"):
        bad.append("framework fields, all three set: want PASS, got %s" % got)
    return bad


def a_late_plugin(w):
    """A plugin the user enables while the questions are open (the world's ask.gather does it) is in plugins_keep, and so on in the
    project: the list is read after the questions, not before."""
    code, out = w.forge("new", "demo", "--stack", "node", "--framework", "--apply")
    pf = read_json(w.path("config", "projects", "demo.claude.json")) or {}
    if code != 0 or "late@mk" not in (pf.get("plugins_keep") or []):
        return ["a plugin enabled while the questions run is not in plugins_keep (exit %d): %s" % (code, pf.get("plugins_keep"))]
    return []


def a_doctor_fail(w):
    """A FAIL row of `forge doctor NAME` other than `instruction files` (which a fresh project always has: no CLAUDE.md yet) makes
    `forge new --framework` exit 1, after it printed that row and said the project was made. The world's doctor carries an injected row."""
    code, out = w.forge("new", "demo", "--stack", "node", "--framework", "--apply")
    bad = []
    if code != 1 or "injected failure" not in out or "demo is made and registered" not in out or "toy check" not in out.split("is made and registered")[-1]:
        bad.append("a FAIL row other than instruction files did not make forge new exit 1 (exit %d): %s" % (code, tail(out, 3)))
    if not os.path.isdir(w.project("demo")) or not os.path.exists(w.path("config", "projects", "demo.claude.json")):
        bad.append("the project was removed after doctor failed")
    return bad


# ---------------------------------------------------------------- 4.4 U9: the options the old registering script had and forge new lacked
# (--account-server, --memory lite, --worktree-guard, --no-baseline, --no-git). Each is asserted against the effect the script gave it.

LITE = "claude-mem-lite@sdsrss"
POSTHOG = "https://mcp.posthog.com/mcp?project_id=42"
NOTION = "https://mcp.notion.com/mcp"
OTHER_POSTHOG = "https://mcp.posthog.com/mcp?project_id=1"
PARITY_ANSWERS = ["--profiles", "none", "--skills", "none", "--server", "none"]  # every question but memory, which each test gives


def registry_servers(w):
    return (read_json(w.path("config", "mcp-registry.json")) or {}).get("servers", {})


def a_account_server(w):
    """`--account-server SERVICE[=PIN]` adds the registry entry `<service>-<name>` (type http, the service's URL, pinned when a pin is
    given, a `_doc` naming the project) and lists it in the project's servers; a bare service that has a pin form is said to be UNPINNED
    in the plan. An unknown service and a pin on a service that has none are refused before the first write."""
    bad = []
    before = w.fingerprint()
    code, out = w.forge("new", "demo", "--stack", "generic", "--account-server", "posthog", "--account-server", "notion")
    if code != 0 or w.fingerprint() != before or "posthog-demo" not in out or "UNPINNED" not in out or "notion-demo" not in out:
        bad.append("--account-server dry-run: exit %d, want 0, nothing written and the plan naming posthog-demo UNPINNED and notion-demo "
                   "(tree changed %s): %s" % (code, w.fingerprint() != before, tail(out, 6)))
    for argv, needle in ((["--account-server", "nope"], "unknown service 'nope'"), (["--account-server", "notion=5"], "no project pin")):
        before = w.snapshot()
        code, out = w.forge("new", "demo", "--stack", "generic", *argv, "--apply")
        if code != 2 or needle not in out or w.snapshot() != before:
            bad.append("%s: exit %d, want 2 saying %r and nothing written: %s" % (" ".join(argv), code, needle, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "generic", "--account-server", "posthog=42", "--account-server", "notion", "--apply")
    if code != 0:
        return bad + ["--account-server --apply: exit %d: %s" % (code, tail(out, 6))]
    servers = registry_servers(w)
    want = {"posthog-demo": POSTHOG, "notion-demo": NOTION}
    if set(servers) != set(want):
        bad.append("the registry holds %s, want exactly %s" % (sorted(servers), sorted(want)))
    for key, url in want.items():
        entry = servers.get(key) or {}
        if entry.get("type") != "http" or entry.get("url") != url or "demo" not in str(entry.get("_doc")):
            bad.append("registry entry %s is %s, want type http, url %s and a _doc naming demo" % (key, entry, url))
    pf = read_json(w.path("config", "projects", "demo.claude.json")) or {}
    if pf.get("servers") != list(want):
        bad.append("the project's servers are %s, want %s" % (pf.get("servers"), list(want)))
    held = ((read_json(os.path.join(w.home, ".claude.json")) or {}).get("projects", {}).get(os.path.realpath(w.project("demo"))) or {}).get("mcpServers", {})
    if set(held) != set(want):
        bad.append("forge sync did not give the project its servers: ~/.claude.json holds %s" % sorted(held))
    return bad


def a_account_server_existing(w):
    """A registry entry of the name that has the same URL is used as it is (the registry is not rewritten); one with another URL is a
    login that a new URL would replace, so the run is refused, exit 2, before the first write, and the entry stays."""
    bad = []
    reg_path = w.path("config", "mcp-registry.json")
    reg = read_json(reg_path)
    reg["servers"]["notion-keep"] = {"_doc": "made earlier", "type": "http", "url": NOTION}
    reg["servers"]["posthog-clash"] = {"type": "http", "url": OTHER_POSTHOG}
    write_json(reg_path, reg)
    text = open(reg_path, encoding="utf-8").read()
    code, out = w.forge("new", "keep", "--stack", "generic", "--account-server", "notion", "--apply")
    if code != 0 or open(reg_path, encoding="utf-8").read() != text or (read_json(w.path("config", "projects", "keep.claude.json")) or {}).get("servers") != ["notion-keep"]:
        bad.append("a registry entry with the same URL was not used as it is: exit %d: %s" % (code, tail(out)))
    before = w.snapshot()
    code, out = w.forge("new", "clash", "--stack", "generic", "--account-server", "posthog=42", "--apply")
    if code != 2 or "posthog-clash" not in out or w.snapshot() != before:
        bad.append("a registry entry with another url: exit %d, want 2 naming posthog-clash and nothing written: %s" % (code, tail(out)))
    if registry_servers(w).get("posthog-clash", {}).get("url") != OTHER_POSTHOG:
        bad.append("a registry entry with another url was replaced")
    return bad


def a_account_server_rollback(w):
    """The registry is written before the project file; when a later step fails (the world's forge.json write is made to) the registry,
    the project file, the folder and forge.json are as they were. Exit 1."""
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--account-server", "notion", "--apply")
    bad = []
    if code != 1 or "injected after the registry" not in out:
        bad.append("the injected failure did not stop the run: exit %d: %s" % (code, tail(out)))
    if w.snapshot() != before or os.path.lexists(w.project("demo")):
        bad.append("left behind: %s" % ", ".join(os.path.join(w.top, p) for p in left_behind(before, w.snapshot())[:6]))
    return bad


def a_registry_copy_kept(w):
    """A later step fails and the registry cannot be put back either (the world's rollback fails writing it): the message says
    `cp COPY REGISTRY`, and COPY must still be there, holding the registry as it was."""
    original = open(w.path("config", "mcp-registry.json"), encoding="utf-8").read()
    code, out = w.forge("new", "demo", "--stack", "generic", "--account-server", "notion", "--apply")
    m = re.search(r"put it back with: cp (\S+) ", out)
    if not m:
        return ["no `cp COPY REGISTRY` hint after the failed restore (exit %d): %s" % (code, tail(out, 4))]
    try:
        held = open(m.group(1), encoding="utf-8").read()
    except OSError:
        return ["the recovery copy %s named by the hint is gone" % m.group(1)]
    return [] if held == original else ["the recovery copy does not hold the registry as it was"]


def a_other_memory_fail(w):
    """The memory row fails for a reason other than the empty store (the world's memory_doctor adds a failing `memory-backend` check):
    `forge new --framework --memory lite` still exits 1, prints the row, and says the project is made but doctor fails."""
    code, out = w.forge("new", "demo", "--stack", "node", "--framework", *PARITY_ANSWERS, "--memory", "lite", "--apply")
    bad = []
    if code != 1 or not re.search(r"^FAIL  memory ", out, re.M) or "fails beyond" not in out or "open a new session in the folder" in out:
        bad.append("another memory failure was tolerated: exit %d, want 1, the memory row printed and no closing line: %s" % (code, tail(out, 3)))
    if not os.path.exists(w.path("config", "projects", "demo.claude.json")):
        bad.append("the project was removed after doctor failed")
    return bad


def project_of(w, name="demo"):
    return read_json(w.path("config", "projects", "%s.claude.json" % name)) or {}


def settings_local(w, name="demo"):
    return read_json(os.path.join(w.project(name), ".claude", "settings.local.json")) or {}


def a_memory_lite(w):
    """`--memory lite` is the claude-mem-lite plugin and nothing else: it joins plugins_keep (after the stack's chosen --plugin), no server
    is added, the project's settings turn the plugin on, and the generator derives CLAUDE_MEM_DIR from the project name. `--memory none`
    and a project with no memory answer carry neither the plugin nor the store."""
    bad = []
    before = w.fingerprint()
    code, out = w.forge("new", "demo", "--stack", "generic", *PARITY_ANSWERS, "--memory", "lite")
    if code != 0 or w.fingerprint() != before or "claude-mem-lite" not in out:
        bad.append("--memory lite dry-run: exit %d, want 0, nothing written and the plan naming claude-mem-lite (tree changed %s): %s" % (
            code, w.fingerprint() != before, tail(out, 6)))
    code, out = w.forge("new", "demo", "--stack", "generic", *PARITY_ANSWERS, "--memory", "lite", "--apply")
    if code != 0:
        return bad + ["--memory lite --apply: exit %d: %s" % (code, tail(out, 6))]
    pf = project_of(w)
    if pf.get("plugins_keep") != [LITE] or pf.get("servers") != []:
        bad.append("--memory lite: plugins_keep %s and servers %s, want [%s] and []" % (pf.get("plugins_keep"), pf.get("servers"), LITE))
    sl = settings_local(w)
    if sl.get("enabledPlugins", {}).get(LITE) is not True:
        bad.append("the project's settings do not turn %s on: %s" % (LITE, sl.get("enabledPlugins")))
    store = (sl.get("env") or {}).get("CLAUDE_MEM_DIR", "")
    if not store.endswith(os.path.join("data", "memory-lite", "demo")):
        bad.append("the generator did not derive the store from the name: CLAUDE_MEM_DIR is %r" % store)
    code, out = w.forge("new", "withplugin", "--stack", "node", *PARITY_ANSWERS, "--memory", "lite", "--plugin", NODE["plugins"][0], "--apply")
    if code != 0 or project_of(w, "withplugin").get("plugins_keep") != [NODE["plugins"][0], LITE]:
        bad.append("--memory lite with --plugin: exit %d, plugins_keep %s, want [%s, %s]: %s" % (
            code, project_of(w, "withplugin").get("plugins_keep"), NODE["plugins"][0], LITE, tail(out)))
    code, out = w.forge("new", "none", "--stack", "generic", *PARITY_ANSWERS, "--memory", "none", "--apply")
    if code != 0 or "plugins_keep" in project_of(w, "none") or "CLAUDE_MEM_DIR" in (settings_local(w, "none").get("env") or {}):
        bad.append("--memory none carries the plugin or its store (exit %d): %s %s" % (code, project_of(w, "none").get("plugins_keep"),
                                                                                         (settings_local(w, "none").get("env") or {}).get("CLAUDE_MEM_DIR")))
    return bad


def a_memory_lite_common(w):
    """The common layer already lists the plugin (skill_keep.common_plugins): `--memory lite` is the same backend, not a second one, so
    it is not refused as `one per project` and plugins_keep names it once."""
    path = w.path("config", "forge.json")
    doc = read_json(path)
    doc["skill_keep"]["common_plugins"] = [LITE]
    write_json(path, doc)
    code, out = w.forge("new", "demo", "--stack", "generic", *PARITY_ANSWERS, "--memory", "lite", "--plugin", "context7@claude-plugins-official", "--apply")
    keep = project_of(w).get("plugins_keep")
    if code != 0 or keep != ["context7@claude-plugins-official", LITE]:
        return ["--memory lite with the plugin in common_plugins: exit %d, plugins_keep %s, want it once: %s" % (code, keep, tail(out))]
    return []


def a_memory_lite_framework(w):
    """With --framework the plugin joins the plugins the framework project keeps (all the plain project has on), once, at the end."""
    code, out = w.forge("new", "demo", "--stack", "node", "--framework", *PARITY_ANSWERS, "--memory", "lite", "--apply")
    want = ["mine@mk"] + NODE["plugins"] + ["common@mk", LITE]
    keep = project_of(w).get("plugins_keep")
    bad = []
    if keep != want:
        bad.append("--framework --memory lite: exit %d, plugins_keep %s, want %s: %s" % (code, keep, want, tail(out, 3)))
    # A fresh lite project has no claude-mem-lite.db until its first session: the memory row's one FAIL for it is expected, like `instruction files`.
    if code != 0 or "open a new session in the folder" not in out:
        bad.append("--framework --memory lite on a healthy fresh project: exit %d, want 0 and the closing line: %s" % (code, tail(out, 3)))
    return bad


def a_worktree_guard(w):
    """`--worktree-guard` writes `"worktree_guard": true` and the sync wires hooks/worktree_guard.py as a PreToolUse entry of the project;
    without it there is neither. As an option of the stack question it is an answer, so alone, with nothing asked, it makes every other
    question need its flag."""
    bad = []
    code, out = w.forge("new", "demo", "--stack", "generic", *PARITY_ANSWERS, "--memory", "none", "--worktree-guard", "--apply")
    if code != 0 or project_of(w).get("worktree_guard") is not True:
        return ["--worktree-guard: exit %d, worktree_guard %r, want True: %s" % (code, project_of(w).get("worktree_guard"), tail(out))]
    wired = [h for g in (settings_local(w).get("hooks") or {}).get("PreToolUse", []) for h in g.get("hooks", []) if "worktree_guard.py" in h.get("command", "")]
    if len(wired) != 1:
        bad.append("sync did not wire hooks/worktree_guard.py as one PreToolUse entry: %s" % (settings_local(w).get("hooks"),))
    if "options     worktree_guard" not in out:
        bad.append("the plan does not show the option: %s" % tail(out, 12))
    code, out = w.forge("new", "plain", "--stack", "generic", *PARITY_ANSWERS, "--memory", "none", "--apply")
    if code != 0 or "worktree_guard" in project_of(w, "plain") or "worktree_guard.py" in json.dumps(settings_local(w, "plain")):
        bad.append("a project without the flag has a worktree guard (exit %d)" % code)
    before = w.snapshot()
    code, out = w.forge("new", "alone", "--stack", "generic", "--worktree-guard", "--apply")
    if code != 2 or "--memory" not in out or w.snapshot() != before:
        bad.append("--worktree-guard alone: exit %d, want 2 naming the missing --memory and nothing written: %s" % (code, tail(out)))
    return bad


def a_no_baseline(w):
    """`--no-baseline` leaves out the project's skill_keep.extras row: config/forge.json is not written at all (byte for byte as it was)
    and the plan says the row is skipped. Without the flag the row is there. With skills answered the row would hold them, so the run is
    refused, exit 2, before the first write."""
    bad = []
    os.makedirs(os.path.join(w.home, ".claude", "skills", "alpha"))
    with open(os.path.join(w.home, ".claude", "skills", "alpha", "SKILL.md"), "w") as fh:
        fh.write("---\nname: alpha\ndescription: toy\n---\n")
    forge_json = w.path("config", "forge.json")
    text = open(forge_json, encoding="utf-8").read()
    code, out = w.forge("new", "bare", "--stack", "generic", "--no-baseline", "--apply")
    if code != 0 or open(forge_json, encoding="utf-8").read() != text or "no-baseline" not in out or "wrote  config/forge.json" in out:
        bad.append("--no-baseline: exit %d, forge.json changed %s, want 0, unchanged, and the plan saying --no-baseline: %s" % (
            code, open(forge_json, encoding="utf-8").read() != text, tail(out, 8)))
    if not os.path.isfile(w.path("config", "projects", "bare.claude.json")):
        bad.append("--no-baseline made no project file")
    code, out = w.forge("new", "with", "--stack", "generic", "--apply")
    if code != 0 or "with.claude.json" not in (read_json(forge_json).get("skill_keep", {}).get("extras") or {}):
        bad.append("without the flag there is no skill_keep.extras row (exit %d)" % code)
    before = w.snapshot()
    code, out = w.forge("new", "skilled", "--stack", "generic", "--profiles", "none", "--skills", "alpha", "--server", "none", "--memory", "none",
                        "--no-baseline", "--apply")
    if code != 2 or "--no-baseline" not in out or "alpha" not in out or w.snapshot() != before:
        bad.append("--no-baseline with --skills alpha: exit %d, want 2 naming --no-baseline and alpha and nothing written: %s" % (code, tail(out)))
    return bad


def a_no_baseline_existing_row(w):
    """`--no-baseline` on a name that already has a skill_keep.extras row, empty or not (left from a project that was removed): the project
    would still be enrolled (sync_skill_keep.py gives a row's project the common skills and switches trimming on), so the run is refused
    before the first write, exit 2, naming the row; forge.json is untouched and the row is never deleted here. A name with no row is made.
    Before: only a row that held skills was refused, so an empty row (the one a plain `forge new` leaves) was kept, the run said
    `skills row  skipped (--no-baseline)` and exited 0, and `sync_skill_keep.py --check` then exited 1 with `extras +['alpha'] -[]`.
    The world has a common skill: with `common_skills: []` an empty row changes nothing, which hid this."""
    bad = []
    forge_json = w.path("config", "forge.json")
    doc = read_json(forge_json)
    doc["skill_keep"]["common_skills"] = ["alpha"]
    extras = doc["skill_keep"].setdefault("extras", {})
    extras["demo.claude.json"] = ["alpha"]
    extras["empty.claude.json"] = []
    write_json(forge_json, doc)
    for name, held in (("demo", "skills"), ("empty", "empty")):
        before = w.snapshot()
        code, out = w.forge("new", name, "--stack", "generic", "--no-baseline", "--apply")
        if code != 2 or "%s.claude.json" % name not in out or "skill_keep.extras" not in out or w.snapshot() != before:
            bad.append("--no-baseline with an existing %s extras row: exit %d, want 2 naming %s.claude.json and skill_keep.extras, nothing written: %s"
                       % (held, code, name, tail(out)))
    code, out = w.forge("new", "fresh", "--stack", "generic", "--no-baseline", "--apply")
    if code != 0 or "fresh.claude.json" in read_json(forge_json)["skill_keep"]["extras"]:
        bad.append("--no-baseline with no row: exit %d, want 0 and no row for fresh.claude.json: %s" % (code, tail(out)))
    return bad


def a_no_git(w):
    """`--no-git` makes the folder, .gitignore and README.md and no `.git`, the sync that follows still works, and the output says there is
    no git init. Without the flag there is a `.git`."""
    bad = []
    code, out = w.forge("new", "demo", "--stack", "generic", "--no-git", "--apply")
    entries = sorted(os.listdir(w.project("demo"))) if os.path.isdir(w.project("demo")) else []
    if code != 0 or ".git" in entries or "README.md" not in entries or ".gitignore" not in entries:
        bad.append("--no-git: exit %d, the folder holds %s, want exit 0 and no .git: %s" % (code, entries, tail(out, 6)))
    if "ran    git init" in out or "no git init" not in out:
        bad.append("--no-git: the output does not say there is no git init: %s" % tail(out, 12))
    code, out = w.forge("new", "plain", "--stack", "generic", "--apply")
    if code != 0 or not os.path.isdir(os.path.join(w.project("plain"), ".git")):
        bad.append("without --no-git there is no .git (exit %d)" % code)
    return bad


def a_parity_flags_by_mode(w):
    """The new flags belong to making a project: a directory that is registered, and a profile, refuse them (exit 2, nothing written)."""
    bad = []
    d = w.register_demo("regdemo")
    before = w.snapshot()
    for flag in (["--no-git"], ["--no-baseline"], ["--account-server", "notion"], ["--worktree-guard"], ["--memory", "lite"]):
        argvs = [["new", d, *flag]] + ([["new", "@code", *flag]] if flag[0] in ("--no-git", "--no-baseline", "--account-server") else [])
        for argv in argvs:  # a profile refuses the flags of making before it looks for the project (test_ask.py has the ones it asks)
            code, out = w.forge(*argv, cwd=d)
            if code != 2 or "belong to making" not in out or w.snapshot() != before:
                bad.append("%s: exit %d, want 2 saying the flag belongs to making a project, and nothing written: %s" % (" ".join(argv[:1] + argv[2:]), code, tail(out)))
    return bad


def a_help(w):
    code, out = w.forge("new", "--help")
    flags = ("--path", "--stack", "--framework", "--yes", "--apply", "--name", "--writes-tracked-files",
             "--account-server", "--worktree-guard", "--no-baseline", "--no-git", "--memory")
    miss = [f for f in flags if f not in out]
    return ["`forge new --help` does not list %s" % ", ".join(miss)] if code != 0 or miss else []


def a_unknown_stack(w):
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "cobol", "--apply")
    missing = [n for n in SIX if n not in out]
    if code != 2 or missing or w.snapshot() != before:
        return ["an unknown stack: exit %d, want 2 naming all six stacks (missing %s) and nothing written: %s" % (code, missing, tail(out))]
    return []


# ---------------------------------------------------------------- 4.4 U5: the stacks are data (examples/stacks/<stack>/)

SIX = ("generic", "next", "node", "python", "rust", "tauri")
STACK_KEYS = ("description", "servers", "plugins", "checks", "skill_sets")
PERSONAL = re.compile(r"/home/|/Users/|@(?!example\.(com|org|test))[\w.-]+\.\w+")


def a_stacks_created(w):
    """Every stack makes a project whose .gitignore ignores .env and holds no placeholder, and whose README is `# NAME`."""
    bad = []
    for stack in SIX:
        name = "p-%s" % stack
        code, out = w.forge("new", name, "--stack", stack, "--apply")
        gi_path = os.path.join(w.project(name), ".gitignore")
        if code != 0 or not os.path.exists(gi_path):
            bad.append("stack %s: exit %d, no project: %s" % (stack, code, tail(out, 4)))
            continue
        gi = open(gi_path).read()
        if ".env" not in gi.splitlines():
            bad.append(".gitignore of stack %s does not ignore .env: %r" % (stack, gi[:60]))
        if "{{" in gi:
            bad.append("placeholder left in .gitignore of stack %s" % stack)
        rd = open(os.path.join(w.project(name), "README.md")).read()
        if rd != "# %s\n" % name:
            bad.append("README.md of stack %s is %r, want %r" % (stack, rd, "# %s\n" % name))
    return bad


def a_stack_files(w):
    """Every stack folder is complete on its own: a stack.json that parses with the five keys (a description, four lists of
    strings, nothing else), a gitignore, no personal data; and the stacks are exactly the six."""
    root = w.path("examples", "stacks")
    bad = []
    found = sorted(os.listdir(root)) if os.path.isdir(root) else []
    if found != sorted(SIX):
        bad.append("examples/stacks holds %s, want %s" % (found, sorted(SIX)))
    for stack in found:
        for fn in ("stack.json", "gitignore"):
            p = os.path.join(root, stack, fn)
            if not os.path.isfile(p):
                bad.append("stack %s has no %s" % (stack, fn))
            elif PERSONAL.search(open(p).read()):
                bad.append("stack %s: %s holds personal data" % (stack, fn))
        doc = read_json(os.path.join(root, stack, "stack.json"))
        if not isinstance(doc, dict):
            bad.append("stack %s: stack.json does not parse as an object" % stack)
            continue
        if sorted(doc) != sorted(STACK_KEYS):
            bad.append("stack %s: stack.json has the keys %s, want %s" % (stack, sorted(doc), sorted(STACK_KEYS)))
        elif not isinstance(doc["description"], str) or not doc["description"].strip() or \
                not all(isinstance(doc[k], list) and all(isinstance(x, str) for x in doc[k]) for k in STACK_KEYS[1:]):
            bad.append("stack %s: stack.json has a wrong type (description a text, the rest lists of texts)" % stack)
    return bad


def a_generic_as_182(w, base_new):
    """`--stack generic` writes the same .gitignore and README, byte for byte, as 182's head did (its constants)."""
    m = re.search(r'GENERIC_GITIGNORE = """(.*?)"""', base_new, re.S)
    if not m:
        return ["the base revision's forge/new.py holds no GENERIC_GITIGNORE"]
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    bad = []
    got = open(os.path.join(w.project("demo"), ".gitignore")).read() if os.path.exists(os.path.join(w.project("demo"), ".gitignore")) else None
    if got != m.group(1):
        bad.append("generic .gitignore differs from 182's head: %r vs %r" % ((got or "")[:50], m.group(1)[:50]))
    rd = open(os.path.join(w.project("demo"), "README.md")).read() if os.path.exists(os.path.join(w.project("demo"), "README.md")) else None
    if rd != "# demo\n":
        bad.append("generic README differs from 182's head: %r" % rd)
    return bad


def a_unresolved(w):
    """A `{{X}}` in a stack file, with no value: exit 2 naming `unresolved {{X}} in stacks/generic/gitignore`, in the plan as well
    as with --apply, and no folder, project file or row is left (the world carries the placeholder; see UNRESOLVED)."""
    bad = []
    for extra in ([], ["--apply"]):
        before = w.snapshot()
        code, out = w.forge("new", "demo", "--stack", "generic", *extra)
        gi = os.path.join(w.project("demo"), ".gitignore")
        if os.path.exists(gi) and "{{X}}" in open(gi).read():
            bad.append("placeholder left in .gitignore")
        if code != 2 or "unresolved {{X}} in stacks/generic/gitignore" not in out:
            bad.append("a {{X}} with no value%s: exit %d, want 2 naming `unresolved {{X}} in stacks/generic/gitignore`: %s" % (" ".join([""] + extra), code, tail(out)))
        if os.path.lexists(w.project("demo")) or w.snapshot() != before:
            bad.append("an unresolved placeholder left %s" % changed(before, w.snapshot())[:4])
    return bad


UNRESOLVED = [(os.path.join("examples", "stacks", "generic", "gitignore"), "Thumbs.db\n", "Thumbs.db\n{{X}}\n")]
BROKEN = [(os.path.join("examples", "stacks", "node", "stack.json"), '  "checks": ["pnpm test"],\n', "")]


def a_bad_stack_json(w):
    """A stack.json that lacks a key (here node's `checks`, taken out in this world) is refused before the first write, exit 2, one
    line naming the file and the key; another stack still works."""
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "node", "--apply")
    bad = []
    if code != 2 or "stacks/node/stack.json" not in out or "checks" not in out or len([l for l in out.splitlines() if l.strip()]) != 1:
        bad.append("a stack.json without checks: exit %d, want 2 and ONE line naming stacks/node/stack.json and checks: %s" % (code, tail(out)))
    if os.path.lexists(w.project("demo")) or w.snapshot() != before:
        bad.append("a broken stack.json left %s" % changed(before, w.snapshot())[:4])
    return bad


UNUSED_SCRIPT = """import json, sys
sys.path.insert(0, sys.argv[1])
from forge import new
text, errors, warnings = new.substitute("generic", {"gitignore": "a {{NAME}}\\n"}, {"NAME": "demo", "OTHER": "x"})
print(json.dumps({"text": text, "errors": errors, "warnings": warnings}))
"""


def a_unused_argument(w):
    """A value nothing used is a warning (not an error); the one used is replaced and not warned about."""
    script = os.path.join(w.tmp, "unused.py")
    with open(script, "w") as fh:
        fh.write(UNUSED_SCRIPT)
    r = subprocess.run([sys.executable, script, w.root], cwd=w.cwd, env=w.env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    got = None
    try:
        got = json.loads(r.stdout)
    except ValueError:
        pass
    if not got:
        return ["could not call forge.new.substitute: %s" % tail(r.stdout + r.stderr, 3)]
    bad = []
    if got["text"] != {"gitignore": "a demo\n"} or got["errors"]:
        bad.append("substitute: text %r, errors %r, want the NAME replaced and no error" % (got["text"], got["errors"]))
    if not (len(got["warnings"]) == 1 and "OTHER" in got["warnings"][0]):
        bad.append("an unused argument not warned about: warnings %s" % got["warnings"])
    return bad


def a_no_forge_json(w):
    os.unlink(w.path("config", "forge.json"))
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    if code != 1 or "config/forge.json missing" not in out:
        return ["no forge.json: exit %d, want 1 'config/forge.json missing': %s" % (code, tail(out))]
    return []


def a_name_or_path(w):
    """A bare word that is a directory in the current folder is registered, and the first line says so; with a creation flag it
    is refused, exit 2, naming both ways out; a bare word that is no directory is a name; a path form is always a path."""
    bad = []
    os.makedirs(os.path.join(w.cwd, "demo"))
    code, out = w.forge("new", "demo")
    first = out.splitlines()[0] if out.strip() else ""
    want = ("forge new: ./demo exists here, registering it (nothing is created; to create a new project named demo elsewhere, "
            "run it from another folder or give --path)")
    pf = read_json(w.path("config", "projects", "demo.claude.json")) or {}
    if code != 0 or first != want:
        bad.append("name taken for a path silently: exit %d, first line %r, want %r" % (code, first, want))
    if pf.get("project_path") != os.path.realpath(os.path.join(w.cwd, "demo")) or os.listdir(w.projects):
        bad.append("registering ./demo: project_path %r, projects_dir holds %s" % (pf.get("project_path"), os.listdir(w.projects)))
    os.makedirs(os.path.join(w.cwd, "other"))
    for extra in (["--stack", "generic"], ["--apply"], ["--path", w.projects], ["--framework"]):
        before = w.snapshot()
        code, out = w.forge("new", "other", *extra)
        if code != 2 or w.snapshot() != before:
            bad.append("./other with %s: exit %d, want 2 and nothing written; changed %s: %s" % (extra[0], code, changed(before, w.snapshot())[:3], tail(out)))
        elif "forge new ./other" not in out or "--path" not in out or "registers it" in out or len(out.strip().splitlines()) != 1:
            bad.append("./other with %s: want ONE line naming `forge new ./other` and --path, not 'registers it': %s" % (extra[0], tail(out)))
    # a bare word that is no directory in the current folder is a name to create, even beside other directories
    code, out = w.forge("new", "fresh", "--stack", "generic", "--apply")
    if code != 0 or not os.path.isdir(os.path.join(w.projects, "fresh", ".git")):
        bad.append("a bare word that is no directory here was not made: exit %d: %s" % (code, tail(out)))
    # a path form is always a path: no note, however it is written
    os.makedirs(os.path.join(w.cwd, "pathy"))
    code, out = w.forge("new", "./pathy")
    if code != 0 or "exists here" in out:
        bad.append("./pathy: exit %d, a path form carries no note: %s" % (code, tail(out)))
    return bad


def a_rerun_in_projects(w):
    """The project just made, asked for again from inside projects_dir: it says it exists and is registered."""
    bad = []
    code, out = w.forge("new", "again", "--stack", "generic", "--apply")
    if code != 0:
        return ["could not make the project to ask for again: exit %d: %s" % (code, tail(out))]
    for flags in (["--stack", "generic", "--apply"], []):
        before = w.snapshot()
        code, out = w.forge("new", "again", *flags, cwd=w.projects)
        if code == 0 or w.snapshot() != before or "registers it" in out or "already exists" not in out or "registered" not in out:
            bad.append("again %s from projects_dir: exit %d, want a refusal saying it already exists and is registered, nothing written: %s"
                       % (" ".join(flags) or "(no flags)", code, tail(out)))
    return bad


def a_lock(w):
    """Another run holds forge new's lock: this one waits, creates nothing meanwhile, and then goes on."""
    state = os.path.join(w.home, ".local", "state", "forge")
    os.makedirs(state, exist_ok=True)
    held, bad = [], []

    def hold():
        with open(os.path.join(state, "new.lock"), "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            held.append(1)
            time.sleep(2.5)

    t = threading.Thread(target=hold)
    t.start()
    while not held:
        time.sleep(0.02)
    proc = w.start("new", "demo", "--stack", "generic", "--apply")
    time.sleep(1.5)
    if os.path.lexists(w.project("demo")):
        bad.append("wrote while another run held the lock: %s exists" % w.project("demo"))
    out = proc.communicate(timeout=120)[0]
    t.join()
    if proc.returncode != 0 or not os.path.isdir(os.path.join(w.project("demo"), ".git")):
        bad.append("after the lock was freed the run did not finish: exit %d: %s" % (proc.returncode, tail(out)))
    return bad


def a_two_same_name(w):
    """Two runs at once for the same name, the folder already there and empty: one makes it, the other exits in one line
    and removes nothing the winner made. Control (no lock, no second check): `two runs for one name: exits [0, 0]`."""
    os.makedirs(w.project("same"))
    env = w.slow_env(2)
    procs = w.start_together([{"args": ["new", "same", "--stack", "generic", "--apply"], "env": env}] * 2)
    res = sorted((p.communicate(timeout=120)[0], p.returncode) for p in procs)
    codes = sorted(c for _, c in res)
    bad = []
    # 2 when the loser lost the race under the lock, 1 when it came late enough to see the folder already in use: either way one line.
    if codes[0] != 0 or codes[1] not in (1, 2):
        bad.append("two runs for one name: exits %s, want one 0 and one 1 or 2: %s" % (codes, " || ".join(tail(o, 3) for o, _ in res)))
    loser = [o for o, c in res if c != 0]
    if loser and len([l for l in loser[0].splitlines() if l.startswith("! ")]) != 1:  # the plan it printed before the lock is not the refusal
        bad.append("two runs for one name: the loser did not refuse in exactly one `!` line: %s" % tail(loser[0]))
    entries = set(os.listdir(w.project("same")))
    if entries != {".git", ".gitignore", "README.md", ".claude"}:
        bad.append("two runs for one name: the winner's folder holds %s, want .git .gitignore README.md .claude (the loser removed or added something)" % sorted(entries))
    return bad


def a_two_names(w):
    """Two runs at once for different names: forge.json keeps both skill_keep.extras rows.
    Control (no lock, no re-read): `lost a skill_keep.extras row`."""
    env = w.slow_env(2)
    procs = w.start_together([{"args": ["new", n, "--stack", "generic", "--apply"], "env": env} for n in ("aa", "bb")])
    outs = [(p.communicate(timeout=120)[0], p.returncode) for p in procs]
    bad = []
    if [c for _, c in outs] != [0, 0]:
        bad.append("two runs for two names: exits %s: %s" % ([c for _, c in outs], " || ".join(tail(o, 3) for o, _ in outs)))
    extras = ((read_json(w.path("config", "forge.json")) or {}).get("skill_keep") or {}).get("extras", {})
    for n in ("aa", "bb"):
        if extras.get("%s.claude.json" % n) != []:
            bad.append("lost a skill_keep.extras row: %s.claude.json (forge.json has %s)" % (n, sorted(extras)))
        if not os.path.isfile(w.path("config", "projects", "%s.claude.json" % n)):
            bad.append("no project file for %s" % n)
    return bad


def a_path_outside_world(w):
    """A toy HOME writes its toy world only: a --path outside it is refused before anything is made there.
    Control (no check): `made outside the world`."""
    outside = sandbox.mkdtemp("new-outside-")
    bad = []
    before = w.snapshot()
    for extra in ([], ["--yes"]):
        code, out = w.forge("new", "demo", "--stack", "generic", "--apply", "--path", outside, *extra)
        if os.listdir(outside):
            bad.append("made outside the world: %s now holds %s" % (outside, os.listdir(outside)))
            break
        if code == 0 or w.snapshot() != before:
            bad.append("--path outside the world: exit %d, changed %s: %s" % (code, changed(before, w.snapshot())[:3], tail(out)))
    sandbox.rmtree(outside)
    return bad


def a_path_in_checkout(w):
    """A target inside the forge checkout, or an empty --path, is refused with one line and nothing written."""
    bad = []
    os.makedirs(os.path.join(w.root, "docs", "sub"), exist_ok=True)
    cases = [("--path inside the checkout", ["--path", w.root]), ("--path in a folder of the checkout", ["--path", os.path.join(w.root, "docs")]),
             ("an empty --path", ["--path", ""])]
    for n, (label, extra) in enumerate(cases):  # a name of its own each: an old run that makes one must not make the next refuse as registered
        before = w.snapshot()
        code, out = w.forge("new", "case%d" % n, "--stack", "generic", "--apply", *extra)
        if code == 0 or w.snapshot() != before or len([l for l in out.splitlines() if l.strip()]) != 1:
            bad.append("%s: exit %d, want a refusal in one line and nothing written; changed %s: %s" % (label, code, changed(before, w.snapshot())[:3], tail(out)))
    doc = read_json(w.path("config", "forge.json"))
    doc["projects_dir"] = os.path.join(w.root, "docs")
    write_json(w.path("config", "forge.json"), doc)
    before = w.snapshot()
    code, out = w.forge("new", "viadir", "--stack", "generic", "--apply")
    if code == 0 or w.snapshot() != before:
        bad.append("projects_dir inside the checkout: exit %d, changed %s: %s" % (code, changed(before, w.snapshot())[:3], tail(out)))
    return bad


def a_bad_projects_dir(w):
    """projects_dir relative, empty, a list, a ~user or missing: exit 2, nothing written. Control (the absolute check
    taken out): `a relative projects_dir was used`."""
    bad = []
    os.makedirs(os.path.join(w.cwd, "pd"))
    for value in ("pd", "", ["x"], "~nobodyatall/x", os.path.join(w.top, "missing")):
        doc = read_json(w.path("config", "forge.json"))
        doc["projects_dir"] = value
        write_json(w.path("config", "forge.json"), doc)
        before = w.snapshot()
        code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
        if os.path.lexists(os.path.join(w.cwd, "pd", "demo")):
            bad.append("a relative projects_dir was used: %s" % os.path.join(w.cwd, "pd", "demo"))
        elif code != 2 or w.snapshot() != before:
            bad.append("projects_dir %r: exit %d, want 2 and nothing written; changed %s: %s" % (value, code, changed(before, w.snapshot())[:3], tail(out)))
    return bad


def a_signals(w):
    """TERM or INT in the middle of --apply (here, in a slow git init) rolls back what the run made, as a failure does.
    Control (no handler): `left behind after SIGTERM`."""
    bad = []
    env = w.slow_env(1.5)
    for sig in (signal.SIGTERM, signal.SIGINT):
        before = w.snapshot()
        proc = w.start("new", "demo", "--stack", "generic", "--apply", env=env)
        deadline = time.time() + 30
        while time.time() < deadline and not os.path.exists(os.path.join(w.project("demo"), ".gitignore")):
            time.sleep(0.05)
        proc.send_signal(sig)
        out = proc.communicate(timeout=60)[0]
        time.sleep(2)  # an orphaned slow git must have finished before the tree is read
        if w.snapshot() != before:
            bad.append("left behind after %s: %s (exit %d)" % (sig.name, ", ".join(os.path.join(w.top, p) for p in left_behind(before, w.snapshot())[:5]), proc.returncode))
        if proc.returncode == 0 or "Traceback" in out:
            bad.append("%s: exit %d, want non-zero and no traceback: %s" % (sig.name, proc.returncode, tail(out, 3)))
    return bad


# ---------------------------------------------------------------- existing directory: as master

def registration_run(w):
    """The same sequence in a world; returns [(argv, exit code, masked output)] and the masked file manifest."""
    d = w.register_demo("regdemo")
    d2 = w.register_demo("second")
    runs = []
    for argv in (["new", d], ["new", d], ["new", d2, "--name", "other-name", "--writes-tracked-files"],
                 ["new", os.path.join(w.top, "projects", "nope")], ["new", w.home, "--name", "My_Project"],
                 ["new", d2, "--name", "@x"]):
        code, out = w.forge(*argv)
        runs.append((" ".join(argv).replace(w.top, "@W@"), code, out.replace(w.top, "@W@")))
    man = {k: v[:3] for k, v in sandbox.manifest(w.top, mask=True).items() if k != "log" and not k.startswith("log" + os.sep)}
    return runs, man


def a_registration_as_master(w, master_cli):
    mw = World("master", projects_dir=False)  # the base world: master's cli.py, and a forge.json with no projects_dir
    try:
        with open(os.path.join(mw.root, "forge", "cli.py"), "w", encoding="utf-8") as fh:
            fh.write(master_cli)
        runs_m, man_m = registration_run(mw)
        runs_w, man_w = registration_run(w)
        fm = read_json(mw.path("config", "forge.json"))
    finally:
        mw.close()
    bad = []
    for (argv, code_m, out_m), (_, code_w, out_w) in zip(runs_m, runs_w):
        if (code_m, out_m) != (code_w, out_w):
            bad.append("`forge %s` differs from master: exit %d vs %d, %s vs %s" % (argv, code_w, code_m, tail(out_w, 3), tail(out_m, 3)))
    # forge.json differs by design (projects_dir): compare every other file, and forge.json minus that key.
    for k in sorted(set(man_m) | set(man_w)):
        if k.startswith(os.path.join("forge", "forge") + os.sep) or k.startswith(os.path.join("forge", "tests") + os.sep):
            continue  # the engine copies: forge/cli.py is what differs between the two worlds
        if k == os.path.join("forge", "config", "forge.json") or k.startswith(os.path.join("home", ".local", "state", "forge")):
            continue  # forge.json differs by design (projects_dir); the journal and owned.json hold timestamps and each world's own paths
        if man_m.get(k) != man_w.get(k):
            bad.append("`forge new PATH` differs from master: file %s" % k)
    fw = read_json(w.path("config", "forge.json"))
    fw.pop("projects_dir", None)
    if fm != fw:
        bad.append("`forge new PATH` differs from master: config/forge.json")
    ok_runs = [code for _, code, _ in runs_w]
    if ok_runs[:3] != [0, 1, 0]:
        bad.append("registration exit codes %s, want 0, 1, 0 first (a registration, a duplicate, a renamed one)" % ok_runs)
    return bad


# ---------------------------------------------------------------- controls

NEW = os.path.join("forge", "new.py")
ASK = os.path.join("forge", "ask.py")
ACCOUNTS = os.path.join("forge", "accounts.py")
CLI = os.path.join("forge", "cli.py")
LIB = os.path.join("forge", "lib.py")
# lib.record raising when told `mkdir`: the fault the rollback order is shown against (the real one never raises on an OSError, but a
# signal handler's SystemExit lands in the same gap).
FAIL_RECORD = (LIB, '    log = os.environ.get("FORGE_WRITE_LOG")\n    if log:\n        try:\n            with open(log, "a"',
               '    if what == "mkdir":\n        raise RuntimeError("record failed (test fault)")\n'
               '    log = os.environ.get("FORGE_WRITE_LOG")\n    if log:\n        try:\n            with open(log, "a"')
# A step that fails after the registry and the project file are written: the forge.json write (what the account-server rollback is shown against).
FAIL_AFTER_REGISTRY = (NEW, '                    lib.write_text(lib.SETTINGS, lib.dumps(doc) + "\\n")  # atomic',
                       '                    raise OSError("injected after the registry")  # atomic')
# The rollback cannot write the registry back (a double fault): the recovery copy is then the only way back.
FAIL_RESTORE_REGISTRY = (NEW, "                try:\n                    lib.write_text(path, rest[0])\n",
                         "                try:\n                    if path.endswith('mcp-registry.json'):\n                        raise OSError('disk full')\n                    lib.write_text(path, rest[0])\n")
# A second memory failure on a fresh lite project, beside the empty store.
OTHER_MEMORY = (os.path.join("scripts", "sync", "memory_doctor.py"), '                db = os.path.join(want, "claude-mem-lite.db")\n',
                '                check(name, "memory-backend", False, "injected second backend")\n                db = os.path.join(want, "claude-mem-lite.db")\n')
# (label, assertion, mutations as (file, old text, new text), message the assertion must give)
REFRESH = 'project["plugins_keep"] = ask.with_memory_plugin(framework_plugins(stack["plugins"], doc), ans)\n'
# The user enables a plugin while the questions are asked: the first thing ask.gather does, in the world's copy of the engine.
LATE = (os.path.join("forge", "ask.py"), "    problems = []\n    if ctx.error:\n        return Answers(), [ctx.error]\n",
        "    import json as _j, os as _o\n    _p = _o.path.join(_o.environ['HOME'], '.claude', 'settings.json')\n"
        "    _d = _j.load(open(_p))\n    _d['enabledPlugins']['late@mk'] = True\n    _j.dump(_d, open(_p, 'w'))\n"
        "    problems = []\n    if ctx.error:\n        return Answers(), [ctx.error]\n")

# A doctor row that always FAILs, in `forge doctor NAME`'s list: what a real failure (project roots, generated...) looks like to forge new.
INJECT = (os.path.join("forge", "cli.py"), '        ("framework fields", lambda: framework_fields_row(name), fix["framework fields"]),\n',
          '        ("framework fields", lambda: framework_fields_row(name), fix["framework fields"]),\n'
          '        ("toy check", lambda: lib.Result("FAIL", "toy check", "injected failure"), ""),\n')

CONTROLS = [
    ("no check ahead of the first write, no cleanup", a_missing_stack,
     [(NEW, "if problems:", "if False:"), (NEW, "complete = rollback(undo)", "complete = True"),
      # the stack is read by the same check, so with it gone the plan has a stack to print and the write finds none after the mkdir
      (NEW, "stack = files = warnings = None", 'stack = {"description": "", "servers": [], "plugins": [], "checks": [], "skill_sets": []}\n    files, warnings = None, []')],
     "left a partial folder: "),
    ("a CLAUDE.md written", a_generic_created,
     [(NEW, 'write_file(undo, target, "README.md", text)', 'write_file(undo, target, "README.md", text); write_file(undo, target, "CLAUDE.md", text)')],
     "wrote outside the allowed list: "),
    ("a dry-run that goes on", a_dry_run, [(NEW, "if not a.apply:", "if False:")], "dry-run changed the tree"),
    ("a reserved list of verbs", a_list_created,
     [(NEW, "if not KEBAB.match(name):", 'if not KEBAB.match(name) or name in ("list", "new", "doctor"):')], "project named 'list' rejected"),
    ("no name check", a_bad_names, [(NEW, "if not KEBAB.match(name):", "if False:")], "project named '-x' created"),
    ("a path taken for a name", a_path_not_name, [(NEW, "if path_like(arg):", "if False:")], "'./nope' was not refused as a path"),
    ("a bare directory registered silently", a_name_or_path, [(NEW, 'print("forge new: ./%s exists here', '(lambda *x: None)("forge new: ./%s exists here')],
     "name taken for a path silently"),
    ("a bare directory with a creation flag not refused", a_name_or_path, [(NEW, "if creation_flags(a):\n        return refuse(2, \"./%s", "if False:\n        return refuse(2, \"./%s")],
     "want 2 and nothing written"),
    ("a registered project taken for a plain directory", a_rerun_in_projects, [(NEW, 'if prof.get("project_path") and', 'if False and')],
     "already exists and is registered"),
    ("no lock", a_lock, [(NEW, "with stopped_means_rollback(), creation_lock():", "with stopped_means_rollback():")],
     "wrote while another run held the lock"),
    ("no lock, no second check, two runs for one name", a_two_same_name,
     [(NEW, "with stopped_means_rollback(), creation_lock():", "with stopped_means_rollback():"),
      (NEW, "                if why:\n                    return refuse(2, \"another forge new", "                if False:\n                    return refuse(2, \"another forge new"),
      # the checks sit a second before the first write: both runs are past them when either writes (without it the late one is refused by chance)
      (NEW, "    ok, why = lib.may_write()", "    time.sleep(1)\n    ok, why = lib.may_write()")],
     "two runs for one name"),
    ("no lock and no re-read, two names", a_two_names, [(NEW, "with stopped_means_rollback(), creation_lock():", "with stopped_means_rollback():"),
                                                        (NEW, "doc, row = skills_doc(key)  # read again", "pass  # read again")],
     "lost a skill_keep.extras row"),
    ("no guard for a world", a_path_outside_world, [(NEW, "why = world_error(target)\n    if why:", "why = None\n    if why:")], "made outside the world"),
    ("a target inside the checkout", a_path_in_checkout, [(NEW, "if (target + os.sep).startswith(os.path.realpath(lib.ROOT) + os.sep):", "if False:")],
     "inside the checkout: exit"),
    ("an empty --path", a_path_in_checkout, [(NEW, "if not a.parent_dir.strip():", "if False:")], "an empty --path: exit"),
    ("--framework not checked", a_framework, [(NEW, "why = lib.project_error(project) or framework.plan(project, name).error", "why = None")],
     "--framework wrote a project that sync refuses"),
    ("a handover that never names checks_quick", a_framework_made, [(os.path.join("examples", "new-handoff.md"), "checks_quick", "the quick checks", True)],
     "handoff misses checks_quick"),
    ("no framework fields row", a_framework_made, [(CLI, '    ("framework fields", framework_fields_row, ""),\n', ""),
                                                   (CLI, '        ("framework fields", lambda: framework_fields_row(name), fix["framework fields"]),\n', "")],
     "want one `framework fields` row"),
    ("a framework project with the three unarmed fields written", a_framework_made, [(NEW, "factory=\"off\", checks=", "factory=\"off\", protected_paths=[\"**\"], checks=")],
     "protected_paths was written into the project file"),
    ("a handover written into the project", a_framework_made,
     [(NEW, '    print(handoff.rstrip("\\n"))\n', '    open(os.path.join(target, "HANDOFF.md"), "w").write(handoff)\n    print(handoff.rstrip("\\n"))\n')],
     "the project folder holds"),
    ("doctor's result swallowed", a_doctor_fail, [INJECT, (NEW, "    return 1 if other else 0", "    return 0")],
     "a FAIL row other than instruction files did not make forge new exit 1"),
    ("a handover from the stack's checks", a_framework_checks, [(NEW, "handoff = handoff_text(name, target, a.stack, project[\"checks\"])",
                                                                    "handoff = handoff_text(name, target, a.stack, stack[\"checks\"])")],
     "handover names a check the project file does not hold"),
    ("plugins_keep of the stack alone", a_framework_made, [(NEW, "plugins_keep=framework_plugins(stack[\"plugins\"], doc)", "plugins_keep=list(stack[\"plugins\"])"), (NEW, REFRESH, "pass\n")],
     "project file: plugins_keep is"),
    ("a doctor and closing line for every project", a_framework_made, [(NEW, "    if not a.framework:\n        return 0\n", "")],
     "without --framework: forge doctor's report or the closing line was printed"),
    ("app_run asked of a project without a screen", a_framework_fields, [(os.path.join("forge", "framework.py"), 'if prof.get("ui") is True', "if True")],
     "a project without a screen and two fields set: want PASS"),
    ("the plugin list read before the questions", a_late_plugin, [LATE, (NEW, REFRESH, "pass\n")],
     "a plugin enabled while the questions run is not in plugins_keep"),
    ("a relative projects_dir", a_bad_projects_dir, [(NEW, "not os.path.isabs(os.path.expanduser(configured))", "False")],
     "a relative projects_dir was used"),
    ("no handler for TERM", a_signals, [(NEW, "with stopped_means_rollback(), creation_lock():", "with creation_lock():")], "left behind after SIGTERM"),
    ("a stray file in HOME", a_generic_created, [(NEW, "git_init(target)\n", 'git_init(target)\n                open(os.path.join(lib.HOME, "stray"), "w").close()\n')],
     "wrote outside the allowed list"),
    ("a non-empty folder written into", a_target_exists, [(NEW, "if os.listdir(target):", "if False:")], "wrote into a non-empty folder"),
    ("a link followed", a_target_exists, [(NEW, "if os.path.islink(target):", "if False:"), (NEW, "if os.listdir(target):", "if False:")],
     "wrote through a link"),
    ("git init that follows GIT_DIR", a_git_env, [(NEW, ", env=lib.git_env())", ")")], "git init followed GIT_DIR"),
    ("a trailing newline in a name (creation)", a_bad_names, [(NEW, '(-[a-z0-9]+)*\\Z")', '(-[a-z0-9]+)*$")')],
     "project named 'demo\\n' created"),
    ("a trailing newline in a name (registration)", a_bad_registration_name, [(NEW, '(-[a-z0-9]+)*\\Z")', '(-[a-z0-9]+)*$")')],
     "registered under a name with a trailing newline"),
    ("mkdir recorded for rollback after record", a_record_fails_after_mkdir,
     [FAIL_RECORD, (NEW, '                    undo.append(("dir", target))  # before anything else that can fail or be interrupted\n                    lib.record("mkdir", target)\n',
                    '                    lib.record("mkdir", target)\n                    undo.append(("dir", target))\n')],
     "left behind: "),
    ("no cleanup after git fails", a_git_fails, [(NEW, "complete = rollback(undo)", "complete = True")], "left behind: "),
    ("no cleanup after forge.json fails", a_forge_json_fails, [(NEW, "complete = rollback(undo)", "complete = True")], "left behind: "),
    ("a substituter that lets {{X}} through", a_unresolved, UNRESOLVED + [(NEW, "if unresolved:", "if False:")], "placeholder left in .gitignore"),
    ("a stack whose .gitignore forgets .env", a_stacks_created, [(os.path.join("examples", "stacks", "rust", "gitignore"), ".env\n.env.*\n", "env-not-here\n")],
     ".gitignore of stack rust does not ignore .env"),
    ("a stack.json with a key missing", a_stack_files, [(os.path.join("examples", "stacks", "tauri", "stack.json"), '"skill_sets"', '"skill_set"')],
     "stack tauri: stack.json has the keys"),
    ("a stack.json not checked", a_bad_stack_json, BROKEN + [(NEW, "if missing:", "if False:")], "a stack.json without checks"),
    ("an unused argument not warned about", a_unused_argument, [(NEW, "if unused else []", "if False else []")], "an unused argument not warned about"),
    # 4.4 U9
    ("an existing extras row beside --no-baseline", a_no_baseline_existing_row, [(NEW, "    if a.no_baseline and not row:", "    if a.no_baseline and held:")],
     "--no-baseline with an existing empty extras row"),
    ("the recovery copy deleted before a failed restore", a_registry_copy_kept,
     [FAIL_AFTER_REGISTRY, FAIL_RESTORE_REGISTRY, (NEW, '            if kind == "restore":  # a file that existed: put back what it held\n',
                                                   '            if kind == "restore":  # a file that existed: put back what it held\n                forget(rest[1])\n')],
     "named by the hint is gone"),
    ("the creation flags allowed on a registered directory", a_parity_flags_by_mode,
     [(NEW, "or bool(a.account_server) or a.no_baseline\n            or a.no_git or answer_flags(a))", "or answer_flags(a))")], "want 2 saying the flag belongs to making"),
    ("--worktree-guard not an answer flag", a_parity_flags_by_mode, [(NEW, '"ui", "command_guard", "worktree_guard"))\n\n\ndef creation_flags', '"ui", "command_guard"))\n\n\ndef creation_flags')],
     "want 2 saying the flag belongs to making"),
    ("a profile allowed the flags of making", a_parity_flags_by_mode,
     [(NEW, ',\n                                      ("--account-server", a.account_server), ("--no-baseline", a.no_baseline), ("--no-git", a.no_git)) if given]', ") if given]")],
     "want 2 saying the flag belongs to making"),
    ("every memory failure tolerated", a_other_memory_fail, [OTHER_MEMORY, (NEW, "    return [l for l in r.stdout.splitlines() if l.startswith(\"FAIL\")] == [EXPECTED_MEMORY_FAIL % name]", "    return True")],
     "another memory failure was tolerated"),
    ("the registry not put back", a_account_server_rollback, [FAIL_AFTER_REGISTRY, (NEW, 'undo.append(("restore", REGISTRY, account.text, saved))', "pass")], "left behind: "),
    ("a registry entry with another URL replaced", a_account_server_existing, [(ACCOUNTS, 'if current is not None and current.get("url") != row["url"]:', "if False:")],
     "a registry entry with another url"),
    ("the account servers not listed", a_account_server,
     [(NEW, 'project["servers"] = list(project["servers"]) + [n for n in account.names if n not in project["servers"]]', "pass")], "the project's servers are"),
    ("--memory lite without the plugin", a_memory_lite, [(ASK, "    if ans.memory == LITE:\n        ctx.proj", "    if False:\n        ctx.proj")], "--memory lite: plugins_keep"),
    ("--memory lite refused beside common_plugins", a_memory_lite_common, [(ASK, "ans.memory and ans.memory != LITE and ", "ans.memory and ")],
     "--memory lite with the plugin in common_plugins"),
    ("--memory lite lost in a framework project", a_memory_lite_framework, [(NEW, 'ask.with_memory_plugin(framework_plugins(stack["plugins"], doc), ans)',
                                                                            'framework_plugins(stack["plugins"], doc)')], "--framework --memory lite"),
    ("--worktree-guard not written", a_worktree_guard, [(ASK, '    if st["worktree_guard"]:\n        ctx.proj["worktree_guard"] = True\n', "")], "--worktree-guard: exit"),
    ("--no-baseline still writes the row", a_no_baseline, [(NEW, '(not a.no_baseline and (row or extras)) or lifted', "row or extras or lifted"),
                                                         (NEW, 'del doc["skill_keep"]["extras"][key]', "pass")], "--no-baseline: exit 0, forge.json changed True"),
    ("--no-baseline beside skills", a_no_baseline, [(NEW, "if a.no_baseline and extras != held:", "if False and extras != held:")], "--no-baseline with --skills alpha"),
    ("--no-git still runs git init", a_no_git, [(NEW, "                if not a.no_git:\n", "                if True:\n")], "--no-git: exit 0, the folder holds"),
]


def main():
    master_cli = None
    r = subprocess.run(["git", "-C", sandbox.FORGE, "show", "%s:forge/cli.py" % BASE], capture_output=True, text=True)
    if r.returncode == 0:
        master_cli = r.stdout
    else:
        notrun.append("registration compared with master: revision %s is not in this clone (%s)" % (BASE, r.stderr.strip()[:80]))

    r = subprocess.run(["git", "-C", sandbox.FORGE, "show", "%s:forge/new.py" % HEAD_182], capture_output=True, text=True)
    if r.returncode == 0:
        w = World("g182")
        try:
            for why in a_generic_as_182(w, r.stdout):
                failures.append("generic as 182 -- %s" % why)
            n_checks[0] += 1
        finally:
            w.close()
        cw = World("g182c", mutate=[(os.path.join("examples", "stacks", "generic", "gitignore"), ".idea/\n", ".idea\n")])
        try:
            got = cw.anchors_missing or a_generic_as_182(cw, r.stdout)
            check("control: a changed generic .gitignore is caught", any("differs from 182's head" in g for g in got), "got %s" % got[:2])
            print("control %-45s -> %s" % ("generic .gitignore changed", (got[0] if got else "NOT SEEN FAILING")[:110]))
        finally:
            cw.close()
    else:
        notrun.append("generic compared with 182's head: revision %s is not in this clone (%s)" % (HEAD_182, r.stderr.strip()[:80]))

    plain = [("no --stack", a_missing_stack, {}), ("one error for every missing answer", a_one_error, {"projects_dir": False}),
             ("generic stack created", a_generic_created, {}), ("dry-run", a_dry_run, {}), ("a project named list", a_list_created, {}),
             ("bad names", a_bad_names, {}), ("a bad registration name", a_bad_registration_name, {}),
             ("record fails after mkdir", a_record_fails_after_mkdir, {"mutate": [FAIL_RECORD]}), ("path not name", a_path_not_name, {}), ("target exists", a_target_exists, {}),
             ("already registered", a_registered, {}), ("git fails", a_git_fails, {}), ("GIT_DIR in the environment", a_git_env, {}), ("forge.json fails", a_forge_json_fails, {}),
             ("sync fails", a_sync_fails, {}), ("--path", a_path_flag, {}), ("flags by mode", a_flags_by_mode, {}),
             ("--framework", a_framework, {}), ("help", a_help, {}), ("unknown stack", a_unknown_stack, {}), ("no forge.json", a_no_forge_json, {}),
             ("a name or a path", a_name_or_path, {}), ("again from projects_dir", a_rerun_in_projects, {}), ("the lock", a_lock, {}),
             ("two runs, one name", a_two_same_name, {}), ("two runs, two names", a_two_names, {}), ("--path outside the world", a_path_outside_world, {}),
             ("--path in the checkout", a_path_in_checkout, {}), ("bad projects_dir", a_bad_projects_dir, {}), ("signals", a_signals, {}),
             ("every stack creates a project", a_stacks_created, {}), ("the stack files", a_stack_files, {}),
             ("an unresolved placeholder", a_unresolved, {"mutate": UNRESOLVED}), ("a broken stack.json", a_bad_stack_json, {"mutate": BROKEN}),
             ("an unused argument", a_unused_argument, {}),
             ("--account-server", a_account_server, {}), ("--account-server, an entry that exists", a_account_server_existing, {}),
             ("--account-server rolled back", a_account_server_rollback, {"mutate": [FAIL_AFTER_REGISTRY]}),
             ("the registry's recovery copy kept", a_registry_copy_kept, {"mutate": [FAIL_AFTER_REGISTRY, FAIL_RESTORE_REGISTRY]}),
             ("--memory lite", a_memory_lite, {}), ("--memory lite, listed in common_plugins", a_memory_lite_common, {}),
             ("--worktree-guard", a_worktree_guard, {}), ("--no-baseline", a_no_baseline, {}), ("--no-baseline, a row exists", a_no_baseline_existing_row, {}), ("--no-git", a_no_git, {}),
             ("the flags of making", a_parity_flags_by_mode, {})]
    for label, fn, kw in plain:
        w = World("a", **kw)
        try:
            failures.extend("%s -- %s" % (label, why) for why in w.anchors_missing)  # a mutated world whose mutation did not apply tests nothing
            for why in fn(w):
                failures.append("%s -- %s" % (label, why))
            n_checks[0] += 1
        finally:
            w.close()
    for label, fn, kw in (("--framework made", a_framework_made, {}), ("handover checks", a_framework_checks, {}),
                          ("framework fields row", a_framework_fields, {}), ("doctor FAIL row", a_doctor_fail, {"mutate": [INJECT]}),
                          ("a plugin enabled while asking", a_late_plugin, {"mutate": [LATE]}),
                          ("--memory lite with --framework", a_memory_lite_framework, {}),
                          ("another memory failure", a_other_memory_fail, {"mutate": [OTHER_MEMORY]})):
        w = World("fw", framework=True, **kw)
        try:
            for why in fn(w):
                failures.append("%s -- %s" % (label, why))
            n_checks[0] += 1
        finally:
            w.close()
    if master_cli is not None:
        w = World("reg")
        for why in a_registration_as_master(w, master_cli):
            failures.append("registration as master -- %s" % why)
        n_checks[0] += 1
        w.close()
        # Control: one more key in the project file it writes.
        cw = World("regc", mutate=[(CLI, "project.update(project=name, project_path=path, writes_tracked_files=bool(a.writes_tracked_files))",
                                    "project.update(project=name, project_path=path, writes_tracked_files=bool(a.writes_tracked_files), x=1)")])
        got = cw.anchors_missing or a_registration_as_master(cw, master_cli)
        check("control: a changed registration is caught", any("differs from master" in g for g in got), "got %s" % got[:2])
        print("control %-45s -> %s" % ("one more key in the project file", (got[0] if got else "NOT SEEN FAILING")[:110]))
        cw.close()
    for label, fn, mutate, needle in CONTROLS:
        if fn is a_forge_json_fails and os.geteuid() == 0:
            notrun.append("control '%s': a read-only folder does not stop root" % label)
            continue
        cw = World("c", mutate=mutate, framework=fn in (a_framework_made, a_framework_checks, a_framework_fields, a_doctor_fail, a_late_plugin, a_memory_lite_framework, a_other_memory_fail))
        got = cw.anchors_missing or fn(cw)
        check("control '%s' produces %r" % (label, needle), any(needle in g for g in got), "got %s" % (got[:2] or "no failure (the assertion passed)"))
        shown = [g for g in got if needle in g] or got
        print("control %-45s -> %s" % (label, (shown[0] if shown else "NOT SEEN FAILING")[:110]))
        cw.close()
    sandbox.cleanup()
    if failures:
        for n in notrun:
            print("NOT RUN: %s" % n)
        print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
        for f in failures:
            print("FAIL %s" % f)
        sys.exit(1)
    print("%d check(s), 0 failures%s" % (n_checks[0], " (%d NOT RUN)" % len(notrun) if notrun else ""))
    if notrun:  # exit 77 and the last line the reason: `forge test` shows a yellow NOT RUN, NOT ARMED row, never a PASS
        for n in notrun[:-1]:
            print("NOT RUN: %s" % n)
        print("NOT RUN: %s" % notrun[-1])
        sys.exit(77)


if __name__ == "__main__":
    main()
