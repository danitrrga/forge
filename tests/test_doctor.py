#!/usr/bin/env python3
"""The two `forge doctor` checks added in docs/unify-plan.md (steps 2 and 3), and the
row shape they needed. Each case builds its own world: nothing here reads or writes the real
machine's profiles, skills or HOME.

1. `sync_skill_keep.py --check`: the dry-run, exiting 1 when a profile would change. Until it
   existed nothing watched that drift; the doctor row runs it. The toy world is the real profiles
   copied beside a toy HOME and toy project dirs (the layout lib.may_write allows a toy HOME to
   write), --apply'd once so it is clean, then drifted by removing a skill from one profile.
2. A CHECKS row that is a Python callable returning a lib.Result, so a check can be a WARN: a
   command row maps exit code to PASS/FAIL only, and hindsight_doctor exits with its failure
   count, argparse with 2.
3. skill_name_clashes: a project skill named like a global skill (forge's skills/ or ~/.claude/skills) is a WARN.

Seen failing on the code before the change, as the cases printed it:
  --check (the script ignored the unknown flag, so --check --apply even wrote): "--check on a
  never-synced world = 0, want 1"; "--check on a drifted world = (0, 'Re-run with --apply, then:
  python scripts/sync/sync_agent_config.py --apply'), want (1, '1 profile(s) would change.')";
  "--check with --apply = (0, False), want (1, True)".
  rows (cmd_doctor ran every row as a command): "doctor with a WARN row = (None, 'TypeError: can
  only concatenate list (not "function") to list', ''), want (0, None, 'SUMMARY: 0 passed, 1
  warnings, 0 failures')"; "the skill keep row = None, want ['scripts/sync/sync_skill_keep.py',
  '--check']".
  clashes: "a clean world = ('raised', 'AttributeError', "module 'forge.cli' has no attribute
  'skill_name_clashes'"), want ('PASS', ...)".
Global skill only under HOME (clash-home): "a global skill only under HOME = ('WARN', 'skill names',
'b:gsd-fast'), want ('WARN', 'skill names', 'a:omarchy, b:gsd-fast')"; the check took the global names from forge's skills/ alone.
The MIT skills (mit-skills), run with skills/fixing-* moved aside: "forge ships the two MIT
skills = [], want ['fixing-accessibility', 'fixing-motion-performance']"; "a local copy of the MIT skills =
('PASS', 'skill names', \"no project skill shares a global skill's name\"), want ('WARN', 'skill names',
'hero:fixing-accessibility, hero:fixing-motion-performance')". With them present all pass.
Each mutation of the new code fails a case. A frozen profile skipped: "a seeded clash =
('WARN', 'skill names', 'a:gsd-fast, b:design-taste'), want (... 'fz:gsd-fast')". WARN returned as
FAIL: "a seeded clash = ('FAIL', ...)". --check always exiting 0: "--check on a drifted world = (0,
'1 profile(s) would change.'), want (1, ...)". A raising check not caught: "doctor with a raising
row = (None, 'OSError: unreadable', ...)". The fix text not appended: "the WARN row's line =
['WARN', 'w', 'a clash'], want [..., 'a clash -- rename it']".

4. The command guard smoke check (T3 of docs/command-guard-design.md). Seen failing on the
code before it (20 cases): "no profile turns the guard on = (['raised'], 'AttributeError'), want
(['PASS'], 'command guard')", "the entry removed = (['raised'], False), want (['FAIL'], True)",
"doctor over a guard with no entry = (0, None, False, False), want (1, None, True, True)". Each mutation
of the new code fails a case: CLAUDE_PROJECT_DIR not passed "a guarded profile, entry and config in
order = (['FAIL'], 'guard ok'), want (['PASS'], 'guard ok')"; any entry accepted "two guard entries =
['PASS'], want ['FAIL']"; the harmless command not required to exit 0 "a guard that refuses everything =
['PASS'], want ['FAIL']"; config never read "a config that does not parse = (['PASS'], False), want
(['FAIL'], True)"; a list result cut to its first line "doctor prints a line per guarded profile".

5. `forge doctor NAME` (the owner): one project's checks, each scoped to it. Seen failing on
the code before it (17 cases), every doctor case on argparse's "forge: error: unrecognized arguments:
<name>" (exit 2): "doctor of an unknown project = (2, False, False), want (1, True, True)", "a
never-synced project = (2, '', False), want (1, 'FAIL', True)", "a stale settings.local.json = (2, '',
False), want (1, 'FAIL', True)", "a frozen project's generated row = None, want ('PASS', 'frozen: forge
writes nothing')"; and "each write line = [None, ...], want [1, ...]" (no cli.pending_writes). Each
mutation of the new code fails a case: WOULD and DOC_CHANGES never matching "a stale settings.local.json
= (1, 'PASS', False), want (1, 'FAIL', True)"; SKIP- items counted "lines that write nothing = ['  ~ p
SKIP-agents-md(non-forge content):AGENTS.md'], want []"; the unreadable profile not looked up "doctor of
a profile with a wrong type = (1, ['e doctor: unknown proj'], '', False), want (1, ['profile'], 'FAIL',
True)"; skill_name_clashes unfiltered "a healthy project's rows = {... 'skill names': 'WARN' ...}";
command_guard_smoke unfiltered "{... 'guard guarded': 'FAIL' ...}"; frozen not special-cased in the
generated row "('PASS', 'the dry-run of forge sync --project frozen would write nothing'), want ('PASS',
'frozen: forge writes nothing')"; frozen not said in the profile row "a frozen project's profile row says
frozen = ('PASS', False)"; the hindsight row never shown "a healthy project's hindsight row names its
bank = False"; the dry-run's exit code ignored "a dry-run that exits 1 with nothing to write = ('PASS',
False), want ('FAIL', True)". Added after the simplify pass: exit 1 only on a FAIL, red on the code before
it (the default rows ran) and on cmd_doctor mutated to exit 1 for any NAME: "doctor NAME with only a WARN
= 1, want 0".

6. The `instruction files` row (research/21-para-forge/07): a block another tool wrote into an
AGENTS.md or CLAUDE.md (turbo, next dev, any `<!-- BEGIN:name -->`) is a WARN; reading none is a FAIL
(non-negotiable 7). Seen failing on the code before it, every case on "AttributeError: module 'forge.cli'
has no attribute 'instruction_file_blocks'": "2 turbo's block in AGENTS.md = [('raised', ...)], want
[('WARN', 'p:AGENTS.md:5 BEGIN:turborepo-agent-rules: set \"agentGuidance\": false ...')...]", "the row is
registered = [], want [None]". Control: with the marker pattern disabled the row says PASS for case 2, so
case 2 is red without it. Each mutation of the new code fails a case: links not resolved "7 AGENTS.md linked
to a CLAUDE.md with a block = [('WARN', 'p:AGENTS.md:4 ...'), ('WARN', 'p:CLAUDE.md:4 ...') ...]"; hidden and
build dirs walked "8 a block in node_modules, a build dir or a hidden dir does not count = [('WARN',
'p:.claude/worktrees/w/CLAUDE.md:1 ...')"; frozen not skipped "a frozen project is skipped = [('WARN',
'fz:CLAUDE.md:1 ...')"; zero not a FAIL "9 no file to read = [('PASS', 'read 0 instruction file(s) in 0
project(s), ...')], want [('FAIL', ...)]". `only` first filtered before the attribution: "only: the outer
project alone = [('WARN', 'outer:vault/CLAUDE.md:4 ...')...], want [('PASS', 'read 1 ...')]".

7. The `worktree guard` row (W3 of research/21-para-forge/04-guarda-de-worktrees.md): per guarded
profile, exactly the canonical group (matcher included) and a toy-worktree probe of the wired command; zero
guarded profiles, unscoped, is a FAIL. Seen failing on the code before it, 22 cases, every smoke case on
"AttributeError" ("worktree guard: no profile turns it on = (['raised'], 'AttributeError', False), want
(['FAIL'], 'worktree guard', True)"), "worktree guard: through doctor = (0, None, False), want (1, None, True)",
and "a healthy project's rows" without the row. Each mutation of the new code fails a case: scratch left to
the hook "a guarded profile, entry in order = (['FAIL'] ...), want (['PASS'] ...)"; zero a pass "no profile
turns it on = (['PASS'] ...)"; matcher not compared "no matcher = ['PASS'], want ['FAIL']"; BLOCKED not
required "exit 2 without BLOCKED = ['PASS']"; frozen checked and "on": false wired, each "... is not checked
= (['FAIL'], 'worktree guard frozen' / 'isoff')"; the probe run from the main checkout "a guarded profile,
entry in order = (['FAIL'] ...)".

8. `skill names` skips frozen profiles (docs/orchestration.md decided it; a frozen project's audit). Seen
failing on the code before it, 6 cases: "a seeded clash = ('WARN', 'skill names', 'a:gsd-fast, b:design-taste,
fz:gsd-fast'), want ('WARN', 'skill names', 'a:gsd-fast, b:design-taste')", "a frozen project, by name = ('WARN',
'skill names'), want ('SKIP', 'skill names')", "only a frozen project = ('WARN', 'skill names'), want ('FAIL',
'skill names')", "a frozen project's skill names row = 'PASS', want 'SKIP'". Control: with only the loop's frozen
skip removed, 4 cases fail ("a frozen clash beside a clean project = ('WARN', 'skill names', 'fz:gsd-fast'), want
('PASS', ...)").

9. The `frozen drift` row (a frozen project's audit, ENTREGA-A-FORGE.md): per frozen profile, the
settings.local.json keys that differ from what forge would write there if it were not frozen, computed in
memory (skills.write_settings_local with lib.write_json swapped for a recorder), never written. Seen failing on
the code before it, 15 cases, every one on "('raised', 'AttributeError', \"module 'forge.cli' has no attribute
'frozen_drift'\")", e.g. "a frozen file that approves what the profile does not = ('raised', ...), want ('WARN',
'frozen drift', 'p: enabledMcpjsonServers (2 on disk, 0 from forge); compared 1 frozen profile(s)')", "a frozen
project's doctor rows = False, want True", "a frozen project's frozen drift row = ('', False, False), want
('WARN', True, True)". Each mutation of the new code fails a case: the recorder removed so the write happens
"the drift check writes nothing = False, want True" and "...not even a .bak = ['settings.local.json',
'settings.local.json.bak'], want ['settings.local.json']"; the deny rows dropped "a deny row forge would add =
'compared 1 frozen profile(s), each settings.local.json is what forge would write', want 'p: permissions ...'";
keys only on disk ignored "a key forge would remove = ('PASS', 'frozen drift'), want ('WARN', 'frozen drift')";
zero compared a pass "a frozen profile whose directory is gone = ('WARN', 'frozen drift'), want ('FAIL', ...)";
unfrozen profiles compared "an unfrozen profile is not compared = ('WARN', ..., 'fz: ...; live: ...; compared
2 frozen profile(s)')"; the sizes dropped "p: enabledMcpjsonServers (? on disk, ? from forge)"; the recorder not
restored "lib.write_json is back after the call = '<lambda>', want 'write_json'".

10. T6 of docs/portable-design.md: the doctor reads config/forge.json. Each case below runs on a
toy forge.json (`settings_world`, `toy_settings`), never the real one. Seen failing on the code before it
(Sonnet 5.5), as the cases printed it:
  doctor_extra: "a toy doctor_extra row appears = [] ... want ['PASS toy', 'FAIL bad']", "no doctor_extra key adds
  nothing" held, "a malformed doctor_extra row is a FAIL = [], want ['FAIL doctor_extra']";
  CHECKS: "the hindsight and design rows left CHECKS = ['hindsight', 'design'], want []", "the integrations row is
  registered = False, want True";
  jev off: "jev off: the row is a SKIP that was not run = ('FAIL', False), want ('SKIP', True)" (the toy command
  exits 1 and ran), "jev off: the SKIP says how to turn it off for good = False";
  integrations: every case on "AttributeError: module 'forge.cli' has no attribute 'integrations_row'", e.g. "a
  user_hooks row naming a missing script = ('raised', ...), want ('FAIL', ...)";
  instruction_files_skip: "a project the config skips = ('WARN', ...), want ('SKIP', ...)";
  session_wait: "session_wait with the key absent = ('raised', ...), want None", "a session in the configured
  project waits = '', want 'memory is starting'", "another project is not special = 'memory is starting', want ''";
  forge sync: "gsd off: forge sync says NOT RUN = False" and "gsd off: the step did not run = False";
  forge test: "forge test lists the data history's tests = (0, False, ...), want (0, True, ...)";
  forge doctor NAME: "a healthy project's rows = {..., 'hindsight': 'SKIP'}, want {...}" and "a healthy project has
  no hindsight row = True, want False"."""
import argparse
import contextlib
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import lib  # noqa: E402
import sandbox  # noqa: E402

FIXTURES = os.path.join(sandbox.FORGE, "tests", "fixtures", "config")
# The settings the cases outside a `toy_settings` run on: the fixture forge.json, never this machine's
# config/forge.json (a copy_engine copy has none; red there before, M1: "! config/forge.json missing -- run
# bin/forge init" at the import of forge.hooks).
lib.SETTINGS = os.path.join(FIXTURES, "forge.json")
from forge import cli, hooks, skills  # noqa: E402,F401  (hooks: imported here, under the fixture config, so a toy one is never cached)

SCRIPT = "scripts/sync/sync_skill_keep.py"
# The skills a toy HOME holds in keep_world: the gsd-* ones the baseline is made of, toy-common (the fixture
# forge.json's one common skill) and `omarchy`, standalone.
TOY_SKILLS = ["gsd-fast", "gsd-debug", "toy-common", "omarchy"]
failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


@contextlib.contextmanager
def toy(root, home=None):
    """lib pointed at the toy `root` (and HOME at `home`, when given), restored on the way out: a
    toy ROOT left behind would leak into every later case."""
    real = lib.ROOT, lib.PROFILES, lib.HOME
    lib.ROOT, lib.PROFILES = root, os.path.join(root, "config", "profiles")
    if home is not None:
        lib.HOME = home
    try:
        yield
    finally:
        lib.ROOT, lib.PROFILES, lib.HOME = real


def put_profile(root, name, prof):
    with open(os.path.join(root, "config", "profiles", name + ".claude.json"), "w") as fh:
        json.dump(prof, fh)


def keep_world(tmp):
    """(root, env): a toy forge with the fixture profiles (project_path moved into the toy), a toy HOME
    holding TOY_SKILLS, and a settings.json naming the toy checkout so --apply may write."""
    base = os.path.join(tmp, "keep")
    root, home = os.path.join(base, "forge"), os.path.join(base, "home")
    sandbox.mini_root(root, SCRIPT)
    os.makedirs(os.path.join(root, "config", "profiles"))
    # The skill tables live in config/forge.json (T3 of docs/portable-design.md): a toy root without it exits 1.
    shutil.copy(os.path.join(FIXTURES, "forge.json"), os.path.join(root, "config", "forge.json"))
    for f in glob.glob(os.path.join(FIXTURES, "profiles", "*.claude.json")):
        with open(f, encoding="utf-8") as fh:
            prof = json.load(fh)
        prof["project_path"] = os.path.join(base, "projects", os.path.basename(f)[:-len(".claude.json")])
        os.makedirs(prof["project_path"])
        with open(os.path.join(root, "config", "profiles", os.path.basename(f)), "w", encoding="utf-8") as fh:
            json.dump(prof, fh)
    for name in TOY_SKILLS:
        os.makedirs(os.path.join(home, ".claude", "skills", name))
    sandbox.installed_settings(home, root)
    return root, sandbox.bare_env(home, base)


def keep(root, env, *flags):
    r = subprocess.run([sys.executable, SCRIPT] + list(flags), cwd=root, env=env, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1]


def keep_cases(tmp):
    root, env = keep_world(tmp)
    profiles = os.path.join(root, "config", "profiles")
    drifted = os.path.join(profiles, "app.claude.json")
    # A world that was never synced is drift too: every profile lacks COMMON_ENV.
    want("--check on a never-synced world", keep(root, env, "--check")[0], 1)
    want("--apply on the toy world", keep(root, env, "--apply")[0], 0)
    want("--check on a clean world", keep(root, env, "--check"), (0, "0 profile(s) would change."))
    want("a dry-run on a clean world", keep(root, env)[0], 0)

    with open(drifted, encoding="utf-8") as fh:
        prof = json.load(fh)
    prof["skills_keep"].remove("gsd-fast")
    with open(drifted, "w", encoding="utf-8") as fh:
        json.dump(prof, fh)
    before = sandbox.manifest(root, tops=("config",))
    want("--check on a drifted world", keep(root, env, "--check"), (1, "1 profile(s) would change."))
    want("--check wrote nothing", sandbox.manifest(root, tops=("config",)) == before, True)
    # What the flag must not change: the plain dry-run still reports and exits 0.
    want("a dry-run on a drifted world", keep(root, env)[0], 0)
    code, last = keep(root, env, "--check", "--apply")
    # forge's exit rule is a line starting with "! ", as every other sys.exit message in the script does.
    want("--check with --apply", (code, "--check" in last and "--apply" in last, last.startswith("! ")), (1, True, True))
    want("--check with --apply wrote nothing", sandbox.manifest(root, tops=("config",)) == before, True)
    want("--apply repairs the drift", keep(root, env, "--apply")[0], 0)
    want("--check after the repair", keep(root, env, "--check")[0], 0)


def doctor(rows):
    """(exit code, output lines, the exception's type name or None) of cmd_doctor over `rows`."""
    real, cli.CHECKS = cli.CHECKS, rows
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = cli.cmd_doctor(None)
        err = None
    except Exception as e:
        code, err = None, "%s: %s" % (type(e).__name__, e)
    finally:
        cli.CHECKS = real
    return code, out.getvalue().splitlines(), err


def fields(lines, i):
    """Level, name and detail of the i-th printed line, empty when there is none."""
    return ((lines[i].split(None, 2) if i < len(lines) else []) + ["", "", ""])[:3]


def summary(lines):
    return next((l for l in lines if l.startswith("SUMMARY")), "")


def row_cases():
    warn = lambda: lib.Result("WARN", "w", "a clash")  # noqa: E731
    fail = lambda: lib.Result("FAIL", "f", "broken")  # noqa: E731
    ok = lambda: lib.Result("PASS", "p", "fine")  # noqa: E731

    def boom():
        raise OSError("unreadable")
    code, lines, err = doctor([("w", warn, "rename it")])
    want("doctor with a WARN row", (code, err, summary(lines)), (0, None, "SUMMARY: 0 passed, 1 warnings, 0 failures"))
    want("the WARN row's line", fields(lines, 0), ["WARN", "w", "a clash -- rename it"])
    code, lines, err = doctor([("p", ok, "unused"), ("f", fail, "fix it")])
    want("doctor with a FAIL row", (code, err, fields(lines, 0)[0], fields(lines, 1)[2]),
         (1, None, "PASS", "broken -- fix it"))
    want("a PASS row's detail carries no fix", fields(lines, 0)[2], "fine")
    code, lines, err = doctor([("b", boom, "see the error")])
    want("doctor with a raising row", (code, err, fields(lines, 0)), (1, None, ["FAIL", "b", "OSError: unreadable -- see the error"]))
    # The command rows are unchanged: exit code 0 is PASS, anything else FAIL with the last line.
    code, lines, err = doctor([("c0", ["-c", "print('all good')"], "fix"),
                               ("c2", ["-c", "import sys; print('bad'); sys.exit(2)"], "fix it")])
    want("command rows", (code, [fields(lines, 0), fields(lines, 1)]),
         (1, [["PASS", "c0", "all good"], ["FAIL", "c2", "bad -- fix it"]]))
    # The two real rows are registered: the keep check as a command, the clash check as a callable.
    rows = {name: cmd for name, cmd, _ in cli.CHECKS}
    want("the skill keep row", rows.get("skill keep"), [SCRIPT, "--check"])
    want("the skill names row", rows.get("skill names"), getattr(cli, "skill_name_clashes", None))
    # The two rows that came from the code's table now come from config/forge.json's doctor_extra.
    want("the hindsight and design rows left CHECKS", [n for n in ("hindsight", "design") if n in rows], [])
    want("the doctor_extra row is registered", rows.get("doctor_extra") is not None and rows.get("doctor_extra") is getattr(cli, "doctor_extra_row", 0), True)
    want("the integrations row is registered", rows.get("integrations") is not None and rows.get("integrations") is getattr(cli, "integrations_row", 0), True)


def toy_cases(tmp):
    # The restore is the point of `toy`, and no other case can see it go missing: each one that reads
    # lib swaps its own world in first. Control: leave lib.ROOT and lib.PROFILES at the toy in toy's
    # `finally` and "toy restores on exit" goes red.
    real = lib.ROOT, lib.PROFILES, lib.HOME
    home = os.path.join(tmp, "toy-home")
    with toy(tmp, home):
        want("toy points lib at the world", (lib.ROOT, lib.PROFILES, lib.HOME),
             (tmp, os.path.join(tmp, "config", "profiles"), home))
    want("toy restores on exit", (lib.ROOT, lib.PROFILES, lib.HOME), real)
    try:
        with toy(tmp, home):
            raise ValueError
    except ValueError:
        pass
    want("toy restores on an exception", (lib.ROOT, lib.PROFILES, lib.HOME), real)
    with toy(tmp):
        want("toy leaves HOME alone without home", lib.HOME, real[2])


def clash_world(tmp, name, projects, global_skills, frozen=()):
    """A toy ROOT with skills/<global_skills> and one profile per project in `projects`
    ({project: [skill dirs in its .claude/skills]}), pointed at by lib.ROOT and lib.PROFILES."""
    root = os.path.join(tmp, name)
    for s in global_skills:
        os.makedirs(os.path.join(root, "skills", s))
    os.makedirs(os.path.join(root, "config", "profiles"))
    for proj, skills in projects.items():
        path = os.path.join(root, "projects", proj)
        os.makedirs(path)
        for s in skills:
            os.makedirs(os.path.join(path, ".claude", "skills", s))
        prof = {"project": proj, "project_path": path}
        if proj in frozen:
            prof["frozen"] = True
        put_profile(root, proj, prof)
    return root


def clashes(root, home_skills=()):
    """skill_name_clashes in the toy `root`, with a toy HOME whose ~/.claude/skills holds `home_skills`
    (the real HOME is never read, and skills.global_skills' cache is cleared on both sides)."""
    home = os.path.join(root, "home")
    for s in home_skills:
        os.makedirs(os.path.join(home, ".claude", "skills", s))
    skills.global_skills.cache_clear()
    try:
        with toy(root, home):
            return tuple(cli.skill_name_clashes())
    except Exception as e:
        return ("raised", type(e).__name__, str(e))
    finally:
        skills.global_skills.cache_clear()


def clashes_only(root, only):
    """skill_name_clashes(only) in the toy `root`, with a toy HOME and the caches cleared as `clashes` does."""
    skills.global_skills.cache_clear()
    try:
        with toy(root, os.path.join(root, "home")):
            res = cli.skill_name_clashes(only)
            return tuple(res)
    except Exception as e:
        return ("raised", type(e).__name__, str(e))
    finally:
        skills.global_skills.cache_clear()


def clash_cases(tmp):
    clean = clash_world(tmp, "clean", {"a": ["local-one"], "b": []}, ["gsd-fast", "design-taste"])
    # The PASS says how many it read (non-negotiable 7): 1 skill in 2 projects, b has none. Red on
    # 77ba24d: "FAIL a clean world = ('PASS', 'skill names', \"no project skill shares a global skill's
    # name\"), want ('PASS', 'skill names', \"read 1 project skill(s) in 2 project(s), none shares a global skill's name\")".
    want("a clean world", clashes(clean), ("PASS", "skill names",
         "read 1 project skill(s) in 2 project(s), none shares a global skill's name"))
    # A project with no .claude/skills is read and clean (most real ones have none). A profile without
    # project_path or whose directory is gone is not read: a WARN naming it, never a silent pass.
    # Red on 77ba24d: "FAIL a profile without project_path = ('PASS', ...), want ('WARN', 'skill names', ...)".
    put_profile(clean, "nopath", {"project": "nopath"})
    want("a profile without project_path", clashes(clean), ("WARN", "skill names",
         "not read, no project_path or no such directory: nopath; read 1 project skill(s) in 2 project(s)"))
    put_profile(clean, "gone", {"project": "gone", "project_path": os.path.join(clean, "projects", "gone")})
    want("a profile whose project directory is gone", clashes(clean)[:2], ("WARN", "skill names"))
    want("...and it names both", ["gone, nopath" in clashes(clean)[2]], [True])
    for gone in ("gone", "nopath"):
        os.remove(os.path.join(clean, "config", "profiles", gone + ".claude.json"))
    # Zero projects read is a FAIL where zero is impossible: only the unreadable profile in scope.
    only = clash_world(tmp, "unreadable", {}, ["gsd-fast"])
    put_profile(only, "nopath", {"project": "nopath"})
    want("no project read at all", clashes(only), ("FAIL", "skill names",
         "no project read; not read, no project_path or no such directory: nopath"))
    want("no profile at all", clashes(clash_world(tmp, "noprofile", {}, ["gsd-fast"]))[:2], ("FAIL", "skill names"))
    # Hidden dirs are not skills (skill_dirs), and a plain file named like a global skill is not one.
    os.makedirs(os.path.join(clean, "projects", "a", ".claude", "skills", ".gsd-fast"))
    open(os.path.join(clean, "projects", "a", ".claude", "skills", "gsd-fast"), "w").close()
    want("hidden dirs and plain files", clashes(clean)[0], "PASS")

    seeded = clash_world(tmp, "seeded", {"a": ["gsd-fast", "mine"], "b": ["design-taste"], "z": ["unrelated"], "fz": ["gsd-fast"]},
                         ["gsd-fast", "design-taste", "other"], frozen=("fz",))
    # A frozen project is skipped (docs/orchestration.md: a frozen project's own copies of a global
    # skill stopped warning); its divergence is the frozen drift row's. fz holds gsd-fast and is not named.
    want("a seeded clash", clashes(seeded),
         ("WARN", "skill names", "a:gsd-fast, b:design-taste"))
    # An unread project beside a clash is named after it, so the clash text stays what it was.
    put_profile(seeded, "nopath", {"project": "nopath"})
    want("a clash beside an unread project", clashes(seeded),
         ("WARN", "skill names", "a:gsd-fast, b:design-taste; not read, no project_path or no such directory: nopath"))
    os.remove(os.path.join(seeded, "config", "profiles", "nopath.claude.json"))
    # By name, a frozen project is a SKIP (as the instruction files row is); beside a clean project its
    # clash is not counted; and a world of frozen projects alone read 0 projects, a FAIL.
    want("a frozen project, by name", clashes_only(seeded, "fz")[:2], ("SKIP", "skill names"))
    cleanfz = clash_world(tmp, "clean-frozen", {"a": ["mine"], "fz": ["gsd-fast"]}, ["gsd-fast"], frozen=("fz",))
    want("a frozen clash beside a clean project", clashes(cleanfz),
         ("PASS", "skill names", "read 1 project skill(s) in 1 project(s), none shares a global skill's name"))
    onlyfz = clash_world(tmp, "only-frozen", {"fz": ["gsd-fast"]}, ["gsd-fast"], frozen=("fz",))
    want("only a frozen project", clashes(onlyfz)[:2], ("FAIL", "skill names"))

    # A global skill that exists only in ~/.claude/skills (omarchy, diagnose-crash on this machine:
    # links into /usr/share/omarchy) is global too. forge's skills/ has no "omarchy".
    homeonly = clash_world(tmp, "homeonly", {"a": ["omarchy", "mine"], "b": ["gsd-fast"]}, ["gsd-fast"])
    want("a global skill only under HOME", clashes(homeonly, ["omarchy"]),
         ("WARN", "skill names", "a:omarchy, b:gsd-fast"))

    # The two MIT frontend review skills forge ships (mit-skills). The global names are the
    # real checkout's skills/, so this fails until forge ships them; a project that keeps a local copy
    # (a frozen project's hero profile had one of each, git-ignored) is flagged, and the same project without it is clean.
    mit = ["fixing-accessibility", "fixing-motion-performance"]
    if os.path.isdir(os.path.join(sandbox.FORGE, "skills")):
        real = os.listdir(os.path.join(sandbox.FORGE, "skills"))
        want("forge ships the two MIT skills", [s for s in mit if s in real], mit)
    else:  # a copy_engine copy has no skills/, so there is nothing that ships them to check
        real = ["gsd-fast", "design-taste", "other"] + mit
        print("NOT RUN: forge ships the two MIT skills -- no skills/ in this checkout")
    local = clash_world(tmp, "mit-local", {"hero": mit + ["mine"]}, real)
    want("a local copy of the MIT skills", clashes(local),
         ("WARN", "skill names", "hero:fixing-accessibility, hero:fixing-motion-performance"))
    gone = clash_world(tmp, "mit-gone", {"hero": ["mine"]}, real)
    want("the MIT skills without the local copy", clashes(gone),
         ("PASS", "skill names", "read 1 project skill(s) in 1 project(s), none shares a global skill's name"))


DRIFT_REGISTRY = {"servers": {"s": {"deny_tools": ["t"]}}}


def drift_world(tmp, name, projects, registry=DRIFT_REGISTRY):
    """A toy ROOT with a registry and one profile per project in `projects`: {project: (profile fields,
    settings.local.json content, or None for no file)}. The project's directory is root/projects/<project>."""
    root = os.path.join(tmp, name)
    os.makedirs(os.path.join(root, "config", "profiles"))
    with open(os.path.join(root, "config", "mcp-registry.json"), "w") as fh:
        json.dump(registry, fh)
    for proj, (extra, settings) in projects.items():
        path = os.path.join(root, "projects", proj)
        os.makedirs(os.path.join(path, ".claude"))
        if settings is not None:
            with open(os.path.join(path, ".claude", "settings.local.json"), "w") as fh:
                json.dump(settings, fh)
        put_profile(root, proj, dict({"project": proj, "project_path": path}, **extra))
    return root


def drift(root, only=None):
    """cli.frozen_drift in the toy `root` (a toy HOME beside it) as a tuple of (level, name, detail)."""
    skills.global_skills.cache_clear()
    skills.plugin_universe.cache_clear()
    try:
        with toy(root, os.path.join(root, "home")):
            return tuple(cli.frozen_drift(only))
    except Exception as e:
        return ("raised", type(e).__name__, str(e))
    finally:
        skills.global_skills.cache_clear()
        skills.plugin_universe.cache_clear()


def drift_cases(tmp):
    """The `frozen drift` row (a frozen project's audit, ENTREGA-A-FORGE.md, point 9 and the closing list): what forge would write into a frozen project's settings.local.json, computed in memory,
    against what is on disk."""
    # A frozen project's real case in miniature: the profile approves no .mcp.json server, the file approves two.
    portal = drift_world(tmp, "drift-portal", {
        "p": ({"frozen": True, "mcpjson_approved": []}, {"enabledMcpjsonServers": ["a", "b"], "x": 1})})
    before = sandbox.manifest(portal)
    want("a frozen file that approves what the profile does not", drift(portal), (
        "WARN", "frozen drift", "p: enabledMcpjsonServers (2 on disk, 0 from forge); compared 1 frozen profile(s)"))
    # Nothing is written: not the file, and not the once-ever .bak that write_json(backup=True) makes.
    want("the drift check writes nothing", sandbox.manifest(portal) == before, True)
    want("...not even a .bak", sorted(os.listdir(os.path.join(portal, "projects", "p", ".claude"))),
         ["settings.local.json"])
    # The recorder that stands in for lib.write_json during the call is put back, or every later write in
    # the process (a session start's own sync) would be swallowed.
    want("lib.write_json is back after the call", lib.write_json.__name__, "write_json")

    # Equal: the file already holds what forge would write (and a key forge has no opinion on).
    same = drift_world(tmp, "drift-same", {
        "p": ({"frozen": True, "mcpjson_approved": ["a"]}, {"enabledMcpjsonServers": ["a"], "x": 1})})
    want("a frozen file that is what forge would write", drift(same),
         ("PASS", "frozen drift", "compared 1 frozen profile(s), each settings.local.json is what forge would write"))

    # A key forge removes because the profile does not declare it (env is generator-owned both ways),
    # while a permission Claude Code added is merged into, not drift.
    stale = drift_world(tmp, "drift-env", {
        "p": ({"frozen": True}, {"env": {"STALE": "1"}, "permissions": {"allow": ["Bash(ls)"]}})})
    want("a key forge would remove", drift(stale)[:2], ("WARN", "frozen drift"))
    want("...named, and the added permission is not", drift(stale)[2].split(";")[0], "p: env (1 on disk, absent from forge)")

    # The deny rows a granted server declares (mcp.with_denied_tools) are part of what forge would write.
    deny = drift_world(tmp, "drift-deny", {"p": ({"frozen": True, "servers": ["s"]}, {})})
    want("a deny row forge would add", drift(deny)[2].split(";")[0], "p: permissions (absent on disk, 1 from forge)")
    deny_ok = drift_world(tmp, "drift-deny-ok", {
        "p": ({"frozen": True, "servers": ["s"]}, {"permissions": {"deny": ["mcp__s__t"]}})})
    want("a deny row already there", drift(deny_ok)[0], "PASS")

    # Only frozen profiles are compared; an unfrozen one with the same drift is the generated row's.
    mixed = drift_world(tmp, "drift-mixed", {
        "fz": ({"frozen": True, "mcpjson_approved": []}, {"enabledMcpjsonServers": ["a"]}),
        "live": ({"mcpjson_approved": []}, {"enabledMcpjsonServers": ["a"]})})
    want("an unfrozen profile is not compared", drift(mixed),
         ("WARN", "frozen drift", "fz: enabledMcpjsonServers (1 on disk, 0 from forge); compared 1 frozen profile(s)"))

    # Zero compared is a FAIL only when something is frozen (non-negotiable 7); no frozen profile at all is
    # nothing to compare.
    want("no profile is frozen", drift(drift_world(tmp, "drift-none", {"live": ({}, {})}))[:2], ("PASS", "frozen drift"))
    gone = drift_world(tmp, "drift-gone", {"p": ({"frozen": True}, {})})
    shutil.rmtree(os.path.join(gone, "projects", "p"))
    want("a frozen profile whose directory is gone", drift(gone)[:2], ("FAIL", "frozen drift"))
    bad = drift_world(tmp, "drift-bad", {"p": ({"frozen": True}, {})})
    with open(os.path.join(bad, "projects", "p", ".claude", "settings.local.json"), "w") as fh:
        fh.write("{not json")
    want("a frozen file that does not parse is not compared", drift(bad)[:2], ("FAIL", "frozen drift"))
    # One unread beside one compared: a WARN that names it, and the count still says how many were compared.
    beside = drift_world(tmp, "drift-beside", {"ok": ({"frozen": True}, {}), "gone": ({"frozen": True}, {})})
    shutil.rmtree(os.path.join(beside, "projects", "gone"))
    res = drift(beside)
    want("an unread frozen profile beside a compared one", (res[:2], "gone" in res[2], "compared 1 frozen profile(s)" in res[2]),
         (("WARN", "frozen drift"), True, True))
    # By name: the frozen project's own row; an unfrozen project is a SKIP that says so.
    want("by name, the frozen project", drift(mixed, "fz")[0], "WARN")
    want("by name, an unfrozen project", drift(mixed, "live")[:2], ("SKIP", "frozen drift"))
    # Registered, and in a frozen project's doctor rows only.
    want("the frozen drift row is registered", {n: c for n, c, _ in cli.CHECKS}.get("frozen drift"),
         getattr(cli, "frozen_drift", None))
    names = lambda prof: [n for n, _, _ in cli.project_checks("p", prof, None)]  # noqa: E731
    want("a frozen project's doctor rows", "frozen drift" in names({"frozen": True}), True)
    want("an unfrozen project's doctor rows", "frozen drift" in names({}), False)


TURBO = "<!-- BEGIN:turborepo-agent-rules -->\n# This is NOT the Turborepo you know\n<!-- END:turborepo-agent-rules -->\n"
NEXT = "<!-- BEGIN:nextjs-agent-rules -->\n# This is NOT the Next.js you know\n<!-- END:nextjs-agent-rules -->\n"
# The markers are the generator's own constants, read from its source: this file names none of them.
_SYSDOC = open(os.path.join(sandbox.FORGE, "scripts", "sync", "sync_system_doc.py"), encoding="utf-8").read()
FORGE_OWN = (re.search(r'^BEGIN = "(.*)"$', _SYSDOC, re.M).group(1) + "\nsee AGENT-SYSTEM.md\n"
             + re.search(r'^END = "(.*)"$', _SYSDOC, re.M).group(1) + "\n<!-- ds-readiness:begin -->\nimport from ui\n<!-- ds-readiness:end -->\n")
OWN = "# The project's own text\n\nRun the tests before a commit.\n"


def inst_world(tmp, name, projects, frozen=()):
    """A toy ROOT with one profile per project in `projects` ({project: {relative file: text}}); a text
    that is ("link", target) makes the file a symlink to that sibling."""
    root = os.path.join(tmp, name)
    os.makedirs(os.path.join(root, "config", "profiles"))
    for proj, files in projects.items():
        base = os.path.join(root, "projects", proj)
        os.makedirs(base)
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(base, rel)), exist_ok=True)
            if isinstance(text, tuple):
                os.symlink(text[1], os.path.join(base, rel))
            else:
                with open(os.path.join(base, rel), "w") as fh:
                    fh.write(text)
        prof = {"project": proj, "project_path": base}
        if proj in frozen:
            prof["frozen"] = True
        put_profile(root, proj, prof)
    return root


def inst(root, only=None):
    """instruction_file_blocks over the toy `root`, as [(level, detail)]; the real profiles are never read."""
    try:
        with toy(root):
            res = cli.instruction_file_blocks(only)
        return [(r.level, r.detail) for r in (res if isinstance(res, list) else [res])]
    except Exception as e:
        return [("raised", "%s: %s" % (type(e).__name__, e))]


def instruction_cases(tmp):
    n = [0]

    def world(files, **kw):
        n[0] += 1
        return inst_world(tmp, "inst%d" % n[0], {"p": files}, **kw)
    tfix = 'set "agentGuidance": false in the root turbo.json and delete the block'
    nfix = "set agentRules: false in next.config and delete the block"

    clean = world({"AGENTS.md": OWN, "CLAUDE.md": OWN})
    want("1 a clean project", inst(clean), [("PASS", "read 2 instruction file(s) in 1 project(s), no tool-managed block")])
    before = sandbox.manifest(clean)
    inst(clean)
    want("the row writes nothing", sandbox.manifest(clean) == before, True)

    turbo = world({"AGENTS.md": OWN + "\n" + TURBO, "CLAUDE.md": OWN})
    want("2 turbo's block in AGENTS.md", inst(turbo), [
        ("WARN", "p:AGENTS.md:5 BEGIN:turborepo-agent-rules: " + tfix),
        ("WARN", "read 2 instruction file(s) in 1 project(s), 1 tool-managed block(s)")])
    # The control: with the marker pattern gone the row cannot warn, so case 2 would be red.
    real_block = getattr(cli, "FOREIGN_BLOCK", None)
    cli.FOREIGN_BLOCK = re.compile(r"(?!)")
    try:
        want("2 control: without the pattern the row passes (case 2 red)", inst(turbo)[0][0], "PASS")
    finally:
        cli.FOREIGN_BLOCK = real_block
        if real_block is None:
            del cli.FOREIGN_BLOCK

    want("3 next's block in the root CLAUDE.md", inst(world({"CLAUDE.md": OWN + NEXT}))[0],
         ("WARN", "p:CLAUDE.md:4 BEGIN:nextjs-agent-rules: " + nfix))
    want("4 next's block in apps/web/AGENTS.md", inst(world({"CLAUDE.md": OWN, "apps/web/AGENTS.md": NEXT}))[0],
         ("WARN", "p:apps/web/AGENTS.md:1 BEGIN:nextjs-agent-rules: " + nfix))
    want("5 an unknown BEGIN: marker", inst(world({"CLAUDE.md": "<!-- BEGIN:other-tool -->\nx\n"}))[0],
         ("WARN", "p:CLAUDE.md:1 BEGIN:other-tool: a tool wrote this block; remove it and switch that tool's setting off"))
    want("6 forge's own two markers", inst(world({"CLAUDE.md": FORGE_OWN})),
         [("PASS", "read 1 instruction file(s) in 1 project(s), no tool-managed block")])
    linked = inst(world({"CLAUDE.md": OWN + TURBO, "AGENTS.md": ("link", "CLAUDE.md")}))
    want("7 AGENTS.md linked to a CLAUDE.md with a block", linked, [
        ("WARN", "p:CLAUDE.md:4 BEGIN:turborepo-agent-rules: " + tfix),
        ("WARN", "read 1 instruction file(s) in 1 project(s), 1 tool-managed block(s)")])
    want("8 a block in node_modules, a build dir or a hidden dir does not count",
         inst(world({"CLAUDE.md": OWN, "node_modules/x/AGENTS.md": TURBO, "apps/web/node_modules/y/CLAUDE.md": NEXT,
                     ".claude/worktrees/w/CLAUDE.md": TURBO, "dist/CLAUDE.md": NEXT})),
         [("PASS", "read 1 instruction file(s) in 1 project(s), no tool-managed block")])
    want("9 no file to read", inst(world({"README.md": "x"})), [("FAIL", "read 0 instruction files in 1 project(s), and a check "
                                                                    "that saw nothing is not a pass (does project_path hold an AGENTS.md or CLAUDE.md?)")])
    want("9 no profile at all", inst(inst_world(tmp, "inst-empty", {}))[0][0], "FAIL")
    want("a block four levels down is not seen", inst(world({"CLAUDE.md": OWN, "a/b/c/d/AGENTS.md": TURBO}))[0][0], "PASS")
    want("a block three levels down is", inst(world({"CLAUDE.md": OWN, "a/b/c/AGENTS.md": TURBO}))[0][0], "WARN")

    # Orchestrator decisions: frozen profiles are skipped (and a world of only frozen ones read 0), the
    # deepest project owns a nested file, `dev` is not a project, and `only` scopes to one project.
    frozen = inst_world(tmp, "inst-frozen", {"fz": {"CLAUDE.md": TURBO}, "ok": {"CLAUDE.md": OWN}}, frozen=("fz",))
    want("a frozen project is skipped", inst(frozen), [("PASS", "read 1 instruction file(s) in 1 project(s), no tool-managed block")])
    want("a frozen project, by name", inst(frozen, "fz")[0][0], "SKIP")
    nested = inst_world(tmp, "inst-nested", {"outer": {"CLAUDE.md": OWN}})
    inner = os.path.join(nested, "projects", "outer", "vault")
    os.makedirs(inner)
    with open(os.path.join(inner, "CLAUDE.md"), "w") as fh:
        fh.write(OWN + TURBO)
    put_profile(nested, "inner", {"project": "inner", "project_path": inner})
    put_profile(nested, "dev", {"project": "dev", "project_path": os.path.join(nested, "projects")})
    want("a nested file belongs to the deepest project, dev reads nothing", [d for _, d in inst(nested)][0],
         "inner:CLAUDE.md:4 BEGIN:turborepo-agent-rules: " + tfix)
    want("read counts once across nested profiles", inst(nested)[-1][1].startswith("read 2 instruction file(s) in 2 project(s)"), True)
    want("only: the outer project alone", inst(nested, "outer"), [("PASS", "read 1 instruction file(s) in 1 project(s), no tool-managed block")])
    # "dev" is a name instruction_files_skip lists (this machine's forge.json does; the fixture's list is empty).
    with toy_settings(settings_world(tmp, "inst-dev-skip", dict(integrations=OFF, instruction_files_skip=["dev"]))):
        want("only: dev is not a project", inst(nested, "dev")[0][0], "SKIP")
    # Wired as a row, and into forge doctor NAME.
    want("the row is registered", [c for n_, c, _ in cli.CHECKS if n_ == "instruction files"], [getattr(cli, "instruction_file_blocks", None)])
    with toy(turbo):
        rows = [n_ for n_, _, _ in cli.project_checks("p", lib.profiles()["p"], None)]
    want("the row is in forge doctor NAME", "instruction files" in rows, True)


# A stand-in for hooks/guard_tool_use.py: forge's real guard does not refuse `cat ~/.npmrc` until T1
# of docs/command-guard-design.md merges, and what is under test is the check, not the guard. It
# refuses (exit 2) only a Bash command naming ~/.npmrc, and only when CLAUDE_PROJECT_DIR is set, so
# a check that forgets the variable gets 0 for the canary and fails.
STUB_GUARD = """import json, os, sys
d = json.load(sys.stdin)
if os.environ.get("CLAUDE_PROJECT_DIR") and "~/.npmrc" in d["tool_input"].get("command", ""):
    sys.exit(2)
"""


def guard_world(tmp, name, entry="canonical", config=None, guard=STUB_GUARD, hooks=None, frozen=False, root=None,
                hook_extra=None, matcher=None):
    """A toy ROOT (`root`, or tmp/name) with a stub guard and a profile `name` that turns the guard
    on, whose project's settings.local.json holds `entry`: "canonical" (the command the check
    expects), "none" (no guard entry, only another hook), "twice" (the canonical entry in two
    groups), "missing" (no settings.local.json), or any other string, taken as the command.
    `config` is the text of config/guard/<name>.json, absent when None; `matcher` is the group's matcher."""
    root = root or os.path.join(tmp, name)
    os.makedirs(os.path.join(root, "hooks"), exist_ok=True)
    os.makedirs(os.path.join(root, "config", "profiles"), exist_ok=True)
    project = os.path.join(root, "projects", name)
    os.makedirs(os.path.join(project, ".claude"))
    with open(os.path.join(root, "hooks", "guard_tool_use.py"), "w") as fh:
        fh.write(guard)
    prof = {"project": name, "project_path": project, "command_guard": True}
    if hooks:
        prof["hooks"] = hooks
    if frozen:
        prof["frozen"] = True
    put_profile(root, name, prof)
    if config is not None:
        os.makedirs(os.path.join(root, "config", "guard"), exist_ok=True)
        with open(os.path.join(root, "config", "guard", name + ".json"), "w") as fh:
            fh.write(config)
    canonical = "python3 %s --project %s" % (os.path.join(root, "hooks", "guard_tool_use.py"), name)
    group = lambda c: dict({"matcher": matcher} if matcher else {},  # noqa: E731
                           hooks=[dict({"type": "command", "command": c, "timeout": 10}, **(hook_extra or {}))])
    pre = {"canonical": [group(canonical)], "none": [group("python3 /elsewhere/audit.py")],
           "twice": [group(canonical), group(canonical)]}.get(entry) or [group(entry)]
    if entry != "missing":
        with open(os.path.join(project, ".claude", "settings.local.json"), "w") as fh:
            json.dump({"hooks": {"PreToolUse": pre}}, fh)
    return root


# Entries with the canonical command that would not stop a call: (label, keys over the canonical hook).
BAD_HOOKS = [("type prompt", {"type": "prompt"}), ("timeout 0", {"timeout": 0}), ("timeout 0.01", {"timeout": 0.01}),
             ("no type", {"type": None}), ("async", {"async": True})]


def smoke(root, fn_name, *args):
    """The rows of the cli check `fn_name` (command_guard_smoke, worktree_guard_smoke) in the toy
    `root`, as (level, name, detail) tuples."""
    try:
        with toy(root):
            got = getattr(cli, fn_name)(*args)
        return [tuple(r) for r in (got if isinstance(got, list) else [got])]
    except Exception as e:
        return [("raised", type(e).__name__, str(e))]


def levels(rows):
    return [r[0] for r in rows]


def hooks_world(root, name, hooks):
    """`root` (a guard_world or wtguard_world) with its project's settings.local.json rewritten to
    {"hooks": hooks}, whatever `hooks` is."""
    with open(os.path.join(root, "projects", name, ".claude", "settings.local.json"), "w") as fh:
        json.dump({"hooks": hooks}, fh)
    return root


def guard_cases(tmp):
    good = json.dumps({"_doc": "x", "secret_paths": [{"pattern": "\\.guardkey\\b", "why": "the key"}],
                       "harness_paths": [{"path": "a/b", "why": "w"}]})
    # No profile turns the guard on: one PASS line, as on this machine today.
    off = os.path.join(tmp, "off")
    os.makedirs(os.path.join(off, "config", "profiles"))
    for n, extra in (("a", {"command_guard": False}), ("b", {})):
        put_profile(off, n, dict(extra, project=n, project_path=os.path.join(off, n)))
    rows = smoke(off, "command_guard_smoke")
    want("no profile turns the guard on", (levels(rows), rows[0][1]), (["PASS"], "command guard"))

    rows = smoke(guard_world(tmp, "ok", config=good), "command_guard_smoke")
    want("a guarded profile, entry and config in order", (levels(rows), rows[0][1]), (["PASS"], "guard ok"))
    want("a guarded profile with no config file", levels(smoke(guard_world(tmp, "nocfg"), "command_guard_smoke")), ["PASS"])

    # The negative control of the design: the same world with the entry removed must be a FAIL.
    rows = smoke(guard_world(tmp, "noentry", entry="none"), "command_guard_smoke")
    want("the entry removed", (levels(rows), "settings.local.json" in rows[0][2]), (["FAIL"], True))
    # The canonical group has no matcher (skills.GUARDS), so it sees every tool; behind "Write" the guard
    # never meets Bash. Red on 64fd663: "FAIL a guard behind matcher Write = (['PASS'], False), want (['FAIL'], True)".
    for i, m in enumerate(("Write", "Bash", "Write|Edit|Bash")):
        rows = smoke(guard_world(tmp, "matcher%d" % i, matcher=m), "command_guard_smoke")
        want("a guard behind matcher %s" % m, (levels(rows), "matcher %s" % m in rows[0][2]), (["FAIL"], True))
    # Control: the matcher Claude Code reads as every tool still passes (the sync would rewrite it to none).
    want("a guard behind matcher *", levels(smoke(guard_world(tmp, "matcher_star", matcher="*"), "command_guard_smoke")), ["PASS"])
    want("two guard entries", levels(smoke(guard_world(tmp, "twice", entry="twice"), "command_guard_smoke")), ["FAIL"])
    want("a guard entry with another command", levels(smoke(guard_world(
        tmp, "other", entry="python3 /elsewhere/hooks/guard_tool_use.py"), "command_guard_smoke")), ["FAIL"])
    want("no settings.local.json", levels(smoke(guard_world(tmp, "nofile", entry="missing"), "command_guard_smoke")), ["FAIL"])
    # The canonical command in an entry that cannot block: another type, a timeout that kills it
    # first, or async. _own_guard keeps such an entry, so only the doctor can see it (Codex;
    # before, each was "= ['PASS'], want ['FAIL']").
    for label, extra in BAD_HOOKS:
        rows = smoke(guard_world(tmp, "bad" + label.replace(" ", ""), hook_extra=extra), "command_guard_smoke")
        want("a guard entry with " + label, (levels(rows), "by hand" in rows[0][2]), (["FAIL"], True))
    # Present and canonical, but a guard that lets the canary through, refuses everything, or crashes.
    want("a guard that allows the canary", levels(smoke(guard_world(tmp, "lax", guard="import sys\n"), "command_guard_smoke")), ["FAIL"])
    want("a guard that refuses everything", levels(smoke(guard_world(
        tmp, "strict", guard="import sys\nsys.exit(2)\n"), "command_guard_smoke")), ["FAIL"])
    want("a guard that crashes", levels(smoke(guard_world(tmp, "crash", guard="raise SystemExit('boom')\n"), "command_guard_smoke")), ["FAIL"])
    # The config file: a broken one, an unknown key, a wrong type.
    for i, (label, text) in enumerate((
            ("a config that does not parse", "{nope"), ("a config with an unknown key", '{"deny": []}'),
            ("a config that is not an object", "[]"), ("secret_paths not a list", '{"secret_paths": {}}'),
            ("a secret_paths pattern that is no regex", '{"secret_paths": [{"pattern": "(", "why": "w"}]}'),
            ("a harness_paths entry without a path", '{"harness_paths": [{"why": "w"}]}'))):
        rows = smoke(guard_world(tmp, "cfg%d" % i, config=text), "command_guard_smoke")
        want(label, (levels(rows), "config/guard/cfg%d.json" % i in rows[0][2]), (["FAIL"], True))
    # A profile that declares the guard in its hooks block as well, and a frozen one (nothing is written there).
    both = {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 /x/hooks/guard_tool_use.py"}]}]}
    want("the guard in the hooks block too", levels(smoke(guard_world(tmp, "dup", hooks=both), "command_guard_smoke")), ["FAIL"])
    want("a frozen profile", levels(smoke(guard_world(tmp, "frozen", entry="none", frozen=True), "command_guard_smoke")), ["PASS"])
    # A settings.local.json whose `hooks` is not an object holds no guard entry: a FAIL that says so,
    # never "cannot be read". The worktree row's twin is in wtguard_cases; this one already passed.
    for i, hooks in enumerate(("x", [1], 5)):
        rows = smoke(hooks_world(guard_world(tmp, "hk%d" % i), "hk%d" % i, hooks), "command_guard_smoke")
        want("a settings file whose hooks is %r" % (hooks,), (levels(rows), "holds 0 guard entries" in rows[0][2]),
             (["FAIL"], True))
    # One line per guarded profile, in name order, the good one still a PASS beside the bad one.
    two = guard_world(tmp, "two_a")
    guard_world(tmp, "two_b", entry="none", root=two)
    rows = smoke(two, "command_guard_smoke")
    want("two guarded profiles", [(r[0], r[1]) for r in rows], [("PASS", "guard two_a"), ("FAIL", "guard two_b")])
    # command_guard on and no project (round 10): the profile is left out, and the row names it.
    put_profile(two, "two_np", {"project_path": os.path.join(two, "projects", "two_a"), "command_guard": True})
    rows = smoke(two, "command_guard_smoke")
    want("a guard on and no project", [(r[0], r[1]) for r in rows[-1:]], [("FAIL", "guard two_np")])

    # Through cmd_doctor: the FAIL reaches the printed line and the exit code, with the fix appended,
    # and a check that returns a list prints every line of it.
    root = guard_world(tmp, "viadoctor", entry="none")
    guard_world(tmp, "viadoctor2", root=root)
    with toy(root):
        code, lines, err = doctor([r for r in cli.CHECKS if r[0] == "command guard"])
    first = lines[0] if lines else ""
    want("doctor over a guard with no entry", (code, err, first.startswith("FAIL  guard viadoctor "), "forge sync" in first),
         (1, None, True, True))
    want("doctor prints a line per guarded profile", ([l.split()[:3] for l in lines[:2]], summary(lines)),
         ([["FAIL", "guard", "viadoctor"], ["PASS", "guard", "viadoctor2"]], "SUMMARY: 1 passed, 0 warnings, 1 failures"))


# 7. The worktree guard smoke check (W3 of research/21-para-forge/04-guarda-de-worktrees.md). A
# stand-in for hooks/worktree_guard.py, so this does not wait on that hooks/ commit: it refuses
# (exit 2, the hook's own stderr prefix) a Write outside the payload's cwd, and only when that cwd
# is a real linked worktree (a `.git` file) and WORKTREE_GUARD_SCRATCH is empty. A check that
# builds no worktree, or leaves the hook believing its /tmp toy is scratch, gets 0 and fails.
STUB_WT_GUARD = """import json, os, sys
d = json.load(sys.stdin)
cwd, p = d["cwd"], d["tool_input"]["file_path"]
if os.path.isfile(os.path.join(cwd, ".git")) and os.environ.get("WORKTREE_GUARD_SCRATCH") == "" \\
        and not p.startswith(cwd + os.sep):
    sys.stderr.write("worktree_guard: BLOCKED - outside this worktree\\n")
    sys.exit(2)
"""
WT_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|Bash"


def wtguard_world(tmp, name, entry="canonical", guard=STUB_WT_GUARD, value=True, frozen=False, root=None, path=True,
                  hook_extra=None):
    """A toy ROOT (`root`, or tmp/name) with a stub worktree guard and a profile `name` whose
    worktree_guard is `value`, and whose settings.local.json holds `entry`: "canonical", "none"
    (only another hook), "twice", "nomatcher", "matcher Write", "missing" (no file), or any other
    string, taken as the command behind the canonical matcher."""
    root = root or os.path.join(tmp, name)
    os.makedirs(os.path.join(root, "hooks"), exist_ok=True)
    os.makedirs(os.path.join(root, "config", "profiles"), exist_ok=True)
    project = os.path.join(root, "projects", name)
    os.makedirs(os.path.join(project, ".claude"))
    with open(os.path.join(root, "hooks", "worktree_guard.py"), "w") as fh:
        fh.write(guard)
    prof = {"project": name, "worktree_guard": value}
    if path:
        prof["project_path"] = project
    if frozen:
        prof["frozen"] = True
    put_profile(root, name, prof)
    canonical = "python3 %s --project %s" % (os.path.join(root, "hooks", "worktree_guard.py"), name)
    hook = lambda c: dict({"type": "command", "command": c, "timeout": 10}, **(hook_extra or {}))  # noqa: E731
    group = lambda c, m=WT_MATCHER: dict({"matcher": m} if m else {}, hooks=[hook(c)])  # noqa: E731
    pre = {"canonical": [group(canonical)], "none": [group("python3 /elsewhere/audit.py")],
           "twice": [group(canonical), group(canonical)], "nomatcher": [group(canonical, None)],
           "matcher Write": [group(canonical, "Write")]}.get(entry) or [group(entry)]
    if entry != "missing":
        with open(os.path.join(project, ".claude", "settings.local.json"), "w") as fh:
            json.dump({"hooks": {"PreToolUse": pre}}, fh)
    return root


def wtguard_cases(tmp):
    tmp = os.path.join(tmp, "wt")
    # No profile asks for it: a stranger's legitimate zero, a SKIP that says NOT RUN, NOT ARMED (T9 of
    # docs/portable-design.md; red before: "(['FAIL'], 'worktree guard', True)"). One that asks for it and is frozen
    # is configured and checked by nothing, and stays a FAIL (below, "a frozen profile is not checked").
    off = os.path.join(tmp, "off")
    os.makedirs(os.path.join(off, "config", "profiles"))
    for n, extra in (("a", {"worktree_guard": False}), ("b", {}), ("c", {"worktree_guard": {"on": False}})):
        put_profile(off, n, dict(extra, project=n, project_path=os.path.join(off, n)))
    rows = smoke(off, "worktree_guard_smoke")
    want("worktree guard: no profile turns it on", (levels(rows), rows[0][1], rows[0][2].startswith("NOT RUN, NOT ARMED: ")),
         (["SKIP"], "worktree guard", True))
    # Scoped to a project that does not turn it on, zero is expected: a PASS, as the command guard's.
    want("worktree guard: one project that does not turn it on", levels(smoke(off, "worktree_guard_smoke", "a")), ["PASS"])

    rows = smoke(wtguard_world(tmp, "ok"), "worktree_guard_smoke")
    want("worktree guard: a guarded profile, entry in order", (levels(rows), rows[0][1], "1 guarded" in rows[0][2]),
         (["PASS"], "worktree guard ok", True))
    want("worktree guard: the object form", levels(smoke(wtguard_world(tmp, "obj", value={"write_roots": []}), "worktree_guard_smoke")), ["PASS"])
    # The negative control of the design: the same world with the entry removed is a FAIL.
    rows = smoke(wtguard_world(tmp, "noentry", entry="none"), "worktree_guard_smoke")
    want("worktree guard: the entry removed", (levels(rows), "settings.local.json" in rows[0][2]), (["FAIL"], True))
    for label, entry in (("two entries", "twice"), ("no matcher", "nomatcher"), ("matcher Write", "matcher Write"),
                         ("another command", "python3 /elsewhere/hooks/worktree_guard.py"), ("no file", "missing")):
        want("worktree guard: %s" % label, levels(smoke(wtguard_world(tmp, "e" + label.replace(" ", ""), entry=entry), "worktree_guard_smoke")), ["FAIL"])
    want("worktree guard: no project_path", levels(smoke(wtguard_world(tmp, "nopath", path=False), "worktree_guard_smoke")), ["FAIL"])
    for label, extra in BAD_HOOKS:
        rows = smoke(wtguard_world(tmp, "bad" + label.replace(" ", ""), hook_extra=extra), "worktree_guard_smoke")
        want("worktree guard: an entry with " + label, (levels(rows), "by hand" in rows[0][2]), (["FAIL"], True))
    # Canonical, but a guard that lets the main-checkout write through, refuses everything, or crashes.
    want("worktree guard: a guard that allows everything", levels(smoke(wtguard_world(tmp, "lax", guard="import sys\n"), "worktree_guard_smoke")), ["FAIL"])
    rows = smoke(wtguard_world(tmp, "strict", guard="import sys\nsys.stderr.write('worktree_guard: BLOCKED - all\\n')\nsys.exit(2)\n"), "worktree_guard_smoke")
    want("worktree guard: a guard that refuses everything", (levels(rows), "inside" in rows[0][2]), (["FAIL"], True))
    want("worktree guard: a guard that crashes", levels(smoke(wtguard_world(tmp, "crash", guard="raise SystemExit('boom')\n"), "worktree_guard_smoke")), ["FAIL"])
    # A settings.local.json whose `hooks` is a non-empty list, a string or a number holds no guard entry.
    # Red before the shared reader: "worktree guard: a settings file whose hooks is 'x' = (['FAIL'], False),
    # want (['FAIL'], True)" (the detail read "... cannot be read (AttributeError)").
    for i, hooks in enumerate(("x", [1], 5)):
        rows = smoke(hooks_world(wtguard_world(tmp, "hk%d" % i), "hk%d" % i, hooks), "worktree_guard_smoke")
        want("worktree guard: a settings file whose hooks is %r" % (hooks,),
             (levels(rows), "holds 0 worktree guard entries" in rows[0][2]), (["FAIL"], True))
    # Exit 2 without the hook's refusal: what python3 prints for a script that is not there.
    want("worktree guard: exit 2 without BLOCKED", levels(smoke(wtguard_world(
        tmp, "noblock", guard="import json, sys\nd = json.load(sys.stdin)\nsys.exit(0 if d['cwd'] in d['tool_input']['file_path'] else 2)\n"), "worktree_guard_smoke")), ["FAIL"])
    # Frozen is not checked, so a world with only a frozen profile that asks for the guard is the zero FAIL; "on": false
    # asks for nothing, and is the SKIP.
    rows = smoke(wtguard_world(tmp, "frozen", entry="none", frozen=True), "worktree_guard_smoke")
    want("worktree guard: a frozen profile is not checked", (levels(rows), rows[0][1]), (["FAIL"], "worktree guard"))
    rows = smoke(wtguard_world(tmp, "isoff", entry="none", value={"on": False, "worktree_dirs": []}), "worktree_guard_smoke")
    want("worktree guard: on false is not checked, and asks for nothing", (levels(rows), rows[0][1]), (["SKIP"], "worktree guard"))
    # One line per guarded profile, in name order, each with the count.
    two = wtguard_world(tmp, "w2a")
    wtguard_world(tmp, "w2b", entry="none", root=two)
    rows = smoke(two, "worktree_guard_smoke")
    want("worktree guard: two guarded profiles", [(r[0], r[1], "2 guarded" in r[2]) for r in rows],
         [("PASS", "worktree guard w2a", True), ("FAIL", "worktree guard w2b", True)])
    want("worktree guard: scoped to one of two", [r[1] for r in smoke(two, "worktree_guard_smoke", "w2b")], ["worktree guard w2b"])

    # A guard the profile asked for, in a profile lib.profiles leaves out for its type (round 10): the
    # unscoped row names it and FAILs. It was silently absent, so with "on": "true" the row PASSed.
    # (forge doctor NAME already shows the profile row for it.) Red before: "worktree guard: an on that is a
    # string, beside a good one = [('PASS', 'worktree guard w3ok')], want [..., ('FAIL', 'worktree guard
    # w3bad')]", and the same for a guard on with no project; the command guard's twin: "a guard on and no
    # project = [('FAIL', 'guard two_b')], want [('FAIL', 'guard two_np')]".
    bad = wtguard_world(tmp, "w3ok")
    wtguard_world(tmp, "w3bad", value={"on": "true"}, root=bad)
    rows = smoke(bad, "worktree_guard_smoke")
    want("worktree guard: an on that is a string, beside a good one", [(r[0], r[1]) for r in rows],
         [("PASS", "worktree guard w3ok"), ("FAIL", "worktree guard w3bad")])
    want("worktree guard: the string-on row says why", "worktree_guard.on is not a boolean" in rows[-1][2], True)
    want("worktree guard: scoped to the good one beside it", [r[1] for r in smoke(bad, "worktree_guard_smoke", "w3ok")],
         ["worktree guard w3ok"])
    noproj = wtguard_world(tmp, "w4")
    put_profile(noproj, "w4np", {"project_path": os.path.join(noproj, "projects", "w4"), "worktree_guard": True})
    rows = smoke(noproj, "worktree_guard_smoke")
    want("worktree guard: a guard on and no project", [(r[0], r[1]) for r in rows],
         [("PASS", "worktree guard w4"), ("FAIL", "worktree guard w4np")])
    # Only the guard's own profiles: a profile left out for another field is not this row's business.
    other = wtguard_world(tmp, "w5")
    put_profile(other, "w5x", {"project": "w5x", "project_path": 5})
    want("worktree guard: a profile left out for another field is not a row", [r[1] for r in smoke(other, "worktree_guard_smoke")],
         ["worktree guard w5"])

    # Through cmd_doctor: the FAIL reaches the exit code, with the fix appended; and the row is in
    # forge doctor and forge doctor NAME.
    with toy(two):
        code, lines, err = doctor([r for r in cli.CHECKS if r[0] == "worktree guard"])
        names = [n_ for n_, _, _ in cli.project_checks("w2a", lib.profiles()["w2a"], None)]
    want("worktree guard: through doctor", (code, err, len(lines) > 1 and "forge sync" in lines[1]), (1, None, True))
    want("worktree guard: in forge doctor NAME", "worktree guard" in names, True)


# 5. forge doctor NAME (the owner: "forge doctor <project>" to diagnose one stuck project).
# A whole toy world, because one of its rows runs `forge sync --project NAME` as a subprocess:
# this checkout copied without design/ beside a toy HOME and toy projects (the shape lib.may_write
# lets a toy HOME write), its profiles replaced by toy ones, and an empty fake secrets.json.
# `healthy` is mapped to a Hindsight bank and has an env (so it gets a settings.local.json),
# `clash` holds a project skill named like a global one, `guarded` turns the command guard on with
# no settings.local.json (its smoke check FAILs). The other projects' trouble must not reach
# healthy's lines. A profile with a field of the wrong type is added only for its own case: every
# generator names it with a '!' line, so the sync of any project exits 1 while it is there.
TOY_PROFILES = {
    "healthy": {"servers": [], "env": {"TOY": "1"}},
    "frozen": {"frozen": True},
    "clash": {},
    "guarded": {"command_guard": True},
}


def project_world(tmp):
    """(forge copy, its env, {project: path}). Nothing is synced yet."""
    base = os.path.join(tmp, "project-world")
    root, home = os.path.join(base, "forge"), os.path.join(base, "home")
    sandbox.copy_engine(root)
    sandbox.seed(root)
    profiles = os.path.join(root, "config", "profiles")
    for f in os.listdir(profiles):
        os.remove(os.path.join(profiles, f))
    paths = {}
    for name, extra in TOY_PROFILES.items():
        paths[name] = os.path.join(base, "projects", name)
        os.makedirs(os.path.join(paths[name], ".claude"))
        sandbox.git(paths[name], "init", "-q")
        with open(os.path.join(profiles, name + ".claude.json"), "w") as fh:
            json.dump(dict(extra, project=name, project_path=paths[name]), fh)
    os.makedirs(os.path.join(paths["clash"], ".claude", "skills", "gsd-fast"))
    os.makedirs(os.path.join(root, "skills", "gsd-fast"))  # the global skill it clashes with: a copy_engine copy has no skills/
    # The frozen project's stale file: a dry-run of an unfrozen one would want to rewrite it.
    with open(os.path.join(paths["frozen"], ".claude", "settings.local.json"), "w") as fh:
        json.dump({"env": {"STALE": "1"}}, fh)
    # The layout the generator insists on: config/secrets.json links to credentials/ (a copy is a '!').
    os.makedirs(os.path.join(root, "credentials"))
    with open(os.path.join(root, "credentials", "secrets.json"), "w") as fh:
        json.dump({}, fh)
    os.chmod(os.path.join(root, "credentials", "secrets.json"), 0o600)
    os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(root, "config", "secrets.json"))
    # A bank for the healthy project: the per-project hindsight row (gone since T6) showed it, so a doctor
    # that still printed that row would fail "a healthy project has no hindsight row".
    canon = os.path.join(root, "config", "hindsight-coding-agents.json")
    with open(canon, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["mapPathToBank"][paths["healthy"]] = "toybank"
    with open(canon, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    sandbox.installed_settings(home, root)
    return root, sandbox.bare_env(home, base), paths


NS = []


def forge(root, env, *args):
    """(exit code, output lines) of the toy checkout's bin/forge, in an empty network namespace
    when this machine gives one (sandbox.unshare_ok)."""
    if not NS:
        NS.append(sandbox.UNSHARE if sandbox.unshare_ok()[0] else ())
    r = subprocess.run(list(NS[0]) + [sys.executable, os.path.join(root, "bin", "forge")] + list(args), cwd=root,
                       env=env, capture_output=True, text=True, timeout=300)
    return r.returncode, (r.stdout + r.stderr).splitlines()


def rows_of(lines):
    """{row name: (level, detail)} of lib.report's lines ("%-4s  %-22s %s")."""
    return {l[6:28].strip(): (l[:4].strip(), l[29:]) for l in lines if len(l) > 29 and not l.startswith("SUMMARY")}


def row(rows, name):
    return rows.get(name, ("", ""))


def pending_cases():
    """cli.pending_writes over the generators' own sample lines: each write line counts once, and
    no line of a project that is up to date, or that the generator refuses to change, does."""
    writes = ["   would write overrides -> ~/p/.claude/settings.local.json (untrimmed (pass-through only), env 1)",
              "   codex mcp -> ~/p/.codex/config.toml (0 servers) +gitignore(would add .codex/) (would create)",
              "   codex mcp -> ~/p/.codex/config.toml (2 servers) (would update)",
              "   codex mcp -> ~/p/.codex/config.toml (2 servers) (would chmod 600 config.toml)",
              "   ~/.claude.json -> would write",
              "would chmod 600 ~/.claude.json (it carries resolved secrets)",
              "   codex sees project skills -> ~/p/.agents/skills (2 skill(s), +2)  [dry-run]",
              "  ~ p                    copy:AGENT-SYSTEM.md, SKIP-agents-md(no CLAUDE.md to point at):AGENTS.md"]
    idle = ["MODE: DRY-RUN (no files written; pass --apply to write)",
            "   overrides -> ~/p/.claude/settings.local.json (untrimmed (pass-through only), env 1) (already current)",
            "   codex mcp -> ~/p/.codex/config.toml (0 servers) (already current)",
            "   codex sees project skills -> ~/p/.agents/skills (2 skill(s))",
            "   ~/.claude.json -> already current", "OK.  (dry-run — rerun with --apply after a clean Claude restart)",
            "  = p                    up to date", "  = p                    frozen: nothing written",
            "  ~ p                    SKIP-agents-md(non-forge content):AGENTS.md", "0 change(s) would apply."]
    pending = getattr(cli, "pending_writes", lambda lines: None)
    want("each write line", [pending([l]) for l in writes], [1] * len(writes))
    want("lines that write nothing", [l for l in idle if pending([l]) != 0], [])


def project_cases(tmp):
    root, env, paths = project_world(tmp)
    fix = "-- forge sync --apply --project healthy"

    code, lines = forge(root, env, "doctor", "nosuch")
    first = (lines or [""])[0]
    want("doctor of an unknown project", (code, first.startswith("! "), "unknown project: nosuch" in first), (1, True, True))
    # An empty name (forge doctor "$UNSET") is an unknown project too, never the full doctor. Red on
    # dbc41ed: "FAIL doctor of an empty project name = (1, False, False, 11), want (1, True, True, 1)".
    code, lines = forge(root, env, "doctor", "")
    first = (lines or [""])[0]
    want("doctor of an empty project name", (code, first.startswith("! "), "unknown project: " in first, len(lines)),
         (1, True, True, 1))

    bad = os.path.join(root, "config", "profiles", "bad.claude.json")
    with open(bad, "w") as fh:
        json.dump({"project": "bad", "project_path": os.path.join(root, "..", "projects", "bad"), "frozen": "yes"}, fh)
    code, lines = forge(root, env, "doctor", "bad")
    os.remove(bad)
    rows = rows_of(lines)
    want("doctor of a profile with a wrong type", (code, list(rows), row(rows, "profile")[0],
                                                   "frozen is not a boolean" in row(rows, "profile")[1]),
         (1, ["profile"], "FAIL", True))

    # Never synced: the dry-run would write healthy's files, so the row is a FAIL with its fix.
    code, lines = forge(root, env, "doctor", "healthy")
    generated = row(rows_of(lines), "generated")
    want("a never-synced project", (code, generated[0], generated[1].endswith(fix)), (1, "FAIL", True))

    code, lines = forge(root, env, "sync", "--apply", "--project", "healthy")
    want("the toy apply of healthy", (code, sandbox.tail("\n".join(lines))), (0, sandbox.tail("\n".join(lines))))
    code, lines = forge(root, env, "doctor", "healthy")
    rows = rows_of(lines)
    levels = {k: v[0] for k, v in rows.items()}
    want("a healthy project's rows", levels, {"profile": "PASS", "generated": "PASS", "skill names": "PASS",
                                              "instruction files": "PASS", "command guard": "PASS", "worktree guard": "PASS",
                                              "memory": levels.get("memory", "(none)")})
    want("a healthy project's memory row", "memory" in rows, True)
    want("a healthy project has no hindsight row", "hindsight" in rows, False)
    want("a healthy project's exit code follows its FAILs", code, 1 if "FAIL" in levels.values() else 0)
    want("a healthy project's summary", sum(l.startswith("SUMMARY") for l in lines), 1)

    # The other projects' trouble is theirs: the clash and the broken guard show in their own doctor.
    code, lines = forge(root, env, "doctor", "clash")
    names = row(rows_of(lines), "skill names")
    want("the clashing project's skill names row", (names[0], names[1].startswith("clash:gsd-fast")), ("WARN", True))
    code, lines = forge(root, env, "doctor", "guarded")
    want("the guarded project's guard row", (code, row(rows_of(lines), "guard guarded")[0]), (1, "FAIL"))

    # Nothing to write, but the dry-run exits 1: a server the registry does not have is a '!' line.
    hp = os.path.join(root, "config", "profiles", "healthy.claude.json")
    with open(hp, encoding="utf-8") as fh:
        clean = fh.read()
    with open(hp, "w", encoding="utf-8") as fh:
        json.dump(dict(json.loads(clean), servers=["not-in-registry"]), fh)
    code, lines = forge(root, env, "doctor", "healthy")
    with open(hp, "w", encoding="utf-8") as fh:
        fh.write(clean)
    generated = row(rows_of(lines), "generated")
    want("a dry-run that exits 1 with nothing to write", (generated[0], generated[1].startswith(
        "the dry-run exits 1 with 1 '!' line(s), which forge sync --project healthy shows")), ("FAIL", True))

    # Stale: settings.local.json no longer what the generator writes.
    slp = os.path.join(paths["healthy"], ".claude", "settings.local.json")
    with open(slp, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["env"] = {"STALE": "1"}
    with open(slp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    code, lines = forge(root, env, "doctor", "healthy")
    generated = row(rows_of(lines), "generated")
    want("a stale settings.local.json", (code, generated[0], generated[1].endswith(fix)), (1, "FAIL", True))

    # Frozen: forge writes nothing there, which the row says instead of running the dry-run (whose
    # own frozen line would read as zero writes too), and every other row still runs.
    before = sandbox.manifest(paths["frozen"])
    code, lines = forge(root, env, "doctor", "frozen")
    rows = rows_of(lines)
    want("a frozen project's generated row", rows.get("generated"), ("PASS", "frozen: forge writes nothing"))
    want("a frozen project's profile row says frozen", (row(rows, "profile")[0], row(rows, "profile")[1].endswith(
        "; frozen: forge writes nothing for it")), ("PASS", True))
    want("a frozen project's other rows", [k for k in ("skill names", "command guard", "memory", "hindsight") if k in rows],
         ["skill names", "command guard", "memory"])
    want("a frozen project's instruction files row", row(rows, "instruction files")[0], "SKIP")
    want("a frozen project is left as it was", sandbox.manifest(paths["frozen"]) == before, True)
    # The toy frozen file holds an env its profile does not declare, which an unfrozen run would remove.
    drift_row = row(rows, "frozen drift")
    want("a frozen project's frozen drift row", (drift_row[0], drift_row[1].startswith("frozen: env"),
                                                  "compared 1 frozen profile(s)" in drift_row[1]), ("WARN", True, True))
    want("a frozen project's skill names row", row(rows, "skill names")[0], "SKIP")

    # Exit 1 only on a FAIL: in the toy world the memory row always FAILs (no rendered Hindsight
    # config), so this runs cmd_doctor in-process over one WARN row, the toy profiles and a CHECKS
    # whose only row FAILs (what the default doctor would run instead).
    real = lib.PROFILES, cli.CHECKS, getattr(cli, "project_checks", None)
    lib.PROFILES = os.path.join(root, "config", "profiles")
    cli.CHECKS = [("f", lambda: lib.Result("FAIL", "f", "the default doctor ran"), "")]
    cli.project_checks = lambda name, prof, why: [("w", lambda: lib.Result("WARN", "w", "only a warning"), "")]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.cmd_doctor(argparse.Namespace(project="healthy"))
    finally:
        lib.PROFILES, cli.CHECKS, cli.project_checks = real
    want("doctor NAME with only a WARN", code, 0)


def settings_world(tmp, name, doc):
    """The path of a toy config/forge.json holding `doc`."""
    d = os.path.join(tmp, "settings-" + name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "forge.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


@contextlib.contextmanager
def toy_settings(path):
    """lib.settings() reading the toy file `path`, and the real one again on the way out: lib caches
    the parse by path, and a toy left behind would leak into every later case."""
    real = lib.SETTINGS
    lib.SETTINGS = path
    lib.settings.cache_clear()
    try:
        yield
    finally:
        lib.SETTINGS = real
        lib.settings.cache_clear()


OFF = {"codex": False, "gsd": False, "jev": False, "hindsight": False, "caveman": False}


def lines_of(results):
    return [(r.level, r.detail) for r in (results if isinstance(results, list) else [results])]


def at(seq, i):
    """seq[i], or ("missing",) when the code under test returned fewer lines than it should."""
    return seq[i] if -len(seq) <= i < len(seq) else ("missing",)


def call(fn_name, *args):
    """cli.<fn_name>(*args) as [(level, detail)], or [('raised', ...)] when it is not there or raises."""
    try:
        return lines_of(getattr(cli, fn_name)(*args))
    except Exception as e:
        return [("raised", "%s: %s" % (type(e).__name__, e))]


def extra_cases(tmp):
    """doctor_extra rows join the full doctor; a jev that is off is a SKIP that did not run."""
    extra_row = [r for r in cli.CHECKS if r[0] == "doctor_extra"]
    toy_row = ["toy", ["-c", "print('toy ok')"], "fix toy"]
    bad_row = ["bad", ["-c", "import sys; print('toy broke'); sys.exit(1)"], "fix bad"]
    with toy_settings(settings_world(tmp, "extra", dict(integrations=OFF, doctor_extra=[toy_row, bad_row]))):
        code, lines, err = doctor(extra_row)
        want("a toy doctor_extra row appears", (code, err, [fields(lines, 0), fields(lines, 1)]),
             (1, None, [["PASS", "toy", "toy ok"], ["FAIL", "bad", "toy broke -- fix bad"]]))
        code, lines, err = doctor([])
        want("a doctor over other rows runs none of them", (code, summary(lines)), (0, "SUMMARY: 0 passed, 0 warnings, 0 failures"))
    with toy_settings(settings_world(tmp, "extra-none", dict(integrations=OFF))):
        code, lines, err = doctor(extra_row)
        want("no doctor_extra key adds nothing", (code, err, lines), (0, None, ["SUMMARY: 0 passed, 0 warnings, 0 failures"]))
    with toy_settings(settings_world(tmp, "extra-bad", dict(integrations=OFF, doctor_extra=[["only-a-name"], "x"]))):
        code, lines, err = doctor(extra_row)
        want("a malformed doctor_extra row is a FAIL", (code, err, [fields(lines, 0)[:2], fields(lines, 1)[:2]]),
             (1, None, [["FAIL", "doctor_extra"], ["FAIL", "doctor_extra"]]))
        want("a malformed doctor_extra row names its place", "row 0 is not [name, [argv...], fix]" in (lines + ["", ""])[0]
             and "row 1 is not" in (lines + ["", ""])[1], True)

    # jev off: the row is not run. The toy command exits 1, so a run would be a FAIL.
    jev_row = [("jev", ["-c", "import sys; print('ran'); sys.exit(1)"], "fix jev")]
    with toy_settings(settings_world(tmp, "jev-off", dict(integrations=dict(OFF)))):
        code, lines, err = doctor(jev_row)
        level, name, detail = fields(lines, 0)
        want("jev off: the row is a SKIP that was not run", (code, level, name, "ran" in detail, "NOT RUN, NOT ARMED: jev is off" in detail),
             (0, "SKIP", "jev", False, True))
        want("jev off: the SKIP says how to turn it off for good", "setup.py --uninstall --apply" in detail, True)
        want("jev off: a SKIP carries no fix", "fix jev" in detail, False)
        want("jev off: a SKIP is not in the summary's counts", summary(lines), "SUMMARY: 0 passed, 0 warnings, 0 failures")
    with toy_settings(settings_world(tmp, "jev-on", dict(integrations=dict(OFF, jev=True)))):
        code, lines, err = doctor(jev_row)
        want("control, jev on: the same row runs", (code, fields(lines, 0)), (1, ["FAIL", "jev", "ran -- fix jev"]))


def integrations_cases(tmp):
    """The `integrations` row: integrations, then the scripts the user_hooks rows name."""
    scripts = os.path.join(tmp, "integ-scripts")
    os.makedirs(scripts)
    present = os.path.join(scripts, "present.py")
    with open(present, "w") as fh:
        fh.write("pass\n")
    missing = os.path.join(scripts, "missing.py")

    def hook(script, marker, on=None, command=None):
        row = {"event": "UserPromptSubmit", "command": command or "python3 " + script, "timeout": 10, "marker": marker,
               "matcher": None, "agents": ["claude"]}
        if on is not None:
            row["on"] = on
        return row

    def run(name, integrations, user_hooks, root=None, **extra):
        with toy_settings(settings_world(tmp, name, dict(integrations=integrations, user_hooks=user_hooks, **extra))):
            if root:
                with toy(root):
                    return call("integrations_row")
            return call("integrations_row")

    got = run("hook-missing", OFF, [hook(missing, "gone.py")])
    want("a user_hooks row naming a missing script FAILs", [l for l in got if l[0] == "FAIL"],
         [("FAIL", 'user_hooks row gone.py (UserPromptSubmit): %s does not exist, so the hook cannot start'
           ' -- restore it, or set "on": false on the row' % missing)])
    want("a missing script is a checked one: the closing line counts it", at(got, -1), ("PASS", "checked 1: 0 integration(s) on, 1 user_hooks script(s)"))
    got = run("hook-present", OFF, [hook(present, "here.py")])
    want("control: the same row naming a script that exists PASSes", got,
         [("SKIP", "NOT RUN, NOT ARMED: codex is off in config/forge.json"), ("SKIP", "NOT RUN, NOT ARMED: gsd is off in config/forge.json"),
          ("SKIP", "NOT RUN, NOT ARMED: jev is off in config/forge.json"), ("SKIP", "NOT RUN, NOT ARMED: hindsight is off in config/forge.json"),
          ("SKIP", "NOT RUN, NOT ARMED: caveman is off in config/forge.json"),
          ("PASS", "user_hooks row here.py (UserPromptSubmit): %s is there" % present),
          ("PASS", "checked 1: 0 integration(s) on, 1 user_hooks script(s)")])
    got = run("hook-off", OFF, [hook(missing, "gone.py", on=False), hook(present, "here.py")])
    want("a row with \"on\": false is a SKIP, its missing script is not a FAIL",
         ([l for l in got if "gone.py" in l[1]], [l[0] for l in got].count("FAIL")),
         ([("SKIP", 'NOT RUN, NOT ARMED: user_hooks row gone.py is "on": false in config/forge.json')], 0))
    got = run("hook-noscript", OFF, [hook(None, "echo", command="echo hello"), hook(present, "here.py")])
    want("a command that names no script is not a line", [l for l in got if "echo" in l[1]], [])
    got = run("hook-two", OFF, [hook(None, "two.py", command="python3 -u %s --flag %s" % (present, missing))])
    want("every script a command names is checked, options are not", [l for l in got if l[0] in ("PASS", "FAIL")],
         [("PASS", "user_hooks row two.py (UserPromptSubmit): %s is there" % present),
          ("FAIL", 'user_hooks row two.py (UserPromptSubmit): %s does not exist, so the hook cannot start'
           ' -- restore it, or set "on": false on the row' % missing),
          ("PASS", "checked 2: 0 integration(s) on, 2 user_hooks script(s)")])
    # Through the doctor: a FAIL line, exit 1; and not a FAIL line, exit 0.
    with toy_settings(settings_world(tmp, "hook-through", dict(integrations=OFF, user_hooks=[hook(missing, "gone.py")]))):
        code, lines, err = doctor([r for r in cli.CHECKS if r[0] == "integrations"])
        want("through the doctor: a missing hook script exits 1, with no fix suffix", (code, err, "-- python3" in " ".join(lines),
                                                                                    lines[0].startswith("SKIP")), (1, None, False, True))
    # Nothing configured (everything off, no user_hooks row) is a stranger's legitimate zero: a SKIP (T9 of
    # docs/portable-design.md; red before: "('FAIL', 'checked 0: every integration is off ...')"). Fail at 0
    # (non-negotiable 7) stays where something is configured: a row that names no script, nothing to check it by.
    got = run("zero", OFF, [])
    want("an integrations row with nothing configured is a SKIP", at(got, -1), (
        "SKIP", "NOT RUN, NOT ARMED: every integration is off in config/forge.json and no user_hooks row is configured, so there is nothing to check"))
    got = run("zero-configured", OFF, [hook(None, "echo", command="echo hello")])
    want("an integrations row that checked nothing, with a user_hooks row configured, FAILs", at(got, -1), (
        "FAIL", "checked 0: every integration is off in config/forge.json and no user_hooks row names a script, so this row proved nothing"))
    # Integrations that are on and what they need.
    real_path = os.environ.get("PATH", "")
    empty = os.path.join(tmp, "integ-empty-path")
    os.makedirs(empty)
    os.environ["PATH"] = empty
    try:
        got = run("codex-gone", dict(OFF, codex=True), [])
        want("codex on and not on PATH", at(got, 0), ("FAIL", "codex is on in config/forge.json but not on PATH -- install it or set integrations.codex false"))
        got = run("gsd-gone", dict(OFF, gsd=True), [], gsd_patches=True)
        want("gsd on, patched, and no npm on PATH", at(got, 1), ("FAIL", "gsd is on in config/forge.json but npm is not on PATH -- install node or set integrations.gsd false"))
        # GSD unpatched comes from pnpm dlx, so pnpm is what it needs. Red before:
        # "gsd on, unpatched, and no pnpm on PATH = ('FAIL', 'gsd is on in config/forge.json but npm is not on PATH -- ...'), want
        # ('FAIL', 'gsd is on in config/forge.json but pnpm is not on PATH -- install pnpm or set integrations.gsd false')".
        for label, extra in (("gsd_patches false", dict(gsd_patches=False)), ("gsd_patches absent", {})):
            got = run("gsd-gone-" + label.replace(" ", "-"), dict(OFF, gsd=True), [], **extra)
            want("gsd on, unpatched (%s), and no pnpm on PATH" % label, at(got, 1),
                 ("FAIL", "gsd is on in config/forge.json but pnpm is not on PATH -- install pnpm or set integrations.gsd false"))
    finally:
        os.environ["PATH"] = real_path
    fake_bin = os.path.join(tmp, "integ-bin")
    os.makedirs(fake_bin)
    for tool in ("codex", "npm", "pnpm"):
        with open(os.path.join(fake_bin, tool), "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(os.path.join(fake_bin, tool), 0o755)
    os.environ["PATH"] = fake_bin
    try:
        got = run("codex-here", dict(OFF, codex=True, gsd=True), [], gsd_patches=True)
        want("control: codex and gsd (patched) on, found on PATH", got[:2], [("PASS", "codex is on, codex found on PATH"),
                                                                             ("PASS", "gsd is on, npm found on PATH")])
        got = run("pnpm-here", dict(OFF, gsd=True), [], gsd_patches=False)
        want("control: gsd on, unpatched, found on PATH", at(got, 1), ("PASS", "gsd is on, pnpm found on PATH"))
    finally:
        os.environ["PATH"] = real_path
    world = os.path.join(tmp, "integ-jev-world")
    os.makedirs(world)
    got = run("jev-gone", dict(OFF, jev=True), [], root=world)
    want("jev on and skills/jev missing", at(got, 2), ("FAIL", "jev is on but skills/jev is missing"))
    os.makedirs(os.path.join(world, "skills", "jev"))
    got = run("jev-here", dict(OFF, jev=True), [], root=world)
    want("control: jev on and skills/jev there", at(got, 2), ("PASS", "jev is on, skills/jev is there"))
    got = run("quiet", dict(OFF, hindsight=True, caveman=True), [])
    want("hindsight and caveman on need nothing here", [l for l in got if l[0] != "SKIP"], [
        ("PASS", "hindsight is on, no dependency checked here"), ("PASS", "caveman is on, no dependency checked here"),
        ("PASS", "checked 2: 2 integration(s) on, 0 user_hooks script(s)")])
    # A hook row that is not an object: the generator exits on it, the doctor says so as a FAIL.
    with toy_settings(settings_world(tmp, "hook-garbage", dict(integrations=OFF, user_hooks=["nope"]))):
        got = call("integrations_row")
        want("a user_hooks row forge.hooks cannot read is a FAIL, not an exit", [l[0] for l in got if "could not read them" in l[1]], ["FAIL"])


def codex_hooks_cases(tmp):
    """The `codex hooks` row: Codex gets no hook from forge, so ~/.codex/hooks.json holding a command forge
    wrote is a FAIL naming the fix. Red before: every case on "AttributeError: module 'forge.cli' has no
    attribute 'codex_hooks_row'". Negative control: with the check made to find nothing (the row returning
    PASS whatever the file holds) "a forge entry in the file" = [('PASS', ...)], want a FAIL."""
    target = os.path.join(tmp, "codex-hooks", "hooks.json")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    real = hooks.CODEX_HOOKS
    hooks.CODEX_HOOKS = target
    forge_cmd = "python3 %s/caveman_house_rules.py" % hooks.HOOK_DIR

    def put(doc):
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))

    def entry(cmd):
        return {"hooks": [{"type": "command", "command": cmd, "timeout": 5}]}
    try:
        on = dict(OFF, codex=True)
        with toy_settings(settings_world(tmp, "codex-hooks-on", dict(integrations=on))):
            want("the row is registered", {n: c for n, c, _ in cli.CHECKS}.get("codex hooks") is getattr(cli, "codex_hooks_row", 0), True)
            if os.path.exists(target):
                os.remove(target)
            want("no hooks.json: PASS, and says there is none", call("codex_hooks_row"),
                 [("PASS", "%s is not there, so forge left no hook in it" % lib.short(target))])
            put({"hooks": {"Stop": [entry("node /opt/herdr/notify.js")]}})
            want("a file with only a foreign entry: PASS, and says how many it looked at", call("codex_hooks_row"),
                 [("PASS", "1 entry in %s, none is forge's" % lib.short(target))])
            put({"hooks": {"SessionStart": [entry(forge_cmd)], "Stop": [entry("node /opt/herdr/notify.js")]}})
            want("a forge entry in the file: FAIL, naming the event and the command", call("codex_hooks_row"),
                 [("FAIL", "%s still holds 1 hook(s) forge wrote: SessionStart %s" % (lib.short(target), forge_cmd))])
            put({"hooks": {"SessionStart": [entry("python3 /elsewhere/caveman_house_rules.py")]}})
            want("the same script under another path is not forge's: PASS", [l[0] for l in call("codex_hooks_row")], ["PASS"])
            put("{bad")
            want("a file that does not parse: FAIL", [l[0] for l in call("codex_hooks_row")], ["FAIL"])
            put({"hooks": {"SessionStart": ["x", entry("node /opt/herdr/notify.js")]}})
            want("a file with an entry of the wrong shape: FAIL, never a PASS over what could not be read",
                 [l[0] for l in call("codex_hooks_row")], ["FAIL"])
        with toy_settings(settings_world(tmp, "codex-hooks-off", dict(integrations=OFF))):
            put({"hooks": {"SessionStart": [entry(forge_cmd)]}})
            want("codex off: a SKIP that did not look", call("codex_hooks_row"),
                 [("SKIP", "NOT RUN, NOT ARMED: codex is off in config/forge.json")])
    finally:
        hooks.CODEX_HOOKS = real


def skip_cases(tmp):
    """instruction_files_skip, session_wait and the gsd step, each read from the toy file."""
    base = inst_world(tmp, "skipcfg", {"skipme": {"CLAUDE.md": "x\n<!-- BEGIN:other-tool -->\n"}})
    with toy_settings(settings_world(tmp, "skip-listed", dict(integrations=OFF, instruction_files_skip=["skipme"]))):
        got = inst(base, "skipme")
        want("a project the config skips", at(got, 0)[0], "SKIP")
    with toy_settings(settings_world(tmp, "skip-empty", dict(integrations=OFF, instruction_files_skip=[]))):
        want("a project the config does not skip", inst(base, "skipme")[0][0], "WARN")
    with toy_settings(settings_world(tmp, "skip-absent", dict(integrations=OFF))):
        want("no instruction_files_skip key skips nothing", inst(base, "skipme")[0][0], "WARN")

    wait = {"project": "toyproj", "health": "http://127.0.0.1:1/health", "unit": "toy-unit"}
    with toy_settings(settings_world(tmp, "wait-absent", dict(integrations=dict(OFF, hindsight=True)))):
        want("session_wait with the key absent", getattr(cli, "session_wait", lambda: "no cli.session_wait")(), None)
    with toy_settings(settings_world(tmp, "wait-off", dict(integrations=OFF, session_wait=wait))):
        want("session_wait with hindsight off", getattr(cli, "session_wait", lambda: "no cli.session_wait")(), None)
    with toy_settings(settings_world(tmp, "wait-on", dict(integrations=dict(OFF, hindsight=True), session_wait=wait))):
        want("session_wait with hindsight on", getattr(cli, "session_wait", lambda: "no cli.session_wait")(), wait)
        want("the unit comes from the config", getattr(cli, "memory_unit", lambda: "no cli.memory_unit")(), "toy-unit")

        def session(project):
            """What a session start in `project` prints, with the sync steps, lock and resolver stubbed out."""
            saved = (cli.SYNC, cli.MEMORY_WAIT, cli.MEMORY_POLL, cli.unit_state, lib.resolve_project, lib.profiles, lib.lock)
            cli.SYNC, cli.MEMORY_WAIT, cli.MEMORY_POLL, cli.unit_state = [], 0.3, 0.1, lambda: "activating"
            lib.resolve_project, lib.profiles = (lambda path: project), (lambda skipped=None: {project: {}})
            lib.lock = lambda timeout=20: contextlib.nullcontext()
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    cli.cmd_session_start(None)
            finally:
                cli.SYNC, cli.MEMORY_WAIT, cli.MEMORY_POLL, cli.unit_state, lib.resolve_project, lib.profiles, lib.lock = saved
            return json.loads(out.getvalue())["systemMessage"] if out.getvalue().strip() else ""
        msg = session("toyproj")
        want("a session in the configured project waits", ("memory is starting (toy-unit: activating" in msg), True)
        want("another project is not special", session("otherproj"), "")
    with toy_settings(settings_world(tmp, "wait-missing", dict(integrations=dict(OFF, hindsight=True)))):
        os.remove(lib.SETTINGS)
        lib.settings.cache_clear()
        # A session start exits 0 whatever happens: lib.settings() exits on a missing file.
        saved = (cli.SYNC, lib.resolve_project, lib.profiles, lib.lock)
        cli.SYNC, lib.resolve_project, lib.profiles = [], (lambda path: "p"), (lambda skipped=None: {"p": {}})
        lib.lock = lambda timeout=20: contextlib.nullcontext()
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = cli.cmd_session_start(None)
        except BaseException as e:
            code = "raised %s" % type(e).__name__
        finally:
            cli.SYNC, lib.resolve_project, lib.profiles, lib.lock = saved
        want("a session start with no config/forge.json still exits 0, and says why", (code, "config/forge.json missing" in out.getvalue()), (0, True))

    # forge sync: a step whose integration is off is said, not run.
    root = os.path.join(tmp, "sync-world")
    os.makedirs(os.path.join(root, "scripts"))
    marker = os.path.join(root, "ran.txt")
    with open(os.path.join(root, "scripts", "step.py"), "w") as fh:
        fh.write("open(%r, 'a').write('x')\n" % marker)

    def sync(integrations):
        saved = cli.SYNC
        cli.SYNC = [("gsd runtime", "scripts/step.py", None, "--apply", True)]
        out = io.StringIO()
        try:
            with toy_settings(settings_world(tmp, "sync-%s" % integrations["gsd"], dict(integrations=integrations))), toy(root):
                with contextlib.redirect_stdout(out):
                    code = cli.cmd_sync(argparse.Namespace(apply=False, project=None, all=False))
        finally:
            cli.SYNC = saved
        return code, out.getvalue()
    code, out = sync(dict(OFF))
    want("gsd off: forge sync says NOT RUN", (code, "== forge: gsd runtime == NOT RUN, NOT ARMED (gsd off)" in out), (0, True))
    want("gsd off: the step did not run", os.path.exists(marker), False)
    code, out = sync(dict(OFF, gsd=True))
    want("control, gsd on: the step runs", (code, os.path.exists(marker), "NOT RUN" in out), (0, True, False))


def test_cases(tmp):
    """forge test lists the engine's history and, when it exists, the data history over the same tree."""
    def toy_repo(name, engine, data=None, broken_data=False):
        d = os.path.join(tmp, "histories", name)
        os.makedirs(d)
        sandbox.git(d, "init", "-q")
        for rel in engine:
            with open(os.path.join(d, rel), "w") as fh:
                fh.write("pass\n")
            sandbox.git(d, "add", rel)
        if data or broken_data:
            dg = os.path.join(d, ".forge-data.git")
            if broken_data:
                os.makedirs(dg)
            else:
                subprocess.run(["git", "init", "-q", "--bare", dg], check=True)
                for rel in data:
                    with open(os.path.join(d, rel), "w") as fh:
                        fh.write("pass\n")
                    subprocess.run(["git", "--git-dir", dg, "--work-tree", d, "-c", "core.hooksPath=/dev/null", "add", rel], check=True)
        return d

    def forge_test(d):
        out, real = io.StringIO(), lib.ROOT
        lib.ROOT = d
        try:
            with contextlib.redirect_stdout(out):
                code = cli.cmd_test(None)
        finally:
            lib.ROOT = real
        return code, out.getvalue()
    code, out = forge_test(toy_repo("one", ["test_a.py"]))
    want("control: one history (before the split) is no failure", (code, "SUMMARY: 1 passed, 0 warnings, 0 failures" in out), (0, True))
    code, out = forge_test(toy_repo("two", ["test_a.py"], ["test_b.py"]))
    want("forge test lists the data history's tests", (code, "PASS  test_a.py" in out, "PASS  test_b.py" in out,
                                                       "SUMMARY: 2 passed, 0 warnings, 0 failures" in out), (0, True, True, True))
    code, out = forge_test(toy_repo("broken", ["test_a.py"], broken_data=True))
    want("a data history git cannot read is a FAIL that names it", (code, "FAIL  git ls-files (data history)" in out), (1, True))


def main():
    tmp = sandbox.mkdtemp("doctor-test-")
    keep_cases(tmp)
    row_cases()
    toy_cases(tmp)
    clash_cases(tmp)
    drift_cases(tmp)
    instruction_cases(tmp)
    guard_cases(tmp)
    wtguard_cases(tmp)
    pending_cases()
    extra_cases(tmp)
    integrations_cases(tmp)
    codex_hooks_cases(tmp)
    skip_cases(tmp)
    test_cases(tmp)
    project_cases(tmp)
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
