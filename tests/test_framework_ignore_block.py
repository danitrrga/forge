#!/usr/bin/env python3
"""The `.gitignore` block of the framework step (forge/fwxignore.py, forge/gitblock.py, called from forge/framework.py).

The framework keeps a project's working documents (markdown and tsv) under <project>/.fwx/, and they must be tracked. A
project's own `*.md` rule ignores every one of them, nothing ignores the worktrees the framework creates under
.claude/worktrees/, and .claude/<plugin>.json is generated. For a profile with `framework: true`, `forge sync` keeps ONE
block at the END of the project's .gitignore (a negation only works after the rule it negates):

    # BEGIN FORGE-FWX (managed by forge)
    !/.fwx/**/*.md
    /.claude/<plugin>.json
    /.claude/worktrees/
    # END FORGE-FWX

Everything runs in-process against a toy HOME, toy profiles and toy git repositories (tests/sandbox.py's temp dirs, removed
at exit); PATH is the fake directory alone, python3 and git linked in (standing order 10).

Seen failing on the base (97c3ec7, this file as it is, the framework step writing the single line `.claude/toyfw.json`):
  1. "1: .fwx/.../context.md shows in git status -- ['?? .claude/worktrees/', '?? .fwx/decisions.tsv', ...]" (the markdown is
     ignored by `*.md`; the worktree shows because nothing ignores it).
  2. "2: the block is last, whole and exact -- ['*.md', '.claude/toyfw.json']"; "2: a block that sits before `*.md` is moved to
     the end ... -- context.md still ignored".
  3. "3: a path under the project's narrower rule stays ignored" held only because nothing un-ignored it; the broad-form control
     below is the one that fails when `!/.fwx/**` is used.
  The controls of section 2 are about git itself and pass on the base: they prove the block's three lines are each needed
  (without the `!` line only the tsv shows; with it before `*.md` the markdown is still ignored; without the worktrees line
  the worktree shows). Sections 4 to 7 (idempotence, fold, tail, markers, off, uninstall, repo-owned, doctor) were red for the
  same reason: no block. First messages: "4: the first apply writes the block -- None", "5: BEGIN without END: ... -- exit 0",
  "7: writes_tracked_files false: the block is in .git/info/exclude -- ...", "8: doctor row: FAIL naming .gitignore:1:*.md ...
  -- AttributeError: module 'forge.cli' has no attribute 'framework_ignore_row'".
Negative controls on the finished code, each mutation put back (the checks that went red are named in the commit message).
"""
import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("fwgi-test-")
HOME = os.path.join(TOY, "home")
BIN = os.path.join(TOY, "bin")
os.makedirs(HOME)
os.makedirs(BIN)
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
from forge import cli, owned, sync, uninstall  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")  # this checkout may be a linked worktree, which never writes

failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:700]))


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
_n = [0]


def forge_json(on=True):
    _n[0] += 1
    doc = {"integrations": {k: False for k in lib.INTEGRATIONS}}
    doc["integrations"]["consent"] = True
    if on:
        doc["framework"] = FW
    path = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()


def plugin_dir():
    d = os.path.join(HOME, "plug", NAME)
    os.makedirs(os.path.join(d, ".claude-plugin"))
    with open(os.path.join(d, ".claude-plugin", "marketplace.json"), "w") as f:
        json.dump({"name": NAME, "owner": {"name": "toy"}, "plugins": [{"name": NAME, "source": "./"}]}, f)
    with open(os.path.join(d, ".claude-plugin", "plugin.json"), "w") as f:
        json.dump({"name": NAME, "version": "0.0.1", "description": "toy"}, f)


FAKE = '''#!%s
import json, os, sys
reg = os.path.join(%r, ".claude", "plugins", "known_marketplaces.json")
if sys.argv[1:4] == ["plugin", "marketplace", "add"]:
    os.makedirs(os.path.dirname(reg), exist_ok=True)
    doc = json.load(open(reg)) if os.path.exists(reg) else {}
    doc[os.path.basename(sys.argv[4])] = {"source": {"source": "directory", "path": sys.argv[4]}, "installLocation": sys.argv[4]}
    json.dump(doc, open(reg, "w"))
'''
with open(os.path.join(BIN, "claude"), "w") as f:
    f.write(FAKE % (sys.executable, HOME))
os.chmod(os.path.join(BIN, "claude"), 0o755)

_p = [0]


def project(gitignore=None, commit=False, sub=None):
    """A toy checkout (one empty commit, so `git worktree add` works) with a .gitignore of `gitignore` when given;
    `commit` commits it. `sub`: the project is that directory of a larger repository."""
    _p[0] += 1
    top = os.path.join(TOY, "toyproj%d" % _p[0])
    os.makedirs(top)
    sandbox.git(top, "init", "-q", "-b", "main")
    sandbox.git(top, "commit", "-q", "--allow-empty", "-m", "init")
    d = os.path.join(top, sub) if sub else top
    os.makedirs(d, exist_ok=True)
    if gitignore is not None:
        with open(os.path.join(d, ".gitignore"), "w") as f:
            f.write(gitignore)
        if commit:
            sandbox.git(top, "add", "-A")
            sandbox.git(top, "commit", "-q", "-m", "ignore")
    return d


def profile(ppath, name="toyapp", **over):
    p = {"project": name, "project_path": ppath, "servers": [], "plugins_keep": ["keep@toy"], "skills_keep": ["*"], "framework": True}
    p.update(over)
    return p


_w = [0]
SECRET = "fake-linear-key-NOT-REAL"


class World:
    def __init__(self):
        _w[0] += 1
        self.base = os.path.join(TOY, "world%d" % _w[0])
        self.cfg = os.path.join(self.base, "config")
        self.pdir = os.path.join(self.cfg, "profiles")
        os.makedirs(self.pdir)
        with open(os.path.join(self.cfg, "mcp-registry.json"), "w") as f:
            f.write('{"servers": {}}')
        with open(os.path.join(self.base, "secrets.json"), "w") as f:
            json.dump({"LINEAR_API_KEY": SECRET}, f)
        os.symlink(os.path.join(self.base, "secrets.json"), os.path.join(self.cfg, "secrets.json"))
        with open(os.path.join(self.cfg, "project-relocations.json"), "w") as f:
            f.write('{"relocations": []}')
        self.names = set()

    def put(self, prof):
        self.names.add(prof["project"])
        with open(os.path.join(self.pdir, prof["project"] + ".claude.json"), "w") as f:
            json.dump(prof, f)

    def drop(self, name):
        os.remove(os.path.join(self.pdir, name + ".claude.json"))
        self.names.discard(name)

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


def raw(f):
    try:
        with open(f, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def text(f):
    b = raw(f)
    return None if b is None else b.decode()


def put(f, s):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w") as fh:
        fh.write(s)


def gi(p):
    return os.path.join(p, ".gitignore")


def bang(out):
    return [l for l in out.splitlines() if l.lstrip().startswith("!")]


def blines(out):
    return [l for l in out.splitlines() if "FORGE-FWX block" in l]


def block(prefix="", name=NAME):
    return ["# BEGIN FORGE-FWX (managed by forge)", "!/%s.fwx/**/*.md" % prefix, "/%s.claude/%s.json" % (prefix, name),
            "/%s.claude/worktrees/" % prefix, "# END FORGE-FWX"]


def btext(**kw):
    return "\n".join(block(**kw)) + "\n"


def status(p):
    """git status --short -uall, as the project sees it."""
    return subprocess.run(["git", "-C", p, "status", "--short", "-uall"], capture_output=True, text=True).stdout.splitlines()


def ignored(p, rel):
    """(is ignored, `source:line:pattern` of the rule that decides) by git check-ignore -v --no-index."""
    r = subprocess.run(["git", "-C", p, "check-ignore", "-v", "--no-index", "--", rel], capture_output=True, text=True)
    return r.returncode == 0, r.stdout.split("\t")[0] if r.stdout else ""


def make_docs(p):
    for rel in (".fwx/milestones/v1/phases/01-x/context.md", ".fwx/decisions.tsv", ".fwx/subprojects/a/private/n.md",
                ".fwx/subprojects/a/open.md", "notes.md"):
        put(os.path.join(p, rel), "x\n")


def make_worktree(p):
    sandbox.git(p, "worktree", "add", "-q", ".claude/worktrees/x", "-b", "wt-%d" % _n[0])


def seen(p):
    """What `git status` lists of the four things that matter: (context, tsv, fwx.json, worktree, notes)."""
    st = "\n".join(status(p))
    return (".fwx/milestones/v1/phases/01-x/context.md" in st, ".fwx/decisions.tsv" in st, ".claude/%s.json" % NAME in st,
            ".claude/worktrees" in st, "notes.md" in st)


def fresh(gitignore, commit=False, name="toyapp", **over):
    p = project(gitignore, commit)
    w = World()
    w.put(profile(p, name=name, **over))
    return p, w


forge_json()
plugin_dir()
STAR = "*.md\n!README.md\nnode_modules/\n"
REG = lambda: raw(owned.path())  # noqa: E731

# --------------------------------------------------------------------------------------------- 1. the project's `*.md`
p, w = fresh(STAR)
code, out = w.run()
make_docs(p)
make_worktree(p)
ctx, tsv, fwjson, wt, notes = seen(p)
check("1: apply exits 0 -- %s" % bang(out), code == 0, out)
check("1: .fwx/.../context.md shows in git status -- %s" % status(p), ctx, status(p))
check("1: .fwx/decisions.tsv shows", tsv, status(p))
check("1: .claude/toyfw.json does not show", not fwjson and os.path.exists(os.path.join(p, ".claude", NAME + ".json")), status(p))
check("1: a real `git worktree add .claude/worktrees/x` does not show", not wt and os.path.isdir(os.path.join(p, ".claude", "worktrees", "x")), status(p))
check("1: the project's own `*.md` still ignores a note outside .fwx/", not notes, status(p))
check("2: the block is last, whole and exact -- %s" % (text(gi(p)) or "").splitlines(), text(gi(p)) == STAR + btext(), text(gi(p)))
check("2: no single `.claude/toyfw.json` line is written beside the block", ".claude/toyfw.json\n" not in (text(gi(p)) or "").replace("/.claude/toyfw.json\n", ""), text(gi(p)))
c = [c for c in owned.previous(gi(p), "framework")[0]]
check("2: the block is one claim of part framework, owner the profile, the digest of its text",
      [(x["kind"], x["at"], x["owner"]) for x in c] == [("item", ["block", "FORGE-FWX"], "toyapp")]
      and c[0]["sum"] == owned.digest("\n".join(block())), c)

# ----------------------------------------------------------------------------------- 2. controls: git itself, three lines
def world_with(gitignore):
    q = project(gitignore)
    make_docs(q)
    make_worktree(q)
    return q


no_bang = btext().replace("!/.fwx/**/*.md\n", "")
q = world_with(STAR + no_bang)
check("control A: without the `!` line the markdown stays ignored and only the tsv shows -- %s" % status(q),
      seen(q)[:2] == (False, True), status(q))
q = world_with(btext() + STAR)
check("control B: the block BEFORE `*.md` leaves the markdown ignored (so `last in the file` is enforced, not assumed) -- %s" % status(q),
      seen(q)[0] is False, status(q))
q = world_with(STAR + btext().replace("/.claude/worktrees/\n", ""))
check("control C: without the worktrees line the worktree shows -- %s" % status(q), seen(q)[3] is True, status(q))
q = world_with(STAR + btext())
check("control D: the whole block, last, gives the intended outcome (git status: context, tsv shown; fwx.json, worktree, notes not)",
      seen(q) == (True, True, False, False, False), status(q))

# ---------------------------------------------------------------------- 3. a narrower project rule must survive
NARROW = STAR + "/.fwx/subprojects/*/private/\n"
p, w = fresh(NARROW)
w.run()
make_docs(p)
check("3: a file under the project's own narrower rule stays ignored after the block -- %s" % ignored(p, ".fwx/subprojects/a/private/n.md")[1],
      ignored(p, ".fwx/subprojects/a/private/n.md")[0], status(p))
check("3: a sibling file of it is tracked material", ".fwx/subprojects/a/open.md" in "\n".join(status(p)), status(p))
q = project(NARROW + "!/.fwx/**\n")
make_docs(q)
check("3 control: the broad form `!/.fwx/**` re-exposes the private file (why the block is narrow)",
      ".fwx/subprojects/a/private/n.md" in "\n".join(status(q)), status(q))

# ----------------------------------------------------------------------------------------------------- 4. idempotence
p, w = fresh(STAR)
code, out = w.run(apply=False)
check("4: a dry-run says it would create the block, and writes nothing",
      any("would create" in l for l in blines(out)) and text(gi(p)) == STAR and code == 0, (code, blines(out)))
code, out = w.run()
check("4: the first apply writes the block -- %s" % blines(out), text(gi(p)) == STAR + btext() and any("(created)" in l for l in blines(out)), blines(out))
before = (raw(gi(p)), REG())
code, out = w.run()
check("4: the second apply changes nothing (the file, the registry) and says already current -- %s" % blines(out),
      code == 0 and before == (raw(gi(p)), REG()) and any("already current" in l for l in blines(out)), (code, blines(out)))
code, out = w.run(apply=False)
check("4: the second dry-run says already current", any("already current" in l for l in blines(out)), blines(out))
# An outdated block (an older forge wrote fewer lines) is brought current in place.
put(gi(p), STAR + "\n".join(block()[:3] + block()[4:]) + "\n")
code, out = w.run(apply=False)
check("4: a dry-run over a stale block says would update", any("would update" in l for l in blines(out)), blines(out))
code, out = w.run()
check("4: apply brings it current, in place", text(gi(p)) == STAR + btext() and any("(updated" in l for l in blines(out)), (text(gi(p)), blines(out)))
# no .gitignore at all: created whole
p0 = project()
w0 = World()
w0.put(profile(p0, name="nogi"))
w0.run()
check("4: a project with no .gitignore gets one holding exactly the block", text(gi(p0)) == btext(), text(gi(p0)))
# A project that is a directory of a larger repository: its .gitignore, anchored there.
p1 = project(STAR, sub="app")
w1 = World()
w1.put(profile(p1, name="sub"))
w1.run()
make_docs(p1)
check("4: a project in a subdirectory of a repository gets the block in its own .gitignore and its documents track",
      text(gi(p1)) == STAR + btext() and seen(p1)[0] and seen(p1)[1], status(p1))

# --------------------------------------------------------------------------- 4b. the fold of the old single line
p, w = fresh(STAR + ".claude/toyfw.json\ndist/\n")
owned.record(gi(p), [owned.claim("item", ["line", ".claude/toyfw.json"], ".claude/toyfw.json", "toyapp")], True, part="framework")
code, out = w.run()
t = text(gi(p))
check("4b: the claimed old single line is folded into the block -- %s" % t.splitlines(),
      t == STAR + "dist/\n" + btext(), t)
check("4b: its claim is released and the block's is held -- %s" % owned.previous(gi(p), "framework")[0],
      [x["at"] for x in owned.previous(gi(p), "framework")[0]] == [["block", "FORGE-FWX"]], owned.previous(gi(p), "framework")[0])
p, w = fresh(STAR + ".claude/toyfw.json\n")  # the same line, but the project's own: not claimed, not touched
w.run()
check("4b: an unclaimed line of the same text is the project's and stays -- %s" % (text(gi(p)) or "").splitlines(),
      text(gi(p)) == STAR + ".claude/toyfw.json\n" + btext(), text(gi(p)))

# ---------------------------------------------------------------------------- 4c. lines after the block
p, w = fresh(STAR)
w.run()
put(gi(p), text(gi(p)) + "dist/\n.env\n")
before = raw(gi(p))
code, out = w.run()
check("4c: harmless lines the project put after the block are left alone, nothing moves -- %s" % blines(out),
      raw(gi(p)) == before and any("already current" in l for l in blines(out)) and code == 0, (blines(out), text(gi(p))))
for why, tail, rel in (("`*.md` again", "*.md\n", ".fwx/milestones/v1/phases/01-x/context.md"),
                       ("`*.tsv`... of the block's own kind: `.fwx/` as a whole", ".fwx/\n", ".fwx/milestones/v1/phases/01-x/context.md"),
                       ("a negation of the worktrees line", "!/.claude/worktrees/\n", ".claude/worktrees/x")):
    p, w = fresh(STAR)
    w.run()
    put(gi(p), text(gi(p)) + "dist/\n" + tail)
    code, out = w.run(apply=False)
    check("4c: a later line that re-ignores/un-ignores (%s): the dry-run says it would move the block" % why,
          any("would update" in l and "moved" in l for l in blines(out)), blines(out))
    code, out = w.run()
    t = text(gi(p)) or ""
    check("4c: (%s) the block is moved to the end, the owner's lines stay in their order -- %s" % (why, t.splitlines()),
          t == STAR + "dist/\n" + tail + btext() and any("moved" in l for l in blines(out)), t)
    if ".fwx/" == tail.strip():
        # the whole directory is ignored: no negation of a file can bring it back; the outcome stays wrong and is said
        check("4c: (%s) a rule the block cannot beat is a `!` line naming the path and the rule, exit 1 -- %s" % (why, bang(out)),
              code == 1 and any(".gitignore:" in l and ".fwx" in l for l in bang(out)), (code, out))
    else:
        make_docs(p)
        check("4c: (%s) and the outcome is right: the documents show" % why, code == 0 and (seen(p)[0] if "md" in rel else True), (code, status(p), out))

# ------------------------------------------------------------------------------------------------------ 5. broken markers
B, E = block()[0], block()[-1]
for label, body, line in (("BEGIN without END", STAR + B + "\n!/.fwx/**/*.md\n", 4),
                          ("END without BEGIN", STAR + "!/.fwx/**/*.md\n" + E + "\n", 5),
                          ("two blocks", STAR + btext() + "dist/\n" + btext(), 10),
                          ("edited marker text", STAR + btext().replace("(managed by forge)", "(managed by hand)"), 4),
                          ("END before BEGIN", STAR + E + "\n" + B + "\n", 4)):
    p, w = fresh(body)
    code, out = w.run()
    check("5: %s: exit non-zero, a `!` line names .gitignore and the line %d -- %s" % (label, line, bang(out)),
          code != 0 and any(re.search(r"\.gitignore:%d\b" % line, l) for l in bang(out)), (code, out))
    check("5: %s: the file is not touched and no block is claimed" % label,
          text(gi(p)) == body and not owned.previous(gi(p), "framework")[0], text(gi(p)))
    check("5: %s: .claude/toyfw.json is not written (it would be unignored)" % label, not os.path.exists(os.path.join(p, ".claude", NAME + ".json")), "")

# ---------------------------------------------------------------------------------- 6. framework false, uninstall
OWN = "/.claude/worktrees/\n!/.fwx/**/*.md\n"  # the project's own lines, identical to the block's, outside its markers
orig = "*.md\n" + OWN + "node_modules/\n"
p, w = fresh(orig)
w.run()
check("6: setup, the block is there after the project's own lines", text(gi(p)) == orig + btext(), text(gi(p)))
w.put(profile(p, name="toyapp", framework=False))
code, out = w.run(apply=False)
check("6: a dry-run of true -> false says it would remove the block", any("would remove" in l for l in blines(out)) and text(gi(p)) == orig + btext(), (blines(out), out))
code, out = w.run()
check("6: true -> false removes exactly the block: the file is the original again, identical lines outside the markers stay -- %s"
      % (text(gi(p)) or "").splitlines(), text(gi(p)) == orig and code == 0, text(gi(p)))
check("6: no claim of the block is left", not owned.previous(gi(p), "framework")[0], owned.previous(gi(p), "framework")[0])
# an edited block stays, and is named
p, w = fresh(STAR)
w.run()
put(gi(p), text(gi(p)).replace("/.claude/worktrees/", "/.claude/worktrees/\n/.my-extra/"))
w.put(profile(p, name="toyapp", framework=False))
code, out = w.run()
check("6: an edited block is the project's: it stays, and a `!` line names it -- %s" % bang(out),
      "# BEGIN FORGE-FWX" in text(gi(p)) and any("block" in l and "edited" in l for l in bang(out)), (text(gi(p)), out))
# forge uninstall --project
p, w = fresh(orig)
w.run()
w.drop("toyapp")
sync.CFG, lib.PROFILES = w.cfg, w.pdir
o = io.StringIO()
with contextlib.redirect_stdout(o):
    code = uninstall.main(argparse.Namespace(integration=None, project="toyapp", apply=True))
check("6: forge uninstall --project: exit 0 -- %s" % sandbox.tail(o.getvalue(), 3), code == 0, o.getvalue())
check("6: forge uninstall --project: removes exactly the block -- %s" % (text(gi(p)) or "").splitlines(), text(gi(p)) == orig, text(gi(p)))
check("6: forge uninstall --project: no claim of the block is left", not [x for x in owned.previous(gi(p))[0] if x["at"][:1] == ["block"]], "")

# ----------------------------------------------------------------------------------------- 7. writes_tracked_files: false
p, w = fresh("*.md\n", commit=True, writes_tracked_files=False)
before_gi = raw(gi(p))
code, out = w.run()
ex = os.path.join(p, ".git", "info", "exclude")
check("7: the tracked .gitignore is not touched", raw(gi(p)) == before_gi, text(gi(p)))
check("7: the block is in .git/info/exclude -- %s" % (text(ex) or "").splitlines()[-6:], btext() in (text(ex) or ""), text(ex))
make_docs(p)
make_worktree(p)
ctx, tsv, fwjson, wt, notes = seen(p)
check("7: what actually happens: a `!` in info/exclude does not beat `*.md` of the .gitignore: context.md stays ignored (%s)" % ignored(p, ".fwx/milestones/v1/phases/01-x/context.md")[1],
      ctx is False and ignored(p, ".fwx/milestones/v1/phases/01-x/context.md")[1].startswith(".gitignore:1:"), status(p))
check("7: but the tsv shows, and fwx.json and the worktree stay out of git status", tsv and not fwjson and not wt, status(p))
check("7: the step says so with a `!` line that names the path, the rule and the fix, and exits 1 -- %s" % bang(out),
      code == 1 and any(".fwx/" in l and ".gitignore:1" in l and "carry the block" in l for l in bang(out)), (code, out))
check("7: the output says the un-ignore holds only in this clone", any("only in this clone" in l for l in blines(out)), blines(out))
before = (raw(ex), REG())
code2, out2 = w.run()
check("7: a second apply changes nothing and says already current", before == (raw(ex), REG()) and any("already current" in l for l in blines(out2)), blines(out2))
# The repo's own tracked .gitignore carries the block: nothing is written to the exclude, exit 0.
p, w = fresh("*.md\n" + btext(), commit=True, writes_tracked_files=False)
code, out = w.run()
ex = os.path.join(p, ".git", "info", "exclude")
check("7: a repo that carries the block itself: exit 0, no `!`, nothing of the block in info/exclude -- %s" % bang(out),
      code == 0 and "FORGE-FWX" not in (text(ex) or "") and any("already current" in l for l in blines(out)), (code, out))
# A repo whose rules do not ignore the markdown: the block in info/exclude does what it can, exit 0.
p, w = fresh("node_modules/\n", commit=True, writes_tracked_files=False)
code, out = w.run()
make_docs(p)
make_worktree(p)
check("7: a repo with no `*.md`: exit 0, the documents show, fwx.json and worktree do not -- %s" % status(p),
      code == 0 and seen(p) == (True, True, False, False, True), (code, out))
# turned off: only the block of the exclude goes
w.put(profile(p, name="toyapp", framework=False, writes_tracked_files=False))
w.run()
check("7: true -> false takes the block out of info/exclude", "FORGE-FWX" not in (text(os.path.join(p, ".git", "info", "exclude")) or ""),
      text(os.path.join(p, ".git", "info", "exclude")))

# ------------------------------------------------------------------------------------------------------- 8. the doctor row
def row(only=None):
    try:
        return cli.framework_ignore_row(only)
    except AttributeError as e:  # the row is not there: a failed check, not a crash of the suite
        return lib.Result("CRASH", "framework ignore", "AttributeError: %s" % e)


p, w = fresh(STAR)
w.run()
w.run()  # lib.PROFILES points at this world
r = row()
check("8: doctor row after the block: PASS naming how many projects it looked at -- %s %s" % (r.level, r.detail),
      r.level == "PASS" and "looked at 1 project" in r.detail, r)
put(gi(p), text(gi(p)) + "*.md\n")
r = row()
check("8: a later `*.md` makes it FAIL naming the path and the rule with file:line -- %s %s" % (r.level, r.detail),
      r.level == "FAIL" and ".fwx/x/y.md" in r.detail and ".gitignore:%d:*.md" % (len(text(gi(p)).splitlines())) in r.detail, r)
p, w = fresh("*.md\n", commit=True, writes_tracked_files=False)
w.run()
r = row()
check("8: a repo-owned project whose documents stay ignored: FAIL naming .gitignore:1:*.md -- %s %s" % (r.level, r.detail),
      r.level == "FAIL" and ".gitignore:1:*.md" in r.detail, r)
w2 = World()
sync.CFG, lib.PROFILES = w2.cfg, w2.pdir
w2.put(profile(project(), name="off", framework=False))
r = row()
check("8: no profile with the framework on: SKIP, NOT RUN, NOT ARMED -- %s %s" % (r.level, r.detail),
      r.level == "SKIP" and r.detail.startswith("NOT RUN, NOT ARMED: "), r)
w3 = World()
sync.CFG, lib.PROFILES = w3.cfg, w3.pdir
gone = os.path.join(TOY, "not-a-repo")
os.makedirs(gone)
w3.put(profile(gone, name="norepo"))
r = row()
check("8: a framework profile whose project cannot be looked at: looking at zero is a FAIL -- %s %s" % (r.level, r.detail),
      r.level == "FAIL" and "looked at 0" in r.detail, r)
check("8: the row is registered in forge doctor", "framework ignore" in [c[0] for c in cli.CHECKS], [c[0] for c in cli.CHECKS])

# ------------------------------------------------------------ 9. a project with no framework is never touched
forge_json()
p, w = fresh(STAR, framework=False)
code, out = w.run()
check("9: framework false: .gitignore byte-identical, no block line", text(gi(p)) == STAR and not blines(out) and code == 0, (text(gi(p)), out))

print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
for f in failures:
    print("FAIL  " + f)
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
