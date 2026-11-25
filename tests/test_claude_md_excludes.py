#!/usr/bin/env python3
"""The project field `claude_md_excludes` (a list of paths or globs of CLAUDE.md files a nested project must not load,
the one above its folder) is written as `claudeMdExcludes` into <project>/.claude/settings.local.json by
skills.write_settings_local, is typed by lib.PROJECT_FIELDS, and is a claim forge owns (forge/owned.py): the list is
written whole, a project that stops declaring it gets the key taken out while it is still what forge wrote, and one
edited by hand since stays and is named. A project without the field gets the same file as before, byte for byte.

Runs in-process against a toy HOME and toy projects; lib.may_write() is stubbed to allow, because this checkout may be
a linked worktree, which never writes.

Seen failing on the code before the field (d6d71b9), 12 of 20 checks red, the first ones:
  FAIL lib.PROJECT_FIELDS has a row for claude_md_excludes -- None
  FAIL project_error: a string is not a list -- None
  FAIL declared: the key is written whole -- {}
  FAIL declared: the key is claimed -- []
and likewise the dry-run line, the empty-path message, the changed list, the line naming the hand edit.
Relative and ~ entries (Claude Code matches absolute paths, so they match nothing): seen failing before the check, 3 of 26 red:
  FAIL project_error: 'x/CLAUDE.md' is refused, naming it and the two valid forms -- None
  (likewise '~/x/CLAUDE.md' and './CLAUDE.md').
Single-star entries and a bare ** (a * does not cross /, so '*/CLAUDE.md', '*.md', '*upper/CLAUDE.md' match nothing against an
absolute path, and ** would hide the project's own file) were accepted by the `/ or *` check: 4 of 29 red:
  FAIL project_error: '*/CLAUDE.md' is refused, naming it and the two valid forms -- None  (likewise '*.md', '*upper/CLAUDE.md', '**')
The '  ! ' prefix check on the hand-edit line, seen red with the print's prefix taken out of forge/skills.py:
  FAIL edited by hand: named on a '  ! ' line -- <path>: claudeMdExcludes was edited by hand, left in place
The accepting checks, seen red under a mutation of the validator in forge/lib.py (each put back, 1 of 29 red each):
  entries starting with **/ rejected (startswith(("/",))):
    FAIL project_error: '**/monorepo/CLAUDE.md' is fine -- claude_md_excludes entry '**/monorepo/CLAUDE.md' is not absolute: it must start with / or **/
  an empty list rejected (a `== []` guard returning "claude_md_excludes is empty"):
    FAIL project_error: an empty list is fine (declared, nothing excluded) -- claude_md_excludes is empty
Controls on the finished code, each mutation put back from a copy of forge/skills.py, each seen red: the key not written
(crash, KeyError: 'claudeMdExcludes', exit 1); no claim recorded (4 FAIL); the prune branch dropped (3); the prune
ignoring the digest, so a hand edit is removed (2)."""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("claude-md-excludes-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
from forge import lib, owned, skills  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")

APPLY = lib.Ctx(True, None, False)
DRY = lib.Ctx(False, None, False)
UP = "/toy/upper/CLAUDE.md"
UP2 = "/toy/upper/CLAUDE.local.md"
failures, n_checks, n_proj = [], [0], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", str(detail)[:600])


def project():
    n_proj[0] += 1
    p = os.path.join(TOY, "proj%d" % n_proj[0])
    os.makedirs(os.path.join(p, ".claude"))
    return p


def slp(p):
    return os.path.join(p, ".claude", "settings.local.json")


def doc(p):
    if not os.path.exists(slp(p)):
        return {}  # a missing file is a red check, not a crash
    with open(slp(p), encoding="utf-8") as fh:
        return json.load(fh)


def run(p, ctx=APPLY, **keys):
    """(the line, what the call printed) for a toy project of `keys`."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        line = skills.write_settings_local(ctx, dict({"project": "toy", "project_path": p}, **keys), {}, [], ())
    return line, out.getvalue()


def claims(p):
    return {(c["kind"], tuple(c["at"])): c for c in owned.previous(slp(p))[0]}


KEY = ("key", ("claudeMdExcludes",))
OTHER = {"permissions": {"allow": ["Bash(a:*)"]}}

# 1. The type row: project_error is the one place that knows it.
check("lib.PROJECT_FIELDS has a row for claude_md_excludes", lib.PROJECT_FIELDS.get("claude_md_excludes") == (list, str),
      lib.PROJECT_FIELDS.get("claude_md_excludes"))
check("project_error: a list of paths is fine", lib.project_error({"claude_md_excludes": [UP]}) is None)
check("project_error: a string is not a list", lib.project_error({"claude_md_excludes": UP}) == "claude_md_excludes is not a list of strings",
      lib.project_error({"claude_md_excludes": UP}))
check("project_error: a list with a number is not a list of strings", lib.project_error({"claude_md_excludes": [1]}) is not None)
check("project_error: an empty path names nothing", lib.project_error({"claude_md_excludes": [" "]}) == "claude_md_excludes has an empty path",
      lib.project_error({"claude_md_excludes": [" "]}))
for bad in ("x/CLAUDE.md", "~/x/CLAUDE.md", "./CLAUDE.md", "*/CLAUDE.md", "*.md", "*upper/CLAUDE.md", "**"):  # none can match an absolute path (a single * does not cross /); a bare ** would hide the project's own file
    why = lib.project_error({"claude_md_excludes": [UP, bad]})
    check("project_error: %r is refused, naming it and the two valid forms" % bad,
          why == "claude_md_excludes entry %r is not absolute: it must start with / or **/" % bad, why)
for good in ("/x/CLAUDE.md", "**/monorepo/CLAUDE.md"):
    check("project_error: %r is fine" % good, lib.project_error({"claude_md_excludes": [good]}) is None,
          lib.project_error({"claude_md_excludes": [good]}))
check("project_error: an empty list is fine (declared, nothing excluded)", lib.project_error({"claude_md_excludes": []}) is None,
      lib.project_error({"claude_md_excludes": []}))

# 2. Declared: written whole, claimed, named in the line; a dry-run writes and records nothing.
p = project()
line, _ = run(p, DRY, claude_md_excludes=[UP, UP2])
check("dry-run: says it would write, with the count", line and "would write" in line and "CLAUDE.md excludes 2" in line, line)
check("dry-run: no file", not os.path.exists(slp(p)), slp(p))
line, _ = run(p, claude_md_excludes=[UP, UP2])
check("declared: the key is written whole", doc(p).get("claudeMdExcludes") == [UP, UP2], doc(p))
check("declared: the line names it", line and "CLAUDE.md excludes 2" in line, line)
check("declared: the key is claimed", KEY in claims(p) and claims(p)[KEY]["sum"] == owned.digest([UP, UP2]) and claims(p)[KEY]["owner"] == "toy",
      sorted(claims(p)))
check("declared: a second run is already current", "already current" in (run(p, claude_md_excludes=[UP, UP2])[0] or ""))
run(p, claude_md_excludes=[UP])
check("declared: a changed list replaces the old one whole", doc(p).get("claudeMdExcludes") == [UP], doc(p))
check("declared: the changed list is the claim now", KEY in claims(p) and claims(p)[KEY]["sum"] == owned.digest([UP]), sorted(claims(p)))

# 3. Stops declaring it: taken out while it is still what forge wrote, claim gone with it.
run(p, **OTHER)
check("no longer declared: the key goes", "claudeMdExcludes" not in doc(p), doc(p))
check("no longer declared: the claim goes", KEY not in claims(p), sorted(claims(p)))

# 4. Edited by hand since: stays, named on one '  ! ' line.
p = project()
run(p, claude_md_excludes=[UP])
d = doc(p)
d["claudeMdExcludes"] = [UP, "/by/hand/CLAUDE.md"]
lib.write_json(slp(p), d)
line, printed = run(p, **OTHER)
check("edited by hand: the list stays", doc(p).get("claudeMdExcludes") == [UP, "/by/hand/CLAUDE.md"], doc(p))
check("edited by hand: named on a '  ! ' line", any(l.startswith("  ! ") and "claudeMdExcludes was edited by hand" in l for l in printed.splitlines()), printed)

# 5. A project without the field: no key, and a key set by hand is never touched or claimed.
p = project()
lib.write_json(slp(p), {"claudeMdExcludes": ["/by/hand/CLAUDE.md"], "permissions": {"allow": ["Bash(b:*)"]}})
run(p, **OTHER)
check("never declared: the hand-set key is untouched and unclaimed",
      doc(p).get("claudeMdExcludes") == ["/by/hand/CLAUDE.md"] and KEY not in claims(p), (doc(p), sorted(claims(p))))
p = project()
run(p, **OTHER)
check("never declared: no key in the file", "claudeMdExcludes" not in doc(p), doc(p))

sandbox.cleanup(bool(failures))
print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
sys.exit(1 if failures else 0)
