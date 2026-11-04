#!/usr/bin/env python3
"""The generator denies a project's agents the right to write in forge (forge/sync.py `forge_deny`, `with_forge_deny`), 3.6 U2c.

For every profile except forge's own, `forge sync` writes into the project's settings.local.json `permissions.deny` one `Edit` and
one `Write` rule per top-level entry of the checkout (`lib.ROOT`) except `plugins`: `<Tool>(//<root>/<dir>/**)` for a directory,
`<Tool>(//<root>/<file>)` for a file, and the dry-run prints `  + deny <rule>  (agents of a project do not write in forge)` for each
rule the file does not hold yet. `plugins/` is left out because the plugin repos (`plugins/fwx`) live there and their sessions write
in their own folder. The rules go in as the profile's own `deny` does (union, one owned item claim each), so a rule put by hand
stays, and what forge wrote goes when the entry or the rule stops being wanted.

Why one pair per entry and not one pair on the whole checkout: a `deny` beats any `allow`, and the permission pattern has no way to
leave a folder out of itself. Measured on Claude Code 2.1.308 with scripts/bench/auto_mode.py's world (headless `claude -p
--permission-mode auto`, K1 denied/rule and V1 allowed in every run, one cell each, the harness showing the denial as
"File is in a directory that is denied by your permission settings"):
  * `Edit(//<repo>/**)` + `Write(//<repo>/**)`: Edit of hooks/guard_tool_use.py, of README.md, of plugins/toy/probe.txt and Write of
    hooks/new.txt all denied -- the exception cannot be made inside the pattern.
  * the same with `Edit(//<repo>/!plugins/**)`, and with a second deny `Edit(!//<repo>/plugins/**)`: the first matches nothing (all
    four allowed), the second changes nothing (all four denied). No negation.
  * one `Edit`+`Write` pair per top-level entry but `plugins`: hooks/ and README.md denied, Write of hooks/new.txt denied, Edit of
    plugins/toy/probe.txt allowed. With the `Edit` rules alone Write was denied too (the Write rules are kept: the unit says both).
The matcher below (`denied`) is that measured behaviour: a directory rule matches what is below it, a file rule that file.

Seen failing on master (40d20f1), this file as it is: every check about a rule red, e.g.
  "deny rules missing after --apply -- None"
  "dry-run: `+ deny Edit(//.../hooks/**)  (agents of a project do not write in forge)` is printed -- []"
  "claimed: every rule is an owned item claim -- []"
the controls that pass there (forge's profile gets nothing, a hand-set rule is kept, a frozen profile gets nothing, nothing is written
by a dry-run) stay green. Against a version that writes one pair on the whole checkout instead of one per entry:
  "plugin repo write denied -- <root>/plugins/toy/probe.txt matches ['Edit(//<root>/**)', ...]"
Against a version that puts the path in the code instead of reading lib.ROOT: "forge path hard-coded -- ...".
Against a version that writes the rules into every profile: "deny written into the forge profile -- ...".
Against a version without the folder guard (a profile whose project folder is gone): "missing folder: the project folder is not created -- True"
(the rules made the folder again and hid the `!` line the codex step prints for it; test_codex_harness caught it first).
Three suites that ran a toy profile over the real checkout (test_sync_agent_config 20, test_framework_permissions, test_codex_harness)
saw the new key and were adjusted; each is named in the commit.
Everything runs in-process against a toy HOME, a toy forge.json, toy profiles, a toy config/ and a toy forge root."""
import contextlib
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("fwdeny-test-")
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
from forge import owned, sync  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")  # this checkout may be a linked worktree, which never writes
REAL_ROOT = lib.ROOT

failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:700]))


WHY = "(agents of a project do not write in forge)"
_r = [0]


def toy_root(entries=("hooks/guard.py", "skills/x/SKILL.md", "plugins/toy/probe.txt", ".claude/worktrees/w/f.txt", "README.md", "bin/forge")):
    """A toy forge checkout: the given files, each in its own top-level entry; a file at the top is a file entry."""
    _r[0] += 1
    root = os.path.join(TOY, "forgeroot%d" % _r[0])
    for rel in entries:
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        with open(os.path.join(root, rel), "w") as f:
            f.write("x\n")
    return os.path.realpath(root)


def rules_for(root, skip=("plugins",)):
    """The rules the unit means for `root`, written out by hand (never by the code under test): per top-level entry but the skipped
    ones, Edit then Write, `//` and the absolute path; a directory ends in `/**`."""
    out = []
    for e in sorted(os.listdir(root)):
        if e in skip:
            continue
        tail = "/**" if os.path.isdir(os.path.join(root, e)) else ""
        out += ["%s(/%s/%s%s)" % (t, root, e, tail) for t in ("Edit", "Write")]
    return out


def denied(rule_list, path):
    """The rules of `rule_list` that deny writing `path`: the measured semantics of `Tool(//abs/dir/**)` and `Tool(//abs/file)`."""
    hit = []
    for r in rule_list:
        if not r.startswith(("Edit(//", "Write(//")):
            continue
        body = r[r.index("(") + 2:-1]  # the absolute path after the `//`, minus the closing parenthesis
        body = "/" + body.lstrip("/")
        if body.endswith("/**"):
            if path.startswith(body[:-2]):
                hit.append(r)
        elif path == body:
            hit.append(r)
    return hit


_n = [0]


def forge_json():
    _n[0] += 1
    path = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()


_p = [0]


def project():
    _p[0] += 1
    d = os.path.join(TOY, "toyproj%d" % _p[0])
    os.makedirs(d)
    sandbox.git(d, "init", "-q", "-b", "main")
    return d


def profile(ppath, name, **over):
    p = {"project": name, "project_path": ppath, "servers": [], "plugins_keep": ["keep@toy"], "skills_keep": ["*"]}
    p.update(over)
    return {k: v for k, v in p.items() if v != "DROP"}


_w = [0]


class World:
    """A toy config/ (registry, secrets link, profiles)."""

    def __init__(self):
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

    def put(self, prof):
        self.names.add(prof["project"])
        with open(os.path.join(self.pdir, prof["project"] + ".claude.json"), "w") as f:
            json.dump(prof, f)

    def run(self, apply=True, root=None):
        """One generator run over this world's profiles, with `lib.ROOT` as the toy forge checkout `root` (the real one when None)."""
        sync.CFG, lib.PROFILES = self.cfg, self.pdir
        for pf in os.listdir(self.pdir):
            pp = json.load(open(os.path.join(self.pdir, pf)))["project_path"]
            if not os.path.realpath(pp).startswith(TOY + os.sep):
                sys.exit("FENCE: a toy profile points outside the toy world -- nothing run")
        real_ctx, real_root = lib.context, lib.ROOT
        lib.context = lambda argv: lib.Ctx(bool(argv), set(self.names), False)
        lib.ROOT = root or real_root
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = sync.agent_config(["--apply"] if apply else [])
        finally:
            lib.context, lib.ROOT = real_ctx, real_root
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


def deny_of(p):
    return (perms_of(p) or {}).get("deny")


def bang(text):
    return [l for l in text.splitlines() if l.lstrip().startswith("!")]


def plus_deny(text):
    return [l for l in text.splitlines() if l.startswith("  + deny ")]


def claims_of(p):
    return owned.previous(slp(p))[0]


forge_json()

# ------------------------------------------------------------------------------------------ 1. a project gets the rules
ROOT1 = toy_root()
WANT1 = rules_for(ROOT1)
check("fixture: the hand-written expectation is 10 rules (5 entries but plugins, Edit and Write) -- %d" % len(WANT1), len(WANT1) == 10, WANT1)
pp = project()
w = World()
w.put(profile(pp, "app"))
code, out = w.run(apply=False, root=ROOT1)
want_lines = ["  + deny %s  %s" % (r, WHY) for r in WANT1]
check("dry-run: exit 0 and no `!` -- %s" % bang(out), code == 0 and not bang(out), out)
check("dry-run: one `+ deny <rule>  %s` line per rule, in order -- %s" % (WHY, plus_deny(out)), plus_deny(out) == want_lines, out)
check("dry-run: writes nothing", not os.path.exists(slp(pp)), os.listdir(pp))
code, out = w.run(root=ROOT1)
check("deny rules missing after --apply -- %s" % deny_of(pp), deny_of(pp) == WANT1, deny_of(pp))
check("apply: exit 0 and the same `+ deny` lines -- %s" % bang(out), code == 0 and plus_deny(out) == want_lines, out)
check("claimed: every rule is an owned item claim -- %s" % [c["at"] for c in claims_of(pp)],
      {c["at"][2] for c in claims_of(pp) if c["kind"] == "item" and c["at"][:2] == ["permissions", "deny"]} == set(WANT1), claims_of(pp))
before = raw(slp(pp))
code, out = w.run(root=ROOT1)
check("second apply: byte-identical and no `+ deny` -- %s" % plus_deny(out), raw(slp(pp)) == before and not plus_deny(out) and code == 0, out)

# what the rules cover, by the measured semantics: the plugin repos are not denied, the rest of the checkout is.
for rel, want in (("hooks/guard.py", True), ("hooks/new/deep/file.py", True), ("skills/x/SKILL.md", True), ("README.md", True),
                  ("bin/forge", True), (".claude/worktrees/w/f.txt", True), ("plugins/toy/probe.txt", False),
                  ("plugins/other/deep/f.py", False)):
    hit = denied(deny_of(pp) or [], os.path.join(ROOT1, rel))
    if want:
        check("%s is denied -- %s" % (rel, hit), bool(hit), deny_of(pp))
    else:
        check("plugin repo write denied -- %s/%s matches %s" % (ROOT1, rel, hit), not hit, deny_of(pp))
check("control: the matcher sees a file outside the checkout as not denied", not denied(deny_of(pp) or [], os.path.join(pp, "src", "a.py")), deny_of(pp))
check("control: the matcher denies a file the whole-checkout rule covers (it can fail)",
      bool(denied(["Edit(/%s/**)" % ROOT1], os.path.join(ROOT1, "plugins/toy/probe.txt"))), "")

# the rule is not a fixed path: another root, other rules, none naming the first; and never this checkout's own path.
ROOT2 = toy_root(("docs/a.md", "plugins/p/q.txt", "Makefile"))
code, out = w.run(root=ROOT2)
WANT2 = rules_for(ROOT2)
check("forge path hard-coded -- %s" % deny_of(pp), deny_of(pp) == WANT2 and not any(ROOT1 in r for r in deny_of(pp) or []), deny_of(pp))
check("forge path hard-coded: no rule names the real checkout -- %s" % [r for r in deny_of(pp) or [] if REAL_ROOT in r],
      not any(REAL_ROOT in r for r in deny_of(pp) or []), deny_of(pp))

# ------------------------------------------------------------------------------------------ 2. forge's own profile gets none
ppf = project()
wf = World()
wf.put(profile(ppf, "forge"))
code, out = wf.run(root=ROOT1)
check("deny written into the forge profile -- %s" % deny_of(ppf), not deny_of(ppf) and "+ deny" not in out and code == 0, (deny_of(ppf), out))
# the same rule by path: a profile of another name whose project is the checkout is forge's own too (the toy root is inside the toy world)
wo = World()
wo.put(profile(ROOT1, "mirror"))
code, out = wo.run(root=ROOT1)
check("deny written into the forge profile: one whose project is the checkout -- %s" % deny_of(ROOT1), not deny_of(ROOT1) and "+ deny" not in out, (deny_of(ROOT1), out))
# and a profile whose project is inside plugins/ (fwx) is a project like any other: it gets the rules, none of them on plugins/
ppp = os.path.join(ROOT1, "plugins", "toy")
wp = World()
wp.put(profile(ppp, "toyplugin"))
code, out = wp.run(root=ROOT1)
check("plugin profile: gets the rules of the other entries -- %s" % deny_of(ppp), deny_of(ppp) == WANT1, (deny_of(ppp), out))
check("plugin profile: its own folder is not denied -- %s" % denied(deny_of(ppp) or [], os.path.join(ppp, "probe.txt")),
      not denied(deny_of(ppp) or [], os.path.join(ppp, "probe.txt")), deny_of(ppp))

# a frozen profile and one with no project_path get nothing, as before
ppz = project()
wz = World()
wz.put(profile(ppz, "frozen", frozen=True))
wz.run(root=ROOT1)
check("frozen: nothing written -- %s" % os.path.exists(slp(ppz)), not os.path.exists(slp(ppz)), "")

# a project whose folder is gone gets nothing: writing the file would make the folder again and hide the `!` line of the codex step
gone = os.path.join(TOY, "gone-project")
wg = World()
wg.put(profile(gone, "gone", plugins_keep="DROP", skills_keep="DROP"))
code, out = wg.run(root=ROOT1)
check("missing folder: the project folder is not created -- %s" % os.path.exists(gone), not os.path.exists(gone) and "+ deny" not in out, out)

# ------------------------------------------------------------------------------------------ 3. what is not ours stays
ppm = project()
wm = World()
HAND = "Bash(rm -rf /:*)"
wm.put(profile(ppm, "mixed", permissions={"allow": ["Bash(git status:*)"], "deny": ["Edit(//somewhere/else/**)"],
                                          "additionalDirectories": ["/design/one"]}))
os.makedirs(os.path.dirname(slp(ppm)), exist_ok=True)
lib.write_json(slp(ppm), {"permissions": {"deny": [HAND], "allow": ["Bash(ls:*)"], "additionalDirectories": ["/by/hand"]}})
code, out = wm.run(root=ROOT1)
d = deny_of(ppm) or []
check("union: the hand-set rule, the profile's own and the generated ones are all there -- %s" % d,
      d[:1] == [HAND] and "Edit(//somewhere/else/**)" in d and set(WANT1) <= set(d) and len(d) == len(set(d)) == len(WANT1) + 2, d)
check("union: allow and additionalDirectories are not disturbed -- %s" % perms_of(ppm),
      (perms_of(ppm) or {}).get("allow") == ["Bash(ls:*)", "Bash(git status:*)"]
      and (perms_of(ppm) or {}).get("additionalDirectories") == ["/by/hand", "/design/one"], perms_of(ppm))
# one entry of the checkout goes away: only its two rules go
shutil.rmtree(os.path.join(ROOT1, "skills"))
code, out = wm.run(root=ROOT1)
d = deny_of(ppm) or []
gone = [r for r in WANT1 if "/skills/" in r]
check("entry removed: its two rules go and the others stay -- %s" % [r for r in WANT1 if r in d and "/skills/" in r],
      len(gone) == 2 and not any(r in d for r in gone) and all(r in d for r in WANT1 if r not in gone), d)
check("entry removed: the hand-set rule and the profile's own stay", HAND in d and "Edit(//somewhere/else/**)" in d, d)
# the entry comes back: the rules come back
wm.put(profile(ppm, "mixed", permissions={"allow": ["Bash(git status:*)"], "deny": ["Edit(//somewhere/else/**)"]}))
os.makedirs(os.path.join(ROOT1, "skills", "x"))
code, out = wm.run(root=ROOT1)
d = deny_of(ppm) or []
check("rules back after the entry returns -- %s" % len(d), set(WANT1) <= set(d), d)
real_listing = os.listdir
sync.os.listdir = lambda p: [] if os.path.realpath(p) == ROOT1 else real_listing(p)  # the root cannot be looked at: zero entries
code, out = wm.run(root=ROOT1)
sync.os.listdir = real_listing
check("zero entries: one `!` line naming the deny step, exit 1 -- %s" % bang(out), code == 1 and any("forge write deny" in l for l in bang(out)), out)
check("zero entries: the file is left as it was -- %s" % deny_of(ppm), set(WANT1) <= set(deny_of(ppm) or []), deny_of(ppm))

# ------------------------------------------------------------------------------------------ 4. beside the framework step
sandbox_cfg = World()
ppf2 = project()
plug = os.path.join(HOME, "plug", "toyfw")
os.makedirs(os.path.join(plug, ".claude-plugin"), exist_ok=True)
with open(os.path.join(plug, ".claude-plugin", "marketplace.json"), "w") as f:
    json.dump({"name": "toyfw", "owner": {"name": "toy"}, "plugins": [{"name": "toyfw", "source": "./"}]}, f)
roles = {r: {"small": "sonnet", "normal": "sonnet", "big": "sonnet"} for r in ("orchestrator", "executor", "reviewer")}
fwdoc = {"integrations": {k: False for k in lib.INTEGRATIONS},
         "framework": {"models": roles, "limits": {"on": False, "per_project": {}, "ram_min_free_gb": 0}, "rounds": 4,
                       "critique_rounds_unattended": 2, "factory": {}, "weekly": {"on": True, "min_sessions": 5}, "paths": {},
                       "linear": {"labels": {}}, "plugin_source": {"source": "directory", "path": "~/plug/toyfw"}}}
_n[0] += 1
fwpath = os.path.join(TOY, "forge-%d.json" % _n[0])
with open(fwpath, "w") as f:
    json.dump(fwdoc, f)
lib.SETTINGS = fwpath
lib.settings.cache_clear()
with open(os.path.join(BIN, "claude"), "w") as f:
    f.write("#!%s\nimport sys\nsys.exit(0)\n" % sys.executable)
os.chmod(os.path.join(BIN, "claude"), 0o755)
with open(os.path.join(sandbox_cfg.cfg, "framework-permissions.json"), "w") as f:
    json.dump({"schema": 1, "allow": [{"rule": "Bash(fwx linear comment:*)", "roles": ["orchestrator"], "why": "t", "measured": "t"}]}, f)
sandbox_cfg.put(profile(ppf2, "fwapp", framework=True, checks=["make test"], permissions={"additionalDirectories": ["/design/one"]}))
code, out = sandbox_cfg.run(root=ROOT1)
pf = perms_of(ppf2) or {}
check("framework on: exit 0, no `!` -- %s" % bang(out), code == 0 and not bang(out), out)
check("framework on: the framework's allow rule and the main checkout are written -- %s" % pf,
      pf.get("allow") == ["Bash(fwx linear comment:*)"] and pf.get("additionalDirectories") == ["/design/one", os.path.realpath(ppf2)], pf)
check("framework on: the deny rules are written too -- %s" % pf.get("deny"), pf.get("deny") == rules_for(ROOT1), pf)
before = raw(slp(ppf2))
code, out = sandbox_cfg.run(root=ROOT1)
check("framework on: a second apply is byte-identical -- %s" % [l for l in out.splitlines() if l.startswith("  + ")], raw(slp(ppf2)) == before, out)

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL", f)
print("%d checks, %d failed" % (n_checks[0], len(failures)))
if failures:
    sys.exit(1)
