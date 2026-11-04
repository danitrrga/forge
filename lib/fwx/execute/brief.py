"""The brief of an executor, one file per task (3.4 U9): the facts of a task, what is missing from them, and the text.

`task_facts` and `fix_facts` gather everything a brief says into one dict (`facts`); `missing(facts)` lists the fields that are
empty, which `prepare` turns into exit 2 ("a brief with an empty field is not launched"); `render(facts)` fills the slots of
data/executor-brief.md, whose nine fields come in the order of pstack's brief (orchestrate.md l.40-53). The text that is
the same for every task lives in that file; what varies is computed here, from the plan, the git state and the run.

Where a brief and the base-context file meet (2.5 U9): `shared_context(paths)` is the one place that names the files every
agent of the phase reads (`context.md`, `decisions.tsv`, `plan.md`). When the briefs rely on the base file, that function is
what changes; nothing else here spells those names, and the template does not.

A run's briefs live in `<git-common-dir>/fwx/runs/<run>/briefs/<task>.md` (written by `put`); the fixer's is `_fix.md`: no task
id can start with an underscore (`ID`), so the name cannot clash. What an agent writes is not there: its report and its TMPDIR
are in a folder of its own worktree that git ignores, made by `fwx wave scratch <run> <unit>` (execute/base.py), because Claude
Code asks permission for anything under `.git` and refuses an isolated agent's write outside its worktree. The brief does not
hold the base sha either: a later wave's worktrees start from the head after the earlier waves merged, so the workflow gives it
in the prompt when the wave launches.

Imports the standard library and fwx.plan (the fields of a plan's test).
"""
import os
import re
import string
from pathlib import Path

from fwx import plan

TEMPLATE = Path(__file__).resolve().parents[3] / "data" / "executor-brief.md"
STANDING = Path(__file__).resolve().parents[3] / "agents" / "executor.md"
FIELDS = ("GOAL", "SCOPE", "CONTEXT", "ACCEPTANCE", "VERIFY", "TIMEBOX", "FORBIDDEN", "REPORT", "STANDING")
# Minutes by size: a guide, seeded until 3.4 U0b measures real runs. Nothing can cut an agent off (the workflow has no timer).
TIMEBOX = {"small": 20, "normal": 40, "big": 60}
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")  # what may name a file: a task id, a finding id, a run
FIX = "_fix"
FIX_UNIT = "fix"  # the fixer's scratch folder and report: a task may be called `fix`, but never in the fixer's worktree
TESTS_OF_FINDINGS = "the test files that cover each finding, new or existing"
NO_TEST = "none: a UI task carries no test; the owner walks it"
SEVERITY = ("low", "medium", "high")
FINDING_KEYS = ("id", "file", "line", "claim", "evidence", "severity")


def shared_context(paths):
    """The lines of CONTEXT every agent of the phase gets: the files it reads. The seam 2.5 U9 moves."""
    return ["- %s: %s" % (name, paths[key]) for name, key in (("context.md", "context"), ("decisions.tsv", "decisions"), ("plan.md", "plan"))]


def folder_of(common, run):
    return os.path.join(common, "fwx", "runs", run)


def _context(paths, previous):
    return {"context": shared_context(paths) + (["- The report of the previous attempt, read it before anything else: %s" % previous] if previous else []),
            "context_files": [paths[k] for k in ("context", "decisions", "plan")] + ([previous] if previous else []),
            "previous": previous}


def _common(name, ident, part, ctx, size, files):
    folder = ctx["folder"]
    return dict({"name": name, "id": ident, "unit": FIX_UNIT if ident == FIX else ident, "part": part, "size": size, "run": ctx["run"],
                 "plan": ctx["paths"]["plan"], "files": list(files), "brief": os.path.join(folder, "briefs", ident + ".md")},
                **_context(ctx["paths"], ctx.get("previous")))


def task_facts(task, wave_tasks, ctx):
    """The facts of one task. `wave_tasks` are the tasks of its wave (those that run beside it); `ctx` is {run, part, paths:
    {context, decisions, plan}, folder, previous?}."""
    others = sorted({plan._norm(f) for t in wave_tasks if t["id"] != task["id"] for f in t["files"]} - {plan._norm(f) for f in task["files"]})
    facts = _common("task %s" % task["id"], task["id"], ctx["part"], ctx, task["size"], [plan._norm(f) for f in task["files"]])
    facts.update({"kind": "task", "type": task["type"], "wave": task["wave"], "ui": task["ui"], "others": others,
                  "tests": [dict(t) for t in task["tests"]], "trailers": ["Fwx-Task: %s/%s" % (ctx["part"], task["id"]), "Fwx-Run: %s" % ctx["run"]]})
    return facts


def fix_facts(findings, source, tasks, checks, size, ctx):
    """The facts of the fixer's task: every finding, in one brief. Its files are the findings' and the plan's."""
    files = sorted({plan._norm(f["file"]) for f in findings if isinstance(f.get("file"), str)})
    facts = _common("fix", FIX, ctx["part"], ctx, size, files + [TESTS_OF_FINDINGS])
    runs = []
    for t in tasks:
        runs += [x["run"] for x in t["tests"] if x["run"] not in runs]
    facts.update({"kind": "fix", "type": "bug", "wave": None, "ui": False, "others": [], "findings": findings, "source": source,
                  "tests": [{"run": c, "measures": None, "red": None} for c in list(checks) + [r for r in runs if r not in checks]],
                  "trailers": ["Fwx-Finding: <id>, the id of the one finding that commit fixes", "Fwx-Run: %s" % ctx["run"]]})
    facts["context"] += ["- The findings file: %s" % source] + [
        "- %s evidence: %s" % (f["id"], " ".join(str(f["evidence"]).split())) for f in findings]
    facts["context_files"].append(source)
    return facts


def _acceptance(facts):
    if facts["kind"] == "fix":
        return ["- %s (%s:%s, %s): %s" % (f["id"], f["file"], f["line"], f["severity"], " ".join(str(f["claim"]).split())) for f in facts["findings"]]
    return ["- %s" % " ".join(t["measures"].split()) for t in facts["tests"]]


def _verify(facts):
    if facts["kind"] == "fix":
        return ["- `%s`" % t["run"] for t in facts["tests"]]
    return ["- `%s`  (red, before the code: %s)" % (t["run"], " ".join(t["red"].split())) for t in facts["tests"]]


def missing(facts):
    """['task T2: SCOPE is empty', ...]: the fields a launch cannot do without. ACCEPTANCE and VERIFY are not needed by a UI task
    (it carries no test); a context file that is not there is a CONTEXT problem."""
    name, found = facts["name"], []
    if not facts["files"]:
        found.append("%s: SCOPE is empty" % name)
    if not facts["context"]:
        found.append("%s: CONTEXT is empty" % name)
    found += ["%s: CONTEXT names %s, which is not there" % (name, p) for p in facts["context_files"] if not os.path.exists(p)]
    if not facts["ui"]:
        if not _acceptance(facts):
            found.append("%s: ACCEPTANCE is empty" % name)
        if not _verify(facts):
            found.append("%s: VERIFY is empty" % name)
    return found


def _goal(facts):
    if facts["kind"] == "fix":
        return ("Fix the %d finding(s) listed in CONTEXT, one commit per finding. The part is %s; the plan is %s."
                % (len(facts["findings"]), facts["part"], facts["plan"]))
    return ("Do task %s (%s, %s, wave %d) of part %s. The files and the tests below are its definition; the plan that holds it is %s."
            % (facts["id"], facts["type"], facts["size"], facts["wave"], facts["part"], facts["plan"]))


def _template():
    with open(TEMPLATE, encoding="utf-8") as f:
        text = f.read()
    return text[text.index("\n# Brief") + 1:]


def render(facts):
    """The brief as text. Every slot of the template is filled and every value is used (string.Template raises on a slot that has
    none; the test fails on a value that no slot takes)."""
    slots = {
        "heading": "%s of %s, run %s" % (facts["name"], facts["part"], facts["run"]),
        "goal": _goal(facts),
        "files": "\n".join("- %s" % f for f in facts["files"]),
        "may_not": ", ".join(facts["others"]) if facts["others"] else "none (no other task runs with this one)",
        "run": facts["run"], "unit": facts["unit"], "trailers": "\n".join("- " + t for t in facts["trailers"]),
        "context": "\n".join(facts["context"]),
        "acceptance": "\n".join(_acceptance(facts)) or NO_TEST,
        "verify": "\n".join(_verify(facts)) or NO_TEST,
        "minutes": TIMEBOX[facts["size"]], "standing": str(STANDING),
    }
    return string.Template(_template()).substitute(slots)


def put(path, text):
    """Write a brief (the folder is made); an existing file is an error, since a run's brief is never rewritten."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        f.write(text)


def finding_problems(items):
    """What is wrong with a list of findings (plan C.5: {id, file, line, claim, evidence, severity}), one string per problem."""
    found, seen = [], set()
    for i, f in enumerate(items, 1):
        if not isinstance(f, dict):
            found.append("finding %d is not an object" % i)
            continue
        for k in sorted(set(f) - set(FINDING_KEYS)):
            found.append("finding %d has the key %r, which is not one of %s" % (i, k, ", ".join(FINDING_KEYS)))
        for k in ("id", "file", "claim", "evidence"):
            if not isinstance(f.get(k), str) or not f[k].strip():
                found.append("finding %d: %s is not a non-empty string" % (i, k))
        if not isinstance(f.get("line"), int) or isinstance(f.get("line"), bool) or f["line"] < 0:
            found.append("finding %d: line is not a number" % i)
        if f.get("severity") not in SEVERITY:
            found.append("finding %d: severity %r is not one of %s" % (i, f.get("severity"), ", ".join(SEVERITY)))
        if isinstance(f.get("id"), str) and f["id"].strip():
            if not ID.match(f["id"]):
                found.append("finding %d: the id %r cannot name a commit trailer or a file" % (i, f["id"]))
            elif f["id"] in seen:
                found.append("finding %d: the id %s is used twice" % (i, f["id"]))
            seen.add(f["id"])
    return found
