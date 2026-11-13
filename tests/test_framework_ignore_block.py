#!/usr/bin/env python3
"""The `.gitignore` block of the framework step (forge/fwxignore.py, forge/gitblock.py, called from forge/framework.py).

The framework keeps a project's working documents (markdown and tsv) under <project>/.fwx/, and they must be tracked. A
project's own `*.md` rule ignores every one of them, nothing ignores the worktrees the framework creates under
.claude/worktrees/, and .claude/<plugin>.json is generated. For a profile with `framework: true`, `forge sync` keeps ONE
block at the END of the project's .gitignore (a negation only works after the rule it negates):

    # BEGIN FORGE-FWX (managed by forge, do not edit inside)
    !/.fwx/**/*.md
    !/.fwx/**/*.tsv
    /.claude/<plugin>.json
    /.claude/worktrees/
    # END FORGE-FWX

(in .git/info/exclude, one block per project, the markers tagged with the project's place: `# BEGIN FORGE-FWX app/ (...)`)

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
Review round (sections 10 to 16, seen failing on a11e284 before the fixes: 47 of 119 checks; section 17, the profile field
framework_ignore_block, 22 checks red on that head):
  D1 two projects in one repository, writes_tracked_files false: "each keeps its own block ... -- ['# git ls-files ...', ...]" and
     every run printed "(updated; ..." for both. D1 with the tracked .gitignore did NOT fail: each project has its own file.
  D2 "exit 1 and a `!` line naming the root rule -- [] -- (0, ..." (exit 0, no `!`, with the root `.gitignore:1:*.md`).
  D3 "no scratch directory: exit 1 and a `!` line ... -- [] -- (0, ..." (exit 0, block written). D4 "(updated)" with no mention
  of the edit, uninstall "was edited, left in place". D5 "git still ignores .fwx/decisions.tsv (.gitignore:4:*.tsv) -- no line from the
  end of the file can beat that rule". D6 two `git rev-parse` per profile with the framework off. D7 the block in LF after CRLF lines.
Negative controls on the finished code, each mutation put back (the checks that went red are named in the commit message):
  M1 one shared tag, M2 probe without the parent .gitignore files, M3 "no answer" read as success, M4 a git call before the claims
  in drop, M5 line ending always LF, M6 no tsv line in the block, M7a an edited block not removable, M7b sync silent about the
  edit, M8 the block never moved to the end, M9 the worktrees sample taken out of the probe (the 4c worktrees check of D8 fails,
  its old form `... if "md" in rel else True` passes).
"""
import argparse
import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

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
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CLAUDE_CONFIG_DIR"):
    os.environ.pop(var, None)
XDG = os.path.join(TOY, "xdg")  # the global ignore file git reads by default lives under it: a toy, so no check reads the machine's
os.environ["XDG_CONFIG_HOME"] = XDG
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, sandbox.FORGE)
from forge import lib  # noqa: E402

BASE_SETTINGS = os.path.join(TOY, "forge-base.json")
with open(BASE_SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
lib.SETTINGS = BASE_SETTINGS
from forge import cli, fwxignore, owned, sync, uninstall  # noqa: E402

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


def block(prefix="", name=NAME, tag=""):
    """The block as forge writes it; `tag` (the project's place, "sub/") only in the exclude file of a repository."""
    t = " " + tag if tag else ""
    return ["# BEGIN FORGE-FWX%s (managed by forge, do not edit inside)" % t, "!/%s.fwx/**/*.md" % prefix, "!/%s.fwx/**/*.tsv" % prefix,
            "/%s.claude/%s.json" % (prefix, name), "/%s.claude/worktrees/" % prefix, "# END FORGE-FWX%s" % t]


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
        make_worktree(p)
        if "worktrees" in rel:  # D8: this used to be `... if "md" in rel else True`, which looked at nothing for this case
            check("4c: (%s) and the outcome is right: a real worktree stays out of git status, the documents show" % why,
                  code == 0 and ignored(p, rel)[0] and not seen(p)[3] and seen(p)[0], (code, status(p), out))
        else:
            check("4c: (%s) and the outcome is right: the documents show" % why, code == 0 and seen(p)[0], (code, status(p), out))

# ------------------------------------------------------------------------------------------------------ 5. broken markers
B, E = block()[0], block()[-1]
for label, body, line in (("BEGIN without END", STAR + B + "\n!/.fwx/**/*.md\n", 4),
                          ("END without BEGIN", STAR + "!/.fwx/**/*.md\n" + E + "\n", 5),
                          ("two blocks", STAR + btext() + "dist/\n" + btext(), 11),
                          ("edited marker text", STAR + btext().replace("(managed by forge, do not edit inside)", "(managed by hand)"), 4),
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
# a block edited by hand is forge's too (D4: everything between the markers is forge's): it goes, and nothing is said as `!`
p, w = fresh(STAR)
w.run()
put(gi(p), text(gi(p)).replace("/.claude/worktrees/", "/.claude/worktrees/\n/.my-extra/"))
w.put(profile(p, name="toyapp", framework=False))
code, out = w.run()
check("6: an edited block is removed with the rest of it, like sync rewrites it -- %s" % bang(out),
      text(gi(p)) == STAR and code == 0 and not bang(out), (text(gi(p)), out))
# forge uninstall NAME
p, w = fresh(orig)
w.run()
w.drop("toyapp")
sync.CFG, lib.PROFILES = w.cfg, w.pdir
o = io.StringIO()
with contextlib.redirect_stdout(o):
    code = uninstall.main(argparse.Namespace(integration=None, project="toyapp", apply=True))
check("6: forge uninstall NAME: exit 0 -- %s" % sandbox.tail(o.getvalue(), 3), code == 0, o.getvalue())
check("6: forge uninstall NAME: removes exactly the block -- %s" % (text(gi(p)) or "").splitlines(), text(gi(p)) == orig, text(gi(p)))
check("6: forge uninstall NAME: no claim of the block is left", not [x for x in owned.previous(gi(p))[0] if x["at"][:1] == ["block"]], "")

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

# ------------------------------------------------------------ 10. D1: two projects in one repository
def mono(gitignore, *subs):
    """A toy repository (the .gitignore committed) with empty directories `subs`; returns its top."""
    _p[0] += 1
    top = os.path.join(TOY, "toymono%d" % _p[0])
    os.makedirs(top)
    sandbox.git(top, "init", "-q", "-b", "main")
    sandbox.git(top, "commit", "-q", "--allow-empty", "-m", "init")
    put(gi(top), gitignore)
    sandbox.git(top, "add", "-A")
    sandbox.git(top, "commit", "-q", "-m", "ignore")
    for sub in subs:
        os.makedirs(os.path.join(top, sub))
    return top


def only(world_name, ppath, **over):
    """A world holding the one profile `world_name`: a sync of it alone."""
    w_ = World()
    w_.put(profile(ppath, name=world_name, **over))
    return w_


top = mono("node_modules/\n", "a", "b")
ex = os.path.join(top, ".git", "info", "exclude")
ex0 = text(ex)
pa, pb = os.path.join(top, "a"), os.path.join(top, "b")
wa, wb = only("proja", pa, writes_tracked_files=False), only("projb", pb, writes_tracked_files=False)
both = World()
both.put(profile(pa, name="proja", writes_tracked_files=False))
both.put(profile(pb, name="projb", writes_tracked_files=False))
code, out = both.run()
ta, tb = btext(prefix="a/", tag="a/"), btext(prefix="b/", tag="b/")
# D1 on the base (a11e284): "framework -> .../exclude FORGE-FWX block (updated; ...)" for both on every run, and the exclude holds
# only /b/ lines: -- ['# BEGIN FORGE-FWX (managed by forge)', '!/b/.fwx/**/*.md', '/b/.claude/toyfw.json', '/b/.claude/worktrees/', ...]
check("D1: two projects of one repository with writes_tracked_files false: each keeps its own block in .git/info/exclude -- %s"
      % (text(ex) or "").splitlines()[-12:], code == 0 and ta in text(ex) and tb in text(ex), (code, out))
check("D1: and there are exactly two blocks in it", (text(ex) or "").count("# BEGIN FORGE-FWX") == 2, text(ex))
check("D1: git ignores both generated files and both worktrees folders",
      all(ignored(q, rel)[0] for q in (pa, pb) for rel in (".claude/toyfw.json", ".claude/worktrees/x")), "")
before = (raw(ex), REG())
code, out = both.run()
check("D1: a second run of both changes nothing and says already current for both, never updated -- %s" % blines(out),
      before == (raw(ex), REG()) and len([l for l in blines(out) if "already current" in l]) == 2
      and not any("updated" in l for l in blines(out)), (blines(out)))
snapshot = raw(ex)
for order in (wa, wb, wb, wa, wa, wb):
    order.run()
check("D1: runs of each project alone, in any order, leave both blocks and the exclude as it was", raw(ex) == snapshot,
      (text(ex) or "").splitlines()[-14:])
# one project is switched off: only its own lines go
wa.put(profile(pa, name="proja", framework=False, writes_tracked_files=False))
code, out = wa.run()
check("D1: proja with framework false takes out its own block and leaves projb's whole -- %s" % (text(ex) or "").splitlines()[-8:],
      code == 0 and ta not in text(ex) and tb in text(ex) and (text(ex) or "").count("# BEGIN FORGE-FWX") == 1, (code, out))
wa.put(profile(pa, name="proja", writes_tracked_files=False))
wa.run()
check("D1: and turned on again it gets its block back beside projb's", ta in text(ex) and tb in text(ex), text(ex))
# forge uninstall NAME of one
wb.drop("projb")
sync.CFG, lib.PROFILES = wb.cfg, wb.pdir
o = io.StringIO()
with contextlib.redirect_stdout(o):
    code = uninstall.main(argparse.Namespace(integration=None, project="projb", apply=True))
check("D1: forge uninstall projb (a directory of the repository) removes projb's block only, exit 0 -- %s"
      % sandbox.tail(o.getvalue(), 3), code == 0 and tb not in text(ex) and ta in text(ex), (code, o.getvalue(), text(ex)))
w_off = World()
w_off.put(profile(pa, name="proja", framework=False, writes_tracked_files=False))
w_off.run()
check("D1: the last one off leaves the exclude as git made it", text(ex) == ex0, text(ex))

# the same two-projects-in-one-repository case with the repo's .gitignore written by forge: each its own file
top = mono("*.md\n", "b")
tb_ = os.path.join(top, "b")
w1, w2 = only("projroot", top), only("projsub", tb_)
both = World()
both.put(profile(top, name="projroot"))
both.put(profile(tb_, name="projsub"))
code, out = both.run()
check("D1 (tracked .gitignore): the project at the root and the one in b each carry their own block, exit 0 -- %s" % bang(out),
      code == 0 and all((text(f) or "").count("# BEGIN FORGE-FWX") == 1 and "/.claude/toyfw.json" in text(f).splitlines()
                        for f in (gi(top), gi(tb_))), (code, out))
make_docs(top)
make_docs(tb_)
st = "\n".join(status(top))
check("D1 (tracked .gitignore): the documents of both show -- %s" % status(top),
      ".fwx/decisions.tsv" in st and "b/.fwx/decisions.tsv" in st and ".fwx/milestones/v1/phases/01-x/context.md" in st
      and "b/.fwx/milestones/v1/phases/01-x/context.md" in st, status(top))
before = (raw(gi(top)), raw(gi(tb_)), REG())
for order in (w1, w2, both, w2, w1):
    order.run()
check("D1 (tracked .gitignore): runs in any order change nothing", before == (raw(gi(top)), raw(gi(tb_)), REG()), "")
w2.put(profile(tb_, name="projsub", framework=False))
w2.run()
check("D1 (tracked .gitignore): the sub project off removes its block (its file is gone) and the root's stays whole",
      not os.path.exists(gi(tb_)) and text(gi(top)) == before[0].decode(), (text(gi(tb_)), text(gi(top))))

# ------------------------------------------------------------ 11. D2: rules above the project, in the repository's layout
# D2 on the base: exit 0 with "FORGE-FWX block (created; in .git/info/exclude: ...)" and no `!` line, while
# `git check-ignore -v --no-index .fwx/x/y.md` says `.gitignore:1:*.md`.
top = mono("*.md\n", "app")
app = os.path.join(top, "app")
w = only("sub", app, writes_tracked_files=False)
code, out = w.run()
check("D2: a project in a directory, its rules in the repository's root .gitignore: exit 1 and a `!` line naming the root rule -- %s" % bang(out),
      code == 1 and any(".fwx/x/y.md" in l and ".gitignore:1:*.md" in l for l in bang(out)), (code, out))
code, out = w.run()
check("D2: the second run does not turn that into a success -- %s" % bang(out), code == 1 and bool(bang(out)), (code, out))
w.run(apply=False)
code, out = w.run(apply=False)
check("D2: nor does a dry-run", code == 1 and bool(bang(out)), (code, out))
r = cli.framework_ignore_row("sub")
check("D2: sync and the doctor row agree -- %s %s" % (r.level, r.detail), r.level == "FAIL", r)
# the repository's rules already give the wanted answer for a project in a directory (the generated file ignored, the documents not)
top = mono(".claude/\n", "app")
w = only("sub", os.path.join(top, "app"), writes_tracked_files=False)
code, out = w.run()
check("D2: root rules that already ignore .claude/ and not the documents: `already current` and exit 0 is true", code == 0 and not bang(out) and any("already current" in l for l in blines(out))
      and ignored(os.path.join(top, "app"), ".fwx/x/y.md")[0] is False, (code, out))
# a rule above a project whose .gitignore forge writes: a directory rule it cannot beat is a `!` line, not a success
top = mono("/app/.fwx/\n", "app")
w = only("sub", os.path.join(top, "app"))
code, out = w.run()
check("D2: tracked .gitignore of a project in a directory, a root rule `/app/.fwx/`: exit 1, the `!` line names that rule -- %s" % bang(out),
      code == 1 and any(".gitignore:1:/app/.fwx/" in l for l in bang(out)), (code, out))
# a root `*.md` is beaten by the project's own block, which sits deeper
top = mono("*.md\n", "app")
w = only("sub", os.path.join(top, "app"))
code, out = w.run()
make_docs(os.path.join(top, "app"))
check("D2: control: a root `*.md` above a project whose own .gitignore carries the block is beaten by it: exit 0, documents show",
      code == 0 and seen(os.path.join(top, "app"))[0], (code, out))

# ------------------------------------------------------------ 12. D3: it cannot be checked
# D3 on the base: exit 0 and "framework -> .../.gitignore FORGE-FWX block (created)" with no `!`, the file written, STAR unchanged...
p, w = fresh(STAR)
real_tempdir = tempfile.tempdir
tempfile.tempdir = os.path.join(TOY, "no-such-scratch-dir")
try:
    code, out = w.run()
finally:
    tempfile.tempdir = real_tempdir
check("D3: no scratch directory: exit 1 and a `!` line that says what could not be checked, NOT RUN, NOT ARMED -- %s" % bang(out),
      code == 1 and any("could not check" in l and "NOT RUN, NOT ARMED" in l for l in bang(out)), (code, out))
check("D3: nothing is written: no block, no claim, no generated file", text(gi(p)) == STAR and not owned.previous(gi(p), "framework")[0]
      and not os.path.exists(os.path.join(p, ".claude", NAME + ".json")), text(gi(p)))
p, w = fresh(STAR)
real_run = subprocess.run


def silent_git(args, *a, **kw):
    if "check-ignore" in args:
        raise subprocess.TimeoutExpired(args, 1)
    return real_run(args, *a, **kw)


subprocess.run = silent_git
try:
    code, out = w.run()
finally:
    subprocess.run = real_run
check("D3: git gives no answer: exit 1, the same `!` line, nothing written -- %s" % bang(out),
      code == 1 and any("could not check" in l and "NOT RUN, NOT ARMED" in l for l in bang(out)) and text(gi(p)) == STAR, (code, out))
p, w = fresh(STAR, commit=True, writes_tracked_files=False)
tempfile.tempdir = os.path.join(TOY, "no-such-scratch-dir")
try:
    code, out = w.run()
finally:
    tempfile.tempdir = real_tempdir
check("D3: the same for a project whose block goes to .git/info/exclude", code == 1 and any("NOT RUN, NOT ARMED" in l for l in bang(out))
      and "FORGE-FWX" not in (text(os.path.join(p, ".git", "info", "exclude")) or ""), (code, out))

# a project that is a linked worktree: where info/exclude is comes from git, and when git does not say, that is not "no rules"
main_ = project(STAR, commit=True)
wt_ = os.path.join(TOY, "toylinked%d" % _p[0])
sandbox.git(main_, "worktree", "add", "-q", wt_, "-b", "lw-%d" % _p[0])
w = only("linked", wt_)
real_exclude_site = lib.exclude_site
lib.exclude_site = lambda *a, **k: None
try:
    code, out = w.run()
finally:
    lib.exclude_site = real_exclude_site
check("D3: a linked worktree whose info/exclude git does not place: exit 1, NOT RUN, NOT ARMED, nothing written -- %s" % bang(out),
      code == 1 and any("NOT RUN, NOT ARMED" in l for l in bang(out)) and text(gi(wt_)) == STAR, (code, out))

# ------------------------------------------------------------ 13. D4: everything between the markers is forge's
# D4 on the base: sync said `(updated)` and uninstall `... ["block","FORGE-FWX"] was edited, left in place`.
p, w = fresh(STAR)
w.run()
put(gi(p), text(gi(p)).replace("/.claude/worktrees/", "/.claude/worktrees/\n/.my-extra/"))
code, out = w.run()
check("D4: sync rewrites a block edited inside the markers, and the line says it differed from what forge writes -- %s" % blines(out),
      code == 0 and text(gi(p)) == STAR + btext() and any("differed from what forge writes" in l for l in blines(out)), (text(gi(p)), blines(out)))
out = w.run()[1]
check("D4: a sync of a block that is right says already current and nothing of the kind -- %s" % blines(out),
      bool(blines(out)) and all("already current" in l and "differed" not in l for l in blines(out)), blines(out))
check("D4: the BEGIN line tells the reader not to edit inside", "do not edit inside" in block()[0], block()[0])
put(gi(p), text(gi(p)).replace("/.claude/worktrees/", "/.claude/worktrees/\n/.my-extra/"))
w.drop("toyapp")
sync.CFG, lib.PROFILES = w.cfg, w.pdir
o = io.StringIO()
with contextlib.redirect_stdout(o):
    code = uninstall.main(argparse.Namespace(integration=None, project="toyapp", apply=True))
check("D4: uninstall removes a block edited inside the markers, with no `edited, left in place` line -- %s" % sandbox.tail(o.getvalue(), 3),
      code == 0 and text(gi(p)) == STAR and "left in place" not in o.getvalue(), (code, o.getvalue(), text(gi(p))))

# ------------------------------------------------------------ 14. D5: the fix text is true, and a tsv rule is beaten
# D5 on the base: exit 1, "git still ignores .fwx/decisions.tsv (.gitignore:3:*.tsv) -- no line from the end of the file can beat that rule"
for why, rules in (("a `*.tsv` rule", STAR + "*.tsv\n"), ("a `*` allowlist with `!*/` and `!*.py`", "*\n!*/\n!*.py\n")):
    p, w = fresh(rules)
    code, out = w.run()
    make_docs(p)
    check("D5: %s: exit 0, no `!` line -- %s" % (why, bang(out)), code == 0 and not bang(out), (code, out))
    check("D5: %s: the markdown and the tsv both show in git status -- %s" % (why, status(p)), seen(p)[:2] == (True, True), status(p))
q = project("*.tsv\n" + btext().replace("!/.fwx/**/*.tsv\n", ""))
make_docs(q)
check("D5 control: without the tsv line a `*.tsv` rule keeps the tsv ignored (the line is needed)", seen(q)[1] is False, status(q))
p, w = fresh(STAR + ".fwx/\n")
code, out = w.run()
check("D5: a rule the block cannot beat (`.fwx/`): exit 1 and a fix text that claims no impossibility -- %s" % bang(out),
      code == 1 and bang(out) and not any("no line from the end" in l for l in bang(out)) and any("un-ignores only" in l for l in bang(out)), (code, out))

# ------------------------------------------------------------ 15. D6: a project without the framework forks no git of its own
# D6 on the base: 2 `git rev-parse` calls per profile with the framework off (--git-common-dir, --show-prefix).
p, w = fresh(STAR, framework=False)
calls = []


def spy(args, *a, **kw):
    calls.append(list(args))
    return real_run(args, *a, **kw)


subprocess.run = spy
try:
    code, out = w.run(apply=False)
finally:
    subprocess.run = real_run
rp = [c for c in calls if "rev-parse" in c]
check("D6: a profile with framework false, never given a block, runs no git rev-parse -- %s" % rp, code == 0 and not rp, (calls, out))
# ... and one that had a block is still cleaned (the registry tells where, not git)
p, w = fresh(STAR, commit=True, writes_tracked_files=False)
w.run()
w.put(profile(p, name="toyapp", framework=False, writes_tracked_files=False))
subprocess.run = spy
calls[:] = []
try:
    code, out = w.run()
finally:
    subprocess.run = real_run
check("D6: a profile that had its block in .git/info/exclude loses it with no rev-parse either -- %s" % [c for c in calls if "rev-parse" in c],
      "FORGE-FWX" not in (text(os.path.join(p, ".git", "info", "exclude")) or "") and not [c for c in calls if "rev-parse" in c], (calls, out))

# ------------------------------------------------------------ 16. D7: the line ending the file uses
# D7 on the base: b'*.md\r\nnode_modules/\r\n# BEGIN FORGE-FWX (managed by forge)\n!/.fwx/**/*.md\n...' (the block in LF).
for why, orig_ in (("CRLF", b"*.md\r\nnode_modules/\r\n"), ("CRLF without a last break", b"*.md\r\nnode_modules/")):
    p, w = fresh("")
    with open(gi(p), "wb") as fh:
        fh.write(orig_)
    code, out = w.run()
    got = raw(gi(p)) or b""
    check("D7: %s file: every line break after the block went in is CRLF -- %s" % (why, got), b"\n" not in got.replace(b"\r\n", b"")
          and got.startswith(orig_) and got.endswith(b"# END FORGE-FWX\r\n"), got)
    before = raw(gi(p))
    w.run()
    check("D7: %s: the second run is byte-identical" % why, raw(gi(p)) == before, raw(gi(p)))
    if orig_.endswith(b"\r\n"):
        w.put(profile(p, name="toyapp", framework=False))
        w.run()
        check("D7: %s: framework false gives the original bytes back" % why, raw(gi(p)) == orig_, raw(gi(p)))
p, w = fresh(STAR)
w.run()
check("D7: control: an LF file stays LF", b"\r" not in (raw(gi(p)) or b""), raw(gi(p)))

# ------------------------------------------------------------ 17. framework_ignore_block: false, a project that keeps .fwx out of this git
# Seen failing on adb68b7 before the field existed: (a) "exit 0 ... -- (1, ..." (the D2 `!` line, exit 1, for a repo whose
# `/*` ignores .fwx on purpose); (b) the block stayed; (d) "framework_ignore_block is refused by profile_error -- None";
# (e) the row said FAIL (`git still ignores .fwx/x/y.md (.gitignore:1:/*)`).
SKIP_TXT = "NOT RUN, NOT ARMED: framework_ignore_block is false"


def fresh_all_ignored(rules, **over):
    """A repository whose committed .gitignore (force-added: its own `/*` ignores it) is `rules`."""
    q = project(rules)
    sandbox.git(q, "add", "-f", ".gitignore")
    sandbox.git(q, "commit", "-q", "-m", "ignore")
    w_ = World()
    w_.put(profile(q, **over))
    return q, w_


for why, kw in (("writes_tracked_files false, rules in the repo's .gitignore", dict(writes_tracked_files=False)),
                ("its own .gitignore", {})):
    p, w = fresh_all_ignored("/*\n", framework_ignore_block=False, **kw)
    ex = os.path.join(p, ".git", "info", "exclude")
    before = (raw(gi(p)), raw(ex), REG())
    code, out = w.run()
    check("17a: %s, `/*` ignores .fwx on purpose: exit 0, no `!` line, one SKIP line -- %s" % (why, bang(out)),
          code == 0 and not bang(out) and len([l for l in out.splitlines() if SKIP_TXT in l]) == 1, (code, out))
    check("17a: %s: nothing written to .gitignore, .git/info/exclude or the registry's block claims" % why,
          (raw(gi(p)), raw(ex)) == before[:2] and not [c for c in owned.previous(ex)[0] + owned.previous(gi(p))[0] if owned.is_block(c)], text(gi(p)))
    code, out = w.run(apply=False)
    check("17a: %s: a dry-run says the same and exits 0" % why, code == 0 and any(SKIP_TXT in l for l in out.splitlines()) and not bang(out), (code, out))
    r = row()
    check("17e: %s: the doctor row is a SKIP with NOT RUN, NOT ARMED, neither PASS nor FAIL -- %s %s" % (why, r.level, r.detail),
          r.level == "SKIP" and r.detail.startswith("NOT RUN, NOT ARMED: ") and "framework_ignore_block" in r.detail, r)
# (b) a block written earlier goes, and nothing else in the file changes
for why, kw, site in (("tracked .gitignore", {}, gi), ("info/exclude", dict(writes_tracked_files=False), lambda q: os.path.join(q, ".git", "info", "exclude"))):
    p, w = fresh("node_modules/\n", commit=True, **kw)
    ex_before = text(os.path.join(p, ".git", "info", "exclude"))
    gi_before = text(gi(p))
    w.run()
    check("17b: setup (%s): the block is there -- %s" % (why, (text(site(p)) or "").splitlines()[-7:]), "FORGE-FWX" in (text(site(p)) or ""), text(site(p)))
    w.put(profile(p, name="toyapp", framework_ignore_block=False, **kw))
    code, out = w.run(apply=False)
    check("17b: %s: a dry-run says it would remove the block and writes nothing" % why,
          any("would remove" in l for l in blines(out)) and "FORGE-FWX" in (text(site(p)) or ""), blines(out))
    code, out = w.run()
    check("17b: %s: the block is removed, the file is what it was before forge, the SKIP line is there, exit 0 -- %s" % (why, bang(out)),
          code == 0 and text(gi(p)) == gi_before and text(os.path.join(p, ".git", "info", "exclude")) == ex_before
          and any(SKIP_TXT in l for l in out.splitlines()) and not bang(out), (code, out))
    check("17b: %s: no claim of the block is left" % why, not [c for c in owned.previous(site(p))[0] if owned.is_block(c)], owned.previous(site(p))[0])
# (c) the field absent, true or null-free: the D2 case is still the `!` line and exit 1
p, w = fresh_all_ignored("/*\n", writes_tracked_files=False)
code, out = w.run()
check("17c: field absent: the repo that ignores .fwx gives the `!` line, exit 1, and the line names the field as the other way out -- %s" % bang(out),
      code == 1 and any(".gitignore:1:/*" in l and "framework_ignore_block" in l for l in bang(out)), (code, out))
p, w = fresh_all_ignored("/*\n", writes_tracked_files=False, framework_ignore_block=True)
code, out = w.run()
check("17c: field true is the same as absent", code == 1 and bool(bang(out)) and not any(SKIP_TXT in l for l in out.splitlines()), (code, out))
# the row with one managed and one switched-off project looks at the first only
pm, wm = fresh(STAR)
off_p, _ = fresh_all_ignored("/*\n")
wm.put(profile(off_p, name="offproj", framework_ignore_block=False))
wm.run()
r = row()
check("17e: one project looked at, one switched off: PASS, and the detail names the switched-off one -- %s %s" % (r.level, r.detail),
      r.level == "PASS" and "looked at 1 project" in r.detail and "offproj (framework_ignore_block is false: switched off)" in r.detail, r)
# (d) the type
for bad in ("no", 0, None, [], {}):
    why = lib.profile_error(profile(project(), framework_ignore_block=bad))
    check("17d: framework_ignore_block %r is a profile error naming the field -- %s" % (bad, why), bool(why) and "framework_ignore_block" in why, why)
check("17d: true and false are accepted", all(lib.profile_error(profile(project(), framework_ignore_block=v)) is None for v in (True, False)), "")
p, w = fresh(STAR, framework_ignore_block="no")
code, out = w.run()
check("17d: a sync of a profile with \"no\" exits non-zero and writes nothing to the project -- %s" % bang(out)[:2],
      code != 0 and text(gi(p)) == STAR, (code, out))

# ------------------------------------------------------------ 18. second review of the PR
def check_ignore_calls(calls):
    return [c for c in calls if "check-ignore" in c]


@contextlib.contextmanager
def git_stub(decide):
    """subprocess.run replaced: decide(args, k) is None (run for real), an exception (raised) or the CompletedProcess to
    answer; k counts the `git check-ignore` calls so far, this one included."""
    real = subprocess.run
    calls = []

    def fake(args, *a, **kw):
        calls.append(list(args))
        r = decide(list(args), len(check_ignore_calls(calls)))
        if r is None:
            return real(args, *a, **kw)
        if isinstance(r, BaseException):
            raise r
        return r

    subprocess.run = fake
    try:
        yield calls
    finally:
        subprocess.run = real


def cp(args, rc, out="", err=""):
    return subprocess.CompletedProcess(args, rc, out, err)


def silent(a, k):
    """A git whose check-ignore never answers."""
    return subprocess.TimeoutExpired(a, 1) if "check-ignore" in a else None


@contextlib.contextmanager
def global_ignore(rules, via_config=True):
    """The user's global ignore file holding `rules`: named by core.excludesFile of a toy global config, or at the default
    place under the toy XDG_CONFIG_HOME. Yields its path; the environment is put back."""
    _n[0] += 1
    d = os.path.join(TOY, "gl%d" % _n[0])
    os.makedirs(d)
    saved = (os.environ["GIT_CONFIG_GLOBAL"], os.environ["XDG_CONFIG_HOME"])
    if via_config:
        ign = os.path.join(d, "global-ignore")
        put(ign, rules)
        put(os.path.join(d, "config"), "[core]\n\texcludesFile = %s\n" % ign)
        os.environ["GIT_CONFIG_GLOBAL"] = os.path.join(d, "config")
    else:
        ign = os.path.join(d, "xdg", "git", "ignore")
        put(ign, rules)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(d, "xdg")
    try:
        yield ign
    finally:
        os.environ["GIT_CONFIG_GLOBAL"], os.environ["XDG_CONFIG_HOME"] = saved


# 18.0 a `git check-ignore` that says anything but 0 or 1 is no answer
# Mutation (`return None` -> `continue` in _probe) left this file at 146 checks, 0 failures; with it: exit 0 and the block written.
p, w = fresh(STAR)
with git_stub(lambda a, k: cp(a, 128, "", "fatal: detected dubious ownership") if "check-ignore" in a else None):
    code, out = w.run()
check("18.0: check-ignore exits 128: exit 1, a `!` line that says what could not be checked, nothing written -- %s" % bang(out),
      code == 1 and any("could not check" in l and "NOT RUN, NOT ARMED" in l for l in bang(out)) and text(gi(p)) == STAR
      and not os.path.exists(os.path.join(p, ".claude", NAME + ".json")), (code, out))

# 18.2 sync and doctor are one decision, and it sees what git sees: .gitignore files under .fwx/ and .claude/
# Seen failing on 85c0c8b: sync exit 0 with no `!` while the doctor said FAIL (.fwx/.gitignore:1:*.md, .claude/.gitignore:1:!toyfw.json).
def below(rel, body):
    def setup():
        p_, w_ = fresh(STAR)
        put(os.path.join(p_, rel), body)
        return p_, w_
    return setup


def exclude_mode_root_rule():
    q_ = mono("*.md\n", "app")
    return os.path.join(q_, "app"), only("sub", os.path.join(q_, "app"), writes_tracked_files=False)


SCENARIOS = (("a `*.md` in .fwx/.gitignore", below(".fwx/.gitignore", "*.md\n"), False),
             ("a `*.tsv` in .fwx/.gitignore", below(".fwx/.gitignore", "*.tsv\n"), False),
             ("a `!toyfw.json` in .claude/.gitignore", below(".claude/.gitignore", "!toyfw.json\n"), False),
             ("a `!worktrees/` in .claude/.gitignore", below(".claude/.gitignore", "!worktrees/\n"), False),
             ("a root `*.md` above a project of the exclude mode", exclude_mode_root_rule, False),
             ("nothing under the project", lambda: fresh(STAR), True))
for label, setup, clean_wanted in SCENARIOS:
    p, w = setup()
    code, out = w.run()
    r = row()
    clean = code == 0 and not bang(out)
    check("18.2: %s: sync (%s) and the doctor row (%s) agree, and clean is %s -- %s" % (label, "clean" if clean else "`!`", r.level, clean_wanted, bang(out)[:1]),
          clean == clean_wanted and (r.level == "PASS") == clean_wanted, (code, out, r))
p, w = below(".fwx/.gitignore", "*.md\n")()
code, out = w.run()
check("18.2: the `!` line names the rule of the file under .fwx/ -- %s" % bang(out), any(".fwx/.gitignore:1:*.md" in l for l in bang(out)), (code, out))
r = row()
check("18.2: and the doctor's FAIL names it and does not tell a project that writes its own .gitignore to carry the block in it -- %s" % r.detail,
      r.level == "FAIL" and ".fwx/.gitignore:1:*.md" in r.detail and "carry the block" not in r.detail, r)

# 18.3 the global ignore is the machine's own: read by sync and doctor alike, and named as the cause
# Seen failing on 85c0c8b: with core.excludesFile naming a file with `.fwx/`, sync exit 0 while git status hid the documents and the doctor said FAIL.
for how, kw in (("core.excludesFile", dict(via_config=True)), ("the default file under XDG_CONFIG_HOME", dict(via_config=False))):
    with global_ignore(".fwx/\n", **kw) as g:
        p, w = fresh(STAR)
        code, out = w.run()
        make_docs(p)
        r = row()
        check("18.3: a global ignore (%s) that ignores .fwx/: exit 1, the `!` line names that file as the machine's own setting -- %s" % (how, bang(out)),
              code == 1 and any("global ignore %s:1:.fwx/" % g in l and "this machine's own setting" in l for l in bang(out)), (code, out))
        check("18.3: (%s) git status agrees (the documents are hidden), and so does the doctor -- %s" % (how, r.level),
              ".fwx/decisions.tsv" not in "\n".join(status(p)) and r.level == "FAIL" and "this machine's own setting" in r.detail, (status(p), r))
with global_ignore("*.md\n") as g:
    p, w = fresh("node_modules/\n")
    code, out = w.run()
    make_docs(p)
    check("18.3: a global `*.md` is beaten by the block, as git would: exit 0, the documents show -- %s" % status(p),
          code == 0 and not bang(out) and seen(p)[:2] == (True, True), (code, out))
# The scratch reads no other git config: a template directory of the global config holding an exclude file would be copied into it.
_n[0] += 1
tpl = os.path.join(TOY, "tpl%d" % _n[0])
put(os.path.join(tpl, "info", "exclude"), ".fwx/\n")
tplcfg = os.path.join(TOY, "tplcfg%d" % _n[0])
put(tplcfg, "[init]\n\ttemplateDir = %s\n" % tpl)
p, w = fresh(STAR)
os.remove(os.path.join(p, ".git", "info", "exclude"))
saved_cfg = os.environ["GIT_CONFIG_GLOBAL"]
os.environ["GIT_CONFIG_GLOBAL"] = tplcfg
try:
    code, out = w.run()
finally:
    os.environ["GIT_CONFIG_GLOBAL"] = saved_cfg
check("18.3: a global config with init.templateDir is not read by the scratch repository: exit 0 -- %s" % bang(out)[:1],
      code == 0 and not bang(out), (code, out))

# 18.4 a project path with glob characters
# Seen failing on 85c0c8b: "exit 1 ... git does not ignore .claude/toyfw.json (no rule) ... a rule of the repo's own .gitignore ranks above" (there is none).
for dirname in ("a+b(c)[d]", "sp ace\\back", "st*r?"):
    q = mono("node_modules/\n", dirname)
    pq = os.path.join(q, dirname)
    wq = only("glob", pq, writes_tracked_files=False)
    code, out = wq.run()
    exq = os.path.join(q, ".git", "info", "exclude")
    esc = "".join("\\" + c if c in "\\[]*?" else c for c in dirname)
    check("18.4: project `%s` in .git/info/exclude: exit 0, its lines escaped -- %s" % (dirname, bang(out)),
          code == 0 and not bang(out) and "/%s/.claude/toyfw.json" % esc in (text(exq) or "").splitlines(), (code, out, text(exq)))
    check("18.4: `%s`: git ignores the generated file and the worktrees folder" % dirname,
          ignored(pq, ".claude/toyfw.json")[0] and ignored(pq, ".claude/worktrees/x")[0], "")
    before = raw(exq)
    code, out = wq.run()
    check("18.4: `%s`: the second run is already current and changes nothing" % dirname,
          raw(exq) == before and any("already current" in l for l in blines(out)), blines(out))

# 18.5 two projects in one repository that both stay wrong: one write per sync, and no false reason
# Seen failing on 85c0c8b: every run "(updated; moved to the end of the file: a later line decided .fwx/x/y.md (.gitignore:1:*.md))", twice.
q = mono("*.md\n", "a", "b")
both = World()
both.put(profile(os.path.join(q, "a"), name="proja", writes_tracked_files=False))
both.put(profile(os.path.join(q, "b"), name="projb", writes_tracked_files=False))
exq = os.path.join(q, ".git", "info", "exclude")
both.run()
writes = []
real_write_text = lib.write_text
lib.write_text = lambda path, *a, **k: (writes.append(path), real_write_text(path, *a, **k))[1]
try:
    outs = [both.run()[1] for _ in range(3)]
finally:
    lib.write_text = real_write_text
check("18.5: three more runs of two projects held by a rule they cannot beat write the exclude file %d times" % len([x for x in writes if x == exq]),
      not [x for x in writes if x == exq], writes)
check("18.5: and say `already current` for both, never `moved` -- %s" % blines(outs[0]),
      all(len([l for l in blines(o) if "already current" in l]) == 2 and not any("moved" in l for l in blines(o)) for o in outs), outs[0])

# 18.7 two profiles with the same `project` name in different directories of a repository (nothing in forge refuses that)
# Seen failing on 85c0c8b: the one that is off removed the block of the one that is on, on every sync, which put it back.
q = mono("node_modules/\n", "a", "b")
w7 = World()
for nm, pp, on in (("proja", os.path.join(q, "a"), True), ("projb", os.path.join(q, "b"), False)):
    with open(os.path.join(w7.pdir, nm + ".claude.json"), "w") as fh:
        json.dump(profile(pp, name="shared", writes_tracked_files=False, framework=on), fh)
    w7.names.add(nm)
exq = os.path.join(q, ".git", "info", "exclude")
for i in range(3):
    code, out = w7.run()
check("18.7: the profile that is off removes nothing of the one that is on (the same `project`) -- %s" % (text(exq) or "").splitlines()[-7:],
      code == 0 and btext(prefix="a/", tag="a/") in (text(exq) or "") and "FORGE-FWX b/" not in (text(exq) or ""), (code, out))

# 18.8 the scratch repository is removed on every way out
# Mutation `mkdtemp` without cleanup: 94 folders left in the second review's run and the file said 0 failures.
scr = os.path.join(TOY, "scratch-tmp")
os.makedirs(scr)
real_tempdir = tempfile.tempdir
tempfile.tempdir = scr
try:
    p, w = fresh(STAR)
    w.run()
    p, w = fresh(STAR)
    with git_stub(silent):
        w.run()
    real_probe = fwxignore._probe
    fwxignore._probe = lambda *a, **k: 1 / 0
    try:
        fwxignore.ensure(False, p, NAME, False, "toyapp")
    except ZeroDivisionError:
        pass
    finally:
        fwxignore._probe = real_probe
    left = [x for x in os.listdir(scr) if x.startswith("forge-fwx-")]
finally:
    tempfile.tempdir = real_tempdir
check("18.8: a success, a git that does not answer and an exception leave no forge-fwx-* folder -- %s" % left, left == [], left)
fakebin = os.path.join(TOY, "fakegit")
os.makedirs(fakebin)
mark = os.path.join(TOY, "probe-started")
with open(os.path.join(fakebin, "git"), "w") as fh:
    fh.write('#!/bin/sh\ncase "$*" in *check-ignore*) : > "$FWX_MARK"; exec %s 30;; esac\nexec %s "$@"\n' % (shutil.which("sleep", path="/usr/bin:/bin"), shutil.which("git")))
os.chmod(os.path.join(fakebin, "git"), 0o755)
scr2 = os.path.join(TOY, "scratch-tmp2")
os.makedirs(scr2)
p, w = fresh(STAR)
child = subprocess.Popen([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\nfrom forge import fwxignore\n"
                          "fwxignore.ensure(False, %r, 'toyfw', False, 'toyapp')" % (sandbox.FORGE, p)],
                         env={"HOME": HOME, "PATH": fakebin, "TMPDIR": scr2, "FWX_MARK": mark, "PYTHONDONTWRITEBYTECODE": "1",
                              "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
rc = None
try:
    for _ in range(300):
        if os.path.exists(mark):
            break
        time.sleep(0.1)
    started = os.path.exists(mark)
    child.send_signal(signal.SIGTERM)
    rc = child.wait(timeout=30)
finally:
    if child.poll() is None:
        child.kill()
        child.wait()
left = [x for x in os.listdir(scr2) if x.startswith("forge-fwx-")]
check("18.8: a SIGTERM in the middle of the probe leaves no forge-fwx-* folder and ends the process as terminated -- started %s, rc %s, %s" % (started, rc, left),
      started and left == [] and rc == 128 + signal.SIGTERM, (started, rc, left))

# 18.9 a caller's GIT_DIR / GIT_WORK_TREE aims neither the scratch nor forge's questions at another repository
# Seen failing on 85c0c8b: with a decoy repository's GIT_DIR and GIT_WORK_TREE, exit 1 and a `!` whose rule is the decoy's `*.md`.
decoy = project("*.md\n", commit=True)
for how, kw in (("its own .gitignore", {}), ("info/exclude", dict(writes_tracked_files=False))):
    p, w = fresh("node_modules/\n", commit=True, **kw)
    os.environ["GIT_DIR"], os.environ["GIT_WORK_TREE"] = os.path.join(decoy, ".git"), decoy
    try:
        code, out = w.run()
    finally:
        del os.environ["GIT_DIR"], os.environ["GIT_WORK_TREE"]
    check("18.9: (%s) GIT_DIR and GIT_WORK_TREE of a decoy repository: no `!` (the decoy's rule decides nothing) -- %s" % (how, bang(out)[:1]),
          code == 0 and not bang(out), (code, out))
    # the doctor too
    os.environ["GIT_DIR"], os.environ["GIT_WORK_TREE"] = os.path.join(decoy, ".git"), decoy
    try:
        r = row()
    finally:
        del os.environ["GIT_DIR"], os.environ["GIT_WORK_TREE"]
    check("18.9: (%s) and the doctor row -- %s %s" % (how, r.level, r.detail[:90]), r.level == "PASS", r)

# 18.10 an ignore file that is not UTF-8 above the project is copied as it is
# Seen failing on 85c0c8b: "! framework -> .../toyfw.json NOT written: <root>/.gitignore unreadable ('utf-8' codec can't decode byte 0xf3".
q = mono("", "app")
with open(gi(q), "wb") as fh:
    fh.write(b"# caf\xf3\nnode_modules/\n")
pq = os.path.join(q, "app")
wq = only("latin", pq, writes_tracked_files=False)
code, out = wq.run()
check("18.10: a latin-1 comment in the repository's .gitignore: exit 0, the block written, the file untouched -- %s" % bang(out)[:1],
      code == 0 and not bang(out) and "FORGE-FWX" in (text(os.path.join(q, ".git", "info", "exclude")) or "")
      and raw(gi(q)) == b"# caf\xf3\nnode_modules/\n", (code, out))
with open(gi(q), "wb") as fh:
    fh.write(b"# caf\xf3\n*.md\n")
code, out = wq.run()
check("18.10: and its rules count: a `*.md` after it is the rule the `!` line names -- %s" % bang(out)[:1],
      code == 1 and any(".gitignore:2:*.md" in l for l in bang(out)), (code, out))

# 18.11 mutations of the first round's fixes that no check saw (second review), each now caught
# a block tagged with a path with a space: the tag is %-quoted
q = mono("node_modules/\n", "my app")
wq = only("spaced", os.path.join(q, "my app"), writes_tracked_files=False)
code, out = wq.run()
check("18.11: a project in `my app`: the marker carries `my%%20app/`, exit 0 -- %s" % bang(out)[:1],
      code == 0 and "# END FORGE-FWX my%20app/" in (text(os.path.join(q, ".git", "info", "exclude")) or ""), (code, out))
# a block whose tag starts like another's (a project and one inside it)
q = mono("node_modules/\n", "app", "app/sub")
wn = World()
wn.put(profile(os.path.join(q, "app"), name="outer", writes_tracked_files=False))
wn.put(profile(os.path.join(q, "app", "sub"), name="inner", writes_tracked_files=False))
exq = os.path.join(q, ".git", "info", "exclude")
wn.run()
before = raw(exq)
code, out = wn.run()
check("18.11: a project inside another: both blocks, a second run already current for both -- %s" % blines(out),
      code == 0 and raw(exq) == before and len([l for l in blines(out) if "already current" in l]) == 2
      and (text(exq) or "").count("# BEGIN FORGE-FWX") == 2, (code, out))
wo = only("outer", os.path.join(q, "app"), framework=False, writes_tracked_files=False)
wo.run()
check("18.11: the outer one off takes out its block and leaves the inner one's whole",
      btext(prefix="app/sub/", tag="app/sub/") in (text(exq) or "") and "FORGE-FWX app/ " not in (text(exq) or ""), text(exq))
# the chain is every directory down to the project, not the root and the project only
q = mono("node_modules/\n", "docs/app")
put(os.path.join(q, "docs", ".gitignore"), "app/.fwx/\n")
wq = only("deep", os.path.join(q, "docs", "app"), writes_tracked_files=False)
code, out = wq.run()
check("18.11: a rule of a directory between the root and the project counts -- %s" % bang(out)[:1],
      code == 1 and any("docs/.gitignore:1:app/.fwx/" in l for l in bang(out)), (code, out))
# the probe that follows the move of the block to the end gives no answer: nothing is moved, nothing is said to be done
p, w = fresh(STAR)
w.run()
put(gi(p), text(gi(p)) + "*.md\n")
before = raw(gi(p))
with git_stub(lambda a, k: subprocess.TimeoutExpired(a, 1) if "check-ignore" in a and k > 4 else None):
    code, out = w.run()
check("18.11: the probe that follows the move gives no answer: exit 1, NOT RUN, NOT ARMED, the file as it was -- %s" % bang(out)[:1],
      code == 1 and any("NOT RUN, NOT ARMED" in l for l in bang(out)) and raw(gi(p)) == before, (code, out))
# a .gitignore that is a link, and git does not answer
p, w = fresh(None)
put(os.path.join(p, "real-ignore"), "node_modules/\n")
os.symlink("real-ignore", gi(p))
with git_stub(silent):
    code, out = w.run()
check("18.11: a .gitignore that is a link and git that does not answer: exit 1, NOT RUN, NOT ARMED -- %s" % bang(out)[:1],
      code == 1 and any("NOT RUN, NOT ARMED" in l for l in bang(out)), (code, out))
code, out = w.run()
check("18.11: the same link with git answering: the generated file is not ignored, so a `!` line, exit 1, nothing written through the link",
      code == 1 and os.path.islink(gi(p)) and text(os.path.join(p, "real-ignore")) == "node_modules/\n" and bool(bang(out)), (code, out))
# the doctor's row, when git does not answer
p, w = fresh(STAR)
w.run()
with git_stub(silent):
    r = row()
check("18.11: the doctor row, git not answering: not a PASS, and it says git did not answer -- %s %s" % (r.level, r.detail),
      r.level == "FAIL" and "git did not answer" in r.detail, r)
# a tsv that only a later line re-ignores: the probe must see it and move the block
p, w = fresh(STAR)
w.run()
put(gi(p), text(gi(p)) + "*.tsv\n")
code, out = w.run()
make_docs(p)
check("18.11: a later `*.tsv` is seen: the block is moved, the tsv shows -- %s" % blines(out),
      code == 0 and any("moved" in l and ".fwx/decisions.tsv" in l for l in blines(out)) and seen(p)[1], (code, out, status(p)))
# an info/exclude that is a link is never written through
p, w = fresh("node_modules/\n", commit=True, writes_tracked_files=False)
exq = os.path.join(p, ".git", "info", "exclude")
os.remove(exq)
put(os.path.join(TOY, "exclude-target"), "# the target\n")
os.symlink(os.path.join(TOY, "exclude-target"), exq)
code, out = w.run()
check("18.11: an info/exclude that is a link: a `!` line, exit 1, the target is untouched -- %s" % bang(out)[:1],
      code == 1 and bool(bang(out)) and text(os.path.join(TOY, "exclude-target")) == "# the target\n", (code, out))
# a block that was there already and is not claimed stays unclaimed
p, w = fresh(STAR + btext())
code, out = w.run()
check("18.11: a block the project had already (unclaimed) is `already current` and stays unclaimed (uninstall leaves it) -- %s" % blines(out),
      code == 0 and any("already current" in l for l in blines(out)) and not owned.previous(gi(p), "framework")[0], (code, out, owned.previous(gi(p), "framework")[0]))
# the single claimed line outside the block, equal to a line inside it: only the outside one is folded
p, w = fresh("node_modules/\n", commit=True, writes_tracked_files=False)
exq = os.path.join(p, ".git", "info", "exclude")
ex_template = text(exq)
w.run()
put(exq, "/.claude/toyfw.json\n" + text(exq))
owned.record(exq, owned.previous(exq, "framework")[0] + [owned.claim("item", ["line", "/.claude/toyfw.json"], "/.claude/toyfw.json", "toyapp")], True, part="framework")
code, out = w.run()
check("18.11: a claimed single line equal to one inside an intact block is folded, and the block is not called different -- %s" % blines(out),
      code == 0 and any("folded" in l for l in blines(out)) and not any("differed" in l for l in blines(out))
      and text(exq) == ex_template + btext(), (code, out, text(exq)))

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
