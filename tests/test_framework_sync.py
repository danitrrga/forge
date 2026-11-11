#!/usr/bin/env python3
"""The `framework` step of the generator (forge/framework.py, called from forge/sync.py): for a profile with
`framework: true`, `forge sync` writes <project>/.claude/<plugin>.json and enables the plugin; with `false` or the
field absent it writes nothing and takes out only what it wrote itself.

  * The plugin's name is not in the code: it is the `name` of <plugin_source.path>/.claude-plugin/marketplace.json,
    which must list a plugin of that name. The fixtures use `toyfw`, so a generator with a fixed name fails the first case.
  * `true`: the file with every field of the schema (project, factory, weekly, models, limits, rounds, linear.labels,
    integrations, paths), its ignore line (.git/info/exclude with writes_tracked_files false), in settings.local.json
    enabledPlugins["toyfw@toyfw"] and extraKnownMarketplaces.toyfw (the source with `~` expanded), env.LINEAR_API_KEY
    when the secret exists (else one line, no `!`, that says NOT RUN, NOT ARMED), and the three as owned claims.
  * `true` -> `false`: the file and the two keys go; a file or key edited since stays and is named on a `!` line.
  * Errors, each a `!` line, exit 1 and nothing written: no plugins_keep, no plugin_source, a source that is not a
    directory, a folder without marketplace.json or whose marketplace lists no plugin of its name.
  * Branch B (measured in 2.2 U0): with --apply, a machine registry (~/.claude/plugins/known_marketplaces.json)
    without the marketplace at that path gets one `claude plugin marketplace add <path> --scope local`, run from the
    project's folder; a second apply makes no call, a dry-run none, and no `claude` on PATH is a `!` line.
  * `forge uninstall --project` takes the file and the keys out.
  * examples/forge.json's `framework.models` equal the framework repo's config.py DEFAULTS. The comparison runs over a
    toy repo in the temp world (equal, and one alias changed as its control); with FRAMEWORK_REPO set it also runs
    against the real repo, an extra and never a condition: the suite runs every check without it.

Everything runs in-process against a toy HOME, a toy forge.json and toy profiles. `claude` is a fake on PATH: PATH is
the fake directory alone (python3 and git linked into it), never the system's behind it, so the real `claude` is
unreachable (the first check proves it).

Seen failing on 530fc79 (master: no framework step; this file as it is, run in a plain copy of that commit): 54 of 121
checks red, the other 67 are controls that pass there (a profile with `false` or no field writes nothing, a dry-run
writes nothing, every error writes nothing, uninstall of a project with nothing written). First messages:
  true: "true: .claude/toyfw.json is written -- exists False"
  true: "settings: enabledPlugins toyfw@toyfw is on -- None -- {'keep@toy': True}"
  labels: "labels: linear.labels is copied from framework.linear -- linear.labels is empty -- None"
  no secret: "no secret: one NOT RUN, NOT ARMED line, no `!` -- [] -- []"
  errors: "no plugins_keep: a `!` line that names plugins_keep -- [] -- MODE: APPLY ..." (exit 0)
  uninstall: "uninstall: setup, the file is there -- " (nothing was ever written to take out)
  branch B: "branch B: two applies make one `marketplace add` -- calls 0 -- []"
3.6 U3b (section 7: worktree.baseRef and the profile fields checks_quick, app_run, default_branch_protected, ui_image).
Seen failing on 57655b6 (master, this file as it is): 32 of 186 checks red. First messages:
  baseRef: "baseRef: a `true` profile gets worktree.baseRef \"head\" -- worktree None -- None"
  profile_error: "profile_error rejects ui_image without dockerfile, naming dockerfile -- None -- None" (the bad profile passes: no row)
  fields: "fields: default_branch_protected true reaches project.default_branch_protected -- missing from fwx.json"
Negative controls, each mutation put back: baseRef never pruned (2 red); an edited baseRef removed anyway (1); baseRef not claimed (3);
`..` allowed in dockerfile (2); unknown keys of app_run/ui_image allowed (2); default_branch_protected always false (1).
With FRAMEWORK_REPO set there is one more check: the real repo's models comparison.
app_run.ready / ready_timeout_s (the keys the plugin's walk selftest reads). Seen failing on dacc4e9 (master, this file as it is): 5 of 204
checks red, first message: "profile_error accepts app_run with ready -- app_run.ready is not a key of app_run (known: container, down,
login, run, up, url)"; the others: ready_timeout_s 45 and 12.5, both keys together, and "fields: app_run.ready and ready_timeout_s reach
project.app_run unchanged -- missing from fwx.json". The rejection rows already passed there (the unknown-key error names the key), so
they are controls on the finished code, each mutation put back: positivity check dropped (3 red: ready_timeout_s 0, 0.0, -1); bool
allowed (1: "rejects app_run with ready_timeout_s true"); finiteness dropped (1: infinity); `ready` may be empty (2: empty, blank).
Negative controls on the finished code, each mutation put back from a copy, the checks that went red (17 mutations, each
red): fixed plugin name "fwx" (36: the first case, `.claude/toyfw.json` missing); `linear` not copied (1: "linear.labels is
empty"); the plugins_keep error removed (2: it writes `.claude/toyfw.json`); `claude` called on every apply (2: "calls 2");
file never removed (1); an edited file removed anyway (2); no ignore line (4); LINEAR_API_KEY never added (2); the NOT RUN
line missing (1); the marketplace key never pruned (3); an edited marketplace key removed anyway (2); the marketplace not
claimed (4), the plugin entry not enabled (5) or not claimed (1), the file not claimed (5); `~` not expanded (49); an alias
changed in examples/forge.json (1: "m15 ... {'detector': ({'small': 'sonnet', ...").
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("fwsync-test-")
HOME = os.path.join(TOY, "home")
BIN = os.path.join(TOY, "bin")
os.makedirs(HOME)
os.makedirs(BIN)
# Order 10: only the fake directory on PATH. python3 and git are linked in; `claude` is the fake, written per case.
for tool in ("python3", "git"):
    os.symlink(shutil.which(tool), os.path.join(BIN, tool))
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
os.environ["PATH"] = BIN
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, sandbox.FORGE)
from forge import lib  # noqa: E402

BASE_SETTINGS = os.path.join(TOY, "forge-base.json")
with open(BASE_SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
lib.SETTINGS = BASE_SETTINGS
from forge import owned, sync, uninstall  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")  # this checkout may be a linked worktree, which never writes

failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:600]))


check("control: `claude` is not reachable but through the fake directory (PATH is %s)" % os.environ["PATH"],
      shutil.which("claude") is None and os.environ["PATH"] == BIN, shutil.which("claude"))

SECRET = "fake-linear-key-5d1e-NOT-REAL"
NAME = "toyfw"
FW = {"models": {"planner": {"small": "opus", "normal": "opus", "big": "opus"},
                 "detector": {"small": "haiku", "normal": "haiku", "big": "haiku"}},
      "limits": {"on": False, "per_project": {}, "ram_min_free_gb": 0},
      "rounds": 4, "critique_rounds_unattended": 2,
      "factory": {"watchdog_nudge_min": 7, "watchdog_fail_min": 30, "cost_warn_x_median": 3, "classifier": "apply"},
      "weekly": {"on": True, "min_sessions": 5},
      "paths": {"notify": "echo toy", "verdict": None},
      "linear": {"labels": {"needs-owner": "toy-needs-help"}},
      "plugin_source": {"source": "directory", "path": "~/plug/" + NAME}}
INTEGRATIONS_ON = {"consent": True}

_n = [0]


def forge_json(fw="default", integrations=None):
    """Point lib at a toy forge.json: the integrations given on, the rest off, and the framework section `fw`
    (the string "default" is FW, None leaves the section out)."""
    _n[0] += 1
    doc = {"integrations": {k: (integrations or {}).get(k, False) for k in lib.INTEGRATIONS}}
    if fw is not None:
        doc["framework"] = FW if fw == "default" else fw
    path = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()
    return doc


def plugin_dir(name=NAME, listed=NAME, marketplace=True):
    """HOME/plug/<name>: a plugin folder whose marketplace is called `name` and lists a plugin called `listed`."""
    d = os.path.join(HOME, "plug", name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, ".claude-plugin"))
    if marketplace:
        with open(os.path.join(d, ".claude-plugin", "marketplace.json"), "w") as f:
            json.dump({"name": name, "owner": {"name": "toy"},
                       "plugins": [] if listed is None else [{"name": listed, "source": "./"}]}, f)
        with open(os.path.join(d, ".claude-plugin", "plugin.json"), "w") as f:
            json.dump({"name": name, "version": "0.0.1", "description": "toy"}, f)
    return d


_p = [0]


def project(remote="https://example.org/toy-org/toy-repo.git", head_branch="toy-main", origin_head="trunk",
            gitignore=None, commit_ignore=False):
    """A toy checkout under TOY: a git repo on `head_branch`, its origin `remote` (None: no remote), origin/HEAD
    pointing at `origin_head` (None: unset), a .gitignore of `gitignore` when given."""
    _p[0] += 1
    d = os.path.join(TOY, "toyproj%d" % _p[0])
    os.makedirs(d)
    sandbox.git(d, "init", "-q", "-b", head_branch)
    if remote:
        sandbox.git(d, "remote", "add", "origin", remote)
        if origin_head:
            sandbox.git(d, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/" + origin_head)
    if gitignore is not None:
        with open(os.path.join(d, ".gitignore"), "w") as f:
            f.write(gitignore)
        if commit_ignore:
            sandbox.git(d, "add", ".gitignore")
            sandbox.git(d, "commit", "-q", "-m", "ignore")
    return d


def profile(ppath, name="toyapp", **over):
    p = {"project": name, "project_path": ppath, "servers": [], "plugins_keep": ["keep@toy"], "skills_keep": ["*"],
         "framework": True, "factory": "trial", "factory_ui_bugs": True, "checks": ["make test", "make lint"],
         "protected_paths": ["db/**"], "production": {"branches": ["release"], "commands": ["deploy "]},
         "verdict_command": "python3 verdict.py", "ui": True}
    p.update(over)
    return {k: v for k, v in p.items() if v != "DROP"}


_w = [0]


class World:
    """A toy config/ (registry, secrets link, profiles) the generator runs over, one world per case."""

    def __init__(self, secrets=None):
        _w[0] += 1
        self.base = os.path.join(TOY, "world%d" % _w[0])
        self.cfg = os.path.join(self.base, "config")
        self.pdir = os.path.join(self.cfg, "profiles")
        os.makedirs(self.pdir)
        with open(os.path.join(self.cfg, "mcp-registry.json"), "w") as f:
            f.write('{"servers": {}}')
        with open(os.path.join(self.base, "secrets.json"), "w") as f:
            json.dump({"LINEAR_API_KEY": SECRET} if secrets is None else secrets, f)
        os.symlink(os.path.join(self.base, "secrets.json"), os.path.join(self.cfg, "secrets.json"))
        with open(os.path.join(self.cfg, "project-relocations.json"), "w") as f:
            f.write('{"relocations": []}')
        self.names = set()

    def put(self, prof):
        name = prof["project"]
        self.names.add(name)
        with open(os.path.join(self.pdir, name + ".claude.json"), "w") as f:
            json.dump(prof, f)

    def drop(self, name):
        os.remove(os.path.join(self.pdir, name + ".claude.json"))
        self.names.discard(name)

    def run(self, apply=True):
        """(exit code, everything the run printed). Nothing outside TOY is in scope: asserted first."""
        sync.CFG, lib.PROFILES = self.cfg, self.pdir
        for pf in os.listdir(self.pdir):
            pp = json.load(open(os.path.join(self.pdir, pf)))["project_path"]
            if not os.path.realpath(pp).startswith(TOY + os.sep):
                sys.exit("FENCE: a toy profile points outside the toy world -- nothing run")
        real = lib.context
        lib.context = lambda argv: lib.Ctx(bool(argv), set(self.names), False)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = sync.agent_config(["--apply"] if apply else [])
        finally:
            lib.context = real
        text = out.getvalue() + err.getvalue()
        check("control: no run prints the secret", SECRET not in text, text)
        return code, text


def slp(p):
    return os.path.join(p, ".claude", "settings.local.json")


def fwfile(p, name=NAME):
    return os.path.join(p, ".claude", name + ".json")


def load(f):
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def raw(f):
    try:
        with open(f, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def fwlines(text):
    """The lines the framework step prints: `   framework -> ...`, or `   ! framework -> ...`."""
    return [l for l in text.splitlines() if re.match(r"^\s*(! )?framework\b", l)]


def bang(text):
    return [l for l in text.splitlines() if l.lstrip().startswith("!")]


def claims_of(f, part=None):
    return owned.previous(f, part)[0]


def sl_keys(p):
    d = load(slp(p)) or {}
    return d.get("enabledPlugins", {}), d.get("extraKnownMarketplaces", {}), d.get("env", {})


FAKE = '''#!%s
import json, os, sys
log = os.path.join(%r, "claude-calls.jsonl")
with open(log, "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
reg = os.path.join(%r, ".claude", "plugins", "known_marketplaces.json")
if sys.argv[1:4] == ["plugin", "marketplace", "add"]:
    os.makedirs(os.path.dirname(reg), exist_ok=True)
    doc = json.load(open(reg)) if os.path.exists(reg) else {}
    path = sys.argv[4]
    doc[os.path.basename(path)] = {"source": {"source": "directory", "path": path}, "installLocation": path}
    json.dump(doc, open(reg, "w"))
    print("Successfully added marketplace")
'''
CALLS = os.path.join(TOY, "claude-calls.jsonl")
REGISTRY_FILE = os.path.join(HOME, ".claude", "plugins", "known_marketplaces.json")


def install_fake(exit_code=0):
    p = os.path.join(BIN, "claude")
    with open(p, "w") as f:
        f.write(FAKE % (sys.executable, TOY, HOME) + ("sys.exit(%d)\n" % exit_code if exit_code else ""))
    os.chmod(p, 0o755)


def calls():
    if not os.path.exists(CALLS):
        return []
    return [json.loads(l) for l in open(CALLS) if l.strip()]


def reset_registry():
    for f in (CALLS, REGISTRY_FILE):
        if os.path.exists(f):
            os.remove(f)


install_fake()  # a registered marketplace is the common case; section 6 takes it away

# ------------------------------------------------------------------------------------------ 1. framework true
forge_json(integrations=INTEGRATIONS_ON)
plugin = plugin_dir()
pp = project()
w = World()
w.put(profile(pp))
code, out = w.run()
doc = load(fwfile(pp))
check("true: exit 0 -- exit %d: %s" % (code, bang(out)), code == 0, out)
check("true: .claude/toyfw.json is written", doc is not None, "exists %s; output %s" % (os.path.exists(fwfile(pp)), out[-400:]))
doc = doc or {}
proj = doc.get("project", {})
check("true: schema 1 and framework true", doc.get("schema") == 1 and doc.get("framework") is True, (doc.get("schema"), doc.get("framework")))
check("true: project.name is the profile's `project`", proj.get("name") == "toyapp", proj.get("name"))
check("true: project.main_checkout is project_path resolved", proj.get("main_checkout") == os.path.realpath(pp), proj.get("main_checkout"))
check("true: project.linear_project is the origin's last segment without .git", proj.get("linear_project") == "toy-repo",
      proj.get("linear_project"))
check("true: project.default_branch is origin/HEAD's", proj.get("default_branch") == "trunk", proj.get("default_branch"))
check("true: project.factory_branch is factory", proj.get("factory_branch") == "factory", proj.get("factory_branch"))
check("true: checks, protected_paths, production, verdict_command and ui come from the profile",
      proj.get("checks") == ["make test", "make lint"] and proj.get("protected_paths") == ["db/**"]
      and proj.get("production") == {"branches": ["release"], "commands": ["deploy "]}
      and proj.get("verdict_command") == "python3 verdict.py" and proj.get("ui") is True, proj)
check("true: the later phases' project fields are the schema's defaults",
      proj.get("checks_quick") == [] and proj.get("app_run") is None and proj.get("surface_context") == {}, proj)
fac = doc.get("factory", {})
check("true: factory.mode and factory.ui_bugs come from the profile", fac.get("mode") == "trial" and fac.get("ui_bugs") is True, fac)
check("true: factory carries the framework section's keys", fac.get("watchdog_nudge_min") == 7 and fac.get("classifier") == "apply", fac)
check("true: weekly, models, limits, rounds, critique_rounds_unattended and paths come from the framework section",
      doc.get("weekly") == FW["weekly"] and doc.get("models") == FW["models"] and doc.get("limits") == FW["limits"]
      and doc.get("rounds") == 4 and doc.get("critique_rounds_unattended") == 2 and doc.get("paths") == FW["paths"],
      {k: doc.get(k) for k in ("weekly", "models", "limits", "rounds", "critique_rounds_unattended", "paths")})
check("labels: linear.labels is copied from framework.linear -- linear.labels %s" % ("is empty" if not (doc.get("linear") or {}).get("labels") else ""),
      (doc.get("linear") or {}).get("labels") == {"needs-owner": "toy-needs-help"}, doc.get("linear"))
check("true: integrations holds the four names, read from forge.json (notifications is not an integration yet: false)",
      doc.get("integrations") == {"consent": True, "notifications": False, "agent_browser": False, "mempalace": False},
      doc.get("integrations"))
gi = raw(os.path.join(pp, ".gitignore")) or b""
check("true: the ignore line, inside the FORGE-FWX block, is in .gitignore",
      b"/.claude/toyfw.json" in gi.splitlines() and b"# BEGIN FORGE-FWX (managed by forge)" in gi.splitlines(), gi)
check("true: git ignores the file", subprocess.run(["git", "-C", pp, "check-ignore", "-q", ".claude/toyfw.json"]).returncode == 0, "")
enabled, markets, env = sl_keys(pp)
check("settings: enabledPlugins toyfw@toyfw is on -- %s" % enabled.get("toyfw@toyfw"), enabled.get("toyfw@toyfw") is True, enabled)
check("settings: the profile's own plugins_keep entry is kept", enabled.get("keep@toy") is True, enabled)
check("settings: extraKnownMarketplaces.toyfw is the source with ~ expanded, in the form `marketplace add` writes",
      markets.get(NAME) == {"source": {"source": "directory", "path": plugin}}, markets)
check("settings: env.LINEAR_API_KEY is the resolved secret", env.get("LINEAR_API_KEY") == SECRET, sorted(env))
check("settings: the file is 0600 (it holds the key)", os.path.exists(slp(pp)) and os.stat(slp(pp)).st_mode & 0o777 == 0o600, "")
fc = claims_of(fwfile(pp))
check("claims: the file is a `file` claim, part framework, owner the profile, the digest of what was written",
      len(fc) == 1 and fc[0]["kind"] == "file" and fc[0].get("part") == "framework" and fc[0]["owner"] == "toyapp"
      and fc[0]["sum"] == owned.digest(doc) and doc, fc)
sc = {(c["kind"], tuple(c["at"])) for c in claims_of(slp(pp))}
check("claims: extraKnownMarketplaces.toyfw and enabledPlugins.toyfw@toyfw are key claims",
      ("key", ("extraKnownMarketplaces", NAME)) in sc and ("key", ("enabledPlugins", "toyfw@toyfw")) in sc, sorted(sc))
check("claims: the ignore block is claimed, part framework",
      any(c["kind"] == "item" and c["at"] == ["block", "FORGE-FWX"] and c.get("part") == "framework"
          for c in claims_of(os.path.join(pp, ".gitignore"))), claims_of(os.path.join(pp, ".gitignore")))

# Again: byte-identical, and the line says so.
before = (raw(fwfile(pp)), raw(slp(pp)), raw(os.path.join(pp, ".gitignore")), raw(owned.path()))
code, out = w.run()
after = (raw(fwfile(pp)), raw(slp(pp)), raw(os.path.join(pp, ".gitignore")), raw(owned.path()))
check("again: exit 0, every file byte-identical, the registry too", code == 0 and before == after, (code, bang(out)))
check("again: the line says already current", any("already current" in l for l in fwlines(out)), out)

# A dry-run in a fresh project writes nothing and says what it would write.
pp2 = project()
w2 = World()
w2.put(profile(pp2))
code, out = w2.run(apply=False)
check("dry-run: exit 0, no file, no settings.local.json, no .gitignore",
      code == 0 and not os.path.exists(fwfile(pp2)) and not os.path.exists(slp(pp2))
      and not os.path.exists(os.path.join(pp2, ".gitignore")), (code, out[-300:]))
check("dry-run: the line says it would write", any("would" in l for l in fwlines(out)), out)

# defaults: no origin/HEAD -> the checkout's branch; no remote -> the folder's name; absent profile fields -> defaults.
pp3 = project(origin_head=None)
w3 = World()
w3.put(profile(pp3, name="lean", factory="DROP", factory_ui_bugs="DROP", checks="DROP", protected_paths="DROP",
               production="DROP", verdict_command="DROP", ui="DROP"))
w3.run()
d3 = load(fwfile(pp3)) or {}
check("defaults: without origin/HEAD, default_branch is the checkout's branch", d3.get("project", {}).get("default_branch") == "toy-main",
      d3.get("project"))
check("defaults: absent profile fields give factory off/false, no checks, no protected paths, no production, no verdict, ui false",
      d3.get("factory", {}).get("mode") == "off" and d3.get("factory", {}).get("ui_bugs") is False
      and d3["project"].get("checks") == [] and d3["project"].get("protected_paths") == []
      and d3["project"].get("production") == {"branches": [], "commands": []}
      and d3["project"].get("verdict_command") is None and d3["project"].get("ui") is False, d3.get("project"))
pp4 = project(remote=None)
w4 = World()
w4.put(profile(pp4, name="solo"))
w4.run()
d4 = load(fwfile(pp4)) or {}
check("defaults: without a remote, linear_project is the folder's name",
      d4.get("project", {}).get("linear_project") == os.path.basename(pp4), d4.get("project"))

# A profile's `linear_project` overrides the remote's name (a repository whose issues live in another Linear project).
pp4b = project()
w4b = World()
w4b.put(profile(pp4b, name="shared", linear_project="Other Project"))
w4b.run()
d4b = load(fwfile(pp4b)) or {}
check("linear_project in the profile overrides the remote's name",
      d4b.get("project", {}).get("linear_project") == "Other Project", d4b.get("project", {}).get("linear_project"))
check("linear_project in the profile: the other fields are as without it",
      {k: v for k, v in d4b.get("project", {}).items() if k != "linear_project"} ==
      {k: v for k, v in proj.items() if k not in ("linear_project", "name", "main_checkout")} | {
          "name": "shared", "main_checkout": os.path.realpath(pp4b)}, d4b.get("project"))
for bad in (5, "", "  "):
    why = lib.profile_error(profile(pp4b, linear_project=bad))
    check("linear_project %r is refused by profile_error" % (bad,), bool(why) and "linear_project" in why, why)

# no `framework.linear` -> {"labels": {}}; no framework.models etc. -> the file still has the schema's tables.
fw_bare = {k: v for k, v in FW.items() if k in ("plugin_source",)}
forge_json(fw=fw_bare)
pp5 = project()
w5 = World()
w5.put(profile(pp5, name="bare"))
w5.run()
d5 = load(fwfile(pp5)) or {}
check("no framework.linear: linear is {\"labels\": {}}", d5.get("linear") == {"labels": {}}, d5.get("linear"))
check("a bare framework section: the tables are there and empty (the plugin lays its defaults under them)",
      all(isinstance(d5.get(k), dict) for k in ("factory", "weekly", "models", "limits", "paths")), sorted(d5))
# walk: a `walk` table in the section reaches the file as it is; a section without one leaves the key out (so the
# plugin's defaults apply, as for rounds). Seen failing before the change, 1 of 189 checks:
# `FAIL walk: framework.walk.browser_executable reaches fwx.json -- walk is missing from fwx.json -- None`.
WALK = {"browser_executable": "/srv/browsers/chrome-headless-shell"}
forge_json(fw=dict(FW, walk=WALK))
pp5w = project()
w5w = World()
w5w.put(profile(pp5w, name="walk"))
w5w.run()
d5w = load(fwfile(pp5w)) or {}
check("walk: framework.walk.browser_executable reaches fwx.json -- walk is %s" % d5w.get("walk", "missing from fwx.json"),
      (d5w.get("walk") or {}).get("browser_executable") == WALK["browser_executable"], d5w.get("walk"))
check("walk: no `walk` key in the section means no `walk` key in the file (bare section) -- %s" % d5.get("walk", "absent"),
      "walk" not in d5 and "walk" not in doc, (d5.get("walk"), doc.get("walk")))
# open: the user's opener, {"command": [argv with {url} and {path}]}, reaches the file as it is, under the top-level key
# `open`; a section without one leaves the key out; one that is not a table is treated as absent (as for walk).
# Seen failing before the change, 1 of 209 checks (the other two new checks pass on the old code, being absences):
# `FAIL open: framework.open reaches fwx.json unchanged -- open is missing from fwx.json -- None`.
OPEN = {"command": ["toy-opener", "--new-window", "{url}", "{path}"]}
forge_json(fw=dict(FW, open=OPEN))
pp5o = project()
w5o = World()
w5o.put(profile(pp5o, name="open"))
w5o.run()
d5o = load(fwfile(pp5o)) or {}
check("open: framework.open reaches fwx.json unchanged -- open is %s" % d5o.get("open", "missing from fwx.json"),
      d5o.get("open") == OPEN, d5o.get("open"))
check("open: no `open` key in the section means no `open` key in the file (bare section) -- %s" % d5.get("open", "absent"),
      "open" not in d5 and "open" not in doc, (d5.get("open"), doc.get("open")))
forge_json(fw=dict(FW, open=["toy-opener", "{url}"]))
pp5p = project()
w5p = World()
w5p.put(profile(pp5p, name="openlist"))
w5p.run()
d5p = load(fwfile(pp5p)) or {}
check("open: an `open` that is not a table is left out of the file, as for walk -- %s" % d5p.get("open", "absent"),
      "open" not in d5p, d5p.get("open"))
forge_json(integrations=INTEGRATIONS_ON)

# ------------------------------------------------------------------------------- 2. false: both directions
pp6 = project(gitignore="node_modules/\n", commit_ignore=True)
w6 = World()
w6.put(profile(pp6, name="off", framework=False))
code, out = w6.run()
check("false: exit 0 and the run prints no framework line", code == 0 and not fwlines(out), out)
check("false: no file, no marketplace, no plugin, no key", not os.path.exists(fwfile(pp6)) and sl_keys(pp6)[1] == {}
      and "toyfw@toyfw" not in sl_keys(pp6)[0] and "LINEAR_API_KEY" not in sl_keys(pp6)[2], os.listdir(os.path.join(pp6, ".claude")))
check("false: the .gitignore is untouched", raw(os.path.join(pp6, ".gitignore")) == b"node_modules/\n", raw(os.path.join(pp6, ".gitignore")))
pp7 = project()
w7 = World()
w7.put(profile(pp7, name="absent", framework="DROP"))
code, out = w7.run()
check("absent: nothing either", code == 0 and not os.path.exists(fwfile(pp7)) and "toyfw" not in json.dumps(load(slp(pp7)) or {}), out)

# true -> false: the file, the two keys and the key env go; a foreign marketplace, a foreign file and the rest stay.
pp8 = project()
w8 = World()
w8.put(profile(pp8, name="flip"))
w8.run()
s = load(slp(pp8)) or {}
s.setdefault("extraKnownMarketplaces", {})["other"] = {"source": {"source": "github", "repo": "toy-org/other"}}
lib.write_json(slp(pp8), s)
with open(os.path.join(pp8, ".claude", "keep-me.json"), "w") as f:
    f.write("{}")
w8.put(profile(pp8, name="flip", framework=False))
code, out = w8.run(apply=False)
check("true -> false, dry-run: says what it would remove, removes nothing",
      os.path.exists(fwfile(pp8)) and "toyfw@toyfw" in sl_keys(pp8)[0] and any("would remove" in l for l in fwlines(out)), out)
code, out = w8.run()
en, mk, ev = sl_keys(pp8)
check("true -> false: exit 0 -- %s" % bang(out), code == 0, out)
check("true -> false: .claude/toyfw.json is gone", not os.path.exists(fwfile(pp8)), "")
check("true -> false: enabledPlugins no longer has toyfw@toyfw, the profile's keep entry stays",
      "toyfw@toyfw" not in en and en.get("keep@toy") is True, en)
check("true -> false: extraKnownMarketplaces.toyfw is gone, the foreign marketplace stays", NAME not in mk and "other" in mk, mk)
check("true -> false: env.LINEAR_API_KEY is gone", "LINEAR_API_KEY" not in ev, ev)
check("true -> false: a foreign file beside it stays", os.path.exists(os.path.join(pp8, ".claude", "keep-me.json")), "")
check("true -> false: no claim of the file is left", claims_of(fwfile(pp8)) == [], claims_of(fwfile(pp8)))
check("true -> false: no key claim of the marketplace is left",
      not [c for c in claims_of(slp(pp8)) if c["at"][:1] == ["extraKnownMarketplaces"]], claims_of(slp(pp8)))
before = (raw(slp(pp8)), raw(owned.path()))
code, out = w8.run()
check("true -> false, again: nothing to do, bytes unchanged, no framework line",
      code == 0 and before == (raw(slp(pp8)), raw(owned.path())) and not fwlines(out), out)

# true -> false with the file edited by hand: it stays, one `!` line; the marketplace key edited: stays, `!`.
pp9 = project()
w9 = World()
w9.put(profile(pp9, name="hand"))
w9.run()
d = load(fwfile(pp9)) or {}
d["rounds"] = 9
lib.write_json(fwfile(pp9), d)
s = load(slp(pp9)) or {}
s.setdefault("extraKnownMarketplaces", {}).setdefault(NAME, {"source": {}}).setdefault("source", {})["path"] = "/somewhere/else"
lib.write_json(slp(pp9), s)
w9.put(profile(pp9, name="hand", framework=False))
code, out = w9.run()
check("hand-edited: the file stays with its edit", (load(fwfile(pp9)) or {}).get("rounds") == 9, os.path.exists(fwfile(pp9)))
check("hand-edited: the marketplace key stays with its edit", sl_keys(pp9)[1].get(NAME, {}).get("source", {}).get("path") == "/somewhere/else",
      sl_keys(pp9)[1])
check("hand-edited: one `!` line each, exit 1",
      code == 1 and len([l for l in bang(out) if "toyfw.json" in l and "left" in l]) == 1
      and len([l for l in bang(out) if "extraKnownMarketplaces" in l and "left" in l]) == 1, (code, bang(out)))

# ------------------------------------------------------------------------------------- 3. the secret, the repo
w10 = World(secrets={})
pp10 = project()
w10.put(profile(pp10, name="nokey"))
code, out = w10.run()
lines = [l for l in out.splitlines() if "NOT RUN, NOT ARMED" in l and "LINEAR_API_KEY" in l]
check("no secret: one NOT RUN, NOT ARMED line, no `!` -- %s" % lines,
      len(lines) == 1 and not lines[0].lstrip().startswith("!") and "(toyfw linear exits 2)" in lines[0]
      and "config/secrets.json" in lines[0], lines)
check("no secret: exit 0, the file and the plugin are still there", code == 0 and os.path.exists(fwfile(pp10))
      and sl_keys(pp10)[0].get("toyfw@toyfw") is True, (code, bang(out)))
check("no secret: no env key written", "LINEAR_API_KEY" not in sl_keys(pp10)[2], sl_keys(pp10)[2])
w11 = World()
pp11 = project()
w11.put(profile(pp11, name="withkey"))
code, out = w11.run()
check("control: with the secret there is no NOT RUN line", "LINEAR_API_KEY" not in out, out)

pp12 = project(gitignore="node_modules/\n", commit_ignore=True)
w12 = World()
w12.put(profile(pp12, name="repoowned", writes_tracked_files=False))
code, out = w12.run()
exclude = raw(os.path.join(pp12, ".git", "info", "exclude")) or b""
check("writes_tracked_files false: the line is in .git/info/exclude, anchored", b"/.claude/toyfw.json" in exclude.splitlines()
      and b"# BEGIN FORGE-FWX (managed by forge)" in exclude.splitlines(), exclude)
check("writes_tracked_files false: .gitignore is intact", raw(os.path.join(pp12, ".gitignore")) == b"node_modules/\n", raw(os.path.join(pp12, ".gitignore")))
check("writes_tracked_files false: the file is written and exit is 0", code == 0 and os.path.exists(fwfile(pp12)), (code, bang(out)))

# ------------------------------------------------------------------------------------------------ 4. the errors
def nothing_written(p):
    return (not os.path.exists(fwfile(p)) and "toyfw@toyfw" not in sl_keys(p)[0] and sl_keys(p)[1] == {}
            and "LINEAR_API_KEY" not in sl_keys(p)[2])


w = World()
pp = project()
w.put(profile(pp, name="nokeep", plugins_keep="DROP"))
code, out = w.run()
check("no plugins_keep: a `!` line that names plugins_keep -- %s" % bang(out), any("plugins_keep" in l for l in bang(out)), out)
check("no plugins_keep: exit 1 and nothing written (no toyfw.json, no enabledPlugins)",
      code == 1 and nothing_written(pp) and "enabledPlugins" not in (load(slp(pp)) or {}), (code, os.path.exists(fwfile(pp))))

forge_json(fw={k: v for k, v in FW.items() if k != "plugin_source"}, integrations=INTEGRATIONS_ON)
w = World()
pp = project()
w.put(profile(pp, name="nosource"))
code, out = w.run()
check("no plugin_source: a `!` line that names it, exit 1, nothing written",
      code == 1 and any("plugin_source" in l for l in bang(out)) and nothing_written(pp), (code, bang(out)))
forge_json(fw=None, integrations=INTEGRATIONS_ON)
w = World()
pp = project()
w.put(profile(pp, name="nosection"))
code, out = w.run()
check("no framework section: the same", code == 1 and any("plugin_source" in l for l in bang(out)) and nothing_written(pp), (code, bang(out)))

forge_json(fw=dict(FW, plugin_source={"source": "git", "url": "https://example.org/toyfw.git"}), integrations=INTEGRATIONS_ON)
w = World()
pp = project()
w.put(profile(pp, name="git"))
code, out = w.run()
check("a source that is not a directory: `!`, exit 1, nothing written",
      code == 1 and any("directory" in l for l in bang(out)) and nothing_written(pp), (code, bang(out)))

forge_json(integrations=INTEGRATIONS_ON)
plugin_dir(marketplace=False)
w = World()
pp = project()
w.put(profile(pp, name="nomarket"))
code, out = w.run()
check("a folder without marketplace.json: `!` naming it, exit 1, nothing written -- %s" % bang(out),
      code == 1 and any("marketplace.json" in l for l in bang(out)) and nothing_written(pp), (code, bang(out)))
plugin_dir(listed="other")
w = World()
pp = project()
w.put(profile(pp, name="unlisted"))
code, out = w.run()
check("a marketplace that lists no plugin of its name: `!`, exit 1, nothing written -- %s" % bang(out),
      code == 1 and any("marketplace.json" in l or "lists" in l for l in bang(out)) and nothing_written(pp), (code, bang(out)))
plugin_dir(listed=None)
w = World()
pp = project()
w.put(profile(pp, name="empty"))
code, out = w.run()
check("a marketplace that lists no plugin at all: the same", code == 1 and nothing_written(pp), (code, bang(out)))
os.makedirs(os.path.join(HOME, "plug", "traversal", ".claude-plugin"), exist_ok=True)
with open(os.path.join(HOME, "plug", "traversal", ".claude-plugin", "marketplace.json"), "w") as f:
    json.dump({"name": "../../evil", "plugins": [{"name": "../../evil", "source": "./"}]}, f)
forge_json(fw=dict(FW, plugin_source={"source": "directory", "path": "~/plug/traversal"}), integrations=INTEGRATIONS_ON)
w = World()
pp = project()
w.put(profile(pp, name="evil"))
code, out = w.run()
check("a plugin name that is not a plain identifier: `!`, exit 1, nothing written outside .claude/",
      code == 1 and bang(out) and not os.path.exists(os.path.join(pp, "evil.json")) and nothing_written(pp)
      and not os.path.exists(os.path.join(TOY, "evil.json")), (code, bang(out)))
forge_json(integrations=INTEGRATIONS_ON)
plugin_dir()

# ------------------------------------------------------------------------------------ 5. forge uninstall --project
w = World()
pp = project()
w.put(profile(pp, name="gone"))
w.run()
check("uninstall: setup, the file is there", os.path.exists(fwfile(pp)) and "toyfw@toyfw" in sl_keys(pp)[0], "")
w.drop("gone")
sync.CFG, lib.PROFILES = w.cfg, w.pdir
out = io.StringIO()
with contextlib.redirect_stdout(out):
    code = uninstall.main(argparse.Namespace(integration=None, project="gone", apply=True))
check("uninstall --project: exit 0 -- %s" % sandbox.tail(out.getvalue(), 3), code == 0, out.getvalue())
check("uninstall --project: the file is gone", not os.path.exists(fwfile(pp)), out.getvalue())
en, mk, ev = sl_keys(pp)
check("uninstall --project: the marketplace and the plugin entry are gone", NAME not in mk and "toyfw@toyfw" not in en, (en, mk))
check("uninstall --project: no claim of the file or of the keys is left",
      claims_of(fwfile(pp)) == [] and not [c for c in claims_of(slp(pp)) if c["at"][:1] == ["extraKnownMarketplaces"]], "")

# ------------------------------------------------------------------------------------------- 6. branch B: the registry
install_fake()
reset_registry()
want_argv = ["plugin", "marketplace", "add", plugin, "--scope", "local"]
w = World()
pp = project()
w.put(profile(pp, name="regb"))
code, out = w.run(apply=False)
check("branch B, dry-run: no call to claude", calls() == [], calls())
check("branch B, dry-run: the line says the command it would run, no `!`, exit 0",
      code == 0 and any("marketplace add" in l and "--scope local" in l and "would" in l for l in out.splitlines()) and not bang(out), (code, out))
code, out = w.run()
check("branch B: the first apply calls `claude plugin marketplace add <path> --scope local` once, from the project's folder",
      [c["argv"] for c in calls()] == [want_argv] and [os.path.realpath(c["cwd"]) for c in calls()] == [os.path.realpath(pp)], calls())
code, out = w.run()
check("branch B: two applies make one `marketplace add` -- calls %d" % len(calls()), len(calls()) == 1, calls())
pp_b = project()
w.put(profile(pp_b, name="regb2"))
code, out = w.run()
check("branch B: a second project finds the machine registry already holding the marketplace: still one call",
      len(calls()) == 1 and code == 0, calls())
reset_registry()
os.remove(os.path.join(BIN, "claude"))
w = World()
pp = project()
w.put(profile(pp, name="noclaude"))
code, out = w.run()
check("no claude on PATH, apply: a `!` line that holds the command as the fix, exit 1",
      code == 1 and any("claude plugin marketplace add" in l and "--scope local" in l for l in bang(out)), (code, bang(out)))
check("no claude on PATH: the file and the settings are still written (the marketplace entry is the machine's, the rest the project's)",
      os.path.exists(fwfile(pp)) and sl_keys(pp)[0].get("toyfw@toyfw") is True, "")
install_fake(exit_code=3)
reset_registry()
w = World()
pp = project()
w.put(profile(pp, name="failing"))
code, out = w.run()
check("claude exits 3: a `!` line, exit 1", code == 1 and bang(out), (code, bang(out)))
install_fake()
reset_registry()
# framework false never calls claude, and turning it off does not remove the machine's entry.
w = World()
pp = project()
w.put(profile(pp, name="off2", framework=False))
w.run()
check("false: no call to claude", calls() == [], calls())
w.put(profile(pp, name="off2"))
w.run()
n_after_on = len(calls())
w.put(profile(pp, name="off2", framework=False))
w.run()
check("true -> false: the machine's registry entry is left (it is shared by every project)",
      n_after_on == 1 and len(calls()) == 1 and os.path.exists(REGISTRY_FILE) and NAME in load(REGISTRY_FILE), calls())
os.remove(os.path.join(BIN, "claude"))

# --------------------------------------------------------------------------- 7. the model seed (m15)
import glob  # noqa: E402
import importlib.util  # noqa: E402


def seed_diff(repo):
    """(why it cannot be compared, or None; the roles whose models differ): examples/forge.json's framework.models
    against the DEFAULTS["models"] of the single lib/<package>/config.py of the framework repo at `repo`."""
    cfgs = glob.glob(os.path.join(repo, "lib", "*", "config.py"))
    if len(cfgs) != 1:
        return "%s has no single lib/<package>/config.py (found %d)" % (repo, len(cfgs)), None
    spec = importlib.util.spec_from_file_location("framework_config_under_test_%d" % n_checks[0], cfgs[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seed = load(os.path.join(sandbox.FORGE, "examples", "forge.json"))["framework"]["models"]
    want = mod.DEFAULTS["models"]
    return None, {r: (seed.get(r), want.get(r)) for r in set(seed) | set(want) if seed.get(r) != want.get(r)}


def toy_repo(models):
    """A toy framework repo in the temp world whose config.py holds DEFAULTS = {"models": models}."""
    d = os.path.join(TOY, "toyrepo%d" % n_checks[0])
    os.makedirs(os.path.join(d, "lib", "toyfw"))
    with open(os.path.join(d, "lib", "toyfw", "config.py"), "w") as f:
        f.write("DEFAULTS = {\"models\": %r}\n" % (models,))
    return d


# Without the real repo the comparison runs against a toy one: the same models as the seed (equal), and one alias
# changed (the control: it must be found). This proves the comparison, not the real DEFAULTS.
toy_seed = load(os.path.join(sandbox.FORGE, "examples", "forge.json"))["framework"]["models"]
why, diff = seed_diff(toy_repo(toy_seed))
check("m15 (toy repo): equal models compare equal, over %d roles" % len(toy_seed), why is None and diff == {} and len(toy_seed) > 0, (why, diff))
changed = json.loads(json.dumps(toy_seed))
role = sorted(changed)[0]
changed[role]["small"] = "haiku" if changed[role]["small"] != "haiku" else "sonnet"
why, diff = seed_diff(toy_repo(changed))
check("m15 control (toy repo): one alias changed is found, naming its role", why is None and list(diff) == [role], (why, diff))
why, diff = seed_diff(os.path.join(TOY, "no-such-repo"))
check("m15 control: a repo without config.py cannot be compared, and says so", why is not None and diff is None, (why, diff))

# The real repo, when FRAMEWORK_REPO names it: an extra run, never a condition of the suite.
repo = os.environ.get("FRAMEWORK_REPO")
if repo:
    why, diff = seed_diff(repo)
    check("m15: examples/forge.json's framework.models equal the framework repo's DEFAULTS", why is None and diff == {}, (why, diff))

# ------------------------------------------------------------------ 7. 3.6 U3b: baseRef and the four profile fields
forge_json(integrations=INTEGRATIONS_ON)
plugin_dir()


def worktree_of(p):
    return (load(slp(p)) or {}).get("worktree")


def base_claims(p):
    return [c for c in claims_of(slp(p)) if c["at"][:1] == ["worktree"]]


# baseRef: a `true` profile gets it, a `false` one nothing, true -> false takes it out, a foreign worktree key stays.
ppb = project()
wb = World()
wb.put(profile(ppb, name="baseref"))
code, out = wb.run(apply=False)
check("baseRef: a dry-run writes nothing", not os.path.exists(slp(ppb)) and "baseRef" in out, out)
code, out = wb.run()
check("baseRef: a `true` profile gets worktree.baseRef \"head\" -- worktree %s" % worktree_of(ppb),
      worktree_of(ppb) == {"baseRef": "head"}, worktree_of(ppb))
check("baseRef: the summary line names it", any("worktree.baseRef" in l for l in out.splitlines() if "overrides ->" in l), out)
check("baseRef: it is an owned key claim", [c["kind"] for c in base_claims(ppb)] == ["key"] and base_claims(ppb)[0]["at"] == ["worktree", "baseRef"],
      base_claims(ppb))
before = raw(slp(ppb))
code, out = wb.run()
check("baseRef: a second apply leaves the file byte-identical", raw(slp(ppb)) == before and code == 0, out)
s = load(slp(ppb))
s.setdefault("worktree", {})["symlinkDirectories"] = ["node_modules"]
lib.write_json(slp(ppb), s)
wb.put(profile(ppb, name="baseref", framework=False))
code, out = wb.run()
check("baseRef: true -> false takes baseRef out and leaves the foreign worktree key -- worktree %s" % worktree_of(ppb),
      code == 0 and worktree_of(ppb) == {"symlinkDirectories": ["node_modules"]} and not base_claims(ppb), (code, out))
wb.put(profile(ppb, name="baseref"))
wb.run()
check("baseRef: back to true, it is there again", (worktree_of(ppb) or {}).get("baseRef") == "head", worktree_of(ppb))
ppo = project()
wo = World()
wo.put(profile(ppo, name="baserefoff", framework=False))
wo.run()
check("baseRef: a `false` profile gets no worktree key", "worktree" not in (load(slp(ppo)) or {}), load(slp(ppo)))
ppa = project()
wa = World()
wa.put(profile(ppa, name="baserefabsent", framework="DROP"))
wa.run()
check("baseRef: a profile without the field gets no worktree key", "worktree" not in (load(slp(ppa)) or {}), load(slp(ppa)))
pph = project()
wh = World()
wh.put(profile(pph, name="basereftwo"))
wh.run()
s = load(slp(pph))
s.setdefault("worktree", {})["baseRef"] = "fresh"
lib.write_json(slp(pph), s)
wh.put(profile(pph, name="basereftwo", framework=False))
code, out = wh.run()
check("baseRef: edited by hand, it stays and one `!` line names it, exit 1",
      worktree_of(pph) == {"baseRef": "fresh"} and code == 1
      and len([l for l in bang(out) if "worktree.baseRef" in l and "left" in l]) == 1, (worktree_of(pph), code, bang(out)))
ppn = project()
wn = World()
wn.put(profile(ppn, name="baserefshape"))
wn.run()
s = load(slp(ppn))
s["worktree"] = "by hand"
lib.write_json(slp(ppn), s)
code, out = wn.run()
check("baseRef: a worktree that is not an object is left alone and named, not crashed on -- %s" % bang(out),
      load(slp(ppn)).get("worktree") == "by hand" and any("worktree is not an object" in l for l in out.splitlines()), (code, out))

# profile_error: the four fields, each bad shape rejected and each good one accepted (a control that the rows do not reject all).
GOOD_APP = {"up": "make up", "run": "", "down": "make down", "url": "http://localhost:3000"}
GOOD_IMG = {"dockerfile": "Dockerfile.ui", "expect": "Sign in"}
for label, field, value in (("checks_quick list", "checks_quick", ["pnpm tsc", "pnpm lint"]), ("checks_quick empty", "checks_quick", []),
                            ("default_branch_protected true", "default_branch_protected", True),
                            ("default_branch_protected false", "default_branch_protected", False),
                            ("app_run", "app_run", GOOD_APP),
                            ("app_run with login and container", "app_run", dict(GOOD_APP, login="make login", container=True)),
                            ("app_run with ready", "app_run", dict(GOOD_APP, ready="Dashboard")),
                            ("app_run with ready_timeout_s 45", "app_run", dict(GOOD_APP, ready_timeout_s=45)),
                            ("app_run with ready_timeout_s 12.5", "app_run", dict(GOOD_APP, ready_timeout_s=12.5)),
                            ("app_run with ready and ready_timeout_s", "app_run", dict(GOOD_APP, ready="Dashboard", ready_timeout_s=45)),
                            ("ui_image", "ui_image", GOOD_IMG),
                            ("ui_image in a subfolder", "ui_image", dict(GOOD_IMG, dockerfile="ui/Dockerfile"))):
    why = lib.profile_error({"project": "x", "project_path": "/x", field: value})
    check("profile_error accepts %s -- %s" % (label, why), why is None, why)
for label, field, value, word in (
        ("checks_quick as a string", "checks_quick", "pnpm tsc", "checks_quick"),
        ("checks_quick with a non-string", "checks_quick", ["pnpm tsc", 3], "checks_quick"),
        ("default_branch_protected \"yes\"", "default_branch_protected", "yes", "default_branch_protected"),
        ("app_run as a string", "app_run", "make up", "app_run"),
        ("app_run without url", "app_run", {k: v for k, v in GOOD_APP.items() if k != "url"}, "url"),
        ("app_run without up", "app_run", {k: v for k, v in GOOD_APP.items() if k != "up"}, "up"),
        ("app_run without run", "app_run", {k: v for k, v in GOOD_APP.items() if k != "run"}, "run"),
        ("app_run without down", "app_run", {k: v for k, v in GOOD_APP.items() if k != "down"}, "down"),
        ("app_run with a numeric url", "app_run", dict(GOOD_APP, url=3000), "url"),
        ("app_run with login as a bool", "app_run", dict(GOOD_APP, login=True), "login"),
        ("app_run with container \"yes\"", "app_run", dict(GOOD_APP, container="yes"), "container"),
        ("app_run with a key it has no slot for", "app_run", dict(GOOD_APP, extra="x"), "extra"),
        ("app_run with an empty ready", "app_run", dict(GOOD_APP, ready=""), "ready"),
        ("app_run with a blank ready", "app_run", dict(GOOD_APP, ready="  "), "ready"),
        ("app_run with a numeric ready", "app_run", dict(GOOD_APP, ready=3), "ready"),
        ("app_run with ready_timeout_s true", "app_run", dict(GOOD_APP, ready_timeout_s=True), "ready_timeout_s"),
        ("app_run with ready_timeout_s 0", "app_run", dict(GOOD_APP, ready_timeout_s=0), "ready_timeout_s"),
        ("app_run with ready_timeout_s 0.0", "app_run", dict(GOOD_APP, ready_timeout_s=0.0), "ready_timeout_s"),
        ("app_run with ready_timeout_s -1", "app_run", dict(GOOD_APP, ready_timeout_s=-1), "ready_timeout_s"),
        ("app_run with ready_timeout_s \"30\"", "app_run", dict(GOOD_APP, ready_timeout_s="30"), "ready_timeout_s"),
        ("app_run with ready_timeout_s infinity", "app_run", dict(GOOD_APP, ready_timeout_s=float("inf")), "ready_timeout_s"),
        ("ui_image as a string", "ui_image", "Dockerfile", "ui_image"),
        ("ui_image without dockerfile", "ui_image", {"expect": "Sign in"}, "dockerfile"),
        ("ui_image without expect", "ui_image", {"dockerfile": "Dockerfile.ui"}, "expect"),
        ("ui_image with an empty expect", "ui_image", dict(GOOD_IMG, expect=""), "expect"),
        ("ui_image with an empty dockerfile", "ui_image", dict(GOOD_IMG, dockerfile=""), "dockerfile"),
        ("ui_image with dockerfile ../x", "ui_image", dict(GOOD_IMG, dockerfile="../x"), "dockerfile"),
        ("ui_image with dockerfile a/../../x", "ui_image", dict(GOOD_IMG, dockerfile="a/../../x"), "dockerfile"),
        ("ui_image with an absolute dockerfile", "ui_image", dict(GOOD_IMG, dockerfile="/etc/passwd"), "dockerfile"),
        ("ui_image with a key it has no slot for", "ui_image", dict(GOOD_IMG, extra="x"), "extra")):
    why = lib.profile_error({"project": "x", "project_path": "/x", field: value})
    check("profile_error rejects %s, naming %s -- %s" % (label, word, why), why is not None and word in why, why)
bad = World()
ppbad = project()
bad.put(profile(ppbad, name="badimg", ui_image={"expect": "Sign in"}))
code, out = bad.run()
check("a profile with a bad ui_image: the run says so and writes no framework file -- exit %d" % code,
      code != 0 and "ui_image" in out and not os.path.exists(fwfile(ppbad)), out)

# The two fields reach .claude/fwx.json; absent they are false and null.
ppf = project()
wf = World()
wf.put(profile(ppf, name="fields", default_branch_protected=True, ui_image=GOOD_IMG, app_run=GOOD_APP, checks_quick=["pnpm tsc"]))
code, out = wf.run()
pf = (load(fwfile(ppf)) or {}).get("project", {})
check("fields: default_branch_protected true reaches project.default_branch_protected -- %s" % pf.get("default_branch_protected", "missing from fwx.json"),
      pf.get("default_branch_protected") is True, pf)
check("fields: ui_image reaches project.ui_image", pf.get("ui_image") == GOOD_IMG, pf.get("ui_image"))
check("fields: app_run and checks_quick still reach the file", pf.get("app_run") == GOOD_APP and pf.get("checks_quick") == ["pnpm tsc"], pf)
ppr = project()
wr = World()
READY_APP = dict(GOOD_APP, ready="Dashboard", ready_timeout_s=12.5)
wr.put(profile(ppr, name="readyapp", app_run=READY_APP))
code, out = wr.run()
pr = (load(fwfile(ppr)) or {}).get("project", {})
check("fields: app_run.ready and ready_timeout_s reach project.app_run unchanged -- %s" % pr.get("app_run", "missing from fwx.json"),
      pr.get("app_run") == READY_APP, pr.get("app_run"))
ppd = project()
wd = World()
wd.put(profile(ppd, name="defaults"))
wd.run()
pd = (load(fwfile(ppd)) or {}).get("project", {})
check("fields: without them, project.default_branch_protected is false and project.ui_image null -- %s" % {k: pd.get(k, "missing") for k in ("default_branch_protected", "ui_image")},
      pd.get("default_branch_protected") is False and "ui_image" in pd and pd["ui_image"] is None, pd)

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL", f)
print("%d checks, %d failed" % (n_checks[0], len(failures)))
if failures:
    sys.exit(1)
