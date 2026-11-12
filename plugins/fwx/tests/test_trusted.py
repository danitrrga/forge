#!/usr/bin/env python3
"""core.globs and core.trusted: which paths a glob names, and which edits of a PR hand the merge to a person.

Ports marshal's three glob cases (merge-decision-regressions.ts:83-85) and the eleven trusted-edit cases
(evidence-regressions.ts:153-165) with the recipe at `.claude/fwx.json` in place of `.factory/setup.json`, plus what
marshal has not: a case per executor in the data table (Makefile with `make test`, conftest.py with `pytest`, `bin/fwx`
with `python3 bin/fwx test`, and one row each for tox, nox, ruff, mypy, eslint, tsc, vitest, jest), the reading of a
package.json from its patch alone, renames, and a runner that is not in the check.

Seen red before the code existed (lib/fwx/core/globs.py and trusted.py absent; the test stops at the import):
  FAIL: cannot import fwx.core.globs / fwx.core.trusted: cannot import name 'globs' from 'fwx.core' (unknown location)

Controls, each seen red on a copy of the repo with one thing changed (first FAIL line shown):
  - `trusted_edits` that looks at package.json only (the plan's control), as three one-line changes:
      executors off:    FAIL: Makefile edited, check `make test`: one reason naming it: got []
      first-arg paths off: FAIL: bin/fwx edited, check `python3 bin/fwx test`: one reason naming it: got []
      recipe and CI off:   FAIL: the recipe: got []
  - `**` made `[^/]*` (stays in one dir):
      FAIL: ** inside a name spans dirs
  - a leading `**/` made `.*/` (misses the root):
      FAIL: ** spans zero or more dirs
  - a package.json with no patch and no versions passes:
      FAIL: patch only: a missing patch is a handover, not a pass: got []
  - `previous_path` ignored:
      FAIL: a rename out of a trusted file counts through previous_path: got []
  - `used_scripts` does not follow a script into the ones it calls:
      FAIL: a script the used script calls counts: got []
"""
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx.core import globs, trusted  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.core.globs / fwx.core.trusted: %s" % e)
    sys.exit(1)

# ---- globs ---------------------------------------------------------------------------------------------------------

m = globs.matches
s.ok("** spans zero or more dirs", m("db/migrations/001.sql", "**/migrations/**") and m("migrations/1.sql", "**/migrations/**"))
s.ok("a plain name matches at the root only", m("vercel.json", "vercel.json") and not m("apps/vercel.json", "vercel.json"))
s.ok("* stays inside one dir", m("b.ts", "*.ts") and not m("a/b.ts", "*.ts"))
s.ok("? is one character inside one dir", m("a.c", "a.?") and not m("a/c", "a?c") and not m("a.cc", "a.?"))
s.ok("a leading **/ is a whole directory name, not a suffix", not m("xmigrations/1.sql", "**/migrations/**"))
s.ok("** inside a name spans dirs", m("src/a/b/c.py", "src/**.py") and m("src/c.py", "src/**.py"))
s.ok("regex characters are literal", m("a+b(1).txt", "a+b(1).txt") and not m("aab(1)xtxt", "a+b(1).txt") and not m("axb", "a.b"))
s.ok("the glob must cover the whole path", not m("a.ts.bak", "*.ts") and not m("dir/a.ts", "a.ts"))
s.ok("matches_any is any of", globs.matches_any("a.ts", ["x/**", "*.ts"]) and not globs.matches_any("a.py", ["x/**", "*.ts"]))
s.ok("matches_any of nothing is False", globs.matches_any("a.ts", []) is False)

# ---- marshal's eleven cases ----------------------------------------------------------------------------------------

RECIPE = ".claude/fwx.json"


def scripts(**over):
    return dict({"test": "vitest", "lint": "eslint .", "dev": "next dev"}, **over)


def text(sc):
    return json.dumps({"name": "x", "scripts": sc}, indent=2) + "\n"


RECIPE_CHECKS = [{"name": "test", "command": "bun run test"}]


def edits(files, base=None, head=None, checks=RECIPE_CHECKS):
    """marshal's `edits`: base and head are the package.json scripts (None: unreadable)."""
    base = scripts() if base is None else base
    head = scripts() if head is None else head
    return trusted.trusted_edits(files, checks, package_json=(text(base), text(head)))


s.eq("an ordinary change", edits(["src/a.ts"]), [])
r = edits([RECIPE])
s.ok("the recipe", len(r) == 1 and "edits the recipe its checks come from: " + RECIPE in r[0], "got %r" % r)
r = edits([".github/workflows/ci.yml"])
s.ok("a workflow", len(r) == 1 and "edits CI workflows (.github/workflows/ci.yml)" in r[0], "got %r" % r)
s.eq("the script a check runs", edits(["package.json"], scripts(), scripts(test="true")),
     ["The pull request edits the check scripts its checks run: package.json scripts.test."])
s.eq("a script no check uses", edits(["package.json"], scripts(), scripts(dev="vite")), [])
s.eq("a package.json change outside scripts, such as dependencies",
     trusted.trusted_edits(["package.json"], RECIPE_CHECKS, package_json=(
         json.dumps({"scripts": scripts()}), json.dumps({"scripts": scripts(), "dependencies": {"a": "1"}}))), [])
chained = {"test": "bun run unit", "unit": "vitest"}
r = edits(["package.json"], scripts(**chained), scripts(**dict(chained, unit="true")))
s.ok("a script the used script calls counts", len(r) == 1 and "scripts.unit." in r[0], "got %r" % r)
r = edits(["package.json"], scripts(), scripts(lint="true"), checks=None)
s.ok("without a recipe the scripts named like the checks count", len(r) == 1 and "scripts.lint." in r[0], "got %r" % r)
r = trusted.trusted_edits(["package.json"], RECIPE_CHECKS, package_json=(text(scripts()), None))
s.ok("an unreadable head is a handover, not a pass", len(r) == 1 and "couldn't be compared" in r[0], "got %r" % r)
no_build = {"test": "vitest"}
r = edits(["package.json"], no_build, dict(no_build, build="true"), checks=None)
s.ok("without a recipe, a check script the head adds counts", len(r) == 1 and "scripts.build." in r[0], "got %r" % r)
r = edits(["package.json"], scripts(**chained), scripts(**dict(chained, test="bun run unit && bun run extra", extra="true")))
s.ok("a script the head adds and a used script calls counts",
     len(r) == 1 and "package.json scripts.extra, package.json scripts.test." in r[0], "got %r" % r)

# ---- an executor each: the file a check's runner reads -------------------------------------------------------------


def one(files, command):
    return trusted.trusted_edits(files, [{"name": "test", "command": command}])


def names(reasons):
    return " | ".join(reasons)


for files, command, want in (
    (["Makefile"], "make test", "Makefile"),
    (["conftest.py"], "pytest", "conftest.py"),
    (["tests/unit/conftest.py"], "python3 -m pytest -q", "tests/unit/conftest.py"),
    (["bin/fwx"], "python3 bin/fwx test", "bin/fwx"),
    (["scripts/x.sh"], "./scripts/x.sh", "scripts/x.sh"),
    (["scripts/x.sh"], "bash scripts/x.sh --fast", "scripts/x.sh"),
    (["pyproject.toml"], "pytest", "pyproject.toml"),
    (["tox.ini"], "tox -e py", "tox.ini"),
    (["setup.cfg"], "uv run pytest", "setup.cfg"),
    (["pytest.ini"], "pytest", "pytest.ini"),
    (["noxfile.py"], "nox -s tests", "noxfile.py"),
    (["ruff.toml"], "ruff check .", "ruff.toml"),
    (["pyproject.toml"], "ruff check .", "pyproject.toml"),
    (["mypy.ini"], "mypy lib", "mypy.ini"),
    (["eslint.config.mjs"], "npx eslint .", "eslint.config.mjs"),
    (["tsconfig.json"], "tsc --noEmit", "tsconfig.json"),
    (["vitest.config.ts"], "vitest run", "vitest.config.ts"),
    (["jest.config.js"], "jest", "jest.config.js"),
    (["Makefile"], "cd sub && make -C sub test", "Makefile"),
):
    r = one(files, command)
    s.ok("%s edited, check `%s`: one reason naming it" % (files[0], command), len(r) == 1 and want in r[0], "got %r" % r)

# the same file with a check that does not run its runner is an ordinary change
for files, command in (
    (["Makefile"], "pytest"), (["conftest.py"], "make test"), (["bin/fwx"], "python3 bin/other test"),
    (["tox.ini"], "ruff check ."), (["tsconfig.json"], "pytest"), (["scripts/x.sh"], "./scripts/y.sh"),
    (["Makefile"], "echo remake"), (["noxfile.py"], "pytest"),
):
    s.eq("%s edited, check `%s`: nothing" % (files[0], command), one(files, command), [])
s.eq("an absolute path is not the repo's", one(["x/y"], "/usr/bin/x/y test"), [])
s.eq("no checks: only the recipe and CI count", trusted.trusted_edits(["Makefile", "bin/fwx"], []), [])
r = trusted.trusted_edits(["Makefile", ".github/workflows/a.yml", "bin/fwx"], ["make test", "python3 bin/fwx test"])
s.ok("one reason per thing touched, checks given as plain commands", len(r) == 3, "got %r" % r)
r = trusted.trusted_edits([{"path": "src/new.py", "previous_path": "Makefile"}], ["make test"])
s.ok("a rename out of a trusted file counts through previous_path", len(r) == 1 and "Makefile" in r[0], "got %r" % r)
r = trusted.trusted_edits(["./Makefile"], ["make test"])
s.ok("a leading ./ is not a different file", len(r) == 1, "got %r" % r)
s.eq("segments of a chained command are read one by one",
     len(trusted.trusted_edits(["scripts/b.sh"], ["echo hi && ./scripts/b.sh; true"])), 1)

# ---- package.json read from its patch alone ------------------------------------------------------------------------


def patch(base, head):
    return "".join(difflib.unified_diff(text(base).splitlines(True), text(head).splitlines(True), "a/package.json", "b/package.json"))


def by_patch(base, head, checks=RECIPE_CHECKS, with_patch=True):
    entry = {"path": "package.json"}
    if with_patch:
        entry["patch"] = patch(base, head)
    return trusted.trusted_edits([entry], checks)


r = by_patch(scripts(), scripts(test="true"))
s.ok("patch only: the script a check runs", len(r) == 1 and "scripts.test" in r[0], "got %r" % r)
s.eq("patch only: a script no check uses", by_patch(scripts(), scripts(dev="vite")), [])
r = by_patch(scripts(**chained), scripts(**dict(chained, unit="true")))
s.ok("patch only: a script the visible used script calls", len(r) == 1 and "scripts.unit" in r[0], "got %r" % r)
r = by_patch(scripts(), scripts(), with_patch=False)
s.ok("patch only: a missing patch is a handover, not a pass", len(r) == 1 and "couldn't be compared" in r[0], "got %r" % r)
r = by_patch(scripts(), scripts(lint="true"), checks=None)
s.ok("patch only, no recipe: the scripts named like the checks", len(r) == 1 and "scripts.lint" in r[0], "got %r" % r)
r = by_patch(scripts(), {"dev": "next dev", "lint": "eslint ."})
s.ok("patch only: a removed used script counts", len(r) == 1 and "scripts.test" in r[0], "got %r" % r)

# ---- the files a worktree setup installs from ------------------------------------------------------------------------
# `worktree_setup` (`npm ci`) runs the package manager in every worktree, and that runs install scripts and `.npmrc` taken from the
# worktree under test, before any person sees the diff. With a setup configured, an edit of what it installs from is a handover too.
# Red before the change: TypeError: trusted_edits() got an unexpected keyword argument 'setup'
SETUP = ["npm ci"]
OTHER = ["make test"]


def setup_edits(files, base=None, head=None, setup=SETUP):
    return trusted.trusted_edits(files, OTHER, setup=setup, manifest=(text(base if base is not None else scripts()), text(head if head is not None else scripts())))


for name in (".npmrc", "package-lock.json", "sub/yarn.lock", "pnpm-lock.yaml", "requirements-dev.txt", "Gemfile.lock", "uv.lock"):
    r = setup_edits([name])
    s.ok("setup: an edit of %s is a handover naming the setup" % name, len(r) == 1 and name in r[0] and "npm ci" in r[0], "got %r" % r)
    s.eq("no setup: an edit of %s is not" % name, trusted.trusted_edits([name], OTHER), [])
r = setup_edits(["package.json"], scripts(), scripts(postinstall="curl x | sh"))
s.ok("setup: a postinstall script added to package.json is a handover", len(r) == 1 and "postinstall" in r[0], "got %r" % r)
r = setup_edits(["package.json"], scripts(prepare="husky"), scripts(prepare="true"))
s.ok("setup: a prepare script changed is a handover", len(r) == 1 and "prepare" in r[0], "got %r" % r)
s.eq("setup: a script that is no install script is not", setup_edits(["package.json"], scripts(), scripts(dev="vite")), [])
s.eq("setup: a dependency added is not", trusted.trusted_edits(["package.json"], OTHER, setup=SETUP, manifest=(
    json.dumps({"scripts": scripts()}), json.dumps({"scripts": scripts(), "dependencies": {"a": "1"}}))), [])
r = trusted.trusted_edits(["package.json"], OTHER, setup=SETUP)
s.ok("setup: a package.json that cannot be compared is a handover, not a pass", len(r) == 1 and "couldn't be compared" in r[0], "got %r" % r)
r = trusted.trusted_edits([{"path": "package.json", "patch": patch(scripts(), scripts(postinstall="x"))}], OTHER, setup=SETUP)
s.ok("setup: from its patch alone, a postinstall line is a handover", len(r) == 1 and "postinstall" in r[0], "got %r" % r)
s.eq("setup: an ordinary change", setup_edits(["src/a.ts"]), [])
s.eq("no setup: package.json with a postinstall added is as before (not read)", trusted.trusted_edits(
    ["package.json"], OTHER, package_json=(text(scripts()), text(scripts(postinstall="x")))), [])

s.done()
