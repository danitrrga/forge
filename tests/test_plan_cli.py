#!/usr/bin/env python3
"""`fwx plan brief` and `fwx plan status` (lib/fwx/plan_step.py): the agent and model of a step, its brief, and what a
finished step says about itself.

Every case builds a toy repo (tests/helpers.toy_repo) with a phase folder under `.fwx/`, writes the `stage` rows with
`state.append_audit`, and runs the real `bin/fwx`. The brief of the three steps, its absolute paths (also when launched from a
worktree, and when `dir` is the worktree's copy), `model` equal to `fwx model`, no model name in a brief, `--head` without the
brief, the owner-accepted ids, the round starting again after a `discuss` row, `critique_rounds_unattended: 1`, and every
row of the status table of the plan's Appendix C, supervised and unattended.

Seen red with plan_step.py written but `fwx plan` knowing only `check` (362 of 455 checks failed, the first:
  FAIL: status premortem missing (): exit: got 2, want 0
  FAIL: status premortem missing (): status: got None, want 'failed')

Added by 3.3 U4 (a U2 file), seen red against plan_step.py before the change:
  FAIL: brief plan: names the plan template of the plugin: <the brief>

Controls, each seen red on a copy of the repo with one thing changed (FAIL lines quoted):
  - a `status` without the cap on unattended rounds (the control the plan names: it would let the factory loop a third time):
      FAIL: status postmortem unattended objections round 2: status: got 'done', want 'needs-owner'
      FAIL: status postmortem unattended, critique_rounds_unattended 1, round 1: status: got 'done', want 'needs-owner'
  - a critique_round that does not start again at a `discuss` row (5 FAIL lines):
      FAIL: round after a discuss row: got 3, want 1
  - a premortem.md `round` that is not compared with the rounds counted:
      FAIL: status premortem round 2 in the file, 1 counted: status: got 'done', want 'failed'
  - an unattended `back-to-discuss` that stays `back-to-discuss`:
      FAIL: status premortem unattended back-to-discuss: status: got 'back-to-discuss', want 'needs-owner'
  - an unattended postmortem `ok` that does not read `## Needs from the owner before executing`:
      FAIL: status postmortem unattended ok with a need: status: got 'done', want 'needs-owner'
  - the folder given used as it is, not moved to its place in the main checkout (20 FAIL lines):
      FAIL: status premortem given the worktree's copy: status: got 'failed', want 'done'
      FAIL: status given the worktree's copy: phase_dir is the main checkout's: got '<worktree>/.fwx/...', want '<main>/.fwx/...'
  - the model written as a literal in place of config.model (8 FAIL lines):
      FAIL: head premortem: model is the pre-mortem's normal one: got 'sonnet', want 'fable'
      FAIL: head planner small: model: got 'sonnet', want 'haiku'
  - the owner-accepted ids (`source` postmortem r<N>) left out of the plan brief:
      FAIL: brief plan supervised with a postmortem: names D2 (source: postmortem r1): <the brief>
  - a plan that starts with no premortem.md after the premortem stage:
      FAIL: brief plan after the premortem stage with no premortem.md: exit: got 0, want 1
  - `--head` printing the brief after the three keys (21 FAIL lines):
      FAIL: head premortem: keys: got [], want ['agent', 'model', 'round']
  - a brief launched in a phase that never entered the step's stage (round 0):
      FAIL: brief postmortem in a phase that is not at that stage: exit: got 0, want 1
  - a `--diff` value that is not checked:
      FAIL: brief --diff 'main': exit: got 0, want 2
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
from fwx import plan_step, state  # noqa: E402

s = helpers.Suite()
MODEL_NAME = re.compile(r"\b(opus|sonnet|haiku|fable)\b", re.I)


def front(data, body):
    return "---\n" + json.dumps(data, indent=2) + "\n---\n" + body


def good_plan(tasks=None):
    t = {"id": "T1", "part": 1, "type": "feature", "wave": 1, "files": ["a.py"], "depends_on": [], "tests": [], "size": "small", "ui": False}
    return front({"size": {"tag": "small", "parts": 1, "agents": 1},
                  "criteria": [{"id": "C1", "text": "it works", "measure": "t.py exits 0"},
                               {"id": "C2", "text": "it is fast", "measure": "time t.py"}],
                  "tasks": tasks or [t], "not_built": [], "later": []},
                 "## Goal\nBuild it.\n\n## Approach\nT1; carries out D1.\n\n## Size\nSmall.\n")


def premortem(verdict="ok", rnd=1, size="small", parts=1):
    return front({"verdict": verdict, "size_tag": size, "parts": parts, "round": rnd},
                 "## Verdict\n%s\n\n## Failure reasons\n%s\n\n## Size\n%s.\n"
                 % (verdict, "- the owner meant something else" if verdict != "ok" else "None.", size))  # U8: the reasons match the verdict


def postmortem(verdict="ok", rnd=1, needs="None"):
    return front({"verdict": verdict, "security_review": False, "round": rnd},
                 "## Verdict\n%s\n\n## Findings\n%s\n\n## Criteria\nC1 holds.\n\n## Checked\nAll.\n\n"
                 "## Needs from the owner before executing\n%s\n\n## Not found wrong\nNothing.\n"
                 % (verdict, "- blocker C1 must hold / evidence: a.py:1" if verdict == "objections" else "None.", needs))  # U8: the findings match the verdict


DECISIONS = ("date\tid\tdecision\twhy\trejected\tsupport\tsource\tsupersedes\n"
             "when\tD1\tuse files\tsimple\t\tchosen\t\t\n"
             "when\tD2\tkeep the cap\tthe owner said so\t\tapproved\tpostmortem r1\t\n"
             "when\tD3\tno database\tguess\t\tagent-assumption\t\t\n"
             "when\tD4\tEnglish only\tnot asked\t\tunexamined\t\t\n"
             "when\tD5\tolder\told\t\tchosen\t\tD1\n")

CONFIG = {"schema": 1, "critique_rounds_unattended": 2,
          "models": {"pre-mortem": {"normal": "fable"}, "planner": {"small": "haiku", "normal": "sonnet", "big": "opus"},
                     "post-mortem": {"small": "haiku", "normal": "fable", "big": "opus"}}}


def world(files=None, config=None, tracked=False):
    """A toy repo with a phase folder; returns (repo, phase dir)."""
    repo = helpers.toy_repo()
    helpers.write(repo, ".claude/fwx.json", json.dumps(config or CONFIG))
    ph = os.path.join(repo, ".fwx", "milestones", "v1", "phases", "01-thing")
    helpers.write(ph, "context.md", "# context\n")
    helpers.write(ph, "decisions.tsv", DECISIONS)
    helpers.write(repo, ".fwx/PROJECT.md", "# project\n")
    for rel, text in (files or {}).items():
        helpers.write(ph, rel, text)
    if tracked:
        helpers.git(repo, "add", "-A", "-f")
        helpers.git(repo, "commit", "-q", "-m", "state")
    return repo, ph


def rows(repo, ph, *dests):
    for d in dests:
        state.append_audit(ph, "stage", detail=d, cwd=repo)


def this_round(text):
    m = re.search(r"## This round\n(.*?)(?=\n## |\Z)", text, re.S)
    return m.group(1) if m else ""


def first(text):
    return text.splitlines()[0] if text else ""


def run(cwd, *args):
    return helpers.fwx(cwd, "plan", *args)


def jline(r):
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {}


def status(label, repo, ph, step, want, *flags, first=None, cwd=None):
    r = run(cwd or repo, "status", ph, step, *flags)
    d = jline(r)
    s.eq("status %s: exit" % label, r.returncode, 0)
    s.eq("status %s: status" % label, d.get("status"), want)
    s.eq("status %s: one line" % label, len(r.stdout.strip().splitlines()), 1)
    s.eq("status %s: keys" % label, sorted(d), ["phase_dir", "reason", "status"])
    if first is not None:
        s.eq("status %s: the first word of the reason is the verdict" % label, (d.get("reason") or "").split(" ")[0].rstrip(":;,"), first)
    return d


# ---------------------------------------------------------------- critique_round

repo, ph = world()
s.eq("round with no rows", plan_step.critique_round(ph, "premortem"), 0)
rows(repo, ph, "premortem", "planning", "postmortem", "planning", "postmortem")
s.eq("round premortem", plan_step.critique_round(ph, "premortem"), 1)
s.eq("round postmortem counts only its own rows", plan_step.critique_round(ph, "postmortem"), 2)
s.eq("round planning", plan_step.critique_round(ph, "planning"), 2)
rows(repo, ph, "discuss", "premortem", "planning", "postmortem")
s.eq("round after a discuss row", plan_step.critique_round(ph, "postmortem"), 1)
s.eq("round of a stage not entered since the discuss", plan_step.critique_round(ph, "executing"), 0)
state.append_audit(ph, "round", detail="use discuss", cwd=repo)
state.append_audit(ph, "evidence", sha="abc", rc="1")
s.eq("round ignores round and evidence rows", plan_step.critique_round(ph, "postmortem"), 1)

# ---------------------------------------------------------------- status: the table

# every step: a file that is missing, does not validate or has another round
repo, ph = world()
rows(repo, ph, "premortem")
for step in ("premortem", "plan", "postmortem"):
    for flag in ((), ("--unattended",)):
        status("%s missing %s" % (step, flag), repo, ph, step, "failed", *flag)
repo, ph = world({"premortem.md": "no frontmatter\n", "plan.md": "---\nnot json\n---\n", "postmortem.md": "---\n{}\n---\n"})
rows(repo, ph, "premortem", "planning", "postmortem")
for step in ("premortem", "plan", "postmortem"):
    d = status("%s invalid" % step, repo, ph, step, "failed")
    s.ok("status %s invalid: the reason names the file" % step, ("%s.md" % step) in d.get("reason", ""), d.get("reason", ""))

# the premortem
for verdict, sup, unat in (("ok", "done", "done"), ("objections", "done", "done"),
                           ("back-to-discuss", "back-to-discuss", "needs-owner")):
    repo, ph = world({"premortem.md": premortem(verdict)})
    rows(repo, ph, "premortem")
    status("premortem %s" % verdict, repo, ph, "premortem", sup, first=verdict)
    status("premortem unattended %s" % verdict, repo, ph, "premortem", unat, "--unattended", first=verdict if unat == "done" else None)
repo, ph = world({"premortem.md": premortem("ok", rnd=2)})
rows(repo, ph, "premortem")
d = status("premortem round 2 in the file, 1 counted", repo, ph, "premortem", "failed")
s.ok("premortem round mismatch: the reason says both rounds", "2" in d.get("reason", "") and "1" in d.get("reason", ""), d.get("reason", ""))
repo, ph = world({"premortem.md": premortem("ok", rnd=1)})
rows(repo, ph, "premortem", "discuss", "premortem")
status("premortem round 1 after a discuss row", repo, ph, "premortem", "done")
repo, ph = world({"premortem.md": premortem("ok", rnd=2)})
rows(repo, ph, "premortem", "discuss", "premortem")
status("premortem round 2 in the file after a discuss row", repo, ph, "premortem", "failed")

# the plan
repo, ph = world({"plan.md": good_plan()})
rows(repo, ph, "planning")
for flag in ((), ("--unattended",)):
    status("plan clean %s" % (flag,), repo, ph, "plan", "done", *flag)
bad = good_plan([{"id": "T1", "part": 1, "type": "feature", "wave": 1, "files": [], "depends_on": [], "tests": [], "size": "small", "ui": False}])
repo, ph = world({"plan.md": bad})
rows(repo, ph, "planning")
for flag in ((), ("--unattended",)):
    d = status("plan with an error %s" % (flag,), repo, ph, "plan", "failed", *flag)
    s.ok("plan with an error: the reason carries the checker's line", "tasks[T1].files: empty" in d.get("reason", ""), d.get("reason", ""))

# the postmortem
for verdict, sup, unat in (("ok", "done", "done"), ("back-to-discuss", "back-to-discuss", "needs-owner")):
    repo, ph = world({"postmortem.md": postmortem(verdict)})
    rows(repo, ph, "postmortem")
    status("postmortem %s" % verdict, repo, ph, "postmortem", sup, first=verdict)
    status("postmortem unattended %s" % verdict, repo, ph, "postmortem", unat, "--unattended")
for needs in ("None", "none.", "None.\n"):
    repo, ph = world({"postmortem.md": postmortem("ok", needs=needs)})
    rows(repo, ph, "postmortem")
    status("postmortem unattended ok, needs %r" % needs, repo, ph, "postmortem", "done", "--unattended")
repo, ph = world({"postmortem.md": postmortem("ok", needs="Which database to use.")})
rows(repo, ph, "postmortem")
status("postmortem supervised ok with a need", repo, ph, "postmortem", "done")
status("postmortem unattended ok with a need", repo, ph, "postmortem", "needs-owner", "--unattended")
repo, ph = world({"postmortem.md": front({"verdict": "ok", "security_review": False, "round": 1}, "## Verdict\nok\n")})
rows(repo, ph, "postmortem")
status("postmortem unattended ok with no needs section", repo, ph, "postmortem", "needs-owner", "--unattended")

# the cap of unattended rounds: objections in round 1 go to the planner, in round 2 to the owner
repo, ph = world({"postmortem.md": postmortem("objections", rnd=1)})
rows(repo, ph, "postmortem")
status("postmortem supervised objections", repo, ph, "postmortem", "done", first="objections")
status("postmortem unattended objections round 1", repo, ph, "postmortem", "done", "--unattended", first="objections")
repo, ph = world({"postmortem.md": postmortem("objections", rnd=2)})
rows(repo, ph, "postmortem", "planning", "postmortem")
status("postmortem supervised objections round 2", repo, ph, "postmortem", "done")
status("postmortem unattended objections round 2", repo, ph, "postmortem", "needs-owner", "--unattended")
one = dict(CONFIG, critique_rounds_unattended=1)
repo, ph = world({"postmortem.md": postmortem("objections", rnd=1)}, config=one)
rows(repo, ph, "postmortem")
status("postmortem unattended, critique_rounds_unattended 1, round 1", repo, ph, "postmortem", "needs-owner", "--unattended")
three = dict(CONFIG, critique_rounds_unattended=3)
repo, ph = world({"postmortem.md": postmortem("objections", rnd=2)}, config=three)
rows(repo, ph, "postmortem", "planning", "postmortem")
status("postmortem unattended, critique_rounds_unattended 3, round 2", repo, ph, "postmortem", "done", "--unattended")

# a worktree finds the same folder; a folder that is not one cannot be read
repo, ph = world({"premortem.md": premortem("ok")}, tracked=True)
rows(repo, ph, "premortem")
wt = helpers.add_worktree(repo, "job")
d = status("premortem launched from a worktree", repo, ph, "premortem", "done", cwd=wt)
s.eq("status: phase_dir is the main checkout's", d.get("phase_dir"), ph)
d = status("premortem given the worktree's copy", repo, os.path.join(wt, ".fwx", "milestones", "v1", "phases", "01-thing"), "premortem", "done")
s.eq("status given the worktree's copy: phase_dir is the main checkout's", d.get("phase_dir"), ph)
for args, label in (((os.path.join(repo, "nope"), "premortem"), "not a folder"), ((ph,), "no step"), ((ph, "plans"), "unknown step"),
                    ((ph, "premortem", "--bogus"), "unknown flag")):
    r = run(repo, "status", *args)
    s.eq("status %s: exit" % label, r.returncode, 2)
    s.ok("status %s: nothing on stdout" % label, r.stdout == "", r.stdout)

# ---------------------------------------------------------------- brief and head

def brief(label, repo, ph, step, *flags, want=0, cwd=None):
    r = run(cwd or repo, "brief", ph, step, *flags)
    s.eq("brief %s: exit" % label, r.returncode, want)
    if want:
        s.ok("brief %s: no brief on stdout" % label, r.stdout == "", r.stdout[:80])
        s.ok("brief %s: stderr says what is missing" % label, r.stderr.strip() != "", r.stderr)
    return r


repo, ph = world({"premortem.md": premortem("objections"), "plan.md": good_plan(), "postmortem.md": postmortem("objections")})
rows(repo, ph, "premortem", "planning", "postmortem")
helpers.write(ph, "research/topic.md", "r\n")
helpers.write(ph, "demo/page.html", "d\n")
helpers.write(repo, ".fwx/durable/identity.md", "i\n")
main_checkout = repo
common = {"PROJECT.md": os.path.join(repo, ".fwx", "PROJECT.md"), "durable/": os.path.join(repo, ".fwx", "durable"),
          "context.md": os.path.join(ph, "context.md"), "decisions.tsv": os.path.join(ph, "decisions.tsv"),
          "research/": os.path.join(ph, "research"), "demo/": os.path.join(ph, "demo"),
          ".claude/fwx.json": os.path.join(repo, ".claude", "fwx.json")}
for step, out_file in (("premortem", "premortem.md"), ("plan", "plan.md"), ("postmortem", "postmortem.md")):
    for flags in ((), ("--unattended",)):
        r = brief("%s %s" % (step, flags), repo, ph, step, *flags)
        t = r.stdout
        for name, p in common.items():
            s.ok("brief %s %s: names %s by its absolute path" % (step, flags, name), p in t, p)
        s.ok("brief %s %s: names the file to write" % (step, flags), os.path.join(ph, out_file) in t)
        s.ok("brief %s %s: no model name" % (step, flags), not MODEL_NAME.search(t), str(MODEL_NAME.search(t)))
        s.ok("brief %s %s: states the mode" % (step, flags), ("unattended" if flags else "supervised") in first(t))
        s.ok("brief %s %s: returns under 100 words" % (step, flags), "under 100 words" in t)
        s.ok("brief %s %s: no relative path to the folder" % (step, flags), not re.search(r"(?<![/\w.])\.fwx/", t), t)
        s.ok("brief %s %s: counts decisions by support" % (step, flags),
             "decisions.tsv, 4 decisions in force: chosen 1, approved 1, unexamined 1, agent-assumption 1." in t, t)
        s.ok("brief %s %s: names the agent-assumption and unexamined ids" % (step, flags), "agent-assumption: D3." in t and "unexamined: D4." in t, t)
        s.ok("brief %s %s: the superseded D1 is not counted" % (step, flags), "D1" not in (re.search(r"decisions\.tsv, [^\n]*\n[^\n]*\n[^\n]*", t) or re.search("D1", "D1")).group(0), t)

# the files of each step
t = brief("premortem files", repo, ph, "premortem").stdout
s.ok("brief premortem: no earlier result listed", "premortem.md:" not in t and "plan.md:" not in t, t)
t = brief("plan files", repo, ph, "plan").stdout
s.ok("brief plan: lists premortem.md", "- premortem.md: %s" % os.path.join(ph, "premortem.md") in t, t)
s.ok("brief plan: lists the last postmortem.md", os.path.join(ph, "postmortem.md") in t, t)
# the plan template (3.3 U4): only the planner's brief names it, as an absolute path of the plugin that exists
tpl = os.path.join(ROOT, "templates", "phase", "plan.md")
s.ok("brief plan: names the plan template of the plugin", "- plan.md template: %s" % tpl in t and os.path.isfile(tpl), t)
for step in ("premortem", "postmortem"):
    s.ok("brief %s: does not name the plan template" % step, "template" not in brief("%s template" % step, repo, ph, step).stdout)
t = brief("postmortem files", repo, ph, "postmortem").stdout
for name in ("premortem.md", "plan.md", "postmortem.md"):
    s.ok("brief postmortem: lists %s" % name, "- %s" % name in t or os.path.join(ph, name) in t, t)
sub = os.path.join(ph, "01.1-part")
helpers.write(sub, "plan.md", good_plan())
t = brief("postmortem with a subphase", repo, ph, "postmortem").stdout
s.ok("brief postmortem: lists each subphase's plan.md", os.path.join(sub, "plan.md") in t, t)
os.remove(os.path.join(sub, "plan.md"))
os.rmdir(sub)

# the variants
t = brief("plan supervised with a postmortem", repo, ph, "plan").stdout
s.ok("brief plan supervised with a postmortem: names D2 (source: postmortem r1)", "D2" in this_round(t), t)
s.ok("brief plan supervised with a postmortem: names only the accepted ids", not re.search(r"D[3-5]", this_round(t)), t)
s.ok("brief plan supervised: does not hand the blockers rule to a planner with an owner", plan_step.REPLAN_UNATTENDED not in t, t)
s.ok("brief plan with a postmortem: the counts of the plan being replaced", "1 plan file(s): 1 tasks, 1 waves, 1 parts; 0 errors" in t, t)
t = brief("plan unattended with a postmortem", repo, ph, "plan", "--unattended").stdout
s.ok("brief plan unattended with a postmortem: blockers and warnings", plan_step.REPLAN_UNATTENDED in t, t)
s.ok("brief plan unattended with a postmortem: the counts of the plan being replaced", "1 plan file(s): 1 tasks, 1 waves, 1 parts; 0 errors" in t, t)
s.ok("brief plan unattended with a postmortem: no premortem rule (the planner already met it)", plan_step.PREMORTEM_UNATTENDED not in t, t)

repo2, ph2 = world({"premortem.md": premortem("objections")})
rows(repo2, ph2, "premortem", "planning")
t = brief("plan unattended after premortem objections", repo2, ph2, "plan", "--unattended").stdout
s.ok("brief plan unattended after premortem objections: addresses them", plan_step.PREMORTEM_UNATTENDED in t, t)
t = brief("plan supervised after premortem objections", repo2, ph2, "plan").stdout
s.ok("brief plan supervised after premortem objections: no unattended rule", plan_step.PREMORTEM_UNATTENDED not in t, t)
repo3, ph3 = world({"premortem.md": premortem("ok")})
rows(repo3, ph3, "premortem", "planning")
t = brief("plan unattended after a clean premortem", repo3, ph3, "plan", "--unattended").stdout
s.ok("brief plan unattended after a clean premortem: nothing to address", plan_step.PREMORTEM_UNATTENDED not in t and "## This round" not in t, t)

t = brief("postmortem", repo, ph, "postmortem").stdout
s.ok("brief postmortem: carries the checker's count line", "checked 1 plan file(s): 1 tasks, 1 waves, 1 parts; 0 errors, " in t, t)
s.ok("brief postmortem: tells it not to repeat the checker", "do not repeat" in t, t)
s.ok("brief postmortem: no diff without --diff", "git diff" not in t, t)
t = brief("postmortem --diff", repo, ph, "postmortem", "--diff", "main..job/x").stdout
s.ok("brief postmortem --diff: names the diff to review against", "git diff main..job/x" in t, t)
for bad_diff in ("main", "-x..y", "a..b;rm", "a b..c"):
    r = run(repo, "brief", ph, "postmortem", "--diff", bad_diff)
    s.eq("brief --diff %r: exit" % bad_diff, r.returncode, 2)
s.eq("brief --diff on another step: exit", run(repo, "brief", ph, "plan", "--diff", "a..b").returncode, 2)
s.eq("brief --diff without a value: exit", run(repo, "brief", ph, "postmortem", "--diff").returncode, 2)

# the round
repo4, ph4 = world({"premortem.md": premortem("ok")})
rows(repo4, ph4, "premortem", "planning", "postmortem", "planning", "postmortem")
helpers.write(ph4, "plan.md", good_plan())
t = brief("postmortem round 2", repo4, ph4, "postmortem").stdout
s.ok("brief postmortem: round 2", "round 2" in first(t) and '"round": 2' in t, t)
rows(repo4, ph4, "discuss", "premortem")
t = brief("premortem after a discuss row", repo4, ph4, "premortem").stdout
s.ok("brief premortem: the round starts again at 1", "round 1" in first(t) and '"round": 1' in t, t)

# --head: the three keys, and no brief
for step, agent in (("premortem", "fwx:pre-mortem"), ("plan", "fwx:planner"), ("postmortem", "fwx:post-mortem")):
    r = brief("head %s" % step, repo, ph, step, "--head")
    d = jline(r)
    s.eq("head %s: keys" % step, sorted(d), ["agent", "model", "round"])
    s.ok("head %s: stdout is the three keys only" % step, len(r.stdout.strip().splitlines()) == 1 and "phase folder" not in r.stdout.lower(), r.stdout)
    s.eq("head %s: agent" % step, d.get("agent"), agent)
    s.eq("head %s: round" % step, d.get("round"), 1)

# the model comes from the configuration: role and size
def model_of(cwd, role, size):
    return helpers.fwx(cwd, "model", role, size).stdout.strip()


s.eq("head premortem: model is the pre-mortem's normal one", jline(run(repo, "brief", ph, "premortem", "--head")).get("model"), "fable")
s.eq("head premortem: equal to fwx model", model_of(repo, "pre-mortem", "normal"), "fable")
for tag, want in (("small", "haiku"), ("normal", "sonnet"), ("big", "opus")):
    r5, p5 = world({"premortem.md": premortem("ok", size=tag), "plan.md": good_plan()})
    rows(r5, p5, "premortem", "planning", "postmortem")
    s.eq("head planner %s: model" % tag, jline(run(r5, "brief", p5, "plan", "--head")).get("model"), want)
    s.eq("head planner %s: equal to fwx model" % tag, model_of(r5, "planner", tag), want)
    pm = {"small": "haiku", "normal": "fable", "big": "opus"}[tag]
    s.eq("head post-mortem %s: model" % tag, jline(run(r5, "brief", p5, "postmortem", "--head")).get("model"), pm)
    s.eq("head post-mortem %s: equal to fwx model" % tag, model_of(r5, "post-mortem", tag), pm)
# a configuration that changes the model changes the head
r5, p5 = world({"premortem.md": premortem("ok", size="big")}, config={"schema": 1, "models": {"planner": {"big": "fable"}}})
rows(r5, p5, "premortem", "planning")
s.eq("head planner big, configured fable", jline(run(r5, "brief", p5, "plan", "--head")).get("model"), "fable")
# the mini plan: no premortem.md and no premortem stage, so the size is small
r6, p6 = world({})
rows(r6, p6, "planning")
s.eq("head planner with no premortem (a mini plan): small", jline(run(r6, "brief", p6, "plan", "--head")).get("model"), "haiku")
t = brief("plan, a mini plan", r6, p6, "plan").stdout
s.ok("brief plan, a mini plan: lists no premortem.md", "premortem.md" not in t, t)

# a launch from a worktree names the main checkout's files
repo7, ph7 = world({"premortem.md": premortem("ok"), "plan.md": good_plan()}, tracked=True)
rows(repo7, ph7, "premortem", "planning", "postmortem")
wt = helpers.add_worktree(repo7, "job")
wph = os.path.join(wt, ".fwx", "milestones", "v1", "phases", "01-thing")
for label, cwd, given in (("from a worktree, given the main checkout's folder", wt, ph7), ("from a worktree, given its own copy", wt, wph),
                          ("from the main checkout, given the worktree's copy", repo7, wph)):
    for step in ("premortem", "plan", "postmortem"):
        t = brief("%s %s" % (step, label), repo7, given, step, cwd=cwd).stdout
        s.ok("brief %s: names the main checkout's context.md" % label, os.path.join(ph7, "context.md") in t, t)
        s.ok("brief %s: names the main checkout's decisions.tsv" % label, os.path.join(ph7, "decisions.tsv") in t, t)
        s.ok("brief %s: never names the worktree" % label, wt not in t, t)

# ---------------------------------------------------------------- brief: what the step needs
repo8, ph8 = world({"premortem.md": premortem("ok"), "plan.md": good_plan()})
rows(repo8, ph8, "premortem", "planning", "postmortem")
os.remove(os.path.join(ph8, "context.md"))
for step in ("premortem", "plan", "postmortem"):
    r = brief("%s with no context.md" % step, repo8, ph8, step, want=1)
    s.ok("brief %s with no context.md: names the file" % step, "context.md" in r.stderr, r.stderr)
    brief("%s --head with no context.md" % step, repo8, ph8, step, "--head", want=1)

repo9, ph9 = world({})
rows(repo9, ph9, "premortem", "planning")
r = brief("plan after the premortem stage with no premortem.md", repo9, ph9, "plan", want=1)
s.ok("brief plan with no premortem.md: names the file", "premortem.md" in r.stderr, r.stderr)
repo9, ph9 = world({"premortem.md": "---\n{}\n---\n"})
rows(repo9, ph9, "premortem", "planning")
r = brief("plan with an invalid premortem.md", repo9, ph9, "plan", want=1)
s.ok("brief plan with an invalid premortem.md: the reason is the checker's", r.stderr.count("premortem.md: ") >= 1, r.stderr)
brief("postmortem with an invalid premortem.md", repo9, ph9, "postmortem", want=1)
repo9, ph9 = world({})
rows(repo9, ph9, "postmortem")
brief("postmortem with no plan.md", repo9, ph9, "postmortem", want=1)
repo9, ph9 = world({"plan.md": bad})
rows(repo9, ph9, "postmortem")
r = brief("postmortem with an invalid plan.md", repo9, ph9, "postmortem", want=1)
s.ok("brief postmortem with an invalid plan.md: names the field", "tasks[T1].files" in r.stderr, r.stderr)
repo9, ph9 = world({"plan.md": good_plan()})
r = brief("postmortem in a phase that is not at that stage", repo9, ph9, "postmortem", want=1)
s.ok("brief with no stage row: says which `fwx stage` to run", "fwx stage" in r.stderr and "postmortem" in r.stderr, r.stderr)

# usage and cannot-run
for args, label in (((), "nothing"), ((ph,), "no step"), ((ph, "plans"), "unknown step"), ((ph, "plan", "--bogus"), "unknown flag"),
                    ((os.path.join(repo, "nope"), "plan"), "not a folder")):
    r = run(repo, "brief", *args)
    s.eq("brief %s: exit" % label, r.returncode, 2)
    s.ok("brief %s: nothing on stdout" % label, r.stdout == "", r.stdout)
nogit = helpers.mkdtemp("fwx-nogit-")
r = run(nogit, "status", nogit, "premortem")
s.eq("status outside a git repository: exit", r.returncode, 2)
r = helpers.fwx(repo, "plan", "check", ph)
s.ok("`plan check` is still there", r.returncode in (0, 1) and "checked" in r.stdout, r.stdout + r.stderr)
s.ok("plan help names the three", all(w in run(repo).stderr for w in ("check", "brief", "status")), run(repo).stderr)

s.done()
