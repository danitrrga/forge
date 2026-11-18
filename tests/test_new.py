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
      control (no name check): `project named '@x' created`
  - an argument that looks like a path and does not exist is refused as a path (exit 1, "is not a directory", as
    before), never taken for a name.
      control (no path check): `'./nope' was not refused as a path`
  - a target folder that is not empty, or is a link, is refused and never written into.
      control (no check): `wrote into a non-empty folder`, `wrote through a link`
  - a failure halfway (a git that fails; a forge.json that cannot be written after the project file) leaves nothing this
    run made, and nothing else is touched.
      control (no cleanup): `left behind: <paths>`
  - an existing directory behaves as on master: output and files compared with the base revision's cli.py.
      control (one more key in the project file): `differs from master`
Also: the missing answers are named in ONE error (--stack and projects_dir together), --path puts the folder under it
and nowhere else, `forge new --help` lists every flag.

Seen failing first (this file, before forge/new.py existed): `forge new demo --stack generic --apply` died with
`forge new: ... is not a directory` exit 1 (the old command), every creation assertion failed, and every control
said `control anchor not found in forge/new.py`."""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

BASE = "2ffe5bf"  # master before this unit: the registration side is compared with its forge/cli.py
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


class World:
    def __init__(self, tag, mutate=(), projects_dir=True):
        self.top = sandbox.mkdtemp("new-%s-" % tag)
        self.root = os.path.join(self.top, "forge")
        self.home = os.path.join(self.top, "home")
        self.projects = os.path.join(self.top, "projects")
        self.cwd = os.path.join(self.top, "cwd")
        self.tmp = os.path.join(self.top, "tmp")
        self.logs = os.path.join(self.top, "log")
        for d in (self.home, self.projects, self.cwd, self.tmp, self.logs):
            os.makedirs(d)
        sandbox.copy_engine(self.root)
        sandbox.git(self.root, "init", "-q")
        sandbox.git(self.root, "add", "-A")
        sandbox.git(self.root, "commit", "-q", "-m", "engine")
        self.anchors_missing = []
        for rel, old, new in mutate:
            p = os.path.join(self.root, rel)
            text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
            if text.count(old) != 1:
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
        write_json(os.path.join(cfg, "forge.json"), doc)
        for name in ("mcp-registry.json", "gateway.json"):
            shutil.copy(os.path.join(self.root, "examples", name), os.path.join(cfg, name))
        os.makedirs(os.path.join(self.root, "credentials"), mode=0o700)
        with open(os.path.join(self.root, "credentials", "secrets.json"), "w") as fh:
            fh.write("{}\n")
        os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(cfg, "secrets.json"))
        os.makedirs(os.path.join(self.root, "docs"), exist_ok=True)
        shutil.copy(os.path.join(self.root, "examples", "AGENT-SYSTEM.md"), os.path.join(self.root, "docs", "AGENT-SYSTEM.md"))
        self.env = sandbox.bare_env(self.home, self.tmp, FORGE_WRITE_LOG=os.path.join(self.logs, "writes.log"),
                                    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

    def close(self):
        sandbox.rmtree(self.top)
        if self.top in sandbox._made:
            sandbox._made.remove(self.top)

    def forge(self, *args, env=None):
        """(exit code, stdout and stderr) of `bin/forge args`, run from W/cwd with no terminal."""
        r = subprocess.run([sys.executable, os.path.join(self.root, "bin", "forge")] + list(args), cwd=self.cwd,
                           env=env or self.env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def project(self, name):
        return os.path.join(self.projects, name)

    def snapshot(self):
        """Every file of the world by kind, mode and content (not mtime), the write log left out; .git directories
        are not walked by sandbox.manifest, so their paths are added."""
        snap = {k: v[:3] for k, v in sandbox.manifest(self.top).items() if k != "log" and not k.startswith("log" + os.sep)}
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
                      os.path.join("forge", "config", "forge.json")) or parts[0] == "home":
            continue
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
    for name in ("@x", "-x", "My_Project", "a--b", "x-"):
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


def a_path_not_name(w):
    bad = []
    for arg in ("./nope", "sub/nope", "~/nope", ".nope", "~nope"):
        before = w.snapshot()
        code, out = w.forge("new", arg, "--stack", "generic", "--apply")
        if code != 1 or "is not a directory" not in out:
            bad.append("%r was not refused as a path: exit %d: %s" % (arg, code, tail(out)))
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
    code, out = w.forge("new", "demo", "--stack", "generic", "--framework", "--apply")
    pf = read_json(w.path("config", "projects", "demo.claude.json")) or {}
    if code != 0 or pf.get("framework") is not True:
        return ["--framework: exit %d, framework=%r: %s" % (code, pf.get("framework"), tail(out, 10))]
    return []


def a_help(w):
    code, out = w.forge("new", "--help")
    flags = ("--path", "--stack", "--framework", "--yes", "--apply", "--name", "--writes-tracked-files")
    miss = [f for f in flags if f not in out]
    return ["`forge new --help` does not list %s" % ", ".join(miss)] if code != 0 or miss else []


def a_unknown_stack(w):
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "cobol", "--apply")
    if code != 2 or "generic" not in out or w.snapshot() != before:
        return ["an unknown stack: exit %d, want 2 naming generic and nothing written: %s" % (code, tail(out))]
    return []


def a_no_forge_json(w):
    os.unlink(w.path("config", "forge.json"))
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    if code != 1 or "config/forge.json missing" not in out:
        return ["no forge.json: exit %d, want 1 'config/forge.json missing': %s" % (code, tail(out))]
    return []


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
CLI = os.path.join("forge", "cli.py")
# (label, assertion, mutations as (file, old text, new text), message the assertion must give)
CONTROLS = [
    ("no check ahead of the first write, no cleanup", a_missing_stack,
     [(NEW, "if problems:", "if False:"), (NEW, "rollback(undo)", "pass")], "left a partial folder: "),
    ("a CLAUDE.md written", a_generic_created,
     [(NEW, 'write_file(undo, target, "README.md", text)', 'write_file(undo, target, "README.md", text); write_file(undo, target, "CLAUDE.md", text)')],
     "wrote outside the allowed list: "),
    ("a dry-run that goes on", a_dry_run, [(NEW, "if not a.apply:", "if False:")], "dry-run changed the tree"),
    ("a reserved list of verbs", a_list_created,
     [(NEW, "if not KEBAB.match(name):", 'if not KEBAB.match(name) or name in ("list", "new", "doctor"):')], "project named 'list' rejected"),
    ("no name check", a_bad_names, [(NEW, "if not KEBAB.match(name):", "if False:")], "project named '@x' created"),
    ("a path taken for a name", a_path_not_name, [(CLI, "if not os.path.isdir(os.path.expanduser(a.path)) and not path_like(a.path):",
                                                    "if not os.path.isdir(os.path.expanduser(a.path)):")], "'./nope' was not refused as a path"),
    ("a non-empty folder written into", a_target_exists, [(NEW, "if os.listdir(target):", "if False:")], "wrote into a non-empty folder"),
    ("a link followed", a_target_exists, [(NEW, "if os.path.islink(target):", "if False:"), (NEW, "if os.listdir(target):", "if False:")],
     "wrote through a link"),
    ("no cleanup after git fails", a_git_fails, [(NEW, "rollback(undo)", "pass")], "left behind: "),
    ("no cleanup after forge.json fails", a_forge_json_fails, [(NEW, "rollback(undo)", "pass")], "left behind: "),
]


def main():
    master_cli = None
    r = subprocess.run(["git", "-C", sandbox.FORGE, "show", "%s:forge/cli.py" % BASE], capture_output=True, text=True)
    if r.returncode == 0:
        master_cli = r.stdout
    else:
        notrun.append("registration compared with master: revision %s is not in this clone (%s)" % (BASE, r.stderr.strip()[:80]))

    plain = [("no --stack", a_missing_stack, {}), ("one error for every missing answer", a_one_error, {"projects_dir": False}),
             ("generic stack created", a_generic_created, {}), ("dry-run", a_dry_run, {}), ("a project named list", a_list_created, {}),
             ("bad names", a_bad_names, {}), ("path not name", a_path_not_name, {}), ("target exists", a_target_exists, {}),
             ("already registered", a_registered, {}), ("git fails", a_git_fails, {}), ("forge.json fails", a_forge_json_fails, {}),
             ("sync fails", a_sync_fails, {}), ("--path", a_path_flag, {}), ("flags by mode", a_flags_by_mode, {}),
             ("--framework", a_framework, {}), ("help", a_help, {}), ("unknown stack", a_unknown_stack, {}), ("no forge.json", a_no_forge_json, {})]
    for label, fn, kw in plain:
        w = World("a", **kw)
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
        cw = World("c", mutate=mutate)
        got = cw.anchors_missing or fn(cw)
        check("control '%s' produces %r" % (label, needle), any(needle in g for g in got), "got %s" % (got[:2] or "no failure (the assertion passed)"))
        print("control %-45s -> %s" % (label, (got[0] if got else "NOT SEEN FAILING")[:110]))
        cw.close()
    sandbox.cleanup()
    for n in notrun:
        print("NOT RUN: %s" % n)
    if failures:
        print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
        for f in failures:
            print("FAIL %s" % f)
        sys.exit(1)
    print("%d check(s), 0 failures%s" % (n_checks[0], " (%d NOT RUN)" % len(notrun) if notrun else ""))


if __name__ == "__main__":
    main()
