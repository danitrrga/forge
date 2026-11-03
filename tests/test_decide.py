#!/usr/bin/env python3
"""core.decide and `fwx decide --facts FILE`: the merge decision, from the facts of a PR.

Ports the decideMerge cases of marshal's merge-decision-regressions.ts (:83-266) that are not about Bugbot, the old
assessment format, the runner or the clock, on the `facts` of the contract: everything holds (trial: handover, would_merge
true), off evaluates nothing, no assessment, an unsure agent, the review label in any case, a red check, a conflict, an open
finding, a 303-line PR, a migration and a major bump (no rule of fwx catches those), running checks, a hard failure that does
not wait, the evidence states (no checks, failed, missing, stale, dirty, incomplete, untrusted), a PR that edits what its
checks run, and a repo with no CI whose own evidence stands in for it. What is not ported, and why: the runner's states
(5.2 runs `fwx verify` before it decides), the 60-minute wait (the caller has the clock), GitHub's `unknown` mergeability
(the producer of the facts says `running`), Bugbot (the facts carry `review`), the screenshots rule (`ui` is U5b's).

This unit builds 12 rules; U5b adds the other 7 (19 in all). The control loop is the plan's: for each rule, a case that
only it catches. With the table the rule hands the case over (or waits, for `still-running`) with a reason that starts with
its id and nothing else, and with the rule in `disabled` the same case would merge. The loop is a function that returns what
is wrong, and it is run again on a table without the rule and must say so: a rule deleted from the table is a failure of
this file. The file prints how many rules it checked and fails on any number but 12.

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
(207 checks on the good code.)
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

EXPECTED = ["review-label", "agent", "ci-failed", "conflict", "trusted-edit", "evidence-head", "evidence-dirty",
            "evidence-recipe", "evidence-failed", "no-checks", "review-findings", "still-running"]
PENDING = {"still-running"}
HEAD = "a" * 40
OTHER = "b" * 40
RECIPE = "python3 bin/fwx test"


def facts():
    """A PR that would merge: a plain edit, a green check, the evidence at the head for the whole recipe, a confident agent."""
    return {
        "mode": "trial", "labels": ["factory"], "type": "bug", "risk": "low", "surfaces": [],
        "agent": {"recommendation": "merge", "confident": True, "assumptions": ["sorted by name"]},
        "pr": {"number": 7, "head_sha": HEAD, "base": "factory", "mergeable": True, "running": False,
               "changed_files": [{"path": "src/list.py", "additions": 10, "deletions": 2}],
               "checks": [{"name": "ci", "state": "success"}]},
        "evidence": {"sha": HEAD, "clean": True, "commands": [{"cmd": RECIPE, "rc": 0}]},
        "plan_files": ["src/**"], "review": {"open_medium_high": 0, "running": False},
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


CASES = {
    "review-label": lambda: put(facts(), "labels", ["factory", "Review"]),
    "agent": lambda: put(facts(), "agent", None),
    "ci-failed": lambda: put(facts(), "pr.checks", [{"name": "ci", "state": "failure"}]),
    "conflict": lambda: put(facts(), "pr.mergeable", False),
    "trusted-edit": lambda: edit(facts(), ".github/workflows/ci.yml"),
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
s.eq("the table of the engine lists the 12 rules of this unit, in this order", ids, EXPECTED)
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
s.eq("a confident additive change the issue asked for merges", D(put(facts(), "type", "feature"))["would_merge"], True)
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

# size, migrations and major bumps are not rules of fwx (major-bump and max-size were dropped), and a manifest edit that
# only bumps a dependency is not an edit of what the checks run
f = facts()
put(f, "pr.changed_files", [{"path": "a.py", "additions": 200, "deletions": 103}])
s.eq("a 303-line pull request merges", D(f)["would_merge"], True)
f = put(facts(), "pr.changed_files", [{"path": "drizzle/0001.sql", "additions": 1, "deletions": 0}])
s.eq("a migration merges (no protected path in this unit)", D(f)["would_merge"], True)
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
only(edit(facts(), ".github/workflows/ci.yml"), "trusted-edit", "a workflow edit hands over despite verified evidence")
only(edit(facts(), ".claude/fwx.json"), "trusted-edit", "an edit of the recipe")
f = edit(facts(), "scripts/old/ci.yml", previous_path=".github/workflows/ci.yml")
only(f, "trusted-edit", "a rename out of the workflows directory counts through previous_path")
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
    data = dict({"disabled": [], "rules": [{"id": r["id"], "outcome": r["outcome"]} for r in table["rules"]]}, **over)
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
dis = decide.load_table(table_file(disabled=["conflict"]))
got = D(CASES["conflict"](), dis)
s.eq("a rule in `disabled` of the file is not evaluated: its case would merge", (got["would_merge"], got["reasons"]), (True, []))
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
s.ok("acceptance 3: the reason is `trusted-edit: ...`", len(body["reasons"]) == 1 and "".join(body["reasons"]).startswith("trusted-edit: "), repr(body))
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
if checked != 12:
    s.ok("the control loop checked the 12 rules of this unit", False, "checked %d" % checked)
s.done()
