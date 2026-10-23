#!/usr/bin/env python3
"""T9 of docs/portable-design.md (sections 6 and 10, point 3): what a stranger gets from `forge init` and
`forge add`, run in a world the way a stranger has it.

The world is W/forge (an engine-only copy: sandbox.copy_engine, `git init`, one commit), W/home (the HOME
of every command) and W/projects/demo (a repository with one commit), side by side, which is the shape
lib.may_write allows a toy HOME to write. npm, pnpm, codex and systemctl are logging stubs first on PATH, so a
run that reaches for any of them leaves a line in W/log. Nothing is read from or written to the real
HOME or this checkout's data: the copy has no config/forge.json, no profile and no credentials. There is
no `unshare`: with every integration off nothing connects, and runners that restrict user namespaces
could not run it.

Run: `init --yes --without codex,gsd`, then `add demo`. Assertions (each prints what it counted, and fails
at a count of 0):
  init exits 0 and no stub was called; every path forge logged (FORGE_WRITE_LOG) lies under W; every hook
  command in the world's ~/.claude/settings.json names a script that exists; zero skills are linked and the
  relink step says SKIP; no file init changed or created holds the real HOME; `forge doctor` exits 0 with
  no FAIL or WARN line, and the rows a stranger has nothing to run for say NOT RUN, NOT ARMED; a second
  `forge sync --all` dry-run has no pending write; `forge add` leaves the project's tracked files alone
  and its untracked files are exactly the set pinned below; init twice, and add of a missing directory, a
  registered name and a name that is not kebab-case are each refused and write nothing.
Controls, run every time in the same world and put back afterwards:
  (a) integrations.hindsight true and the demo profile granted hindsight-coding-agents: the hook-path assertion,
      over ~/.claude/settings.json and demo's settings.local.json (where those rows are written per project),
      fails and names the world's ~/.hindsight/coding-agents/dist/claude-hook.js, then passes again once both
      are put back (the put-back sync takes the rows out of demo's file);
  (b) the real HOME in a profile env: the no-real-HOME assertion fails and names the file, then passes again;
  (c) on a machine that has the private data (config/profiles/ beside publish/engine.gitignore or
      config/publish-deny.txt): a world built with sandbox.copy_checkout(untracked=True), which carries every
      profile, fails the `only the forge and demo profiles` assertion; elsewhere NOT RUN;
  (d) a user_hooks row that names no script: the integrations row is a FAIL (something is configured and
      nothing could be checked), where the same world without the row is a SKIP.
Also: the choice logic (--yes, --with, --without, the two questions) as a pure function; `--track` in a
second world; and the doctor rows that FAIL on a legitimate zero (no profile asks for the worktree guard, no
config/toolchain.json while GSD is off) as SKIP, with the zero where something is configured still a FAIL.

Seen failing before `init` existed (this file as it is): the first command died with
`forge: error: argument cmd: invalid choice: 'init' (choose from 'sync', 'doctor', 'metrics', 'test',
'toolchain', 'session-start', 'check-public', 'commit')`, exit 2. The red messages of each later change are
in the commit that made it. Not here: the byte-identity of the real dry-runs (scripts/dev/gate.py)."""
import json
import os
import pwd
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

sys.path.insert(0, sandbox.FORGE)
from forge import cli, lib, toolchain  # noqa: E402  (pure functions and two path constants only: nothing here writes through them)

failures, notrun, n_checks = [], [], [0]
GIT_ENV = dict(os.environ, **sandbox.GIT_ENV)
HINDSIGHT_HOOK = os.path.join(".hindsight", "coding-agents", "dist", "claude-hook.js")
INTEGRATIONS = ("codex", "gsd", "hindsight")
# What `forge add` leaves untracked in a project whose own files it must not touch: nothing. An untrimmed
# profile with no servers needs no .claude/settings.local.json, there is no pointer in CLAUDE.md, no ignore
# line and no .codex/ with Codex off, and sync_system_doc.py writes the copy of AGENT-SYSTEM.md into a
# repo-owned project only where the repo's own ignore rules already cover it (it prints SKIP-doc, and that is
# not a pending write). The one thing add does for such a project is its key in ~/.claude.json.
DEMO_UNTRACKED = set()
REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir
ASK_CODEX = "Codex found: manage its config too? [Y/n]"
ASK_GSD = "pnpm found: install GSD (planning skills, unpatched from its package with pnpm dlx @opengsd/gsd-core)? [Y/n]"
# What init runs for GSD: GSD's own installer, through pnpm, for Claude Code, global.
GSD_DLX = "dlx @opengsd/gsd-core@latest --claude --global"


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))


def want(label, got, expected):
    check(label, got == expected, "%r, want %r" % (got, expected))


def tail(text, n=6):
    return " | ".join(text.strip().splitlines()[-n:])


# ---------------------------------------------------------------- the world

def stub(bin_dir, log_dir, name, extra=""):
    """An executable `name` that appends its argv to log_dir/name.log, then runs `extra` (shell)."""
    os.makedirs(bin_dir, exist_ok=True)
    p = os.path.join(bin_dir, name)
    with open(p, "w") as fh:
        fh.write('#!/bin/sh\necho "$@" >> %s\n%s\n' % (os.path.join(log_dir, name + ".log"), extra))
    os.chmod(p, 0o755)


class World:
    def __init__(self, tag):
        self.top = sandbox.mkdtemp("fresh-install-%s-" % tag)
        self.root = os.path.join(self.top, "forge")
        self.home = os.path.join(self.top, "home")
        self.demo = os.path.join(self.top, "projects", "demo")
        self.logs = os.path.join(self.top, "log")
        self.tmp = os.path.join(self.top, "tmp")
        for d in (self.home, self.logs, self.tmp, self.demo):
            os.makedirs(d)
        sandbox.copy_engine(self.root)
        allow = os.path.join(sandbox.FORGE, "publish", "engine.gitignore")
        if os.path.exists(allow):
            # Before the split this checkout's own ignore file is not the engine's: the allowlist becomes it then, and
            # a stranger's checkout has it from the start (it decides which history forge commit routes a path to).
            shutil.copy(allow, os.path.join(self.root, "." + "gitignore"))
        sandbox.git(self.root, "init", "-q")
        sandbox.git(self.root, "add", "-A")
        sandbox.git(self.root, "commit", "-q", "-m", "engine")
        with open(os.path.join(self.demo, "README.md"), "w") as fh:
            fh.write("demo\n")
        sandbox.git(self.demo, "init", "-q")
        sandbox.git(self.demo, "add", "-A")
        sandbox.git(self.demo, "commit", "-q", "-m", "demo")
        bin_dir = os.path.join(self.top, "stubs")
        npm_root = os.path.join(self.top, "npm-root")
        os.makedirs(npm_root)
        for name in ("npm", "pnpm", "codex", "systemctl"):
            # `npm root -g` names an empty directory: nothing is installed, and an install does nothing.
            stub(bin_dir, self.logs, name, 'test "$1 $2" = "root -g" && echo %s' % npm_root if name == "npm" else "")
        self.env = sandbox.bare_env(self.home, self.tmp, bin_dir=bin_dir,
                                    FORGE_WRITE_LOG=os.path.join(self.logs, "writes.log"),
                                    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

    def forge(self, *args):
        """(exit code, stdout and stderr) of `bin/forge args` from the checkout."""
        r = subprocess.run([sys.executable, os.path.join(self.root, "bin", "forge")] + list(args), cwd=self.root,
                           env=self.env, capture_output=True, text=True, timeout=600)
        return r.returncode, r.stdout + r.stderr

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def stub_calls(self):
        out = {}
        for name in ("npm", "pnpm", "codex", "systemctl"):
            p = os.path.join(self.logs, name + ".log")
            out[name] = open(p).read().splitlines() if os.path.exists(p) else []
        return out

    def snapshot(self):
        """The world's files as sandbox.manifest sees them (.git directories left out), less the
        stubs' logs and the write log."""
        return {k: v for k, v in sandbox.manifest(self.top).items() if k != "log" and not k.startswith("log" + os.sep)}

    def written(self):
        p = os.path.join(self.logs, "writes.log")
        return [l.split(" ", 1)[1] for l in open(p).read().splitlines() if " " in l] if os.path.exists(p) else []


def changed_since(before, after):
    """The paths added or changed between two snapshots, by kind, mode and content (not mtime)."""
    return sorted(k for k, v in after.items() if k not in before or before[k][:3] != v[:3])


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)


def git_out(*argv):
    return subprocess.run(["git"] + list(argv), capture_output=True, text=True, env=GIT_ENV).stdout


# ---------------------------------------------------------------- the assertions

def hook_commands(home, also=()):
    """Every hook command in home/.claude/settings.json, then in each settings file of `also` (a project's
    .claude/settings.local.json, where the hooks written per project land)."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("command"), str):
                out.append(x["command"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for f in (os.path.join(home, ".claude", "settings.json"),) + tuple(also):
        walk((read_json(f) or {}).get("hooks"))
    return out


def hook_check(home, also=()):
    """(how many hook commands name a path, [(command, path)] for each path that does not exist) over
    every hook command in home/.claude/settings.json and the settings files of `also`. A `~/` in a
    command is the world's HOME."""
    checked, missing = 0, []
    for command in hook_commands(home, also):
        try:
            words = shlex.split(command)
        except ValueError:
            words = command.split()
        paths = [os.path.join(home, w[2:]) if w.startswith("~/") else w for w in words[1:] if w.startswith(("/", "~/"))]
        checked += bool(paths)
        missing += [(command, p) for p in paths if not os.path.exists(p)]
    return checked, missing


def real_home_in(world, files):
    """The files of `files` (paths relative to the world) whose text holds the real HOME."""
    needle, out = REAL_HOME.encode(), []
    for rel in files:
        p = os.path.join(world.top, rel)
        if os.path.isfile(p) and not os.path.islink(p):
            with open(p, "rb") as fh:
                if needle in fh.read():
                    out.append(rel)
    return out


def only_forge_and_demo(profiles_dir):
    """(whether the profiles are exactly forge and demo, the names found)."""
    names = sorted(n[:-len(".claude.json")] for n in os.listdir(profiles_dir) if n.endswith(".claude.json")) if os.path.isdir(profiles_dir) else []
    return names == ["demo", "forge"], names


def untracked_files(project):
    """({untracked paths}, [every other status line]) of a project, listing each untracked file."""
    lines = git_out("-C", project, "status", "--porcelain", "--untracked-files=all").splitlines()
    return {l[3:] for l in lines if l.startswith("??")}, [l for l in lines if not l.startswith("??")]


# ---------------------------------------------------------------- the choice logic, as a pure function

def choice_cases():
    asked = []

    def run(yes, with_names, without_names, have, answer=True):
        del asked[:]

        def ask(question):
            asked.append(question)
            return answer
        got, why = cli.init_choices(yes, with_names, without_names, have, ask)
        return got, why, list(asked)

    both, neither = {"codex": True, "pnpm": True}, {"codex": False, "pnpm": False}
    off = {k: False for k in INTEGRATIONS}
    want("init_choices --yes takes what it found, and asks nothing", run(True, [], [], both), (dict(off, codex=True, gsd=True), None, []))
    want("init_choices --yes with nothing found: everything off", run(True, [], [], neither), (off, None, []))
    want("init_choices --without codex,gsd", run(True, [], ["codex", "gsd"], both), (off, None, []))
    got, why, q = run(False, [], [], both, answer=False)
    want("init_choices asks the two questions, and takes `no`", (got, q), (off, [ASK_CODEX, ASK_GSD]))
    got, why, q = run(False, [], ["codex"], both)
    want("init_choices asks only about what --without left open", (got, q), (dict(off, gsd=True), [ASK_GSD]))
    got, why, q = run(False, [], [], {"codex": False, "pnpm": True})
    want("init_choices asks only about the tools it found", (got, q), (dict(off, gsd=True), [ASK_GSD]))
    want("init_choices --with switches on what is not detected", run(True, ["hindsight"], [], neither),
         (dict(off, hindsight=True), None, []))
    for label, with_names, have, names, in (("--with codex without codex on PATH", ["codex"], neither, "codex"),
                                           ("--with gsd without pnpm on PATH", ["gsd"], neither, "pnpm"),
                                           ("--with an unknown name", ["nope"], both, "nope")):
        got, why, q = run(True, with_names, [], have)
        check("init_choices %s is refused, naming %s" % (label, names), got is None and names in (why or ""), "got %r, %r" % (got, why))
    # caveman was an integration until it was removed: it is an unknown name now, in either list, and the
    # generic refusal names it and the names that remain.
    for flag, with_names, without_names in (("--with", ["caveman"], []), ("--without", [], ["caveman"])):
        got, why, q = run(True, with_names, without_names, both)
        want("init_choices %s caveman is refused as an unknown integration" % flag, (got, why),
             (None, "unknown integration 'caveman' (one of codex, gsd, hindsight)"))
    got, why, q = run(True, ["hindsight"], ["hindsight"], both)
    check("init_choices a name in both lists is refused", got is None and "hindsight" in (why or ""), "got %r, %r" % (got, why))


# ---------------------------------------------------------------- the rows that FAIL on a legitimate zero

def level_of(result):
    return result[0].level if isinstance(result, list) else result.level


def doctor_row_cases():
    """The rows M1 recorded as FAIL on a fresh world, as results, each next to the zero that stays a
    FAIL because something is configured. In process, against a toy config/profiles and a toy
    config/forge.json (lib.PROFILES and lib.SETTINGS, put back afterwards)."""
    top = sandbox.mkdtemp("fresh-install-rows-")
    real = (lib.PROFILES, lib.SETTINGS, toolchain.MANIFEST)
    try:
        lib.PROFILES = os.path.join(top, "profiles")
        os.makedirs(lib.PROFILES)

        def profile(name, **extra):
            write_json(os.path.join(lib.PROFILES, name + ".claude.json"), dict({"project": name, "project_path": os.path.join(top, name)}, **extra))
        profile("plain")
        res = cli.worktree_guard_smoke()
        want("worktree guard: no profile asks for it is a SKIP, saying NOT RUN, NOT ARMED",
             (level_of(res), res.detail.startswith(cli.NOT_ARMED) if not isinstance(res, list) else None), ("SKIP", True))
        profile("off", worktree_guard={"on": False, "worktree_dirs": []})
        want("worktree guard: a profile that declares it off is still a SKIP", level_of(cli.worktree_guard_smoke()), "SKIP")
        profile("frozen", worktree_guard=True, frozen=True)
        res = cli.worktree_guard_smoke()
        want("worktree guard: a frozen profile that asks for it stays a FAIL, saying checked 0 and frozen",
             (level_of(res), "checked 0" in res.detail and "frozen" in res.detail), ("FAIL", True))

        lib.SETTINGS = os.path.join(top, "forge.json")
        for gsd in (False, True):
            write_json(lib.SETTINGS, {"integrations": {"gsd": gsd}, "gsd_patches": True})
            lib.settings.cache_clear()
            toolchain.MANIFEST = os.path.join(top, "no-such-toolchain.json")
            results, todo, where = toolchain.check()
            if gsd:
                want("toolchain: no file with gsd on stays a FAIL", [r.level for r in results], ["FAIL"])
            else:
                want("toolchain: no file with gsd off is a SKIP, saying NOT RUN, NOT ARMED, with nothing to install",
                     ([r.level for r in results], results[0].detail.startswith(cli.NOT_ARMED), any(todo.values())), (["SKIP"], True, False))
            want("toolchain row, no file, gsd %s" % ("on" if gsd else "off"), toolchain.row().level, "FAIL" if gsd else "SKIP")
            toolchain.MANIFEST = os.path.join(top, "empty-toolchain.json")
            write_json(toolchain.MANIFEST, {"tools": [], "pip": []})
            want("toolchain: a file that lists nothing is a FAIL, gsd %s" % ("on" if gsd else "off"), toolchain.row().level, "FAIL")
        # GSD on but unpatched (a stranger's): no package is pinned, because GSD comes from pnpm dlx. Red before:
        # "toolchain: gsd on, gsd_patches false, no file is a SKIP = (['FAIL'], []), want (['SKIP'], [])".
        for label, doc in (("gsd_patches false", {"integrations": {"gsd": True}, "gsd_patches": False}),
                           ("gsd_patches absent", {"integrations": {"gsd": True}})):
            write_json(lib.SETTINGS, doc)
            lib.settings.cache_clear()
            toolchain.MANIFEST = os.path.join(top, "no-such-toolchain.json")
            results, todo, where = toolchain.check()
            want("toolchain: gsd on, %s, no file is a SKIP" % label, ([r.level for r in results], any(todo.values())), (["SKIP"], False))
        lib.SETTINGS = os.path.join(top, "no-such-forge.json")
        lib.settings.cache_clear()
        toolchain.MANIFEST = os.path.join(top, "no-such-toolchain.json")
        want("toolchain: no config/forge.json is a SKIP, not an exit", toolchain.row().level, "SKIP")
    finally:
        lib.PROFILES, lib.SETTINGS, toolchain.MANIFEST = real
        lib.settings.cache_clear()


# ---------------------------------------------------------------- the main world

def main_world():
    w = World("main")
    want("the world has no config/profiles yet", os.path.exists(w.path("config", "profiles")), False)
    before = w.snapshot()
    # caveman was an integration until its removal: init refuses it as it refuses any unknown name, and writes
    # nothing. Red with "caveman" put back in lib.INTEGRATIONS: "init --with caveman is refused as an unknown integration, exit 1, nothing written -- exit 1: ! forge init: failed -- doctor (exit 1) | ..." (init ran and wrote config/forge.json).
    code, out = w.forge("init", "--yes", "--with", "caveman")
    check("init --with caveman is refused as an unknown integration, exit 1, nothing written",
          code == 1 and "! forge init: unknown integration 'caveman' (one of codex, gsd, hindsight)" in out
          and not os.path.exists(w.path("config", "forge.json")), "exit %d: %s" % (code, tail(out, 3)))
    code, out = w.forge("init", "--yes", "--without", "codex,gsd")
    check("init --yes --without codex,gsd exits 0", code == 0, "exit %d: %s" % (code, tail(out)))
    # Control of the init exit rules below: every step passed or was not run (the SKIP and NOT RUN rows
    # of this world), and nothing says it failed.
    check("init with nothing broken prints no '! forge init' line and has NOT RUN rows",
          "! forge init" not in out and "NOT RUN, NOT ARMED" in out, tail(out, 12))
    want("no stub was called (npm, pnpm, codex, systemctl)", w.stub_calls(), {"npm": [], "pnpm": [], "codex": [], "systemctl": []})
    after = w.snapshot()
    changed = changed_since(before, after)
    check("init changed the world (%d path(s))" % len(changed), len(changed) > 0, "no path changed")
    logged = w.written()
    outside = [p for p in logged if not os.path.realpath(p).startswith(w.top + os.sep)]
    check("every path forge logged lies under the world (%d logged)" % len(logged), len(logged) > 0 and not outside,
          "logged %d, outside: %s" % (len(logged), outside[:3]))
    named = ("config/forge.json", "config/profiles/forge.claude.json", "config/mcp-registry.json", "credentials/secrets.json", "docs/AGENT-SYSTEM.md")
    check("the init output names what it wrote", all(s in out for s in named), "missing %s in: %s" % ([s for s in named if s not in out], tail(out, 30)))

    fj = read_json(w.path("config", "forge.json")) or {}
    want("forge.json: every integration off", fj.get("integrations"), {k: False for k in INTEGRATIONS})
    prof = read_json(w.path("config", "profiles", "forge.claude.json")) or {}
    want("the checkout's own profile", {k: prof.get(k) for k in ("project", "project_path", "servers", "writes_tracked_files")},
         {"project": "forge", "project_path": w.root, "servers": [], "writes_tracked_files": False})
    want("the registry is empty", (read_json(w.path("config", "mcp-registry.json")) or {}).get("servers"), {})
    sec = w.path("credentials", "secrets.json")
    want("credentials/secrets.json is `{}`, mode 600", (read_json(sec), oct(os.stat(sec).st_mode & 0o777) if os.path.exists(sec) else None), ({}, "0o600"))
    link = w.path("config", "secrets.json")
    want("config/secrets.json links to ../credentials/secrets.json", os.readlink(link) if os.path.islink(link) else None, "../credentials/secrets.json")
    doc = w.path("docs", "AGENT-SYSTEM.md")
    check("docs/AGENT-SYSTEM.md is the example", os.path.exists(doc) and open(doc).read() == open(w.path("examples", "AGENT-SYSTEM.md")).read())
    want("no config/toolchain.json while gsd is off", os.path.exists(w.path("config", "toolchain.json")), False)
    want("an empty skills/ exists", os.listdir(w.path("skills")) if os.path.isdir(w.path("skills")) else None, [])
    want("git config core.hooksPath", git_out("-C", w.root, "config", "core.hooksPath").strip(), "githooks")

    checked, missing = hook_check(w.home)
    print("%d hook command(s) checked" % checked)
    check("every hook command names a script that exists (%d checked)" % checked, checked > 0 and not missing,
          "%d checked, missing: %s" % (checked, missing[:3]))
    session = "%s/bin/forge session-start" % w.root
    check("~/.claude/settings.json has the SessionStart row that runs this checkout", any(session in c for c in hook_commands(w.home)),
          "no command holds %s" % session)
    skills_dir = os.path.join(w.home, ".claude", "skills")
    want("zero skills are linked", os.listdir(skills_dir) if os.path.isdir(skills_dir) else [], [])
    if w.top.startswith(REAL_HOME + os.sep):
        notrun.append("no file holds the real HOME: the world lies under it, so the assertion cannot be shown")
    else:
        leaks = real_home_in(w, changed)
        check("no file init changed or created holds the real HOME (%d scanned)" % len(changed), len(changed) > 0 and not leaks, "leaks: %s" % leaks)

    code, out = w.forge("doctor")
    lines = out.splitlines()
    bad = [l for l in lines if l.startswith(("FAIL", "WARN"))]
    check("forge doctor exits 0 with no FAIL or WARN line", code == 0 and not bad, "exit %d: %s" % (code, " | ".join(bad) or tail(out)))
    for name in INTEGRATIONS:
        check("doctor: %s reads NOT RUN, NOT ARMED" % name,
              any(l.startswith("SKIP") and "NOT RUN, NOT ARMED: %s is off" % name in l for l in lines), tail(out, 20))
    for row in ("worktree guard", "toolchain", "integrations"):
        # A SKIP row that says NOT RUN, NOT ARMED and nothing after it, no `-- fix` suffix of a row that did run.
        mine = [l for l in lines if l.startswith("SKIP") and row in l and "NOT RUN, NOT ARMED" in l and " -- " not in l.split("NOT RUN, NOT ARMED", 1)[1]]
        check("doctor: the %s row is a SKIP that says NOT RUN, NOT ARMED, with no fix suffix" % row, mine, tail(out, 20))

    code, out = w.forge("sync", "--all")
    pending = cli.pending_writes(out.splitlines())
    check("a second `forge sync --all` dry-run exits 0 with no pending write", code == 0 and pending == 0,
          "exit %d, %d pending: %s" % (code, pending, tail(out, 12)))
    # The two user-scope steps left forge sync for forge skills (docs/toolchain-design.md section 5).
    check("forge sync --all runs neither of them", "skill links" not in out and "gsd runtime" not in out, tail(out, 12))
    code, out = w.forge("skills")
    check("forge skills exits 0", code == 0, "exit %d: %s" % (code, tail(out, 12)))
    # docs/portable-design.md section 10 says the relink line reads NOT RUN, NOT ARMED; the code (T5) prints a SKIP line.
    check("the relink step says SKIP, with nothing to link", "relink_skills: SKIP -- skills/ holds no skill, so there is nothing to link" in out, tail(out, 12))
    check("the gsd step says NOT RUN, NOT ARMED", "== forge: gsd runtime == NOT RUN, NOT ARMED (gsd off)" in out, tail(out, 12))

    code, out = w.forge("add", w.demo)
    check("forge add exits 0", code == 0, "exit %d: %s" % (code, tail(out)))
    ok, names = only_forge_and_demo(w.path("config", "profiles"))
    check("only the forge and demo profiles", ok, "found %s" % names)
    dp = read_json(w.path("config", "profiles", "demo.claude.json")) or {}
    want("the demo profile", {k: dp.get(k) for k in ("project", "project_path", "writes_tracked_files")},
         {"project": "demo", "project_path": w.demo, "writes_tracked_files": False})
    want("the demo profile is untrimmed (no skills_keep, no plugins_keep)", [k for k in ("skills_keep", "plugins_keep") if k in dp], [])
    fresh, others = untracked_files(w.demo)
    want("forge add leaves the project's tracked files alone (git status)", others, [])
    want("the project's untracked files are the pinned set (%d)" % len(DEMO_UNTRACKED), fresh, DEMO_UNTRACKED)
    keys = (read_json(os.path.join(w.home, ".claude.json")) or {}).get("projects", {})
    check("forge add put the project's key in the world's ~/.claude.json", w.demo in keys, "keys: %s" % sorted(keys))
    check("the add output names the profile it wrote", "config/profiles/demo.claude.json" in out, tail(out))

    refusals = (("a second init", ["init", "--yes", "--without", "codex,gsd"], "already initialised -- run forge doctor"),
                ("add of a directory that is not there", ["add", os.path.join(w.top, "projects", "nope")], "is not a directory"),
                ("add of a registered project", ["add", w.demo], "already registered"),
                ("add under a name that is not kebab-case", ["add", w.home, "--name", "My_Project"], "kebab-case"))
    for label, argv, needle in refusals:
        snap = w.snapshot()
        code, out = w.forge(*argv)
        check("%s is refused with exit 1, saying why, and writes nothing" % label,
              code == 1 and needle in out and changed_since(snap, w.snapshot()) == [], "exit %d: %s" % (code, tail(out)))

    controls(w, before)


def controls(w, before):
    """Each control makes the world wrong in one way, shows the assertion going red with its message, puts
    the world back, and shows the assertion green again."""
    fj_path = w.path("config", "forge.json")
    good_fj = open(fj_path).read()

    # (a) hindsight on and demo using it: its hook rows, written into demo's settings.local.json (a profile
    # uses Hindsight when its servers list hindsight-coding-agents), name files under the world's HOME that
    # do not exist. The world's registry lacks the server: sync says so and still writes the file.
    fj = json.loads(good_fj)
    fj["integrations"]["hindsight"] = True
    write_json(fj_path, fj)
    dp_path = w.path("config", "profiles", "demo.claude.json")
    good_dp = open(dp_path).read()
    dp = json.loads(good_dp)
    dp["servers"] = dp.get("servers", []) + ["hindsight-coding-agents"]
    write_json(dp_path, dp)
    demo_sl = (os.path.join(w.demo, ".claude", "settings.local.json"),)
    code, out = w.forge("sync", "--apply", "--all")
    checked, missing = hook_check(w.home, demo_sl)
    target = os.path.join(w.home, HINDSIGHT_HOOK)
    print("control (a), hindsight on: %d hook command(s) checked, missing %s" % (checked, sorted({p for _, p in missing})))
    check("control (a): with hindsight on the hook-path assertion fails and names %s" % target, any(p == target for _, p in missing),
          "sync exit %d; %d checked; missing %s; %s" % (code, checked, sorted({p for _, p in missing}), tail(out)))
    with open(fj_path, "w") as fh:
        fh.write(good_fj)
    with open(dp_path, "w") as fh:
        fh.write(good_dp)
    code, out = w.forge("sync", "--apply", "--all")
    checked, missing = hook_check(w.home, demo_sl)
    check("control (a) put back: the hook-path assertion passes again (%d checked)" % checked, checked > 0 and not missing,
          "sync exit %d, missing %s" % (code, missing[:2]))

    # (b) the real HOME in a profile's env: the no-real-HOME assertion must see it.
    if w.top.startswith(REAL_HOME + os.sep):
        notrun.append("control (b): the world lies under the real HOME, so the assertion cannot be shown")
    else:
        pp = w.path("config", "profiles", "forge.claude.json")
        good, pre_b = open(pp).read(), w.snapshot()
        prof = json.loads(good)
        prof["env"] = {"FORGE_TEST_HOME": REAL_HOME}
        write_json(pp, prof)
        code, out = w.forge("sync", "--apply", "--project", "forge")
        leaks = real_home_in(w, changed_since(before, w.snapshot()))
        print("control (b), the real HOME in a profile env: files holding it: %s" % leaks)
        check("control (b): with the real HOME in a profile env the no-real-HOME assertion fails and names the settings file",
              os.path.join("forge", ".claude", "settings.local.json") in leaks, "sync exit %d, leaks %s; %s" % (code, leaks, tail(out)))
        with open(pp, "w") as fh:
            fh.write(good)
        code, out = w.forge("sync", "--apply", "--project", "forge")
        for k in set(w.snapshot()) - set(pre_b):  # the once-ever .bak of a file the control rewrote holds it too
            os.remove(os.path.join(w.top, k))
        want("control (b) put back: no file holds the real HOME again", real_home_in(w, changed_since(before, w.snapshot())), [])

    # (c) a world with every profile: only where the data is.
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    have_data = os.path.isdir(os.path.join(root, "config", "profiles")) and any(
        os.path.exists(os.path.join(root, *p)) for p in (("config", "publish-deny.txt"), ("publish", "engine.gitignore")))
    if not have_data:
        notrun.append("control (c): this checkout has no profiles beside its data, so there is no full world to show the assertion on")
    else:
        full = sandbox.mkdtemp("fresh-install-full-")
        sandbox.copy_checkout(full, untracked=True)  # never run in: it holds every profile, pointing at real projects
        ok, names = only_forge_and_demo(os.path.join(full, "config", "profiles"))
        print("control (c), a world built with copy_checkout(untracked=True): %d profiles (%s ...)" % (len(names), ", ".join(names[:4])))
        check("control (c): a world with every profile fails `only the forge and demo profiles`", not ok and len(names) > 2, "found %s" % names)

    # (d) a user_hooks row that names no script: configured, and nothing to check, so a FAIL and not a SKIP.
    fj = json.loads(good_fj)
    fj["user_hooks"] = [{"event": "Stop", "command": "echo done", "timeout": 5, "marker": "echo", "matcher": None, "agents": ["claude"]}]
    write_json(fj_path, fj)
    code, out = w.forge("doctor")
    rows = [l for l in out.splitlines() if " integrations " in l]
    print("control (d), a user_hooks row naming no script: %s" % (rows[-1][:150] if rows else "(no integrations row)"))
    check("control (d): a user_hooks row that names no script makes the integrations row a FAIL, checked 0",
          code == 1 and any(l.startswith("FAIL") and "checked 0" in l for l in rows), "exit %d: %s" % (code, rows[-1:] or tail(out)))
    with open(fj_path, "w") as fh:
        fh.write(good_fj)

    # The controls put the world back, as far as what a stranger runs: still no FAIL, still nothing pending.
    code, out = w.forge("doctor")
    check("after the controls forge doctor exits 0 again", code == 0, "exit %d: %s" % (code, tail(out)))
    code, out = w.forge("sync", "--all")
    check("after the controls a `forge sync --all` dry-run has no pending write", code == 0 and cli.pending_writes(out.splitlines()) == 0,
          "exit %d: %s" % (code, tail(out, 8)))


# ---------------------------------------------------------------- --track

def track_world():
    w = World("track")
    code, out = w.forge("init", "--yes", "--without", "codex,gsd", "--track")
    check("init --track exits 0", code == 0, "exit %d: %s" % (code, tail(out)))
    want("--track leaves every integration off", (read_json(w.path("config", "forge.json")) or {}).get("integrations"),
         {k: False for k in INTEGRATIONS})
    checked, missing = hook_check(w.home)
    check("with --track, every hook command still names a script that exists (%d checked)" % checked, checked > 0 and not missing, "missing %s" % missing[:2])
    data = w.path(".forge-data.git")
    want("init --track makes .forge-data.git, a history over the checkout (a git directory, not bare)",
         (os.path.isdir(data), git_out("--git-dir", data, "rev-parse", "--is-bare-repository").strip()), (True, "false"))
    want("the data history has no remote", git_out("--git-dir", data, "remote").strip(), "")
    code, out = w.forge("commit", "--all", "-m", "my data")
    check("forge commit puts the data in the data history", code == 0 and "private" in out, "exit %d: %s" % (code, tail(out)))
    tracked = git_out("--git-dir", data, "--work-tree", w.root, "ls-files").split()
    check("the data history holds config/forge.json and the profile", {"config/forge.json", "config/profiles/forge.claude.json"} <= set(tracked),
          "tracked: %s" % tracked[:10])
    want("the data history never holds the secrets or a generated settings file",
         [t for t in tracked if t.startswith("credentials") or t == "config/secrets.json" or t.endswith("settings.local.json")], [])
    eng = git_out("-C", w.root, "ls-files").split()
    want("the engine history took no data file", [t for t in eng if t.startswith(("config/forge.json", "config/profiles", "credentials"))], [])


def gsd_world():
    """init with GSD left on and `gsd_patches` false, the stranger's value: GSD comes
    unpatched from its own package, installed by GSD's own installer through pnpm, and npm is never called. The
    pnpm stub logs its argv and installs nothing. No config/toolchain.json is written (no npm package is pinned),
    forge.json says gsd_patches false, and the gsd runtime step of forge sync is the one-line unpatched note."""
    w = World("gsd")
    code, out = w.forge("init", "--yes", "--without", "codex")
    calls = w.stub_calls()
    want("init with gsd on calls pnpm once, with GSD's non-interactive flags for a global Claude Code install", calls["pnpm"], [GSD_DLX])
    want("init with gsd on never calls npm", calls["npm"], [])
    # Red before the skills step: "the init output has the skills step" (init ran gsd, sync, doctor).
    for step in ("gsd", "skills", "sync", "doctor"):
        check("the init output has the %s step" % step, "== forge init: %s ==" % step in out, tail(out, 12))
    check("there is no toolchain or gsd skills step", "== forge init: toolchain ==" not in out and "== forge init: gsd skills ==" not in out, tail(out, 12))
    check("a pnpm that exits 0 is not named as a failed step", "failed -- gsd" not in out, tail(out, 12))
    # The pnpm stub installs nothing, so the doctor's skill keep row FAILs: a step that ran and broke exits 1,
    # with its reason on a '!' line. Red before this change: exit 1 with no '! forge init' line at all ("exit 1,
    # no failed line: ... SUMMARY: 8 passed, 0 warnings, 1 failures | put your own skills in ...").
    check("a doctor that FAILs exits init 1, and a '!' line names it",
          code == 1 and "! forge init: failed -- doctor (exit 1)" in out, "exit %d: %s" % (code, tail(out, 6)))
    want("no config/toolchain.json: no npm package is pinned", os.path.exists(w.path("config", "toolchain.json")), False)
    doc = read_json(w.path("config", "forge.json")) or {}
    want("forge.json: gsd on, codex off, gsd_patches false", (doc.get("integrations", {}).get("gsd"), doc.get("integrations", {}).get("codex"), doc.get("gsd_patches")),
         (True, False, False))
    code, out = w.forge("skills")
    check("forge skills says the gsd runtime is the user's own unpatched install, with no '!' line",
          "GSD is your own unpatched install" in out and not any(l.lstrip().startswith("!") and "gsd" in l.lower() for l in out.splitlines()), tail(out, 12))
    want("forge skills touched neither npm nor pnpm again", (w.stub_calls()["npm"], w.stub_calls()["pnpm"]), ([], [GSD_DLX]))


def broken_gsd_world():
    """init with GSD on and a pnpm that exits 3: the installer ran and broke, which is a failure (the machine has
    the tool, so it is not a NOT RUN). The later steps still run, and the '!' line says which step and its exit
    code. Negative control: the same world with a pnpm that exits 0 has no 'failed -- gsd' (gsd_world)."""
    w = World("gsd-broken")
    stub(os.path.join(w.top, "stubs"), w.logs, "pnpm", "exit 3")
    code, out = w.forge("init", "--yes", "--without", "codex")
    # Red before this change: the line was "! forge init: failed -- gsd" (no exit code).
    check("a pnpm that exits 3: init exits 1 and the '!' line names the gsd step and its exit code",
          code == 1 and "! forge init: failed -- gsd (exit 3)" in out, "exit %d: %s" % (code, tail(out, 6)))
    check("a failed gsd step does not stop skills, sync and doctor", all("== forge init: %s ==" % s in out for s in ("skills", "sync", "doctor")), tail(out, 12))


def kept_world():
    """A checkout that holds data but no forge.json: init replaces none of it."""
    w = World("kept")
    os.makedirs(w.path("config"), exist_ok=True)
    os.makedirs(w.path("credentials"))
    mine = {"config/mcp-registry.json": '{"servers": {}, "_doc": "mine"}\n', "credentials/secrets.json": '{"TOKEN": "mine"}\n'}
    for rel, text in mine.items():
        with open(w.path(rel), "w") as fh:
            fh.write(text)
    code, out = w.forge("init", "--yes", "--without", "codex,gsd")
    check("init over existing data exits 0", code == 0, "exit %d: %s" % (code, tail(out)))
    for rel, text in mine.items():
        check("init keeps %s" % rel, open(w.path(rel)).read() == text and "kept   %s" % rel in out, "now %r; %s" % (open(w.path(rel)).read(), tail(out, 20)))


def other_checkout_world():
    """A machine whose SessionStart hook names another checkout: init and add refuse to write from this one."""
    w = World("other")
    other = os.path.join(w.top, "other")
    os.makedirs(os.path.join(other, "bin"))
    open(os.path.join(other, "bin", "forge"), "w").close()
    sandbox.installed_settings(w.home, other)
    before = w.snapshot()
    code, out = w.forge("init", "--yes", "--without", "codex,gsd")
    check("init from a checkout the machine does not run is refused, naming the one it runs", code == 1 and "is not the checkout this machine runs" in out and other in out,
          "exit %d: %s" % (code, tail(out)))
    check("and writes nothing", changed_since(before, w.snapshot()) == [], "changed: %s" % changed_since(before, w.snapshot())[:5])


def main():
    for part in (choice_cases, doctor_row_cases, main_world, track_world, gsd_world, broken_gsd_world, kept_world, other_checkout_world):
        try:
            part()
        except Exception as e:  # a part that cannot run is a failure of its own, and the others still run
            failures.append("%s raised %s: %s" % (part.__name__, type(e).__name__, e))
    for f in failures:
        print("FAIL", f)
    for n in notrun:
        print("NOT RUN", n)
    print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
    sandbox.cleanup(bool(failures))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
