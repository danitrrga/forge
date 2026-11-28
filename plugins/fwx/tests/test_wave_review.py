#!/usr/bin/env python3
r"""`fwx wave review` and `fwx wave findings` (09.5 T53): lib/fwx/execute/review.py, lib/fwx/execute/brief.py, lib/fwx/commands/wave.py,
lib/fwx/routes.py.

A review pass is read by two commands instead of reviewPass() of workflows/execute.js:
  wave review --part-dir D --run R --from A --to B [--security]   writes the reviewer's brief (and the security reviewer's when
      `--security`, the post-mortem's `security_review` or a protected path of the last final merge asks for it) and numbers the pass
      (r1, r2 ...); `next` is `launch`.
  wave findings --run R --report LINE...   reads each reviewer's report from the last line of its reply (readReview, validFinding and
      the criteria rule of execute.js), numbers the findings per pass (`r1-F1`), turns a reviewer's `outside` items into findings, and
      says `next`: `relaunch` (a miss, once), `stop` (a second miss), `fix` (the fixer's brief, ids for `wave merge --findings`),
      `verify` (the verifier's brief: only above three items, D10, the one behaviour that is not a port) or `done`.
  wave findings --run R --verdicts LINE   routes each id by the verifier's verdict: fix, consider, note, dismissed, and a large
      `outside` item to `file`; `next` is `fix` when any is left to fix, `done` otherwise (`owner` when the last final merge named a
      protected path, as the flow ends in execute.js).

Builds a toy repo (tests/test_wave_prepare.py `Scene`) and writes each fake reviewer's `.fwx-agent/<run>/<unit>/report.json`; the commands
run through `bin/fwx`. Nothing here reads the real HOME or configuration. The two commands record their results in the run's own files
(`<n>-review.json`, `<n>-findings.json`), from which the next call reads the pass, the items and the misses.

Seen red before the code existed (python3 tests/test_wave_review.py: `review` and `findings` were no verbs of `wave`, `fwx wave` read
them as the summary's first word and exited 2 with its usage):
  FAIL: wave review: exit: got (2, ...), want (0, '')

Controls: each case also runs on a copy of bin/, lib/ and data/ with one line of the code changed (`MUTANTS` below, each `old` must be in
its file exactly once) and must fail with the text in `MUTANTS`. The one the task predicted, the verifier on any item as at d348f8d
(`THRESHOLD = 0`): FAIL: 3 findings go to the fixer -> next verify.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
import test_wave_prepare as wp  # noqa: E402
from test_wave_prepare import mutant_tree, runner  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
RUN = "01-alpha-abc1234-1"
TASKS = [wp.task("T1", 1, ["src/a.py"]), wp.task("T2", 2, ["src/b.py"])]


def J(r):
    try:
        v = json.loads(r.stdout)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def finding(i="F1", line=3, file="src/a.py", severity="medium", **kw):
    f = {"id": i, "file": file, "line": line, "claim": "claim of " + i, "evidence": "evidence of " + i, "severity": severity}
    f.update(kw)
    return f


def outside(where="src/z.py:7", size="small", issue=None, what="z drops the last row", fix="read to the end"):
    return {"where": where, "what": what, "fix": fix, "size": size, "issue": issue}


def criteria(c1="yes", c2="yes"):
    return [{"id": "C1", "met": c1, "evidence": "ran m1"}, {"id": "C2", "met": c2, "evidence": "ran m2"}]


class World:
    """A toy repo with the part's plan, a phase branch with one commit past its start (the diff of a pass), and the reviewers' folders."""

    def __init__(self, security=False, config=None, tasks=None, **kw):
        cfg = {"project": {"checks": ["true"], "checks_quick": ["true"]}}
        cfg["project"].update((config or {}).get("project", {}))
        self.S = wp.Scene(tasks=tasks or TASKS, security=security, config=cfg, **kw)
        self.frm = self.S.head()
        self.S.commit("n.txt", "one more commit")
        self.to = self.S.head()
        self.dirs = {}
        self.env = dict(self.S.env)
        self.runs = os.path.join(self.S.repo, ".git", "fwx", "runs")

    def run_dir(self, run=RUN):
        return os.path.join(self.runs, run)

    def files(self, sub="", run=RUN):
        d = os.path.join(self.run_dir(run), sub)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def review(self, R, *extra, run=RUN, frm=None, to=None):
        r = R(self.S.cwd, "wave", "review", "--part-dir", self.S.part, "--run", run, "--from", frm or self.frm, "--to", to or self.to, *extra, env=self.env)
        return r, J(r) or {}

    def dir_of(self, unit):
        return self.dirs.setdefault(unit, helpers.mkdtemp("fwx-review-"))

    def path(self, unit, run=RUN):
        d = self.dirs.setdefault(unit, helpers.mkdtemp("fwx-review-"))
        return os.path.join(d, ".fwx-agent", run, unit, "report.json")

    def reply(self, unit, findings=(), crit=None, out=(), looked=("src/a.py",), run=RUN, **override):
        """Write the unit's report and return the last line of its reply."""
        rep = {"looked_at": list(looked), "findings": list(findings), "criteria": criteria() if crit is None else crit, "outside": list(out)}
        rep.update(override)
        p = self.path(unit, run)
        helpers.write(os.path.dirname(p), "report.json", json.dumps(rep))
        return "reviewed %s looked_at=%d findings=%d criteria_no=0 criteria_unproven=0" % (p, len(looked), len(findings))

    def find(self, R, *lines, run=RUN, extra=()):
        r = R(self.S.cwd, "wave", "findings", "--run", run, "--report", *lines, *extra, env=self.env)
        return r, J(r) or {}

    def verdicts(self, R, verdicts, run=RUN, unit="r1-verifier", raw=None, severity=None):
        """Write the verifier's report (`verdicts`: {id: verdict}; severity medium, or `severity`: {id: severity}) and ask the command to route it."""
        rows = [{"id": i, "verdict": v, "severity": (severity or {}).get(i, "none" if v == "dismiss" else "medium"), "reason": "because " + i}
                for i, v in (verdicts or {}).items()]
        p = self.path(unit, run)
        helpers.write(os.path.dirname(p), "report.json", json.dumps(raw if raw is not None else {"verdicts": rows}))
        return self.say_verdicts(R, "verdicts %s" % p, run)

    def say_verdicts(self, R, line, run=RUN):
        r = R(self.S.cwd, "wave", "findings", "--run", run, "--verdicts", line, env=self.env)
        return r, J(r) or {}

    def step_file(self, name, rec, run=RUN):
        helpers.write(self.run_dir(run), name, json.dumps(rec))

    def final_merge(self, protected):
        """The run's own last `wave merge --final`, as `wave merge` records it, naming the protected paths of the diff."""
        self.step_file("1-integrate.json", {"step": "integrate", "exit": 0, "args": {"part_dir": self.S.part, "run": RUN, "branches": [], "findings": [], "final": True},
                                            "result": {"ok": True, "protected": list(protected)}})


def nxt(S, label, v, want):
    """The case's check on `next`: the label names what is expected, and says what came instead."""
    return S.ok("%s -> next %s" % (label, v.get("next")), v.get("next") == want, "want next %r, got %r (%s)" % (want, v.get("next"), json.dumps(v)[:220]))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------------------------------- wave review

def case_review(R, S):
    W = World()
    r, v = W.review(R)
    S.eq("wave review: exit", (r.returncode, r.stderr.strip()[:200]), (0, ""))
    nxt(S, "wave review says launch the reviewer", v, "launch")
    S.eq("wave review: the first pass is r1", v.get("pass"), "r1")
    S.eq("wave review: one reviewer, unit r1", [(x.get("role"), x.get("unit")) for x in v.get("reviewers") or []], [("reviewer", "r1")])
    brief = (v.get("reviewers") or [{}])[0].get("brief") or ""
    S.ok("wave review: the reviewer's brief is a file under the run's briefs", os.path.isfile(brief) and os.path.dirname(brief) == os.path.join(W.run_dir(), "briefs"), brief)
    text = read(brief) if os.path.isfile(brief) else ""
    for label, want in (("the diff of the pass", "%s..%s" % (W.frm, W.to)), ("the whole of the run on the first pass", "the whole of this run"),
                        ("the plan's first criterion", "C1"), ("its measure", "m1"), ("the second criterion", "C2"),
                        ("context.md", os.path.join(W.S.phase, "context.md")), ("decisions.tsv", "decisions.tsv"), ("plan.md", os.path.join(W.S.part, "plan.md")),
                        ("the scratch order", "fwx scratch new %s r1" % RUN), ("report.json in the scratch folder", "report.json"),
                        ("the reply line it must give", "reviewed <report path> looked_at=")):
        S.ok("wave review: the reviewer's brief names %s" % label, want in text, "missing %r" % want)
    S.ok("wave review: the reviewer's REPORT says the file-write tool is enough, naming no harness tool (08-steering's wording)", "file-write tool" in text and "Write tool" not in text, text[-600:])
    S.ok("wave review: no security brief without a reason", all("sec" not in f for f in W.files("briefs")), str(W.files("briefs")))
    S.eq("wave review: the call is recorded", W.files(), ["1-review.json", "briefs"])
    # the second pass reviews only the commits of a fix, and its units are r2
    r2, v2 = W.review(R)
    S.eq("a second pass is r2", v2.get("pass"), "r2")
    b1, b2 = [((x.get("reviewers") or [{}])[0]).get("brief") or "" for x in (v, v2)]
    text2 = read(b2) if os.path.isfile(b2) else ""
    S.ok("the second pass reviews the commits of a fix only", "the commits of a fix only" in text2 and "whole of this run" not in text2, text2[:300])
    S.ok("each pass has its own brief", bool(b1) and b1 != b2, "")
    # usage and refusals write nothing
    W2 = World()
    for label, extra in (("a ref that is not a commit", dict(to="nope-not-a-ref")), ("a base that is not a commit", dict(frm="nope-not-a-ref"))):
        r, v = W2.review(R, **extra)
        S.eq("wave review (%s): exit 2, a reason, no JSON" % label, (r.returncode, bool(r.stderr.strip()), r.stdout), (2, True, ""))
    S.eq("wave review: a refused call writes nothing", W2.files(), [])
    for opt in ("--part-dir", "--run", "--from", "--to"):
        args = ["wave", "review", "--part-dir", W2.S.part, "--run", RUN, "--from", W2.frm, "--to", W2.to]
        i = args.index(opt)
        r = R(W2.S.cwd, *(args[:i] + args[i + 2:]), env=W2.env)
        S.eq("wave review without %s: exit 2 with the usage" % opt, (r.returncode, "usage: fwx wave review" in r.stderr, r.stdout), (2, True, ""))
    r = R(helpers.mkdtemp("fwx-nogit-"), "wave", "review", "--part-dir", W2.S.part, "--run", RUN, "--from", W2.frm, "--to", W2.to, env=W2.env)
    S.eq("wave review outside a repository: exit 2", r.returncode, 2)


def case_default_merge(R, S):
    """What the default branch brought in by a merge after the run's base is not the part's: the reviewer's brief names only the
    part's own files; with no merge the brief says nothing of it."""
    W = World()
    helpers.write(W.S.repo, "src/m.py", "m\n")
    helpers.git(W.S.repo, "add", "-A")
    helpers.git(W.S.repo, "commit", "-q", "-m", "master moves")
    helpers.git(W.S.cwd, "merge", "-q", "--no-edit", "master")
    W.S.commit("src/a.py", "the part's own edit")
    r, v = W.review(R, to=W.S.head())
    text = read((v.get("reviewers") or [{}])[0].get("brief") or "")
    S.ok("default merge: the brief restricts the diff to the part's own files", "Review only these files of the diff: n.txt, src/a.py." in text, text[:400])
    S.ok("default merge: master's file is not listed", "src/m.py" not in text, text[:400])
    r, v = World().review(R)
    text = read((v.get("reviewers") or [{}])[0].get("brief") or "")
    S.ok("default merge, control: with no merge the brief has no such line", "Review only" not in text, text[:400])


def case_security(R, S):
    """The security reviewer is launched when asked (`--security`), when the plan's post-mortem asks for it, or when the last final merge
    named a protected path (execute.js: `A.security.needed || st.protected.length > 0`)."""
    def roles(W, *extra):
        r, v = W.review(R, *extra)
        return [(x.get("role"), x.get("unit")) for x in v.get("reviewers") or []], v

    both = [("reviewer", "r1"), ("security-reviewer", "r1-sec")]
    W = World()
    got, v = roles(W, "--security")
    S.eq("--security launches the security reviewer too", got, both)
    sec = next((x["brief"] for x in v.get("reviewers", []) if x["role"] == "security-reviewer"), "")
    text = read(sec) if os.path.isfile(sec) else ""
    S.ok("the security reviewer's brief names its diff, `report.json` and the scratch order for r1-sec",
         all(w in text for w in ("%s..%s" % (W.frm, W.to), "report.json", "fwx scratch new %s r1-sec" % RUN)), text[:300])
    got, _ = roles(World(security=True))
    S.eq("the post-mortem's security_review launches the security reviewer", got, both)
    W = World()
    W.final_merge(["src/secret/k.py"])
    got, v = roles(W)
    S.eq("a protected path of the last final merge launches the security reviewer", got, both)
    S.eq("the protected paths are in the result", v.get("protected"), ["src/secret/k.py"])
    sec = next((x["brief"] for x in v.get("reviewers", []) if x["role"] == "security-reviewer"), "")
    S.ok("the security reviewer's brief names the protected paths", os.path.isfile(sec) and "src/secret/k.py" in read(sec), sec)
    W = World()
    W.final_merge([])
    got, _ = roles(W)
    S.eq("a final merge that named none asks for no security reviewer", got, [("reviewer", "r1")])


# ---------------------------------------------------------------------------------------------------- wave findings: the threshold

def case_small_plan(R, S):
    """A small plan may skip the post-mortem (08.3 T31): `wave review` decides the security review as `wave new` does (prepare._security_why).
    Red before: FAIL: small plan, no postmortem: exit: got (2, 'the post-mortem of the phase cannot be read: ... postmortem.md: file: cannot be read (No such file or directory)'), want (0, '')"""
    for label, kw, want in (("security_review false", dict(plan_extra={"security_review": False}), None),
                            ("security_review true", dict(plan_extra={"security_review": True}), "plan.md security_review is true"),
                            ("a task on a protected path", dict(plan_extra={"security_review": False}, config={"project": {"protected_paths": ["src/a.py"]}}), "protected path")):
        W = World(postmortem=False, size="small", **kw)
        r, v = W.review(R)
        S.eq("small plan, no postmortem, %s: exit" % label, (r.returncode, r.stderr.strip()[:200]), (0, ""))
        S.eq("small plan, no postmortem, %s: the agents of the pass" % label, [x.get("role") for x in v.get("reviewers") or []],
             ["reviewer"] + (["security-reviewer"] if want else []))
        S.ok("small plan, no postmortem, %s: `security` says why" % label, want in v.get("security", "") if want else v.get("security") == "not asked for", v.get("security"))
    W = World(postmortem=False, size="normal", plan_extra={"security_review": False})
    r, v = W.review(R)
    S.eq("a normal plan with no postmortem is still refused, naming the file", (r.returncode, "postmortem.md" in r.stderr, r.stdout), (2, True, ""))
    S.eq("a refused call writes nothing", W.files(), [])


def case_threshold(R, S):
    """D10: the verifier runs only on a review with more than three items. At d348f8d (execute.js:637) it ran on any."""
    W = World()
    W.review(R)
    briefs = os.path.join(W.run_dir(), "briefs")
    os.makedirs(briefs, exist_ok=True)
    helpers.write(briefs, "_fix-1.md", "an earlier fixer's brief\n")  # `wave merge` wrote it: the number is the next free one
    r, v = W.find(R, W.reply("r1", [finding("F1"), finding("F2"), finding("F3")]))
    S.eq("wave findings: exit", (r.returncode, r.stderr.strip()[:200]), (0, ""))
    nxt(S, "3 findings go to the fixer", v, "fix")
    S.eq("3 findings: the ids are numbered by the pass", v.get("ids"), ["r1-F1", "r1-F2", "r1-F3"])
    S.eq("3 findings: no verifier brief is written", [f for f in W.files("briefs") if "verify" in f], [])
    S.ok("3 findings: `why` is the text for `wave fix --why`", (v.get("why") or "").startswith("review findings to fix: r1-F1, r1-F2, r1-F3"), v.get("why"))
    fb = v.get("brief") or ""
    S.ok("3 findings: the fixer's brief is the next free `_fix-<n>.md`", os.path.basename(fb) == "_fix-2.md" and os.path.isfile(fb), fb)
    text = read(fb) if os.path.isfile(fb) else ""
    for label, want in (("each id", "r1-F3"), ("each claim", "claim of F2"), ("the id in its commit trailer", "Fwx-Finding: <id>"), ("the run's trailer", "Fwx-Run: " + RUN),
                        ("the scratch order of the fixer", "fwx scratch new %s fix-2" % RUN), ("the file of a finding", "src/a.py"), ("the plan", "plan.md")):
        S.ok("3 findings: the fixer's brief names %s" % label, want in text, "missing %r" % want)
    S.eq("3 findings: the head the fixer starts from", v.get("head"), W.to)
    # G1: `unit` is the agent that follows (what `wave report --unit` reads), the fixer here
    S.eq("3 findings: the unit of the fixer that follows", v.get("unit"), "fix-2")
    S.eq("3 findings: the groups", [len(v.get(k) or []) for k in ("fix", "consider", "note", "dismissed", "file")], [3, 0, 0, 0, 0])
    S.eq("3 findings: reported", v.get("reported"), 3)
    S.eq("the criteria of the pass are returned", [c["id"] + c["met"] for c in v.get("criteria") or []], ["C1yes", "C2yes"])
    S.eq("the findings and the fixer are recorded in the run's files", W.files()[:2], ["1-review.json", "2-findings.json"])
    # four: the verifier
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1"), finding("F2"), finding("F3"), finding("F4")]))
    nxt(S, "4 findings go to the verifier", v, "verify")
    S.eq("4 findings: nothing is fixed yet", (v.get("ids") or [], v.get("fix") or []), ([], []))
    vb = v.get("brief") or ""
    S.ok("4 findings: the verifier's brief is a file of the run", os.path.isfile(vb), vb)
    text = read(vb) if os.path.isfile(vb) else ""
    for label, want in (("every finding id", "r1-F4"), ("a claim", "claim of F3"), ("its diff", "%s..%s" % (W.frm, W.to)),
                        ("the scratch order of the verifier", "fwx scratch new %s r1-verifier" % RUN), ("the reply line", "verdicts <report path>")):
        S.ok("4 findings: the verifier's brief names %s" % label, want in text, "missing %r" % want)
    S.eq("4 findings: the unit of the verifier", v.get("unit"), "r1-verifier")
    S.eq("4 findings: the items are in the result", [i["id"] for i in v.get("items") or []], ["r1-F1", "r1-F2", "r1-F3", "r1-F4"])
    # no findings: the pass is done
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", []))
    nxt(S, "no findings is done", v, "done")
    S.eq("no findings: nothing reported, no brief", (v.get("reported"), v.get("brief"), W.files("briefs")), (0, None, ["_review-r1.md"]))
    # the second pass numbers its ids by r2
    W = World()
    W.review(R)
    W.find(R, W.reply("r1", [finding("F1")]))
    W.review(R)
    r, v = W.find(R, W.reply("r2", [finding("F1")], run=RUN))
    S.eq("the ids of the second pass are r2-F1", v.get("ids"), ["r2-F1"])


def case_outside(R, S):
    """A reviewer's `outside` items become findings (O<k>, SO<k> for the security reviewer); a large one is returned to file."""
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1")], out=[outside(), outside(where="docs/x.md:2", size="large", what="x is wrong")]))
    nxt(S, "a finding and two outside items (3 items) go to the fixer", v, "fix")
    S.eq("the outside items are numbered O1, O2 after the findings", [i["id"] for i in v.get("items") or []], ["r1-F1", "r1-O1", "r1-O2"])
    S.eq("a large outside item is not fixed: it is for the session to file", v.get("ids"), ["r1-F1", "r1-O1"])
    S.eq("a large outside item is returned in `file`", [o.get("where") for o in v.get("file") or []], ["docs/x.md:2"])
    one = next((i for i in v.get("items") or [] if i["id"] == "r1-O1"), {})
    S.eq("an outside item as a finding: file, line, claim, severity", (one.get("file"), one.get("line"), one.get("claim"), one.get("severity")), ("src/z.py", 7, "z drops the last row", "medium"))
    S.ok("an outside item as a finding: the fix its finder proposes is in the evidence", "read to the end" in str(one.get("evidence")), str(one))
    W = World()
    W.review(R, "--security")
    lines = [W.reply("r1", [finding("F1")], out=[outside()]), W.reply("r1-sec", [finding("S1")], out=[outside(where="src/y.py:1")])]
    r, v = W.find(R, *lines)
    S.eq("the security reviewer's findings and outside items follow: S1, SO1", [i["id"] for i in v.get("items") or []], ["r1-F1", "r1-O1", "r1-S1", "r1-SO1"])
    nxt(S, "four items go to the verifier", v, "verify")
    outs = (v.get("outside_of") or {})
    S.eq("the outside item each id came from is kept for the verdicts", sorted(outs), ["r1-O1", "r1-SO1"])
    # the same id in two reports, or twice in one, is kept apart
    W = World()
    W.review(R, "--security")
    r, v = W.find(R, W.reply("r1", [finding("F1"), finding("F1", line=9)]), W.reply("r1-sec", [finding("F1", line=4)]))
    S.eq("a repeated id is made unique", [i["id"] for i in v.get("items") or []], ["r1-F1", "r1-F1.x", "r1-F1.x.x"])
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("a b/c")]))
    S.eq("an id that cannot name a commit trailer is made one", v.get("ids"), ["r1-a_b_c"])
    # a large outside item with three items or fewer: nothing to fix, only to file
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [], out=[outside(size="large")]))
    nxt(S, "only a large outside item is done", v, "done")
    S.eq("only a large outside item: it is to file", [o.get("size") for o in v.get("file") or []], ["large"])


def case_control(R, S):
    """`wave new --control-findings` findings join the first pass only (execute.js: `if (tag === 'r1')`)."""
    W = World()
    ctl = helpers.write(W.S.repo, "control.json", json.dumps([finding("X1", file="src/b.py")]))
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1"), finding("F2"), finding("F3")]), extra=("--control-findings", ctl))
    nxt(S, "three findings and a control one (4 items) go to the verifier", v, "verify")
    S.eq("the control finding is numbered by the pass", [i["id"] for i in v.get("items") or []], ["r1-F1", "r1-F2", "r1-F3", "r1-X1"])
    W = World()
    ctl = helpers.write(W.S.repo, "control.json", json.dumps([finding("X1", file="src/b.py")]))
    W.review(R)
    W.find(R, W.reply("r1", []))
    W.review(R)
    r, v = W.find(R, W.reply("r2", [finding("F1"), finding("F2"), finding("F3")]), extra=("--control-findings", ctl))
    nxt(S, "a control finding is not added to the second pass", v, "fix")
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", []), extra=("--control-findings", os.path.join(W.S.repo, "nothing.json")))
    S.eq("a control file that cannot be read: exit 2", r.returncode, 2)


# ---------------------------------------------------------------------------------------------------- wave findings: the misses

def case_misses(R, S):
    """readReview and twice() of execute.js: a report that is not usable is asked for once more, with the reason when it was
    rejected for what is in it; a second miss ends the run. The misses are counted from the run's own files."""
    W = World()
    W.review(R)
    r, v = W.find(R, "I reviewed it and it looks fine")
    nxt(S, "a reply that is no line of a report relaunches the reviewer", v, "relaunch")
    S.eq("the relaunch names the unit and its brief", [(x.get("unit"), os.path.isfile(x.get("brief") or "")) for x in v.get("relaunch") or []], [("r1", True)])
    r, v = W.find(R, "I reviewed it and it looks fine")
    nxt(S, "a second miss of the reviewer ends the run", v, "stop")
    S.eq("the second miss: why", v.get("why"), "reviewer did not return")
    S.eq("the second miss is a gap", v.get("gap"), "reviewer did not return")
    def bare(rep):
        """The report with `criteria` taken out."""
        del rep["criteria"]
        return rep
    for label, kw in (
            ("looked_at is empty", dict(looked_at=[])),
            ("a finding with a line that is no number", dict(findings=[finding(line="3")])),
            ("a finding with no claim", dict(findings=[finding(claim="")])),
            ("a finding with an unknown severity", dict(findings=[finding(severity="urgent")])),
            ("a criterion that is no yes, no or unproven", dict(crit=[{"id": "C1", "met": "maybe", "evidence": "x"}])),
    ):
        W = World()
        W.review(R)
        r, v = W.find(R, W.reply("r1", **kw))
        nxt(S, "a report where %s relaunches" % label, v, "relaunch")
    W = World()
    W.review(R)
    line = W.reply("r1", [finding("F1")])
    helpers.write(os.path.dirname(W.path("r1")), "report.json", json.dumps({"looked_at": ["a"], "findings": []}))
    r, v = W.find(R, line)
    nxt(S, "a report with no `criteria` relaunches", v, "relaunch")
    # the general reviewer answers for every criterion of the plan: an empty or partial list is a report to write again (CodeRabbit 4696262780).
    # Seen red on the code before the fix: FAIL: a report with `criteria: []` relaunches -> next done, want relaunch
    for label, crit in (("`criteria: []`", []), ("one of the plan's two criteria", criteria()[:1])):
        W = World()
        W.review(R)
        r, v = W.find(R, W.reply("r1", [], crit=crit))
        nxt(S, "a report with %s relaunches" % label, v, "relaunch")
        S.ok("the note names the criterion left out", "C2" in ((v.get("relaunch") or [{}])[0].get("note") or "") or crit == [], json.dumps(v)[:200])
    # a malformed outside item is rejected with its reason, which the second rejection ends the run with
    W = World()
    W.review(R)
    line = W.reply("r1", [finding("F1")], out=[outside(issue="DTC-12")])
    r, v = W.find(R, line)
    nxt(S, "a reviewer's outside item with a key is rejected: relaunch", v, "relaunch")
    note = (v.get("relaunch") or [{}])[0].get("note") or ""
    S.ok("the relaunch note says the report was rejected, naming `issue`", "rejected" in note and "issue" in note, note)
    r, v = W.find(R, line)
    nxt(S, "the same report again ends the run", v, "stop")
    S.ok("the reason is the rejection, not `did not return`", (v.get("why") or "").startswith("reviewer returned a report that was rejected: outside item 1:"), v.get("why"))
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1")], out=[{"where": "src/z.py", "what": "w", "fix": "f", "size": "small", "issue": None}]))
    nxt(S, "an outside item whose `where` has no line relaunches", v, "relaunch")
    # an unmet criterion that no finding names
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1")], crit=criteria(c2="no")))
    nxt(S, "a criterion that is not met and that no finding names relaunches", v, "relaunch")
    S.ok("the note names the criterion", "C2" in ((v.get("relaunch") or [{}])[0].get("note") or ""), json.dumps(v)[:200])
    r, v = W.find(R, W.reply("r1", [finding("F1", claim="C2 is not met")], crit=criteria(c2="no")))
    nxt(S, "the same criterion named by a finding's claim is read", v, "fix")
    S.eq("the criterion that is not met is in the result", [(c["id"], c["met"]) for c in v.get("criteria") or []], [("C1", "yes"), ("C2", "no")])
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1", evidence="the run of C2 printed 1 failure")], crit=criteria(c2="no")))
    nxt(S, "a criterion named in a finding's evidence is read", v, "fix")
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [], crit=criteria(c2="unproven")))
    nxt(S, "an unproven criterion needs no finding", v, "done")
    # only a path inside the unit's scratch folder is read
    def not_read(label, make):
        W = World()
        W.review(R)
        good = W.reply("r1", [finding("F1")])
        r, v = W.find(R, make(W, good))
        nxt(S, "%s is not read" % label, v, "relaunch")

    def climbing(W, good):
        os.makedirs(os.path.join(W.dirs["r1"], "sub"))
        return good.replace(W.dirs["r1"] + "/.fwx-agent", W.dirs["r1"] + "/sub/../.fwx-agent")
    not_read("the report of another unit", lambda W, good: W.reply("r9", [finding("F1")]))
    not_read("the report of another run", lambda W, good: W.reply("r1", [finding("F1")], run="02-other-1"))
    not_read("a path that climbs out of the folder", climbing)
    not_read("a file that is not report.json", lambda W, good: good.replace("report.json", "other.json"))
    not_read("looked_at=0 on the line", lambda W, good: good.replace("looked_at=1", "looked_at=0"))
    # the security reviewer's miss alone is relaunched; the reviewer's good report is passed again with it
    W = World()
    W.review(R, "--security")
    ok = W.reply("r1", [finding("F1")])
    r, v = W.find(R, ok, "no line at all")
    nxt(S, "the reviewer reads, the security reviewer misses: relaunch", v, "relaunch")
    S.eq("only the security reviewer is relaunched", [x.get("unit") for x in v.get("relaunch") or []], ["r1-sec"])
    r, v = W.find(R, ok, W.reply("r1-sec", []))
    nxt(S, "both read the second time", v, "fix")
    W = World()
    W.review(R, "--security")
    r, v = W.find(R, ok, "no line at all")
    r, v = W.find(R, ok, "no line at all")
    nxt(S, "a second miss of the security reviewer ends the run", v, "stop")
    S.eq("the second miss: why", v.get("why"), "security-reviewer did not return")
    # a miss is counted per unit: the reviewer's second launch does not make the security reviewer's first a second
    W = World()
    W.review(R, "--security")
    ok = W.reply("r1", [finding("F1")])
    W.find(R, "no line at all", W.reply("r1-sec", []))
    r, v = W.find(R, ok, "no line at all")
    nxt(S, "a miss is counted per unit", v, "relaunch")
    S.eq("the security reviewer is the one relaunched", [x.get("unit") for x in v.get("relaunch") or []], ["r1-sec"])
    # a miss is counted per pass: the next pass starts at none
    W = World()
    W.review(R)
    W.find(R, "nothing")
    W.find(R, W.reply("r1", [finding("F1")]))
    W.review(R)
    r, v = W.find(R, "nothing")
    nxt(S, "a miss of the next pass is a first miss again", v, "relaunch")
    # no pass to read
    W = World()
    r, v = W.find(R, W.reply("r1", []))
    S.eq("a report with no `wave review` before it: exit 2 and a reason", (r.returncode, bool(r.stderr.strip()), r.stdout), (2, True, ""))


# ---------------------------------------------------------------------------------------------------- wave findings: the verdicts

def four(W, R, out=(), sec=False):
    """A pass with four items, waiting for the verifier (with `sec`, the security reviewer reads and finds nothing)."""
    W.review(R)
    lines = [W.reply("r1", [finding("F1"), finding("F2"), finding("F3"), finding("F4")] if not out else [finding("F1"), finding("F2")], out=out)]
    r, v = W.find(R, *(lines + ([W.reply("r1-sec", [])] if sec else [])))
    return v


def case_verdicts(R, S):
    W = World()
    four(W, R)
    r, v = W.verdicts(R, {"r1-F1": "fix", "r1-F2": "consider", "r1-F3": "note", "r1-F4": "dismiss"})
    S.eq("wave findings --verdicts: exit", (r.returncode, r.stderr.strip()[:200]), (0, ""))
    nxt(S, "a verdict `fix` is fixed", v, "fix")
    S.eq("the ids to fix", v.get("ids"), ["r1-F1"])
    S.eq("consider: id, file, line, claim, severity", v.get("consider"), [{"id": "r1-F2", "file": "src/a.py", "line": 3, "claim": "claim of F2", "severity": "medium"}])
    S.eq("note: id and claim", v.get("note"), [{"id": "r1-F3", "claim": "claim of F3"}])
    S.eq("dismissed: id and the verifier's reason", v.get("dismissed"), [{"id": "r1-F4", "reason": "because r1-F4"}])
    S.eq("the route of each id", v.get("routes"), {"r1-F1": "fix", "r1-F2": "consider", "r1-F3": "note", "r1-F4": "dismissed"})
    S.eq("fix: the finding with the verifier's severity", [(f["id"], f["severity"]) for f in v.get("fix") or []], [("r1-F1", "medium")])
    S.eq("reported counts every item of the pass", v.get("reported"), 4)
    fb = v.get("brief") or ""
    S.ok("the fixer's brief names only the finding to fix", os.path.isfile(fb) and "claim of F1" in read(fb) and "claim of F2" not in read(fb), fb)
    S.ok("`why` is the text for `wave fix --why`", (v.get("why") or "").startswith("review findings to fix: r1-F1"), v.get("why"))
    S.eq("the head the fixer starts from", v.get("head"), W.to)
    # G1: after the verifier, `unit` is the fixer's, not `r1-verifier`
    # Red before: FAIL: the unit of the fixer that follows the verifier: got 'r1-verifier', want 'fix-1'
    S.eq("the unit of the fixer that follows the verifier", v.get("unit"), "fix-1")
    # D25 (09-trim): a verified finding of severity low goes to consider, never to fix; only medium and high trigger a fix round and a new gate
    # Red before: FAIL: D25: a low `fix` verdict is not fixed, a medium and a high one are: got ['r1-F1', 'r1-F2', 'r1-F3', 'r1-F4'], want ['r1-F2', 'r1-F3', 'r1-F4']
    W = World()
    four(W, R)
    r, v = W.verdicts(R, {"r1-F1": "fix", "r1-F2": "fix", "r1-F3": "fix", "r1-F4": "fix"}, severity={"r1-F1": "low", "r1-F2": "medium", "r1-F3": "high"})
    S.eq("D25: a low `fix` verdict is not fixed, a medium and a high one are", v.get("ids"), ["r1-F2", "r1-F3", "r1-F4"])
    S.eq("D25: the low one is in consider, with its severity", v.get("consider"), [{"id": "r1-F1", "file": "src/a.py", "line": 3, "claim": "claim of F1", "severity": "low"}])
    S.eq("D25: the routes", v.get("routes"), {"r1-F1": "consider", "r1-F2": "fix", "r1-F3": "fix", "r1-F4": "fix"})
    S.ok("D25: the fixer's brief holds no low finding", os.path.isfile(v.get("brief") or "") and "claim of F1" not in read(v["brief"]) and "claim of F2" in read(v["brief"]), v.get("brief"))
    W = World()
    four(W, R)
    r, v = W.verdicts(R, {"r1-F1": "fix", "r1-F2": "dismiss", "r1-F3": "dismiss", "r1-F4": "dismiss"}, severity={"r1-F1": "low"})
    nxt(S, "D25: nothing but a low `fix` verdict is done: no fix round", v, "done")
    S.eq("D25: and it is listed for the owner", [c["id"] for c in v.get("consider") or []], ["r1-F1"])
    # nothing to fix
    W = World()
    four(W, R)
    r, v = W.verdicts(R, {"r1-F1": "dismiss", "r1-F2": "note", "r1-F3": "consider", "r1-F4": "dismiss"})
    nxt(S, "no verdict `fix` is done", v, "done")
    S.eq("done: no brief, no ids", (v.get("brief"), v.get("ids")), (None, []))
    # a protected path ends the flow with the owner, as at d348f8d
    W = World()
    W.final_merge(["src/secret/k.py"])
    four(W, R, sec=True)
    r, v = W.verdicts(R, {"r1-F1": "dismiss", "r1-F2": "dismiss", "r1-F3": "dismiss", "r1-F4": "dismiss"})
    nxt(S, "nothing to fix but a protected path: the owner", v, "owner")
    S.ok("the owner is told the path", "protected path: src/secret/k.py" in (v.get("why") or ""), v.get("why"))
    # large outside items go to file even when the verifier says fix; a small one is fixed
    W = World()
    four(W, R, out=[outside(size="large"), outside(where="src/y.py:2")])
    r, v = W.verdicts(R, {"r1-F1": "dismiss", "r1-F2": "dismiss", "r1-O1": "fix", "r1-O2": "fix"})
    nxt(S, "a small outside item the verifier says fix is fixed", v, "fix")
    S.eq("the small one is the id to fix", v.get("ids"), ["r1-O2"])
    S.eq("a large outside item the verifier says fix is returned to file", [(o.get("where"), o.get("size")) for o in v.get("file") or []], [("src/z.py:7", "large")])
    S.eq("its route is file", (v.get("routes") or {}).get("r1-O1"), "file")
    # a large outside item the verifier does not say fix is judged like any other
    W = World()
    four(W, R, out=[outside(size="large"), outside(where="src/y.py:2")])
    r, v = W.verdicts(R, {"r1-F1": "dismiss", "r1-F2": "dismiss", "r1-O1": "dismiss", "r1-O2": "note"})
    S.eq("a dismissed large outside item is not filed", v.get("file"), [])
    # D25 demotes a low `fix` to consider, but a large outside item is too big for a fix round whatever its severity: it is still filed
    W = World()
    four(W, R, out=[outside(size="large"), outside(where="src/y.py:2")])
    r, v = W.verdicts(R, {"r1-F1": "dismiss", "r1-F2": "dismiss", "r1-O1": "fix", "r1-O2": "fix"}, severity={"r1-O1": "low", "r1-O2": "low"})
    S.eq("a large outside item rated low is returned in `file`", [o.get("where") for o in v.get("file") or []], ["src/z.py:7"])
    S.eq("a small outside item rated low is in consider", [c["id"] for c in v.get("consider") or []], ["r1-O2"])
    S.eq("the routes of the two low outside items", v.get("routes"), {"r1-F1": "dismissed", "r1-F2": "dismissed", "r1-O1": "file", "r1-O2": "consider"})
    # a verdict that is not usable
    W = World()
    four(W, R)
    r, v = W.verdicts(R, {"r1-F1": "fix", "r1-F2": "fix", "r1-F3": "fix"})
    nxt(S, "a verdict missing for an id relaunches the verifier", v, "relaunch")
    S.ok("the note names the id with no verdict", "r1-F4" in ((v.get("relaunch") or [{}])[0].get("note") or ""), json.dumps(v)[:200])
    S.eq("the relaunch is the verifier's unit and brief", [(x.get("unit"), os.path.isfile(x.get("brief") or "")) for x in v.get("relaunch") or []], [("r1-verifier", True)])
    r, v = W.verdicts(R, {"r1-F1": "fix", "r1-F2": "fix", "r1-F3": "fix"})
    nxt(S, "a second miss of the verifier ends the run", v, "stop")
    S.eq("the second miss: why", v.get("why"), "review-verifier did not return")
    S.eq("the second miss is a gap", v.get("gap"), "review-verifier did not return")
    W = World()
    four(W, R)
    r, v = W.verdicts(R, None, raw={"verdicts": [{"id": i, "verdict": "keep", "severity": "low", "reason": "r"} for i in ("r1-F1", "r1-F2", "r1-F3", "r1-F4")]})
    nxt(S, "a verdict that is none of the four groups relaunches", v, "relaunch")
    W = World()
    four(W, R)
    r, v = W.say_verdicts(R, "I have my verdicts")
    nxt(S, "a reply that is no line of a report relaunches the verifier", v, "relaunch")
    W = World()
    four(W, R)
    r, v = W.verdicts(R, None, raw={"verdicts": [{"id": i, "verdict": "fix", "severity": "medium", "reason": "r"} for i in ("r1-F1", "r1-F2", "r1-F3", "r1-F4")], "extra": 1})
    nxt(S, "a verdicts file with every id is read", v, "fix")
    S.eq("every id fixed", v.get("ids"), ["r1-F1", "r1-F2", "r1-F3", "r1-F4"])
    W = World()
    four(W, R)
    p = W.path("r9-verifier")
    helpers.write(os.path.dirname(p), "report.json", json.dumps({"verdicts": [{"id": i, "verdict": "fix", "severity": "medium", "reason": "r"} for i in ("r1-F1", "r1-F2", "r1-F3", "r1-F4")]}))
    r, v = W.say_verdicts(R, "verdicts %s" % p)
    nxt(S, "the verdicts of another unit are not read", v, "relaunch")
    # no verifier awaited
    W = World()
    W.review(R)
    r, v = W.verdicts(R, {"r1-F1": "fix"})
    S.eq("verdicts with no pass waiting for them: exit 2 and a reason", (r.returncode, bool(r.stderr.strip()), r.stdout), (2, True, ""))
    W = World()
    W.review(R)
    W.find(R, W.reply("r1", [finding("F1")]))
    r, v = W.verdicts(R, {"r1-F1": "fix"})
    S.eq("verdicts after a pass that went to the fixer: exit 2", r.returncode, 2)


def case_usage(R, S):
    W = World()
    W.review(R)
    line = W.reply("r1", [])
    base = ["wave", "findings", "--run", RUN, "--report", line]
    for label, args in (("neither --report nor --verdicts", ["wave", "findings", "--run", RUN]),
                        ("both", base + ["--verdicts", "verdicts x"]),
                        ("no --run", ["wave", "findings", "--report", line]),
                        ("a run that cannot name a folder", ["wave", "findings", "--run", "../x", "--report", line]),
                        ("an option nobody knows", base + ["--nope"]),
                        ("--report with no word", ["wave", "findings", "--run", RUN, "--report"])):
        r = R(W.S.cwd, *args, env=W.env)
        S.eq("usage (%s): exit 2 with the usage on stderr, nothing on stdout" % label, (r.returncode, "usage: fwx wave findings" in r.stderr, r.stdout), (2, True, ""))
    S.eq("usage: nothing was written for a refused call", W.files(), ["1-review.json", "briefs"])
    r = R(W.S.cwd, *base, env=W.env)
    S.eq("usage: the good call runs", r.returncode, 0)
    r = R(helpers.mkdtemp("fwx-nogit-"), *base, env=W.env)
    S.eq("outside a repository: exit 2", r.returncode, 2)


def case_fixer_retry(R, S):
    """A fixer brief that could not be written leaves no `_findings-<unit>.json` behind (CodeRabbit 4696262791): the next call allocates the same
    unit from the brief files alone and opens its source exclusively. In process (the fault is a write that fails). Seen red on the code before
    the fix: FAIL: the failed brief leaves no findings file -> ['_findings-fix-1.json'] and FAIL: the retry after it works -> FileExistsError."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from fwx.execute import brief as brief_mod, review as review_mod
    W = World()
    saved_env = dict(os.environ)
    os.environ.update(W.env)
    real_put, folder = brief_mod.put, os.path.join(W.run_dir(), "briefs")
    f = finding("r1-F1")

    def failing(path, text):
        raise OSError(28, "No space left on device")
    brief_mod.put = failing
    try:
        try:
            review_mod._fixer(W.S.cwd, W.S.part, RUN, [f])
        except OSError:
            pass
        left = [n for n in sorted(os.listdir(folder)) if n.startswith("_findings-")] if os.path.isdir(folder) else []
        S.eq("the failed brief leaves no findings file -> %s" % left, left, [])
        brief_mod.put = real_put
        try:
            got = review_mod._fixer(W.S.cwd, W.S.part, RUN, [f])[0]
        except FileExistsError as e:
            got = "FileExistsError: %s" % e
        S.eq("the retry after it works -> %s" % got, got, "fix-1")
    finally:
        brief_mod.put = real_put
        os.environ.clear()
        os.environ.update(saved_env)


def case_recorded(R, S):
    """`wave run` records each unit's worktree in state.json: a reviewer's or verifier's report is read from there, whatever path its line echoes."""
    W = World()
    W.review(R)
    line = W.reply("r1", [finding("F1")])
    helpers.write(W.run_dir(), "state.json", json.dumps({"workers": {"r1/1": {"unit": "r1", "worktree": W.dirs["r1"]}, "r1-verifier/1": {"unit": "r1-verifier", "worktree": W.dir_of("r1-verifier")}}}))
    r, v = W.find(R, line.replace(W.path("r1"), ".fwx-agent/%s/r1/report.json" % RUN))
    nxt(S, "a recorded reviewer is read though its line has no folder before .fwx-agent", v, "fix")
    W = World()
    W.review(R)
    W.find(R, W.reply("r1", [finding("F%d" % i) for i in range(1, 5)]))
    rows = [{"id": "r1-F%d" % i, "verdict": "fix", "severity": "medium", "reason": "x"} for i in range(1, 5)]
    helpers.write(os.path.dirname(W.path("r1-verifier")), "report.json", json.dumps({"verdicts": rows}))
    helpers.write(W.run_dir(), "state.json", json.dumps({"workers": {"r1-verifier/1": {"unit": "r1-verifier", "worktree": W.dirs["r1-verifier"]}}}))
    r, v = W.say_verdicts(R, "verdicts .fwx-agent/%s/r1-verifier/report.json" % RUN)
    nxt(S, "a recorded verifier is read though its line has no folder before .fwx-agent", v, "fix")


def case_routes(R, S):
    """A finding on a file under `.fwx/` (executors may not write there) goes to `consider` before the verifier threshold, and an unverified `low`
    one goes to `consider` instead of a fix round."""
    W = World()
    W.review(R)
    fx = [finding("F%d" % i, file=f) for i, f in enumerate((".fwx/milestones/v1/plan.md", "/abs/repo/.fwx/ctx.md", "sub/.fwx/x.md"), 1)]
    r, v = W.find(R, W.reply("r1", fx + [finding("F4")]))
    nxt(S, "3 findings under .fwx/ and 1 real one: no verifier, the real one is fixed", v, "fix")
    S.eq("findings under .fwx/: only the real one is fixed, the others are listed", (v.get("ids"), [c["id"] for c in v.get("consider") or []]), (["r1-F4"], ["r1-F1", "r1-F2", "r1-F3"]))
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1", file=".fwx/plan.md")], out=[outside(where=".fwx/plan.md:93", size="large")]))
    S.eq("a finding and a large outside item under .fwx/ are both listed, none fixed or filed", (v.get("next"), v.get("ids"), len(v.get("consider") or []), v.get("file")), ("done", [], 2, []))
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1", severity="low"), finding("F2", severity="medium")]))
    S.eq("an unverified low finding is listed, a medium one is fixed", (v.get("ids"), [c["id"] for c in v.get("consider") or []]), (["r1-F2"], ["r1-F1"]))
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1", severity="low")]))
    nxt(S, "a pass of one low finding is done", v, "done")
    W = World()
    r, v = W.review(R)
    text = read(v["reviewers"][0]["brief"])
    S.ok("the reviewer's brief says `.fwx/` files are not reviewable", "not reviewable" in text, text[-500:])


def case_uncommittable(R, S):
    """A finding on a file no commit of the worktree can carry (git-ignored and untracked, or outside the worktree: `~/...`, `../x`, `/abs`) goes to
    `consider` and counts nothing towards the verifier threshold, as one under `.fwx/` does; a tracked file, and a file that does not exist yet,
    are still fixed. The `where` of an `outside` item is judged as the reviewer wrote it: its `file` has lost the leading `/` and the `..`.
    Seen red against the code before `_uncommittable` (5 FAILs, among them):
      FAIL: 3 uncommittable findings and a tracked one: no verifier, the tracked one is fixed -> next verify: want next 'fix', got 'verify'
      FAIL: uncommittable outside items are listed, the finding is fixed: got ([], []), want (['r1-F1'], ['r1-O1', 'r1-O2', 'r1-O3', 'r1-O4'])
      FAIL: a pass of one ignored-file finding is done, listed: got ('fix', ['r1-F1'], []), want ('done', [], ['r1-F1'])"""
    W = World()
    W.review(R)
    bad = ["config/forge.json", "~/.claude/settings.json", "../outside.py"]
    r, v = W.find(R, W.reply("r1", [finding("F%d" % i, file=f) for i, f in enumerate(bad, 1)] + [finding("F4")]))
    nxt(S, "3 uncommittable findings and a tracked one: no verifier, the tracked one is fixed", v, "fix")
    S.eq("uncommittable findings are listed, the tracked one is fixed", (v.get("ids"), [c["id"] for c in v.get("consider") or []]), (["r1-F4"], ["r1-F1", "r1-F2", "r1-F3"]))
    W = World()
    W.review(R)
    wh = ["config/forge.json:2", "~/.claude/settings.json:5", "../outside.py:3", "/etc/hosts:1"]
    r, v = W.find(R, W.reply("r1", [finding("F1")], out=[outside(where=w) for w in wh]))
    nxt(S, "4 uncommittable outside items and a tracked finding: no verifier, the finding is fixed", v, "fix")
    S.eq("uncommittable outside items are listed, the finding is fixed", (v.get("ids"), [c["id"] for c in v.get("consider") or []]), (["r1-F1"], ["r1-O1", "r1-O2", "r1-O3", "r1-O4"]))
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1", file="src/new.py"), finding("F2", file="src/a.py")]))
    S.eq("a file that does not exist yet is fixed, like a tracked one", (v.get("next"), v.get("ids")), ("fix", ["r1-F1", "r1-F2"]))
    W = World()
    W.review(R)
    r, v = W.find(R, W.reply("r1", [finding("F1", file="config/forge.json")]))
    S.eq("a pass of one ignored-file finding is done, listed", (v.get("next"), v.get("ids"), [c["id"] for c in v.get("consider") or []]), ("done", [], ["r1-F1"]))


def case_goal_and_ui(R, S):
    """The reviewer's brief gives the phase goal (the Intent of context.md) and, for a part with a UI task, the paths under `Approved UI`;
    a part with no UI task gets no such section (context.md criterion 2).

    Seen red before the code: FAIL: a UI part: the reviewer's brief gives the phase goal / the approved prototypes (the brief held the
    context.md path and the plan's criteria only)."""
    ctx = "# context\n\n## Intent\nShip the one-home rule for the working documents.\n\n## What success means\n1. one home\n\n## Approved UI\ndemo/figure-b.html\n\n## Research\nNone.\n"
    for label, tasks, ui in (("a UI part", TASKS + [wp.task("T3", 3, ["web/page.html"], ui=True)], True), ("a part with no UI task", TASKS, False)):
        W = World(tasks=tasks)
        helpers.write(W.S.phase, "context.md", ctx)
        r, v = W.review(R)
        text = read(v["reviewers"][0]["brief"]) if v.get("reviewers") else ""
        S.ok("%s: the reviewer's brief gives the phase goal" % label, "Ship the one-home rule for the working documents." in text, text[:600])
        S.ok("%s: the reviewer's brief %s the approved prototypes" % (label, "gives" if ui else "has no section of"),
             ("demo/figure-b.html" in text and os.path.join(W.S.phase) in text) == ui and ("## APPROVED UI" in text) == ui, text[:900])
        sec = read(W.review(R, "--security")[1]["reviewers"][1]["brief"])
        S.ok("%s: the security reviewer's brief has neither" % label, "Ship the one-home rule" not in sec and "APPROVED UI" not in sec, sec[:400])


CASES = [case_review, case_default_merge, case_security, case_small_plan, case_threshold, case_outside, case_control, case_misses, case_verdicts, case_usage, case_fixer_retry, case_recorded, case_routes, case_uncommittable, case_goal_and_ui]
V_ = "lib/fwx/execute/review.py"
W_ = "lib/fwx/commands/wave.py"
MUTANTS = [
    ("the verifier runs on any item (the rule at d348f8d)", case_threshold, V_, "THRESHOLD = 3\n", "THRESHOLD = 0\n",
     "3 findings go to the fixer -> next verify"),
    ("the verifier runs from three items", case_threshold, V_, "if sum(not _uncommittable(top, i, outside_of) for i in items) > THRESHOLD:", "if sum(not _uncommittable(top, i, outside_of) for i in items) >= THRESHOLD:",
     "3 findings go to the fixer -> next verify"),
    ("the verifier runs from five items", case_threshold, V_, "THRESHOLD = 3\n", "THRESHOLD = 4\n",
     "4 findings go to the verifier -> next fix"),
    ("the ids are not prefixed by the pass", case_threshold, V_, 'ident = "%s-%s" % (tag, ', 'ident = "%s%s" % ("", ',
     "3 findings: the ids are numbered by the pass"),
    ("a repeated id is kept", case_outside, V_, '        ident += ".x"\n', "        break\n",
     "a repeated id is made unique"),
    ("the outside items are dropped", case_outside, V_, 'for k, o in enumerate(rep["outside"], 1):', "for k, o in enumerate([], 1):",
     "the outside items are numbered O1, O2 after the findings"),
    ("a large outside item is fixed", case_outside, V_, 'return o is not None and o["size"] == "large"', "return False",
     "a large outside item is not fixed: it is for the session to file"),
    ("the control findings join every pass", case_control, V_, 'if tag == "r1" and control:', "if control:",
     "a control finding is not added to the second pass"),
    ("a report is read once and never relaunched", case_misses, V_, "    if prior >= 1:\n", "    if True:\n",
     "a reply that is no line of a report relaunches the reviewer -> next stop"),
    ("the misses of every unit are one count", case_misses, V_, 'if x.get("unit") == unit:', "if True:",
     "a miss is counted per unit -> next stop"),
    ("an empty looked_at is a review", case_misses, V_, ' or not rep["looked_at"]', "",
     "a report where looked_at is empty relaunches"),
    ("looked_at=0 on the line is read", case_misses, V_, "    if int(m.group(2)) == 0:\n        return None, None\n", "    if False:\n        return None, None\n",
     "looked_at=0 on the line is not read"),
    ("any path that names a report is read", case_misses, V_, 'if not ("/" + path).endswith(_tail(run, unit)) or ".." in path.split("/"):\n        return None\n',
     'if ".." in path.split("/"):\n        return None\n',
     "the report of another unit is not read"),
    ("a path that climbs is read", case_misses, V_, '.endswith(_tail(run, unit)) or ".." in path.split("/"):\n        return None\n', '.endswith(_tail(run, unit)):\n        return None\n',
     "a path that climbs out of the folder is not read"),
    ("the finding's shape is not checked", case_misses, V_, 'if any(not _valid(f) for f in rep["findings"]):', "if False:",
     "a finding with a line that is no number relaunches"),
    ("a reviewer's outside item may carry a key", case_misses, V_, 'outside_problem(rep, "reviewer", False)', 'outside_problem(rep, "executor", False)',
     "a reviewer's outside item with a key is rejected: relaunch"),
    ("the rejection is not the reason of the second miss", case_misses, V_, 'why = "%s returned a report that was rejected: %s" % (m["role"], rejected) if rejected else "%s did not return" % m["role"]',
     'why = "%s did not return" % m["role"]',
     "the reason is the rejection, not `did not return`"),
    ("an unmet criterion needs no finding", case_misses, V_, 'if c["met"] == "no" and not any(', 'if False and not any(',
     "a criterion that is not met and that no finding names relaunches"),
    ("the evidence of a finding does not name a criterion", case_misses, V_, '"%s %s" % (f["claim"], f["evidence"])', 'f["claim"]',
     "a criterion named in a finding's evidence is read"),
    ("`--security` does nothing", case_security, V_, '(["--security"] if security else [])', "[]",
     "--security launches the security reviewer too"),
    ("the post-mortem's security_review does nothing", case_security, V_, " + asked + ", " + [] + ",
     "the post-mortem's security_review launches the security reviewer"),
    ("a protected path asks for no security review", case_security, V_, '(["the last final merge named a protected path"] if protected else [])', "[]",
     "a protected path of the last final merge launches the security reviewer"),
    ("a missing postmortem.md is an error again", case_small_plan, V_, 'asked = prepare._security_why(data, owner["postmortem"], cfg)',
     'asked = plan.load_postmortem(owner["postmortem"]) and []', "small plan, no postmortem, security_review false: exit"),
    ("the review reads the default branch's edits as the part's", case_default_merge, V_, "only = own if own !=", "only = None if True or own !=",
     "default merge: the brief restricts the diff to the part's own files"),
    ("the fixer's unit is the verifier's", case_verdicts, V_, "**dict(common, unit=unit))", "**common)",
     "the unit of the fixer that follows the verifier"),
    ("the fixer's unit is not returned", case_threshold, V_, "**dict(common, unit=unit))", "**dict(common, unit=None))",
     "3 findings: the unit of the fixer that follows"),
    ("a low `fix` verdict is fixed (D25 undone)", case_verdicts, V_, 'severity == "low")\n', 'severity == "never")\n',
     "D25: a low `fix` verdict is not fixed, a medium and a high one are"),
    ("a verdict `consider` is fixed", case_verdicts, V_, 'elif verdict == "consider":', 'elif verdict == "fix":',
     "consider: id, file, line, claim, severity"),
    ("the verdicts of any unit are read", case_verdicts, V_, 'if not ("/" + path).endswith(_tail(run, unit)) or ".." in path.split("/"):\n        return None, ""', 'if False:\n        return None, ""',
     "the verdicts of another unit are not read"),
    ("a verdict missing for an id is read", case_verdicts, V_, '    if missing:\n        return None, "no verdict', '    if False:\n        return None, "no verdict',
     "a verdict missing for an id relaunches the verifier"),
    ("a verdict that is none of the four groups is read", case_verdicts, V_, 'elif d.get("verdict") not in VERDICTS:', "elif False:",
     "a verdict that is none of the four groups relaunches"),
    ("a protected path does not end the flow with the owner", case_verdicts, V_, ') if protected else ("done"', ') if False else ("done"',
     "nothing to fix but a protected path: the owner"),
    ("a large outside item is filed when dismissed", case_verdicts, V_, 'if _large(outside_of, ident) and verdict == "fix" and not forced:', "if _large(outside_of, ident) and not forced:",
     "a dismissed large outside item is not filed"),
    ("the prototypes go to a part with no UI task", case_goal_and_ui, V_, 'if any(x["ui"] for x in data["tasks"]) else None', "if True else None",
     "a part with no UI task: the reviewer's brief has no section of the approved prototypes"),
    ("the reviewer gets no goal", case_goal_and_ui, V_, 'plan.section(owner["context"], "Intent")', "None",
     "the reviewer's brief gives the phase goal"),
    ("one of --report and --verdicts is not needed", case_usage, W_, '(("--report" in parsed[0]) == ("--verdicts" in parsed[0]))', '(("--report" in parsed[0]) and ("--verdicts" in parsed[0]))',
     "usage (neither --report nor --verdicts)"),
]

if __name__ == "__main__":
    real = runner(ROOT)
    for case in CASES:
        case(real, s)
    for name, case, path, old, new, needle in MUTANTS:
        m = helpers.FirstFail(lambda f, needle=needle: needle in f)
        try:
            tree = mutant_tree(path, old, new)
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        m.run(case, runner(tree), m)
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
    s.done()
