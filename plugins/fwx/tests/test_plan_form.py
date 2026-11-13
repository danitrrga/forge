#!/usr/bin/env python3
"""lib/fwx/plan_form.py through `plan.check_phase` and `fwx plan check`: the form of the plan files and what a script can check.

Every case builds a phase folder inside a toy repo from one valid base (plan.md, premortem.md, postmortem.md, decisions.tsv),
changes one thing, and wants one exact message in `errors` (or `warnings`), on the command's output, and exit 1 (0 for a
warning). The cases name no function of plan_form: they go through check_phase and the command, so the same file runs against
the checker without plan_form.

Seen red with U1's `check_phase` alone (plan.py without its call to plan_form): 122 FAIL lines of 474 checks, 58 of them a missing
error or warning; the rest are the same cases seen through the exit code, the count line and the command's output. Quoted:
  FAIL: error: ## Goal of twelve lines: 'plan.md: ## Goal: 12 lines, under ten required' not in []
  FAIL: error: a cite to a file that does not exist: 'plan.md: body: cited file not found: lib/nope.py' not in []
  FAIL: error: D9 in the body, no row: 'plan.md: body: D9 is not defined in decisions.tsv' not in []
  FAIL: error: a blocker with unproven evidence: 'postmortem.md: findings[1]: unproven evidence on a blocker' not in []
  FAIL: error: postmortem ok with a blocker: 'postmortem.md: findings: verdict ok with a blocker finding' not in []
  FAIL: error: a protected path with security_review false: 'postmortem.md: security_review: task T1 touches a protected path (.github/workflows/**): security_review must be true' not in []
  FAIL: error: premortem.md: ## Size inside a fence is not a heading: 'premortem.md: ## Size: missing' not in []
  FAIL: warning: 3601 words: 'plan.md: body: 3601 words, over 3600: is every line needed?' not in []
The clean cases (0 errors, 0 warnings) pass on the old checker, as they must: they are what the new one must not break.

Controls: each check of plan_form switched off or bent in turn on a copy (the 26 mutants are in the commit message): the cases of
that check fail, the clean ones keep passing.
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

REAL = "".join("line %d of the real file\n" % i for i in range(1, 41))
REPO = helpers.toy_repo({"lib/real.py": REAL, "docs/note.md": "one\ntwo\n",
                         ".claude/fwx.json": json.dumps({"schema": 1, "project": {"protected_paths": [".github/workflows/**"]}})})
WORK = helpers.mkdtemp("fwx-form-cwd-")
COUNT = re.compile(r"checked (\d+) plan file\(s\): (\d+) tasks, (\d+) waves, (\d+) parts; (\d+) errors, (\d+) warnings\Z")

GOAL = "## Goal\nBuild it.\n\n"
APPROACH = "## Approach\nT1 and T2 first, T3 after, for C1 and C2; carries out D1. See `lib/real.py:10-12`.\n\n"
SIZE = "## Size\nNormal.\n"
BODY = GOAL + APPROACH + SIZE
NOCITE = BODY.replace(" See `lib/real.py:10-12`.", "")  # for a phase outside any repository: no cite to look for
PRE_BODY = "## Verdict\nok\n\n## Failure reasons\nNone.\n\n## Size\nNormal.\n"
POST_BODY = ("## Verdict\nok\n\n## Findings\nNone.\n\n## Criteria\nC1 and C2 can fail.\n\n## Checked\nthe tests.\n\n"
             "## Needs from the owner before executing\nNone\n\n## Not found wrong\nthe rest.\n")
PRE = {"verdict": "ok", "size_tag": "normal", "parts": 1, "round": 1}
POST = {"verdict": "ok", "security_review": False, "round": 1}
DECISIONS = ("date\tid\tdecision\twhy\trejected\tsupport\tsource\tsupersedes\n"
             "day-1\tD1\tuse a\tbecause\t\tchosen\tturn 1\t\n")


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


_n = [0]


def phase(change=None, body=BODY, pre=PRE_BODY, post=POST_BODY, pre_fm=PRE, post_fm=POST, decisions=DECISIONS, extra=None, in_repo=True):
    """A phase folder with plan.md, premortem.md, postmortem.md and decisions.tsv; `pre` or `post` None leaves the file out."""
    _n[0] += 1
    d = os.path.join(REPO, ".fwx", "p%d" % _n[0]) if in_repo else helpers.mkdtemp("fwx-form-")
    fm = base()
    if change:
        change(fm)
    helpers.write(d, "plan.md", fm_text(fm) + body)
    if pre is not None:
        helpers.write(d, "premortem.md", fm_text(pre_fm) + pre)
    if post is not None:
        helpers.write(d, "postmortem.md", fm_text(post_fm) + post)
    if decisions is not None:
        helpers.write(d, "decisions.tsv", decisions)
    for rel, text in (extra or {}).items():
        helpers.write(d, rel, text)
    return d


def task(fm, tid):
    return next(t for t in fm["tasks"] if t["id"] == tid)


def cli(d, *args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx"), "plan", "check", d] + list(args), cwd=WORK,
                          env=helpers.clean_env(), capture_output=True, text=True)


def case(label, d, errors=(), warnings=(), exact=None):
    """check_phase and the command agree. Each wanted message is one whole entry of errors (or warnings) and on the output;
    exit 1 with an error, 0 without; `exact` is (errors, warnings), what the folder must give and nothing else."""
    r = plan.check_phase(d)
    for want in errors:
        s.ok("error: %s" % label, want in r["errors"], "%r not in %r" % (want, r["errors"]))
    for want in warnings:
        s.ok("warning: %s" % label, want in r["warnings"], "%r not in %r" % (want, r["warnings"]))
    if exact is not None:
        s.eq("only these: %s" % label, (len(r["errors"]), len(r["warnings"])), exact)
        if exact == (0, 0):
            s.eq("nothing at all: %s" % label, (r["errors"], r["warnings"]), ([], []))
    p = cli(d)
    s.eq("exit: %s" % label, p.returncode, 1 if r["errors"] else 0)
    lines = p.stdout.strip().splitlines()
    m = COUNT.match(lines[-1]) if lines else None
    s.ok("count line: %s" % label, m is not None, repr(lines[-1:]))
    if m:
        s.eq("count line says the errors and warnings: %s" % label, (int(m.group(5)), int(m.group(6))), (len(r["errors"]), len(r["warnings"])))
    for want in errors:
        s.ok("command prints the error: %s" % label, "error: " + want in p.stdout, p.stdout)
    for want in warnings:
        s.ok("command prints the warning: %s" % label, "warning: " + want in p.stdout, p.stdout)
    return r


def words(n):
    return " ".join(["word"] * n)


def padded(n, line=True):
    """BODY grown to exactly n words: in one line, or in lines of three words."""
    extra = n - len(BODY.split())
    pad = words(extra) + "\n" if line else "".join("one two three\n" for _ in range(extra // 3)) + words(extra % 3) + "\n"
    return GOAL + APPROACH + pad + "\n" + SIZE


# ---- the clean case: the three files and what they need give nothing
r = case("a clean phase", phase(), exact=(0, 0))
s.eq("the clean phase: counts", (r["plans"], r["tasks"]), (1, 3))
case("a clean phase with no premortem and no postmortem", phase(pre=None, post=None), exact=(0, 0))

# ---- the headings of the body, in order
case("plan.md without ## Goal", phase(body=APPROACH + SIZE), ["plan.md: ## Goal: missing"])
case("plan.md without ## Approach", phase(body=GOAL + SIZE), ["plan.md: ## Approach: missing"])
case("plan.md with ## Approach before ## Goal", phase(body=APPROACH + GOAL + SIZE), ["plan.md: ## Approach: comes before ## Goal"])
case("plan.md with no ## Size is fine when nothing warns", phase(body=GOAL + APPROACH), exact=(0, 0))
case("a ## Goal inside a fence is not a heading", phase(body="```\n## Goal\nx\n```\n" + APPROACH + SIZE), ["plan.md: ## Goal: missing"])
case("premortem.md without ## Failure reasons", phase(pre="## Verdict\nok\n\n## Size\nNormal.\n"), ["premortem.md: ## Failure reasons: missing"])
case("premortem.md: ## Size inside a fence is not a heading", phase(pre="## Verdict\nok\n\n## Failure reasons\nNone.\n\n```\n## Size\nx\n```\n"), ["premortem.md: ## Size: missing"])
case("premortem.md with ## Size before ## Verdict", phase(pre="## Size\nNormal.\n\n## Verdict\nok\n\n## Failure reasons\nNone.\n"), ["premortem.md: ## Size: comes before ## Failure reasons"])
for heading in ("Verdict", "Findings", "Criteria", "Checked", "Needs from the owner before executing", "Not found wrong"):
    case("postmortem.md without ## " + heading, phase(post=POST_BODY.replace("## " + heading + "\n", "## Other\n")), ["postmortem.md: ## %s: missing" % heading])
case("postmortem.md with ## Checked before ## Criteria", phase(post=POST_BODY.replace("## Criteria\nC1 and C2 can fail.\n\n## Checked\nthe tests.\n", "## Checked\nthe tests.\n\n## Criteria\nC1 and C2 can fail.\n")),
     ["postmortem.md: ## Checked: comes before ## Criteria"])

# ---- ## Goal: under ten non-empty lines, and short in words
goal = lambda n: "## Goal\n" + "".join("line %d\n\n" % i for i in range(n))
case("## Goal of twelve lines", phase(body=goal(12) + APPROACH + SIZE), ["plan.md: ## Goal: 12 lines, under ten required"])
case("## Goal of ten lines", phase(body=goal(10) + APPROACH + SIZE), ["plan.md: ## Goal: 10 lines, under ten required"])
case("## Goal of nine lines, blanks between them", phase(body=goal(9) + APPROACH + SIZE), exact=(0, 0))
case("## Goal of nine lines in a fence counts them", phase(body="## Goal\n```\n" + "x\n" * 12 + "```\n\n" + APPROACH + SIZE), ["plan.md: ## Goal: 14 lines, under ten required"])
case("## Goal of one line of 200 words", phase(body="## Goal\n" + words(200) + "\n\n" + APPROACH + SIZE), ["plan.md: ## Goal: 200 words, under 150 required"])
case("## Goal of 149 words", phase(body="## Goal\n" + words(149) + "\n\n" + APPROACH + SIZE), exact=(0, 0))

# ---- no edit history
DATE = "-".join(("2001", "01", "02"))  # built, not written: the guard refuses a literal date in an engine file
for line in ("Ajustado el %s con el post-mortem." % DATE, "Revisado el %s." % DATE, "**Adjusted on %s**: scope." % DATE):
    case("history: " + line[:12], phase(body=GOAL + line + "\n\n" + APPROACH + SIZE),
         ['plan.md: body: edit history in the plan (git is the history): "%s"' % re.match(r"\**(\w+ (?:el|on) [\d-]+)", line).group(1)])
case("'Ajustado el' with no date is no history", phase(body=GOAL + APPROACH + "## Size\nAjustado el tamano after the review.\n"), exact=(0, 0))
case("history inside a fence is no history", phase(body=GOAL + APPROACH + "## Size\nNormal.\n```\nAjustado el " + DATE + "\n```\n"), exact=(0, 0))

# ---- ids that nothing defines
case("T9 in the body", phase(body=BODY.replace("T3 after", "T9 after")), ["plan.md: body: T9 is not defined in tasks"])
case("C9 in the body", phase(body=BODY.replace("C2", "C9")), ["plan.md: body: C9 is not defined in criteria"])
case("D9 in the body, no row", phase(body=BODY.replace("D1", "D9")), ["plan.md: body: D9 is not defined in decisions.tsv"])
case("D1 with no decisions.tsv at all", phase(decisions=None), ["plan.md: body: D1 is not defined in decisions.tsv"])
case("an id in a fence is not looked at", phase(body=BODY + "```\nT9 C9 D9\n```\n"), exact=(0, 0))
case("a file name is not an id", phase(body=BODY.replace("D1.", "D1; see `t.py` and `T7.py` and x_T8.")), exact=(0, 0))
case("T1-T3 names both ends", phase(body=BODY.replace("T1 and T2 first, T3 after", "T1-T4 first")), ["plan.md: body: T4 is not defined in tasks"])
sub_decisions = DECISIONS + "day-1\tD2\tnew a\tbecause\t\tchosen\tturn 2\tD1\n"
# still defined (no error about an undefined id); the one warning is the plan check's own, `cites D1, superseded by D2` (it was (0, 0)
# before that warning existed: FAIL: only these: a replaced decision is still defined: got (0, 1), want (0, 0))
case("a replaced decision is still defined", phase(body=BODY.replace("D1.", "D1 and D2."), decisions=sub_decisions),
     warnings=["plan.md: body: cites D1, superseded by D2"], exact=(0, 1))

# ---- citations to a file and line of the main checkout
case("a cite to a file that does not exist", phase(body=BODY + "See `lib/nope.py:3`.\n"), ["plan.md: body: cited file not found: lib/nope.py"])
case("a cite past the end of the file", phase(body=BODY + "See `lib/real.py:90`.\n"), ["plan.md: body: lib/real.py:90 is past its end (40 lines)"])
case("a cite range past the end", phase(body=BODY + "See `lib/real.py:30-41`.\n"), ["plan.md: body: lib/real.py:41 is past its end (40 lines)"])
case("a cite of line zero", phase(body=BODY + "See `lib/real.py:0`.\n"), ["plan.md: body: lib/real.py:0 is not a line"])
case("a cite of the last line", phase(body=BODY + "See `lib/real.py:40` and `docs/note.md:2`.\n"), exact=(0, 0))
case("a cite outside the checkout", phase(body=BODY + "See `../../etc/passwd.txt:1`.\n"), ["plan.md: body: cited file not found: ../../etc/passwd.txt"])
case("a cite in a fence or outside backticks is not looked at", phase(body=BODY + "```\n`lib/nope.py:3`\n```\nAlso lib/nope.py:3 and host.com:443 and `localhost:8080`.\n"), exact=(0, 0))
case("a cite of a file of the phase folder", phase(body=BODY + "See `context.md:2`.\n", extra={"context.md": "a\nb\nc\n"}), exact=(0, 0))
case("a cite past the end of a file of the phase folder", phase(body=BODY + "See `context.md:9`.\n", extra={"context.md": "a\nb\nc\n"}), ["plan.md: body: context.md:9 is past its end (3 lines)"])
d = phase(body=NOCITE + "See `lib/real.py:10`.\n", post=None, in_repo=False)
r = plan.check_phase(d)
s.eq("a cite with no checkout: no error", r["errors"], [])
s.ok("a cite with no checkout: says NOT RUN, NOT ARMED", len(r["warnings"]) == 1 and r["warnings"][0].startswith("plan.md: body: NOT RUN, NOT ARMED: 1 cite(s) not looked at"), repr(r["warnings"]))
s.ok("a cite with no checkout: the command prints it", "NOT RUN, NOT ARMED" in cli(d).stdout and cli(d).returncode == 0, cli(d).stdout)
case("no cite, no checkout: nothing to look at is no warning", phase(body=NOCITE, post=None, in_repo=False), exact=(0, 0))

# ---- the budget of the body, in words
case("3600 words, long lines", phase(body=padded(3600)), exact=(0, 0))
case("3601 words", phase(body=padded(3601)), warnings=["plan.md: body: 3601 words, over 3600: is every line needed?"], exact=(0, 1))
case("4800 words", phase(body=padded(4800)), warnings=["plan.md: body: 4800 words, over 3600: is every line needed?"], exact=(0, 1))
case("4801 words", phase(body=padded(4801)), ["plan.md: body: 4801 words, over the 4800 allowed"])
fenced = GOAL + APPROACH + "```\n" + words(4801) + "\n```\n" + SIZE
case("4801 words in a fence still count", phase(body=fenced), ["plan.md: body: %d words, over the 4800 allowed" % len(fenced.split())])
r = case("450 short lines are 1350 words: lines are not the measure", phase(body=padded(1350, line=False)), exact=(0, 0))
s.ok("the padded body has 450+ lines", len(padded(1350, line=False).splitlines()) > 450)
long = GOAL + APPROACH + ("%s\n" % words(25)) * 150 + SIZE
case("a body of 150 lines of 25 words is over 3600 words", phase(body=long), warnings=["plan.md: body: %d words, over 3600: is every line needed?" % len(long.split())], exact=(0, 1))

# ---- ## Size must say something when the plan warned about its size
five = lambda f: (f["size"].update(tag="small", agents=1), f.update(tasks=[
    {"id": "T%d" % i, "part": 1, "type": "feature", "wave": i, "files": ["f%d.py" % i], "depends_on": ["T%d" % (i - 1)] if i > 1 else [],
     "tests": [], "size": "small", "ui": False} for i in range(1, 6)]))
BAND = "plan.md: tasks: 5 tasks, the small band is 4"
pre_small = dict(PRE, size_tag="small")
case("a band warning and a ## Size with text", phase(five, body=BODY.replace("D1.", "D1 and T5."), pre_fm=pre_small), warnings=[BAND], exact=(0, 1))
case("a band warning and an empty ## Size", phase(five, body=GOAL + APPROACH.replace("T3 after", "T5 after") + "## Size\n\n", pre_fm=pre_small),
     ["plan.md: ## Size: empty, but the plan exceeds the small band (5 tasks, 4 allowed): say why"], [BAND])
case("a band warning and no ## Size", phase(five, body=GOAL + APPROACH.replace("T3 after", "T5 after"), pre_fm=pre_small),
     ["plan.md: ## Size: missing, but the plan exceeds the small band (5 tasks, 4 allowed): say why"], [BAND])
case("a tag that differs from the premortem and an empty ## Size", phase(body=GOAL + APPROACH + "## Size\n", pre_fm=dict(PRE, size_tag="small")),
     ["plan.md: ## Size: empty, but size.tag is normal and premortem.md says small: say why"], ["plan.md: size.tag: normal, but premortem.md says small"])
case("a parts that differs from the premortem and an empty ## Size", phase(body=GOAL + APPROACH + "## Size\n", pre_fm=dict(PRE, parts=2)),
     ["plan.md: ## Size: empty, but size.parts is 1 and premortem.md says 2: say why"], ["plan.md: size.parts: 1, but premortem.md says 2"])
case("a tag that differs from the premortem and a ## Size with text", phase(pre_fm=dict(PRE, size_tag="small")), warnings=["plan.md: size.tag: normal, but premortem.md says small"], exact=(0, 1))
case("an empty ## Size with nothing to say is fine", phase(body=GOAL + APPROACH + "## Size\n"), exact=(0, 0))

# ---- premortem.md: the verdict and its failure reasons
case("premortem ok with a failure reason", phase(pre=PRE_BODY.replace("None.", "- the owner meant X / evidence: D1")),
     ["premortem.md: ## Failure reasons: verdict ok with a failure reason listed"])
case("premortem ok with 'None' as an item", phase(pre=PRE_BODY.replace("None.", "- None.")), exact=(0, 0))
case("premortem objections with no failure reason", phase(pre=PRE_BODY, pre_fm=dict(PRE, verdict="objections")),
     ["premortem.md: ## Failure reasons: verdict objections with no failure reason listed"])
case("premortem objections with a failure reason", phase(pre=PRE_BODY.replace("None.", "1. the owner meant X"), pre_fm=dict(PRE, verdict="objections")), exact=(0, 0))
case("premortem objections: a reason inside a fence is no reason", phase(pre=PRE_BODY.replace("None.", "```\n- x\n```"), pre_fm=dict(PRE, verdict="objections")),
     ["premortem.md: ## Failure reasons: verdict objections with no failure reason listed"])
case("premortem back-to-discuss with a reason", phase(pre=PRE_BODY.replace("None.", "- the plan would build another thing"), pre_fm=dict(PRE, verdict="back-to-discuss")), exact=(0, 0))

# ---- postmortem.md: each finding has a severity and evidence
F = "## Findings\n"


def findings(*items, verdict="ok"):
    return dict(post=POST_BODY.replace("## Findings\nNone.\n", F + "".join(i + "\n" for i in items)), post_fm=dict(POST, verdict=verdict))


GOOD_B = "- blocker the store must keep the file / evidence: lib/real.py:3 / owner: planner / hint: split it"
case("a finding with no severity", phase(**findings("- the store may break / evidence: lib/real.py:3", verdict="objections")),
     ["postmortem.md: findings[1]: no severity (blocker, warning or info first)"])
case("a finding with no evidence", phase(**findings("- warning the store may break / owner: planner", verdict="objections")),
     ["postmortem.md: findings[1]: no evidence: field"])
case("a finding with an empty evidence", phase(**findings("- warning the store may break / evidence: / owner: planner", verdict="objections")),
     ["postmortem.md: findings[1]: evidence: empty"])
case("the second finding is the one", phase(**findings(GOOD_B, "- info all fine", verdict="objections")),
     ["postmortem.md: findings[2]: no evidence: field"])
case("a blocker with unproven evidence", phase(**findings("- blocker x must hold / evidence: unproven: no run / owner: p", verdict="objections")),
     ["postmortem.md: findings[1]: unproven evidence on a blocker"])
case("a warning with unproven evidence", phase(**findings("- warning x must hold / evidence: Unproven: no run", verdict="objections")),
     ["postmortem.md: findings[1]: unproven evidence on a warning"])
case("an info with unproven evidence is fine", phase(**findings("- info x may hold / evidence: unproven: no run")), exact=(0, 0))
case("a finding over two lines, nested bullet inside", phase(**findings("- **blocker** x must hold /\n  evidence: lib/real.py:3\n  - a nested point\n  / owner: p", verdict="objections")), exact=(0, 0))
case("findings in a fence are not findings", phase(**findings("```\n- x\n```")), exact=(0, 0))
case("'None' as a finding is no finding", phase(**findings("- None.")), exact=(0, 0))

# ---- the verdict matches the findings
case("postmortem ok with a blocker", phase(**findings(GOOD_B)), ["postmortem.md: findings: verdict ok with a blocker finding"])
case("postmortem ok with a warning", phase(**findings("- warning x / evidence: lib/real.py:3")), ["postmortem.md: findings: verdict ok with a warning finding"])
case("postmortem ok with an info", phase(**findings("- info x / evidence: lib/real.py:3")), exact=(0, 0))
case("postmortem objections with a blocker", phase(**findings(GOOD_B, verdict="objections")), exact=(0, 0))
case("postmortem objections with only an info", phase(**findings("- info x / evidence: lib/real.py:3", verdict="objections")),
     ["postmortem.md: findings: verdict objections without a blocker or warning finding"])
case("postmortem objections with no findings", phase(post_fm=dict(POST, verdict="objections")), ["postmortem.md: findings: verdict objections without a blocker or warning finding"])
case("postmortem back-to-discuss with no findings", phase(post_fm=dict(POST, verdict="back-to-discuss")), exact=(0, 0))

# ---- security_review by protected path
ci = lambda f: task(f, "T1").update(files=[".github/workflows/ci.yml"])
case("a protected path with security_review false", phase(ci),
     ["postmortem.md: security_review: task T1 touches a protected path (.github/workflows/**): security_review must be true"])
case("a protected path with security_review true", phase(ci, post_fm=dict(POST, security_review=True)), exact=(0, 0))
case("a protected folder", phase(lambda f: task(f, "T2").update(files=["./.github/workflows/"])),
     ["postmortem.md: security_review: task T2 touches a protected path (.github/workflows/**): security_review must be true"])
case("a path that is not protected", phase(lambda f: task(f, "T1").update(files=[".github/CODEOWNERS", "src/workflows/x.yml"])), exact=(0, 0))
case("a protected path and no postmortem yet", phase(ci, post=None), exact=(0, 0))
d = phase(ci, in_repo=False)
r = plan.check_phase(d)
s.ok("a protected path check with no configuration: NOT RUN, NOT ARMED, no error", r["errors"] == [] and any(
    w.startswith("postmortem.md: security_review: NOT RUN, NOT ARMED") for w in r["warnings"]), repr(r))

# ---- subphases: each plan file is checked, the ids of its own tasks, the decisions of the phase
SUB = lambda part, n: {"size": {"tag": "small", "parts": 1, "agents": 1}, "criteria": base()["criteria"], "not_built": [], "later": [],
                       "tasks": [{"id": "S%d" % n, "part": part, "type": "feature", "wave": 1, "files": ["s%d.py" % n], "depends_on": [],
                                  "tests": [], "size": "small", "ui": False}]}
top = lambda f: f.update(size={"tag": "normal", "parts": 2, "agents": 1}, tasks=[
    {"id": "T1", "part": 1, "subphase": "01.1-a", "type": "feature", "wave": 1, "files": ["a.py"], "depends_on": [], "tests": [], "size": "small", "ui": False},
    {"id": "T2", "part": 2, "subphase": "01.2-b", "type": "feature", "wave": 2, "files": ["b.py"], "depends_on": ["T1"], "tests": [], "size": "small", "ui": False}])
SBODY = GOAL + "## Approach\nS1 first, for C1 and D1.\n\n" + SIZE
subs = lambda b1=SBODY, b2=SBODY.replace("S1", "S2"): {"01.1-a/plan.md": fm_text(SUB(1, 1)) + b1, "01.2-b/plan.md": fm_text(SUB(2, 2)) + b2}
case("two subphases, clean", phase(top, body=GOAL + "## Approach\nT1, then T2; D1 and C1.\n\n" + SIZE, pre_fm=dict(PRE, parts=2), extra=subs()), exact=(0, 0))
case("a subphase without ## Approach", phase(top, body=GOAL + "## Approach\nT1, then T2; D1 and C1.\n\n" + SIZE, pre_fm=dict(PRE, parts=2), extra=subs(b1=GOAL + SIZE)),
     ["01.1-a/plan.md: ## Approach: missing"])
case("a subphase citing D9", phase(top, body=GOAL + "## Approach\nT1, then T2; D1 and C1.\n\n" + SIZE, pre_fm=dict(PRE, parts=2), extra=subs(b2=SBODY.replace("D1", "D9"))),
     ["01.2-b/plan.md: body: D9 is not defined in decisions.tsv"])

s.done()
