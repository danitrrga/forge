#!/usr/bin/env python3
"""The end-of-part gate on GitHub CI (09.6 T64, D26): lib/fwx/core/ci_gate.py, core/verify.py `ci=`, core/evidence.py, execute/integrate.py,
execute/prepare.py `_record`, and `fwx decide`.

`fwx wave merge --final` keeps running `checks_quick`, then, with a GitHub origin, a `gh` that answers and the CI workflow at the head,
the gate is CI: the phase branch is pushed (never forced, never the default or a production branch), a draft pull request is opened
once, and the `pull_request` runs of `.github/workflows/ci.yml` on that exact sha are polled until all are completed. Green when at
least one ran and all succeeded, red when one failed (naming its failed jobs and URL), and in every other case (offline, no GitHub
origin, no CI file, a rejected push, a conflicting draft, a cancelled run, no run, no result in `project.check_timeout_s`) the local gate
runs with one line saying why. `fwx verify` by hand and the revert keep the local gate.

A toy world, no network: the repo's `origin` URL is a GitHub one (so the regex matches) and its `pushurl` a local bare repository (so a
push lands there and nowhere else); `gh` is a script that answers from a scenario file and logs every call; PATH holds git, bash, sh and
that script only. The waits are shortened by `FWX_CI_POLL_S` and `FWX_CI_NO_RUN_S`, which the code reads for this purpose.

Seen red at 3bb7ef7 (no core/ci_gate.py, `verify` with no `ci`), the first FAILs: 82 checks, all the CI ones failing because the local gate was
the only one:
  FAIL: a green CI run of the head is the gate: the local checks did not run: got 1, want 0
  FAIL: the phase branch is pushed to origin, at the head: got '', want '<sha>'
  FAIL: decide: a green CI row of the head is evidence for the recipe: got (['evidence-recipe'], 0), want ([], 0)
Controls: each of `MUTANTS` is a copy of lib/ with one line changed and must fail with the FAIL named there; the good code passes first
(86 checks, 126 with the controls). Some of them, the FAIL seen:
  a failed run is not red:        FAIL: a failed CI run is a red gate: exit and gate rc: got (0, 0), want (1, 1)
  verify takes CI by default:     FAIL: fwx verify by hand pushes nothing: got '<sha>', want ''
  the branch is pushed with a +:  FAIL: a rejected push is never forced: the remote branch is as it was: got '<sha>', want '<the remote's sha>'
  the default branch is pushed:   FAIL: the default branch is never pushed: the local gate runs: got (0, 0, '<sha>', [...gh calls...])
  CI evidence judged by recipe:   FAIL: decide: a green CI row of the head is evidence for the recipe: got (['evidence-recipe'], 0), want ([], 0)
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
from test_wave_integrate import IDENT, J, Scene, stop_scenes  # noqa: E402
from test_wave_prepare import Scene as PrepScene  # noqa: E402
from test_wave_prepare import counting, evidence_rows, mutant_tree, ran, runner  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
from fwx import state  # noqa: E402

s = helpers.Suite()
URL = "https://github.com/example/toy.git"
CI = ".github/workflows/ci.yml"
RUN_URL = "https://github.com/example/toy/actions/runs/%d"

FAKE_GH = '''#!__PY__
import json, os, sys
D = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(os.path.join(D, "calls"), "a") as f:
    f.write(" ".join(args) + "\\n")
SC = json.load(open(os.path.join(D, "scenario.json")))
ST = os.path.join(D, "state.json")
state = json.load(open(ST)) if os.path.exists(ST) else {"polls": 0, "prs": [], "created": []}


def done(obj):
    json.dump(state, open(ST, "w"))
    print(json.dumps(obj))
    sys.exit(0)


def fail(msg):
    sys.stderr.write(msg + "\\n")
    sys.exit(1)


if SC.get("down"):
    fail("gh: connection refused")
method, path, body, rest = "GET", None, None, args[1:]
while rest:
    a = rest.pop(0)
    if a == "--method":
        method = rest.pop(0)
    elif a == "--input":
        rest.pop(0)
        body = json.load(sys.stdin)
    else:
        path = a
P = "repos/example/toy"
if args[:1] != ["api"] or not path:
    fail("unexpected: %s" % " ".join(args))
route, _, query = path.partition("?")
q = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv)
if route == P + "/pulls" and method == "GET":
    head = q.get("head", "")
    want = head.split(":", 1)[1] if q.get("state") == "open" and head.startswith("example:") else None
    done([pr for pr in state["prs"] if pr["head"]["ref"] == want])
if route == P + "/pulls" and method == "POST":
    pr = {"number": 7, "head": {"ref": body["head"]}, "base": body["base"], "draft": body.get("draft")}
    state["prs"].append(pr)
    state["created"].append(body)
    done(pr)
if route == P + "/pulls/7":
    done({"number": 7, "mergeable": SC.get("mergeable", True), "head": {"ref": "phase"}})
if route == P:
    done({"default_branch": SC.get("default_branch", "master")})
if route == P + "/actions/runs":
    ok = q.get("event") == "pull_request" and SC["sha"] in ("*", q.get("head_sha"))
    state["polls"] += 1
    polls = SC["polls"] if ok else [[]]
    done({"workflow_runs": polls[min(state["polls"], len(polls)) - 1]})
if route.startswith(P + "/actions/runs/") and route.endswith("/jobs"):
    done({"jobs": SC.get("jobs", {}).get(route.split("/")[-2], [])})
fail("unexpected: %s" % " ".join(args))
'''


def run_of(n, status="completed", conclusion=None):
    return {"id": n, "path": CI, "status": status, "conclusion": conclusion, "html_url": RUN_URL % n}


GREEN = [[run_of(101, "in_progress")], [run_of(101, "completed", "success")]]


class World:
    """A Scene (the integration checkout on `phase`, the part's folder) with the CI workflow committed on `phase`, a GitHub-looking origin
    that pushes into a bare repository, and a PATH of git, bash, sh and a fake `gh` that answers from `scenario`."""

    def __init__(self, polls=GREEN, quick=False, gh=True, origin=URL, ci_file=True, project=None, check_timeout_s=None, mergeable=True,
                 jobs=None, sha="head", down=False, env=None):
        d = helpers.mkdtemp("fwx-ci-")
        self.runs, self.qruns = os.path.join(d, "runs"), os.path.join(d, "qruns")
        self.sc = Scene(quick=[counting(self.qruns, "q")] if quick else (), checks=[counting(self.runs)], check_timeout_s=check_timeout_s)
        sc = self.sc
        if project:
            cfg = os.path.join(sc.repo, ".claude", "fwx.json")
            data = json.load(open(cfg))
            data["project"].update(project)
            open(cfg, "w").write(json.dumps(data))
        if ci_file:
            helpers.write(sc.cwd, CI, "name: CI\n")
            helpers.git(sc.cwd, "add", "-A")
            helpers.git(sc.cwd, "commit", "-q", "-m", "the CI workflow")
        sc.base = sc.head()  # the run's base is the commit with the workflow, so the diff since it names no trusted edit
        sc.run = "01-alpha-%s-1" % sc.base[:7]
        self.bare = os.path.join(d, "origin.git")
        helpers.git(d, "init", "-q", "--bare", self.bare)
        if origin:
            helpers.git(sc.repo, "remote", "add", "origin", origin)
            helpers.git(sc.repo, "config", "remote.origin.pushurl", self.bare)
        self.tools = helpers.mkdtemp("fwx-tools-")
        for tool in ("git", "bash", "sh"):
            found = shutil.which(tool)
            if found:
                os.symlink(found, os.path.join(self.tools, tool))
        if gh:
            helpers.write(self.tools, "gh", FAKE_GH.replace("__PY__", sys.executable), 0o755)
        self.scenario = {"sha": sc.head() if sha == "head" else sha, "polls": polls, "mergeable": mergeable, "jobs": jobs or {}, "down": down}
        helpers.write(self.tools, "scenario.json", json.dumps(self.scenario))
        self.extra_env = env or {}

    def env(self):
        return dict(IDENT, PATH=self.tools, FWX_CI_POLL_S="0.05", FWX_CI_NO_RUN_S="0.4", GIT_TERMINAL_PROMPT="0", **self.extra_env)

    def final(self, R, *branches):
        sc = self.sc
        args = ["--branches"] + list(branches) if branches else []
        return R(sc.cwd, "wave", "merge", "--part-dir", sc.part, "--run", sc.run, *args, "--final", env=self.env())

    def by_hand(self, R):
        return R(self.sc.cwd, "verify", "--dir", self.sc.part, env=self.env())

    def calls(self):
        p = os.path.join(self.tools, "calls")
        return open(p).read().splitlines() if os.path.exists(p) else []

    def gh_state(self):
        p = os.path.join(self.tools, "state.json")
        return json.load(open(p)) if os.path.exists(p) else {"polls": 0, "prs": [], "created": []}

    def pushed(self):
        r = subprocess.run(["git", "-C", self.bare, "rev-parse", "--verify", "-q", "refs/heads/phase"], env=helpers.clean_env(),
                           capture_output=True, text=True)
        return r.stdout.strip()

    def rows(self):
        return [dict(json.loads(r["detail"]), row_rc=r.get("rc", "").strip()) for r in self.sc.audit() if r.get("kind") == "evidence"]

    def ran(self):
        return ran(self.runs)

    def quick_ran(self):
        return ran(self.qruns)


def case_green(R, S):
    w = World(quick=True)
    head = w.sc.head()
    r = w.final(R)
    v = J(r) or {}
    S.eq("a green CI run of the head is the gate: exit, ok, gate rc", (r.returncode, v.get("ok"), (v.get("verify") or {}).get("rc")), (0, True, 0))
    S.eq("a green CI run of the head is the gate: the local checks did not run", w.ran(), 0)
    S.eq("checks_quick still runs first", w.quick_ran(), 1)
    S.eq("the phase branch is pushed to origin, at the head", w.pushed(), head)
    created = w.gh_state()["created"]
    S.eq("one draft pull request, from the phase branch to the default branch", [(c["head"], c["base"], c["draft"]) for c in created], [("phase", "master", True)])
    S.eq("the runs were polled until completed (two polls)", w.gh_state()["polls"], 2)
    S.ok("the poll asks for the pull_request runs of this exact sha", any("actions/runs?head_sha=%s&event=pull_request" % head in c for c in w.calls()), "\n".join(w.calls()))
    S.eq("the row is CI's: source, sha, rc and one command naming the workflow and the run",
         [(x["source"], x["sha"], x["rc"], x["row_rc"], x["commands"]) for x in w.rows()],
         [("ci", head, 0, "0", [{"cmd": "ci:%s:run-101" % CI, "rc": 0}])])
    S.ok("the result line is the evidence line of the row", (v.get("verify") or {}).get("line", "").startswith("evidence %s ci:%s:run-101=0" % (head, CI)), repr(v.get("verify")))
    r2 = w.final(R)
    # The run's URL is said as soon as the run exists (the owner watches the gate wait; `fwx wave run` echoes these lines). Seen red before the line:
    #   FAIL: the URL of the CI run is said while waiting -> stderr 'fwx wave merge: pushed phase at ...\nfwx wave merge: waiting for CI on pull request #1\n...' has no 'CI run '
    S.ok("the URL of the CI run is said while waiting", "CI run %s" % (RUN_URL % 101) in r.stderr, r.stderr)
    S.eq("a second gate on the same head: green again", (r2.returncode, w.ran()), (0, 0))
    S.eq("the draft is opened once", len(w.gh_state()["created"]), 1)
    stop_scenes()


def case_red(R, S):
    w = World(polls=[[run_of(102, "completed", "failure")]], jobs={"102": [{"name": "suite", "conclusion": "failure"}, {"name": "lint", "conclusion": "success"}]})
    r = w.final(R)
    v = J(r) or {}
    S.eq("a failed CI run is a red gate: exit and gate rc", (r.returncode, (v.get("verify") or {}).get("rc")), (1, 1))
    S.eq("a failed CI run is a red gate: the local checks did not run", w.ran(), 0)
    S.eq("the red row is CI's, rc 1, one command per failed job", [(x["source"], x["row_rc"], [c["cmd"] for c in x["commands"]]) for x in w.rows()],
         [("ci", "1", ["ci:%s:run-102:suite" % CI])])
    S.ok("stderr names the failed job and the run's URL", "suite" in r.stderr and RUN_URL % 102 in r.stderr, r.stderr)
    S.ok("a fixer is the next step", v.get("next") == "fix" and "suite" in (v.get("why") or ""), "%r %r" % (v.get("next"), v.get("why")))
    # Seen red before passing `urls` through verify/integrate:
    #   FAIL: a red CI run's URL reaches `why` and the fixer's brief: why='the gate failed on ...: evidence ... ci:...:run-102:suite=1' brief_has=False
    brief = open(v["brief"], encoding="utf-8").read() if v.get("brief") and os.path.exists(v["brief"]) else ""
    S.ok("a red CI run's URL reaches `why` and the fixer's brief", RUN_URL % 102 in (v.get("why") or "") and RUN_URL % 102 in brief,
         "why=%r brief_has=%s" % (v.get("why"), RUN_URL % 102 in brief))
    S.ok("the audited CI evidence row carries no extra `urls` key", "urls" not in (w.rows()[0] if w.rows() else {}), repr(w.rows()[:1]))
    stop_scenes()


def case_runs(R, S):
    other = dict(run_of(201, "completed", "failure"), path=".github/workflows/checks.yml")
    w = World(polls=[[other, run_of(202, "completed", "success"), run_of(203, "in_progress")], [other, run_of(202, "completed", "success"), run_of(203, "completed", "success")]])
    r = w.final(R)
    S.eq("every run of the workflow is waited for: two polls, green", (r.returncode, w.gh_state()["polls"], w.ran()), (0, 2, 0))
    S.eq("one command names all the runs of the workflow, and none of another workflow's", [x["commands"] for x in w.rows()], [[{"cmd": "ci:%s:run-202,203" % CI, "rc": 0}]])
    stop_scenes()
    w = World(polls=[[dict(run_of(204, "completed", "success"), path=CI + "@refs/pull/7/merge")]])
    r = w.final(R)
    S.eq("a run path that carries its ref is the workflow's", (r.returncode, [x["source"] for x in w.rows()]), (0, ["ci"]))
    stop_scenes()


def case_quick_red(R, S):
    w = World(project={"checks_quick": ["exit 1"]})
    r = w.final(R)
    S.eq("a red checks_quick stops before the gate: exit 1", r.returncode, 1)
    S.eq("a red checks_quick pushes nothing and asks GitHub nothing", (w.pushed(), w.calls()), ("", []))
    stop_scenes()


FALLBACKS = [
    # label, World kwargs, what the one line says
    ("gh is not installed", dict(gh=False), "gh is not installed"),
    ("gh does not answer", dict(down=True), "connection refused"),
    ("the origin is not GitHub", dict(origin="https://git.example.org/o/r.git"), "not a GitHub repository"),
    ("there is no origin", dict(origin=None), "no origin remote"),
    ("the CI workflow is not at the head", dict(ci_file=False), "is not at"),
    ("a cancelled run", dict(polls=[[run_of(103, "completed", "cancelled")]]), "cancelled"),
    ("no run within the window", dict(polls=[[]]), "no run of"),
    ("no result within check_timeout_s", dict(polls=[[run_of(104, "in_progress")]], check_timeout_s=1), "no result"),
    ("a conflicting draft pull request", dict(mergeable=False), "conflict"),
]


def case_fallback(R, S):
    for label, kw, said in FALLBACKS:
        w = World(**kw)
        r = w.final(R)
        S.eq("%s: the local gate runs and is green" % label, (r.returncode, w.ran()), (0, 1))
        S.eq("%s: one line says why" % label, r.stderr.count("CI gate not used"), 1)
        S.ok("%s: the line says %r" % (label, said), said in r.stderr, r.stderr)
        S.eq("%s: the row is the local gate's" % label, [x["source"] for x in w.rows()], ["profile"])
        stop_scenes()
    w = World(mergeable=False)
    w.final(R)
    S.ok("a conflicting draft stops the wait at once: no run was asked for", not any("actions/runs" in c for c in w.calls()), "\n".join(w.calls()))
    S.eq("a conflicting draft: the draft was opened once", len(w.gh_state()["created"]), 1)
    stop_scenes()
    for label, project in (("the default branch", {"default_branch": "phase"}), ("a production branch", {"production": {"branches": ["phase"], "commands": []}})):
        w = World(project=project)
        r = w.final(R)
        S.eq("%s is never pushed: the local gate runs" % label, (r.returncode, w.ran(), w.pushed(), w.calls()), (0, 1, "", []))
        S.ok("%s: the line says so" % label, "never pushes" in r.stderr and r.stderr.count("CI gate not used") == 1, r.stderr)
        stop_scenes()
    w = World()
    other = helpers.git(w.sc.repo, "commit-tree", "-m", "elsewhere", "master^{tree}").strip()
    helpers.git(w.sc.repo, "push", w.bare, "%s:refs/heads/phase" % other)
    r = w.final(R)
    S.eq("a rejected push is never forced: the remote branch is as it was", w.pushed(), other)
    S.eq("a rejected push runs the local gate with one line", (r.returncode, w.ran(), r.stderr.count("CI gate not used"), "push" in r.stderr), (0, 1, 1, True))
    S.eq("a rejected push opened no pull request", w.gh_state()["created"], [])
    stop_scenes()


def case_by_hand(R, S):
    w = World()
    r = w.by_hand(R)
    S.eq("fwx verify by hand: exit 0, the local checks ran", (r.returncode, w.ran()), (0, 1))
    S.eq("fwx verify by hand pushes nothing", w.pushed(), "")
    S.eq("fwx verify by hand asks GitHub nothing", w.calls(), [])
    S.eq("fwx verify by hand writes the local row", [x["source"] for x in w.rows()], ["profile"])
    stop_scenes()


def case_final_after_merge(R, S):
    w = World(polls=GREEN, sha="*")
    b = w.sc.agent("one", [("src/a.py", "a1\n", None)])
    r = w.final(R, b)
    v = J(r) or {}
    S.eq("a merge with --final: green on CI, no local check", (r.returncode, w.ran()), (0, 0))
    S.eq("the pushed head is the merge's", w.pushed(), v.get("head"))
    S.ok("the poll asks for the merge's sha", any("head_sha=%s&" % v.get("head") in c for c in w.calls()), "\n".join(w.calls()))
    stop_scenes()


def case_base_reuse(R, S):
    runs = os.path.join(helpers.mkdtemp("fwx-runs-"), "runs")
    sc = PrepScene(recipe=[counting(runs)])
    other = "0" * 40
    ev = {"sha": other, "clean": True, "source": "ci", "commands": [{"cmd": "ci:%s:run-9" % CI, "rc": 0}], "rc": 0}
    state.append_audit(sc.part, "evidence", detail=json.dumps(ev), rc=0, sha=other)
    r = sc.prepare(R)
    S.eq("a green CI row of another sha is not the base's checks: the checks run", (r.returncode, ran(runs)), (0, 1))
    sc2 = PrepScene(recipe=[counting(runs, "y")])
    state.append_audit(sc2.part, "evidence", detail=json.dumps({"sha": sc2.head(), "clean": True, "source": "ci", "commands": [{"cmd": "ci:%s:run-9" % CI, "rc": 1}], "rc": 1}),
                       rc=1, sha=sc2.head())
    n = ran(runs)
    r = sc2.prepare(R)
    S.eq("a red CI row is not the base's checks: the checks run", (r.returncode, ran(runs)), (0, n + 1))
    sc3 = PrepScene(recipe=[counting(runs, "z")])
    ev = {"sha": sc3.head(), "clean": True, "source": "ci", "commands": [{"cmd": "ci:%s:run-9" % CI, "rc": 0}], "rc": 0}
    state.append_audit(sc3.part, "evidence", detail=json.dumps(ev), rc=0, sha=sc3.head())
    n = ran(runs)
    r = sc3.prepare(R)
    S.eq("a green CI row of the base stands in for its checks: none runs", (r.returncode, ran(runs)), (0, n))
    S.ok("and says it reused the record", "base checks: reused the passing record of %s" % sc3.head()[:7] in r.stderr, r.stderr)
    S.eq("it writes no second row", len(evidence_rows(sc3)), 1)
    sc5 = PrepScene(recipe=[counting(runs, "v")])
    ev = {"sha": sc5.head(), "clean": True, "source": "ci", "commands": [{"cmd": "ci:%s:run-9" % CI, "rc": 0}, {"cmd": "ci:%s:run-10" % CI, "rc": 1}], "rc": 0}
    state.append_audit(sc5.part, "evidence", detail=json.dumps(ev), rc=0, sha=sc5.head())
    n = ran(runs)
    r = sc5.prepare(R)
    S.eq("a CI row with a command that failed is not the base's checks: the checks run", (r.returncode, ran(runs)), (0, n + 1))
    sc4 = PrepScene(recipe=[counting(runs, "w")])
    ev = {"sha": sc4.head(), "clean": True, "source": "profile", "commands": [{"cmd": "something else", "rc": 0}], "rc": 0}
    state.append_audit(sc4.part, "evidence", detail=json.dumps(ev), rc=0, sha=sc4.head())
    n = ran(runs)
    r = sc4.prepare(R)
    S.eq("a green row of other checks that is not CI's still stands in for nothing", (r.returncode, ran(runs)), (0, n + 1))


RECIPE = "python3 bin/fwx test"
HEAD = "a" * 40


def decision_facts(evidence):
    return {
        "mode": "trial", "labels": ["factory"], "type": "bug", "risk": "low", "surfaces": [],
        "agent": {"recommendation": "merge", "confident": True, "assumptions": ["sorted by name"]},
        "pr": {"number": 7, "head_sha": HEAD, "base": "factory", "mergeable": True, "running": False,
               "changed_files": [{"path": "src/list.py", "additions": 10, "deletions": 2}], "checks": [{"name": "ci", "state": "success"}]},
        "evidence": evidence, "plan_files": ["**"], "review": {"open_medium_high": 0, "running": False},
        "project": {"checks": [RECIPE], "protected_paths": [], "production": {"branches": [], "commands": []}, "ui_bugs": False},
    }


def case_decide(R, S):
    repo = helpers.toy_repo()
    tmp = helpers.mkdtemp("fwx-facts-")

    def reasons(evidence):
        p = helpers.write(tmp, "facts%d.json" % len(os.listdir(tmp)), json.dumps(decision_facts(evidence)))
        r = R(repo, "decide", "--facts", p)
        try:
            return [x.split(":")[0] for x in json.loads(r.stdout)["reasons"]], r.returncode
        except (ValueError, KeyError):
            return ["<not JSON: %r %r>" % (r.stdout[:80], r.stderr[:120])], r.returncode

    def ev(sha=HEAD, rc=0, source="ci", clean=True):
        return {"sha": sha, "clean": clean, "source": source, "commands": [{"cmd": "ci:%s:run-9" % CI, "rc": rc}], "rc": rc}

    S.eq("decide: a green CI row of the head is evidence for the recipe", reasons(ev()), ([], 0))
    S.eq("decide: a red CI row is evidence-failed", reasons(ev(rc=1)), (["evidence-failed"], 0))
    S.eq("decide: a CI row of another commit is evidence-head", reasons(ev(sha="b" * 40)), (["evidence-head"], 0))
    S.eq("decide: a dirty CI row is evidence-dirty", reasons(ev(clean=False)), (["evidence-dirty"], 0))
    S.eq("decide: the same command under another source is still outside the recipe", reasons(ev(source="profile")), (["evidence-recipe"], 0))
    S.eq("decide: a CI row with no command proves nothing", reasons(dict(ev(), commands=[])), (["evidence-recipe"], 0))


CASES = [case_green, case_red, case_runs, case_quick_red, case_fallback, case_by_hand, case_final_after_merge, case_base_reuse, case_decide]
CG, V, E, I, P = ("lib/fwx/core/ci_gate.py", "lib/fwx/core/verify.py", "lib/fwx/core/evidence.py", "lib/fwx/execute/integrate.py", "lib/fwx/execute/prepare.py")
# (name, case, file, old line, new line, the FAIL it must produce); each `old` is in its file exactly once.
MUTANTS = [
    ("a failed run is not red", case_red, CG, 'failed = [r for r in runs if r.get("conclusion") == "failure"]', "failed = []",
     "a failed CI run is a red gate: exit and gate rc"),
    ("a failed job is not named", case_red, CG, 'j.get("conclusion") == "failure" and j.get("name")', 'j.get("conclusion") == "success" and j.get("name")',
     "the red row is CI's, rc 1, one command per failed job"),
    ("verify takes CI by default", case_by_hand, V, "environ=None, ci=False):", "environ=None, ci=True):", "fwx verify by hand pushes nothing"),
    ("the final merge keeps the local gate", case_green, I, "verify.verify(top, part_dir, say, ci=True)", "verify.verify(top, part_dir, say)",
     "a green CI run of the head is the gate: the local checks did not run"),
    ("the branch is pushed with a +", case_fallback, CG, '"refs/heads/%s:refs/heads/%s" % (branch, branch)', '"+refs/heads/%s:refs/heads/%s" % (branch, branch)',
     "a rejected push is never forced"),
    ("an open draft is not looked for", case_green, CG, "if isinstance(open_, list) and open_ and", "if False and", "the draft is opened once"),
    ("the lookup of the draft names no owner", case_green, CG, 'quote("%s:%s" % (owner, branch), safe=":/")', 'quote(branch, safe=":/")', "the draft is opened once"),
    ("a conflict is not seen", case_fallback, CG, '.get("mergeable") is False:', '.get("mergeable") is False and False:',
     "a conflicting draft pull request: the local gate runs and is green"),
    ("the default branch is pushed", case_fallback, CG, "    if branch in protected:\n", "    if False:\n", "the default branch is never pushed"),
    ("a production branch is pushed", case_fallback, V, ' | set((cfg["project"].get("production") or {}).get("branches") or [])', "",
     "a production branch is never pushed"),
    ("no run is green", case_fallback, CG, "            if runs and all(r.get(", "            if all(r.get(", "no run within the window: the local gate runs and is green"),
    ("a cancelled run is green", case_fallback, CG, "    if odd:\n", "    if False:\n", "a cancelled run: the local gate runs and is green"),
    ("a run in progress is waited for no longer", case_runs, CG, 'all(r.get("status") == "completed" for r in runs)', 'any(r.get("status") == "completed" for r in runs)',
     "every run of the workflow is waited for"),
    ("another workflow's run counts", case_runs, CG, ' and str(r.get("path") or "").split("@")[0] == CI_WORKFLOW]', "]",
     "every run of the workflow is waited for"),
    ("a run path with its ref is not the workflow's", case_runs, CG, 'str(r.get("path") or "").split("@")[0] == CI_WORKFLOW', 'str(r.get("path") or "") == CI_WORKFLOW',
     "a run path that carries its ref is the workflow's"),
    ("the poll sees every event", case_green, CG, "&event=pull_request&per_page=100", "&per_page=100", "a green CI run of the head is the gate: the local checks did not run"),
    ("CI evidence is judged by the recipe", case_decide, E, "ci = evidence.get(\"source\") == CI_SOURCE and bool(rows)", "ci = False",
     "decide: a green CI row of the head is evidence for the recipe"),
    ("CI evidence with no command is green", case_decide, E, 'evidence.get("source") == CI_SOURCE and bool(rows)', 'evidence.get("source") == CI_SOURCE',
     "decide: a CI row with no command proves nothing"),
    ("any green row stands in for the base", case_base_reuse, P, 'detail.get("source") == evidence.CI_SOURCE and got and', "got and",
     "a green row of other checks that is not CI's still stands in for nothing"),
    ("a CI row's failed command is ignored", case_base_reuse, P, "got and all(rc == 0 for _, rc in got))", "got)",
     "a CI row with a command that failed is not the base's checks"),
    ("a red CI run's URL is dropped before the fixer", case_red, I, 'line + (" (%s)" % ", ".join(urls) if urls else "")', "line",
     "a red CI run's URL reaches `why` and the fixer's brief"),
]


if __name__ == "__main__":
    real = runner(ROOT)
    real.root = ROOT
    for case in CASES:
        case(real, s)
    for name, case, path, old, new, needle in MUTANTS:
        m = helpers.FirstFail(lambda f, needle=needle: needle in f)  # the control reads one FAIL: the case stops at it
        try:
            tree = mutant_tree(path, old, new)
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        R = runner(tree)
        R.root = tree
        m.run(case, R, m)
        stop_scenes()
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
    s.done()
