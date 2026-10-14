#!/usr/bin/env python3
"""T5 of docs/portable-design.md: the call sites outside forge/hooks.py read config/forge.json.
Codex off writes no `.codex/`, no `.agents/` links and no ignore line, and relinks no
$CODEX_HOME/skills; Hindsight off runs neither its config writer nor its runtime check, and
memory_doctor does not check what is off; relink_skills with no `skills/` or with none in it says
SKIP and links nothing; a repo-owned project with Codex on gets its ignore line in
.git/info/exclude instead of a refusal and exit 1; MCPORTER_CONFIG in a project's Codex config comes
from forge.json's skill_keep.common_env, and is not written when the file has none.

The generator runs in-process against a toy HOME and a toy config/ (test_sync_agent_config.py's
way: HOME is swapped before the import, everything that reaches systemd or the Hindsight runtime is
stubbed); relink_skills.py and memory_doctor.py run as scripts from a toy root that carries its own
config/forge.json. Nothing real is written.

Seen failing on 03e63d8 (every gate absent; this file run as it is), 21 of 34 checks red:
  codex off: no `.codex/` -- ['config.toml'] was written in the project
  codex off: no `.agents/` links -- .agents/ was created: ['skills']
  codex off: no ignore line -- .gitignore was created holding ['.codex/', '.agents/']
  codex off: the run says NOT RUN, NOT ARMED -- the run printed "codex mcp -> ... +gitignore(created)"
  hindsight off: write_hindsight_config and check_hindsight_runtime are not called -- called [...,
    'write_hindsight_config', 'check_hindsight_runtime']
  hindsight off: the run says NOT RUN, NOT ARMED -- it printed "   hindsight config (stub)"
  repo-owned, codex on: exit 0 -- exit 1, "   ! codex mcp -> <toy>/.codex/config.toml NOT written
    !not-git-ignored(SKIPPED: repo-owned .gitignore does not ignore .codex/)" (the same for the dry-run,
    the second run, a project in a subdirectory of a larger repository and one in a linked worktree)
  repo-owned, codex on: .git/info/exclude holds `.codex/` and `.agents/` -- it held only git's template comments
  MCPORTER_CONFIG comes from skill_keep.common_env -- set to <HOME>/.config/mcporter/mcporter.json, the
    hard-coded path, not <HOME>/toy/mcporter.json; and with no common_env it was still written
  relink_skills, no skills/ and empty skills/: the SKIP line -- exit 0, '' (silent); with an empty skills/
    both ~/.claude/skills and ~/.codex/skills were created
  relink_skills, codex off -- ~/.codex/skills was made: 'relink_skills: 1 skills | 2 linked, 0 pruned'
  memory_doctor, codex and hindsight off -- shown {'codex-trust': True, 'codex-untrusted': True,
    'hindsight-config': True}, exit 1: "FAIL machine/hindsight-config: missing <HOME>/.hindsight/coding-agent.json"
Negative controls on the finished code, each put back from a copy of the file (the checks that went red):
  codex gate removed in sync.py -- 4; hindsight gate removed -- 2; the exclude fallback removed -- 7
  exclude line not anchored to the project's directory -- 5 (the nested and the second-run ones among them);
  the exclude-is-a-symlink refusal removed -- 1 (the line was written through the link);
  `--git-common-dir` replaced by `--git-dir` -- 1 (the linked worktree); MCPORTER_CONFIG hard-coded again -- 2;
  relink_skills with the codex target always on -- 1; its SKIP removed -- 4; memory_doctor's codex gate
  removed -- 2; its hindsight gate removed -- 2.
Controls that pass on 03e63d8 as well, so the red ones are not an artefact of the harness: codex on writes
`.codex/config.toml`, the `.agents/skills/s1` link and both lines into the project's own .gitignore (and
nothing into exclude); hindsight on calls both functions; relink_skills with codex on links both mirrors;
memory_doctor with both on runs the codex and hindsight checks and fails on the missing rendered config;
a project whose .git/info/exclude is a symlink is still refused with `!not-git-ignored` and exit 1; this
toy forge.json holding the hard-coded MCPORTER_CONFIG path gives it back.
Not here: the byte-identity of the real generated files (gate.py)."""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("integration-sites-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, sandbox.FORGE)
from forge import lib  # noqa: E402
# hooks reads the settings file when it is imported, and this checkout's config/forge.json is private
# data a stranger's copy lacks (red there before, M1: "! config/forge.json missing -- run bin/forge
# init" at the import). A toy file with every integration off, and no jev, whose setup.py is private.
lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
from forge import hooks, memory, sync  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"

failures, n_cases = [], [0]
called = []


def check(label, ok, detail=""):
    n_cases[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))


def stub(module, name, result):
    def f(*args):
        called.append(name)
        return result
    setattr(module, name, f)


# Everything that reaches systemd, VS Code, ~/.claude/settings.json, ~/.codex or the Hindsight runtime
# is stubbed; the two Hindsight stubs say whether they ran, which is what the gate is about.
stub(hooks, "write_jev_proxy", ("   jev proxy (stub)", False))
stub(hooks, "write_jev_status_extension", "   jev extension (stub)")
stub(hooks, "write_user_settings", "   user settings (stub)")
stub(hooks, "write_codex_hooks", "   codex hooks (stub)")
stub(memory, "write_hindsight_config", "   hindsight config (stub)")
stub(memory, "check_hindsight_runtime", None)

_n = [0]


def forge_json(integrations, **top):
    """A toy config/forge.json, lib pointed at it; returns its path. Codex and Hindsight are what the
    tests switch, so a name not given is off. `codex_harness` is true unless `top` says otherwise: this
    suite is about where Codex's files go, and the switch has its own suite (test_codex_harness.py)."""
    _n[0] += 1
    doc = dict({"integrations": dict({k: False for k in lib.INTEGRATIONS}, **integrations)}, **dict({"codex_harness": True}, **top))
    path = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()
    return path


def seed(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def repo(d):
    os.makedirs(d, exist_ok=True)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)


def lines_of(path):
    return read(path).splitlines() if os.path.exists(path) else None


def generate(name, profile, apply=True, globals_=False, prepare=None):
    """One agent_config run over a toy config/ holding the one project `name` (its directory is
    <TOY>/<name>/projects/p). Returns (exit code, output, the project's directory). `prepare(dir)`
    makes the project before the run."""
    base = os.path.join(TOY, name)
    cfg, pdir = os.path.join(base, "config"), os.path.join(base, "config", "profiles")
    project = os.path.join(base, "projects", "p")
    os.makedirs(pdir)
    seed(os.path.join(cfg, "mcp-registry.json"), '{"servers": {}}')
    seed(os.path.join(base, "secrets.json"), "{}")
    os.symlink(os.path.join(base, "secrets.json"), os.path.join(cfg, "secrets.json"))
    seed(os.path.join(cfg, "project-relocations.json"), '{"relocations": []}')
    os.makedirs(project, exist_ok=True)
    if prepare:
        prepare(project)
    prof = dict({"project": "p", "servers": [], "project_path": project}, **profile)
    seed(os.path.join(pdir, "p.claude.json"), json.dumps(prof))
    sync.CFG, lib.PROFILES = cfg, pdir
    if not os.path.realpath(project).startswith(TOY + os.sep):
        sys.exit("FENCE: %s is outside the toy world -- nothing run" % project)
    ctx = lib.Ctx(apply, None, globals_)
    lib.context = lambda argv: ctx
    del called[:]
    out, code = io.StringIO(), 0
    with contextlib.redirect_stdout(out):
        try:
            code = sync.agent_config([])
        except SystemExit as e:
            code = e.code
        except Exception as e:  # a crash is a result too
            code = "raised %s: %s" % (type(e).__name__, e)
    return code, out.getvalue(), project


def mcporter_of(project):
    """(the config's text, the MCPORTER_CONFIG it sets or None) for a project's .codex/config.toml."""
    p = os.path.join(project, ".codex", "config.toml")
    text = read(p) if os.path.exists(p) else ""
    return text, tomllib.loads(text).get("shell_environment_policy", {}).get("set", {}).get("MCPORTER_CONFIG")


def skill(project):
    seed(os.path.join(project, ".claude", "skills", "s1", "SKILL.md"), "x")


# 1. Codex off: nothing under .codex/ or .agents/, no ignore line, and the run says why. Codex on, the
# same project, is the control: the same assertions would pass vacuously on a run that wrote nothing.
forge_json({"codex": False, "hindsight": True})
code, out, d = generate("codex-off", {}, prepare=lambda p: (repo(p), skill(p)))
check("codex off: exit 0", code == 0, "exit %r\n%s" % (code, out))
check("codex off: no `.codex/`", not os.path.lexists(os.path.join(d, ".codex")),
      "%r was written in the project" % os.listdir(os.path.join(d, ".codex")) if os.path.isdir(os.path.join(d, ".codex")) else "")
check("codex off: no `.agents/` links", not os.path.lexists(os.path.join(d, ".agents")),
      ".agents/ was created: %r" % (os.listdir(os.path.join(d, ".agents")) if os.path.isdir(os.path.join(d, ".agents")) else None))
check("codex off: no ignore line", not os.path.exists(os.path.join(d, ".gitignore")),
      ".gitignore was created holding %r" % (lines_of(os.path.join(d, ".gitignore")),))
check("codex off: the run says NOT RUN, NOT ARMED",
      any("NOT RUN, NOT ARMED" in l and "codex" in l for l in out.splitlines()), "output:\n%s" % out)

forge_json({"codex": True, "hindsight": True})
code, out, d = generate("codex-on", {}, prepare=lambda p: (repo(p), skill(p)))
check("control, codex on: `.codex/config.toml` and the `.agents/skills/s1` link are written",
      os.path.isfile(os.path.join(d, ".codex", "config.toml")) and os.path.islink(os.path.join(d, ".agents", "skills", "s1")),
      "exit %r\n%s" % (code, out))
check("control, codex on: the project's .gitignore carries both lines",
      lines_of(os.path.join(d, ".gitignore")) == [".codex/", ".agents/"], "%r" % (lines_of(os.path.join(d, ".gitignore")),))
check("control, codex on: not repo-owned, the line goes to .gitignore and not to exclude",
      "codex/" not in read(os.path.join(d, ".git", "info", "exclude")), read(os.path.join(d, ".git", "info", "exclude")))

# 2. Hindsight off: neither its config writer nor its runtime check runs, and the section says so.
forge_json({"codex": False, "hindsight": False})
code, out, _ = generate("hs-off", {}, globals_=True, prepare=repo)
check("hindsight off: write_hindsight_config and check_hindsight_runtime are not called",
      "write_hindsight_config" not in called and "check_hindsight_runtime" not in called, "called %r" % (called,))
check("hindsight off: the run says NOT RUN, NOT ARMED",
      any("NOT RUN, NOT ARMED" in l and "hindsight" in l for l in out.splitlines()), "output:\n%s" % out)
check("hindsight off: exit 0", code == 0, "exit %r\n%s" % (code, out))
forge_json({"codex": False, "hindsight": True})
code, out, _ = generate("hs-on", {}, globals_=True, prepare=repo)
check("control, hindsight on: both are called",
      "write_hindsight_config" in called and "check_hindsight_runtime" in called, "called %r" % (called,))

# 3. A repo-owned project (writes_tracked_files false) with Codex on: the line goes to
# .git/info/exclude, the repo's own .gitignore is not touched, and the run exits 0.
forge_json({"codex": True})
OWN = {"writes_tracked_files": False}


def owned(project):
    repo(project)
    seed(os.path.join(project, ".gitignore"), "node_modules/\n")
    skill(project)


code, out, d = generate("owned-dry", OWN, apply=False, prepare=owned)
check("repo-owned, dry-run: exit 0 and nothing written",
      code == 0 and "+exclude(would add /.codex/)" in out and not os.path.lexists(os.path.join(d, ".codex"))
      and read(os.path.join(d, ".git", "info", "exclude")).count("codex") == 0,
      "exit %r\n%s" % (code, out))
code, out, d = generate("owned", OWN, prepare=owned)
ex = os.path.join(d, ".git", "info", "exclude")
check("repo-owned, codex on: exit 0", code == 0, "exit %r\n%s" % (code, out))
check("repo-owned, codex on: .git/info/exclude holds `.codex/` and `.agents/`, anchored",
      "/.codex/" in read(ex).splitlines() and "/.agents/" in read(ex).splitlines(), "exclude holds %r" % (lines_of(ex),))
check("repo-owned, codex on: the project's own .gitignore is untouched",
      read(os.path.join(d, ".gitignore")) == "node_modules/\n", "%r" % read(os.path.join(d, ".gitignore")))
check("repo-owned, codex on: the config and the link are written, and git ignores both",
      os.path.isfile(os.path.join(d, ".codex", "config.toml")) and os.path.islink(os.path.join(d, ".agents", "skills", "s1"))
      and lib.git_ignores(d, ".codex") and lib.git_ignores(d, ".agents"), "output:\n%s" % out)
# the same run again, over the same world: one line each
ctx_out = io.StringIO()
with contextlib.redirect_stdout(ctx_out):
    code = sync.agent_config([])
check("repo-owned, second run: exit 0 and one line each",
      code == 0 and read(ex).splitlines().count("/.codex/") == 1 and read(ex).splitlines().count("/.agents/") == 1,
      "exit %r, exclude %r\n%s" % (code, lines_of(ex), ctx_out.getvalue()))


def nested(project):
    # The project is a directory of a larger repository: the line must not hide `.codex/` repo-wide.
    top = os.path.dirname(project)
    repo(top)
    seed(os.path.join(top, ".gitignore"), "node_modules/\n")


code, out, d = generate("owned-nested", OWN, prepare=nested)
ex = os.path.join(os.path.dirname(d), ".git", "info", "exclude")
check("repo-owned in a subdirectory of a larger repository: the line is anchored to it",
      code == 0 and "/p/.codex/" in (lines_of(ex) or []) and "/.codex/" not in (lines_of(ex) or []),
      "exit %r, exclude %r\n%s" % (code, lines_of(ex), out))

main_repo = os.path.join(TOY, "wt-main")
repo(main_repo)
seed(os.path.join(main_repo, ".gitignore"), "node_modules/\n")
sandbox.git(main_repo, "add", "-A")
sandbox.git(main_repo, "commit", "-q", "-m", "x")


def linked(project):
    os.rmdir(project)
    sandbox.git(main_repo, "worktree", "add", "-q", project, "-b", "wt")


code, out, d = generate("owned-wt", OWN, prepare=linked)
ex = os.path.join(main_repo, ".git", "info", "exclude")
check("repo-owned in a linked worktree: the common directory's exclude gets the line",
      code == 0 and "/.codex/" in (lines_of(ex) or []), "exit %r, exclude %r\n%s" % (code, lines_of(ex), out))

# Control: a refusal that stays. An exclude file that is a symlink is never written through.
elsewhere = os.path.join(TOY, "elsewhere-exclude")
seed(elsewhere, "")


def linked_exclude(project):
    owned(project)
    ex = os.path.join(project, ".git", "info", "exclude")
    os.makedirs(os.path.dirname(ex), exist_ok=True)
    if os.path.lexists(ex):
        os.remove(ex)
    os.symlink(elsewhere, ex)


code, out, d = generate("owned-exlink", OWN, prepare=linked_exclude)
check("control, repo-owned with an exclude that is a symlink: still refused, exit 1, nothing written through it",
      code == 1 and "!not-git-ignored" in out and read(elsewhere) == "" and not os.path.lexists(os.path.join(d, ".codex")),
      "exit %r, link target %r\n%s" % (code, read(elsewhere), out))

# 4. MCPORTER_CONFIG in a project's Codex config comes from skill_keep.common_env.
forge_json({"codex": True}, skill_keep={"common_env": {"MCPORTER_CONFIG": "~/toy/mcporter.json"}})
code, out, d = generate("mcporter-set", {}, prepare=repo)
text, got = mcporter_of(d)
check("MCPORTER_CONFIG comes from skill_keep.common_env, `~` expanded",
      got == os.path.join(HOME, "toy", "mcporter.json"), "set to %r, config.toml:\n%s" % (got, text))
forge_json({"codex": True})
code, out, d = generate("mcporter-none", {}, prepare=repo)
text, got = mcporter_of(d)
check("no common_env in forge.json: no MCPORTER_CONFIG is written", got is None, "set to %r" % (got,))
check("control, no common_env: the config itself is still written", "[shell_environment_policy]" in text,
      "config.toml:\n%s" % text)
# A file that carries the key the code used to hard-code (this machine's does; the gate compares
# its output byte for byte): the same value comes out.
forge_json({"codex": True}, skill_keep={"common_env": {"MCPORTER_CONFIG": "~/.config/mcporter/mcporter.json"}})
code, out, d = generate("mcporter-real", {}, prepare=repo)
text, got = mcporter_of(d)
check("a forge.json with the path the code hard-coded: MCPORTER_CONFIG is that path",
      got == os.path.join(HOME, ".config", "mcporter", "mcporter.json"), "set to %r" % (got,))

# This checkout's own config/forge.json, where it has one: the same value comes out of it.
REAL_SETTINGS = os.path.join(sandbox.FORGE, "config", "forge.json")
if os.path.exists(REAL_SETTINGS):
    # A copy with codex_harness true: the value is read from .codex/config.toml, which is not written with
    # the switch off. Red before, with it false in the real file: "set to None".
    doc = json.load(open(REAL_SETTINGS))
    doc["codex_harness"] = True
    lib.SETTINGS = os.path.join(TOY, "machine-forge.json")
    with open(lib.SETTINGS, "w") as fh:
        json.dump(doc, fh)
    lib.settings.cache_clear()
    code, out, d = generate("mcporter-machine", {}, prepare=repo)
    text, got = mcporter_of(d)
    check("this machine's forge.json: MCPORTER_CONFIG is the path the code hard-coded",
          got == os.path.join(HOME, ".config", "mcporter", "mcporter.json"), "set to %r" % (got,))
else:
    print("NOT RUN: this machine's forge.json MCPORTER_CONFIG -- no config/forge.json in this checkout")

# 5. relink_skills.py and memory_doctor.py, run as scripts from a toy root with its own forge.json.
PY = sys.executable
RELINK = os.path.join("scripts", "sync", "relink_skills.py")
DOCTOR = os.path.join("scripts", "sync", "memory_doctor.py")


def toy_root(name, integrations, *scripts):
    """A toy checkout with a config/forge.json, next to its own empty HOME; returns (root, home)."""
    base = os.path.join(TOY, name)
    root, home = os.path.join(base, "forge"), os.path.join(base, "home")
    os.makedirs(os.path.join(root, "config", "profiles"))
    os.makedirs(home)
    sandbox.mini_root(root, *scripts)
    with open(os.path.join(root, "config", "forge.json"), "w", encoding="utf-8") as fh:
        json.dump({"integrations": dict({k: False for k in lib.INTEGRATIONS}, **integrations)}, fh)
    return root, home


def run_script(root, home, script, *args):
    r = subprocess.run([PY, os.path.join(root, script)] + list(args), capture_output=True, text=True, timeout=120,
                       env=sandbox.bare_env(home, os.environ.get("TMPDIR") or "/tmp"), cwd=home)
    return r.returncode, r.stdout + r.stderr


def alpha(root):
    seed(os.path.join(root, "skills", "alpha", "SKILL.md"), "---\nname: alpha\n---\n")


root, home = toy_root("relink-none", {"codex": True}, RELINK)
code, out = run_script(root, home, RELINK)
check("relink_skills, no skills/: exit 0 and the SKIP line", code == 0 and "relink_skills: SKIP" in out, "exit %r, %r" % (code, out))
check("relink_skills, no skills/: no mirror is made", not os.path.lexists(os.path.join(home, ".claude", "skills")),
      "~/.claude/skills was created")

root, home = toy_root("relink-empty", {"codex": True}, RELINK)
os.makedirs(os.path.join(root, "skills"))
seed(os.path.join(root, "skills", "README.md"), "not a skill\n")  # a file is not a skill
code, out = run_script(root, home, RELINK)
made = [m for m in (".claude", ".codex") if os.path.lexists(os.path.join(home, m, "skills"))]
check("relink_skills, empty skills/: exit 0 and the SKIP line", code == 0 and "relink_skills: SKIP" in out, "exit %r, %r" % (code, out))
check("relink_skills, empty skills/: no mirror is made", not made, "created %r, empty, and nothing said so" % (made,))

root, home = toy_root("relink-codex-off", {"codex": False}, RELINK)
alpha(root)
code, out = run_script(root, home, RELINK)
check("relink_skills, codex off: ~/.claude/skills is linked and no $CODEX_HOME/skills is made",
      os.path.islink(os.path.join(home, ".claude", "skills", "alpha")) and not os.path.lexists(os.path.join(home, ".codex")),
      "exit %r, ~/.codex %s: %r" % (code, "exists" if os.path.lexists(os.path.join(home, ".codex")) else "absent", out))
root, home = toy_root("relink-codex-on", {"codex": True}, RELINK)
alpha(root)
code, out = run_script(root, home, RELINK)
check("control, relink_skills with codex on: both mirrors are linked",
      all(os.path.islink(os.path.join(home, m, "skills", "alpha")) for m in (".claude", ".codex")), "exit %r, %r" % (code, out))

MEMORY = (DOCTOR, os.path.join("forge", "memory.py"), os.path.join("forge", "mcp.py"))
for label, integrations in (("both off", {}), ("both on", {"codex": True, "hindsight": True})):
    root, home = toy_root("doctor-" + label.replace(" ", "-"), integrations, *MEMORY)
    seed(os.path.join(root, "config", "memory-known-empty.json"), '{"known": {}}')
    code, out = run_script(root, home, DOCTOR)
    shown = {k: k in out for k in ("codex-trust", "codex-untrusted", "hindsight-config")}
    if integrations:
        check("control, memory_doctor with codex and hindsight on: their checks run, and the missing rendered config FAILs",
              all(shown.values()) and code == 1 and "FAIL" in out and "hindsight-config" in out,
              "exit %r, shown %r\n%s" % (code, shown, out))
    else:
        check("memory_doctor, codex and hindsight off: none of their checks run, and it exits 0",
              not any(shown.values()) and code == 0, "exit %r, shown %r\n%s" % (code, shown, out))
        check("memory_doctor, codex and hindsight off: it says NOT RUN, NOT ARMED for each",
              len(re.findall(r"NOT RUN, NOT ARMED", out)) >= 2 and "codex" in out and "hindsight" in out, out)

failed = bool(failures)
for f in failures:
    print("FAIL", f)
print("%d check(s), %d failure(s)" % (n_cases[0], len(failures)))
sandbox.cleanup(failed)
sys.exit(1 if failed else 0)
