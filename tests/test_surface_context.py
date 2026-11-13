#!/usr/bin/env python3
"""The profile field `surface_context` and its doctor row `surface context` (framework part 4.2, unit U2).

A profile says which skills of its own `.claude/skills/` the agent loads when the work touches a surface:
`"surface_context": {"ui": {"skills": ["coss"]}}`. forge/lib.py checks the shape (profile_error), and `forge doctor`
fails when a named skill has no `<project_path>/.claude/skills/<name>/SKILL.md` (forge/framework.py surface_context_row).
forge/framework.py already hands the field to .claude/<plugin>.json; a profile without it is untouched by all of this.

Seen failing on the base (4afa0b8, the field has no row in PROFILE_FIELDS and there is no row function):
  (a) "a: skills is a string: expected profile error, got none" (and the same for every other malformed case of section a:
      the base accepts any value of the field).
  (b) "b: all present: AttributeError: module 'forge.framework' has no attribute 'surface_context_row'" (same for the
      missing-skill and SKIP cases).
  (c) "c: no `surface context` row in `forge doctor toy`" (the real output of the toy checkout's bin/forge).
Negative controls on the finished code, each mutation put back:
  (b) the existence check taken out of surface_context_row: "b: a missing SKILL.md: expected FAIL naming coss, got PASS".
  (c) the `surface context` line taken out of cli.project_checks: "c: no `surface context` row in `forge doctor toy`".
  (a) the shape check taken out of profile_error again: the base's "expected profile error, got none".
Everything runs in a toy world: a toy HOME, toy profiles and projects (tests/sandbox.py temp dirs, removed at exit); the
doctor case runs a copy of the engine in an empty network namespace when the machine gives one."""
import copy
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("surface-ctx-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, sandbox.FORGE)
from forge import lib  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
REAL_PROFILES = lib.PROFILES
failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:600]))


def want(label, got, expected):
    check(label, got == expected, "got %r, want %r" % (got, expected))


# --- (a) the shape of the field ---------------------------------------------------------------------------------------
GOOD = {"project": "toy", "project_path": "/srv/toy", "surface_context": {"ui": {"skills": ["coss", "tokens"]}, "api": {"skills": []}}}


def with_field(value):
    return dict(GOOD, surface_context=value)


want("a: a well-formed field is accepted", lib.profile_error(GOOD), None)
want("a: no field, no error", lib.profile_error({k: v for k, v in GOOD.items() if k != "surface_context"}), None)
want("a: an empty object is accepted (it says nothing)", lib.profile_error(with_field({})), None)
BAD = [
    ("skills is a string", {"ui": {"skills": "coss"}}, "surface_context.ui.skills is not a list"),
    ("skills is missing", {"ui": {}}, "surface_context.ui.skills is missing"),
    ("a surface is a list", {"ui": ["coss"]}, "surface_context is not a JSON object of JSON objects"),
    ("the field is a list", ["ui"], "surface_context is not a JSON object"),
    ("an unknown key", {"ui": {"skills": ["coss"], "paths": []}}, "surface_context.ui.paths is not a key of surface_context.ui"),
    ("a skill is not a string", {"ui": {"skills": ["coss", 3]}}, "surface_context.ui.skills has an item that is not a string"),
    ("a skill name is empty", {"ui": {"skills": [" "]}}, "surface_context.ui.skills has an empty name"),
    ("a skill name leaves the folder", {"ui": {"skills": ["../coss"]}}, "surface_context.ui.skills names a path, not a skill"),
    ("a skill name is a subfolder", {"ui": {"skills": ["a/b"]}}, "surface_context.ui.skills names a path, not a skill"),
]
for label, value, why in BAD:
    got = lib.profile_error(with_field(value))
    check("a: %s: expected profile error, got %s" % (label, got), got is not None and why in got, "got %r, want %r in it" % (got, why))
# A profile with a bad field is left out by lib.profiles (the doctor's `profile` row and the generator's `!` line say why).
skipped = []
os.makedirs(os.path.join(TOY, "cfg", "profiles"))
lib.PROFILES = os.path.join(TOY, "cfg", "profiles")
with open(os.path.join(lib.PROFILES, "toy.claude.json"), "w") as fh:
    json.dump(with_field({"ui": {"skills": "coss"}}), fh)
want("a: lib.profiles leaves the profile out and says why", (list(lib.profiles(skipped)), [w for _, w in skipped]),
     ([], ["surface_context.ui.skills is not a list"]))
os.remove(os.path.join(lib.PROFILES, "toy.claude.json"))

# --- (b) the function ---------------------------------------------------------------------------------------------------
from forge import framework  # noqa: E402

_p = [0]


def world(*profiles):
    """lib.PROFILES at a fresh toy directory holding `profiles`, each (name, extra fields, skills present in its project)."""
    _p[0] += 1
    base = os.path.join(TOY, "w%d" % _p[0])
    lib.PROFILES = os.path.join(base, "profiles")
    os.makedirs(lib.PROFILES)
    paths = {}
    for name, extra, present in profiles:
        paths[name] = os.path.join(base, "projects", name)
        os.makedirs(paths[name])
        for s in present:
            os.makedirs(os.path.join(paths[name], ".claude", "skills", s))
            open(os.path.join(paths[name], ".claude", "skills", s, "SKILL.md"), "w").close()
        with open(os.path.join(lib.PROFILES, name + ".claude.json"), "w") as fh:
            json.dump(dict(extra, project=name, project_path=paths[name]), fh)
    return paths


def row(only=None):
    try:
        return framework.surface_context_row(only)
    except Exception as e:  # a missing function is a failed case, not a crashed suite
        return lib.Result("CRASH", "surface context", "%s: %s" % (type(e).__name__, e))


UI = {"surface_context": {"ui": {"skills": ["coss"]}}}
world(("toy", UI, ["coss"]))
r = row()
want("b: all present: PASS", r.level, "PASS")
check("b: all present: says it looked at one skill of one project", "1 skill" in r.detail and "toy" in r.detail, r.detail)

world(("toy", UI, []))
r = row()
check("b: a missing SKILL.md: expected FAIL naming coss, got %s %s" % (r.level, r.detail), r.level == "FAIL" and "coss" in r.detail, r.detail)

paths = world(("toy", UI, []))
os.makedirs(os.path.join(paths["toy"], ".claude", "skills", "coss"))  # the folder is there, the SKILL.md is not
r = row()
check("b: a skill folder without SKILL.md is missing too: expected FAIL naming coss, got %s" % r.level,
      r.level == "FAIL" and "coss" in r.detail, r.detail)

world(("toy", {"surface_context": {"ui": {"skills": ["coss", "tokens"]}, "api": {"skills": ["rest"]}}}, ["coss", "rest"]))
r = row()
check("b: two surfaces, one skill missing: FAIL names tokens only and counts three looked at",
      r.level == "FAIL" and "tokens" in r.detail and "coss" not in r.detail.split("missing")[-1] and "3 skill" in r.detail, r.detail)

r = (world(("plain", {}, []), ("other", {"surface_context": {}}, [])), row())[1]
check("b: no profile declares the field: SKIP, NOT RUN, NOT ARMED -- no profile declares surface_context",
      r.level == "SKIP" and r.detail.startswith(lib.NOT_ARMED + "no profile declares surface_context"), "%s %s" % (r.level, r.detail))

world(("toy", UI, ["coss"]), ("bad", {"surface_context": {"ui": {"skills": ["gone"]}}}, []))
want("b: `only` looks at that profile alone (toy passes, bad is not read)", row("toy").level, "PASS")
r = row("bad")
check("b: `only` on the profile that lacks its skill fails", r.level == "FAIL" and "gone" in r.detail, r.detail)
r = row("nosuch")
check("b: `only` on a profile that declares nothing: SKIP, NOT ARMED", r.level == "SKIP" and lib.NOT_ARMED in r.detail, r.detail)

paths = world(("toy", UI, ["coss"]))
os.rename(paths["toy"], paths["toy"] + "-gone")
r = row()
check("b: a project_path that is not a directory is a FAIL, never a pass over nothing", r.level == "FAIL" and "toy" in r.detail, r.detail)

world(("empty", {"surface_context": {"ui": {"skills": []}}}, []))
r = row()
check("b: a declared surface with no skill looked at zero skills: FAIL", r.level == "FAIL" and "0 skill" in r.detail, r.detail)

# --- (c) the doctor ---------------------------------------------------------------------------------------------------------
lib.PROFILES = REAL_PROFILES
from forge import cli  # noqa: E402

check("c: the row is registered in forge doctor", "surface context" in [c[0] for c in cli.CHECKS], [c[0] for c in cli.CHECKS])

NS = []


def forge_cli(root, env, *args):
    if not NS:
        NS.append(sandbox.UNSHARE if sandbox.unshare_ok()[0] else ())
    r = subprocess.run(list(NS[0]) + [sys.executable, os.path.join(root, "bin", "forge")] + list(args), cwd=root, env=env,
                       capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr).splitlines()


def rows_of(lines):
    """{row name: (level, detail)} of lib.report's lines ("%-4s  %-22s %s")."""
    return {l[6:28].strip(): (l[:4].strip(), l[29:]) for l in lines if len(l) > 29 and not l.startswith("SUMMARY")}


base = os.path.join(TOY, "doctor-world")
root = os.path.join(base, "forge")
sandbox.copy_engine(root)
sandbox.seed(root)
sandbox.git(root, "init", "-q")
sandbox.git(root, "add", "-A")
pdir = os.path.join(root, "config", "profiles")
for f in os.listdir(pdir):
    os.remove(os.path.join(pdir, f))
projects = {}
for name, extra in (("toy", {"surface_context": {"ui": {"skills": ["coss"]}}}), ("plain", {})):
    projects[name] = os.path.join(base, "projects", name)
    os.makedirs(os.path.join(projects[name], ".claude"))
    sandbox.git(projects[name], "init", "-q")
    with open(os.path.join(pdir, name + ".claude.json"), "w") as fh:
        json.dump(dict(extra, project=name, project_path=projects[name]), fh)
os.makedirs(os.path.join(root, "credentials"))
with open(os.path.join(root, "credentials", "secrets.json"), "w") as fh:
    json.dump({}, fh)
os.chmod(os.path.join(root, "credentials", "secrets.json"), 0o600)
os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(root, "config", "secrets.json"))
dhome = os.path.join(base, "home")
sandbox.installed_settings(dhome, root)
env = sandbox.bare_env(dhome, base)

code, lines = forge_cli(root, env, "doctor", "toy")
rows = rows_of(lines)
check("c: no `surface context` row in `forge doctor toy`", "surface context" in rows, "\n".join(lines))
want("c: the row of `forge doctor toy` fails naming coss (the skill is not there)",
     (rows.get("surface context", ("", ""))[0], "coss" in rows.get("surface context", ("", ""))[1]), ("FAIL", True))
os.makedirs(os.path.join(projects["toy"], ".claude", "skills", "coss"))
open(os.path.join(projects["toy"], ".claude", "skills", "coss", "SKILL.md"), "w").close()
code, lines = forge_cli(root, env, "doctor", "toy")
want("c: with the skill in place the row passes", rows_of(lines).get("surface context", ("", ""))[0], "PASS")

# A project that does not use the feature prints the same rows as before: no new line in its doctor.
code, lines = forge_cli(root, env, "doctor", "plain")
check("c: a profile without the field gets no `surface context` row", "surface context" not in rows_of(lines), "\n".join(lines))

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL " + f)
print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
sys.exit(1 if failures else 0)
