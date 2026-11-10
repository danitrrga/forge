#!/usr/bin/env python3
"""The generator denies a project's agents the right to write in forge (forge/sync.py `forge_deny`, `with_forge_deny`), 3.6 U2c.

For every profile except forge's own, `forge sync` writes into the project's settings.local.json `permissions.deny` one `Edit` rule
per top-level entry of the checkout (`lib.ROOT`) that git tracks (the engine's history and the data history,
`git ls-files`; an untracked folder such as `logs/` comes and goes and would rewrite every project's file on each sync) except
`plugins` and `design`: `<Tool>(//<root>/<dir>/**)` for a directory,
`<Tool>(//<root>/<file>)` for a file, and the dry-run prints `  + deny <rule>  (agents of a project do not write in forge)` for each
rule the file does not hold yet. `plugins/` is left out because the plugin repos (`plugins/fwx`) live
there and their sessions write in their own folder, `design/` because the taste library stays shared (design-taste's `analyse`
edits `design/taste/entries/*.md` from any project). A new tracked top-level entry is covered at the next sync, which runs at
the start of each project's session. The rules go in as the profile's own `deny` does (union, one owned item claim each), so a rule put by hand
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
    plugins/toy/probe.txt allowed. With the `Edit` rules alone Write was denied too; the Write rules were dropped once Claude Code 2.1.308 warned `Write(...) never matches` on each.
The matcher below (`denied`) is that measured behaviour: a directory rule matches what is below it, a file rule that file.

Second round (the `design/` exception and tracked-only enumeration), seen failing on b33d656: "design repo write denied -- <root>/design/taste/entries/a.md
matches [...]" and "untracked entry: no rule for logs/ -- [...]".
Third round (the untracked entries that always matter, `.git`, `.forge-data.git`, `credentials`, `data`, are denied when the checkout has them),
seen failing on acae9d7: "always-denied: credentials/ and .git/ have rules -- [...]".
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
import subprocess
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
from forge import memory, owned, sync  # noqa: E402

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


TRACKED = {}  # root -> {top-level entry that is denied there (tracked, or one of the always-denied untracked): whether it is a directory}


def _git(root, *args, data=False):
    argv = ["git"] + (["--git-dir", os.path.join(root, ".forge-data.git"), "--work-tree", root] if data else ["-C", root]) + list(args)
    return subprocess.run(argv, env=dict(os.environ, **sandbox.GIT_ENV), capture_output=True, text=True, check=True).stdout


def toy_root(entries=("hooks/guard.py", "skills/x/SKILL.md", "plugins/toy/probe.txt", "design/taste/entries/a.md", ".claude/worktrees/w/f.txt",
                      "README.md", "bin/forge"), data=(), untracked=("logs/run.log", "credentials/secrets.json"), repo=True):
    """A toy forge checkout: the `entries` tracked by its `.git`, the `data` ones by a `.forge-data.git` over the same work tree, and the
    `untracked` files left out of both. `repo=False`: no git at all."""
    _r[0] += 1
    root = os.path.join(TOY, "forgeroot%d" % _r[0])

    def make(rels):
        for rel in rels:
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            with open(os.path.join(root, rel), "w") as f:
                f.write("x\n")
    make(entries)
    root = os.path.realpath(root)
    if repo:
        sandbox.git(root, "init", "-q", "-b", "main")
        sandbox.git(root, "add", "-A")
        sandbox.git(root, "commit", "-qm", "engine")
        if data:
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", os.path.join(root, ".forge-data.git")], check=True, capture_output=True,
                           env=dict(os.environ, **sandbox.GIT_ENV))
            make(data)
            _git(root, "add", *data, data=True)
            _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "data", data=True)
    make(untracked)
    TRACKED[root] = {"data": True}  # data/ is denied before the generator made it (forge/sync.py FORGE_DENY_MADE)
    for always in (".git", ".forge-data.git", "credentials", "data"):  # the untracked entries that always matter, when the checkout has them
        if os.path.isdir(os.path.join(root, always)):
            TRACKED[root][always] = True
    for rel in tuple(entries) + tuple(data):
        top = rel.split("/")[0]
        TRACKED[root][top] = TRACKED[root].get(top, False) or "/" in rel
    return root


def rules_for(root, skip=("plugins", "design")):
    """The rules the unit means for `root`, written out by hand (never by the code under test): per tracked top-level entry but the skipped
    ones, an Edit rule (it covers Write too), `//` and the absolute path; a directory ends in `/**`."""
    out = []
    for e in sorted(TRACKED[root]):
        if e in skip:
            continue
        tail = "/**" if TRACKED[root][e] else ""
        out += ["%s(/%s/%s%s)" % (t, root, e, tail) for t in ("Edit",)]
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
check("fixture: the hand-written expectation is 8 rules (5 tracked entries but plugins and design, plus the untracked .git, credentials and data, Edit only) -- %d" % len(WANT1),
      len(WANT1) == 8 and "Edit(/%s/credentials/**)" % ROOT1 in WANT1 and not any(r.startswith("Write(") for r in WANT1), WANT1)
check("fixture: logs/ is on disk, untracked", os.path.isdir(os.path.join(ROOT1, "logs")) and "logs" not in TRACKED[ROOT1], TRACKED[ROOT1])
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

# what the rules cover, by the measured semantics: the plugin repos and the design library are not denied, the rest of the checkout is.
for rel, want in (("hooks/guard.py", True), ("hooks/new/deep/file.py", True), ("skills/x/SKILL.md", True), ("README.md", True),
                  ("bin/forge", True), (".claude/worktrees/w/f.txt", True), ("plugins/toy/probe.txt", False),
                  ("plugins/other/deep/f.py", False), ("design/taste/entries/a.md", False), ("design/taste/entries/new.md", False),
                  ("design/other/x.py", False)):
    hit = denied(deny_of(pp) or [], os.path.join(ROOT1, rel))
    if want:
        check("%s is denied -- %s" % (rel, hit), bool(hit), deny_of(pp))
    elif rel.startswith("design/"):
        check("design repo write denied -- %s/%s matches %s" % (ROOT1, rel, hit), not hit, deny_of(pp))
    else:
        check("plugin repo write denied -- %s/%s matches %s" % (ROOT1, rel, hit), not hit, deny_of(pp))
# an untracked top-level folder adds no rule (logs/ comes and goes); creating one more changes nothing in the file
os.makedirs(os.path.join(ROOT1, ".playwright-mcp"))
before = raw(slp(pp))
code, out = w.run(root=ROOT1)
check("always-denied: credentials/ and .git/ have rules, untracked as they are -- %s" % [r for r in deny_of(pp) or [] if "credentials" in r or "/.git/" in r],
      all(r in (deny_of(pp) or []) for r in ("Edit(/%s/credentials/**)" % ROOT1, "Edit(/%s/.git/**)" % ROOT1)), deny_of(pp))
check("no Write rule is generated: Claude Code 2.1.308 warns `Write(...) never matches` on each, Edit covers Write -- %s" % [r for r in deny_of(pp) or [] if r.startswith("Write(")][:2],
      not any(r.startswith("Write(") for r in deny_of(pp) or []), deny_of(pp))
check("always-denied: a file under credentials/ and under .git/ is denied", bool(denied(deny_of(pp) or [], os.path.join(ROOT1, "credentials/secrets.json")))
      and bool(denied(deny_of(pp) or [], os.path.join(ROOT1, ".git/config"))), deny_of(pp))
check("untracked entry: no rule for logs/ or .playwright-mcp/ -- %s" % [r for r in deny_of(pp) or [] if "/logs" in r or "playwright" in r],
      not any("/logs" in r or "playwright" in r for r in deny_of(pp) or []) and raw(slp(pp)) == before and not plus_deny(out), (deny_of(pp), out))
check("control: the matcher sees a file outside the checkout as not denied", not denied(deny_of(pp) or [], os.path.join(pp, "src", "a.py")), deny_of(pp))
check("control: the matcher denies a file the whole-checkout rule covers (it can fail)",
      bool(denied(["Edit(/%s/**)" % ROOT1], os.path.join(ROOT1, "plugins/toy/probe.txt"))), "")

# the rule is not a fixed path: another root, other rules, none naming the first; and never this checkout's own path.
ROOT2 = toy_root(("docs/a.md", "plugins/p/q.txt", "Makefile"), data=("config/c.json", "docs/b.md"), untracked=("data/mem.db", "logs/x"))
# run from a folder inside the checkout: `git ls-files` lists what is below the current directory, and the data history (a
# work tree with no folder of its own) listed nothing of the entries above it. Red without `cwd=root`: "data history: ..."
here = os.getcwd()
os.chdir(os.path.join(ROOT2, "config"))
try:
    code, out = w.run(root=ROOT2)
finally:
    os.chdir(here)
WANT2 = rules_for(ROOT2)
check("data history: its top-level entries are covered too (config/, and docs/ once) -- %s" % WANT2,
      "Edit(/%s/config/**)" % ROOT2 in WANT2 and sum(r.startswith("Edit(") and "/docs/" in r for r in WANT2) == 1, WANT2)
check("always-denied: data/ and .forge-data.git/ have rules, logs/ none -- %s" % WANT2,
      all("Edit(/%s/%s/**)" % (ROOT2, n) in WANT2 for n in ("data", ".forge-data.git", ".git")) and not any("/logs" in r for r in WANT2), WANT2)
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
# one entry of the checkout goes away: only its rule goes
sandbox.git(ROOT1, "rm", "-rq", "skills")
code, out = wm.run(root=ROOT1)
d = deny_of(ppm) or []
gone = [r for r in WANT1 if "/skills/" in r]
check("entry removed: its rule goes and the others stay -- %s" % [r for r in WANT1 if r in d and "/skills/" in r],
      len(gone) == 1 and not any(r in d for r in gone) and all(r in d for r in WANT1 if r not in gone), d)
check("entry removed: the hand-set rule and the profile's own stay", HAND in d and "Edit(//somewhere/else/**)" in d, d)
# the entry comes back: the rules come back
wm.put(profile(ppm, "mixed", permissions={"allow": ["Bash(git status:*)"], "deny": ["Edit(//somewhere/else/**)"]}))
os.makedirs(os.path.join(ROOT1, "skills", "x"), exist_ok=True)
with open(os.path.join(ROOT1, "skills", "x", "SKILL.md"), "w") as f:
    f.write("x\n")
sandbox.git(ROOT1, "add", "skills")
code, out = wm.run(root=ROOT1)
d = deny_of(ppm) or []
check("rules back after the entry returns -- %s" % len(d), set(WANT1) <= set(d), d)
# the checkout cannot be listed (no git history there): a `!` line, exit 1, the file as it was
ROOT0 = toy_root(("README.md",), repo=False)
code, out = wm.run(root=ROOT0)
check("no history: one `!` line naming the deny step, exit 1 -- %s" % bang(out), code == 1 and any("forge write deny" in l for l in bang(out)), out)
check("no history: the file is left as it was -- %s" % deny_of(ppm), set(WANT1) <= set(deny_of(ppm) or []), deny_of(ppm))
# only exempt entries tracked: the always-denied `.git` is all there is to deny
ROOTP = toy_root(("plugins/a/b.txt", "design/x.md"), untracked=())
code, out = wm.run(root=ROOTP)
check("only exempt entries tracked: just the rules of .git and data -- %s" % [r for r in deny_of(ppm) or [] if ROOTP in r],
      [r for r in deny_of(ppm) or [] if ROOTP in r] == rules_for(ROOTP) == ["Edit(/%s/.git/**)" % ROOTP, "Edit(/%s/data/**)" % ROOTP], (deny_of(ppm), out))

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

# ------------------------------------------------------------------------------------------ 5. a second apply writes nothing
# The first --apply of a profile that uses claude-mem-lite creates data/memory-lite/<store> in the checkout (memory.derive_lite_env),
# a checkout that had no data/ before. A profile run earlier in the same apply (here `a5`, no lite) read the checkout before that, so
# its first apply wrote no rule for data/ and the second one added them: a rewrite of settings.local.json and owned.json on the next session start (the fixture of tests/test_sync_fixture.py on
# the installed checkout: "a second --apply writes nothing (no write lines, every mtime unchanged): exit 0, lines [], changed
# ['home/.local/state/forge', 'home/.local/state/forge/owned.json', ...]"). data/ is now denied whether or not it exists yet.
# Red on master (584fb80): "second apply: byte-identical and no `+ deny` -- ['  + deny Edit(//.../data/**)  (agents of a project do not write in forge)', ...]".
ROOT5 = toy_root()
check("idempotent: the toy checkout has no data/ before the first apply", not os.path.exists(os.path.join(ROOT5, "data")), os.listdir(ROOT5))
pp5 = project()
w5 = World()
pp5a = project()
w5.put(profile(pp5a, "a5"))  # profiles run in file order: a5 before memapp5
w5.put(profile(pp5, "memapp5", plugins_keep=[memory.LITE_PLUGIN]))
real_lite = memory.LITE_ROOT
memory.LITE_ROOT = os.path.join(ROOT5, "data", "memory-lite")
try:
    code, out = w5.run(root=ROOT5)
    first, first_owned, first_deny = raw(slp(pp5a)), claims_of(pp5a), deny_of(pp5a)
    code2, out2 = w5.run(root=ROOT5)
finally:
    memory.LITE_ROOT = real_lite
check("idempotent: the first apply made data/ in the checkout (the control: this is what moved the rules) -- %s" % os.listdir(ROOT5),
      os.path.isdir(os.path.join(ROOT5, "data", "memory-lite", "memapp5")), os.listdir(ROOT5))
check("idempotent: data/ is denied from the first apply -- %s" % first_deny,
      "Edit(/%s/data/**)" % ROOT5 in (first_deny or []), first_deny)
check("second apply: byte-identical and no `+ deny` -- %s" % plus_deny(out2),
      code == 0 and code2 == 0 and raw(slp(pp5a)) == first and not plus_deny(out2) and claims_of(pp5a) == first_owned, (out, out2))

# a project whose file was written when forge still made Write rules: the next apply takes the Write rules out and keeps the Edit ones
ppo = project()
wo = World()
wo.put(profile(ppo, "old"))
sync.FORGE_DENY_TOOLS = ("Edit", "Write")
try:
    wo.run(root=ROOT1)
finally:
    sync.FORGE_DENY_TOOLS = ("Edit",)
seeded = deny_of(ppo) or []
code, out = wo.run(root=ROOT1)
check("migration: seeded with Write rules (%d), the next apply leaves only the Edit ones -- %s" % (sum(r.startswith("Write(") for r in seeded), deny_of(ppo)),
      any(r.startswith("Write(") for r in seeded) and code == 0 and deny_of(ppo) == WANT1, (seeded, deny_of(ppo), out))

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL", f)
print("%d checks, %d failed" % (n_checks[0], len(failures)))
if failures:
    sys.exit(1)
