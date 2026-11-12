#!/usr/bin/env python3
"""lib/fwx/plan.py and `fwx plan check`: the plan files of a phase read, validated and checked for structure.

Every case builds a phase folder in a temp dir from one valid base plan, changes one thing, and looks at what
`plan.check_phase` returns and at what `bin/fwx plan check` prints and exits with (an error is exit 1 and a line
`error: <file>: <field>: <reason>`, a warning is exit 0 and a `warning:` line, and the count line is always there).

Seen red before the code existed (lib/fwx/plan.py absent; the test stops at the import):
  FAIL: cannot import fwx.plan: cannot import name 'plan' from 'fwx' (.../lib/fwx/__init__.py)

Controls, each seen red on a copy of the repo with one thing changed (424 checks on the good code; FAIL lines quoted):
  - a `load_plan` that returns the frontmatter without validating it (the plan's control):
      FAIL: load_plan: task T2 with empty files raises: raised nothing
      FAIL: load_premortem: an invalid file raises: raised nothing
    and with the plan validator that `check_phase` shares finding nothing, 78 FAIL lines, among them:
      FAIL: error: a missing top-level field: 'plan.md: size: missing' not in []
  - a `section` that does not see code fences:
      FAIL: section found a heading inside a fence: got 'not a heading\n```', want None
      (11 FAIL lines: the longer closer, the indented closer, the tilde cases)
  - a closing fence of any length closes (`len(closer) >= len(opener)` dropped):
      FAIL: section: a shorter closer stays inside: got '````\n## Approach\nreal', want None
  - an opening fence with a backtick in its info text counted as a fence:
      FAIL: an info text with a backtick opens no fence: got None, want 'real'
  - a checker that does not look at subphase folders:
      FAIL: error: a subphase without a folder: 'plan.md: tasks[T1].subphase: 01.1-a has no folder' not in []
  - a clash only for equal paths:
      FAIL: error: a folder and a file inside it: 'plan.md: waves[1].files: T1 and T2 both write src' not in []
  - a dependency on a task of the same wave accepted (`>=` as `>`):
      FAIL: error: depends_on a task of the same wave: 'plan.md: tasks[T2].depends_on: T1 is in wave 1, not before wave 1' not in []
  - a phase with no plan.md counted as clean:
      FAIL: error: no plan.md: 'plan.md: file: missing' not in []
  - the count line left out of the output (77 FAIL lines):
      FAIL: count line: a clean plan: []
  - each warning switched off, one at a time (band, earlier wave, uncited decision, agents, premortem size):
      FAIL: warning: more tasks than the band: 'plan.md: tasks: 5 tasks, the small band is 4' not in []
      (and the same with the other four messages)
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx import plan  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.plan: %s" % e)
    sys.exit(1)

BODY = "## Goal\nBuild it.\n\n## Approach\nT1 and T2 first, T3 after; carries out D1.\n\n## Size\nNormal.\n"
# what U8's form check wants of the other plan files (headings, no ids a subphase's plan does not define)
SBODY = "## Goal\nBuild it.\n\n## Approach\nCarries out D1.\n\n## Size\nNormal.\n"
TBODY = "## Goal\nBuild it.\n\n## Approach\nT1, then T2; carries out D1.\n\n## Size\nNormal.\n"
PREB = "## Verdict\nok\n\n## Failure reasons\nNone.\n\n## Size\nNormal.\n"
POSTB = ("## Verdict\nok\n\n## Findings\nNone.\n\n## Criteria\nC1.\n\n## Checked\nAll.\n\n"
         "## Needs from the owner before executing\nNone\n\n## Not found wrong\nNothing.\n")
REPO = helpers.toy_repo({"README": "toy\n", ".claude/fwx.json": '{"schema": 1}'})  # a phase is in a repository with its configuration


def test(run="python3 t.py"):
    return {"run": run, "measures": "the thing", "red": "the old version fails with 'x'"}


def base():
    return {
        "size": {"tag": "normal", "parts": 1, "agents": 2},
        "criteria": [{"id": "C1", "text": "it works", "measure": "t.py exits 0"},
                     {"id": "C2", "text": "it is fast", "measure": "time t.py"}],
        "tasks": [
            {"id": "T1", "part": 1, "type": "feature", "wave": 1, "files": ["a.py"], "depends_on": [], "tests": [test()],
             "size": "small", "ui": False},
            {"id": "T2", "part": 1, "type": "bug", "wave": 1, "files": ["b.py"], "depends_on": [], "tests": [test()],
             "size": "small", "ui": False},
            {"id": "T3", "part": 1, "type": "feature", "wave": 2, "files": ["c.py"], "depends_on": ["T1", "T2"], "tests": [],
             "size": "small", "ui": False},
        ],
        "not_built": [{"what": "x", "why": "y"}],
        "later": [],
    }


def fm_text(fm):
    return "---\n" + json.dumps(fm, indent=1) + "\n---\n"


_made = [0]


def phase(fm=None, body=BODY, raw=None, extra=None):
    """A phase folder with plan.md (frontmatter `fm`, or the text `raw`) and decisions.tsv with D1 chosen."""
    _made[0] += 1
    d = os.path.join(REPO, ".fwx", "p%d" % _made[0])
    helpers.write(d, "plan.md", raw if raw is not None else fm_text(fm if fm is not None else base()) + body)
    helpers.write(d, "decisions.tsv", "date\tid\tdecision\twhy\trejected\tsupport\tsource\tsupersedes\n"
                  "day-1\tD1\tuse a\tbecause\t\tchosen\tturn 1\t\n")
    for rel, text in (extra or {}).items():
        helpers.write(d, rel, text)
    return d


def cli(d, *args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx"), "plan", "check", d] + list(args), cwd=WORK,
                          env=helpers.clean_env(), capture_output=True, text=True)


WORK = helpers.mkdtemp("fwx-plan-cwd-")
COUNT = re.compile(r"checked (\d+) plan file\(s\): (\d+) tasks, (\d+) waves, (\d+) parts; (\d+) errors, (\d+) warnings\Z")


def case(label, d, errors=(), warnings=(), exact=None):
    """check_phase and the command agree: each wanted message is in errors (or warnings) and on the command's output, the
    exit is 1 with an error and 0 without, and the count line is the last one and says how many of each."""
    r = plan.check_phase(d)
    for want in errors:
        s.ok("error: %s" % label, any(want in e for e in r["errors"]), "%r not in %r" % (want, r["errors"]))
    for want in warnings:
        s.ok("warning: %s" % label, any(want in w for w in r["warnings"]), "%r not in %r" % (want, r["warnings"]))
    if exact is not None:
        s.eq("only these: %s" % label, (len(r["errors"]), len(r["warnings"])), exact)
    p = cli(d)
    s.eq("exit: %s" % label, p.returncode, 1 if r["errors"] else 0)
    lines = p.stdout.strip().splitlines()
    m = COUNT.match(lines[-1]) if lines else None
    s.ok("count line: %s" % label, m is not None, repr(lines[-1:]))
    if m:
        s.eq("count line says the errors and warnings: %s" % label, (int(m.group(5)), int(m.group(6))), (len(r["errors"]), len(r["warnings"])))
    for want in errors:
        s.ok("command prints the error: %s" % label, "error: " + next((e for e in r["errors"] if want in e), "?") in p.stdout, p.stdout)
    for want in warnings:
        s.ok("command prints the warning: %s" % label, "warning: " + next((w for w in r["warnings"] if want in w), "?") in p.stdout, p.stdout)
    return r


def mutated(change, **kw):
    fm = base()
    change(fm)
    return phase(fm, **kw)


def task(fm, tid):
    return next(t for t in fm["tasks"] if t["id"] == tid)


# ---- the clean case, and the loader
clean = phase()
r = case("a clean plan", clean, exact=(0, 0))
s.eq("counts", (r["plans"], r["tasks"], r["waves"], r["parts"], r["clashes"]), (1, 3, 2, 1, []))
s.ok("the count line of the clean plan", "checked 1 plan file(s): 3 tasks, 2 waves, 1 parts; 0 errors, 0 warnings" in cli(clean).stdout)
s.eq("load_plan returns the frontmatter", plan.load_plan(os.path.join(clean, "plan.md")), base())
s.eq("constants", (plan.TAGS, plan.TYPES, plan.VERDICTS, plan.BAND),
     (("small", "normal", "big"), ("bug", "refactor", "feature"), ("ok", "objections", "back-to-discuss"), {"small": 4, "normal": 6, "big": 8}))


def raises(label, fn, text=None, field=None):
    try:
        fn()
    except plan.PlanError as e:
        if text is not None:
            s.eq(label + ": text", str(e), text)
        if field is not None:
            s.eq(label + ": field", e.field, field)
        return e
    s.ok(label, False, "raised nothing")


e = raises("load_plan: task T2 with empty files raises", lambda: plan.load_plan(os.path.join(mutated(lambda f: task(f, "T2").update(files=[])), "plan.md"), "plan.md"),
           "plan.md: tasks[T2].files: empty", "tasks[T2].files")
s.eq("PlanError.path", e and e.path, "plan.md")
raises("load_plan: a missing file raises", lambda: plan.load_plan("/nonexistent/plan.md"), field="file")
raises("read_frontmatter: no frontmatter raises", lambda: plan.read_frontmatter(os.path.join(phase(raw="## Goal\nx\n"), "plan.md")), field="frontmatter")

# ---- frontmatter that is not a plan
case("no frontmatter", phase(raw="## Goal\nx\n"), ["plan.md: frontmatter: missing"])
case("frontmatter that is not JSON", phase(raw="---\nsize: {tag: normal}\n---\n" + BODY), ["plan.md: frontmatter: is not JSON"])
case("frontmatter that is a list", phase(raw="---\n[1]\n---\n" + BODY), ["plan.md: frontmatter: is not a JSON object"])
case("no plan.md", helpers.mkdtemp("fwx-plan-"), ["plan.md: file: missing"])
case("a missing top-level field", mutated(lambda f: f.pop("size")), ["plan.md: size: missing"])
case("a missing later", mutated(lambda f: f.pop("later")), ["plan.md: later: missing"])
case("an unknown top-level field", mutated(lambda f: f.update(extra=1)), ["plan.md: extra: unknown field"])
case("size.parts of another type", mutated(lambda f: f["size"].update(parts="2")), ["plan.md: size.parts: must be an integer of at least 1"])
case("size.parts a bool", mutated(lambda f: f["size"].update(parts=True)), ["plan.md: size.parts: must be an integer of at least 1"])
case("size.tag outside its list", mutated(lambda f: f["size"].update(tag="huge")), ["plan.md: size.tag: must be one of small, normal, big"])
case("an unknown size field", mutated(lambda f: f["size"].update(part=1)), ['plan.md: size.part: unknown field (did you mean "parts"?)'])
case("task type outside its list", mutated(lambda f: task(f, "T1").update(type="chore")), ["plan.md: tasks[T1].type: must be one of bug, refactor, feature"])
case("task ui of another type", mutated(lambda f: task(f, "T1").update(ui="no")), ["plan.md: tasks[T1].ui: must be true or false"])
case("task review outside its list", mutated(lambda f: task(f, "T1").update(review="never")), ["plan.md: tasks[T1].review: must be one of blocking, async"])
case("a task field missing", mutated(lambda f: task(f, "T1").pop("wave")), ["plan.md: tasks[T1].wave: missing"])
case("a task that is not an object", mutated(lambda f: f["tasks"].append(7)), ["plan.md: tasks[3]: must be an object"])
case("tasks that is not a list", mutated(lambda f: f.update(tasks={})), ["plan.md: tasks: must be a list"])
case("file instead of files", mutated(lambda f: (task(f, "T2").pop("files"), task(f, "T2").update(file=["b.py"]))),
     ['plan.md: tasks[T2].file: unknown field (did you mean "files"?)', "plan.md: tasks[T2].files: missing"])

# ---- criteria, not_built, later
case("one criterion", mutated(lambda f: f["criteria"].pop()), ["plan.md: criteria: 1 criteria, 2 to 5 required"])
case("six criteria", mutated(lambda f: f["criteria"].extend([dict(f["criteria"][0], id="C%d" % i) for i in range(3, 7)])), ["plan.md: criteria: 6 criteria, 2 to 5 required"])
case("five criteria are fine", mutated(lambda f: f["criteria"].extend([dict(f["criteria"][0], id="C%d" % i) for i in range(3, 6)])), exact=(0, 0))
case("a criterion with empty text", mutated(lambda f: f["criteria"][0].update(text="")), ["plan.md: criteria[0].text: empty"])
case("a criterion with a blank measure", mutated(lambda f: f["criteria"][1].update(measure="  ")), ["plan.md: criteria[1].measure: must be a non-empty string"])
case("a criterion without a measure", mutated(lambda f: f["criteria"][1].pop("measure")), ["plan.md: criteria[1].measure: missing"])
case("not_built without a why", mutated(lambda f: f["not_built"][0].pop("why")), ["plan.md: not_built[0].why: missing"])
case("later with an empty what", mutated(lambda f: f["later"].append({"what": "", "why": "w"})), ["plan.md: later[0].what: empty"])
case("later as a string", mutated(lambda f: f.update(later=["x"])), ["plan.md: later[0]: must be an object {what, why}"])

# ---- tasks
case("task T2 with empty files", mutated(lambda f: task(f, "T2").update(files=[])), ["plan.md: tasks[T2].files: empty"])
case("a repeated task id", mutated(lambda f: task(f, "T2").update(id="T1")), ["plan.md: tasks[T1].id: duplicate of an earlier task"])
case("no tasks", mutated(lambda f: f.update(tasks=[])), ["plan.md: tasks: empty"])
case("depends_on an id that does not exist", mutated(lambda f: task(f, "T3").update(depends_on=["T9"])), ["plan.md: tasks[T3].depends_on: T9 is not a task of this plan"])
case("depends_on a task of the same wave", mutated(lambda f: task(f, "T2").update(depends_on=["T1"])), ["plan.md: tasks[T2].depends_on: T1 is in wave 1, not before wave 1"])
case("depends_on a later wave", mutated(lambda f: task(f, "T1").update(depends_on=["T3"])), ["plan.md: tasks[T1].depends_on: T3 is in wave 2, not before wave 1"])
case("a bug with ui false and no tests", mutated(lambda f: task(f, "T2").update(tests=[])), ["plan.md: tasks[T2].tests: empty (a bug task with ui false needs a test)"])
case("a refactor with ui false and no tests", mutated(lambda f: task(f, "T1").update(type="refactor", tests=[])), ["plan.md: tasks[T1].tests: empty (a refactor task with ui false needs a test)"])
case("a bug with ui true needs no tests", mutated(lambda f: task(f, "T2").update(tests=[], ui=True)), exact=(0, 0))
case("a feature without tests is fine", mutated(lambda f: task(f, "T1").update(tests=[])), exact=(0, 0))
case("a test without run", mutated(lambda f: task(f, "T1")["tests"][0].pop("run")), ["plan.md: tasks[T1].tests[0].run: missing"])
case("a test with an empty measures", mutated(lambda f: task(f, "T1")["tests"][0].update(measures="")), ["plan.md: tasks[T1].tests[0].measures: empty"])
case("a test without red", mutated(lambda f: task(f, "T1")["tests"][0].pop("red")), ["plan.md: tasks[T1].tests[0].red: missing"])
case("a part above size.parts", mutated(lambda f: task(f, "T1").update(part=3)), ["plan.md: tasks[T1].part: 3 is above size.parts 1"])
case("firefox without ui", mutated(lambda f: task(f, "T1").update(firefox=True)), ["plan.md: tasks[T1].firefox: true needs ui: true"])
case("firefox with ui is fine", mutated(lambda f: task(f, "T1").update(firefox=True, ui=True)), exact=(0, 0))
case("a subphase that is not a folder name", mutated(lambda f: task(f, "T1").update(subphase="../x")), ['plan.md: tasks[T1].subphase: must be a folder name like "03.1-slug"'])

# ---- two tasks of a wave with a file in common
r = case("two tasks of a wave writing one file", mutated(lambda f: task(f, "T2").update(files=["b.py", "a.py"])), ["plan.md: waves[1].files: T1 and T2 both write a.py"])
s.eq("the clash is listed", r["clashes"], [{"plan": "plan.md", "wave": 1, "tasks": ["T1", "T2"], "file": "a.py"}])
case("a folder and a file inside it", mutated(lambda f: (task(f, "T1").update(files=["src/"]), task(f, "T2").update(files=["src/x.py"]))), ["plan.md: waves[1].files: T1 and T2 both write src"])
case("the same file in two waves is no clash", mutated(lambda f: task(f, "T3").update(files=["a.py"])), exact=(0, 0))
r = case("a plan with a clash still loads", mutated(lambda f: task(f, "T2").update(files=["a.py"])), ["both write a.py"])
s.eq("load_plan does not look at clashes", plan.load_plan(os.path.join(mutated(lambda f: task(f, "T2").update(files=["a.py"])), "plan.md"))["tasks"][1]["files"], ["a.py"])

# ---- premortem.md and postmortem.md
PRE = {"verdict": "ok", "size_tag": "normal", "parts": 1, "round": 1}
POST = {"verdict": "ok", "security_review": False, "round": 1}
good = phase(extra={"premortem.md": fm_text(PRE) + PREB, "postmortem.md": fm_text(POST) + POSTB})
case("a valid premortem and postmortem", good, exact=(0, 0))
s.eq("load_premortem", plan.load_premortem(os.path.join(good, "premortem.md")), PRE)
s.eq("load_postmortem", plan.load_postmortem(os.path.join(good, "postmortem.md")), POST)
for label, fm, want in (
        ("verdict outside its list", dict(PRE, verdict="maybe"), "premortem.md: verdict: must be one of ok, objections, back-to-discuss"),
        ("a size_tag outside its list", dict(PRE, size_tag="tiny"), "premortem.md: size_tag: must be one of small, normal, big"),
        ("round 0", dict(PRE, round=0), "premortem.md: round: must be an integer of at least 1"),
        ("a missing parts", {k: v for k, v in PRE.items() if k != "parts"}, "premortem.md: parts: missing"),
        ("an unknown field", dict(PRE, security_review=True), "premortem.md: security_review: unknown field")):
    case("premortem " + label, phase(extra={"premortem.md": fm_text(fm)}), [want])
for label, fm, want in (
        ("verdict outside its list", dict(POST, verdict="fine"), "postmortem.md: verdict: must be one of ok, objections, back-to-discuss"),
        ("security_review as a string", dict(POST, security_review="yes"), "postmortem.md: security_review: must be true or false"),
        ("a missing round", {k: v for k, v in POST.items() if k != "round"}, "postmortem.md: round: missing"),
        ("size_tag, which is the premortem's", dict(POST, size_tag="small"), "postmortem.md: size_tag: unknown field")):
    case("postmortem " + label, phase(extra={"postmortem.md": fm_text(fm)}), [want])
case("a postmortem with no frontmatter", phase(extra={"postmortem.md": "## Verdict\nok\n"}), ["postmortem.md: frontmatter: missing"])
raises("load_premortem: an invalid file raises", lambda: plan.load_premortem(os.path.join(phase(extra={"premortem.md": fm_text(dict(PRE, verdict="x"))}), "premortem.md")), field="verdict")

# ---- warnings: they do not change the exit
five = lambda f: (f["size"].update(tag="small", agents=1), f.update(tasks=[
    {"id": "T%d" % i, "part": 1, "type": "feature", "wave": i, "files": ["f%d.py" % i], "depends_on": ["T%d" % (i - 1)] if i > 1 else [],
     "tests": [], "size": "small", "ui": False} for i in range(1, 6)]))
case("more tasks than the band", mutated(five), warnings=["plan.md: tasks: 5 tasks, the small band is 4"], exact=(0, 1))
case("a plan at its band is fine", mutated(lambda f: (five(f), f["tasks"].pop())), exact=(0, 0))
case("size.tag differs from the premortem", phase(extra={"premortem.md": fm_text(dict(PRE, size_tag="small")) + PREB}),
     warnings=["plan.md: size.tag: normal, but premortem.md says small"], exact=(0, 1))
case("size.parts differs from the premortem", phase(extra={"premortem.md": fm_text(dict(PRE, parts=2)) + PREB}),
     warnings=["plan.md: size.parts: 1, but premortem.md says 2"], exact=(0, 1))
case("size.agents is not the widest wave", mutated(lambda f: f["size"].update(agents=3)),
     warnings=["plan.md: size.agents: 3, but the widest wave has 2 task(s)"], exact=(0, 1))
case("a task that would fit in an earlier wave", mutated(lambda f: task(f, "T3").update(depends_on=[])),
     warnings=["plan.md: tasks[T3].wave: could run in wave 1"], exact=(0, 1))
case("an earlier wave that writes its file is no warning", mutated(lambda f: task(f, "T3").update(depends_on=[], files=["a.py"])), exact=(0, 0))
decisions = "date\tid\tdecision\twhy\trejected\tsupport\tsource\tsupersedes\n" + "".join(
    "day-1\t%s\td\tw\t\t%s\t\t%s\n" % row for row in (("D1", "chosen", ""), ("D2", "chosen", ""), ("D3", "approved", ""),
                                                          ("D4", "unexamined", ""), ("D5", "agent-assumption", ""), ("D6", "chosen", ""), ("D7", "chosen", "D6")))
case("a decision the plan does not cite", phase(body=BODY, extra={"decisions.tsv": decisions}),
     warnings=["plan.md: body: D2 (chosen) is not cited", "plan.md: body: D3 (approved) is not cited"], exact=(0, 3))
r = plan.check_phase(phase(body=BODY, extra={"decisions.tsv": decisions}))
s.eq("unexamined, assumed and replaced decisions are not asked for", sorted(w.split()[2] for w in r["warnings"]), ["D2", "D3", "D7"])
s.ok("D10 does not cite D1", any("D1 (chosen)" in w for w in plan.check_phase(phase(body=BODY.replace("D1.", "D10."), extra={"decisions.tsv": decisions}))["warnings"]))

# a plan that still cites a decision a later row replaced (the owner decided after the plan: D10 replaces D2) says so, naming the
# decision it should cite now; a plan that cites the new one says nothing.
# Seen red on master (no such warning; the rehearsal's criterion C2 kept stating the replaced value):
#   FAIL: warning: a plan that cites a replaced decision: 'plan.md: body: cites D2, superseded by D10' not in [...]
after = ("date\tid\tdecision\twhy\trejected\tsupport\tsource\tsupersedes\n"
         "day-1\tD1\td\tw\t\tchosen\t\t\nday-1\tD2\td\tw\t\tchosen\t\t\nday-2\tD10\td\tw\t\tchosen\treview of part 1\tD2\n")
case("a plan that cites a replaced decision", phase(body=BODY.replace("D1.", "D1 and D2."), extra={"decisions.tsv": after}),
     warnings=["plan.md: body: cites D2, superseded by D10"])
fresh = phase(body=BODY.replace("D1.", "D1 and D10."), extra={"decisions.tsv": after})
s.ok("a plan that cites the replacing decision has no such warning",
     not any("superseded by" in w for w in plan.check_phase(fresh)["warnings"]), str(plan.check_phase(fresh)["warnings"]))
s.ok("the same for a plan that cites neither",
     not any("superseded by" in w for w in plan.check_phase(phase(body=BODY, extra={"decisions.tsv": after}))["warnings"]))

# ---- a phase with two subphases
SUB = lambda part, n: {"size": {"tag": "small", "parts": 1, "agents": 1}, "criteria": base()["criteria"], "not_built": [], "later": [],
                       "tasks": [{"id": "S%d" % n, "part": part, "type": "feature", "wave": 1, "files": ["s%d.py" % n], "depends_on": [],
                                  "tests": [], "size": "small", "ui": False}]}
top = lambda: {"size": {"tag": "normal", "parts": 2, "agents": 1}, "criteria": base()["criteria"], "not_built": [], "later": [],
               "tasks": [{"id": "T1", "part": 1, "subphase": "01.1-a", "type": "feature", "wave": 1, "files": ["a.py"], "depends_on": [],
                          "tests": [], "size": "small", "ui": False},
                         {"id": "T2", "part": 2, "subphase": "01.2-b", "type": "feature", "wave": 2, "files": ["b.py"], "depends_on": ["T1"],
                          "tests": [], "size": "small", "ui": False}]}
subs = lambda: {"01.1-a/plan.md": fm_text(SUB(1, 1)) + SBODY, "01.2-b/plan.md": fm_text(SUB(2, 2)) + SBODY}
parts = phase(top(), body=TBODY, extra=subs())
r = case("two subphases", parts, exact=(0, 0))
s.eq("two subphases: counts", (r["plans"], r["tasks"], r["waves"], r["parts"]), (3, 4, 4, 2))
s.ok("two subphases: the count line", "checked 3 plan file(s): 4 tasks, 4 waves, 2 parts; 0 errors, 0 warnings" in cli(parts).stdout)
case("a subphase plan that cites a replaced decision names its file",
     phase(top(), body=TBODY, extra=dict(subs(), **{"decisions.tsv": after, "01.2-b/plan.md": fm_text(SUB(2, 2)) + SBODY.replace("D1.", "D1 and D2.")})),
     warnings=["01.2-b/plan.md: body: cites D2, superseded by D10"])
case("a subphase without a folder", phase(top(), extra={"01.2-b/plan.md": fm_text(SUB(2, 2)) + BODY}), ["plan.md: tasks[T1].subphase: 01.1-a has no folder"])
case("a subphase folder without plan.md", phase(top(), extra={"01.1-a/plan.md": fm_text(SUB(1, 1)) + BODY, "01.2-b/x": "x"}), ["01.2-b/plan.md: file: missing"])
case("a subphase with an invalid plan.md", phase(top(), extra=dict(subs(), **{"01.2-b/plan.md": fm_text(dict(SUB(2, 2), tasks=[])) + BODY})), ["01.2-b/plan.md: tasks: empty"])
case("a subphase task of another part", phase(top(), extra=dict(subs(), **{"01.2-b/plan.md": fm_text(SUB(1, 2)) + BODY})),
     ["01.2-b/plan.md: tasks[S2].part: 1, but the phase's task T2 is part 2"])
case("a task without a subphase when parts is 2", phase((lambda t: (t["tasks"][0].pop("subphase"), t)[1])(top()), extra=subs()),
     ["plan.md: tasks[T1].subphase: missing (size.parts is 2, each task is a subphase)"])
case("a task above parts in a phase with subphases", phase((lambda t: (t["tasks"][1].update(part=3), t)[1])(top()), extra=subs()), ["plan.md: tasks[T2].part: 3 is above size.parts 2"])

# ---- the command
d = phase()
s.eq("no subcommand: exit 2", subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx"), "plan"], capture_output=True, text=True, env=helpers.clean_env()).returncode, 2)
p = cli("/nonexistent/phase")
s.eq("a folder that does not exist: exit 2", p.returncode, 2)
s.ok("a folder that does not exist: says so", "is not a folder" in p.stderr, p.stderr)
s.eq("a stray flag: exit 2", cli(d, "--nope").returncode, 2)
s.eq("--json: exit", cli(d, "--json").returncode, 0)
j = json.loads(cli(d, "--json").stdout)
s.eq("--json: the keys", sorted(j), ["clashes", "errors", "parts", "plans", "summary", "tasks", "warnings", "waves"])
s.ok("--json: the count line is the summary", j["summary"].startswith("checked 1 plan file(s): 3 tasks"), j["summary"])
bad = mutated(lambda f: task(f, "T2").update(files=[]))
s.eq("--json with an error: exit", cli(bad, "--json").returncode, 1)
s.eq("--json with an error: errors", json.loads(cli(bad, "--json").stdout)["errors"], ["plan.md: tasks[T2].files: empty"])
s.ok("the help lists plan", "plan " in subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx"), "--help"], capture_output=True, text=True).stdout)

# ---- section: pstack's check-plan.test.ts cases, on a plan file
def sec(text, heading):
    return plan.section(os.path.join(phase(raw=fm_text(base()) + text), "plan.md"), heading)


s.eq("section: the text under a heading", sec("## Goal\nline 1\n\nline 2\n\n## Size\nbig\n", "Goal"), "line 1\n\nline 2")
s.eq("section: the last heading runs to the end", sec("## Goal\nx\n## Size\nlast\n", "Size"), "last")
s.eq("section: a heading that is not there", sec("## Goal\nx\n", "Size"), None)
s.eq("section: a heading with an empty text", sec("## Goal\n## Size\nx\n", "Goal"), "")
s.eq("section: ### does not end a section", sec("## Goal\na\n### Sub\nb\n## Size\n", "Goal"), "a\n### Sub\nb")
s.eq("section: a heading that only starts like it", sec("## Goal and more\nx\n", "Goal"), None)
s.eq("section: the frontmatter is not the body", plan.section(os.path.join(phase(raw='---\n{"a": "## Goal"}\n---\n## Size\nx\n'), "plan.md"), "Goal"), None)
raises("section: a missing file raises", lambda: plan.section("/nonexistent/x.md", "Goal"), field="file")
s.eq("section found a heading inside a fence", sec("## Goal\nx\n```md\n## Size\nnot a heading\n```\n", "Size"), None)
s.eq("section: the fenced `## ` stays in the text and does not end it", sec("## Goal\nx\n```md\n## Size\n```\ny\n## Size\nz\n", "Goal"), "x\n```md\n## Size\n```\ny")
s.eq("section: a closing fence longer than the opening", sec("## Goal\n```\n## Size\n````\n## Approach\nreal\n", "Size"), None)
s.eq("section: ... and the heading after it counts", sec("## Goal\n```\n## Size\n````\n## Approach\nreal\n", "Approach"), "real")
s.eq("section: an indented closing fence", sec("## Goal\n```\n## Size\n  ```\n## Approach\nreal\n", "Size"), None)
s.eq("section: a tilde fence", sec("## Goal\n~~~markdown\n## Size\n~~~\n## Approach\nreal\n", "Size"), None)
s.eq("section: a tilde fence with a backtick in its info text", sec("## Goal\n~~~markdown `info`\n## Size\n ~~~\n", "Size"), None)
s.eq("section: a backtick closer does not close a tilde fence", sec("## Goal\n~~~\n```\n## Size\n~~~\n## Approach\nreal\n", "Size"), None)
s.eq("section: a shorter closer stays inside", sec("## Goal\n````markdown\n```\n## Size\n````\n## Approach\nreal\n", "Size"), None)
s.eq("section: a different character closer stays inside", sec("## Goal\n````markdown\n~~~\n## Size\n````\n## Approach\nreal\n", "Size"), None)
s.eq("section: a closer with text after it stays inside", sec("## Goal\n```\n``` not a closer\n## Size\n```\n## Approach\nreal\n", "Size"), None)
s.eq("section: a fence never closed runs to the end", sec("## Goal\n```\n## Size\nx\n", "Size"), None)
s.eq("an info text with a backtick opens no fence", sec("## Goal\n``` `x`\n## Size\nreal\n", "Size"), "real")

s.done()
