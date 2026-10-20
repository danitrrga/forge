#!/usr/bin/env python3
"""scripts/sync/sync_system_doc.py records what it created in the ownership record (step 10, increment I3,
task T5; forge/owned.py), so a coming `forge uninstall` can remove it:

  C12 the `.claude/AGENT-SYSTEM.md` line it adds to a project's .gitignore: an item at ["line", <line>] of
      that file, part "system-doc", owner "core", claimed only when forge added the line, and kept on later
      runs while it is still there; a line that was already there is never claimed.
  C13 the AGENTS.md -> CLAUDE.md link: kind `file`, at [], the value "symlink:CLAUDE.md", owner "core", part
      "system-doc", claimed only when this run created or repointed the link. A link that was already right
      may be the user's own, and is not claimed (one claimed on an earlier run stays claimed while it is
      still that link); a file the script now leaves alone loses its claim.
  The copied .claude/AGENT-SYSTEM.md and the pointer block of CLAUDE.md need no claim: content and markers
  say who wrote them.

The script is imported in-process over a toy HOME, toy projects (git repositories) and a toy profiles
directory, with the module's CTX set per case; lib.may_write() is stubbed to allow, because this checkout may
be a linked worktree, which never writes. A dry-run records nothing, and a repo-owned project (forge writes
nothing git tracks there) and a directory under no git record nothing either.

Seen failing on the parent commit (the script claims nothing): 12 of 24 checks red, the other 12 are controls,
dry-runs and the cases that must claim nothing, which pass there. The first:
  FAIL C12: the added ignore line is claimed on .gitignore -- []
  FAIL C13: the AGENTS.md link forge created is claimed -- []
Negative controls on the finished code, each mutation of scripts/sync/sync_system_doc.py put back from a copy,
checks red: the ignore line never claimed (4) or claimed under another part (4); the link never claimed (6), or
not when created (5), or not when repointed (1); an already-right link claimed (2) or losing its claim (2); a file
forge leaves alone keeping its claim (1); the link recorded in a dry-run (1); owner codex (5); the value
symlink:AGENTS.md (1); no part (7)."""
import contextlib
import io
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("owned-system-doc-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = [sys.argv[0]]  # the script reads its own flags at import
sys.path.insert(0, sandbox.FORGE)
sys.path.insert(0, os.path.join(sandbox.FORGE, "scripts", "sync"))
from forge import lib, owned  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")
import sync_system_doc as sd  # noqa: E402

DOC = os.path.join(TOY, "AGENT-SYSTEM.md")
shutil.copy(os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "AGENT-SYSTEM.md"), DOC)
sd.CANON = DOC
lib.PROFILES = os.path.join(TOY, "profiles")
os.makedirs(lib.PROFILES)
LINE = ".claude/AGENT-SYSTEM.md"
failures, n_checks, n_proj = [], [0], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", str(detail)[:500])


def project(repo=True, gitignore=None, claude_md=None, agents=None, link=None, **keys):
    """A toy project with its profile; returns (name, directory). `agents` is the text of a real AGENTS.md,
    `link` a symlink target for it."""
    n_proj[0] += 1
    name = "p%d" % n_proj[0]
    d = os.path.join(TOY, "projects", name)
    os.makedirs(d)
    if repo:
        sandbox.git(d, "init", "-q")
    for fname, text in ((".gitignore", gitignore), ("CLAUDE.md", claude_md), ("AGENTS.md", agents)):
        if text is not None:
            with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
                fh.write(text)
    if link is not None:
        os.symlink(link, os.path.join(d, "AGENTS.md"))
    with open(os.path.join(lib.PROFILES, name + ".claude.json"), "w", encoding="utf-8") as fh:
        json.dump(dict({"project_path": d}, **keys), fh)
    return name, d


def run(name, apply=True):
    sd.CTX = lib.Ctx(apply, {name}, False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = sd.main()
    return code, out.getvalue()


def raw():
    return open(owned.path(), encoding="utf-8").read() if os.path.exists(owned.path()) else ""


def mtime():
    return os.stat(owned.path()).st_mtime_ns if os.path.exists(owned.path()) else None


def drop_registry():
    if os.path.exists(owned.path()):
        os.remove(owned.path())


def claims(file, part="system-doc"):
    return owned.previous(file, part)[0]


def shape(cs):
    return [(c["kind"], c["at"], c["owner"], c["part"]) for c in cs]


LINK_CLAIM = [("file", [], "core", "system-doc")]
LINE_CLAIM = [("item", ["line", LINE], "core", "system-doc")]

# 1. a fresh project: forge adds the ignore line and creates the link, and claims both.
drop_registry()
n1, d1 = project()
gi1, ag1 = os.path.join(d1, ".gitignore"), os.path.join(d1, "AGENTS.md")
code, out = run(n1)
check("control: the run exits 0 and made the line, CLAUDE.md and the link",
      code == 0 and LINE in open(gi1, encoding="utf-8").read().split() and os.path.islink(ag1)
      and os.readlink(ag1) == "CLAUDE.md", (code, out))
check("C12: the added ignore line is claimed on .gitignore", shape(claims(gi1)) == LINE_CLAIM, claims(gi1))
check("C12: the claim is the hash of the line", claims(gi1) and claims(gi1)[0]["sum"] == owned.digest(LINE), claims(gi1))
check("C13: the AGENTS.md link forge created is claimed", shape(claims(ag1)) == LINK_CLAIM, claims(ag1))
check("C13: the claim is the hash of the value symlink:CLAUDE.md",
      claims(ag1) and claims(ag1)[0]["sum"] == owned.digest("symlink:CLAUDE.md"), claims(ag1))
before, stamp = raw(), mtime()
time.sleep(0.05)  # the file system's clock is coarse: a rewrite within a tick would keep the mtime
code, out = run(n1)
check("control: a second run changes nothing", "0 change(s)" in out, out)
check("C12: the line stays claimed on a second apply (it was not added again)", shape(claims(gi1)) == LINE_CLAIM, claims(gi1))
check("C13: the link stays claimed on a second apply (it was already right)", shape(claims(ag1)) == LINK_CLAIM, claims(ag1))
check("a second apply that changes nothing leaves the record's bytes and mtime",
      raw() != "" and raw() == before and mtime() == stamp, "rewritten")

# 2. everything already there before forge: nothing is claimed.
drop_registry()
n2, d2 = project(gitignore="%s\n" % LINE, claude_md="# mine\n", link="CLAUDE.md")
code, out = run(n2)
check("control: the pointer block was appended, so forge did run here", "append-pointer:CLAUDE.md" in out, out)
check("C12: an ignore line that was already there is not claimed", claims(os.path.join(d2, ".gitignore")) == [], raw())
check("C13: an AGENTS.md link that was already right is not claimed", claims(os.path.join(d2, "AGENTS.md")) == [], raw())
code, out = run(n2)
check("C12/C13: nor on a second apply", raw() == "", raw())

# 3. a real AGENTS.md of forge's (both markers) is replaced by the link, which is forge's now.
drop_registry()
begin, end = sd.BEGIN, sd.END
n3, d3 = project(gitignore="%s\n" % LINE, claude_md="# mine\n", agents="%s\nold copy\n%s\n" % (begin, end))
code, out = run(n3)
check("C13: a forge-marked AGENTS.md replaced by the link is claimed",
      os.path.islink(os.path.join(d3, "AGENTS.md")) and shape(claims(os.path.join(d3, "AGENTS.md"))) == LINK_CLAIM, (out, raw()))

# 4. a link to somewhere else is repointed: forge made the link that is there now.
drop_registry()
n4, d4 = project(gitignore="%s\n" % LINE, claude_md="# mine\n", link="elsewhere.md")
code, out = run(n4)
check("C13: a link repointed to CLAUDE.md is claimed",
      os.readlink(os.path.join(d4, "AGENTS.md")) == "CLAUDE.md" and shape(claims(os.path.join(d4, "AGENTS.md"))) == LINK_CLAIM,
      (out, raw()))

# 5. a claimed link the user has since replaced by a file of their own: forge leaves it, and the claim goes.
os.remove(os.path.join(d4, "AGENTS.md"))
with open(os.path.join(d4, "AGENTS.md"), "w", encoding="utf-8") as fh:
    fh.write("# my own rules\n")
code, out = run(n4)
check("control: the user's AGENTS.md is left alone", "SKIP-agents-md(non-forge content)" in out
      and open(os.path.join(d4, "AGENTS.md"), encoding="utf-8").read() == "# my own rules\n", out)
check("C13: a claimed link that is now the user's file loses its claim", claims(os.path.join(d4, "AGENTS.md")) == [], raw())

# 5b. a dry-run over the same state changes no claim: the file is left alone either way, but only an apply says so.
drop_registry()
n5, d5 = project(gitignore="%s\n" % LINE, claude_md="# mine\n")
run(n5)
os.remove(os.path.join(d5, "AGENTS.md"))
with open(os.path.join(d5, "AGENTS.md"), "w", encoding="utf-8") as fh:
    fh.write("# my own rules\n")
before = raw()
run(n5, apply=False)
check("C13: a dry-run leaves a claim whose file forge would leave alone", before != "" and raw() == before, raw())

# 6. a dry-run claims nothing, for a project that would get both.
drop_registry()
n6, d6 = project()
code, out = run(n6, apply=False)
check("control: the dry-run says it would change things and wrote nothing",
      "would apply" in out and not os.path.exists(os.path.join(d6, ".gitignore")), out)
check("C12/C13: a dry-run records nothing", not os.path.exists(owned.path()), raw())

# 7. a repo-owned project (writes_tracked_files false): forge writes nothing git tracks, so nothing is claimed. A
# directory under no git gets no .gitignore and so no line claim, but the link forge creates there is claimed.
drop_registry()
n7, d7 = project(gitignore="keep/\n", writes_tracked_files=False)
run(n7)
check("C12/C13: a repo-owned project claims nothing", raw() == "", raw())
n8, d8 = project(repo=False)
run(n8)
check("C12: a directory under no git has no .gitignore, so no line is claimed",
      not os.path.exists(os.path.join(d8, ".gitignore")) and claims(os.path.join(d8, ".gitignore")) == [], raw())
check("C13: the link forge created there is claimed", shape(claims(os.path.join(d8, "AGENTS.md"))) == LINK_CLAIM, raw())

# 8. the claimed line goes out of the file (the user rewrote .gitignore): the script puts it back, and the line
# it adds again is claimed again.
drop_registry()
n9, d9 = project()
gi9 = os.path.join(d9, ".gitignore")
run(n9)
with open(gi9, "w", encoding="utf-8") as fh:
    fh.write("other/\n")
run(n9)
check("C12: a line the user removed and forge put back is claimed again",
      LINE in open(gi9, encoding="utf-8").read().split() and shape(claims(gi9)) == LINE_CLAIM, (open(gi9).read(), claims(gi9)))

print("%d checks, %d failed" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
