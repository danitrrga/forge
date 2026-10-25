#!/usr/bin/env python3
"""The built-ins Claude Code ships itself (forge/cli_extras.py) are chosen per project the way skills are:
an allowlist. A registry name stays only when forge.json skill_keep.cli_common or the profile's cli_keep
names it; every other one is hidden, 'off' in skillOverrides (override kind) or one DISABLE_*_COMMAND=1 in
env (env kind). No cli_common key and no cli_keep field is the feature off: nothing written, and only what
forge wrote earlier is taken out (forge/owned.py claims, so a user's own entry is never touched).

Runs in-process against a toy HOME and toy projects; lib.may_write() is stubbed to allow, because this
checkout may be a linked worktree, which never writes.

Seen failing on the code before forge/cli_extras.py (write_settings_local without cli_common): 29 of 45 checks red.
  FAIL registry: forge.cli_extras exists -- cannot import name 'cli_extras' from 'forge'
  FAIL write_settings_local took cli_common -- write_settings_local() got an unexpected keyword argument 'cli_common'
  FAIL a: cli_common keeps simplify, hides the other 24 -- got 0: []
  FAIL b: cli_keep keeps team-onboarding, hides the other 24 -- []
  FAIL e: untrimmed: the cli names are hidden -- []
  FAIL f: cli_keep with an unknown name: an error names it -- []
Negative controls, one per case, each a wrong behaviour planted in the finished code and put back from a copy:
  a  kept = set(keep) only (cli_common ignored): "FAIL a: cli_common keeps simplify, hides the other 24 -- got 25"
  b  kept = set(common) only (cli_keep ignored): "FAIL b: cli_keep keeps team-onboarding, hides the other 24"
  c  the "*" wildcard line removed: "FAIL c: cli_keep ['*'] hides no override name"
  d  the stale-claim prune removed: "FAIL d: a name that becomes kept is removed again" and "FAIL d: off again:
     forge's entries are removed"
  e  the untrimmed per-name merge switched off: "FAIL e: untrimmed: the cli names are hidden -- []"
  f  the "not in the registry" refusal switched off: "FAIL f: cli_keep with an unknown name: an error names it"
  callers: forge/sync.py no longer passing cli_common, and lib.PROFILE_FIELDS without cli_keep, each one red."""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("cli-extras-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
from forge import lib  # noqa: E402

# The forge.json the callers read: a toy one with the cli_common key (the real one is the user's data).
lib.SETTINGS = os.path.join(TOY, "forge.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {}, "skill_keep": {"cli_common": ["simplify"]}}, fh)
from forge import cli, owned, skills  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")
lib.PROFILES = os.path.join(TOY, "profiles")  # read by neighbour_skills
os.makedirs(lib.PROFILES)
APPLY = lib.Ctx(True, None, False)

# Claude Code 2.1.308, from the real TUI: what skillOverrides hides, and the env key that hides one built-in each.
OVERRIDE = ["batch", "claude-api", "claude-in-chrome", "code-review", "dataviz", "debug", "deep-research", "design",
            "design-sync", "doctor", "fewer-permission-prompts", "loop", "plugin-authoring", "run",
            "run-skill-generator", "schedule", "simplify", "update-config", "verify", "workflow-authoring",
            "auto-mode-setup", "init", "insights", "security-review", "team-onboarding"]  # 20 skills, 5 commands
ENV = {"login": "DISABLE_LOGIN_COMMAND", "logout": "DISABLE_LOGOUT_COMMAND", "upgrade": "DISABLE_UPGRADE_COMMAND",
       "install-github-app": "DISABLE_INSTALL_GITHUB_APP_COMMAND", "usage-credits": "DISABLE_EXTRA_USAGE_COMMAND"}
ENV_VARS = set(ENV.values())

failures, n_checks, n_proj = [], [0], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", detail)


def project(settings=None):
    n_proj[0] += 1
    p = os.path.join(TOY, "proj%d" % n_proj[0])
    os.makedirs(os.path.join(p, ".claude"))
    if settings is not None:
        lib.write_json(slp(p), settings)
    return p


def slp(p):
    return os.path.join(p, ".claude", "settings.local.json")


def doc(p):
    with open(slp(p), encoding="utf-8") as fh:
        return json.load(fh)


def slurp(file):
    return open(file, "rb").read() if os.path.exists(file) else b""


def run(p, common="absent", **keys):
    """(line, errors): one apply of write_settings_local for a toy profile of `keys`; `common` is
    forge.json's skill_keep.cli_common as the caller passes it, 'absent' for no such key."""
    prof = dict({"project": "toy", "project_path": p}, **keys)
    errors, out = [], io.StringIO()
    kw = {} if common == "absent" else {"cli_common": common}
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            line = skills.write_settings_local(APPLY, prof, {}, errors, (), **kw)
    except TypeError as e:  # the code before this feature: no such parameter
        check("write_settings_local took cli_common", False, e)
        return None, errors
    return line, errors


def over(p):
    return (doc(p).get("skillOverrides") or {}) if os.path.exists(slp(p)) else {}


def envd(p):
    return (doc(p).get("env") or {}) if os.path.exists(slp(p)) else {}


def cli_off(p):
    """The registry names switched off in the file's skillOverrides."""
    return sorted(n for n, v in over(p).items() if v == "off" and n in OVERRIDE)


def env_set(p):
    return {k: v for k, v in envd(p).items() if k in ENV_VARS}


def reset_globals(*names):
    """The skills on the toy machine's ~/.claude/skills (cached by skills.global_skills)."""
    d = os.path.join(HOME, ".claude", "skills")
    if os.path.isdir(d):
        for n in os.listdir(d):
            os.rmdir(os.path.join(d, n))
    for n in names:
        os.makedirs(os.path.join(d, n))
    skills.global_skills.cache_clear()


reset_globals("g1")

# The registry itself: the names the real TUI hid, nothing else.
try:
    from forge import cli_extras
    check("registry: the 25 override names", sorted(n for n, r in cli_extras.HIDEABLE.items() if r[0] == "override")
          == sorted(OVERRIDE) and len(set(OVERRIDE)) == 25, "overrides differ")
    check("registry: the 5 env names and their keys",
          {n: r[1] for n, r in cli_extras.HIDEABLE.items() if r[0] == "env"} == ENV, "env rows differ")
    check("registry: DISABLE_FEEDBACK_COMMAND is not hidden (it did not hide /feedback in 2.1.308)",
          "DISABLE_FEEDBACK_COMMAND" not in {r[1] for r in cli_extras.HIDEABLE.values()}, "")
    check("registry: no always-on name is also hideable", not (cli_extras.ALWAYS & set(cli_extras.HIDEABLE)), "")
    check("registry: help, model and feedback always stay", {"help", "model", "feedback", "bug"} <= cli_extras.ALWAYS, "")
except ImportError as e:
    check("registry: forge.cli_extras exists", False, e)

# (a) cli_common=['simplify'] on a trimmed profile: the other 24 override names off, the 5 env vars set.
p = project()
line, errors = run(p, common=["simplify"], skills_keep=[])
want = sorted(n for n in OVERRIDE if n != "simplify")
check("a: cli_common keeps simplify, hides the other 24", cli_off(p) == want and len(want) == 24,
      "got %d: %s" % (len(cli_off(p)), cli_off(p)))
check("a: simplify is not in skillOverrides", "simplify" not in over(p), over(p))
check("a: the 5 env vars are set to 1", env_set(p) == {v: "1" for v in ENV_VARS}, envd(p))
check("a: the global skill g1 is still off beside them", over(p).get("g1") == "off", over(p))
check("a: no error", errors == [], errors)

# (b) a profile's cli_keep: one name kept; the union with cli_common; an env-kind name kept.
p = project()
run(p, skills_keep=[], cli_keep=["team-onboarding"])
check("b: cli_keep keeps team-onboarding, hides the other 24",
      cli_off(p) == sorted(n for n in OVERRIDE if n != "team-onboarding"), cli_off(p))
p = project()
run(p, common=["simplify"], skills_keep=[], cli_keep=["team-onboarding"])
check("b: cli_common and cli_keep are a union", cli_off(p) == sorted(set(OVERRIDE) - {"simplify", "team-onboarding"}),
      cli_off(p))
p = project()
run(p, skills_keep=[], cli_keep=["login"])
check("b: an env-kind name kept leaves its variable out", env_set(p) == {v: "1" for v in ENV_VARS - {"DISABLE_LOGIN_COMMAND"}},
      envd(p))
check("b: ... and all 25 override names are hidden", cli_off(p) == sorted(OVERRIDE), cli_off(p))

# (c) '*' keeps all.
p = project()
run(p, skills_keep=[], cli_keep=["*"])
check("c: cli_keep ['*'] hides no override name", cli_off(p) == [], cli_off(p))
check("c: cli_keep ['*'] sets no env variable", env_set(p) == {}, envd(p))
check("c: the global skill g1 is still off", over(p).get("g1") == "off", over(p))

# (d) feature off writes nothing; a previous run's entries go; a user's own entry survives.
# Off with nothing of forge's in the file: nothing is written, not even the ownership record. (A skillOverrides
# map of unknown origin in an untrimmed project is still dropped whole, as it always was: nothing says it is
# the user's. Once the feature has written, its claims tell forge's entries from the user's.)
p = project({"model": "x"})
before, reg_before = slurp(slp(p)), slurp(owned.path())
run(p)  # untrimmed, no cli_common, no cli_keep
check("d: feature off writes nothing", slurp(slp(p)) == before and slurp(owned.path()) == reg_before,
      "file changed: %s" % doc(p))
p = project({"skillOverrides": {"mine": "off", "loop": "on"}})
run(p, common=["simplify"])  # on, untrimmed
check("d: on: the user's mine and loop (on) are untouched",
      over(p).get("mine") == "off" and over(p).get("loop") == "on", over(p))
check("d: on: the other names are hidden", len(cli_off(p)) == 23 and "simplify" not in over(p), cli_off(p))
d = doc(p)
d.setdefault("skillOverrides", {})["doctor"] = "on"  # the user edits one of forge's entries
lib.write_json(slp(p), d)
run(p, common=["simplify", "run"])  # run becomes kept: forge's own entry goes
check("d: a name that becomes kept is removed again", "run" not in over(p), over(p))
check("d: ... and the rest stay", len(cli_off(p)) == 21, cli_off(p))
line, _ = run(p)  # feature off again
check("d: off again: forge's entries are removed", cli_off(p) == [] and env_set(p) == {}, doc(p))
check("d: off again: the user's own entries survive", over(p) == {"mine": "off", "loop": "on", "doctor": "on"}, over(p))
check("d: off again: an emptied env is not left behind", "env" not in doc(p), doc(p))

# (e) an untrimmed profile still gets the cli part, and so does the wildcard path.
p = project()
run(p, common=["simplify"])
check("e: untrimmed: the cli names are hidden", cli_off(p) == sorted(set(OVERRIDE) - {"simplify"}), cli_off(p))
check("e: untrimmed: the global skill g1 is not touched", "g1" not in over(p), over(p))
check("e: untrimmed: the env vars are set", env_set(p) == {v: "1" for v in ENV_VARS}, envd(p))
p = project()
run(p, common=["simplify"], skills_keep=["*"], plugins_keep=[])
check("e: skills_keep ['*']: the cli names are hidden and no global skill is", cli_off(p) == sorted(set(OVERRIDE) - {"simplify"})
      and "g1" not in over(p), over(p))
p = project()
run(p, common=["simplify"], env={"MY_VAR": "x", "DISABLE_LOGIN_COMMAND": "0"})
check("e: the profile's own env is kept beside the cli variables and wins a clash",
      envd(p).get("MY_VAR") == "x" and envd(p).get("DISABLE_LOGIN_COMMAND") == "0" and len(env_set(p)) == 5, envd(p))

# (f) the three refusals, loud and with nothing of the cli part written.
def refused(label, needle, common="absent", skills_keep=(), **keys):
    p = project()
    line, errors = run(p, common=common, skills_keep=list(skills_keep), **keys)
    check("f: %s: an error names it" % label, any(needle in e for e in errors), errors)
    check("f: %s: no cli entry written" % label, cli_off(p) == [] and env_set(p) == {}, (over(p), envd(p)))


refused("cli_keep with an unknown name", "nope", cli_keep=["nope"])
refused("cli_keep that is not a list", "cli_keep", cli_keep="help")
refused("cli_keep naming a built-in that has no switch", "help", cli_keep=["help"])
refused("cli_common with an unknown name", "nope", common=["nope"])
reset_globals("g1", "simplify")  # a global skill directory with a registry name
refused("a registry name that is also a global skill", "simplify", common=["loop"], skills_keep=["simplify"])
reset_globals("g1")

# The callers: the doctor's would-write and forge sync read cli_common from config/forge.json and pass it.
p = project()
want = cli.settings_forge_would_write("toy", {"project": "toy", "project_path": p, "skills_keep": []}, {})
check("callers: the doctor's would-write applies forge.json's cli_common",
      isinstance(want, dict) and "simplify" not in want.get("skillOverrides", {}) and "loop" in want.get("skillOverrides", {})
      and want.get("env", {}).get("DISABLE_LOGIN_COMMAND") == "1", "would write %r" % (want,))
with open(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "forge", "sync.py"), encoding="utf-8") as fh:
    check("callers: forge sync passes cli_common to write_settings_local", "cli_extras.common_setting()" in fh.read(), "")
# The profile field: cli_keep is a list of names, checked once like the others.
check("profile: cli_keep of names is valid", lib.profile_error({"cli_keep": ["simplify"]}) is None, "")
check("profile: cli_keep that is not a list is refused", lib.profile_error({"cli_keep": "simplify"}) == "cli_keep is not a list of strings",
      lib.profile_error({"cli_keep": "simplify"}))

print("%d failure(s) over %d checks" % (len(failures), n_checks[0]))
sandbox.cleanup(failures)
sys.exit(1 if failures else 0)
