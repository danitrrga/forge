# copied-from: marshal-factory lib/merge-decision.ts @999ad209598517a4c826073b5a0edc2a4097a4fa, ported to Python (decideMerge:
# the reasons first, then waiting, then merge; the hard limits; the evidence reasons) on the `facts` of the framework's
# contract in place of GitHub's PR facts, with one rule per reason and a table that can release a rule.
"""The merge decision: from the facts of a PR, either the factory would merge it, or it goes to a person, naming the rule.

`decide(facts, table=None)` returns `{"decision": merge|handover|pending, "would_merge": bool, "reasons": [...]}`. Every
reason is `<rule id>: <text>`. The order is marshal's: when any rule gives a reason the decision is `handover`; else, when a
rule says something is still running, `pending`; else `merge`. A hard failure never waits. In `trial` the decision is never
`merge` (nobody merges on their own): a result of `merge` becomes `handover` with no reason and `would_merge` true, so
`would_merge` is what the result was. `mode: off` is `OFF_DECISION` (handover, no reason, nothing evaluated, and nothing but
the mode read). Anything but `off` and `trial` is an error: this part has no `auto`.

The rules are the table `decide_rules.json` (`rules`, in the order they are evaluated and their reasons listed, each with its
`outcome`: `handover` or `pending`; `disabled`, the ids that are not evaluated) and one function each in `CHECKS`. Letting a
rule go is one line in `disabled`. `load_table` refuses a table that lacks a rule the code has, has one it has not, lists one
twice or disables an unknown one, so a rule cannot vanish quietly from the file; `decide` evaluates the table it is given.

The 19 rules, in the order of the table. First, the 12 of marshal: `review-label` (the issue has the label `review`, in any case), `agent` (no assessment, or it recommends
handing over, or it is not confident), `ci-failed` (a check of `pr.checks` is `failure`), `conflict` (`pr.mergeable` is false),
`trusted-edit` (the PR edits what its checks run: `core.trusted`), `evidence-head` (no evidence, or evidence of another
commit), `evidence-dirty`, `evidence-recipe` (the evidence did not run the recipe, or ran other commands), `evidence-failed`,
`no-checks` (the effective recipe `project.checks` is empty), `review-findings` (`review.open_medium_high` above 0) and
`still-running` (`pr.running`, `review.running` or a check `pending`: `pending`, no handover). Then the 7 that U5b adds:

- `type`: the work is a `feature` or `structural` change.
- `ui`: `surfaces` has the mark `ui`. The rule reads no file name: the intake or the autonomous discuss marks the work by what
  it is (it changes what is seen or how the interface is used), so a `.tsx` fixed for a typo merges and a `.css` that
  restyles a screen, marked `ui`, goes to a person.
- `hooks-settings`: a file under `hooks/`, `.claude/hooks/`, `githooks/`, `.githooks/`, `.husky/`, or `.claude/settings*.json`,
  by `path` or `previous_path`.
- `protected-paths`: a file, by `path` or `previous_path`, that matches a glob of `project.protected_paths` or of the table's
  `default_protected_paths` (marshal's own list, `DEFAULT_PROTECTED_PATHS` of `ee22770^`).
- `irreversible`: `pr.base` is one of `production.branches`, or a line a patch adds has a command of `production.commands` in
  it (the command's words in order, split by any blanks, not inside a longer word or path). An entry `mcp__...` is a tool name
  of the consent window and is never looked for in a patch. A file with no patch (GitHub gives none for a large or binary
  file) cannot be shown safe, so it fires the rule too, naming the file ("no patch to inspect"): it fails closed. That holds
  while there is a command to look for; with none (or only `mcp__` names) a patch hides nothing.
- `outside-plan`: a changed file, by `path` only, that no glob of `plan_files` covers, except what is under `.fwx/`; an empty
  `plan_files` is a handover too, because nothing can be checked against it.
- `weakened-assertions`: in a test file (`TEST_FILES`, by `path` or `previous_path`), a patch that removes more assertion lines
  (`ASSERTION`) than it adds, or a test file with no patch to compare.

`major-bump` and `max-size`, which marshal had, are not rules here.

The checks of the facts are `success`, `failure` or `pending`, already translated from GitHub's conclusions by whoever makes
the facts (`neutral`, `skipped` and a skipped review are `pending`; `cancelled` and `timed_out` are `failure`). A state
outside the three is refused, so one of GitHub's raw conclusions can never be read as green. The facts are validated by hand,
`validate_facts`: an unknown field, a missing one or a wrong type is a `FactsError` that starts with the path of the field
(`facts.pr.checks[0].state: ...`). `pr.changed_files[].previous_path` and `patch` are optional (GitHub gives no patch for a
large or binary file; `trusted_edits` hands a package.json with none over). The facts are not changed.

Pure: no clock (the 60-minute wait of a `pending` is the caller's), no network, no process, no files but the table.
Imports `fwx.core.evidence`, `fwx.core.globs` and `fwx.core.trusted`, and from `fwx.state` only the constant `PLAN_DIR`.
"""
import json
import os
import re

from fwx import state
from fwx.core import evidence as evidence_mod
from fwx.core import globs, trusted

TABLE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "decide_rules.json")
MODES = ("off", "trial")
TYPES = ("bug", "refactor", "feature", "structural", "chore")
RISKS = ("low", "medium", "high")
SURFACES = ("ui", "security")
RECOMMENDATIONS = ("merge", "handover")
CHECK_STATES = ("success", "failure", "pending")
OUTCOMES = ("handover", "pending")
REVIEW_LABEL = "review"
MAX_NAMED = 5
ASKED_TYPES = ("feature", "structural")
# Hooks and settings, by glob; a row is one more place whose edit a person looks at.
HOOKS_SETTINGS = ["hooks/**", ".claude/settings*.json", ".claude/hooks/**", "githooks/**", ".githooks/**", ".husky/**"]
# What makes a file a test file, by glob; a new convention is a new row.
TEST_FILES = ["**/test/**", "**/tests/**", "**/__tests__/**", "**/spec/**", "**/specs/**", "**/test_*", "**/*_test.*",
              "**/*.test.*", "**/*.spec.*", "**/*_spec.*"]
# What makes a line an assertion: assert and its relatives (unittest, testify, Rust), `expect(` (jest), `raises(` (pytest),
# `.should` (chai), `t.Error`/`t.Fatal` (Go), and `.eq(` / `.ok(` (this repo's own tests/helpers.py Suite). A new framework is a
# new alternative.
ASSERTION = re.compile(r"\bassert\w*|\bexpect\s*\(|\braises\s*\(|\.should\b|\bt\.(?:Error|Fatal)f?\(|\.(?:eq|ok)\(")
_PATCH_HEADER = re.compile(r"(?:---|\+\+\+) (?:a/|b/|/dev/null)")
OFF_DECISION = {"decision": "handover", "would_merge": False, "reasons": []}


class FactsError(ValueError):
    """The facts are not the contract's; the message starts with the path of the field."""


class TableError(ValueError):
    """The rule table cannot be used."""


# ---- the validator -----------------------------------------------------------------------------------------------------

def _kind(v):
    return {dict: "an object", list: "a list", str: "a string", bool: "a boolean", int: "an integer",
            float: "a number", type(None): "null"}.get(type(v), type(v).__name__)


def _fail(path, message):
    raise FactsError("%s: %s" % (path, message))


def _object(v, path, required, optional=()):
    if not isinstance(v, dict):
        _fail(path, "expected an object, got %s" % _kind(v))
    for key in v:
        if key not in required and key not in optional:
            _fail("%s.%s" % (path, key), "unknown field")
    for key in required:
        if key not in v:
            _fail("%s.%s" % (path, key), "missing")
    return v


def _string(v, path, non_empty=False):
    if not isinstance(v, str):
        _fail(path, "expected a string, got %s" % _kind(v))
    if non_empty and not v:
        _fail(path, "expected a non-empty string, got an empty one")


def _boolean(v, path):
    if not isinstance(v, bool):
        _fail(path, "expected true or false, got %s" % _kind(v))


def _integer(v, path, non_negative=True):
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(path, "expected %s, got %s" % ("a non-negative integer" if non_negative else "an integer", _kind(v)))
    if non_negative and v < 0:
        _fail(path, "expected a non-negative integer, got %d" % v)


def _enum(v, path, values):
    if not isinstance(v, str) or v not in values:
        _fail(path, "expected one of %s, got %r" % (", ".join(values), v))


def _list(v, path, each):
    if not isinstance(v, list):
        _fail(path, "expected a list, got %s" % _kind(v))
    for i, item in enumerate(v):
        each(item, "%s[%d]" % (path, i))


def _check(v, path):
    if isinstance(v, str):
        return
    if isinstance(v, dict) and isinstance(v.get("command"), str):
        return
    _fail(path, "expected a command or an object with a command, got %s" % _kind(v))


def _changed_file(v, path):
    _object(v, path, ("path", "additions", "deletions"), ("previous_path", "patch"))
    _string(v["path"], path + ".path", non_empty=True)
    _integer(v["additions"], path + ".additions")
    _integer(v["deletions"], path + ".deletions")
    for key in ("previous_path", "patch"):
        if key in v:
            _string(v[key], "%s.%s" % (path, key))


def _pr_check(v, path):
    _object(v, path, ("name", "state"))
    _string(v["name"], path + ".name")
    _enum(v["state"], path + ".state", CHECK_STATES)


def _command(v, path):
    _object(v, path, ("cmd", "rc"))
    _string(v["cmd"], path + ".cmd")
    if v["rc"] is not None and (isinstance(v["rc"], bool) or not isinstance(v["rc"], int)):
        _fail(path + ".rc", "expected an integer or null, got %s" % _kind(v["rc"]))


def validate_facts(facts):
    """Raise FactsError, naming the path, unless `facts` is the contract's (the mode `trial`; `off` is checked by `decide`)."""
    if not isinstance(facts, dict):
        _fail("facts", "expected an object, got %s" % _kind(facts))
    if "mode" not in facts:
        _fail("facts.mode", "missing")
    _enum(facts["mode"], "facts.mode", MODES)
    f = _object(facts, "facts", ("mode", "labels", "type", "risk", "surfaces", "agent", "pr", "evidence", "plan_files",
                                 "review", "project"))
    _list(f["labels"], "facts.labels", lambda v, p: _string(v, p))
    _enum(f["type"], "facts.type", TYPES)
    _enum(f["risk"], "facts.risk", RISKS)
    _list(f["surfaces"], "facts.surfaces", lambda v, p: _enum(v, p, SURFACES))
    if f["agent"] is not None:
        agent = _object(f["agent"], "facts.agent", ("recommendation", "confident", "assumptions"))
        _enum(agent["recommendation"], "facts.agent.recommendation", RECOMMENDATIONS)
        _boolean(agent["confident"], "facts.agent.confident")
        _list(agent["assumptions"], "facts.agent.assumptions", lambda v, p: _string(v, p))
    pr = _object(f["pr"], "facts.pr", ("number", "head_sha", "base", "mergeable", "running", "changed_files", "checks"))
    _integer(pr["number"], "facts.pr.number")
    _string(pr["head_sha"], "facts.pr.head_sha", non_empty=True)
    _string(pr["base"], "facts.pr.base")
    _boolean(pr["mergeable"], "facts.pr.mergeable")
    _boolean(pr["running"], "facts.pr.running")
    _list(pr["changed_files"], "facts.pr.changed_files", _changed_file)
    _list(pr["checks"], "facts.pr.checks", _pr_check)
    ev = f["evidence"]
    if not isinstance(ev, dict):
        _fail("facts.evidence", "expected an object, got %s" % _kind(ev))
    if ev:  # {} is no evidence; `fwx verify --json` also gives `source` and `rc`
        _object(ev, "facts.evidence", ("sha", "clean", "commands"), ("source", "rc"))
        _string(ev["sha"], "facts.evidence.sha")
        _boolean(ev["clean"], "facts.evidence.clean")
        _list(ev["commands"], "facts.evidence.commands", _command)
        if "source" in ev:
            _string(ev["source"], "facts.evidence.source")
        if "rc" in ev:
            _integer(ev["rc"], "facts.evidence.rc", non_negative=False)
    _list(f["plan_files"], "facts.plan_files", lambda v, p: _string(v, p))
    review = _object(f["review"], "facts.review", ("open_medium_high", "running"))
    _integer(review["open_medium_high"], "facts.review.open_medium_high")
    _boolean(review["running"], "facts.review.running")
    project = _object(f["project"], "facts.project", ("checks", "protected_paths", "production", "ui_bugs"))
    _list(project["checks"], "facts.project.checks", _check)
    _list(project["protected_paths"], "facts.project.protected_paths", lambda v, p: _string(v, p))
    production = _object(project["production"], "facts.project.production", ("branches", "commands"))
    _list(production["branches"], "facts.project.production.branches", lambda v, p: _string(v, p))
    _list(production["commands"], "facts.project.production.commands", lambda v, p: _string(v, p))
    _boolean(project["ui_bugs"], "facts.project.ui_bugs")


# ---- the rules: each takes validated facts and returns the texts of its reasons ----------------------------------------------

def _short(sha):
    return sha[:7]


def _evidence(f):
    return evidence_mod.evidence_state(f["evidence"], f["pr"]["head_sha"], f["project"]["checks"])


def _cut(names):
    """The first MAX_NAMED names, with `...` when there are more."""
    return ", ".join(names[:MAX_NAMED]) + (", ..." if len(names) > MAX_NAMED else "")


def _touched(f):
    """Every path the PR touches, the new name and the previous one of a rename, once each, in order."""
    seen = []
    for c in f["pr"]["changed_files"]:
        for p in (c["path"], c.get("previous_path")):
            if p and p not in seen:
                seen.append(p)
    return seen


def _patch_lines(patch):
    """(sign, text) of each line a patch adds or removes; the `--- a/x` and `+++ b/x` headers and the context are no line."""
    for line in patch.split("\n"):
        if line[:1] in ("+", "-") and not _PATCH_HEADER.match(line):
            yield line[0], line[1:]


def _review_label(f, table):
    if any(label.lower() == REVIEW_LABEL for label in f["labels"]):
        return ['the issue has the "%s" label, so a person always sees the merge' % REVIEW_LABEL]
    return []


def _agent(f, table):
    agent = f["agent"]
    if agent is None:
        return ["the agent reported no assessment"]
    said = (["recommends handing over"] if agent["recommendation"] != "merge" else []) + \
           (["is not confident"] if not agent["confident"] else [])
    return ["the agent %s" % " and ".join(said)] if said else []


def _ci_failed(f, table):
    red = [c["name"] for c in f["pr"]["checks"] if c["state"] == "failure"]
    return ["a check failed on the latest commit: %s" % ", ".join(red)] if red else []


def _conflict(f, table):
    if f["pr"]["mergeable"]:
        return []
    return ["the pull request conflicts with its base branch (%s)" % f["pr"]["base"]]


def _trusted_edit(f, table):
    return trusted.trusted_edits(f["pr"]["changed_files"], f["project"]["checks"])


def _evidence_head(f, table):
    state, head = _evidence(f), _short(f["pr"]["head_sha"])
    if state["state"] == "missing":
        return ["no checks were run for %s" % head]
    if state["state"] == "stale":
        return ["the latest checks ran at %s, not at %s" % (_short(state["sha"]), head)]
    return []


def _evidence_dirty(f, table):
    state = _evidence(f)
    if state["state"] == "dirty":
        return ["the checks ran at %s on a tree with uncommitted changes" % _short(state["sha"])]
    return []


def _evidence_recipe(f, table):
    state = _evidence(f)
    if state["state"] == "incomplete":
        return ["the checks at %s didn't run %s" % (_short(state["sha"]), ", ".join(state["missing"]))]
    if state["state"] == "untrusted":
        return ["the checks at %s ran other commands than the recipe's (%s) and left out %s" % (
            _short(state["sha"]), ", ".join(state["mismatched"]), ", ".join(state["missing"]))]
    return []


def _evidence_failed(f, table):
    state = _evidence(f)
    if state["state"] == "failed":
        return ["checks failed at %s: %s" % (_short(state["sha"]), ", ".join(state["failed"]))]
    return []


def _no_checks(f, table):
    return ["no checks are defined for this repo"] if _evidence(f)["state"] == "no_checks" else []


def _review_findings(f, table):
    n = f["review"]["open_medium_high"]
    return ["the review has %d unresolved medium or high finding%s" % (n, "" if n == 1 else "s")] if n > 0 else []


def _still_running(f, table):
    waiting = []
    pending = [c["name"] for c in f["pr"]["checks"] if c["state"] == "pending"]
    if pending:
        waiting.append("checks (%s)" % ", ".join(pending))
    if f["review"]["running"]:
        waiting.append("the review")
    if f["pr"]["running"]:
        waiting.append("GitHub")
    return ["waiting for %s" % ", ".join(waiting)] if waiting else []


def _type(f, table):
    if f["type"] in ASKED_TYPES:
        return ["the work is a %s change, so a person decides" % f["type"]]
    return []


def _ui(f, table):
    if "ui" in f["surfaces"]:
        return ["the work changes what is seen or how the interface is used, so a person sees it"]
    return []


def _hooks_settings(f, table):
    hit = [p for p in _touched(f) if globs.matches_any(p, HOOKS_SETTINGS)]
    return ["it edits hooks or settings: %s" % _cut(hit)] if hit else []


def _protected_paths(f, table):
    protected = list(table["default_protected_paths"]) + f["project"]["protected_paths"]
    hit = [p for p in _touched(f) if globs.matches_any(p, protected)]
    return ["it touches protected paths: %s" % _cut(hit)] if hit else []


def _production_pattern(command):
    """The pattern of a command's words, in order, split by any blanks; not inside a longer word or path before it, and when
    it ends in a word character, not at the start of a longer one."""
    words = command.split()
    tail = r"(?![\w-])" if re.match(r"\w", words[-1][-1]) else ""
    return re.compile(r"(?<![\w./-])" + r"\s+".join(re.escape(w) for w in words) + tail)


def _irreversible(f, table):
    production = f["project"]["production"]
    reasons = []
    base = f["pr"]["base"]
    if base and base in production["branches"]:
        reasons.append("the pull request is for %s, a production branch" % base)
    patterns = [(c.strip(), _production_pattern(c)) for c in production["commands"]
                if c.strip() and not c.strip().startswith("mcp__")]
    found, blind = [], []
    for c in f["pr"]["changed_files"]:
        if patterns and not c.get("patch"):
            blind.append(c["path"])
            continue
        for sign, text in _patch_lines(c.get("patch") or ""):
            if sign != "+":
                continue
            for command, pattern in patterns:
                hit = "%s (%s)" % (command, c["path"])
                if pattern.search(text) and hit not in found:
                    found.append(hit)
    if found:
        reasons.append("it adds a production command: %s" % _cut(found))
    if blind:
        reasons.append("no patch to inspect for a production command in: %s" % _cut(blind))
    return reasons


def _outside_plan(f, table):
    plan = f["plan_files"]
    if not plan:
        return ["the plan names no files, so nothing can be checked against it and a person looks"]
    outside = []
    for c in f["pr"]["changed_files"]:
        p = c["path"]
        if p.startswith(state.PLAN_DIR + "/") or globs.matches_any(p, plan) or p in outside:
            continue
        outside.append(p)
    return ["it changes files outside the plan: %s" % _cut(outside)] if outside else []


def _weakened_assertions(f, table):
    weakened, blind = [], []
    for c in f["pr"]["changed_files"]:
        if not any(globs.matches_any(p, TEST_FILES) for p in (c["path"], c.get("previous_path") or "")):
            continue
        if not c.get("patch"):
            blind.append(c["path"])
            continue
        count = {"+": 0, "-": 0}
        for sign, text in _patch_lines(c["patch"]):
            if ASSERTION.search(text):
                count[sign] += 1
        if count["-"] > count["+"]:
            weakened.append("%s (-%d +%d)" % (c["path"], count["-"], count["+"]))
    reasons = []
    if weakened:
        reasons.append("it removes more assertion lines than it adds in tests: %s" % _cut(weakened))
    if blind:
        reasons.append("it changes test files with no patch to compare: %s" % _cut(blind))
    return reasons


CHECKS = {
    "review-label": _review_label,
    "agent": _agent,
    "type": _type,
    "ui": _ui,
    "ci-failed": _ci_failed,
    "conflict": _conflict,
    "trusted-edit": _trusted_edit,
    "hooks-settings": _hooks_settings,
    "protected-paths": _protected_paths,
    "irreversible": _irreversible,
    "outside-plan": _outside_plan,
    "weakened-assertions": _weakened_assertions,
    "evidence-head": _evidence_head,
    "evidence-dirty": _evidence_dirty,
    "evidence-recipe": _evidence_recipe,
    "evidence-failed": _evidence_failed,
    "no-checks": _no_checks,
    "review-findings": _review_findings,
    "still-running": _still_running,
}


# ---- the table and the decision ------------------------------------------------------------------------------------------

def load_table(path=TABLE):
    """The rule table at `path`, checked against the rules the code has; TableError when it cannot be used."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        raise TableError("cannot read the rule table %s: %s" % (path, e.strerror or e))
    except ValueError as e:
        raise TableError("the rule table %s is not JSON: %s" % (path, e))
    if not isinstance(data, dict) or set(data) != {"rules", "disabled", "default_protected_paths"} \
            or not isinstance(data["rules"], list) or not isinstance(data["disabled"], list):
        raise TableError("the rule table %s is {\"rules\": [...], \"disabled\": [...], \"default_protected_paths\": [...]}" % path)
    defaults = data["default_protected_paths"]
    if not isinstance(defaults, list) or not all(isinstance(g, str) and g for g in defaults):
        raise TableError("default_protected_paths of %s is a list of globs, got %r" % (path, defaults))
    seen = []
    for row in data["rules"]:
        if not isinstance(row, dict) or set(row) != {"id", "outcome"} or not isinstance(row["id"], str):
            raise TableError("a rule of %s is {\"id\": ..., \"outcome\": ...}, got %r" % (path, row))
        if row["outcome"] not in OUTCOMES:
            raise TableError("rule %s: outcome is one of %s, got %r" % (row["id"], ", ".join(OUTCOMES), row["outcome"]))
        if row["id"] in seen:
            raise TableError("rule %s is listed twice in %s" % (row["id"], path))
        seen.append(row["id"])
    missing = [r for r in CHECKS if r not in seen]
    unknown = [r for r in seen if r not in CHECKS]
    if missing:
        raise TableError("%s has no row for the rule(s) %s (to let one go, put it in disabled)" % (path, ", ".join(missing)))
    if unknown:
        raise TableError("%s has rule(s) the code does not have: %s" % (path, ", ".join(unknown)))
    for rid in data["disabled"]:
        if rid not in CHECKS:
            raise TableError("%s disables %r, which is no rule" % (path, rid))
    return data


def decide(facts, table=None):
    """{decision, would_merge, reasons} for the facts, by the table (the engine's own when None)."""
    mode = facts.get("mode") if isinstance(facts, dict) else None
    if mode == "off":
        return dict(OFF_DECISION, reasons=[])
    validate_facts(facts)
    table = load_table() if table is None else table
    disabled = set(table["disabled"])
    reasons, waiting = [], []
    for rule in table["rules"]:
        if rule["id"] in disabled:
            continue
        found = ["%s: %s" % (rule["id"], text) for text in CHECKS[rule["id"]](facts, table)]
        (reasons if rule["outcome"] == "handover" else waiting).extend(found)
    if reasons:
        return {"decision": "handover", "would_merge": False, "reasons": reasons}
    if waiting:
        return {"decision": "pending", "would_merge": False, "reasons": waiting}
    # the result is merge; in trial nobody merges on their own, so it is a handover that remembers what it would have done
    return {"decision": "handover", "would_merge": True, "reasons": []}
