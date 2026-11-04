#!/usr/bin/env python3
r"""The executor's brief and `fwx wave prepare` refusing to launch what is not delimited (3.4 U9):
lib/fwx/execute/brief.py, data/executor-brief.md, lib/fwx/execute/prepare.py.

Builds on the toy world of tests/test_wave_prepare.py (its Scene, its runner, its mutant_tree): a toy repo with a linked
worktree on the phase branch, run through `bin/fwx`. Cases that need a brief the command cannot reach (a task with no
files: `load_plan` refuses it first) call lib/fwx/execute/brief.py in a child python on the tree under test.

Seen red before the code existed (python3 tests/test_wave_brief.py, `brief` was null in every task and `prepare` wrote nothing):
  FAIL: briefs: T1 brief is a path: got None, want a string
  FAIL: briefs: the second prepare is a new run, the first one's briefs stay: got '01-alpha-9c3a042-1', want '01-alpha-9c3a042-2'
  FAIL: refused: a feature task with no tests: exit: got 0, want 2
  FAIL: ui: the brief says a UI task carries no test: ACCEPTANCE '' VERIFY ''
  FAIL: module: the empty SCOPE is named (prepare exit 0 with an empty SCOPE): None   (cannot import name 'brief' from 'fwx.execute')
  FAIL: fix: fix.brief is a file: None

Red before the 3.4 U8 fix (the brief held the prepare-time sha, wrong for every later wave, and a report path under `.git`):
  FAIL: briefs: the base is the prompt's BASE line, and no sha is in the brief (a later wave starts from a later head: 3.4 U8 fix, F1): ...
  FAIL: briefs: SCOPE gives the scratch folder (`fwx wave scratch <run> T1`) for TMPDIR, in the worktree and not under .git (3.4 U8 fix, F2): ...
  FAIL: briefs: REPORT names report.json in the scratch folder, the fields and the one-line reply: Write it as JSON to <repo>/.git/fwx/runs/01-alpha-97f1a0d-1/reports/T1.json, with Bash (a heredoc)...

Controls: each case also runs on a copy of bin/, lib/, data/ and templates/ with one line of the code changed (`MUTANTS`, each
line in its file exactly once), and must fail with the text in `MUTANTS`; the good code passes first. The first FAIL line of each,
seen red:
  SCOPE not checked:                      FAIL: module: the empty SCOPE is named (prepare exit 0 with an empty SCOPE): []
  UI task refused:                        FAIL: ui: a UI task with no tests: exit (ui task refused): got 2, want 0
  empty fields not refused:               FAIL: refused: a feature task with no tests: exit: got 0, want 2
  context file not looked for:            FAIL: refused: a CONTEXT file that is not there: exit: got 0, want 2
  briefs written before the base is run:  FAIL: refused: a red base writes no brief
  task id not checked:                    FAIL: refused: a task id that cannot name a file: exit: got 0, want 2
  fields out of order:                    FAIL: briefs: the nine fields in the order of the template: got ['GOAL', 'SCOPE', 'CONTEXT', 'VERIFY', 'ACCEPT
  trailers dropped:                       FAIL: briefs: SCOPE lists its file, the run and both trailers: You may write only these files, in y
  big task at 40 minutes:                 FAIL: briefs: T2 TIMEBOX is 60 minutes: 40 minutes: a guide, since nothing cuts an agent off; on expiry, retur
  every wave runs beside it:              FAIL: briefs: SCOPE says nothing of wave 2's files (they run later): You may write only these files, in your o
  no referent in the header:              FAIL: template: the header names its referent (orchestrate.md @36885ea): <!-- copied-from: none plugins/pstack
  shared file named in the template:      FAIL: template: it does not spell the shared files (one place assembles them, 2.5 U9): <!-- copied-from: pstac
  UI task without its sentence:           FAIL: ui: the brief says a UI task carries no test: ACCEPTANCE 'none\n\n' VERIFY 'none\n\n'
  previous report left out:               FAIL: module: a relaunch puts the previous report in CONTEXT: rc 0, CONTEXT '- context.md: /tmp/tmp7e20r4ij/co
  severity not checked:                   FAIL: fix: a severity that is not low, medium or high: exit: got 0, want 2
  a repeated finding id allowed:          FAIL: fix: a repeated id in --control-findings: exit: got 0, want 2
  the plan's tasks briefed under --fix:   FAIL: fix: fix.brief is a file: None
  revert ids not checked:                 FAIL: revert: an id with a space: exit: got 0, want 2
  revert launches:                        FAIL: revert: nothing is launched, so no brief is written: {'T1': {'id': 'T1', 'type': 'feature', 'size': 'sma
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
import test_wave_prepare as wp  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
FIELDS = ["GOAL", "SCOPE", "CONTEXT", "ACCEPTANCE", "VERIFY", "TIMEBOX", "FORBIDDEN", "REPORT", "STANDING"]
PHASE = wp.PHASE
FINDING = {"id": "F1", "file": "src/a.py", "line": 3, "claim": "a is wrong", "evidence": "line 3 prints it", "severity": "medium"}


def common_dir(repo):
    return os.path.realpath(helpers.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())


def runs_dir(sc):
    return os.path.join(common_dir(sc.repo), "fwx", "runs")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def sections(text):
    """{FIELD: its text} of a brief and the order the fields come in."""
    found = list(re.finditer(r"^## ([A-Z]+)\n", text, re.M))
    out = {}
    for i, m in enumerate(found):
        out[m.group(1)] = text[m.end():found[i + 1].start() if i + 1 < len(found) else len(text)]
    return out, [m.group(1) for m in found]


def tasks_of(a):
    return {t["id"]: t for w in a.get("waves") or [] for t in w["tasks"]}


def brief_of(S, label, a, tid):
    path = tasks_of(a).get(tid, {}).get("brief")
    if not S.ok("%s: %s brief is a path" % (label, tid), isinstance(path, str) and os.path.isabs(path), "got %r, want a string" % path):
        return "", {}
    if not S.ok("%s: %s brief is a file" % (label, tid), os.path.isfile(path), "no file at %s" % path):
        return "", {}
    text = read(path)
    return text, sections(text)[0]


def child(root, code):
    """(exit, stdout, stderr) of python on the tree `root`, with its lib/ on the path; `code` prints JSON."""
    r = subprocess.run([sys.executable, "-c", code], env=helpers.clean_env(PYTHONPATH=os.path.join(root, "lib")),
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def module_facts(extra=""):
    """Python source that makes `facts`, a valid task's facts over files that exist, then runs `extra`."""
    return ("import json, os\n"
            "from fwx.execute import brief\n"
            "d = %r\n" % helpers.mkdtemp("fwx-facts-") +
            "paths = {k: os.path.join(d, k + '.x') for k in ('context', 'decisions', 'plan')}\n"
            "for p in paths.values(): open(p, 'w').write('x')\n"
            "task = {'id': 'T2', 'type': 'feature', 'size': 'normal', 'ui': False, 'wave': 1, 'files': ['src/a.py'],\n"
            "        'tests': [{'run': 'python3 t.py', 'measures': 'm', 'red': 'r'}]}\n"
            "ctx = {'run': 'r-1', 'base': 'a' * 40, 'part': '01-alpha', 'paths': paths, 'folder': os.path.join(d, 'run')}\n"
            "facts = brief.task_facts(task, [task], ctx)\n" + extra)


# ---------------------------------------------------------------------------------------------------- the cases

def case_briefs(R, S):
    sc = wp.Scene(tasks=[wp.task("T1", 1, ["src/a.py"]), wp.task("T2", 1, ["src/b.py"], size="big"), wp.task("T3", 2, ["README"], size="normal")])
    a = wp.ok_args(S, "briefs", sc.prepare(R))
    run, base = a.get("run", ""), sc.head()
    folder = os.path.join(common_dir(sc.repo), "fwx", "runs", run)
    t1, f1 = brief_of(S, "briefs", a, "T1")
    S.eq("briefs: T1 brief lives in the run's briefs folder", tasks_of(a).get("T1", {}).get("brief"), os.path.join(folder, "briefs", "T1.md"))
    S.eq("briefs: one file per task, nothing else", sorted(os.listdir(os.path.join(folder, "briefs"))) if os.path.isdir(folder) else None,
         ["T1.md", "T2.md", "T3.md"])
    _, order = sections(t1)
    S.eq("briefs: the nine fields in the order of the template", order, FIELDS)
    S.ok("briefs: GOAL names the task, the part and the path of plan.md",
         "T1" in f1.get("GOAL", "") and sc.name in f1.get("GOAL", "") and os.path.join(sc.part, "plan.md") in f1.get("GOAL", ""), f1.get("GOAL", "")[:200])
    scope = f1.get("SCOPE", "")
    S.ok("briefs: SCOPE lists its file, the run and both trailers",
         "src/a.py" in scope and run in scope and "Fwx-Task: %s/T1" % PHASE in scope and "Fwx-Run: %s" % run in scope, scope)
    S.ok("briefs: the base is the prompt's BASE line, and no sha is in the brief (a later wave starts from a later head: 3.4 U8 fix, F1)",
         "`BASE` line of your prompt" in scope and "fwx wave check-base" in scope and not re.search(r"\b[0-9a-f]{40}\b", t1) and base not in t1, scope)
    S.ok("briefs: SCOPE names the other task of the wave, as a path it may not write", "src/b.py" in scope and "may not" in scope.lower(), scope)
    S.ok("briefs: SCOPE says nothing of wave 2's files (they run later)", "README" not in scope, scope)
    S.ok("briefs: SCOPE gives the scratch folder (`fwx wave scratch <run> T1`) for TMPDIR, in the worktree and not under .git (3.4 U8 fix, F2)",
         "fwx wave scratch %s T1" % run in scope and "`tmp/` inside it" in scope and "TMPDIR" in scope and ".git/" not in t1 and os.path.join(folder, "tmp") not in t1, scope)
    ctx = f1.get("CONTEXT", "")
    for name in ("context.md", "decisions.tsv", "plan.md"):
        S.ok("briefs: CONTEXT has the absolute path of %s" % name,
             any(os.path.isabs(w) and w.endswith("/" + name) and os.path.exists(w) for w in re.findall(r"/\S+", ctx)), ctx)
    S.ok("briefs: ACCEPTANCE is the measures line", "- m\n" in f1.get("ACCEPTANCE", "") + "\n", f1.get("ACCEPTANCE", ""))
    S.ok("briefs: VERIFY has the command and its red", "python3 t.py" in f1.get("VERIFY", "") and "r" in f1.get("VERIFY", ""), f1.get("VERIFY", ""))
    for tid, minutes in (("T1", 20), ("T3", 40), ("T2", 60)):
        text, f = brief_of(S, "briefs", a, tid)
        S.ok("briefs: %s TIMEBOX is %d minutes" % (tid, minutes), "%d minutes" % minutes in f.get("TIMEBOX", ""), f.get("TIMEBOX", ""))
    S.ok("briefs: TIMEBOX says to return partial findings and stop",
         "on expiry, return partial findings and stop rather than run on" in f1.get("TIMEBOX", ""), f1.get("TIMEBOX", ""))
    forb = f1.get("FORBIDDEN", "")
    S.ok("briefs: FORBIDDEN has the four bans and .fwx/",
         all(w in forb for w in ("no PR retargets or merges", "no rebase", "no force-push", "no fixes outside scope", ".fwx/")), forb)
    rep = f1.get("REPORT", "")
    S.ok("briefs: REPORT names report.json in the scratch folder, the fields and the one-line reply",
         "`report.json` directly in your scratch folder, not in its `tmp/`" in rep and os.path.join(folder, "reports") not in t1 and all(w in rep for w in ("status", "branch", "worktree", "head", "commits", "red", "green",
                                                                                        "question", "outside", "could_not_run", "reason"))
         and "<status> <report path> commits=<n>" in rep, rep)
    S.ok("briefs: REPORT says the Write tool is enough (the folder is in the worktree: no heredoc, Write is not refused there)", "Write tool" in rep and "heredoc" not in rep, rep)
    S.ok("briefs: STANDING names agents/executor.md of the plugin", os.path.join(ROOT, "agents", "executor.md") in f1.get("STANDING", ""), f1.get("STANDING", ""))
    S.ok("briefs: no model name (they come from `fwx model`)", not re.search(r"sonnet|opus|haiku|fable", t1, re.I), t1[:200])
    S.ok("briefs: no placeholder left", re.search(r"\$[a-z_]+", t1) is None, t1)
    S.ok("briefs: the paths are absolute, none relative to a worktree", not re.search(r"(?<![\w/.-])\.\./", t1), t1)
    t3, _ = brief_of(S, "briefs", a, "T3")
    S.ok("briefs: a task with no parallel peer says so", "no other task runs with this one" in sections(t3)[0].get("SCOPE", ""), sections(t3)[0].get("SCOPE", ""))
    S.eq("briefs: the second prepare is a new run, the first one's briefs stay",
         (wp.args_of(sc.prepare(R)) or {}).get("run"), run[:-1] + "2")
    S.ok("briefs: the first run's brief is still there", os.path.isfile(tasks_of(a)["T1"]["brief"] or ""))


def case_template(R, S):
    path = os.path.join(R.root, "data", "executor-brief.md")
    text = read(path) if os.path.exists(path) else ""
    S.ok("template: data/executor-brief.md exists", bool(text), path)
    head = "\n".join(text.splitlines()[:10])
    S.ok("template: the header names its referent (orchestrate.md @36885ea)",
         re.search(r"(referent|copied-from): pstack \S*orchestrate\.md @36885ea", head) is not None, head)
    S.ok("template: the nine fields are in it, in order", [m for m in re.findall(r"^## ([A-Z]+)$", text, re.M)] == FIELDS, text[:300])
    S.ok("template: it does not spell the shared files (one place assembles them, 2.5 U9)",
         not any(w in text.replace("plan.md", "") for w in ("context.md", "decisions.tsv")), text)
    S.ok("template: no model name", not re.search(r"sonnet|opus|haiku|fable", text, re.I))


def case_refused(R, S):
    no_tests = wp.task("T2", 1, ["src/b.py"])
    no_tests["tests"] = []
    sc = wp.Scene(tasks=[wp.task("T1", 1, ["src/a.py"]), no_tests])
    r = sc.prepare(R)
    S.eq("refused: a feature task with no tests: exit", r.returncode, 2)
    S.eq("refused: stdout empty", r.stdout, "")
    S.ok("refused: names the task and the field", "task T2: ACCEPTANCE is empty" in r.stderr and "task T2: VERIFY is empty" in r.stderr, r.stderr)
    S.ok("refused: T1 is not blamed", "task T1" not in r.stderr, r.stderr)
    S.ok("refused: no brief written, not even T1's", not os.path.exists(os.path.join(runs_dir(sc))), "runs/ exists in %s" % common_dir(sc.repo))
    gone = wp.Scene()
    os.remove(os.path.join(gone.phase, "decisions.tsv"))
    r = gone.prepare(R)
    S.eq("refused: a CONTEXT file that is not there: exit", r.returncode, 2)
    S.ok("refused: names the task, the field and the file", "task T1: CONTEXT" in r.stderr and "decisions.tsv" in r.stderr, r.stderr)
    S.ok("refused: nothing written", not os.path.exists(runs_dir(gone)))
    bad = wp.Scene(tasks=[wp.task("../T1", 1, ["src/a.py"])])
    r = bad.prepare(R)
    S.eq("refused: a task id that cannot name a file: exit", r.returncode, 2)
    S.ok("refused: says which", "task ../T1" in r.stderr, r.stderr)
    S.ok("refused: nothing written outside the run", not os.path.exists(os.path.join(common_dir(bad.repo), "fwx", "T1.md")) and not os.path.exists(runs_dir(bad)))
    red = wp.Scene(recipe=["false"], tasks=[wp.task("T1", 1, ["src/a.py"])])
    r = red.prepare(R)
    S.eq("refused: a red base: exit", r.returncode, 1)
    S.ok("refused: a red base writes no brief", not os.path.exists(runs_dir(red)))


def case_ui(R, S):
    ui = wp.task("T2", 1, ["src/b.py"], ui=True)
    ui["tests"] = []
    sc = wp.Scene(tasks=[wp.task("T1", 1, ["src/a.py"]), ui])
    r = sc.prepare(R)
    S.eq("ui: a UI task with no tests: exit (ui task refused)", r.returncode, 0)
    a = wp.args_of(r) or {}
    text, f = brief_of(S, "ui", a, "T2")
    S.ok("ui: the brief says a UI task carries no test", "carries no test" in f.get("ACCEPTANCE", "") and "carries no test" in f.get("VERIFY", ""),
         "ACCEPTANCE %r VERIFY %r" % (f.get("ACCEPTANCE", ""), f.get("VERIFY", "")))
    S.eq("ui: the brief still has the nine fields", sections(text)[1], FIELDS)
    withtests = wp.Scene(tasks=[wp.task("T1", 1, ["src/a.py"], ui=True)])
    _, f = brief_of(S, "ui with tests", wp.args_of(withtests.prepare(R)) or {}, "T1")
    S.ok("ui: a UI task that lists a test still gets it", "python3 t.py" in f.get("VERIFY", ""), f.get("VERIFY", ""))


def case_module(R, S):
    code = module_facts("facts['files'] = []\nprint(json.dumps(brief.missing(facts)))\n")
    rc, out, err = child(R.root, code)
    problems = json.loads(out) if rc == 0 and out.strip() else None
    S.ok("module: an empty SCOPE is named: child failed: %s" % err.strip()[-120:], problems is not None, err[-200:])
    S.ok("module: the empty SCOPE is named (prepare exit 0 with an empty SCOPE)", problems == ["task T2: SCOPE is empty"], repr(problems))
    code = module_facts("print(json.dumps(brief.missing(facts)))\n")
    S.eq("module: a complete task has nothing missing", json.loads(child(R.root, code)[1] or "null"), [])
    code = module_facts("facts['ui'] = True; facts['tests'] = []\nprint(json.dumps(brief.missing(facts)))\n")
    S.eq("module: a UI task needs no ACCEPTANCE and no VERIFY", json.loads(child(R.root, code)[1] or "null"), [])
    code = module_facts("facts['ui'] = True; facts['tests'] = []; facts['files'] = []\nprint(json.dumps(brief.missing(facts)))\n")
    S.eq("module: a UI task still needs SCOPE", json.loads(child(R.root, code)[1] or "null"), ["task T2: SCOPE is empty"])
    code = module_facts("print(brief.render(facts))\n")
    rc, plain, err = child(R.root, code)
    S.ok("module: without a previous attempt CONTEXT names none", rc == 0 and "previous attempt" not in plain.lower(), err[-200:] or plain)
    code = module_facts("ctx['previous'] = '/runs/r-1/reports/T2.json'\nfacts = brief.task_facts(task, [task], ctx)\nprint(brief.render(facts))\n")
    rc, again, err = child(R.root, code)
    ctx = sections(again)[0].get("CONTEXT", "") if rc == 0 else ""
    S.ok("module: a relaunch puts the previous report in CONTEXT", "/runs/r-1/reports/T2.json" in ctx, "rc %s, CONTEXT %r %s" % (rc, ctx, err[-120:]))
    code = module_facts("print(json.dumps({'lines': brief.shared_context(paths), 'text': brief.render(facts)}))\n")
    rc, got, err = child(R.root, code)
    both = json.loads(got) if rc == 0 and got.strip() else {"lines": [], "text": ""}
    S.ok("module: the one shared place gives the three files", len(both["lines"]) == 3, repr(both["lines"]) + err[-120:])
    S.ok("module: CONTEXT holds those lines", bool(both["lines"]) and all(l in sections(both["text"])[0].get("CONTEXT", "") for l in both["lines"]),
         repr(both["lines"]))


def findings_file(items):
    d = helpers.mkdtemp("fwx-find-")
    return helpers.write(d, "f.json", json.dumps(items))


def case_fix(R, S):
    sc = wp.Scene(tasks=[wp.task("T1", 1, ["src/a.py"]), wp.task("T2", 2, ["src/b.py"])])
    f = findings_file([FINDING, dict(FINDING, id="F2", file="src/b.py", line=1, claim="b is wrong", severity="high")])
    a = wp.ok_args(S, "fix", sc.prepare(R, "--fix", f))
    fx = a.get("fix") or {}
    S.eq("fix: source and findings stay", (fx.get("source"), [x["id"] for x in fx.get("findings", [])]), (f, ["F1", "F2"]))
    path = fx.get("brief")
    S.ok("fix: fix.brief is a file", isinstance(path, str) and os.path.isfile(path), repr(path))
    text = read(path) if isinstance(path, str) and os.path.isfile(path) else ""
    fields, order = sections(text)
    S.eq("fix: the nine fields", order, FIELDS)
    S.ok("fix: GOAL says one commit per finding", "one commit per finding" in fields.get("GOAL", ""), fields.get("GOAL", ""))
    S.ok("fix: SCOPE has the files of the findings and the trailer", "src/a.py" in fields.get("SCOPE", "") and "src/b.py" in fields.get("SCOPE", "") and "test files that cover each finding" in fields.get("SCOPE", "")
         and "Fwx-Finding: <id>" in fields.get("SCOPE", "") and "Fwx-Run: %s" % a.get("run") in fields.get("SCOPE", ""), fields.get("SCOPE", ""))
    S.ok("fix: ACCEPTANCE is one line per finding with its claim",
         re.search(r"^- F1 .*a is wrong", fields.get("ACCEPTANCE", ""), re.M) and re.search(r"^- F2 .*b is wrong", fields.get("ACCEPTANCE", ""), re.M),
         fields.get("ACCEPTANCE", ""))
    S.ok("fix: CONTEXT has the findings file and each finding's evidence", f in fields.get("CONTEXT", "") and "line 3 prints it" in fields.get("CONTEXT", ""),
         fields.get("CONTEXT", ""))
    S.ok("fix: the plan's tasks get no brief (the fixer is the only task)", all(t["brief"] is None for t in tasks_of(a).values()), repr(tasks_of(a)))
    S.ok("fix: the brief is in the run's briefs folder under a name no task id can have",
         path == os.path.join(common_dir(sc.repo), "fwx", "runs", a["run"], "briefs", "_fix.md"), str(path))
    for label, item, needle in (("a severity that is not low, medium or high", dict(FINDING, severity="urgent"), "severity"),
                                ("a finding with no claim", {k: v for k, v in FINDING.items() if k != "claim"}, "claim"),
                                ("a line that is not a number", dict(FINDING, line="3"), "line"),
                                ("an unknown key", dict(FINDING, fix="x"), "fix")):
        bad = findings_file([item])
        r = sc.prepare(R, "--fix", bad)
        S.eq("fix: %s: exit" % label, r.returncode, 2)
        S.ok("fix: %s: says finding 1 and %r" % (label, needle), "--fix" in r.stderr and "finding 1" in r.stderr and needle in r.stderr, r.stderr)
    dup = findings_file([FINDING, FINDING])
    r = sc.prepare(R, "--control-findings", dup)
    S.eq("fix: a repeated id in --control-findings: exit", r.returncode, 2)
    S.ok("fix: says --control-findings and the id", "--control-findings" in r.stderr and "F1" in r.stderr, r.stderr)
    ok = wp.ok_args(S, "control findings", sc.prepare(R, "--control-findings", findings_file([FINDING])))
    S.eq("fix: --control-findings alone keeps the plan's briefs", all(isinstance(t["brief"], str) for t in tasks_of(ok).values()), True)


def case_revert(R, S):
    sc = wp.Scene()
    a = wp.ok_args(S, "revert", sc.prepare(R, "--revert", "F1,F2"))
    S.eq("revert: the ids", a.get("revert"), ["F1", "F2"])
    S.ok("revert: nothing is launched, so no brief is written", all(t["brief"] is None for t in tasks_of(a).values()) and not os.path.exists(runs_dir(sc)),
         repr(tasks_of(a)))
    for label, ids in (("an id with a space", "F1,F 2"), ("an id that starts with a dash", "-F1"), ("an empty list", ",")):
        r = sc.prepare(R, "--revert", ids)
        S.eq("revert: %s: exit" % label, r.returncode, 2)
        S.ok("revert: %s: says --revert" % label, "--revert" in r.stderr, r.stderr)


# ---------------------------------------------------------------------------------------------------- the controls

B = "lib/fwx/execute/brief.py"
P = "lib/fwx/execute/prepare.py"
T = "data/executor-brief.md"
CASES = [case_briefs, case_template, case_refused, case_ui, case_module, case_fix, case_revert]
MUTANTS = [
    ("SCOPE not checked", case_module, B, '    if not facts["files"]:', "    if False:", "the empty SCOPE is named"),
    ("UI task refused", case_ui, B, '    if not facts["ui"]:', "    if True:", "ui task refused"),
    ("empty fields not refused", case_refused, P, "        problems += brief.missing(facts)", "        problems += []",
     "a feature task with no tests: exit"),
    ("context file not looked for", case_refused, B, "if not os.path.exists(p)]", "if False]", "a CONTEXT file that is not there: exit"),
    ("briefs written before the base is run", case_refused, P, "    red = None if gating else _base_is_green(top, base, recipe, {part, phase}, say)",
     "    _write(made, folder, False)\n    red = None if gating else _base_is_green(top, base, recipe, {part, phase}, say)", "a red base writes no brief"),
    ("task id not checked", case_refused, P, 'if not brief.ID.match(t["id"]):', "if False:", "a task id that cannot name a file: exit"),
    ("fields out of order", case_briefs, T, "## ACCEPTANCE\n$acceptance\n\n## VERIFY\n", "## VERIFY\n$verify\n\n## ACCEPTANCE\n$acceptance\n\n## OLD\n",
     "the nine fields in the order of the template"),
    ("trailers dropped", case_briefs, T, "\n$trailers", "", "SCOPE lists its file, the run and both trailers"),
    ("a sha back in the brief", case_briefs, T, "Base: the `BASE` line of your prompt,", "Base: 0123456789abcdef0123456789abcdef01234567 (the `BASE` line of your prompt),",
     "no sha is in the brief"),
    ("report back under .git", case_briefs, T, "Write it as JSON to `report.json` directly in your scratch folder, not in its `tmp/` (the Write tool is enough).",
     "Write it as JSON to .git/fwx/reports/T1.json, with a heredoc.", "REPORT names report.json in the scratch folder"),
    ("big task at 40 minutes", case_briefs, B, '"big": 60', '"big": 40', "T2 TIMEBOX is 60 minutes"),
    ("every wave runs beside it", case_briefs, P, 'brief.task_facts(t, [x for x in data["tasks"] if x["wave"] == t["wave"]], ctx)',
     'brief.task_facts(t, data["tasks"], ctx)', "SCOPE says nothing of wave 2's files"),
    ("no referent in the header", case_template, T, "copied-from: pstack", "copied-from: none", "the header names its referent"),
    ("shared file named in the template", case_template, T, "## CONTEXT\n$context", "## CONTEXT\nRead context.md.\n$context",
     "it does not spell the shared files"),
    ("UI task without its sentence", case_ui, B, 'NO_TEST = "none: a UI task carries no test; the owner walks it"', 'NO_TEST = "none"',
     "the brief says a UI task carries no test"),
    ("previous report left out", case_module, B, '(["- The report of the previous attempt, read it before anything else: %s" % previous] if previous else [])', "[]",
     "a relaunch puts the previous report in CONTEXT"),
    ("severity not checked", case_fix, B, 'if f.get("severity") not in SEVERITY:', "if False:", "a severity that is not low, medium or high: exit"),
    ("a repeated finding id allowed", case_fix, B, 'elif f["id"] in seen:', "elif False:", "a repeated id in --control-findings: exit"),
    ("the plan's tasks briefed under --fix", case_fix, P, "    if fix:\n        facts = brief.fix_facts", "    if False:\n        facts = brief.fix_facts",
     "the plan's tasks get no brief"),
    ("revert ids not checked", case_revert, P, "    if not ids or bad:", "    if False:", "an id with a space: exit"),
    ("revert launches", case_revert, P, "size, quick, revert is None and not gating)", "size, quick, True)", "nothing is launched, so no brief is written"),
]

if __name__ == "__main__":
    real = wp.runner(ROOT)
    real.root = ROOT
    for case in CASES:
        case(real, s)
    for name, case, path, old, new, needle in MUTANTS:
        m = helpers.Suite()
        try:
            tree = wp.mutant_tree(path, old, new)
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        run = wp.runner(tree)
        run.root = tree
        case(run, m)
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
    s.done()
