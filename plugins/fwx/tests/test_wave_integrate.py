#!/usr/bin/env python3
"""`fwx wave merge|fix|revert|remove` and `fwx wave` alone (3.4 U3): lib/fwx/commands/wave.py, execute/integrate.py, execute/cleanup.py.

The run builds toy repos (tests/helpers.py `toy_repo`, with a linked worktree on the phase branch as the session has and one
linked worktree per fake executor, on `worktree-agent-<name>` as Claude Code names them) and asks the command through `bin/fwx`.
Nothing here reads the real HOME, the real configuration or a real project. Processes are planted on purpose: a `sleep` for a
live agent (its pid and the start time of /proc/<pid>/stat go into the lock, as Claude Code writes them) and a finished one for
a dead agent.

Seen red before the code existed (python3 tests/test_wave_integrate.py, first lines; the five subcommands exited 2 "not built yet"):
  FAIL: integrate, two clean branches: exit: got (2, 'fwx wave merge: not built yet (3.4 U3)'), want (0, '')
  FAIL: integrate, two clean branches: stdout is JSON: got <not JSON: ''>, want an object
  FAIL: integrate: ok, merged in order: got (None, None), want (True, ['worktree-agent-one', 'worktree-agent-two'])

Red before `integrate --final` took no branch (3.4 align):
  FAIL: integrate --final with no branch: exit: got (2, 'usage: fwx wave merge --part-dir D --run R --branches B... [--final]'), want (0, '')

Red before `summary` looked at the run's own gate (3.4 U8 fix, F3: `summary --run <earlier failed run>` said `pass`):
  FAIL: summary, an earlier run that never ran the gate, green evidence of HEAD from elsewhere: gate got 'pass': got ('pass', 0), want ('fail', 1)
  FAIL: summary, the run's own last gate is red, later green evidence: gate got 'pass': got ('pass', 0), want ('fail', 1)

Red before `next` existed (09.5 T52; case_next and case_next_rules, a conflict, a red check, findings, a lock, a final merge, a result that names no cause):
  FAIL: a conflict says next resolve -> no next: got None, want 'resolve'
  FAIL: next_step: one answer per case (AttributeError: module 'fwx.execute.integrate' has no attribute 'next_step'): got 0, want 12

Red before `summary` carried what the part report reads (09.5 T54, case_summary_report; the same line for criteria, outside, tried, gaps, protected):
  FAIL: fwx wave --run R has findings -> missing
The controls of that case, first FAIL of each (the retry's item, a pass counted at its verify call too, a refused round, a refused merge, no commit, a gap):
  FAIL: fwx wave --run R: outside: got [{... 'src/x.py:1' ...}, {... 'src/gone.py:9' ...}]
  FAIL: fwx wave --run R: findings: got {'reported': 10, 'fix': 1, ...} (want 'reported': 5)
  FAIL: fwx wave --run R: tried: got ['1/3: gate red', '3/3: again'], want ['1/3: gate red']
  FAIL: fwx wave --run R: gaps: got [], want ['executor did not return: T3', 'reviewer did not return']

Controls: each case also runs on a copy of bin/ and lib/ with one line of the code changed (`MUTANTS` below, each `old` must be in
its file exactly once), and must fail with the text in `MUTANTS`; the good code passes first (138 checks, 170 with the controls).
The first FAIL line of each mutant, seen red:
  integrate spends a round on a conflict:   FAIL: rounds 1/3 after integrate: got 'rounds 1/3', want 'rounds 0/3'
  liveness reads only `locked`:             FAIL: integrate, a dead pid holds the lock: exit: got (2, '... a live agent holds worktree-agent-dead: nothing merged'), want (0, '')
  liveness never sees a live agent:         FAIL: integrate, a live agent holds a branch: exit: got 0, want 2
  a commit may carry two findings:          FAIL: integrate, one commit for two findings: refused: got 0, want 2
  fix-round never spends:                   FAIL: fix-round, a conflict with nothing counted: rounds 0/3: got 'rounds 0/3', want 'rounds 1/3'
  fix-round spends on a counted failure:    FAIL: fix-round, red evidence of HEAD: rounds 2/3: got 'rounds 2/3', want 'rounds 1/3'
  fix-round decides by the counter after:   FAIL: fix-round, 2 used before: fix-round exit 1 with 2 of 3 rounds used before this failure: got 1, want 0
  fix-round spends before looking:          FAIL: fix-round, 3 used before: rounds 4/3: got 'rounds 4/3', want 'rounds 3/3' (after an earlier line for the same cause)
  fix-round writes a stage row:             FAIL: fix-round: stage rows written: 1: got 1, want 0
  cleanup deletes by prefix:                FAIL: cleanup: removed a worktree of another run: got True, want False
  cleanup keeps a stale-locked worktree:    FAIL: cleanup: kept a stale-locked worktree: True: got (False, True), want (True, False)
  cleanup without /proc runs on:            FAIL: cleanup, no /proc: exit 1: got 1, want 77
  summary ignores the exit of the evidence: FAIL: summary, red evidence: gate: got 'pass': got 'pass', want 'fail'
  summary ignores the sha of the evidence:  FAIL: summary, evidence of another sha: gate: got 'pass': got 'pass', want 'fail'
  summary never finds the part:             FAIL: summary, from the run files: gate: got 'none': got ('none', 2), want ('pass', 0)
  step files all numbered 0:                FAIL: step files: one per call, numbered: got ['0-fix-round.json', '0-integrate.json', '0-revert.json'], want [...]
"""
import json
import os
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
from test_wave_prepare import CRIT, front, mutant_tree, runner, task  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
from fwx import state  # noqa: E402
from fwx.core import rounds as rounds_mod  # noqa: E402

s = helpers.Suite()
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
PY = sys.executable


SCENES = []  # every Scene made: stop_scenes() ends the agents a control run cut short by helpers.FirstFail left planted


def stop_scenes():
    while SCENES:
        SCENES.pop().stop()


# A step keeps its internal name (it is the `step` of the run's files); the words after `fwx` that run it are the grammar's.
STEP_WORDS = {"integrate": ("wave", "merge"), "fix-round": ("wave", "fix"), "revert": ("wave", "revert"), "cleanup": ("wave", "remove"),
              "summary": ("wave",), "scratch": ("scratch", "new")}


class Scene:
    """A main checkout on master, the integration checkout (a linked worktree on `phase`), the part's folder in the main
    checkout's `.fwx/`, and fake executors: a linked worktree each, on `worktree-agent-<name>`, born from `phase`."""

    def __init__(self, quick=(), protected=(), checks=("true",), check_timeout_s=None):
        self.repo = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n.claude/\n", "src/a.py": "a\n", "src/b.py": "b\n"})
        project = {"checks": list(checks), "checks_quick": list(quick), "protected_paths": list(protected)}
        if check_timeout_s:
            project["check_timeout_s"] = check_timeout_s
        helpers.write(self.repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": project}))
        self.cwd = helpers.add_worktree(self.repo, "phase")
        self.part = os.path.join(self.repo, ".fwx", "milestones", "v1", "phases", "01-alpha")
        os.makedirs(self.part)
        # what a brief is made from: the part's plan (its tasks' files and tests) and the phase's context and decisions
        helpers.write(self.part, "plan.md", front({"size": {"tag": "normal", "parts": 1, "agents": 2}, "criteria": CRIT, "not_built": [], "later": [],
                                                   "tasks": [task("T1", 1, ["src/a.py"]), task("T2", 2, ["src/b.py"])]}))
        helpers.write(self.part, "context.md", "# context\n")
        helpers.write(self.part, "decisions.tsv", "date\tid\tdecision\twhy\trejected\tsupport\tsource\tsupersedes\n")
        self.base = self.head()
        self.run = "01-alpha-%s-1" % self.base[:7]
        self.common = os.path.join(self.repo, ".git")
        self.trees = {}
        self.procs = []
        SCENES.append(self)

    def head(self, cwd=None):
        return helpers.git(cwd or self.cwd, "rev-parse", "HEAD").strip()

    def agent(self, name, changes, run=None):
        """A worktree `name` on `worktree-agent-<name>` from `phase`, one commit per (file, text, finding ids) of `changes`,
        each with Fwx-Run (this run's, or `run`) and its Fwx-Finding trailers. Returns the branch."""
        branch = "worktree-agent-" + name
        wt = os.path.join(helpers.mkdtemp("fwx-agent-"), name)
        helpers.git(self.repo, "worktree", "add", "-q", "-b", branch, wt, "phase")
        self.trees[branch] = os.path.realpath(wt)
        for rel, text, findings in changes:
            helpers.write(wt, rel, text)
            helpers.git(wt, "add", "-A")
            trailers = "\n".join(["Fwx-Task: 01-alpha/%s" % name, "Fwx-Run: %s" % (run or self.run)]
                                 + ["Fwx-Finding: %s" % f for f in findings or ()])
            helpers.git(wt, "commit", "-q", "-m", "work on %s\n\n%s" % (rel, trailers))
        return branch

    def lock(self, branch, pid, start):
        helpers.git(self.repo, "worktree", "lock", "--reason", "claude agent agent-x (pid %d start %s)" % (pid, start), self.trees[branch])

    def live(self):
        """(pid, start) of a process that is running."""
        p = subprocess.Popen(["sleep", "300"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p.pid, start_of(p.pid)

    def dead(self):
        """(pid, start) of a process that has finished (its start time is the one it had)."""
        p = subprocess.Popen(["sleep", "300"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        start = start_of(p.pid)
        p.kill()
        p.wait()
        return p.pid, start

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
        self.procs = []

    def call(self, R, step, *args, cwd=None):
        return R(cwd or self.cwd, *STEP_WORDS[step], *args, env=IDENT)

    def integrate(self, R, *branches, extra=()):
        return self.call(R, "integrate", "--part-dir", self.part, "--run", self.run, "--branches", *branches, *extra)

    def audit(self):
        return state.read_rows(os.path.join(self.part, "audit.tsv"))

    def evidence(self, rc, sha=None, cmds=(("true", 0),)):
        sha = sha or self.head()
        ev = {"sha": sha, "clean": True, "source": "profile", "commands": [{"cmd": c, "rc": r} for c, r in cmds], "rc": rc}
        state.append_audit(self.part, "evidence", detail=json.dumps(ev), rc=rc, sha=sha)

    def use(self, n):
        for i in range(n):
            state.append_audit(self.part, "round", detail="use earlier %d" % i)

    def rounds(self):
        return "rounds %d/3" % rounds_mod.count(self.audit())

    def stages(self):
        return sum(1 for r in self.audit() if r.get("kind") == "stage")

    def clean(self):
        return helpers.git(self.cwd, "status", "--porcelain", "--", ".", ":(exclude).fwx").strip() == "" and \
            not os.path.exists(os.path.join(self.cwd_gitdir(), "MERGE_HEAD"))

    def cwd_gitdir(self):
        return helpers.git(self.cwd, "rev-parse", "--path-format=absolute", "--git-dir").strip()

    def step_files(self, run=None):
        d = os.path.join(self.common, "fwx", "runs", run or self.run)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []


def start_of(pid):
    with open("/proc/%d/stat" % pid) as f:
        return f.read().rsplit(")", 1)[1].split()[19]


def J(r):
    try:
        v = json.loads(r.stdout)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def ok_json(S, label, r, code=0):
    S.eq("%s: exit" % label, (r.returncode, r.stderr.strip()[:200] if r.returncode != code else ""), (code, ""))
    v = J(r)
    S.ok("%s: stdout is JSON" % label, v is not None, "got <not JSON: %r>, want an object" % r.stdout[:80])
    return v or {}


def exists(path):
    return os.path.exists(path)


# ---------------------------------------------------------------------------------------------------- integrate

def case_integrate_clean(R, S):
    sc = Scene()
    b1 = sc.agent("one", [("src/a.py", "a1\n", None)])
    b2 = sc.agent("two", [("src/b.py", "b2\n", None)])
    r = sc.integrate(R, b1, b2)
    v = ok_json(S, "integrate, two clean branches", r)
    S.eq("integrate: ok, merged in order", (v.get("ok"), v.get("merged")), (True, [b1, b2]))
    S.eq("integrate: head is the checkout's HEAD", v.get("head"), sc.head())
    S.eq("integrate: no conflict, nothing locked", (v.get("conflict"), v.get("locked")), (None, []))
    parents = helpers.git(sc.cwd, "rev-list", "--parents", "-n", "1", "HEAD").split()
    S.eq("integrate: the last merge is --no-ff (two parents)", len(parents) - 1, 2)
    S.eq("integrate: both changes are in", (open(os.path.join(sc.cwd, "src/a.py")).read(), open(os.path.join(sc.cwd, "src/b.py")).read()), ("a1\n", "b2\n"))
    S.ok("integrate: the merged worktrees are removed", not exists(sc.trees[b1]) and not exists(sc.trees[b2]))
    S.ok("integrate: the branches go with them", "worktree-agent-one" not in helpers.git(sc.repo, "branch", "--list"))
    S.eq("integrate: no round spent, no row written", (sc.rounds(), sc.audit()), ("rounds 0/3", []))
    S.eq("integrate: quick not run when there is none", v.get("quick", {}).get("ran"), False)
    S.eq("integrate: the call left its file in the run", sc.step_files(), ["1-integrate.json"])
    S.eq("integrate: no verify without --final", v.get("verify", {}).get("ran"), False)
    sc.stop()


def case_integrate_conflict(R, S):
    sc = Scene()
    b1 = sc.agent("one", [("src/a.py", "mine\n", None)])
    b2 = sc.agent("two", [("src/a.py", "yours\n", None)])
    b3 = sc.agent("three", [("src/b.py", "b3\n", None)])
    v = ok_json(S, "integrate, conflict", sc.integrate(R, b1, b2, b3), code=1)
    S.eq("conflict: ok false, the first branch merged, nothing after the conflict", (v.get("ok"), v.get("merged")), (False, [b1]))
    S.eq("conflict: names the branch and the files", v.get("conflict"), {"branch": b2, "files": ["src/a.py"]})
    S.ok("conflict: the tree is clean and no merge is open", sc.clean())
    S.ok("conflict: the branch after the conflict is not touched", exists(sc.trees[b3]))
    got = sc.rounds()
    S.eq("rounds %s after integrate" % got.replace("rounds ", ""), got, "rounds 0/3")
    S.eq("conflict: no audit row", sc.audit(), [])
    sc.stop()


def case_integrate_quick(R, S):
    sc = Scene(quick=["exit 3"])
    b1 = sc.agent("one", [("src/a.py", "a1\n", None)])
    v = ok_json(S, "integrate, quick red", sc.integrate(R, b1), code=1)
    q = v.get("quick") or {}
    S.eq("quick red: ok false, merged anyway, ran with its exit", (v.get("ok"), v.get("merged"), q.get("ran"), q.get("rc"), q.get("cmds")),
         (False, [b1], True, 3, ["exit 3"]))
    S.ok("quick red by its own exit: no timed_out, no limit in the result", "timed_out" not in q and "limit" not in q, "quick: %s" % q)
    sg = Scene(quick=["true"])
    b = sg.agent("one", [("src/a.py", "a1\n", None)])
    v = ok_json(S, "integrate, quick green", sg.integrate(R, b))
    S.eq("quick green: ok true, ran with exit 0", (v.get("ok"), v.get("quick", {}).get("ran"), v.get("quick", {}).get("rc")), (True, True, 0))
    # DTC-113: the quick check runs under the project's own limit. A 2 s check with `check_timeout_s` 1 is stopped, which is not a pass.
    nap = "%s -c 'import time; time.sleep(2)'" % shlex.quote(sys.executable)
    st = Scene(quick=[nap], check_timeout_s=1)
    b = st.agent("one", [("src/a.py", "a1\n", None)])
    r = st.integrate(R, b)
    v = ok_json(S, "integrate, quick over the project's limit", r, code=1)
    S.eq("quick over check_timeout_s: ok false, rc 1 (the check was killed)", (v.get("ok"), (v.get("quick") or {}).get("rc")), (False, 1))
    # PR 223, CodeRabbit: the result said rc 1 and nothing else, so a stopped check looked like a failing one. Report it as the gate does:
    # which check timed out, the limit it had, and what to do about it.
    # Seen red: FAIL: quick over check_timeout_s: the result names the check that timed out and its limit: got (None, None), want ([<nap>], 1)
    q = v.get("quick") or {}
    S.eq("quick over check_timeout_s: the result names the check that timed out and its limit", (q.get("timed_out"), q.get("limit")), ([nap], 1))
    S.ok("quick over check_timeout_s: stderr says to raise project.check_timeout_s", "timed out after 1 s" in r.stderr and "raise `project.check_timeout_s`" in r.stderr, r.stderr)
    sc.stop()
    sg.stop()
    st.stop()


def case_integrate_dirty(R, S):
    sc = Scene()
    b1 = sc.agent("one", [("src/a.py", "a1\n", None)])
    helpers.write(sc.cwd, "README", "edited\n")
    before = sc.head()
    r = sc.integrate(R, b1)
    S.eq("dirty checkout: exit", r.returncode, 2)
    S.ok("dirty checkout: the refusal says why", "uncommitted" in r.stderr, r.stderr[:200])
    S.eq("dirty checkout: nothing merged", sc.head(), before)


def case_integrate_lock(R, S):
    sc = Scene()
    b_live = sc.agent("live", [("src/a.py", "a1\n", None)])
    b_other = sc.agent("other", [("src/b.py", "b2\n", None)])
    sc.lock(b_live, *sc.live())
    before = sc.head()
    r = sc.integrate(R, b_other, b_live)
    v = J(r) or {}
    S.eq("integrate, a live agent holds a branch: exit", r.returncode, 2)
    got = sc.head() != before
    S.eq("merged a locked worktree: %s" % got, got, False)
    S.eq("live agent: nothing merged at all, the lock is named", (v.get("merged"), [x.get("branch") for x in v.get("locked") or []]), ([], [b_live]))
    S.eq("live agent: the result is in the run", sc.step_files(), ["1-integrate.json"])
    sc.stop()

    sd = Scene()
    b_dead = sd.agent("dead", [("src/a.py", "a1\n", None)])
    sd.lock(b_dead, *sd.dead())
    v = ok_json(S, "integrate, a dead pid holds the lock", sd.integrate(R, b_dead))
    S.eq("refused a stale lock: %s" % (v.get("ok") is not True), (v.get("ok"), v.get("merged")), (True, [b_dead]))
    sd.stop()

    so = Scene()
    b_start = so.agent("start", [("src/a.py", "a1\n", None)])
    pid, start = so.live()
    so.lock(b_start, pid, int(start) + 1)
    v = ok_json(S, "integrate, a live pid with another start time", so.integrate(R, b_start))
    S.eq("a pid that lives with another start is not the agent", (v.get("ok"), v.get("merged")), (True, [b_start]))
    so.stop()


def case_integrate_findings(R, S):
    sc = Scene()
    b1 = sc.agent("fix", [("src/a.py", "a1\n", ["F1", "F2"])])
    before = sc.head()
    r = sc.integrate(R, b1, extra=("--findings", "F1,F2"))
    v = J(r) or {}
    S.eq("integrate, one commit for two findings: refused", r.returncode, 2)
    S.eq("one commit for two findings: nothing merged, the check says so", (sc.head(), (v.get("findings_check") or {}).get("ok")), (before, False))
    S.ok("one commit for two findings: the problem names the commit and both ids",
         any("F1" in p and "F2" in p for p in (v.get("findings_check") or {}).get("problems", [])), repr(v.get("findings_check")))

    sm = Scene()
    b = sm.agent("fix", [("src/a.py", "a1\n", ["F1"])])
    v = ok_json(S, "integrate, a finding no commit carries", sm.integrate(R, b, extra=("--findings", "F1,F9")), code=2)
    S.eq("a finding no commit carries: refused, named", (v.get("ok"), any("F9" in p for p in (v.get("findings_check") or {}).get("problems", []))), (False, True))

    s2 = Scene()
    b = s2.agent("fix", [("src/a.py", "a1\n", ["F1"]), ("src/b.py", "b2\n", ["F2"])])
    v = ok_json(S, "integrate, one commit per finding", s2.integrate(R, b, extra=("--findings", "F1,F2")))
    S.eq("one commit per finding: ok", (v.get("ok"), (v.get("findings_check") or {}).get("ok")), (True, True))
    # revert: F1 only leaves F2's change
    r = s2.call(R, "revert", "--part-dir", s2.part, "--run", s2.run, "--findings", "F1")
    v = ok_json(S, "revert F1", r)
    S.eq("revert F1: F1's change is gone, F2's stays", (open(os.path.join(s2.cwd, "src/a.py")).read(), open(os.path.join(s2.cwd, "src/b.py")).read()), ("a\n", "b2\n"))
    S.eq("revert: head, no round spent, no row", (v.get("head"), s2.rounds(), s2.audit()), (s2.head(), "rounds 0/3", []))
    S.eq("revert: names the finding it reverted", [x.get("id") for x in v.get("reverted") or []], ["F1"])
    S.ok("revert: a clean tree", s2.clean())
    # both, newest first: the history is reverted from the end
    s3 = Scene()
    b = s3.agent("fix", [("src/a.py", "a1\n", ["F1"]), ("src/a.py", "a2\n", ["F2"])])
    ok_json(S, "integrate, two findings on one file", s3.integrate(R, b, extra=("--findings", "F1,F2")))
    v = ok_json(S, "revert F1,F2 on one file", s3.call(R, "revert", "--part-dir", s3.part, "--run", s3.run, "--findings", "F1,F2"))
    S.eq("revert F1,F2: newest first, so no conflict and the file is back", (open(os.path.join(s3.cwd, "src/a.py")).read(), [x.get("id") for x in v.get("reverted") or []]), ("a\n", ["F2", "F1"]))
    before = s3.head()
    r = s3.call(R, "revert", "--part-dir", s3.part, "--run", s3.run, "--findings", "F7")
    S.eq("revert, an id no commit carries: exit 2 and nothing changed", (r.returncode, s3.head()), (2, before))
    sc.stop()


def case_integrate_final(R, S):
    sc = Scene(protected=["src/secret/**"])
    b1 = sc.agent("one", [(".github/workflows/ci.yml", "name: x\n", None), ("src/secret/k.py", "k\n", None)])
    v = ok_json(S, "integrate --final", sc.integrate(R, b1, extra=("--final",)))
    S.eq("final: verify ran green with its line", (v.get("verify", {}).get("rc"), (v.get("verify", {}).get("line") or "").startswith("evidence %s " % sc.head())), (0, True))
    S.ok("final: a workflow edit is a trusted edit", bool(v.get("trusted")), repr(v.get("trusted")))
    S.eq("final: protected paths, the workflow and the configured one", sorted(v.get("protected") or []),
         [".github/workflows/ci.yml", "src/secret/k.py"])
    S.eq("final: verify wrote its evidence row in the part", [(r.get("kind"), r.get("rc")) for r in sc.audit()], [("evidence", "0")])
    sc.stop()
    sg = Scene()
    b = sg.agent("one", [("src/a.py", "a1\n", None)])
    v = ok_json(S, "integrate --final, a plain diff", sg.integrate(R, b, extra=("--final",)))
    S.eq("final: nothing trusted, nothing protected", (v.get("trusted"), v.get("protected")), ([], []))
    sr = Scene(checks=["exit 1"])
    b = sr.agent("one", [(".github/workflows/ci.yml", "name: x\n", None)])
    v = ok_json(S, "integrate --final, a red gate", sr.integrate(R, b, extra=("--final",)), code=1)
    S.eq("final, red gate: ok false and nothing said about trust", (v.get("ok"), v.get("verify", {}).get("rc"), v.get("trusted")), (False, 1, []))
    sg.stop()
    sr.stop()


def case_integrate_gate_only(R, S):
    """3.4 align: `integrate --final` with no branch runs the gate on the head as it is (the re-entry at n_C7 once the tasks are
    merged), and reports the trusted edits and protected paths of everything since the run's base."""
    sc = Scene(protected=["src/secret/**"])
    b1 = sc.agent("one", [(".github/workflows/ci.yml", "name: x\n", None), ("src/secret/k.py", "k\n", None)])
    ok_json(S, "gate only, the merge before", sc.integrate(R, b1))
    r = sc.call(R, "integrate", "--part-dir", sc.part, "--run", sc.run, "--final")
    v = ok_json(S, "integrate --final with no branch", r)
    S.eq("gate only: ok, nothing merged, verify ran green on the head", (v.get("ok"), v.get("merged"), v.get("verify", {}).get("ran"), v.get("verify", {}).get("rc")), (True, [], True, 0))
    S.eq("gate only: the head is unchanged", v.get("head"), sc.head())
    S.ok("gate only: a workflow edit since the base is a trusted edit", bool(v.get("trusted")), repr(v.get("trusted")))
    S.eq("gate only: protected paths since the base", sorted(v.get("protected") or []), [".github/workflows/ci.yml", "src/secret/k.py"])
    S.eq("gate only: the evidence row is the head's", [(r.get("kind"), r.get("rc"), r.get("sha")) for r in sc.audit()], [("evidence", "0", sc.head())])
    r = sc.call(R, "integrate", "--part-dir", sc.part, "--run", sc.run)
    S.eq("no branch and no --final: usage, exit %d" % r.returncode, (r.returncode, "usage: fwx wave merge" in r.stderr, r.stdout), (2, True, ""))
    sc.stop()


# ---------------------------------------------------------------------------------------------------- fix-round

def fix(R, sc, why="the wave would not merge"):
    return sc.call(R, "fix-round", "--part-dir", sc.part, "--why", why, "--run", sc.run)


def case_fix_round(R, S):
    a = Scene()
    r = fix(R, a)
    ok_json(S, "fix-round, nothing counted yet", r)
    got = a.rounds()
    S.eq("fix-round, a conflict with nothing counted: %s" % got, got, "rounds 1/3")
    S.eq("fix-round: the call left its file in the run", a.step_files(), ["1-fix-round.json"])
    S.eq("fix-round: no stage row", a.stages(), 0)

    b = Scene()
    b.evidence(1)
    ok_json(S, "fix-round, red evidence of HEAD", fix(R, b))
    got = b.rounds()
    S.eq("fix-round, red evidence of HEAD: %s" % got, got, "rounds 1/3")

    c = Scene()
    c.use(2)
    c.evidence(1)
    r = fix(R, c)
    S.eq("fix-round, 2 used before: fix-round exit %d with 2 of 3 rounds used before this failure" % r.returncode, r.returncode, 0)
    S.eq("fix-round, 2 used before: the failure is the third round", c.rounds(), "rounds 3/3")

    d = Scene()
    d.use(3)
    r = fix(R, d)
    v = J(r) or {}
    S.eq("fix-round, 3 used before: exit", r.returncode, 1)
    got = d.rounds()
    S.eq("fix-round, 3 used before: %s" % got, got, "rounds 3/3")
    S.eq("fix-round, 3 used before: says it did not spend", (v.get("ok"), v.get("spent")), (False, False))

    e = Scene()
    e.use(3)
    e.evidence(1)
    r = fix(R, e)
    S.eq("fix-round, red evidence of HEAD with 3 used before: the same failure after the last fix is the next one: exit", r.returncode, 1)

    f = Scene()
    f.evidence(1, sha="0" * 40)
    ok_json(S, "fix-round, red evidence of another sha", fix(R, f))
    S.eq("fix-round, evidence of another sha is not this failure: it spends", f.rounds(), "rounds 2/3")

    g = Scene()
    r = g.call(R, "fix-round", "--part-dir", g.part, "--why", "  ")
    S.eq("fix-round, a blank reason: exit 2 and nothing written", (r.returncode, g.audit()), (2, []))

    for sc, label in ((a, "a"), (b, "b"), (c, "c")):
        got = sc.stages()
        S.eq("fix-round: stage rows written: %d" % got, got, 0)


# ---------------------------------------------------------------------------------------------------- cleanup

def case_cleanup(R, S):
    sc = Scene()
    pl = sc.agent("plain", [("src/a.py", "a1\n", None)])
    other = sc.agent("other", [("src/b.py", "b2\n", None)], run="01-alpha-deadbee-1")
    unm = sc.agent("unmerged", [("src/c.py", "c\n", None)])
    dirty = sc.agent("dirty", [("src/d.py", "d\n", None)])
    stale = sc.agent("stale", [("src/e.py", "e\n", None)])
    livel = sc.agent("livelock", [("src/f.py", "f\n", None)])
    busy = sc.agent("busy", [("src/g.py", "g\n", None)])
    for b in (pl, other, dirty, stale, livel, busy):  # merged into the phase branch by hand, worktrees stay
        helpers.git(sc.cwd, "merge", "-q", "--no-ff", "-m", "merge " + b, b)
    helpers.write(sc.trees[dirty], "untracked.txt", "x\n")
    sc.lock(stale, *sc.dead())
    sc.lock(livel, *sc.live())
    p = subprocess.Popen(["sleep", "300"], cwd=sc.trees[busy], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sc.procs.append(p)
    r = sc.call(R, "cleanup", "--run", sc.run)
    v = ok_json(S, "cleanup", r)
    removed = [x.get("branch") for x in v.get("removed") or []]
    kept = {x.get("branch"): x.get("why", "") for x in v.get("kept") or []}
    S.ok("cleanup removed the merged worktree of its run", pl in removed and not exists(sc.trees[pl]), "removed %r" % removed)
    got = exists(sc.trees[other]) is False
    S.eq("cleanup: removed a worktree of another run", got, False)
    S.ok("cleanup: its branch is gone, the other run's stays", pl not in helpers.git(sc.repo, "branch", "--list") and other in helpers.git(sc.repo, "branch", "--list"))
    S.ok("cleanup: unmerged commits are kept and say so", unm in kept and "unmerged" in kept[unm] and exists(sc.trees[unm]), repr(kept))
    S.ok("cleanup: a dirty worktree is kept and says so", dirty in kept and "dirty" in kept[dirty], repr(kept))
    got = stale in kept
    S.eq("cleanup: kept a stale-locked worktree: %s" % got, (stale in removed, got), (True, False))
    S.ok("cleanup: kept a live-locked worktree", livel in kept and "live" in kept[livel] and exists(sc.trees[livel]), repr(kept))
    S.ok("cleanup: the phase branch and its worktree are never touched", exists(sc.cwd) and "phase" in helpers.git(sc.repo, "branch", "--list"))
    left = v.get("leftover") or []
    S.ok("cleanup: lists the process planted in a worktree of the run", any(x.get("pid") == p.pid for x in left), repr(left))
    S.ok("cleanup: does not kill it", p.poll() is None)
    S.ok("cleanup: the planted process's worktree is listed too", any(x.get("pid") == p.pid and x.get("worktree") == sc.trees[busy] for x in left), repr(left))
    S.eq("cleanup: the call left its file in the run", sc.step_files(), ["1-cleanup.json"])
    sc.stop()

    # a run with nothing to clean: looked at zero worktrees, said so
    sz = Scene()
    v = ok_json(S, "cleanup, nothing of the run", sz.call(R, "cleanup", "--run", sz.run))
    S.eq("cleanup, nothing of the run: empty lists", (v.get("removed"), v.get("kept"), v.get("leftover")), ([], [], []))
    sz.stop()


def case_cleanup_scratch(R, S):
    """3.4 U8 fix: the reviewers are not isolated, so their scratch folder (`fwx scratch new`) is in the integration checkout:
    `cleanup` removes the one of its own run, the folder of another run stays, and the checkout stays clean."""
    sc = Scene()
    other_run = "01-alpha-%s-2" % sc.base[:7]
    mine = os.path.join(os.path.realpath(sc.cwd), ".fwx-agent", sc.run, "r1")
    theirs = os.path.join(os.path.realpath(sc.cwd), ".fwx-agent", other_run, "r1")
    for run in (sc.run, other_run):
        r = sc.call(R, "scratch", run, "r1")
        S.eq("cleanup scratch, setup: scratch for %s" % run, r.returncode, 0)
        helpers.write(os.path.join(os.path.realpath(sc.cwd), ".fwx-agent", run, "r1"), "report.json", "{}\n")
    v = ok_json(S, "cleanup, scratch of the run", sc.call(R, "cleanup", "--run", sc.run))
    S.eq("cleanup: the run's scratch folder is removed and listed", (v.get("scratch"), exists(mine)), ([os.path.dirname(mine)], False))
    S.ok("cleanup: another run's scratch folder and the ignore file stay while it is there", exists(os.path.join(theirs, "report.json")) and exists(os.path.join(os.path.dirname(os.path.dirname(mine)), ".gitignore")))
    S.eq("cleanup: the checkout is clean", helpers.git(sc.cwd, "status", "--porcelain"), "")
    v = ok_json(S, "cleanup, a second time", sc.call(R, "cleanup", "--run", sc.run))
    S.eq("cleanup: nothing more to remove", v.get("scratch"), [])
    # the last run's folder goes and takes `.fwx-agent/` with its ignore file: nothing is left in the checkout
    ok_json(S, "cleanup, the other run", sc.call(R, "cleanup", "--run", other_run))
    S.eq("cleanup: with no run's folder left, `.fwx-agent/` and its .gitignore are gone too", exists(os.path.join(os.path.realpath(sc.cwd), ".fwx-agent")), False)
    S.eq("cleanup: and the checkout is still clean", helpers.git(sc.cwd, "status", "--porcelain", "--ignored"), "")
    sc.stop()


def case_cleanup_no_proc(R, S):
    """Without /proc cleanup says NOT RUN, NOT ARMED and exits 77: through the tree's own lib, with PROC pointed nowhere."""
    sc = Scene()
    r = run_no_proc(R, sc)
    S.eq("cleanup, no /proc: exit %s" % r.returncode, r.returncode, 77)
    S.ok("cleanup, no /proc: says NOT RUN, NOT ARMED: no /proc", "NOT RUN, NOT ARMED: no /proc" in r.stderr, r.stderr[:200])
    S.eq("cleanup, no /proc: nothing printed on stdout", r.stdout, "")
    sc.stop()


def run_no_proc(R, sc):
    root = getattr(R, "root", ROOT)
    code = ("import sys; sys.path.insert(0, %r); from fwx.execute import cleanup; cleanup.PROC = '/nonexistent-proc'; "
            "from fwx.commands import wave; sys.exit(wave.main(['cleanup', '--run', %r]))" % (os.path.join(root, "lib"), sc.run))
    return subprocess.run([PY, "-c", code], cwd=sc.cwd, env=helpers.clean_env(**IDENT), capture_output=True, text=True)


# ---------------------------------------------------------------------------------------------------- summary

def summ(R, sc, *extra):
    return sc.call(R, "summary", "--run", sc.run, *extra)


def case_summary(R, S):
    sc = Scene()
    sc.evidence(0, cmds=(("true", 0), ("python3 t.py", 0)))
    v = ok_json(S, "summary, green evidence of HEAD", summ(R, sc, "--part-dir", sc.part))
    S.eq("summary, green evidence of HEAD: gate", v.get("gate"), "pass")
    S.eq("summary: head, the evidence line, the rounds", (v.get("head"), v.get("evidence_line"), v.get("rounds")),
         (sc.head(), "evidence %s true=0 python3 t.py=0" % sc.head(), "0/3"))

    # `fwx wave --run R --json` is what the part report reads (09.5 C4, 09.6): JSON is the only output, so the flag changes nothing
    # Red before: fwx wave --run R --json: exit: got 2, want 0   (stderr: usage: fwx wave --run R [--part-dir D])
    j = summ(R, sc, "--part-dir", sc.part, "--json")
    S.eq("fwx wave --run R --json: exit, and the same JSON as without the flag", (j.returncode, J(j)), (0, J(summ(R, sc, "--part-dir", sc.part))))
    S.eq("fwx wave --run R --json: stderr", j.stderr.strip(), "")

    sr = Scene()
    sr.evidence(0)
    sr.evidence(1)
    r = summ(R, sr, "--part-dir", sr.part)
    S.eq("summary, red evidence: gate: got %r" % (J(r) or {}).get("gate"), (J(r) or {}).get("gate"), "fail")
    S.eq("summary, red evidence: exit", r.returncode, 1)
    S.eq("summary, red evidence: it counts as a round", (J(r) or {}).get("rounds"), "1/3")

    so = Scene()
    so.evidence(0, sha="0" * 40)
    r = summ(R, so, "--part-dir", so.part)
    S.eq("summary, evidence of another sha: gate: got %r" % (J(r) or {}).get("gate"), (J(r) or {}).get("gate"), "fail")

    sn = Scene()
    r = summ(R, sn, "--part-dir", sn.part)
    S.eq("summary, no evidence row: gate and exit", ((J(r) or {}).get("gate"), r.returncode), ("none", 2))

    # the part found from the run's own files, as the session calls it (`summary --run R`)
    sf = Scene()
    b = sf.agent("one", [("src/a.py", "a1\n", None)])
    ok_json(S, "summary, setup: integrate", sf.integrate(R, b, extra=("--final",)))
    r = summ(R, sf)
    S.eq("summary, from the run files: gate: got %r" % (J(r) or {}).get("gate"), ((J(r) or {}).get("gate"), r.returncode), ("pass", 0))
    S.eq("summary: its call is the second file of the run", sf.step_files(), ["1-integrate.json", "2-summary.json"])
    r = summ(R, Scene())
    S.eq("summary, a run with no files and no --part-dir: gate none, exit 2", ((J(r) or {}).get("gate"), r.returncode), ("none", 2))

    # 3.4 U8 fix, F3: the gate of an earlier run that never reached it does not pass because a later run's evidence is green on HEAD
    se = Scene()
    b = se.agent("one", [("src/a.py", "a1\n", None)])
    ok_json(S, "summary, an earlier run: its merge, no gate", se.integrate(R, b))
    se.evidence(0)  # another run's gate, green on this head
    r = summ(R, se)
    v = J(r) or {}
    S.eq("summary, an earlier run that never ran the gate, green evidence of HEAD from elsewhere: gate got %r" % v.get("gate"), (v.get("gate"), r.returncode), ("fail", 1))
    S.ok("summary: it says which run and why", se.run in v.get("why", "") and "gate" in v.get("why", ""), repr(v.get("why")))
    sk = Scene(checks=["exit 1"])
    b = sk.agent("one", [("src/a.py", "a1\n", None)])
    ok_json(S, "summary, a run whose last gate is red", sk.integrate(R, b, extra=("--final",)), code=1)
    sk.evidence(0)  # a later hand fix, green on the head, is not this run's gate
    r = summ(R, sk)
    S.eq("summary, the run's own last gate is red, later green evidence: gate got %r" % (J(r) or {}).get("gate"), ((J(r) or {}).get("gate"), r.returncode), ("fail", 1))
    sw = Scene()
    b = sw.agent("one", [("src/a.py", "a1\n", None)])
    ok_json(S, "summary, the wave merge", sw.integrate(R, b))
    ok_json(S, "summary, then the gate on the head (the re-entry)", sw.call(R, "integrate", "--part-dir", sw.part, "--run", sw.run, "--final"))
    r = summ(R, sw)
    S.eq("summary, control: the same run once its own gate passed: gate got %r" % (J(r) or {}).get("gate"), ((J(r) or {}).get("gate"), (J(r) or {}).get("why")), ("pass", ""))
    sv = Scene()  # a run of `--revert` merges nothing: the gate is `fwx verify` on the head the revert made
    helpers.write(sv.cwd, "src/a.py", "a1\n")
    helpers.git(sv.cwd, "add", "-A")
    helpers.git(sv.cwd, "commit", "-q", "-m", "fix a\n\nFwx-Finding: F1\nFwx-Run: %s-%s-0" % ("01-alpha", sv.base[:7]))
    ok_json(S, "summary, a revert-only run: its revert", sv.call(R, "revert", "--part-dir", sv.part, "--run", sv.run, "--findings", "F1"))
    sv.evidence(0)
    r = summ(R, sv)
    S.eq("summary, a run that only reverted: the evidence of the head decides, gate got %r" % (J(r) or {}).get("gate"), ((J(r) or {}).get("gate"), r.returncode), ("pass", 0))


def plant(sc, step, args, result, code=0):
    """A call recorded in the run's files, as `wave.py` `_record` writes it: the calls of the other commands (`report`, `findings`, `fix-round`)
    that `summary` reads, with the results those commands print (their own tests pin those shapes)."""
    d = os.path.join(sc.common, "fwx", "runs", sc.run)
    os.makedirs(d, exist_ok=True)
    n = 1 + max([int(f.split("-")[0]) for f in os.listdir(d)], default=0)
    with open(os.path.join(d, "%d-%s.json" % (n, step)), "w", encoding="utf-8") as f:
        json.dump({"step": step, "exit": code, "args": args, "result": result}, f)


def case_summary_report(R, S):
    """`fwx wave --run R` carries what the part report reads, from the run's own files: execute.js returned it in `details` (09.5 T54)."""
    def item(where, issue, size="small"):
        return {"where": where, "what": "w " + where, "fix": "f " + where, "size": size, "issue": issue}
    unfiled, filed, large = item("src/x.py:1", None), item("src/y.py:2", "DTC-1"), item("src/z.py:3", None, "large")
    sc = Scene()
    fixes = [{"id": "r1-F1", "file": "src/a.py", "line": 1, "claim": "c1", "evidence": "e1", "severity": "high"}]
    consider = {"id": "r1-F2", "file": "src/b.py", "line": 2, "claim": "c2", "severity": "low"}
    note, dismissed = {"id": "r1-F3", "claim": "c3"}, {"id": "r1-F4", "reason": "not a defect"}
    crit = [{"id": "C1", "met": "yes", "evidence": "e"}, {"id": "C2", "met": "unproven", "evidence": "e"}]
    plant(sc, "report", {"unit": "T1"}, {"next": "merge", "branch": "b1", "outside": [unfiled, filed]})
    plant(sc, "report", {"unit": "T2"}, {"next": "retry", "branch": None, "outside": [item("src/gone.py:9", None)]})
    plant(sc, "report", {"unit": "T3"}, {"next": "stop", "why": "executor did not return: T3", "gap": "executor did not return: T3", "outside": []})
    plant(sc, "findings", {"run": sc.run}, {"next": "relaunch", "reported": 0, "criteria": [], "fix": [], "consider": [], "note": [], "dismissed": [], "file": []})
    plant(sc, "findings", {"run": sc.run}, {"next": "verify", "reported": 5, "criteria": [{"id": "C1", "met": "no", "evidence": "first"}],
                                            "fix": [], "consider": [], "note": [], "dismissed": [], "file": []})
    plant(sc, "findings", {"run": sc.run}, {"next": "fix", "reported": 5, "criteria": crit, "fix": fixes, "consider": [consider], "note": [note],
                                            "dismissed": [dismissed], "file": [large]})
    plant(sc, "findings", {"run": sc.run}, {"next": "stop", "gap": "reviewer did not return", "reported": 0, "criteria": [], "fix": [], "consider": [],
                                            "note": [], "dismissed": [], "file": []})
    plant(sc, "fix-round", {"why": "gate red"}, {"ok": True, "spent": True, "rounds": "1/3", "why": "gate red"})
    plant(sc, "fix-round", {"why": "again"}, {"ok": False, "spent": False, "rounds": "3/3", "why": "again"}, 1)
    plant(sc, "integrate", {"findings": ["r2-F1"], "final": False}, {"ok": False, "merged": []}, 1)
    b = sc.agent("one", [("src/a.py", "a1\n", ["r1-F1"])])
    tip = helpers.git(sc.repo, "rev-parse", "refs/heads/" + b).strip()
    ok_json(S, "summary report, the merge of the fix", sc.integrate(R, b, extra=("--findings", "r1-F1", "--final")))
    r = summ(R, sc)
    v = J(r) or {}
    S.eq("summary report: gate and exit are unchanged", (v.get("gate"), r.returncode), ("pass", 0))
    want = {"findings": {"reported": 5, "fix": 1, "consider": [consider], "note": [note], "dismissed": [dismissed],
                         "fixed": [{"id": "r1-F1", "commit": tip, "severity": "high"}], "outside": [large]},
            "criteria": crit, "outside": [unfiled], "tried": ["1/3: gate red"], "gaps": ["executor did not return: T3", "reviewer did not return"],
            "protected": []}
    for k, w in want.items():
        S.ok("fwx wave --run R has %s -> %s" % (k, "present" if k in v else "missing"), k in v)
        S.eq("fwx wave --run R: %s" % k, v.get(k), w)
    # a finding whose merge was refused is not fixed, and a run with no calls of those commands has the groups empty
    S.eq("summary report, a run of no reports and no review: the groups are empty",
         [(J(summ(R, Scene(), "--part-dir", Scene().part)) or {}).get(k) for k in ("outside", "tried", "gaps", "criteria", "protected")], [[], [], [], [], []])
    sp = Scene(protected=["src/a.py"])
    b = sp.agent("one", [("src/a.py", "a1\n", None)])
    ok_json(S, "summary report, a final merge that touches a protected path", sp.integrate(R, b, extra=("--final",)))
    S.eq("summary report: protected is the last final merge's", (J(summ(R, sp)) or {}).get("protected"), ["src/a.py"])
    S.eq("summary report, a run with a merge and no review: fixed is empty",
         ((J(summ(R, sp)) or {}).get("findings") or {}).get("fixed"), [])
    sc.stop()
    sp.stop()


def case_step_files(R, S):
    sc = Scene()
    b = sc.agent("one", [("src/a.py", "a1\n", ["F1"])])
    r1 = sc.integrate(R, b, extra=("--findings", "F1"))
    r2 = fix(R, sc)
    r3 = sc.call(R, "revert", "--part-dir", sc.part, "--run", sc.run, "--findings", "F1")
    S.eq("step files: the three calls ran", (r1.returncode, r2.returncode, r3.returncode), (0, 0, 0))
    S.eq("step files: one per call, numbered", sc.step_files(), ["1-integrate.json", "2-fix-round.json", "3-revert.json"])
    d = os.path.join(sc.common, "fwx", "runs", sc.run)
    try:
        rec = json.load(open(os.path.join(d, "2-fix-round.json")))
    except (OSError, ValueError):
        rec = {}
    S.eq("step file: step, exit and the printed result", (rec.get("step"), rec.get("exit"), rec.get("result")), ("fix-round", 0, J(r2)))
    S.ok("step file: keeps the part, for `summary`", rec.get("args", {}).get("part_dir") == sc.part, repr(rec.get("args")))
    for bad in (("fix-round", "--part-dir", sc.part), ("integrate", "--run", "../x", "--part-dir", sc.part, "--branches", b), ("cleanup",), ("summary",), ("revert",)):
        r = sc.call(R, *bad)
        S.eq("usage error %s: exit 2, nothing printed on stdout" % (bad[0],), (r.returncode, r.stdout), (2, ""))
    S.eq("usage errors write no step file", sc.step_files(), ["1-integrate.json", "2-fix-round.json", "3-revert.json"])
    sc.stop()


# ---------------------------------------------------------------------------------------------------- next

def runs_file(sc, path):
    """The text of a file the result names, which must be inside the run's briefs folder of the git common dir (never under the worktree)."""
    want = os.path.join(os.path.realpath(sc.common), "fwx", "runs", sc.run, "briefs")
    ok = isinstance(path, str) and os.path.isabs(path) and os.path.realpath(path).startswith(want + os.sep) and os.path.isfile(path)
    return open(path, encoding="utf-8").read() if ok else ""


def has(S, label, text, *needles):
    for n in needles:
        S.ok("%s: the brief has %r" % (label, n), n in text, "brief: %s" % text[:300].replace("\n", " | "))


def case_next(R, S):
    """C2: each result of `wave merge` says what follows (`next`, `why`) and, for resolve and fix, writes the brief and gives its path.
    Seen red at d348f8d (python3 tests/test_wave_integrate.py):
      FAIL: a green wave says next wave -> no next: got None, want 'wave'
      FAIL: a conflict says next resolve -> no next: got None, want 'resolve'
      FAIL: quick red says next fix -> no next: got None, want 'fix'"""
    sc = Scene()
    b1 = sc.agent("one", [("src/a.py", "a1\n", None)])
    v = ok_json(S, "next, a green wave", sc.integrate(R, b1))
    S.eq("a green wave says next wave -> %s" % (v.get("next") or "no next"), v.get("next"), "wave")
    S.ok("a green wave: why is a sentence and no brief is written", bool(v.get("why")) and not v.get("brief"), repr((v.get("why"), v.get("brief"))))
    S.eq("a green wave writes no brief file", sc.step_files(), ["1-integrate.json"])
    sc.stop()

    sc = Scene()
    b1 = sc.agent("one", [("src/a.py", "mine\n", None)])
    b2 = sc.agent("two", [("src/a.py", "yours\n", None)])
    v = ok_json(S, "next, a conflict", sc.integrate(R, b1, b2), code=1)
    S.eq("a conflict says next resolve -> %s" % (v.get("next") or "no next"), v.get("next"), "resolve")
    S.ok("a conflict: why names the branch and the file", b2 in (v.get("why") or "") and "src/a.py" in (v.get("why") or ""), repr(v.get("why")))
    text = runs_file(sc, v.get("brief"))
    S.ok("a conflict: the brief is a file in the run's briefs folder", bool(text), repr(v.get("brief")))
    S.eq("the resolver's brief is the first of its kind", os.path.basename(v.get("brief") or ""), "_resolve-1.md")
    S.ok("a conflict: the head it names is the new one, after the merge of the first branch", v.get("head") == sc.head() != sc.base,
         repr((v.get("head"), sc.head(), sc.base)))
    has(S, "resolver", text, "fwx base %s" % sc.head(), "git merge --no-commit %s" % b2, "src/a.py", "Fwx-Run: %s" % sc.run, "Fwx-Task: 01-alpha/two",
        "no rebase", "no push", "nothing written in `.fwx/`", "fwx linear new --template general", "fix nothing outside it",
        "fwx scratch new %s resolve-1" % sc.run, "git merge --abort", "`question`")
    S.ok("the resolver's brief names the plan and the file of the quick checks", os.path.join(sc.part, "plan.md") in text
         and os.path.join(sc.repo, ".claude", "fwx.json") in text, text[:200])
    S.ok("a conflict: no Fwx-Finding trailer in the resolver's brief", "Fwx-Finding" not in text)
    S.ok("a conflict: the tree is clean, no merge is open", sc.clean())
    v2 = ok_json(S, "next, the same conflict again", sc.integrate(R, b2), code=1)
    S.eq("a second resolver's brief is a new file, the first stays", (os.path.basename(v2.get("brief") or ""), bool(runs_file(sc, v.get("brief")))),
         ("_resolve-2.md", True))
    has(S, "second resolver", runs_file(sc, v2.get("brief")), "fwx scratch new %s resolve-2" % sc.run)
    sc.stop()

    sq = Scene(quick=["exit 3"])
    b = sq.agent("one", [("src/a.py", "a1\n", None)])
    v = ok_json(S, "next, quick red", sq.integrate(R, b), code=1)
    S.eq("quick red says next fix -> %s" % (v.get("next") or "no next"), v.get("next"), "fix")
    S.ok("quick red: why says the exit, the head and the command", "exit 3" in (v.get("why") or "") and sq.head() in (v.get("why") or ""), repr(v.get("why")))
    text = runs_file(sq, v.get("brief"))
    S.eq("the fixer's brief is the first of its kind", os.path.basename(v.get("brief") or ""), "_fix-1.md")
    has(S, "fixer", text, "fwx base %s" % sq.head(), "src/a.py", "src/b.py", "Fwx-Run: %s" % sq.run, "no rebase", "nothing written in `.fwx/`",
        "fwx linear new --template general", "fwx scratch new %s fix-1" % sq.run, "exit 3", "A defect you see outside this work is yours")
    S.ok("quick red: no Fwx-Finding trailer without findings", "Fwx-Finding: <id>" not in text)
    sq.stop()

    sf = Scene()
    b = sf.agent("fix", [("src/a.py", "a1\n", ["F1", "F2"])])
    v = ok_json(S, "next, one commit for two findings", sf.integrate(R, b, extra=("--findings", "F1,F2")), code=2)
    S.eq("findings not one per commit says next fix -> %s" % (v.get("next") or "no next"), v.get("next"), "fix")
    text = runs_file(sf, v.get("brief"))
    has(S, "findings fixer", text, "Fwx-Finding: <id>", "F1", "F2", "one commit per finding", b, "fwx base %s" % sf.head())
    sf.stop()

    sl = Scene()
    b_live = sl.agent("live", [("src/a.py", "a1\n", None)])
    sl.lock(b_live, *sl.live())
    v = ok_json(S, "next, a live lock", sl.integrate(R, b_live), code=2)
    S.eq("a live lock says next owner -> %s" % (v.get("next") or "no next"), v.get("next"), "owner")
    S.ok("a live lock: why names the branch, no brief", b_live in (v.get("why") or "") and not v.get("brief"), repr(v))
    sl.stop()

    sg = Scene(checks=["exit 1"])
    b = sg.agent("one", [("src/a.py", "a1\n", None)])
    v = ok_json(S, "next, a red gate", sg.integrate(R, b, extra=("--final",)), code=1)
    S.eq("a red gate says next fix -> %s" % (v.get("next") or "no next"), v.get("next"), "fix")
    has(S, "gate fixer", runs_file(sg, v.get("brief")), "the gate failed on %s" % sg.head())
    sg.stop()

    sw = Scene()
    b = sw.agent("one", [(".github/workflows/ci.yml", "name: x\n", None)])
    v = ok_json(S, "next, trusted edits", sw.integrate(R, b, extra=("--final",)))
    S.eq("trusted edits say next owner -> %s" % (v.get("next") or "no next"), v.get("next"), "owner")
    S.ok("trusted edits: why names the file, no brief", ".github/workflows/ci.yml" in (v.get("why") or "") and not v.get("brief"), repr(v))
    sw.stop()

    sp = Scene()
    b = sp.agent("one", [("src/a.py", "a1\n", None)])
    v = ok_json(S, "next, a green final merge", sp.integrate(R, b, extra=("--final",)))
    S.eq("a green final merge says next review -> %s" % (v.get("next") or "no next"), v.get("next"), "review")
    sp.stop()

    sn = Scene()
    b1 = sn.agent("one", [("src/a.py", "mine\n", None)])
    b2 = sn.agent("two", [("src/a.py", "yours\n", None)])
    os.remove(os.path.join(sn.part, "plan.md"))
    v = ok_json(S, "next, a conflict and no plan to scope the resolver from", sn.integrate(R, b1, b2), code=1)
    S.eq("no plan: the owner is asked and no brief is written -> %s" % (v.get("next") or "no next"), (v.get("next"), v.get("brief")), ("owner", None))
    S.ok("no plan: why says which file is missing", "plan.md" in (v.get("why") or ""), repr(v.get("why")))
    sn.stop()


def case_next_rules(R, S):
    """The rules of `next` on results that are hard to make in a toy repo: a setup that failed after the merges, a verify that could not
    run (which is not a red gate), and the order when several things are wrong at once."""
    base = {"ok": False, "head": "h", "merged": [], "conflict": None, "locked": [], "findings_check": {"ok": True, "problems": []},
            "quick": {"ran": False, "cmds": [], "rc": 0}, "verify": {"ran": False, "rc": None, "line": ""}, "trusted": [], "protected": []}
    code = ("import json, sys\nfrom fwx.execute import integrate\n"
            "base = %r\n"
            "print(json.dumps([integrate.next_step(dict(base, **over), final) for over, final in json.loads(sys.argv[1])]))\n" % base)
    cases = [
        ("a setup that failed", {"setup": "worktree setup failed: npm ci exited 1"}, False, "owner", "npm ci exited 1"),
        ("a verify that could not run", {"verify": {"ran": True, "rc": 2, "line": ""}}, True, "owner", "verify could not run (exit 2)"),
        ("a red gate", {"verify": {"ran": True, "rc": 1, "line": "evidence h x=1"}}, True, "fix", "the gate failed on h: evidence h x=1"),
        ("red quick checks", {"quick": {"ran": True, "cmds": ["a", "b"], "rc": 4}}, False, "fix", "checks_quick failed with exit 4 on h: a ; b"),
        ("a quick check that timed out", {"quick": {"ran": True, "cmds": ["a"], "rc": 1, "timed_out": ["a"], "limit": 9}}, False, "fix", "stopped after 9 s"),
        ("a result that says nothing", {}, False, "owner", "says why in no field"),
        ("a green merge", {"ok": True}, False, "wave", "merged"),
        ("a green final", {"ok": True}, True, "review", "review"),
        ("a green final with trusted edits", {"ok": True, "trusted": ["x.yml"]}, True, "owner", "x.yml"),
        ("a lock and a conflict", {"locked": [{"branch": "b"}], "conflict": {"branch": "c", "files": ["f"]}}, False, "owner", "a live agent holds b"),
        ("a setup that failed after a conflict", {"setup": "worktree setup failed: x", "conflict": {"branch": "c", "files": ["f"]}}, False, "owner", "worktree setup failed: x"),
        ("a conflict", {"conflict": {"branch": "c", "files": ["f", "g"]}}, False, "resolve", "the branch c conflicts in f, g"),
    ]
    r = subprocess.run([sys.executable, "-c", code, json.dumps([[c[1], c[2]] for c in cases])],
                       env=helpers.clean_env(PYTHONPATH=os.path.join(R.root, "lib")), capture_output=True, text=True)
    try:
        got = json.loads(r.stdout)
    except ValueError:
        got = []
    S.eq("next_step: one answer per case (%s)" % r.stderr.strip()[-160:], len(got), len(cases))
    for (label, _over, _final, want, needle), (nxt, why) in zip(cases, got):
        S.eq("%s says next %s -> %s" % (label, want, nxt or "no next"), nxt, want)
        S.ok("%s: why has %r" % (label, needle), needle in why, repr(why))


CASES = [case_integrate_clean, case_integrate_conflict, case_integrate_quick, case_integrate_dirty, case_integrate_lock,
         case_integrate_findings, case_integrate_final, case_integrate_gate_only, case_fix_round, case_cleanup, case_cleanup_scratch, case_cleanup_no_proc, case_summary,
         case_summary_report, case_step_files, case_next, case_next_rules]

I = "lib/fwx/execute/integrate.py"
C = "lib/fwx/execute/cleanup.py"
W = "lib/fwx/commands/wave.py"
LIVE = 'return "live" if alive(pid, start) else "stale"'
MUTANTS = [
    ("integrate spends a round on a conflict", case_integrate_conflict, I, 'result["conflict"] = {"branch": b, "files": files}',
     'result["conflict"] = {"branch": b, "files": files}; rounds.record(part_dir, "use", "conflict")', "rounds 1/3 after integrate"),
    ("liveness reads only `locked`", case_integrate_lock, C, LIVE, 'return "live"', "refused a stale lock"),
    ("liveness never sees a live agent", case_integrate_lock, C, LIVE, 'return "stale"', "merged a locked worktree"),
    ("a commit may carry two findings", case_integrate_findings, I, "if len(ids) > 1:", "if False:", "one commit for two findings: refused"),
    ("integrate --final needs a branch", case_integrate_gate_only, W, '(() if parsed and "--final" in parsed[0] else ("--branches",))', '("--branches",)',
     "integrate --final with no branch: exit"),
    ("fix-round never spends", case_fix_round, I, 'rounds.record(part_dir, "use", why)', "pass", "a conflict with nothing counted: rounds 0/3"),
    ("fix-round spends on a counted failure", case_fix_round, I, "if not counted:", "if True:", "red evidence of HEAD: rounds 2/3"),
    ("fix-round decides by the counter after", case_fix_round, I, "before = rounds.count(rows[:-1]) if counted else rounds.count(rows)",
     "before = rounds.count(rows)", "fix-round exit 1 with 2 of 3 rounds used before this failure"),
    ("fix-round spends before looking", case_fix_round, I, "if before >= cap:", 'rounds.record(part_dir, "use", why)\n    if before >= cap:', "rounds 4/3"),
    ("fix-round writes a stage row", case_fix_round, I, "spent = True", 'spent = True\n        state.append_audit(part_dir, "stage", detail="executing", sha=head)',
     "stage rows written: 1"),
    ("cleanup deletes by prefix", case_cleanup, C, "return bool(owned) or branch in recorded", 'return branch.startswith("worktree-")',
     "removed a worktree of another run"),
    ("cleanup keeps a stale-locked worktree", case_cleanup, C, LIVE, 'return "live"', "kept a stale-locked worktree"),
    ("cleanup without /proc runs on", case_cleanup_no_proc, C, "if not os.path.isdir(PROC):", "if False:", "cleanup, no /proc: exit"),
    ("cleanup keeps the run's scratch", case_cleanup_scratch, C, "    scratch = _scratch(top, run)", "    scratch = []", "the run's scratch folder is removed and listed"),
    ("cleanup leaves the ignore file", case_cleanup_scratch, C, "            os.rmdir(root)", "            pass", "`.fwx-agent/` and its .gitignore are gone too"),
    ("summary ignores the exit of the evidence", case_summary, I, 'gate = "pass" if rc == "0" and sha == head and not why else "fail"', 'gate = "pass" if sha == head and not why else "fail"',
     "red evidence: gate"),
    ("summary ignores the sha of the evidence", case_summary, I, 'gate = "pass" if rc == "0" and sha == head and not why else "fail"', 'gate = "pass" if rc == "0" and not why else "fail"',
     "evidence of another sha: gate"),
    ("summary takes any run's gate", case_summary, I, "why = _own_gate(run, steps) if run else None", "why = None", "an earlier run that never ran the gate"),
    ("summary ignores a red gate of the run", case_summary, I, 'if last.get("exit") != 0 or', "if False and", "the run's own last gate is red"),
    ("summary never finds the part", case_summary, W, 'if rec.get("args", {}).get("part_dir"):', "if False:", "from the run files: gate"),
    ("the report keeps a retry's outside items", case_summary_report, I, 'if step == "report" and res.get("next") == "merge":', 'if step == "report":',
     "fwx wave --run R: outside"),
    ("the report counts a pass at its verify call too", case_summary_report, I, 'if res.get("next") in ("fix", "owner", "done"):', "if True:",
     "fwx wave --run R: findings"),
    ("the report counts a round that was refused", case_summary_report, I, 'elif step == "fix-round" and res.get("ok") is True:', 'elif step == "fix-round":',
     "fwx wave --run R: tried"),
    ("the report takes a refused merge's findings as fixed", case_summary_report, I, 'if args.get("findings") and res.get("ok") is True:', 'if args.get("findings"):',
     "fwx wave --run R: findings"),
    ("the report names no commit of a fixed finding", case_summary_report, I, "commit.setdefault(i, sha)", "commit.setdefault(i, None)", "fwx wave --run R: findings"),
    ("the report takes a gap of no call", case_summary_report, I, 'gaps.append(res["gap"])', "pass", "fwx wave --run R: gaps"),
    ("step files all numbered 0", case_step_files, W, "n = 1 + max(", "n = 0 * max(", "step files: one per call, numbered"),
    ("a conflict goes to a fixer", case_next, I, 'return "resolve", "the branch', 'return "fix", "the branch', "a conflict says next resolve"),
    ("a verify that could not run is fixed", case_next_rules, I, 'if v["rc"] != 1:', "if False:", "a verify that could not run says next owner"),
    ("trusted edits go to the review", case_next, I, 'if result["trusted"]:', "if False:", "trusted edits say next owner"),
    ("the last wave is never the final one", case_next, I, "if not final:", "if True:", "a green final merge says next review"),
    ("a live lock is not named", case_next, I, 'if result["locked"]:\n        return "owner"', 'if False:\n        return "owner"',
     "a live lock: why names the branch"),
    ("the resolver starts from another base", case_next, I, 'facts = brief.resolver_facts(c, result["head"],', 'facts = brief.resolver_facts(c, "0" * 40,',
     "resolver: the brief has 'fwx base"),
    ("the resolver's task trailer is not read", case_next, I, '_trailer_of(top, c["branch"], _branch(top))', "None", "resolver: the brief has 'Fwx-Task: 01-alpha/two'"),
    ("a brief that cannot be written stops the merge", case_next, I, "except (WaveError, config.ConfigError, state.StateError, OSError) as e:\n            result[\"next\"]",
     "except config.ConfigError as e:\n            result[\"next\"]", "no plan to scope the resolver from: exit"),
    ("a second brief overwrites no file but is no new unit", case_next, I, 'unit, path = brief.next_unit(folder, kind)', 'unit, path = kind + "-1", os.path.join(folder, "briefs", "_%s-1.md" % kind)',
     "a second resolver's brief is a new file"),
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
