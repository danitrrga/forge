#!/usr/bin/env python3
"""core.decide and `fwx decide --facts FILE`: the merge decision, from the facts of a PR.

Ports the decideMerge cases of marshal's merge-decision-regressions.ts (:83-266) that are not about Bugbot, the old
assessment format, the runner or the clock, on the `facts` of the contract: everything holds (trial: handover, would_merge
true), off evaluates nothing, no assessment, an unsure agent, the review label in any case, a red check, a conflict, an open
finding, a 303-line PR and a major bump (no rule of fwx catches those), a migration (`protected-paths`), running checks, a hard failure that does
not wait, the evidence states (no checks, failed, missing, stale, dirty, incomplete, untrusted), a PR that edits what its
checks run, a rename out of a protected path (`previous_path`), and a repo with no CI whose own evidence stands in for it.
What is not ported, and why: the attempt, behind-base, size and major-bump limits (dropped, `ee22770`, and `max-size` and
`major-bump` by the owner's answers on the merge rules), the runner's states
(5.2 runs `fwx verify` before it decides), the 60-minute wait (the caller has the clock), GitHub's `unknown` mergeability
(the producer of the facts says `running`), Bugbot (the facts carry `review`), the screenshots rule (the new `ui` reads the
mark `ui` in `surfaces`, not file names).

The 19 rules: U5a's 12 and U5b's 7 (`ui`, `type`, `hooks-settings`, `irreversible`, `outside-plan`, `weakened-assertions`,
`protected-paths`). The control loop is the plan's: for each rule, a case that
only it catches. With the table the rule hands the case over (or waits, for `still-running`) with a reason that starts with
its id and nothing else, and with the rule in `disabled` the same case would merge. The loop is a function that returns what
is wrong, and it is run again on a table without the rule and must say so: a rule deleted from the table is a failure of
this file. The file prints how many rules it checked and fails on any number but 19. The base facts' `plan_files` is `["**"]`
so that only `outside-plan` looks at the plan; a case of a rule that edits a file `.github/**` also protects is not used
for `trusted-edit` (its case is `.claude/fwx.json`): the workflow edit gets both reasons, trusted-edit first.

Also checked: in trial no case of the table is `merge`, `would_merge` keeps what the result was; off reads nothing; the
validator names the path of a bad field (unknown, missing, wrong type, a state of GitHub's that is not one of success,
failure, pending: `neutral`, `skipped`, `cancelled`, `timed_out` are refused, never read as green); the table refuses a
missing, unknown or duplicate id; the module imports no network library; the command prints one JSON object and exits 0, or
2 with the error on stderr and nothing on stdout; acceptance 3: a PR that edits `.github/workflows/ci.yml` is a handover
with `trusted-edit: ...`.

Seen red before the code existed (lib/fwx/core/decide.py absent; the test stops at the import):
  FAIL: cannot import fwx.core.decide: cannot import name 'decide' from 'fwx.core' (.../lib/fwx/core/__init__.py)

Controls (each seen red on a copy of the repo with one thing changed; the RED lines of the commit are the same):
  - each of the 12 rules removed in turn (its function in CHECKS made `lambda f: []`; 3 to 12 FAIL lines each, first one shown):
      FAIL: rule review-label catches its case alone and releases it when disabled: got ["with the rule its case is handover
        with only 'review-label: ...' (got handover, would_merge True, [])"], want []
      (the same line, with the rule's own id, for agent, ci-failed, conflict, trusted-edit, evidence-head, evidence-dirty,
       evidence-recipe, evidence-failed, no-checks, review-findings; for still-running: "its case is pending with only
       'still-running: ...' (got handover, would_merge True, [])")
  - the loop on a table without the rule, in this file, for each of the 12 (the loop's check made `if False:`):
      FAIL: control: the loop on a table without review-label fails: the loop saw nothing wrong with a table that has no review-label
  - a row deleted from decide_rules.json:
      FAIL: the engine's rule table cannot be loaded: .../decide_rules.json has no row for the rule(s) conflict (to let one go,
        put it in disabled)
  - trial can return `merge`:
      FAIL: everything holds in trial: handover, would_merge, no reason: got {'decision': 'merge', 'would_merge': True, 'reasons': []}, want {'decision': 'handover', ...}
  - off evaluates (and so reads the rest of the facts):
      FAIL: mode off: handover, no reason, nothing evaluated (facts of mode only): got {'decision': 'ERROR', ..., 'reasons': ['facts.labels: missing']}
  - a hard failure waits for a running check (reasons kept only when nothing waits):
      FAIL: a hard failure does not wait for the checks: got ('pending', ['still-running']), want ('handover', ['conflict'])
  - GitHub's raw states accepted (neutral, skipped, cancelled, timed_out, action_required, "Success", ""; 9 FAIL lines):
      FAIL: refused: a check in the state 'neutral' (GitHub's, not the three of the contract): got None, want it to start with 'facts.pr.checks[0].state: expected one of success, failure, pending'
  - unknown fields accepted (5 FAIL lines):
      FAIL: refused: an unknown top-level field: got None, want it to start with 'facts.bogus: unknown field'
  - a table that may lack a rule the code has:
      FAIL: a table without a rule the code has is refused, naming it
  - `disabled` ignored (25 FAIL lines):
      FAIL: rule review-label catches its case alone and releases it when disabled: got ['with the rule in disabled the case would merge (got handover, would_merge False, ...
  - reasons without the rule id (45 FAIL lines):
      FAIL: rule review-label catches its case alone and releases it when disabled: got ['with the rule its case is handover with only 'review-label: ...' (got handover, would_merge False, ['the issue has the "review" label ...
  - the review label compared case-sensitive:
      FAIL: rule review-label catches its case alone and releases it when disabled: got ["with the rule its case is handover ... (got handover, would_merge True, [])"], want []
  - `still-running` a handover in the table:
      FAIL: rule still-running catches its case alone and releases it when disabled: got ["with the rule its case is pending ... (got handover, would_merge False, ['still-running: waiting for GitHub'])"], want []
  - the module imports `socket`:
      FAIL: lib/fwx/core/decide.py imports no network or process library: got {'socket'}, want set()
(207 checks on the good code, U5a.)

U5b, seen red before the code existed (decide.py with 12 rules, decide_rules.json without the new rows or
`default_protected_paths`; 110 FAIL lines, the table's and the seven rules' first):
  FAIL: the table of the engine lists the 19 rules, in this order: got ['review-label', 'agent', 'ci-failed', ...], want
    ['review-label', 'agent', 'type', 'ui', 'ci-failed', ...]
  FAIL: rule type catches its case alone and releases it when disabled: got ["with the rule its case is handover with only
    'type: ...' (got handover, would_merge True, [])"], want []
  (the same line, with the rule's own id, for ui, hooks-settings, protected-paths, irreversible, outside-plan,
   weakened-assertions)
  FAIL: a table with no default_protected_paths is refused, naming the key

U5b controls (each seen red on a copy of the repo with one thing changed; 1 to 32 FAIL lines each, first one shown):
  - each of the 7 new rules removed in turn (its function in CHECKS made `lambda f, table: []`):
      FAIL: rule ui catches its case alone and releases it when disabled: got ["with the rule its case is handover with only
        'ui: ...' (got handover, would_merge True, [])"], want []
      (the same line, with the rule's own id, for type, hooks-settings, protected-paths, irreversible, outside-plan,
       weakened-assertions)
  - `ui` that also looks at the extension (the plan's control):
      FAIL: ui: a .tsx typo with surfaces [] is no `ui` reason (would merge): ui: handover for a .tsx typo: ['ui: the work
        changes what is seen or how the interface is used, so a person sees it']
  - `type` that misses `structural`:
      FAIL: type structural hands over: []
  - `hooks-settings` that ignores previous_path:
      FAIL: a rename out of hooks/ counts through previous_path: []
  - `protected-paths` that ignores previous_path:
      FAIL: a rename out of the workflows directory counts through previous_path: got ['trusted-edit'], want ['trusted-edit',
        'protected-paths']
  - `protected-paths` without the table's default globs, or without the project's:
      FAIL: rule protected-paths catches its case alone and releases it when disabled: ... (27 FAIL lines)
      FAIL: the project's own globs apply: []
  - `irreversible` that ignores the base branch:
      FAIL: rule irreversible catches its case alone and releases it when disabled: ... (5 FAIL lines)
  - `irreversible` that searches `mcp__` names in patches:
      FAIL: irreversible: a tool name in a patch (the consent window's) is no reason: ['irreversible: it adds a production
        command: mcp__neon__run_sql (scripts/ship.sh)']
  - `irreversible` that reads removed lines:
      FAIL: irreversible: a removed line is no reason: ['irreversible: it adds a production command: vercel deploy (scripts/ship.sh)']
  - `irreversible` with no word boundary, or with one blank only between the words:
      FAIL: irreversible: a command that is only the start of a longer word is no reason: [...]
      FAIL: any run of blanks inside the command: []
  - `outside-plan` with no `.fwx/` exemption, with an empty plan that passes, or that also reads previous_path:
      FAIL: outside-plan: a file of .fwx/ is never outside
      FAIL: outside-plan: no plan files says so, for a person: outside-plan: it changes files outside the plan: src/list.py
      FAIL: outside-plan: only the new path of a rename is looked at
  - `weakened-assertions` that passes a test file with no patch, hands over a reworded assertion (`>=` for `>`), ignores
    previous_path, counts the patch headers, or reads non-test files:
      FAIL: a test file with no patch cannot be compared: []
      FAIL: weakened-assertions: an assertion reworded (one out, one in) merges
      FAIL: a test file moved out of the tests that lost one: []
      FAIL: weakened-assertions: the file header of a patch is no assertion line
      FAIL: rule review-label catches its case alone and releases it when disabled: ... (191 FAIL lines)
  - `weakened-assertions` that does not know this repo's Suite (`.eq(`, `.ok(`):
      FAIL: an assertion removed, this repo's Suite: []
  - the table that does not require `default_protected_paths`:
      FAIL: a table with no default_protected_paths is refused, naming the key
  - a row of decide_rules.json deleted, or `drizzle/**` deleted from its default globs:
      FAIL: the engine's rule table cannot be loaded: .../decide_rules.json has no row for the rule(s) irreversible (to let one go,
        put it in disabled)
      FAIL: rule protected-paths catches its case alone and releases it when disabled: ... (10 FAIL lines)
  - `irreversible` that skips a file with no patch (it must fail closed):
      FAIL: a changed file with no patch cannot be shown safe: it fails closed: []
(394 checks on the good code.)
"""
import ast
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx.core import decide  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.core.decide: %s" % e)
    sys.exit(1)

EXPECTED = ["review-label", "agent", "type", "ui", "ci-failed", "conflict", "trusted-edit", "hooks-settings",
            "protected-paths", "irreversible", "outside-plan", "weakened-assertions", "evidence-head", "evidence-dirty",
            "evidence-recipe", "evidence-failed", "no-checks", "review-findings", "still-running"]
PENDING = {"still-running"}
HEAD = "a" * 40
OTHER = "b" * 40
RECIPE = "python3 bin/fwx test"


def facts():
    """A PR that would merge: a plain edit the plan covers, a green check, the evidence at the head for the whole recipe, a
    confident agent."""
    return {
        "mode": "trial", "labels": ["factory"], "type": "bug", "risk": "low", "surfaces": [],
        "agent": {"recommendation": "merge", "confident": True, "assumptions": ["sorted by name"]},
        "pr": {"number": 7, "head_sha": HEAD, "base": "factory", "mergeable": True, "running": False,
               "changed_files": [{"path": "src/list.py", "additions": 10, "deletions": 2}],
               "checks": [{"name": "ci", "state": "success"}]},
        "evidence": {"sha": HEAD, "clean": True, "commands": [{"cmd": RECIPE, "rc": 0}]},
        "plan_files": ["**"], "review": {"open_medium_high": 0, "running": False},
        "project": {"checks": [RECIPE], "protected_paths": [], "production": {"branches": [], "commands": []},
                    "ui_bugs": False},
    }


def put(f, dotted, value):
    """f with the field at `dotted` (keys, and list indexes as numbers) set to value; f itself is changed and returned."""
    keys = dotted.split(".")
    node = f
    for k in keys[:-1]:
        node = node[int(k)] if isinstance(node, list) else node[k]
    if isinstance(node, list):
        node[int(keys[-1])] = value
    else:
        node[keys[-1]] = value
    return f


def edit(f, path, **extra):
    f["pr"]["changed_files"].append(dict({"path": path, "additions": 1, "deletions": 0}, **extra))
    return f


def patch_of(*lines):
    """A GitHub-style patch of the given body lines (each with its own +, - or space)."""
    return "@@ -1,%d +1,%d @@\n%s" % (len(lines), len(lines), "\n".join(lines))


def prod(f, branches=(), commands=()):
    return put(f, "project.production", {"branches": list(branches), "commands": list(commands)})


CASES = {
    "review-label": lambda: put(facts(), "labels", ["factory", "Review"]),
    "agent": lambda: put(facts(), "agent", None),
    "type": lambda: put(facts(), "type", "feature"),
    "ui": lambda: put(facts(), "surfaces", ["ui"]),
    "ci-failed": lambda: put(facts(), "pr.checks", [{"name": "ci", "state": "failure"}]),
    "conflict": lambda: put(facts(), "pr.mergeable", False),
    "trusted-edit": lambda: edit(facts(), ".claude/fwx.json"),
    "hooks-settings": lambda: edit(facts(), "hooks/guard.sh"),
    "protected-paths": lambda: edit(facts(), "drizzle/0001.sql"),
    "irreversible": lambda: put(prod(facts(), ["main"]), "pr.base", "main"),
    "outside-plan": lambda: put(edit(facts(), "docs/notes.md"), "plan_files", ["src/**"]),
    "weakened-assertions": lambda: edit(facts(), "tests/test_list.py", patch=patch_of("-    assert a == 1", "+    pass")),
    "evidence-head": lambda: put(facts(), "evidence.sha", OTHER),
    "evidence-dirty": lambda: put(facts(), "evidence.clean", False),
    "evidence-recipe": lambda: put(facts(), "evidence.commands", []),
    "evidence-failed": lambda: put(facts(), "evidence.commands", [{"cmd": RECIPE, "rc": 1}]),
    "no-checks": lambda: put(facts(), "project.checks", []),
    "review-findings": lambda: put(facts(), "review.open_medium_high", 2),
    "still-running": lambda: put(facts(), "pr.running", True),
}


def D(f, tbl=None):
    """decide.decide, with a refusal of the facts as a result that no check expects instead of a crash."""
    try:
        return decide.decide(f, tbl)
    except decide.FactsError as e:
        return {"decision": "ERROR", "would_merge": None, "reasons": [str(e)]}


def loop_failures(table, rid):
    """What is wrong with how `table` treats the case of rule `rid`; [] when the rule catches it and lets it go."""
    bad = []
    got = D(CASES[rid](), table)
    mine = [r for r in got["reasons"] if r.startswith(rid + ": ")]
    want = "pending" if rid in PENDING else "handover"
    if got["decision"] != want or got["would_merge"] or len(mine) != 1 or got["reasons"] != mine:
        bad.append("with the rule its case is %s with only %r (got %s, would_merge %s, %r)" % (want, rid + ": ...",
                   got["decision"], got["would_merge"], got["reasons"]))
    released = dict(table, disabled=list(table["disabled"]) + [rid])
    got = D(CASES[rid](), released)
    if not got["would_merge"] or got["reasons"]:
        bad.append("with the rule in disabled the case would merge (got %s, would_merge %s, %r)" % (
            got["decision"], got["would_merge"], got["reasons"]))
    return bad


try:
    table = decide.load_table()
except decide.TableError as e:
    print("FAIL: the engine's rule table cannot be loaded: %s" % e)
    sys.exit(1)
ids = [r["id"] for r in table["rules"]]
s.eq("the table of the engine lists the 19 rules, in this order", ids, EXPECTED)
s.eq("nothing is disabled by default", table["disabled"], [])

# ---- the control loop: each rule catches its case alone, lets it go when disabled, and the loop notices a missing rule ----
checked = 0
every_case = [("baseline", facts())]
for rid in EXPECTED:
    s.eq("rule %s catches its case alone and releases it when disabled" % rid, loop_failures(table, rid), [])
    without = dict(table, rules=[r for r in table["rules"] if r["id"] != rid])
    s.ok("control: the loop on a table without %s fails" % rid, loop_failures(without, rid) != [],
         "the loop saw nothing wrong with a table that has no %s" % rid)
    checked += 1
    every_case.append((rid, CASES[rid]()))

# ---- trial never merges, would_merge keeps what the result was --------------------------------------------------
g = D(facts())
s.eq("everything holds in trial: handover, would_merge, no reason", g, {"decision": "handover", "would_merge": True, "reasons": []})
for name, case in every_case:
    for variant, tbl in (("table", table), ("rule disabled", dict(table, disabled=EXPECTED))):
        got = D(copy.deepcopy(case), tbl)
        s.ok("trial never merges: case %s, %s" % (name, variant), got["decision"] in ("handover", "pending"), got["decision"])
        s.eq("would_merge is (result == merge): case %s, %s" % (name, variant),
             got["would_merge"], variant == "rule disabled" or name == "baseline")
f = facts()
before = copy.deepcopy(f)
D(f)
s.eq("decide does not change its input", f, before)

# ---- off ------------------------------------------------------------------------------------------------------------
off = {"decision": "handover", "would_merge": False, "reasons": []}
s.eq("mode off: handover, no reason, nothing evaluated (facts of mode only)", D({"mode": "off"}), off)
worst = put(facts(), "mode", "off")
put(worst, "labels", ["review"]); put(worst, "pr.mergeable", False); put(worst, "agent", None)
s.eq("mode off with facts that fail rules: still no reason", D(worst), off)

# ---- marshal's cases, on the contract's facts ------------------------------------------------------------------
def reasons_of(f):
    return D(f)["reasons"]


def rules_of(f, tbl=None):
    """The ids of the rules that give a reason, one per reason, in order."""
    return [r.split(":")[0] for r in D(f, tbl)["reasons"]]


def first(f):
    """The first reason of a decision, or '' when there is none."""
    r = reasons_of(f)
    return r[0] if r else ""


def only(f, rid, why):
    r = reasons_of(f)
    s.ok(why, len(r) == 1 and r[0].startswith(rid + ": "), repr(r))


f = put(facts(), "agent", {"recommendation": "handover", "confident": False, "assumptions": []})
only(f, "agent", "an agent that recommends handing over and is not confident: one agent reason")
s.ok("the agent reason says why", "not confident" in first(f) and "handing over" in first(f), first(f))
only(put(facts(), "agent.confident", False), "agent", "recommend merge but not confident: handover")
only(put(facts(), "agent.recommendation", "handover"), "agent", "confident but recommends handover: handover")
only(put(facts(), "agent", None), "agent", "no assessment at all")
s.ok("no assessment says so", "no assessment" in first(put(facts(), "agent", None)), first(put(facts(), "agent", None)))
only(put(facts(), "labels", ["factory", "REVIEW"]), "review-label", "the review label in capitals")
s.eq("a label that only contains the word review is not the label", D(put(facts(), "labels", ["code-review"]))["would_merge"], True)
f = put(facts(), "pr.checks", [{"name": "ci", "state": "success"}, {"name": "lint", "state": "failure"}])
only(f, "ci-failed", "one red check among green ones")
s.ok("only the red check is named", first(f).endswith(": lint"), first(f))
only(put(facts(), "pr.mergeable", False), "conflict", "a conflict")
only(put(facts(), "review.open_medium_high", 1), "review-findings", "one open medium or high finding")
s.ok("one finding is said in the singular", first(put(facts(), "review.open_medium_high", 1)).endswith(": the review has 1 unresolved medium or high finding"),
     first(put(facts(), "review.open_medium_high", 1)))
s.eq("no open finding: the review is no reason", D(facts())["reasons"], [])

# size and major bumps are not rules of fwx (major-bump and max-size were dropped), and a manifest edit that only bumps a
# dependency is not an edit of what the checks run
f = facts()
put(f, "pr.changed_files", [{"path": "a.py", "additions": 200, "deletions": 103}])
s.eq("a 303-line pull request merges", D(f)["would_merge"], True)
f = put(facts(), "pr.changed_files", [{"path": "drizzle/0001.sql", "additions": 1, "deletions": 0}])
only(f, "protected-paths", "a migration is a protected path (marshal's `drizzle/**`)")
npm = facts()
put(npm, "project.checks", ["npm run test"])
put(npm, "evidence.commands", [{"cmd": "npm run test", "rc": 0}])
bump = '@@ -3,3 +3,3 @@\n   "dependencies": {\n-    "next": "^14.2.0",\n+    "next": "^15.0.0"\n   }'
put(npm, "pr.changed_files", [{"path": "package.json", "additions": 1, "deletions": 1, "patch": bump}])
s.eq("a manifest whose diff bumps a major version merges", D(copy.deepcopy(npm))["would_merge"], True)
rewritten = '@@ -5,3 +5,3 @@\n   "scripts": {\n-    "test": "vitest run",\n+    "test": "true"\n   }'
put(npm, "pr.changed_files", [{"path": "package.json", "additions": 1, "deletions": 1, "patch": rewritten}])
only(npm, "trusted-edit", "a package.json diff that rewrites the script a check runs")
put(npm, "pr.changed_files", [{"path": "package.json", "additions": 1, "deletions": 1}])
only(npm, "trusted-edit", "a package.json with no patch cannot be compared: a person looks")

# a check that is running is pending; so is the review, and so is GitHub computing; hard failures do not wait
f = put(facts(), "pr.checks", [{"name": "ci", "state": "pending"}, {"name": "lint", "state": "pending"}])
put(f, "review.running", True)
got = D(f)
s.eq("running checks and a running review are pending, not a handover", got["decision"], "pending")
s.eq("pending is not a would-merge", got["would_merge"], False)
s.eq("the waiting reason names the rule and what runs", got["reasons"],
     ["still-running: waiting for checks (ci, lint), the review"])
s.eq("GitHub still computing the PR is pending", D(put(facts(), "pr.running", True))["decision"], "pending")
s.eq("a review still running is pending", D(put(facts(), "review.running", True))["decision"], "pending")
f = put(facts(), "pr.checks", [{"name": "ci", "state": "pending"}])
put(f, "pr.mergeable", False)
got = D(f)
s.eq("a hard failure does not wait for the checks", (got["decision"], [r.split(":")[0] for r in got["reasons"]]), ("handover", ["conflict"]))
f = put(facts(), "pr.checks", [{"name": "ci", "state": "pending"}])
put(f, "evidence.sha", OTHER)
s.eq("evidence of another commit hands over even while a check runs",
     [r.split(":")[0] for r in D(f)["reasons"]], ["evidence-head"])

# the evidence states, one rule each
def evid(**over):
    return put(facts(), "evidence", dict(facts()["evidence"], **over))


only(evid(commands=[]), "evidence-recipe", "a required check that did not run (incomplete)")
r = reasons_of(evid(commands=[{"cmd": "true", "rc": 0}]))
s.eq("checks that ran other commands than the recipe's (untrusted)", [x.split(":")[0] for x in r], ["evidence-recipe"])
s.ok("untrusted names what ran and what was left out", "true" in "".join(r) and RECIPE in "".join(r), r)
only(evid(clean=False), "evidence-dirty", "a dirty tree proves nothing")
only(evid(sha=OTHER), "evidence-head", "evidence of an older commit")
s.ok("stale evidence names both commits", OTHER[:7] in first(evid(sha=OTHER)) and HEAD[:7] in first(evid(sha=OTHER)), first(evid(sha=OTHER)))
only(put(facts(), "evidence", {}), "evidence-head", "no evidence at all is not at the head")
f = evid(commands=[{"cmd": RECIPE, "rc": 1}, {"cmd": "make lint", "rc": 2}])
put(f, "project.checks", [RECIPE, "make lint"])
r = reasons_of(f)
s.eq("a failed check at the head, with every failed command named", (len(r), first(f).startswith("evidence-failed: ")), (1, True))
s.ok("the failed commands are named", RECIPE in first(f) and "make lint" in first(f), first(f))
only(evid(commands=[{"cmd": RECIPE, "rc": None}]), "evidence-failed", "a command that never exited is failed")
only(put(facts(), "project.checks", []), "no-checks", "a repo with no checks never merges on its own")
f = put(facts(), "project.checks", [])
put(f, "evidence", {})
s.eq("no checks wins over no evidence", [x.split(":")[0] for x in reasons_of(f)], ["no-checks"])
f = put(facts(), "project.checks", [{"command": RECIPE}])
s.eq("a check given as {command} is read as its command", D(f)["would_merge"], True)
f = put(facts(), "evidence", dict(facts()["evidence"], source="verify", rc=0))
s.eq("the evidence as `fwx verify --json` prints it (with source and rc) is accepted as it is", D(f)["would_merge"], True)

# a repo with no CI: the evidence at the head is the only CI
f = put(facts(), "pr.checks", [])
s.eq("no check reported and the evidence at the head: would merge", D(f)["would_merge"], True)
put(f, "evidence", {})
only(f, "evidence-head", "no check reported and no evidence: nothing to rely on")

# a PR that edits what its checks run
# `.github/**` is also one of marshal's default protected paths, so a workflow edit is both: two reasons, trusted-edit first
s.eq("a workflow edit hands over despite verified evidence: trusted-edit, and protected-paths for `.github/**`",
     rules_of(edit(facts(), ".github/workflows/ci.yml")), ["trusted-edit", "protected-paths"])
only(edit(facts(), ".claude/fwx.json"), "trusted-edit", "an edit of the recipe")
f = edit(facts(), "scripts/old/ci.yml", previous_path=".github/workflows/ci.yml")
s.eq("a rename out of the workflows directory counts through previous_path", rules_of(f), ["trusted-edit", "protected-paths"])
f = put(facts(), "project.checks", ["make test"])
put(f, "evidence.commands", [{"cmd": "make test", "rc": 0}])
only(edit(f, "Makefile"), "trusted-edit", "a Makefile edit with `make test` as the check")
only(edit(facts(), "bin/fwx"), "trusted-edit", "an edit of the file the check runs (`python3 bin/fwx test`)")
s.ok("a trusted-edit reason is the one trusted_edits gives, behind its id", first(edit(facts(), ".github/workflows/ci.yml")).startswith(
    "trusted-edit: The pull request edits CI workflows (.github/workflows/ci.yml)"), first(edit(facts(), ".github/workflows/ci.yml")))

# several rules at once: all of them, in the order of the table
f = put(facts(), "labels", ["review"])
put(f, "pr.mergeable", False)
put(f, "pr.checks", [{"name": "ci", "state": "failure"}])
put(f, "review.open_medium_high", 3)
got = D(f)
s.eq("four rules at once: handover with the four, in the order of the table",
     (got["decision"], [r.split(":")[0] for r in got["reasons"]]), ("handover", ["review-label", "ci-failed", "conflict", "review-findings"]))
s.ok("every reason starts with the id of a rule of the table", all(r.split(": ", 1)[0] in ids for r in got["reasons"]), repr(got["reasons"]))

# ---- the 7 rules of U5b ----------------------------------------------------------------------------------------------
def merges(f):
    got = D(f)
    return got["would_merge"] is True and got["reasons"] == []


# type: a feature or a structural change is a person's
for kind in ("feature", "structural"):
    f = put(facts(), "type", kind)
    only(f, "type", "type %s hands over" % kind)
    s.ok("type %s: the reason names the type" % kind, kind in first(f), first(f))
for kind in ("bug", "refactor", "chore"):
    s.ok("type %s merges" % kind, merges(put(facts(), "type", kind)), repr(reasons_of(put(facts(), "type", kind))))

# ui: the mark `ui` in `surfaces` decides, never a file name ("if it is a tsx for a typo I do not care")
typo = edit(facts(), "src/components/Button.tsx")
s.ok("ui: a .tsx typo with surfaces [] is no `ui` reason (would merge)", merges(typo),
     "ui: handover for a .tsx typo: %r" % reasons_of(typo))
for path in ("src/styles/app.css", "src/App.jsx", "src/page.html", "src/view.vue", "src/Card.svelte", "src/icon.svg"):
    f = edit(facts(), path)
    s.ok("ui: %s with surfaces [] merges" % path, merges(f), "ui: handover for %s: %r" % (path, reasons_of(f)))
f = put(edit(facts(), "src/components/Button.tsx"), "surfaces", ["ui"])
got = D(f)
s.eq("ui: the same PR marked `ui` is a handover with one reason", (got["decision"], got["would_merge"], len(got["reasons"])), ("handover", False, 1))
s.ok("ui: the reason starts with `ui: `", "".join(got["reasons"]).startswith("ui: "), repr(got["reasons"]))
s.eq("ui: a marked PR that touches no UI file is still a handover", rules_of(put(facts(), "surfaces", ["ui"])), ["ui"])
s.ok("ui: the mark `security` alone is no ui reason", merges(put(facts(), "surfaces", ["security"])), repr(reasons_of(put(facts(), "surfaces", ["security"]))))
s.eq("ui: both marks give one ui reason", rules_of(put(facts(), "surfaces", ["security", "ui"])), ["ui"])

# hooks-settings: the hooks and the settings of the agent and of git, by path and by previous_path
for path in ("hooks/guard.sh", ".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/pre.py", "githooks/pre-commit",
             ".githooks/pre-push", ".husky/pre-commit", "hooks/deep/er/x.sh"):
    only(edit(facts(), path), "hooks-settings", "hooks-settings: %s" % path)
for path in ("src/hooks/useThing.ts", ".claude/skills/x/SKILL.md", "docs/hooks.md", "settings.json", ".claude/settings/x.json", "src/githooks.py"):
    s.ok("hooks-settings: %s is not one" % path, merges(edit(facts(), path)), repr(reasons_of(edit(facts(), path))))
only(edit(facts(), "scripts/old/x.sh", previous_path="hooks/x.sh"), "hooks-settings", "a rename out of hooks/ counts through previous_path")
only(edit(facts(), "scripts/old/x.json", previous_path=".claude/settings.json"), "hooks-settings", "a rename out of the settings counts through previous_path")
s.ok("hooks-settings: the reason names the file", "hooks/guard.sh" in first(edit(facts(), "hooks/guard.sh")), first(edit(facts(), "hooks/guard.sh")))

# irreversible: the base is a production branch, or a patch adds a production command; mcp__ names are the consent window's
f = put(prod(facts(), ["main", "release"]), "pr.base", "release")
only(f, "irreversible", "a PR whose base is a production branch")
s.ok("irreversible: the reason names the branch", "release" in first(f), first(f))
s.ok("irreversible: a base that is not a production branch merges", merges(put(prod(facts(), ["main"]), "pr.base", "factory")), "")
s.ok("irreversible: no production branches, base main: merges", merges(put(facts(), "pr.base", "main")), "")
s.ok("irreversible: `main` is not `maintenance`", merges(put(prod(facts(), ["main"]), "pr.base", "maintenance")), "")
CMDS = ["vercel deploy", "terraform apply", "mcp__neon__run_sql", ""]


def with_cmds(commands):
    """The base PR with production commands to search for, and a patch on its own file (a file with no patch fires)."""
    return put(prod(facts(), [], commands), "pr.changed_files.0.patch", patch_of("+x = 1"))


def adds(*body, path="scripts/ship.sh"):
    return edit(with_cmds(CMDS), path, patch=patch_of(*body))


f = adds("+vercel deploy --prod")
only(f, "irreversible", "an added line with a production command prefix")
s.ok("irreversible: the reason names the command and the file", "vercel deploy" in first(f) and "scripts/ship.sh" in first(f), first(f))
only(adds("+  run: terraform apply -auto-approve"), "irreversible", "the command in the middle of an added line")
only(adds("+vercel   deploy"), "irreversible", "any run of blanks inside the command")
only(adds("+x && vercel\tdeploy"), "irreversible", "a tab inside the command, after an operator")
for why, line in (("a removed line", "-vercel deploy --prod"), ("a context line", " vercel deploy --prod"),
                  ("a command that is only the start of a longer word", "+vercel deployment-notes"),
                  ("a command at the end of a longer word", "+prevercel deploy"), ("a path that ends in the command", "+cp x /bin/vercel deploy"),
                  ("a different command", "+vercel dev"), ("a tool name in a patch (the consent window's)", "+mcp__neon__run_sql(drop)")):
    s.ok("irreversible: %s is no reason" % why, merges(adds(line)), repr(reasons_of(adds(line))))
f = edit(with_cmds(CMDS), "assets/big.bin")
only(f, "irreversible", "a changed file with no patch cannot be shown safe: it fails closed")
s.ok("irreversible: the no-patch reason names the file and says there is no patch to inspect",
     "assets/big.bin" in first(f) and "no patch to inspect" in first(f), first(f))
only(edit(with_cmds(CMDS), "scripts/x.sh", patch=""), "irreversible", "an empty patch is no patch")
s.ok("irreversible: with nothing to search for (no commands, or only mcp__ names) a file with no patch is no reason",
     merges(edit(prod(facts(), [], []), "assets/big.bin")) and merges(edit(prod(facts(), [], ["mcp__neon__run_sql"]), "assets/big.bin")), "")
s.ok("irreversible: an empty entry in commands matches nothing", merges(edit(prod(facts(), [], [""]), "a.sh", patch=patch_of("+x"))), "")
f = put(adds("+vercel deploy"), "pr.base", "main")
put(f, "project.production.branches", ["main"])
s.eq("irreversible: the base and a command give two reasons, one rule", rules_of(f), ["irreversible", "irreversible"])

# outside-plan: a file the plan's globs do not cover, except .fwx/; no plan at all is a person's too
f = put(edit(facts(), "docs/notes.md"), "plan_files", ["src/**"])
only(f, "outside-plan", "a file outside the plan")
s.ok("outside-plan: the reason names the file and not the one inside", "docs/notes.md" in first(f) and "src/list.py" not in first(f), first(f))
s.ok("outside-plan: every file inside the plan merges", merges(put(facts(), "plan_files", ["src/**"])), "")
s.ok("outside-plan: a file of .fwx/ is never outside", merges(put(edit(facts(), ".fwx/factory/DTC-1/audit.tsv"), "plan_files", ["src/**"])), "")
s.eq("outside-plan: .fwx/ below another directory is not exempt", rules_of(put(edit(facts(), "pkg/.fwx/x"), "plan_files", ["src/**"])), ["outside-plan"])
f = put(facts(), "plan_files", [])
only(f, "outside-plan", "no plan files at all")
s.ok("outside-plan: no plan files says so, for a person", "no files" in first(f) and "person" in first(f), first(f))
s.ok("outside-plan: a plan of several globs", merges(put(edit(facts(), "docs/a.md"), "plan_files", ["src/**", "docs/*.md"])), "")
s.eq("outside-plan: a glob does not reach into another directory", rules_of(put(edit(facts(), "docs/deep/a.md"), "plan_files", ["src/**", "docs/*.md"])), ["outside-plan"])
many = put(facts(), "plan_files", ["src/**"])
for i in range(7):
    edit(many, "other/f%d.txt" % i)
s.eq("outside-plan: one reason for all the files outside the plan", rules_of(many), ["outside-plan"])
s.ok("outside-plan: the list is cut after five files", "other/f4.txt" in first(many) and "other/f5.txt" not in first(many) and first(many).endswith("..."), first(many))
s.ok("outside-plan: only the new path of a rename is looked at", merges(put(edit(facts(), "src/new.py", previous_path="docs/old.py"), "plan_files", ["src/**"])), "")

# weakened-assertions: in test files, more assertion lines removed than added, or no patch to compare
f = edit(facts(), "tests/test_list.py", patch=patch_of("-    assert a == 1", "-    assert b == 2", "+    assert a == 1"))
only(f, "weakened-assertions", "two assertions removed, one added")
s.ok("weakened-assertions: the reason names the file and the counts", "tests/test_list.py" in first(f) and "-2" in first(f) and "+1" in first(f), first(f))


def test_edit(path, *body, **extra):
    return edit(facts(), path, patch=patch_of(*body), **extra)


s.ok("weakened-assertions: an assertion reworded (one out, one in) merges",
     merges(test_edit("tests/test_list.py", "-    assert a == 1", "+    assert a == 2")), "")
s.ok("weakened-assertions: more assertions added than removed merges",
     merges(test_edit("tests/test_list.py", "-    assert a == 1", "+    assert a == 1", "+    assert b == 2")), "")
s.ok("weakened-assertions: lines removed that are no assertion merge",
     merges(test_edit("tests/test_list.py", "-    # setup", "-    x = 1", "+    x = 2")), "")
s.ok("weakened-assertions: a moved assertion (as many out as in) merges",
     merges(test_edit("tests/test_list.py", "-    assert a == 1", " ctx", "+    assert a == 1")), "")
only(edit(facts(), "tests/test_list.py"), "weakened-assertions", "a test file with no patch cannot be compared")
only(test_edit("tests/test_list.py", "-    assert a == 1", "-    assert b == 2"), "weakened-assertions", "a test file with only assertions removed")
only(test_edit("tests/test_list.py", "-    assert a == 1", "+    pass", previous_path="tests/test_old.py"), "weakened-assertions", "a renamed test file that lost one")
only(test_edit("lib/list.py", "-    assert a == 1", "+    pass", previous_path="tests/test_list.py"), "weakened-assertions", "a test file moved out of the tests that lost one")
s.ok("weakened-assertions: assertions removed from a file that is no test file merge",
     merges(edit(facts(), "src/check.py", patch=patch_of("-    assert a == 1", "+    pass"))), "")
s.ok("weakened-assertions: a source file with no patch merges", merges(edit(facts(), "src/big.py")), "")
s.ok("weakened-assertions: the file header of a patch is no assertion line",
     merges(test_edit("tests/assertions.py", "--- a/tests/assertions.py", "+x")), "")
for path in ("tests/test_a.py", "src/a.test.ts", "src/__tests__/a.ts", "pkg/a_test.go", "spec/a_spec.rb", "src/a.spec.js", "test/a.js", "a_test.py",
             "test_a.py", "app/tests/deep/conftest.py"):
    only(test_edit(path, "-    assert a == 1", "+    pass"), "weakened-assertions", "a test file by its name: %s" % path)
for path in ("src/latest.py", "src/contest/a.py", "src/protest.py", "docs/tests.md", "src/attest.ts", "src/testing.py"):
    s.ok("weakened-assertions: %s is no test file" % path, merges(test_edit(path, "-    assert a == 1", "+    pass")),
         repr(reasons_of(test_edit(path, "-    assert a == 1", "+    pass"))))
for flavour, line in (("pytest raises", "-    with pytest.raises(ValueError):"), ("unittest", "-        self.assertEqual(a, 1)"),
                      ("jest expect", "-  expect(a).toBe(1)"), ("go testify", "-\tassert.Equal(t, a, 1)"), ("rust", "-    assert_eq!(a, 1);"),
                      ("this repo's Suite", "-s.eq(\"a\", a, 1)"), ("chai", "-  a.should.equal(1)")):
    only(test_edit("tests/test_list.py", line, "+    pass"), "weakened-assertions", "an assertion removed, %s" % flavour)
s.ok("weakened-assertions: `require(` of a module is no assertion",
     merges(test_edit("tests/a.test.js", "-const x = require('x')", "+const x = 1")), "")

# protected-paths: the project's globs and the table's defaults (marshal's), by path and by previous_path
for path in ("drizzle/0001.sql", "db/migrations/001.sql", "migrations/1.sql", "src/auth/session.ts", "auth/x.ts", "lib/permissions/a.ts",
             "app/billing/page.ts", "payments/x.ts", ".github/CODEOWNERS", "vercel.json", "vercel.ts", ".env.local", "apps/web/.env", ".env"):
    only(edit(facts(), path), "protected-paths", "protected by default: %s" % path)
for path in ("src/app/page.tsx", "apps/vercel.json", "src/authors.py", "docs/billing.md", "src/environment.ts", "github/x.yml"):
    s.ok("protected-paths: %s is not protected by default" % path, merges(edit(facts(), path)), repr(reasons_of(edit(facts(), path))))
f = put(facts(), "project.protected_paths", ["src/**"])
only(f, "protected-paths", "the project's own globs apply")
s.ok("protected-paths: the defaults stay beside the project's globs", rules_of(edit(copy.deepcopy(f), "drizzle/1.sql")) == ["protected-paths"]
     and "drizzle/1.sql" in first(edit(copy.deepcopy(f), "drizzle/1.sql")), first(edit(copy.deepcopy(f), "drizzle/1.sql")))
f = edit(facts(), "lib/session.ts", previous_path="lib/auth/session.ts")
only(f, "protected-paths", "a rename out of a protected path")
s.ok("protected-paths: the reason names the old path", "lib/auth/session.ts" in first(f), first(f))
s.eq("protected-paths: a rename into a protected path is caught by the new path", rules_of(edit(facts(), "drizzle/x.sql", previous_path="src/x.sql")), ["protected-paths"])
OWN = ["**/migrations/**", "vercel.json", "*.ts"]
for path, hit in (("db/migrations/001.sql", True), ("migrations/1.sql", True), ("apps/vercel.json", False), ("b.ts", True), ("a/b.ts", False)):
    g = put(put(facts(), "project.protected_paths", OWN), "pr.changed_files", [{"path": path, "additions": 1, "deletions": 0}])
    s.eq("protected-paths: marshal's glob cases, %s" % path, rules_of(g, dict(table, default_protected_paths=[])) == ["protected-paths"], hit)
many = facts()
for i in list(range(7)) + [0]:
    edit(many, "drizzle/%d.sql" % i)
s.eq("protected-paths: one reason for all the files", rules_of(many), ["protected-paths"])
s.ok("protected-paths: a file is named once and the list is cut after five", first(many).count("drizzle/0.sql") == 1 and "drizzle/5.sql" not in first(many)
     and first(many).endswith("..."), first(many))
no_defaults = dict(table, default_protected_paths=[])
s.ok("protected-paths: a table with no default globs lets a migration go", D(CASES["protected-paths"](), no_defaults)["would_merge"], "")
s.eq("protected-paths: the project's globs do not need the defaults", rules_of(put(facts(), "project.protected_paths", ["src/**"]), no_defaults), ["protected-paths"])
s.ok("protected-paths: the engine's table has marshal's default globs", {"drizzle/**", "**/migrations/**", ".github/**", "**/.env*"} <= set(table.get("default_protected_paths", [])),
     repr(table.get("default_protected_paths")))

# the new rules together: the order of the table is the order of the reasons
f = put(facts(), "type", "feature")
put(f, "surfaces", ["ui"])
edit(f, "hooks/a.sh")
edit(f, "drizzle/1.sql")
put(f, "plan_files", ["src/**"])
s.eq("five new rules at once: in the order of the table", rules_of(f), ["type", "ui", "hooks-settings", "protected-paths", "outside-plan"])

# ---- the validator ---------------------------------------------------------------------------------------------------
def refused(f):
    try:
        decide.decide(f)
    except decide.FactsError as e:
        return str(e)
    return None


BAD = [
    ("an unknown top-level field", lambda f: put(f, "bogus", 1), "facts.bogus: unknown field"),
    ("an unknown field of the PR", lambda f: put(f, "pr.draft", False), "facts.pr.draft: unknown field"),
    ("a missing field", lambda f: f["pr"].pop("base") and f, "facts.pr.base: missing"),
    ("a missing section", lambda f: f.pop("review") and f, "facts.review: missing"),
    ("a string for a list", lambda f: put(f, "labels", "factory"), "facts.labels: expected a list"),
    ("a number for a string", lambda f: put(f, "labels", [3]), "facts.labels[0]: expected a string"),
    ("a string for the PR number", lambda f: put(f, "pr.number", "7"), "facts.pr.number: expected a non-negative integer"),
    ("a boolean for an integer", lambda f: put(f, "pr.number", True), "facts.pr.number: expected a non-negative integer"),
    ("a string for a boolean", lambda f: put(f, "pr.mergeable", "yes"), "facts.pr.mergeable: expected true or false"),
    ("a mode that is not off or trial", lambda f: put(f, "mode", "auto"), "facts.mode: expected one of off, trial"),
    ("a type that is not one of the five", lambda f: put(f, "type", "docs"), "facts.type: expected one of"),
    ("a risk that is not one of the three", lambda f: put(f, "risk", "none"), "facts.risk: expected one of"),
    ("a surface that is not ui or security", lambda f: put(f, "surfaces", ["billing"]), "facts.surfaces[0]: expected one of"),
    ("a recommendation that is not merge or handover", lambda f: put(f, "agent.recommendation", "ship"),
     "facts.agent.recommendation: expected one of"),
    ("a negative count of additions", lambda f: edit(f, "a.py") and put(f, "pr.changed_files.1.additions", -1),
     "facts.pr.changed_files[1].additions: expected a non-negative integer"),
    ("a previous_path that is not a string", lambda f: put(f, "pr.changed_files.0.previous_path", 3),
     "facts.pr.changed_files[0].previous_path: expected a string"),
    ("a patch that is not a string", lambda f: put(f, "pr.changed_files.0.patch", 3), "facts.pr.changed_files[0].patch: expected a string"),
    ("an empty path", lambda f: put(f, "pr.changed_files.0.path", ""), "facts.pr.changed_files[0].path: expected a non-empty string"),
    ("an empty head sha", lambda f: put(f, "pr.head_sha", ""), "facts.pr.head_sha: expected a non-empty string"),
    ("a command of the evidence with no rc", lambda f: put(f, "evidence.commands", [{"cmd": RECIPE}]),
     "facts.evidence.commands[0].rc: missing"),
    ("a string for an rc", lambda f: put(f, "evidence.commands", [{"cmd": RECIPE, "rc": "0"}]),
     "facts.evidence.commands[0].rc: expected an integer or null"),
    ("evidence without clean", lambda f: f["evidence"].pop("clean") and f, "facts.evidence.clean: missing"),
    ("a check that is neither a command nor {command}", lambda f: put(f, "project.checks", [5]),
     "facts.project.checks[0]: expected a command or an object with a command"),
    ("an unknown field of production", lambda f: put(f, "project.production.tools", []), "facts.project.production.tools: unknown field"),
    ("a number for ui_bugs", lambda f: put(f, "project.ui_bugs", 1), "facts.project.ui_bugs: expected true or false"),
    ("a count of findings that is not an integer", lambda f: put(f, "review.open_medium_high", "2"),
     "facts.review.open_medium_high: expected a non-negative integer"),
]
for state_name in ("neutral", "skipped", "cancelled", "timed_out", "action_required", "Success", ""):
    BAD.append(("a check in the state %r (GitHub's, not the three of the contract)" % state_name,
                lambda f, st=state_name: put(f, "pr.checks.0.state", st), "facts.pr.checks[0].state: expected one of success, failure, pending"))
n_bad = 0
for label, mutate, want in BAD:
    msg = refused(mutate(facts()))
    s.ok("refused: %s" % label, msg is not None and msg.startswith(want), "got %r, want it to start with %r" % (msg, want))
    n_bad += 1
s.eq("a list is not facts", refused([]), "facts: expected an object, got a list")
s.eq("a mode of the wrong type", refused({"mode": 1}), "facts.mode: expected one of off, trial, got 1")
s.eq("facts with no mode", refused({}), "facts.mode: missing")
for name, ok_facts in (("an omitted previous_path and patch", facts()), ("an empty previous_path", put(facts(), "pr.changed_files.0.previous_path", "")),
                       ("a previous_path that is there", put(facts(), "pr.changed_files.0.previous_path", "old/list.py")),
                       ("no evidence at all, as {}", put(facts(), "evidence", {})), ("no assessment, as null", put(facts(), "agent", None)),
                       ("both known surfaces", put(facts(), "surfaces", ["ui", "security"])), ("a patch", put(facts(), "pr.changed_files.0.patch", "@@"))):
    s.eq("accepted: %s" % name, refused(ok_facts), None)

# ---- the table -------------------------------------------------------------------------------------------------------
tmp = helpers.mkdtemp("fwx-decide-")


def table_file(**over):
    data = dict({"disabled": [], "default_protected_paths": list(table.get("default_protected_paths", [])),
                 "rules": [{"id": r["id"], "outcome": r["outcome"]} for r in table["rules"]]}, **over)
    return helpers.write(tmp, "t%d.json" % len(os.listdir(tmp)), json.dumps(data))


def table_error(path):
    try:
        decide.load_table(path)
    except decide.TableError as e:
        return str(e)
    return None


s.eq("a table written like the real one loads", table_error(table_file()), None)
rows = [dict(r) for r in table["rules"]]
s.ok("a table without a rule the code has is refused, naming it",
     "conflict" in (table_error(table_file(rules=[r for r in rows if r["id"] != "conflict"])) or ""))
s.ok("a table with a rule the code does not have is refused, naming it",
     "made-up" in (table_error(table_file(rules=rows + [{"id": "made-up", "outcome": "handover"}])) or ""))
s.ok("a rule listed twice is refused", "twice" in (table_error(table_file(rules=rows + [rows[0]])) or ""))
s.ok("a disabled id that is no rule is refused, naming it", "made-up" in (table_error(table_file(disabled=["made-up"])) or ""))
s.ok("an outcome that is not handover or pending is refused", "outcome" in (table_error(table_file(rules=[dict(rows[0], outcome="merge")] + rows[1:])) or ""))
try:
    dis = decide.load_table(table_file(disabled=["conflict"]))
except decide.TableError as e:
    s.ok("a table with a rule in `disabled` loads", False, str(e))
    dis = table
got = D(CASES["conflict"](), dis)
s.eq("a rule in `disabled` of the file is not evaluated: its case would merge", (got["would_merge"], got["reasons"]), (True, []))
s.ok("a table with no default_protected_paths is refused, naming the key",
     "default_protected_paths" in (table_error(helpers.write(tmp, "nokey.json", json.dumps({"disabled": [], "rules": rows}))) or ""))
s.ok("default_protected_paths that is not a list of strings is refused, naming the key",
     "default_protected_paths" in (table_error(table_file(default_protected_paths=[3])) or "")
     and "default_protected_paths" in (table_error(table_file(default_protected_paths="drizzle/**")) or ""))
s.ok("a missing table file is an error that names the file", "no-such.json" in (table_error(os.path.join(tmp, "no-such.json")) or ""))

# ---- the module is pure code -------------------------------------------------------------------------------------------
NETWORK = {"socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib", "subprocess", "asyncio", "aiohttp"}


def imports_of(source):
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


s.eq("the checker sees a network import (control)", imports_of("import os\nfrom urllib import request\n") & NETWORK, {"urllib"})
for rel in ("lib/fwx/core/decide.py", "lib/fwx/commands/decide.py"):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        s.eq("%s imports no network or process library" % rel, imports_of(fh.read()) & NETWORK, set())

# ---- the command -------------------------------------------------------------------------------------------------------
repo = helpers.toy_repo()


def jload(text):
    """The JSON in text, or None when it is not JSON (a check then fails instead of the test crashing)."""
    try:
        return json.loads(text)
    except ValueError:
        return None


def run(f=None, *args, raw=None):
    if f is not None or raw is not None:
        path = helpers.write(tmp, "facts%d.json" % len(os.listdir(tmp)), raw if raw is not None else json.dumps(f))
        args = ("--facts", path) + args
    r = helpers.fwx(repo, "decide", *args)
    return r.returncode, r.stdout, r.stderr


code, out, err = run(facts())
s.eq("a PR that would merge: exit 0", code, 0)
s.eq("it prints one JSON object with the three keys", jload(out),
     {"decision": "handover", "would_merge": True, "reasons": []})
s.eq("and nothing on stderr", err, "")
code, out, err = run(edit(facts(), ".github/workflows/ci.yml"))
body = jload(out) or {"decision": None, "would_merge": None, "reasons": []}
s.eq("acceptance 3: a PR that edits .github/workflows/ci.yml: exit 0", code, 0)
s.eq("acceptance 3: handover, would_merge false", (body["decision"], body["would_merge"]), ("handover", False))
s.ok("acceptance 3: the first reason is `trusted-edit: ...` (then `protected-paths: ...`, for `.github/**`)",
     len(body["reasons"]) == 2 and body["reasons"][0].startswith("trusted-edit: ") and body["reasons"][1].startswith("protected-paths: "), repr(body))
code, out, err = run(put(facts(), "pr.running", True))
s.eq("a pending decision: exit 0 and `pending`", (code, (jload(out) or {}).get("decision")), (0, "pending"))
code, out, err = run({"mode": "off"})
s.eq("mode off through the command", (code, jload(out)), (0, off))
code, out, err = run(put(facts(), "pr.checks.0.state", "neutral"))
s.eq("a check in the state neutral: exit 2, nothing on stdout", (code, out), (2, ""))
s.ok("and the error names the path", "facts.pr.checks[0].state" in err, err)
code, out, err = run(put(facts(), "bogus", 1))
s.eq("an unknown field: exit 2, nothing on stdout", (code, out), (2, ""))
s.ok("and the error names it", "facts.bogus: unknown field" in err, err)
code, out, err = run(raw="{not json")
s.eq("a file that is not JSON: exit 2", (code, out), (2, ""))
s.ok("and the error says so", "not JSON" in err, err)
code, out, err = run(raw="[]")
s.eq("a JSON list: exit 2", (code, out), (2, ""))
s.eq("a file that is not there: exit 2", run(None, "--facts", os.path.join(tmp, "absent.json"))[0], 2)
s.eq("no --facts: exit 2", run()[0], 2)
s.eq("--facts with no file: exit 2", run(None, "--facts")[0], 2)
s.eq("an unknown option: exit 2", run(facts(), "--bogus")[0], 2)
s.eq("--facts twice: exit 2", run(facts(), "--facts", "x")[0], 2)

print("rules checked: %d" % checked)
if checked != 19:
    s.ok("the control loop checked the 19 rules", False, "checked %d" % checked)
s.done()
