#!/usr/bin/env python3
"""core.evidence: the effective checks recipe, and what the evidence proves about the head commit.

Ports marshal's pure cases of evidence-regressions.ts:75-152 (what to run, and `headEvidence`) onto the facts shape
`{sha, clean, commands: [{cmd, rc}]}`, with the project's recipe (`project.checks`) in place of `.factory/setup.json`.
Not ported: the output-tail redaction (lines 105-123), which belongs to `verify` (2.4 U6), and `requiredChecks`, which
reads marshal's database. Added: the recipe that wins over package.json, one package manager per lockfile, a recipe of
plain commands, the substituted command that must not verify, and the failure of a malformed evidence row.

Seen red before the code existed (lib/fwx/core/evidence.py absent; the test stops at the import):
  FAIL: cannot import fwx.core.evidence: cannot import name 'evidence' from 'fwx.core' (<worktree>/lib/fwx/core/__init__.py)

Controls, each seen red on a copy of the repo with one thing changed (first FAIL line shown):
  - `evidence_state` that does not compare the command with the recipe (the plan's control: an agent's evidence with other
    commands would come out `verified`):
      FAIL: the recipe's commands are required: got {'state': 'verified', ...}, want {'state': 'incomplete', ...}
      FAIL: a command swapped for `true` is not verified: got {'state': 'verified', ...}, want {'state': 'untrusted', ...}
  - `evidence_state` that ignores `clean`:
      FAIL: a dirty tree: got {'state': 'verified', ...}, want {'state': 'dirty', ...}
  - `evidence_state` that compares no sha (evidence of another commit proves this one):
      FAIL: evidence of another commit is stale, naming that commit: got {'state': 'verified', ...}
  - `plan_checks` that ignores the recipe:
      FAIL: the recipe's checks, in the recipe's order: got [], want ['pytest -q', 'ruff check .']
  - `plan_checks` whose lockfile table puts npm first:
      FAIL: two lockfiles: bun first: got ['npm run test']
  - `evidence_state` that counts a failing extra command as noise:
      FAIL: a failing command outside the recipe still fails the evidence: got {'state': 'verified', ...}, want {'state': 'failed', ...}
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx.core import evidence  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.core.evidence: %s" % e)
    sys.exit(1)

# ---- plan_checks: what to run --------------------------------------------------------------------------------------


def repo(files):
    d = helpers.mkdtemp("fwx-ev-")
    for rel, text in files.items():
        helpers.write(d, rel, text)
    return d


def pkg(**scripts):
    return json.dumps({"scripts": scripts})


plan = evidence.plan_checks
only_dev = pkg(dev="next dev")
two = pkg(lint="eslint", test="vitest", dev="next dev")

s.eq("the recipe's checks, in the recipe's order",
     plan(["pytest -q", "ruff check ."], repo({})), ["pytest -q", "ruff check ."])
s.eq("the recipe wins over package.json",
     plan(["pytest -q"], repo({"package.json": two, "bun.lock": ""})), ["pytest -q"])
s.eq("plain commands count as checks, so does a dict with a command",
     plan(["python3 bin/fwx test", {"command": "make lint"}], repo({})), ["python3 bin/fwx test", "make lint"])
s.eq("without a recipe, package.json scripts in check order, by the lockfile's manager",
     plan([], repo({"package.json": two, "bun.lock": ""})), ["bun run test", "bun run lint"])
s.eq("no recipe at all (None) is no recipe", plan(None, repo({"package.json": two, "bun.lock": ""})),
     ["bun run test", "bun run lint"])
s.eq("all four scripts, test lint typecheck build",
     plan([], repo({"package.json": pkg(build="b", typecheck="t", lint="l", test="x")})),
     ["npm run test", "npm run lint", "npm run typecheck", "npm run build"])
for lock, runner in (("bun.lock", "bun run"), ("bun.lockb", "bun run"), ("pnpm-lock.yaml", "pnpm run"),
                     ("yarn.lock", "yarn run"), ("package-lock.json", "npm run")):
    s.eq("lockfile %s runs %s" % (lock, runner), plan([], repo({"package.json": two, lock: ""})),
         ["%s test" % runner, "%s lint" % runner])
s.eq("npm without a lockfile", plan([], repo({"package.json": pkg(test="jest")})), ["npm run test"])
s.eq("two lockfiles: bun first", plan([], repo({"package.json": pkg(test="jest"), "yarn.lock": "", "bun.lock": "",
                                                "package-lock.json": ""})), ["bun run test"])
s.eq("a broken package.json defines nothing", plan([], repo({"package.json": "{not json"})), [])
s.eq("no recipe, no package.json: no checks", plan([], repo({})), [])
s.eq("package.json with no script named like a check", plan([], repo({"package.json": only_dev})), [])
s.eq("a script that is not a string is no check", plan([], repo({"package.json": json.dumps({"scripts": {"test": 1}})})), [])
s.eq("blank commands are no recipe", plan(["", "  "], repo({"package.json": pkg(test="x")})), ["npm run test"])
try:
    plan([3], repo({}))
    s.ok("a check that is not a command is an error", False, "no error")
except ValueError:
    s.ok("a check that is not a command is an error", True)

# ---- evidence_state: what the evidence proves about the head -------------------------------------------------------

A, B, C = "a" * 40, "b" * 40, "c" * 40
state = evidence.evidence_state


def ev(sha=A, clean=True, *cmds):
    return {"sha": sha, "clean": clean, "commands": [{"cmd": c, "rc": rc} for c, rc in (cmds or (("test", 0), ("lint", 0)))]}


def rec(*names):
    return list(names)


s.eq("verified without a recipe: what ran passed", state(ev(), A, None),
     {"state": "verified", "sha": A, "passed": 2, "total": 2})
s.eq("missing: no evidence", state(None, A, None), {"state": "missing"})
s.eq("missing: an empty row", state({}, A, None), {"state": "missing"})
s.eq("evidence of another commit is stale, naming that commit", state(ev(B), A, None), {"state": "stale", "sha": B})
s.eq("a dirty tree", state(ev(A, False), A, None), {"state": "dirty", "sha": A})
s.eq("a failed command is named", state(ev(A, True, ("test", 0), ("lint", 1)), A, None),
     {"state": "failed", "sha": A, "failed": ["lint"], "passed": 1, "total": 2})
s.eq("a command with no exit code (killed) failed", state(ev(A, True, ("test", None)), A, None)["state"], "failed")
s.eq("the recipe's commands are required", state(ev(), A, rec("test", "lint", "build")),
     {"state": "incomplete", "sha": A, "missing": ["build"]})
s.eq("matching commands verify", state(ev(), A, rec("test", "lint")),
     {"state": "verified", "sha": A, "passed": 2, "total": 2})
s.eq("a command swapped for `true` is not verified", state(ev(A, True, ("true", 0), ("lint", 0)), A, rec("test", "lint")),
     {"state": "untrusted", "sha": A, "mismatched": ["true"], "missing": ["test"]})
s.eq("every command swapped for `true` is not verified", state(ev(A, True, ("true", 0)), A, rec("test"))["state"], "untrusted")
s.eq("whitespace around a command does not matter",
     state(ev(A, True, (" test ", 0), ("lint", 0)), A, rec("test", "lint"))["state"], "verified")
s.eq("a command of the recipe given as a dict", state(ev(), A, [{"command": "test"}, "lint"])["state"], "verified")
s.eq("a setup command outside the recipe that passes is not compared",
     state(ev(A, True, ("npm ci", 0), ("test", 0), ("lint", 0)), A, rec("test", "lint")),
     {"state": "verified", "sha": A, "passed": 3, "total": 3})
s.eq("a failing command outside the recipe still fails the evidence",
     state(ev(A, True, ("npm ci", 1), ("test", 0), ("lint", 0)), A, rec("test", "lint")),
     {"state": "failed", "sha": A, "failed": ["npm ci"], "passed": 2, "total": 3})
s.eq("a recipe with no checks", state(ev(), A, []), {"state": "no_checks"})
s.eq("a recipe with no checks, no evidence", state(None, A, []), {"state": "no_checks"})
s.eq("evidence that ran no command, no recipe", state({"sha": A, "clean": True, "commands": []}, A, None), {"state": "no_checks"})
s.eq("a swapped command that also fails is untrusted before it is failed",
     state(ev(A, True, ("true", 1), ("lint", 0)), A, rec("test", "lint"))["state"], "untrusted")
s.eq("dirty comes before incomplete", state(ev(A, False), A, rec("test", "lint", "build"))["state"], "dirty")
s.eq("a failure named once however often it ran", state(ev(A, True, ("test", 1), ("test", 1)), A, rec("test"))["failed"], ["test"])
s.eq("a failure and a pass of one command: failed", state(ev(A, True, ("test", 1), ("test", 0)), A, rec("test"))["state"], "failed")
s.eq("the head's evidence wins when another commit's is newer in the file", state(ev(C), A, rec("test"))["state"], "stale")
for bad, label in (({"sha": A, "clean": True, "commands": "test"}, "commands that is not a list"),
                   ({"sha": A, "clean": True, "commands": [{"cmd": "t"}]}, "a command with no rc"),
                   ({"sha": A, "clean": True, "commands": [{"cmd": "t", "rc": True}]}, "an rc that is a bool"),
                   ({"sha": A, "clean": "yes", "commands": []}, "a clean that is not a bool"),
                   ({"sha": A, "clean": True, "commands": [{"rc": 0}]}, "a command with no cmd")):
    try:
        state(bad, A, None)
        s.ok("malformed evidence is an error: %s" % label, False, "no error")
    except ValueError:
        s.ok("malformed evidence is an error: %s" % label, True)
try:
    state(ev(), "", None)
    s.ok("an empty head sha is an error", False, "no error")
except ValueError:
    s.ok("an empty head sha is an error", True)
s.eq("evidence with no sha proves no head", state({"sha": "", "clean": True, "commands": [{"cmd": "t", "rc": 0}]}, A, None),
     {"state": "stale", "sha": ""})

s.done()
