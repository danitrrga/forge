#!/usr/bin/env python3
"""The framework's permissions step of the generator (forge/framework.py `permissions`, `permission_errors`,
`with_permissions`, called from forge/sync.py), 3.6 U2a.

For a profile with `framework: true`, `forge sync` reads config/framework-permissions.json (schema 1: `allow` rows with
`rule` and `roles`, `not_allowed`, `only_daniel` prefixes), lints it, and writes its `allow` rules into the project's
settings.local.json `permissions.allow` by the path the profile's own permissions take (so the owned claims of
forge/skills.py write them and take them out). It also writes `permissions.additionalDirectories` = the main checkout, so a
session in a linked worktree may reach it (3.6 Appendix B).
  * true: exactly the union of the profile's own allow rules and the list's, a `+ allow <rule>  (framework: <roles>)` line
    per rule not in the file yet, `+ additionalDirectories <path>` for the main checkout; false or no field: nothing.
  * true -> false: only what the list wrote goes (owned item claims); a rule put by hand stays.
  * no list file: one line `framework permissions -> NOT RUN, NOT ARMED: config/framework-permissions.json missing`, exit 0,
    no `!`; the main checkout is still written.
  * lint, each class a `!` line, exit 1 and nothing written for that profile (a settings.local.json that was there stays
    byte for byte): a tool without specifier (`Edit`), `Bash(*)`, `Bash(python3:*)`, `Agent`, `Workflow`; a rule that overlaps an
    `only_daniel` prefix or a `production.commands` of the profile (one is a prefix of the other); a role that is not a key of
    `framework.models`; malformed JSON; a schema other than 1.

Everything runs in-process against a toy HOME, a toy forge.json, toy profiles and a toy config/. `claude` is a fake
directory alone on PATH (order 10); no real project, config or HOME is read.

Seen failing on b28e24c (master, this file as it is, run before the step existed): 77 of 101 checks red, the other 24 are
controls that pass there (a false profile gets nothing, a dry-run writes nothing, the lint-less cases that need no list). First messages:
  union: "union: the apply writes exactly the profile's rule and the list's -- ['Bash(git status:*)']"
  dry-run line: "dry-run: `+ allow Bash(fwx linear comment:*)  (framework: orchestrator)` is printed -- []"
  additionalDirectories: "dirs: a true profile gets the main checkout -- None"
  NOT RUN: "no list: one NOT RUN, NOT ARMED line -- []"
  lint: "lint Bash(*): a `!` line naming the list, exit 1 -- []" (exit 0: the broad rule is written)
  unit table: "permission_errors exists -- AttributeError: module 'forge.framework' has no attribute 'permission_errors'"
Negative controls on the finished code, each mutation put back from a copy, the checks that went red (17 mutations, each red):
no lint at all (crash: the file did not finish); a lint error that does not stop the profile (20: "nothing written for the profile");
rules not passed to settings.local.json (11); main checkout not passed (5); no `+` lines (3); no NOT RUN line (1); no production
overlap (4); no only_daniel overlap (6) or only one direction of it (2); no role check (2); no runner check (13: `python3:*` and the
rest); no bare-tool check (11: `Edit`, `Agent`, `Workflow`); no `*`-only check (6: `Bash(*)`, `Monitor(*)`); a false profile served
(9); schema not checked (2); roles not required (crash); malformed JSON ignored (2).
"""
import contextlib
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("fwperm-test-")
HOME = os.path.join(TOY, "home")
BIN = os.path.join(TOY, "bin")
os.makedirs(HOME)
os.makedirs(BIN)
for tool in ("python3", "git"):  # order 10: only the fake directory on PATH
    os.symlink(shutil.which(tool), os.path.join(BIN, tool))
os.environ["HOME"] = HOME
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
from forge import framework, owned, sync  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")  # this checkout may be a linked worktree, which never writes

failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:700]))


NAME = "toyfw"
ROLES = ("orchestrator", "executor", "reviewer")
FW = {"models": {r: {"small": "sonnet", "normal": "sonnet", "big": "sonnet"} for r in ROLES},
      "limits": {"on": False, "per_project": {}, "ram_min_free_gb": 0}, "rounds": 4, "critique_rounds_unattended": 2,
      "factory": {}, "weekly": {"on": True, "min_sessions": 5}, "paths": {}, "linear": {"labels": {}},
      "plugin_source": {"source": "directory", "path": "~/plug/" + NAME}}
_n = [0]


def forge_json(fw=FW):
    _n[0] += 1
    doc = {"integrations": {k: False for k in lib.INTEGRATIONS}, "framework": fw}
    path = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()


def plugin_dir():
    d = os.path.join(HOME, "plug", NAME)
    os.makedirs(os.path.join(d, ".claude-plugin"), exist_ok=True)
    with open(os.path.join(d, ".claude-plugin", "marketplace.json"), "w") as f:
        json.dump({"name": NAME, "owner": {"name": "toy"}, "plugins": [{"name": NAME, "source": "./"}]}, f)


_p = [0]


def project():
    _p[0] += 1
    d = os.path.join(TOY, "toyproj%d" % _p[0])
    os.makedirs(d)
    sandbox.git(d, "init", "-q", "-b", "main")
    return d


def profile(ppath, name, **over):
    p = {"project": name, "project_path": ppath, "servers": [], "plugins_keep": ["keep@toy"], "skills_keep": ["*"],
         "framework": True, "checks": ["make test"]}
    p.update(over)
    return {k: v for k, v in p.items() if v != "DROP"}


_w = [0]


class World:
    """A toy config/ (registry, secrets link, profiles, and the permissions list when `perms` is given)."""

    def __init__(self, perms=None):
        _w[0] += 1
        self.base = os.path.join(TOY, "world%d" % _w[0])
        self.cfg = os.path.join(self.base, "config")
        self.pdir = os.path.join(self.cfg, "profiles")
        os.makedirs(self.pdir)
        with open(os.path.join(self.cfg, "mcp-registry.json"), "w") as f:
            f.write('{"servers": {}}')
        with open(os.path.join(self.base, "secrets.json"), "w") as f:
            f.write("{}")
        os.symlink(os.path.join(self.base, "secrets.json"), os.path.join(self.cfg, "secrets.json"))
        with open(os.path.join(self.cfg, "project-relocations.json"), "w") as f:
            f.write('{"relocations": []}')
        self.names = set()
        if perms is not None:
            self.perms(perms)

    def perms(self, doc):
        """The list file: a dict is written as JSON, a str as it is, None takes the file away."""
        path = os.path.join(self.cfg, "framework-permissions.json")
        if doc is None:
            if os.path.exists(path):
                os.remove(path)
            return
        with open(path, "w") as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))

    def put(self, prof):
        self.names.add(prof["project"])
        with open(os.path.join(self.pdir, prof["project"] + ".claude.json"), "w") as f:
            json.dump(prof, f)

    def run(self, apply=True):
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
        return code, out.getvalue() + err.getvalue()


def slp(p):
    return os.path.join(p, ".claude", "settings.local.json")


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


def perms_of(p):
    return (load(slp(p)) or {}).get("permissions")


def allow_of(p):
    return (perms_of(p) or {}).get("allow")


def bang(text):
    return [l for l in text.splitlines() if l.lstrip().startswith("!")]


def claims_of(p):
    return owned.previous(slp(p))[0]


def row(rule, roles=("orchestrator",), **extra):
    return dict({"rule": rule, "roles": list(roles), "why": "toy", "measured": "toy-run/O7"}, **extra)


R1, R2 = "Bash(fwx linear comment:*)", "Bash(fwx linear create:*)"
LIST = {"_doc": "toy", "schema": 1,
        "allow": [row(R1), row(R2, ("orchestrator", "executor"))],
        "not_allowed": [{"action": "C2", "lever": "classifier", "owner": "3.x", "why": "toy", "measured": "toy-run/C2"}],
        "only_daniel": [{"prefix": "Bash(git push", "why": "toy"}, {"prefix": "Edit(hooks/", "why": "toy"}]}

# A fake `claude` that does nothing and exits 0: the marketplace registration the framework step runs on --apply (the
# real one is unreachable, PATH being this directory alone), so no `!` line comes from it.
with open(os.path.join(BIN, "claude"), "w") as f:
    f.write("#!%s\nimport sys\nsys.exit(0)\n" % sys.executable)
os.chmod(os.path.join(BIN, "claude"), 0o755)
forge_json()
plugin_dir()

# ------------------------------------------------------------------------------------------ 1. union and removal
pp = project()
w = World(LIST)
w.put(profile(pp, "union", permissions={"allow": ["Bash(git status:*)"]}))
code, out = w.run(apply=False)
check("dry-run: exit 0 and no `!` -- %s" % bang(out), code == 0 and not bang(out), out)
check("dry-run: `+ allow %s  (framework: orchestrator)` is printed -- %s" % (R1, [l for l in out.splitlines() if "+ allow" in l]),
      "  + allow %s  (framework: orchestrator)" % R1 in out.splitlines(), out)
check("dry-run: the rule of two roles names both -- %s" % [l for l in out.splitlines() if R2 in l],
      "  + allow %s  (framework: orchestrator, executor)" % R2 in out.splitlines(), out)
check("dry-run: writes nothing", not os.path.exists(slp(pp)), os.listdir(pp))
code, out = w.run()
check("union: the apply writes exactly the profile's rule and the list's -- %s" % allow_of(pp),
      allow_of(pp) == ["Bash(git status:*)", R1, R2], allow_of(pp))
check("union: exit 0", code == 0, out)
check("union: each list rule is an owned item claim", {c["at"][2] for c in claims_of(pp) if c["kind"] == "item" and c["at"][:2] == ["permissions", "allow"]}
      >= {R1, R2}, claims_of(pp))
before = raw(slp(pp))
code, out = w.run()
check("union: a second apply is byte-identical and prints no `+ allow` -- %s" % [l for l in out.splitlines() if "+ allow" in l],
      raw(slp(pp)) == before and "+ allow" not in out and code == 0, out)
check("union: the list's other sections (not_allowed, only_daniel) write nothing", not any(
    r in (allow_of(pp) or []) for r in ("Bash(git push", "Edit(hooks/")) and "C2" not in str(perms_of(pp)), perms_of(pp))

# the same list on a profile that is false, and on one without the field: nothing, and the list is not even read.
for label, over in (("false", {"framework": False}), ("no field", {"framework": "DROP"})):
    ppo = project()
    wo = World(LIST)
    wo.put(profile(ppo, "off" + label.replace(" ", ""), **over))
    code, out = wo.run()
    check("%s profile: no permissions key written -- %s" % (label, perms_of(ppo)), perms_of(ppo) is None and "+ allow" not in out
          and "permissions ->" not in out, (perms_of(ppo), out))

# true -> false: only the list's rules go; a rule put by hand stays.
ppt = project()
wt = World(LIST)
wt.put(profile(ppt, "flip"))
wt.run()
s = load(slp(ppt))
s.setdefault("permissions", {}).setdefault("allow", []).append("Bash(ls:*)")
lib.write_json(slp(ppt), s)
wt.put(profile(ppt, "flip", framework=False))
code, out = wt.run()
check("true -> false: the list's rules go and the hand-set one stays -- %s" % allow_of(ppt), allow_of(ppt) == ["Bash(ls:*)"], (allow_of(ppt), out))
check("true -> false: the main checkout goes too -- %s" % perms_of(ppt), "additionalDirectories" not in (perms_of(ppt) or {}), perms_of(ppt))
wt.put(profile(ppt, "flip"))
wt.run()
check("false -> true: the rules are back, the hand-set one kept once -- %s" % allow_of(ppt), allow_of(ppt) == ["Bash(ls:*)", R1, R2], allow_of(ppt))

# a rule the list adds and a later edit of the list: a rule dropped from the list goes, the others stay.
wt.perms(dict(LIST, allow=[row(R1)]))
wt.run()
check("list shrinks: the dropped rule goes, the kept one stays -- %s" % allow_of(ppt), allow_of(ppt) == ["Bash(ls:*)", R1], allow_of(ppt))

# ------------------------------------------------------------------------------------------ 2. additionalDirectories
ppd = project()
wd = World(LIST)
wd.put(profile(ppd, "dirs"))
code, out = wd.run(apply=False)
check("dirs: the dry-run prints `+ additionalDirectories <main checkout>` -- %s" % [l for l in out.splitlines() if "additionalDirectories" in l],
      any(l.startswith("  + additionalDirectories ") and os.path.realpath(ppd) in l for l in out.splitlines()), out)
wd.run()
check("dirs: a true profile gets the main checkout -- %s" % (perms_of(ppd) or {}).get("additionalDirectories"),
      (perms_of(ppd) or {}).get("additionalDirectories") == [os.path.realpath(ppd)], perms_of(ppd))
check("dirs: it is an owned item claim", any(c["kind"] == "item" and c["at"] == ["permissions", "additionalDirectories", os.path.realpath(ppd)]
                                              for c in claims_of(ppd)), claims_of(ppd))
pdl = project()
wl = World(LIST)
wl.put(profile(pdl, "dirsown", permissions={"additionalDirectories": ["/tmp/own-dir"]}))
wl.run()
check("dirs: the profile's own directory stays beside the main checkout -- %s" % (perms_of(pdl) or {}).get("additionalDirectories"),
      (perms_of(pdl) or {}).get("additionalDirectories") == ["/tmp/own-dir", os.path.realpath(pdl)], perms_of(pdl))
code, out = wl.run()
check("dirs: a second apply prints no `+ additionalDirectories`", "+ additionalDirectories" not in out and code == 0, out)
pds = project()
ws = World(LIST)
ws.put(profile(pds, "dirsoff", framework=False, permissions={"additionalDirectories": ["/tmp/own-dir"]}))
ws.run()
check("dirs: a false profile keeps only its own -- %s" % perms_of(pds), (perms_of(pds) or {}).get("additionalDirectories") == ["/tmp/own-dir"], perms_of(pds))

# ------------------------------------------------------------------------------------------ 3. no list file
ppn = project()
wn = World(None)
wn.put(profile(ppn, "nolist"))
code, out = wn.run()
NR = "   framework permissions -> NOT RUN, NOT ARMED: config/framework-permissions.json missing"
check("no list: one NOT RUN, NOT ARMED line -- %s" % [l for l in out.splitlines() if "permissions ->" in l],
      [l for l in out.splitlines() if "permissions ->" in l] == [NR], out)
check("no list: exit 0 and no `!` -- %s" % bang(out), code == 0 and not bang(out), out)
check("no list: no allow rule, the main checkout still written -- %s" % perms_of(ppn),
      "allow" not in (perms_of(ppn) or {}) and (perms_of(ppn) or {}).get("additionalDirectories") == [os.path.realpath(ppn)], perms_of(ppn))
ppf = project()
wf = World(None)
wf.put(profile(ppf, "nolistoff", framework=False))
code, out = wf.run()
check("no list: a false profile prints no such line", "permissions ->" not in out and code == 0, out)

# ------------------------------------------------------------------------------------------ 4. lint, through the generator
BAD = [
    ("Bash(*)", dict(LIST, allow=[row("Bash(*)")])),
    ("Bash(python3:*)", dict(LIST, allow=[row("Bash(python3:*)")])),
    ("Bash(python3 *)", dict(LIST, allow=[row("Bash(python3 *)")])),
    ("Bash(npx:*)", dict(LIST, allow=[row("Bash(npx:*)")])),
    ("Edit (no specifier)", dict(LIST, allow=[row("Edit")])),
    ("Agent", dict(LIST, allow=[row("Agent")])),
    ("Workflow", dict(LIST, allow=[row("Workflow")])),
    ("Monitor(*)", dict(LIST, allow=[row("Monitor(*)")])),
    ("Bash(git:*) against only_daniel Bash(git push", dict(LIST, allow=[row("Bash(git:*)")])),
    ("Bash(git push origin fwx/*) inside only_daniel", dict(LIST, allow=[row("Bash(git push origin fwx/*)")])),
    ("Edit(hooks/guard.py) inside only_daniel Edit(hooks/", dict(LIST, allow=[row("Edit(hooks/guard.py)")])),
    ("a role that is not a key of framework.models", dict(LIST, allow=[row(R1, ("orchestrator", "nobody"))])),
    ("a row without roles", dict(LIST, allow=[{"rule": R1, "why": "toy"}])),
    ("a rule that is not a string", dict(LIST, allow=[row(42)])),
    ("schema 2", dict(LIST, schema=2)),
    ("allow is not a list", dict(LIST, allow={"rule": R1})),
    ("malformed JSON", '{"schema": 1, "allow": ['),
    ("not an object", "[1, 2]"),
]
for label, bad in BAD:
    pb = project()
    wb = World(bad)
    wb.put(profile(pb, "lint", production={"branches": [], "commands": []}))
    code, out = wb.run()
    lines = [l for l in bang(out) if "permissions" in l]
    check("lint %s: a `!` line naming the list, exit 1 -- %s" % (label, lines), len(lines) == 1 and code == 1, (code, out))
    check("lint %s: nothing written for the profile" % label, not os.path.exists(slp(pb)) and not os.path.exists(os.path.join(pb, ".claude", NAME + ".json")),
          os.listdir(pb))

# production.commands of the profile: the overlap is per profile, so the other profile of the same list is served.
pa, pc = project(), project()
wp = World(dict(LIST, allow=[row("Bash(deploy staging:*)"), row(R1)]))
wp.put(profile(pa, "prodhit", production={"branches": ["release"], "commands": ["deploy "]}))
wp.put(profile(pc, "prodmiss", production={"branches": ["release"], "commands": ["ship "]}))
code, out = wp.run()
check("lint production.commands: the profile that has `deploy ` gets a `!` line and nothing -- %s" % bang(out),
      any("deploy" in l and "permissions" in l for l in bang(out)) and not os.path.exists(slp(pa)) and code == 1, (code, out))
check("lint production.commands: the other profile still gets the list -- %s" % allow_of(pc),
      allow_of(pc) == ["Bash(deploy staging:*)", R1], allow_of(pc))

# a settings.local.json that was there stays byte for byte when the list turns bad; the list file is only read for true profiles.
pk = project()
wk = World(LIST)
wk.put(profile(pk, "keep"))
wk.run()
good = raw(slp(pk))
wk.perms(dict(LIST, allow=[row(R1), row("Bash(*)")]))
code, out = wk.run()
check("lint: the file that was there stays byte for byte -- exit %d" % code, raw(slp(pk)) == good and code == 1, (code, out))
pz = project()
wz = World('{"broken')
wz.put(profile(pz, "falselint", framework=False))
code, out = wz.run()
check("lint: a false profile never reads the list -- %s" % bang(out), code == 0 and not bang(out), out)

# ------------------------------------------------------------------------------------------ 5. permission_errors, the table
MODELS = set(ROLES)


def perr(*args):
    """framework.permission_errors, or a failure and [] where the function does not exist yet."""
    fn = getattr(framework, "permission_errors", None)
    if fn is None and not any(f.startswith("permission_errors exists") for f in failures):
        check("permission_errors exists", False, "AttributeError: module 'forge.framework' has no attribute 'permission_errors'")
    return fn(*args) if fn else []


GOOD_RULES = ["Bash(fwx linear comment:*)", "Bash(git status:*)", "Workflow(fwx:execute)", "Agent(reviewer)", "Edit(src/app.py)",
              "Bash(python3 tests/test_probe.py)", "mcp__linear-forge__save_comment", "Bash(pnpm test:*)"]
for rule in GOOD_RULES:
    errs = perr(dict(LIST, allow=[row(rule)]), MODELS, [])
    check("table: %s is accepted -- %s" % (rule, errs), errs == [], errs)
check("table: control, the toy list itself has no error", perr(LIST, MODELS, []) == [], perr(LIST, MODELS, []))
for rule in ["Bash", "Bash()", "Bash(*)", "Bash(:*)", "Read(*)", "Bash(python3:*)", "Bash(python:*)", "Bash(node:*)", "Bash(bash *)", "Bash(npm:*)",
             "Bash(pnpm *)", "Bash(uv:*)", "Agent", "Agent()", "Agent(*)", "Monitor", "Workflow", "Workflow(*)", "Write", "WebFetch", "mcp__linear-forge", "mcp__linear-forge__*"]:
    errs = perr(dict(LIST, allow=[row(rule)]), MODELS, [])
    check("table: %s is rejected -- %s" % (rule, errs), len(errs) == 1 and rule in errs[0], errs)
for rule, prod in [("Bash(deploy:*)", ["deploy "]), ("Bash(deploy prod now:*)", ["deploy prod"]), ("Bash(kubectl apply:*)", ["kubectl apply -f"])]:
    errs = perr(dict(LIST, allow=[row(rule)]), MODELS, prod)
    check("table: %s overlaps production %s -- %s" % (rule, prod, errs), len(errs) == 1 and "production" in errs[0], errs)
errs = perr(dict(LIST, allow=[row("Bash(deploy staging:*)")]), MODELS, ["ship "])
check("table: control, the same rule beside another production command is accepted -- %s" % errs, errs == [], errs)

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL", f)
print("%d checks, %d failed" % (n_checks[0], len(failures)))
if failures:
    sys.exit(1)
