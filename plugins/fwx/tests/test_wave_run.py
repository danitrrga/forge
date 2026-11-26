#!/usr/bin/env python3
"""`fwx wave run` and `fwx wave list` (09.6 T66): lib/fwx/commands/wave.py, execute/run.py, execute/orca.py, execute/cleanup.py.

The command runs against a fake `orca` (tests/fake_orca.py) on a PATH of its own, which records every call with the Orca variables it
carried, refuses `worker-release` of a dispatch that is not settled (`dispatch_inactive`, as Orca does) and the creation flags beside
`--worktree path:`, and plays each worker at `worker-start`: it commits in the worktree and writes its report as an executor does. The
toy repos are test_wave_prepare.py's. Nothing here reads the real HOME, the real Orca or a real project.

Seen red before the code existed (python3 tests/test_wave_run.py, first lines; `fwx wave run` was not a verb):
  FAIL: loop: exit: got 2, want 0 (stderr 'fwx wave: unknown verb: run' ...)
  FAIL: loop: stdout is the result line: got '', want 'run <id> done: ...'

Orchestrator steering (`--orchestrator`; case_steer*, case_fake_orca; Orca 1.4.273 live probe), seen red on the code before it, each case's docstring has its lines:
  FAIL: a question reaches the orchestrator once -> 0 sends over many ticks: got 0, want 1
  FAIL: lines: the run is done -> usage: fwx wave run --part-dir D ...
  FAIL: unreachable: needs-owner naming the address, exit 3 -> exit 2, got ''
  FAIL: refusals: --plane factory: stderr names the orchestrator: stderr 'usage: fwx wave run ...'

Controls, each a copy of lib/ with one line changed (MUTANTS), seen red on the case named:
  the cap read as unlimited:                  FAIL: never more open workers than the cap -> 2 open, cap 1
  cleanup without the run's worktrees:        FAIL: a reviewer worktree with no commit is removed -> kept
  release with no stop before it:             FAIL: every dispatch is released -> dispatch_inactive
  a forced removal:                           FAIL: an executor worktree with unmerged commits stays -> removed
  the settings copied as they are:            FAIL: the worker's settings write the cache at 5 minutes -> env has no FORCE_PROMPT_CACHING_5M
  a start with no base context:               FAIL: no base context, no worker -> 1 start
  worker-start without waiting for the worktree: FAIL: discover: worker-start waited for Orca to know the worktree -> 0 show calls
  a selector_not_found is not retried:        FAIL: discover: the run is done -> run <id> failed: orca: orca orchestration worker-start failed (exit 1): selector_not_found
  the peek also takes worker_done:            FAIL: routine worker_done never reaches the orchestrator -> ['[01-alpha T1 dispatch:ctx_1] done T1', ...]
  a forwarded message is not recorded:        FAIL: a question reaches the orchestrator once -> 24 sends over many ticks: got 24, want 1
  an open question does not stop the idle clock / pause the limit: FAIL: an open question pauses the idle stop and the limit: the run still waits after 3.2 s -> exit 1
  the status is sent as an escalation:        FAIL: a question reaches the orchestrator once -> 0 sends over many ticks: got 0, want 1 (the fake refuses it: sender_not_assignee)
  the ask line with no orchestrator:          FAIL: off: no executor is told to ask -> 4 starts
  settled succeeded worker does not wait:     FAIL: reply grace: delayed reply after worker_done finishes done: exit 1, got 'run <id> failed: executor did not return: T1 (2 worktrees kept)\n'
  a progress line is not flushed:             FAIL: progress: a line is out while the first worker still works
  ORCA_TERMINAL_HANDLE is ignored:            FAIL: own terminal (success): no terminal was created -> got ['term_8']
  the run closes the terminal it ran in:      FAIL: own terminal (success): no terminal was closed
  no look at the sender before a worker-start: FAIL: fenced: the run stops needs-owner naming its closed terminal
  a resume keeps the Orca run of a lost terminal: FAIL: fenced: the resume goes on to done

Visible runs (case_progress, case_own_terminal, case_fenced), seen red on the code before them (the first lines):
  FAIL: progress: the lines come in order -> first missing: got 'base check passed', want None
  FAIL: progress: a line is out while the first worker still works -> got []
  FAIL: own terminal (success): no terminal was created -> got ['term_8']: got ['term_8'], want []
  FAIL: own terminal (success): run-create names the terminal of the environment: got ['term_8'], want ['term_ext']
  FAIL: fenced: the run stops needs-owner naming its closed terminal: got '... run <id> failed: orca: orca orchestration worker-start failed (exit 1): consumer_fenced: ...'
  FAIL: fenced: exit 3 -> exit 1: got 1, want 3
"""
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
from test_wave_prepare import CRIT, Scene, front, task  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
from fwx import context_base  # noqa: E402
from fwx.execute import orca as orca_mod  # noqa: E402

s = helpers.Suite()
FAKE = os.path.join(ROOT, "tests", "fake_orca.py")
LIMIT = 2.5
LINE = re.compile(r"run (\S+) (done|failed|needs-owner): (.*)\Z")
BAD = "python3 -c \"import os,sys; sys.exit(1 if os.path.exists('BAD') else 0)\""
THREE = [task("T1", 1, ["src/a.py"]), task("T2", 1, ["src/b.py"]), task("T3", 2, ["src/c.py"])]
FILES = {"T1": {"src/a.py": "a1\n"}, "T2": {"src/b.py": "b1\n"}, "T3": {"src/c.py": "c1\n"}}


class World:
    """A Scene (toy repo, phase worktree, the part's plan) with a fake orca on a PATH of its own and the base context in place."""

    def __init__(self, tasks=None, recipe=("true",), cap=1, behave=None, context=True, registered=(), nested=None, quick=()):
        self.scene = Scene(tasks=tasks or THREE, recipe=recipe, settings={"worktree": {"baseRef": "head"}, "env": {"KEEP_ME": "1"}}, nested=nested,
                           config=dict({"limits": {"per_project": {"executor": cap}, "default_cap": {"supervised": 3, "unattended": 4}}},
                                       **({"project": {"checks": list(recipe), "checks_quick": list(quick)}} if quick else {})))
        sc = self.scene
        self.repo, self.cwd, self.part = sc.code, sc.cwd, sc.part  # the repository the part works in: the workspace's own, or a nested one
        self.dir = helpers.mkdtemp("fwx-orca-")
        self.bin = os.path.join(self.dir, "bin")
        helpers.write(self.bin, "orca", "#!/bin/sh\nexec %s %s \"$@\"\n" % (sys.executable, FAKE), 0o755)
        self.behave = dict({"files": FILES, "criteria": [c["id"] for c in CRIT], "registered": list(registered)}, **(behave or {}))
        self.set_behave()
        if context:
            path = context_base.base_path(self.part)
            helpers.write(os.path.dirname(path), os.path.basename(path), "# map\nBASE-MAP-TEXT\n## Decided\nBASE-DECIDED-TEXT\n")
        self.common = os.path.join(sc.repo, ".git")  # fwx's folder is the workspace's, whichever repo the part works in
        self.procs = []

    def set_behave(self):
        helpers.write(self.dir, "behave.json", json.dumps(self.behave))

    def env(self, **extra):
        e = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "FAKE_ORCA_DIR": self.dir, "CLAUDE_CONFIG_DIR": self.scene.conf,
             "FWX_RUN_POLL_S": "0.05", "FWX_RUN_IDLE_S": "0.4", "FWX_RUN_LIMIT_S": str(LIMIT),
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
             "ORCA_AGENT_SESSION_ID": "leak", "ORCA_AGENT_SESSION_SPAWN_TOKEN": "leak", "ORCA_STRUCTURED_SESSION": "leak"}
        e.update(extra)
        env = helpers.clean_env(**e)
        if "ORCA_TERMINAL_HANDLE" not in extra:  # a suite run inside a real Orca terminal inherits its handle: only a case that sets it may have it
            env.pop("ORCA_TERMINAL_HANDLE", None)
        return env

    def argv(self, root, *flags, part=None):
        return [sys.executable, os.path.join(root, "bin", "fwx"), "wave", "run", "--part-dir", part or self.part, "--plane", "session", "--branch", "phase"] + list(flags)

    def run(self, *flags, root=ROOT, cwd=None, part=None, **env):
        return subprocess.run(self.argv(root, *flags, part=part), cwd=cwd or self.cwd, env=self.env(**env), capture_output=True, text=True, timeout=120)

    def second_part(self, repo, phase="02-beta", tasks=None):
        """Another part of the workspace, working in nested repo `repo`: its phase worktree on branch `phase` (the first part's branch name), its
        plan naming the repo, its post-mortem and its base context. (the worktree, the part's folder)"""
        sc = self.scene
        cwd = sc.worktree(repo)
        part = os.path.join(sc.repo, ".fwx", "milestones", "v1", "phases", phase)
        plan = {"size": {"tag": "normal", "parts": 1, "agents": 2}, "criteria": CRIT, "tasks": tasks or [task("T1", 1, ["src/a.py"])],
                "not_built": [], "later": [], "repo": repo}
        helpers.write(part, "plan.md", front(plan))
        helpers.write(part, "postmortem.md", front({"verdict": "ok", "security_review": False, "round": 1}))
        helpers.write(part, "context.md", "# context\n")
        helpers.write(part, "decisions.tsv", "date\tid\tdecision\twhy\trejected\tsupport\tsource\tsupersedes\n")
        path = context_base.base_path(part)
        helpers.write(os.path.dirname(path), os.path.basename(path), "# map\nBASE-MAP-TEXT\n## Decided\nBASE-DECIDED-TEXT\n")
        return cwd, part

    def fwx(self, *args):
        return helpers.fwx(self.cwd, *args, env={"CLAUDE_CONFIG_DIR": self.scene.conf})

    def calls(self):
        try:
            with open(os.path.join(self.dir, "calls.jsonl"), encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except OSError:
            return []

    def starts(self):
        return [c["start"] for c in self.calls() if "start" in c]

    def dispatches(self):
        try:
            with open(os.path.join(self.dir, "state.json"), encoding="utf-8") as f:
                return json.load(f)["dispatches"]
        except (OSError, ValueError):
            return {}

    def runs(self):
        folder = os.path.join(self.common, "fwx", "runs")
        return sorted(d for d in os.listdir(folder) if os.path.exists(os.path.join(folder, d, "state.json"))) if os.path.isdir(folder) else []

    def state(self, run):
        with open(os.path.join(self.common, "fwx", "runs", run, "state.json"), encoding="utf-8") as f:
            return json.load(f)

    def steps(self, run, step):
        folder = os.path.join(self.common, "fwx", "runs", run)
        found = []
        for name in sorted(os.listdir(folder), key=lambda n: int(n.split("-")[0]) if n.split("-")[0].isdigit() else 0):
            if re.match(r"\d+-%s\.json\Z" % step, name):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    found.append(json.load(f))
        return found

    def worktrees(self):
        out = helpers.git(self.repo, "worktree", "list", "--porcelain")
        return [line.split(" ", 1)[1] for line in out.splitlines() if line.startswith("worktree ")]

    def state_json(self):
        try:
            with open(os.path.join(self.dir, "state.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def terminals(self):
        try:
            with open(os.path.join(self.dir, "state.json"), encoding="utf-8") as f:
                return json.load(f).get("terminals", {})
        except (OSError, ValueError):
            return {}

    def put_done(self, tasks=("T1", "T2", "T3"), findings=()):
        """Tasks already on the phase branch, committed as an executor's merge leaves them (`Fwx-Task` and `Fwx-Run`)."""
        base = helpers.git(self.cwd, "rev-parse", "HEAD").strip()
        run = "01-alpha-%s-1" % base[:7]
        for t in tasks:
            for rel, text in FILES[t].items():
                helpers.write(self.cwd, rel, text)
            helpers.git(self.cwd, "add", "-A")
            helpers.git(self.cwd, "commit", "-q", "-m", "work %s\n\nFwx-Task: 01-alpha/%s\nFwx-Run: %s" % (t, t, run))
        for f in findings:
            helpers.write(self.cwd, "src/f-%s.txt" % f, "x\n")
            helpers.git(self.cwd, "add", "-A")
            helpers.git(self.cwd, "commit", "-q", "-m", "fix %s\n\nFwx-Finding: %s\nFwx-Run: %s" % (f, f, run))

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()


WORLDS = []


def world(**kw):
    w = World(**kw)
    WORLDS.append(w)
    return w


def line_of(r):
    m = LINE.match(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
    return m


def units(w):
    return [x["unit"] for x in w.starts()]


# ---------------------------------------------------------------------------------------------------------------------- the loop

def case_loop(root, S):
    w = world(behave={"units": {"T1": ["bad-outside", "ok"], "T2": "idle"}})
    r = w.run(root=root)
    S.eq("loop: exit, stderr", (r.returncode, r.stderr.strip()[-300:] if r.returncode else ""), (0, ""))
    m = line_of(r)
    S.ok("loop: stdout ends with the result line `run <id> done: ...`", bool(m) and m.group(2) == "done", "got %r" % r.stdout[-200:])
    if not m:
        return
    run = m.group(1)
    starts = w.starts()
    S.eq("loop: starts in order (T1 relaunched once, wave 2 after wave 1, then the reviewer)", units(w), ["T1", "T1", "T2", "T3", "r1"])
    most = max([x["open_before"] for x in starts] or [0]) + 1
    S.ok("never more open workers than the cap -> %d open, cap 1" % most, most <= 1)
    t3 = next((x for x in starts if x["unit"] == "T3"), None)
    wave1 = helpers.git(w.cwd, "log", "--format=%H", "--grep", "work T2").split()
    S.ok("loop: wave 2 starts at the head wave 1 merged into", bool(t3 and wave1) and subprocess.run(
        ["git", "-C", w.repo, "merge-base", "--is-ancestor", wave1[0], t3["head"]]).returncode == 0)
    relaunch = [x for x in starts if x["unit"] == "T1"]
    S.ok("loop: the rejected report's relaunch carries the rejection note", len(relaunch) == 2 and "was rejected" in relaunch[1]["spec"]
         and "outside item 1" in relaunch[1]["spec"] and "was rejected" not in relaunch[0]["spec"])
    for x in starts:
        who = "loop: %s" % x["unit"]
        env = (x["settings"] or {}).get("env", {})
        S.ok("the worker's settings write the cache at 5 minutes -> env has no FORCE_PROMPT_CACHING_5M", env.get("FORCE_PROMPT_CACHING_5M") == "1", "env %r" % env)
        S.eq(who + ": the settings copy keeps the original's keys", (env.get("KEEP_ME"), (x["settings"] or {}).get("worktree")), ("1", {"baseRef": "head"}))
        S.eq(who + ": git status in the worktree is clean after the settings copy", x["status"], "")
        S.eq(who + ": the marker names role, run and unit", ((x["marker"] or {}).get("run"), (x["marker"] or {}).get("unit")), (run, x["unit"]))
        S.eq(who + ": agent claude and a model", (x["agent"], bool(x["model"])), ("claude", True))
        spec = x["spec"] or ""
        S.ok(who + ": the spec holds the base context, the brief line and the worker_done line",
             "BASE-MAP-TEXT" in spec and "Your brief is" in spec and "worker_done" in spec and "# " in spec, "spec %r" % spec[:200])
    S.eq("loop: roles", [(x["unit"], x["marker"]["role"]) for x in starts if x["unit"] in ("T1", "r1")], [("T1", "executor"), ("T1", "executor"), ("r1", "reviewer")])
    S.ok("loop: the executor's spec has the executor's decided section, the reviewer's has not",
         "BASE-DECIDED-TEXT" in starts[0]["spec"] and "BASE-DECIDED-TEXT" not in starts[-1]["spec"])
    calls = w.calls()
    S.ok("loop: no call carries an Orca session variable", all(not any(c["env"].values()) for c in calls), "got %r" % [c["env"] for c in calls if any(c["env"].values())][:1])
    S.eq("loop: one `orca repo add`", len([c for c in calls if c["argv"][:2] == ["repo", "add"]]), 1)
    S.ok("loop: no creation flag beside --worktree", not any(c.get("refused") for c in calls), "got %r" % [c.get("refused") for c in calls if c.get("refused")])
    refused = [c["refused"] for c in calls if c.get("refused")]
    S.ok("every dispatch is released -> %s" % (refused[0] if refused else "released"), all(d["released"] for d in w.dispatches().values()) and not refused,
         "open: %r" % [k for k, d in w.dispatches().items() if not d["released"]])
    idle = next(k for k, d in w.dispatches().items() if d["unit"] == "T2")
    order = [c["argv"][1] for c in calls if c.get("dispatch") == idle and c["argv"][1] in ("worker-stop", "worker-release")]
    S.eq("loop: the idle worker is stopped, then released", order, ["worker-stop", "worker-release"])
    S.eq("loop: the idle worker's last line was judged (its branch merged)", helpers.git(w.cwd, "log", "--format=%s", "--grep", "work T2").strip(), "work T2")
    left = [p for p in w.worktrees() if os.path.realpath(p) not in (os.path.realpath(w.repo), os.path.realpath(w.cwd))]
    reviewer = next((x["worktree"] for x in starts if x["unit"] == "r1"), "")
    S.ok("a reviewer worktree with no commit is removed -> kept", reviewer not in left and not os.path.exists(reviewer), "left %r" % left)
    S.eq("loop: no worktree of the run is left", left, [])
    st = w.state(run)
    S.eq("loop: state: done, nothing kept, a pid", (st["state"], st["result"]["kept"], isinstance(st.get("pid"), int)), ("done", [], True))
    S.eq("loop: a second `wave remove` of a removed run exits 0", (w.fwx("wave", "remove", "--run", run).returncode, w.fwx("wave", "remove", "--run", run).returncode), (0, 0))
    listing = w.fwx("wave", "list")
    rows = [x for x in listing.stdout.splitlines() if x.strip()]
    S.ok("loop: `wave list` prints one line per run", listing.returncode == 0 and len(rows) == 1 and run in rows[0] and "done" in rows[0], "got %r" % listing.stdout)


def case_nested(root, S):
    """A workspace whose code lives in nested repos (DTC-64): a part runs in the repo it names, with that repo's worktrees, branch and checks,
    and everything fwx keeps is the workspace's. Seen red on the code before it (python3 tests/test_wave_run.py):
      FAIL: nested: the run is done: got 'run <id> failed: git worktree add <ws>/.claude/worktrees/<id>-T1 failed: fatal: invalid reference: <sha>'
      FAIL: nested: `wave remove` from a worktree of repo b removes repo a's leftover worktree: exit 2, 'run <id> does not end in -<sha>-<n> of a commit of this repository'"""
    checks = {"a": ["test -f MARK_A"], "b": ["test -f MARK_B"]}
    w = world(nested=checks, tasks=[task("T1", 1, ["src/a.py"])])
    sc = w.scene
    a, b, ws = sc.nested["a"], sc.nested["b"], sc.repo
    r = w.run(root=root)
    m = line_of(r)
    S.ok("nested: the run is done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    if not m:
        return
    run = m.group(1)
    S.ok("nested: the task commit is on a's phase branch", "work T1" in helpers.git(a, "log", "--format=%s", "phase"), helpers.git(a, "log", "--format=%s", "phase"))
    S.eq("nested: the workspace has no branch but its own", helpers.git(ws, "branch", "--format=%(refname:short)").split(), ["master"])
    S.eq("nested: the run's files are under the workspace's .git/fwx/runs", sorted(w.runs()), [run])
    S.ok("nested: nothing of fwx's is in a's own .git", not os.path.exists(os.path.join(a, ".git", "fwx")))
    S.eq("nested: `orca repo add` named a", w.state_json().get("repos"), [a])
    S.eq("nested: no worktree of the run is left in a", [p for p in w.worktrees() if os.path.realpath(p) not in (a, sc.cwd)], [])
    # a second part, in repo b, on the same branch name: its worktrees are b's and the check that decides is b's
    bwt, bpart = w.second_part("b")
    r2 = w.run(cwd=bwt, part=bpart, root=root)
    m2 = line_of(r2)
    S.ok("nested: the part of repo b runs after it and is done (its check, `test -f MARK_B`, passes only in b)", bool(m2) and m2.group(2) == "done",
         "got %r %r" % (r2.stdout[-300:], r2.stderr[-300:]))
    S.ok("nested: the task commit of the second part is on b's phase branch", "work T1" in helpers.git(b, "log", "--format=%s", "phase"))
    S.ok("nested: and not on a's", "02-beta" not in helpers.git(a, "log", "--format=%B", "phase"))
    S.eq("nested: the workspace still has no branch but its own", helpers.git(ws, "branch", "--format=%(refname:short)").split(), ["master"])
    S.eq("nested: both runs are in the workspace's folder", len(w.runs()), 2)
    S.eq("nested: `orca repo add` named b after a", w.state_json().get("repos"), [a, b])
    S.eq("nested: no worktree of the second run is left in b", [p for p in helpers.git(b, "worktree", "list", "--porcelain").split("\n") if p.startswith("worktree ")
                                                                and os.path.realpath(p.split(" ", 1)[1]) not in (b, bwt)], [])
    # a leftover worktree of a's run, removed from a worktree of b: `wave remove` works in the checkout the run's own state names
    left = world(nested=checks, tasks=[task("T1", 1, ["src/a.py"])], behave={"release_fail": ["r1"]})
    rl = left.run(root=root)
    ml = line_of(rl)
    reviewer = next((x["worktree"] for x in left.starts() if x["unit"] == "r1"), "")
    S.ok("nested: a worker whose release failed leaves its worktree", bool(ml) and os.path.isdir(reviewer), "got %r %r" % (rl.stdout[-200:], rl.stderr[-200:]))
    if not ml or not os.path.isdir(reviewer):
        return
    lsc = left.scene
    common = helpers.git(reviewer, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    S.eq("nested: the worker's worktree is a worktree of a, under the workspace's .claude/worktrees", (common, os.path.realpath(reviewer).startswith(os.path.join(lsc.repo, ".claude", "worktrees") + os.sep)),
         (os.path.join(lsc.nested["a"], ".git"), True))
    away = lsc.worktree("b")
    rr = subprocess.run([sys.executable, os.path.join(root, "bin", "fwx"), "wave", "remove", "--run", ml.group(1)], cwd=away,
                        env=helpers.clean_env(CLAUDE_CONFIG_DIR=lsc.conf), capture_output=True, text=True)
    S.eq("nested: `wave remove` from a worktree of repo b removes repo a's leftover worktree: exit", (rr.returncode, rr.stderr.strip()[-200:]), (0, ""))
    S.ok("nested: the leftover worktree is gone", not os.path.exists(reviewer), "still there")


def case_nested_resume(root, S):
    """A cut run of repo a resumed from a worktree of repo b (the same branch name in both, by design) is refused before any step, naming both repos,
    and goes on from a's own worktree. Seen red on the code before the check (python3 tests/test_wave_run.py):
      FAIL: nested resume from repo b: exit 2, no worker, both repos named: got (1, ..., ['T1']), want (2, True, ['T1'])"""
    w = world(nested={"a": ["true"], "b": ["true"]}, tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "later"}})
    sc = w.scene
    a, b = sc.nested["a"], sc.nested["b"]
    p = start_run(w, root, FWX_RUN_LIMIT_S="60")
    end = time.time() + 20
    while time.time() < end and not (w.runs() and any(x.get("dispatch") for x in w.state(w.runs()[0])["workers"].values())):
        time.sleep(0.1)
    kill_group(p)  # the whole group: a fake orca call in flight would save a stale state.json after the kill
    run = w.runs()[0] if w.runs() else ""
    S.eq("nested resume: the first run started T1", units(w), ["T1"])
    bwt, _ = w.second_part("b")
    r = subprocess.run(w.argv(root, "--resume", run), cwd=bwt, env=w.env(), capture_output=True, text=True, timeout=120)
    S.eq("nested resume from repo b: exit 2, no worker, both repos named", (r.returncode, a in r.stderr and bwt in r.stderr, units(w)), (2, True, ["T1"]))
    helpers.write(w.dir, "go-T1", "")
    r = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
    m = line_of(r)
    S.ok("nested resume from a's own worktree: the run goes on to done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))


def stop_lags(w, run, unit, stopped, since=None):
    """Seconds from `since` (default: the runner's own start stamp of `unit` in state.json) to each recorded stop. The fake's call
    time `t` is taken after the fake process boots, so measuring from the fake's `worker-start` lags the runner's limit clock by that boot time
    (up to ~0.7 s on a loaded 4-CPU CI runner: `stopped after [2.2] s` against a 2.5 s limit). In a multi-worker wave, when the earliest worker
    hits LIMIT first, `finish()` tears down later-started siblings immediately, so pass the earliest worker's `started` as `since`."""
    rec = w.state(run)["workers"].get("%s/1" % unit) or {}
    t0 = since if since is not None else rec.get("started")
    return [t - t0 for t in stopped] if t0 else []


def case_failure(root, S):
    w = world(cap=3, tasks=[task("T1", 1, ["src/a.py"]), task("T2", 1, ["src/b.py"]), task("T3", 1, ["src/c.py"])],
              behave={"units": {"T1": "wait", "T2": "ok", "T3": "hang"}})
    r = w.run(root=root)
    m = line_of(r)
    S.ok("failure: the result line says failed and names the kept worktree", bool(m) and m.group(2) == "failed" and "1 worktree kept" in m.group(3), "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("failure: exit 1", r.returncode, 1)
    if not m:
        return
    st = w.state(m.group(1))
    starts = w.starts()
    t2 = next((x["worktree"] for x in starts if x["unit"] == "T2"), "")
    kept = [k["worktree"] for k in st["result"]["kept"]]
    S.ok("an executor worktree with unmerged commits stays -> %s" % ("removed" if t2 not in kept or not os.path.exists(t2) else "stays"),
         t2 in kept and os.path.exists(t2), "kept %r" % kept)
    S.ok("failure: the kept one has its reason", all(k.get("why") for k in st["result"]["kept"]) and "unmerged" in json.dumps(st["result"]["kept"]), "got %r" % st["result"]["kept"])
    others = [x["worktree"] for x in starts if x["unit"] in ("T1", "T3")]
    S.ok("failure: the worktrees with no work are removed", all(not os.path.exists(p) for p in others), "left %r" % [p for p in others if os.path.exists(p)])
    calls = w.calls()
    earliest = min((st["workers"].get("%s/1" % u) or {}).get("started", float("inf")) for u in ("T1", "T3"))
    stops = {}
    for unit in ("T1", "T3"):
        k = next(k for k, d in w.dispatches().items() if d["unit"] == unit)
        stopped = [c["t"] for c in calls if c.get("dispatch") == k and c["argv"][1] == "worker-stop"]
        stops[unit] = stopped
        lags = stop_lags(w, m.group(1), unit, stopped, since=earliest)
        S.ok("failure: %s (%s) is left alone until its limit, then stopped" % (unit, "waiting on a prompt" if unit == "T1" else "running"),
             len(stopped) == 1 and len(lags) == 1 and lags[0] >= LIMIT - 0.05, "stopped after %r s" % ([round(t, 2) for t in lags]))
    S.ok("failure: T3 is torn down only after T1 hit its limit", bool(stops["T1"]) and bool(stops["T3"]) and stops["T3"][0] >= stops["T1"][0],
         "stops=%r" % stops)
    refused = [c["refused"] for c in calls if c.get("refused")]
    S.ok("every dispatch is released -> %s" % (refused[0] if refused else "released"), all(d["released"] for d in w.dispatches().values()) and not refused)
    S.eq("failure: no reviewer ran", [x for x in units(w) if x.startswith("r")], [])
    w.state(m.group(1))


def case_error(root, S):
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "showfail"}})
    r = w.run(root=root)
    m = line_of(r)
    S.ok("error: a raised error ends the run failed, with the cause", bool(m) and m.group(2) == "failed" and "orca" in m.group(3).lower(), "got %r %r" % (r.stdout[-200:], r.stderr[-200:]))
    refused = [c["refused"] for c in w.calls() if c.get("refused")]
    S.ok("every dispatch is released -> %s (after a raised error)" % (refused[0] if refused else "released"), bool(w.dispatches()) and all(d["released"] for d in w.dispatches().values()))
    S.ok("error: the worktree of the worker is gone", all(not os.path.exists(x["worktree"]) for x in w.starts()))


def case_gate_red(root, S):
    w = world(tasks=[task("T1", 1, ["src/a.py"])], recipe=(BAD,), behave={"units": {"T1": {"mode": "ok", "files": {"src/a.py": "a1\n", "BAD": "1\n"}},
                                                                                        "fix-1": {"mode": "ok", "files": {"BAD": None}}}})
    r = w.run(root=root)
    m = line_of(r)
    S.ok("gate: a red gate is fixed and the run is done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("gate: one fixer between the executor and the review", units(w), ["T1", "fix-1", "r1"])
    if m:
        finals = [x for x in w.steps(m.group(1), "integrate") if x["args"]["final"]]
        S.eq("gate: the final merge ran twice, red then green", [x["exit"] for x in finals], [1, 0])
        S.eq("gate: one round spent", len(w.steps(m.group(1), "fix-round")), 1)


def case_retry(root, S):
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": ["failed-report", "ok"]}})
    r = w.run(root=root)
    m = line_of(r)
    S.ok("retry: a failed report is retried in a new worktree and the run is done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("retry: the same task is started twice, then the review", units(w), ["T1", "T1", "r1"])
    starts = w.starts()
    S.ok("retry: the second spec quotes the last report as data, the first does not", len(starts) > 1 and "new attempt in a new worktree" in starts[1]["spec"]
         and "could not do it" in starts[1]["spec"] and "new attempt" not in starts[0]["spec"])
    S.ok("retry: the two worktrees differ", len(starts) > 1 and starts[0]["worktree"] != starts[1]["worktree"])
    if m:
        S.eq("retry: one round spent", len(w.steps(m.group(1), "fix-round")), 1)
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "question"}})
    r = w.run(root=root)
    m = line_of(r)
    S.ok("owner: a question ends the run needs-owner with the question, exit 3", bool(m) and m.group(2) == "needs-owner" and "which one do you mean?" in m.group(3) and r.returncode == 3,
         "exit %d, got %r" % (r.returncode, r.stdout[-300:]))
    S.eq("owner: no reviewer started", units(w), ["T1"])


def case_conflict(root, S):
    tasks = [task("T1", 1, ["src/a.py"]), task("T2", 1, ["src/a.py"]), task("T3", 1, ["src/c.py"])]
    w = world(tasks=tasks, behave={"files": {"T1": {"src/a.py": "one\n"}, "T2": {"src/a.py": "two\n"}, "T3": {"src/c.py": "c1\n"}},
                                   "units": {"resolve-1": {"mode": "ok", "merge": "T2"}}})
    r = w.run(root=root)
    m = line_of(r)
    S.ok("conflict: a conflicting branch goes to a resolver and the run is done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("conflict: the serial wave, the resolver, the review", units(w), ["T1", "T2", "T3", "resolve-1", "r1"])
    S.eq("conflict: the branch after the conflicting one is merged after the resolver", open(os.path.join(w.cwd, "src", "c.py")).read() if os.path.exists(os.path.join(w.cwd, "src", "c.py")) else None, "c1\n")
    S.eq("conflict: no worktree of the run is left", [p for p in w.worktrees() if os.path.realpath(p) not in (os.path.realpath(w.repo), os.path.realpath(w.cwd))], [])


def case_fix(root, S):
    w = world(behave={"units": {"fix": {"mode": "ok", "files": {"src/a.py": "fixed "}, "findings": ["F1"]}}})
    path = helpers.write(w.dir, "fix.json", json.dumps([{"id": "F1", "file": "src/a.py", "line": 1, "claim": "wrong", "evidence": "seen", "severity": "high"}]))
    r = w.run("--fix", path, root=root)
    m = line_of(r)
    S.ok("fix: done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("fix: one fixer and the review, no executor", units(w), ["fix", "r1"])
    if m:
        final = [x for x in w.steps(m.group(1), "integrate") if x["args"]["final"]]
        S.eq("fix: the final merge carries the findings", [x["args"]["findings"] for x in final], [["F1"]])


def case_gate_entry(root, S):
    w = world()
    w.put_done()
    r = w.run("--from", "gate", root=root)
    m = line_of(r)
    S.ok("from gate: done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("from gate: no executor, the review only", units(w), ["r1"])
    if m:
        S.eq("from gate: the gate ran with no branch", [(x["args"]["branches"], x["args"]["final"]) for x in w.steps(m.group(1), "integrate")], [([], True)])


def case_revert(root, S):
    w = world()
    w.put_done(tasks=("T1",), findings=("X1",))
    r = w.run("--revert", "X1", root=root)
    m = line_of(r)
    S.ok("revert: done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("revert: no worker, no Orca call", (w.starts(), w.calls()), ([], []))
    S.ok("revert: the finding's commit is reverted on the phase branch", helpers.git(w.cwd, "log", "-1", "--format=%s").startswith("Revert"))
    # verify exits 2 when HEAD moves during checks: routed to needs-owner (exit 3), not failed (exit 1).
    # Seen red before the fix: FAIL: revert with HEAD moving during verify: needs-owner (exit 3): exit 1, got 'run ... failed: the gate failed after the revert: ...'
    move = "python3 -c \"import os,subprocess; os.path.exists('src/f-X1.txt') or subprocess.check_call(['git','commit','--allow-empty','-q','-m','moved'])\""
    w = world(recipe=(move,))
    w.put_done(tasks=("T1",), findings=("X1",))
    r = w.run("--revert", "X1", root=root)
    m = line_of(r)
    S.ok("revert with HEAD moving during verify: needs-owner (exit 3)", r.returncode == 3 and bool(m) and m.group(2) == "needs-owner" and "verify could not run" in m.group(3),
         "exit %d, got %r %r" % (r.returncode, r.stdout[-300:], r.stderr[-300:]))
    # verify exits 2 with no JSON (e.g. reverting the commit that provided package.json's only check script): needs-owner (exit 3), not failed.
    # Seen red before the fix: FAIL: revert with verify exiting 2 and no JSON: needs-owner (exit 3): exit 1, got 'run ... failed: fwx verify --json exited 2 with no JSON: ...'
    w = world(recipe=())
    helpers.write(w.bin, "npm", "#!/bin/sh\nexit 0\n", 0o755)
    base = helpers.git(w.cwd, "rev-parse", "HEAD").strip()
    run_id = "01-alpha-%s-1" % base[:7]
    helpers.write(w.cwd, "package.json", json.dumps({"scripts": {"test": "true"}}))
    helpers.git(w.cwd, "add", "-A")
    helpers.git(w.cwd, "commit", "-q", "-m", "fix X1\n\nFwx-Finding: X1\nFwx-Run: %s" % run_id)
    r = w.run("--revert", "X1", root=root)
    m = line_of(r)
    S.ok("revert with verify exiting 2 and no JSON: needs-owner (exit 3)", r.returncode == 3 and bool(m) and m.group(2) == "needs-owner" and "verify could not run" in m.group(3),
         "exit %d, got %r %r" % (r.returncode, r.stdout[-300:], r.stderr[-300:]))


def case_security(root, S):
    w = world(tasks=[task("T1", 1, ["src/a.py"])])
    r = w.run("--security", root=root)
    S.eq("security: exit", r.returncode, 0)
    S.eq("security: the security reviewer joins the pass", [(x["unit"], x["marker"]["role"]) for x in w.starts()],
         [("T1", "executor"), ("r1", "reviewer"), ("r1-sec", "security-reviewer")])


def case_refusals(root, S):
    w = world(recipe=("false",))
    r = w.run(root=root)
    S.eq("red base: exit 1 and no Orca call", (r.returncode, w.calls()), (1, []))
    w = world(context=False, tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "hang"}})  # a worker that started would hang: one start, not a run
    r = w.run(root=root)
    n = len(w.starts())
    S.ok("no base context, no worker -> %d start" % n, r.returncode == 2 and n == 0, "exit %d, stderr %r" % (r.returncode, r.stderr[-200:]))
    S.ok("no base context: the reason names the file", "base" in r.stderr.lower(), "got %r" % r.stderr[-200:])


def case_registered(root, S):
    w = world(tasks=[task("T1", 1, ["src/a.py"])])
    w.behave["registered"] = [os.path.realpath(w.repo)]
    w.set_behave()
    w.run(root=root)
    S.eq("registered: a repo Orca already lists is not added again", len([c for c in w.calls() if c["argv"][:2] == ["repo", "add"]]), 0)


def case_one_run(root, S):
    w = world(tasks=[task("T1", 1, ["src/a.py"])])
    folder = os.path.join(w.common, "fwx", "runs", "01-alpha-0000000-9")
    helpers.write(folder, "state.json", json.dumps({"run": "01-alpha-0000000-9", "branch": "phase", "part_dir": w.part, "pid": os.getpid(), "state": "active",
                                                   "step": "executing", "workers": {}, "worktrees": [], "steps": []}))
    r = w.run(root=root)
    S.ok("one run per branch: a second run exits 2 naming the run and --resume", r.returncode == 2 and "01-alpha-0000000-9" in r.stderr and "--resume" in r.stderr,
         "exit %d, stderr %r" % (r.returncode, r.stderr[-300:]))
    S.eq("one run per branch: it started nobody", w.starts(), [])
    rows = [x for x in w.fwx("wave", "list").stdout.splitlines() if "01-alpha-0000000-9" in x]
    S.ok("`wave list` shows the live run", len(rows) == 1 and "alive" in rows[0], "got %r" % rows)


def case_resume(root, S):
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "later"}})
    p = subprocess.Popen(w.argv(root), cwd=w.cwd, env=w.env(FWX_RUN_LIMIT_S="60"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    w.procs.append(p)
    end = time.time() + 20
    while time.time() < end and not (w.runs() and any(x.get("dispatch") for x in w.state(w.runs()[0])["workers"].values())):
        time.sleep(0.1)
    S.eq("resume: the first run started T1", units(w), ["T1"])
    p.kill()
    p.wait()
    run = w.runs()[0] if w.runs() else ""
    # a resumed run merges into whatever is checked out: on another branch it is refused before any step (CodeRabbit 4696262664).
    # Seen red on the code before the fix: FAIL: resume on another branch: exit 2, no step, no worker -> got (0, ...), want (2, ...)
    helpers.git(w.cwd, "checkout", "-q", "-b", "elsewhere")
    r = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
    S.eq("resume on another branch: exit 2, the branch named, no worker started", (r.returncode, "is on elsewhere" in r.stderr and "phase" in r.stderr, units(w)), (2, True, ["T1"]))
    helpers.git(w.cwd, "checkout", "-q", "phase")
    helpers.write(w.dir, "go-T1", "")
    r = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
    m = line_of(r)
    S.ok("resume: the run goes on to done", bool(m) and m.group(2) == "done" and m.group(1) == run, "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("resume: no worker the state already held is started again", units(w), ["T1", "r1"])
    S.ok("resume: every dispatch is released", all(d["released"] for d in w.dispatches().values()))


def case_lock(root, S):
    """Two `wave run` on one branch cannot both pass the check for a live run before either is recorded (CodeRabbit 4696262872): a branch lock held
    for the whole command. Seen red on the code before the fix: FAIL: a branch whose lock is held: the run exits 2 and starts nobody -> got (0, ['T1', 'r1'])."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from fwx.execute import run as run_mod
    w = world(tasks=[task("T1", 1, ["src/a.py"])])
    if not S.ok("run.py names the branch lock", hasattr(run_mod, "lock_path")):
        return
    path = run_mod.lock_path(w.repo, "phase")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = w.run(root=root)
        S.eq("a branch whose lock is held: the run exits 2 and starts nobody", (r.returncode, "starting or running" in r.stderr, units(w)), (2, True, []))
    r = w.run(root=root)
    S.eq("the lock released (its holder gone): the run goes", (r.returncode, units(w)), (0, ["T1", "r1"]))
    S.ok("the lock file does not read as a run", [x for x in w.fwx("wave", "list").stdout.splitlines() if x.strip()] != [] and ".lock" not in w.fwx("wave", "list").stdout)


def case_release(root, S):
    """A worker whose release fails keeps its slot and its worktree (CodeRabbit 4696262860, 4696262886, and the null `message` of 4696262711).
    Seen red on the code before the fix:
      FAIL: cap 1, T1 cannot be released: no other worker starts -> ['T1', 'T2', 'T3', 'r1']
      FAIL: the reviewer whose release failed keeps its worktree -> removed
      FAIL: orca's error with a null message is an OrcaError, the run ends with a line -> exit 1 / script error: TypeError"""
    w = world(behave={"release_fail": ["T1"]})
    r = w.run(root=root)
    m = line_of(r)
    S.eq("cap 1, T1 cannot be released: no other worker starts", units(w), ["T1"])
    S.ok("the run ends failed naming the worker that could not be released", bool(m) and m.group(2) == "failed" and "T1 could not be released" in m.group(3), "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.ok("an orca error whose message is null does not become a script error", not m or "TypeError" not in m.group(3), m.group(3) if m else r.stderr[-200:])
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"release_fail": ["r1"]})
    r = w.run(root=root)
    m = line_of(r)
    reviewer = next((x["worktree"] for x in w.starts() if x["unit"] == "r1"), "")
    S.ok("the reviewer whose release failed keeps its worktree -> %s" % ("kept" if os.path.isdir(reviewer) else "removed"), bool(reviewer) and os.path.isdir(reviewer))
    S.ok("and the line says it was kept", bool(m) and "kept" in r.stdout and "1 worktree kept" in m.group(3), "got %r" % r.stdout[-300:])
    S.ok("a worker whose release failed is not named a worktree to remove: the kept reason says why", "could not be released" in r.stderr, r.stderr[-300:])


def case_alive(root, S):
    """A pid whose signal 0 is refused (EPERM) is a live process (CodeRabbit 4696262805). Seen red on the code before the fix:
    FAIL: alive(pid) when kill answers EPERM -> False"""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from fwx.execute import run as run_mod
    real = os.kill

    def kill(pid, sig):
        raise PermissionError(1, "Operation not permitted")
    os.kill = kill
    try:
        got = run_mod.alive(1)
    finally:
        os.kill = real
    S.eq("alive(pid) when kill answers EPERM -> %s" % got, got, True)
    S.eq("a pid that is gone is not alive", run_mod.alive(2 ** 22 + 12345), False)


def case_settings_mode(root, S):
    """The settings copy of a worker is private when the original is (CodeRabbit 4696262748). Seen red on the code before the fix:
    FAIL: a worker's settings copy is mode 0600 -> 0644"""
    w = world(tasks=[task("T1", 1, ["src/a.py"])])
    os.chmod(os.path.join(w.repo, ".claude", "settings.local.json"), 0o600)
    old = os.umask(0o022)
    try:
        r = w.run(root=root)
    finally:
        os.umask(old)
    modes = [x["settings_mode"] for x in w.starts()]
    S.ok("the run ends done", bool(line_of(r)) and line_of(r).group(2) == "done", r.stderr[-200:])
    S.eq("a worker's settings copy is mode 0600 -> %s" % [oct(m) for m in modes], modes and set(modes), {0o600})


def case_transcript(root, S):
    """`orca.last_text` stops on an empty page or `limited: false` even with a non-empty end cursor, and picks the last reply line
    even when closing prose follows `worker_done`; the spec puts `worker_done` before the final reply line.
    Seen red before the fix:
      FAIL: transcript: trailing prose causes no relaunch: got ['T1', 'T1'], want ['T1', 'r1']
      FAIL: transcript: worker-read stops at end cursor (3 for 2-page limited=True, 1 for limited=False): got (50, None), want (3, 1)"""
    w = world(tasks=[task("T1", 1, ["src/a.py"])],
              behave={"units": {"T1": {"mode": "ok", "pages": 2, "trailing": "Done, I sent worker_done to the coordinator."}}})
    r = w.run(root=root)
    m = line_of(r)
    S.ok("transcript: done despite trailing prose and multi-page transcript", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("transcript: trailing prose causes no relaunch", units(w), ["T1", "r1"])
    reads = {}
    for c in w.calls():
        if c["argv"][:2] == ["orchestration", "worker-read"]:
            reads[c["dispatch"]] = reads.get(c["dispatch"], 0) + 1
    by_unit = {d["unit"]: reads.get(k, 0) for k, d in w.dispatches().items()}
    S.eq("transcript: worker-read stops at end cursor (3 for 2-page limited=True, 1 for limited=False)", (by_unit.get("T1"), by_unit.get("r1")), (3, 1))
    spec = w.starts()[0]["spec"] if w.starts() else ""
    S.ok("transcript: spec puts worker_done before ending the turn with the reply line",
         "worker_done" in spec and "first" in spec[spec.rfind("worker_done") - 80:] and "When you have returned your last line" not in spec, spec[-260:])


def case_waiting(root, S):
    """A ready/idle worker whose `waitingOnHuman` is true, `unknown` or absent may be waiting on a person and is left alone until its limit,
    not stopped at IDLE_S.
    Seen red before the fix:
      FAIL: waiting (unknown): left alone until its limit, not stopped as idle: exit 1, stopped after [1.85] s
      FAIL: waiting (absent): left alone until its limit, not stopped as idle: exit 1, stopped after [1.86] s"""
    for label, mode in (("true", "wait"), ("unknown", "wait-unknown"), ("absent", "wait-absent")):
        w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": mode}})
        r = w.run(root=root)
        calls = w.calls()
        k = next(iter(w.dispatches()), None)
        stopped = [c["t"] for c in calls if c.get("dispatch") == k and c["argv"][1] == "worker-stop"]
        lags = stop_lags(w, w.runs()[0], "T1", stopped) if w.runs() else []
        S.ok("waiting (%s): left alone until its limit, not stopped as idle" % label,
             r.returncode == 1 and len(stopped) == 1 and len(lags) == 1 and lags[0] >= LIMIT - 0.05,
             "exit %d, stopped after %r s" % (r.returncode, [round(t, 2) for t in lags]))


def case_review_fix(root, S):
    """A reviewer returning findings triggers `review()`'s fixer + re-merge + second pass; `--control-findings` given as a relative path
    from a subdirectory still reaches `wave findings`.
    Seen red before the fix:
      FAIL: control-findings relative from subdir: done and fixed r1-C1: exit 1, units ['T1', 'r1'], out '... --control-findings ... cannot be read ...'"""
    finding = {"id": "F1", "file": "src/a.py", "line": 1, "claim": "wrong value", "evidence": "seen", "severity": "high"}
    w = world(tasks=[task("T1", 1, ["src/a.py"])],
              behave={"units": {"r1": {"mode": "ok", "findings": [finding]},
                                "fix-1": {"mode": "ok", "files": {"src/a.py": "fixed "}, "findings": ["r1-F1"]}}})
    r = w.run(root=root)
    m = line_of(r)
    S.ok("review fix: done after fixer and second pass", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("review fix: executor, r1, fix-1, r2", units(w), ["T1", "r1", "fix-1", "r2"])
    if m:
        S.eq("review fix: one round spent", len(w.steps(m.group(1), "fix-round")), 1)
    S.ok("review fix: Fwx-Finding trailer merged on phase branch", "Fwx-Finding: r1-F1" in helpers.git(w.cwd, "log", "-n", "5"))
    # relative `--control-findings` from a subdirectory of the worktree
    w2 = world(tasks=[task("T1", 1, ["src/a.py"])],
               behave={"units": {"fix-1": {"mode": "ok", "files": {"src/a.py": "ctrl "}, "findings": ["r1-C1"]}}})
    helpers.write(w2.cwd, "sub/keep.txt", "k\n")
    helpers.git(w2.cwd, "add", "-A")
    helpers.git(w2.cwd, "commit", "-q", "-m", "add subdir")
    ctrl_abs = helpers.write(w2.dir, "ctrl.json", json.dumps([{"id": "C1", "file": "src/a.py", "line": 1, "claim": "control", "evidence": "seen", "severity": "high"}]))
    subdir = os.path.join(w2.cwd, "sub")
    ctrl_rel = os.path.relpath(ctrl_abs, subdir)
    r2 = w2.run("--control-findings", ctrl_rel, root=root, cwd=subdir)
    m2 = line_of(r2)
    S.ok("control-findings relative from subdir: done and fixed r1-C1", bool(m2) and m2.group(2) == "done" and units(w2) == ["T1", "r1", "fix-1", "r2"],
         "exit %d, units %r, out %r, err %r" % (r2.returncode, units(w2), r2.stdout[-200:], r2.stderr[-200:]))


def case_discover(root, S):
    """Orca knows a worktree only once it has discovered it: `worker-start` of one fwx had just made with `git worktree add` answered
    `selector_not_found` (live, Orca 1.4.273, run 10-nested-repos-f97847b-1: `orca orchestration worker-start failed (exit 1): selector_not_found: No workspace
    matches --worktree path:.../10-nested-repos-f97847b-1-T5. Nothing was started; no effects were applied.`). Orca has no command that makes it discover a path at once
    (`orca help worktree`, `orca help repo`: only `worktree create` and `repo add`), so fwx polls `worktree show` and retries a `selector_not_found` of `worker-start`.
    Seen red on the code before the fix (the fake knows a worktree only after 2 `worktree show` calls):
    FAIL: discover: the run is done -> got 'run <id> failed: orca orchestration worker-start failed (exit 1): selector_not_found: No workspace matches --worktree path:...'."""
    fast = {"FWX_ORCA_DISCOVER_POLL_S": "0.05"}
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"discover_after": 2})
    r = w.run(root=root, **fast)
    m = line_of(r)
    S.ok("discover: the run is done -> %s" % (r.stdout.strip().splitlines() or ["no output"])[-1][:200], bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    shows = [c["show"] for c in w.calls() if "show" in c and c["argv"][:2] == ["worktree", "show"]]
    S.ok("discover: worker-start waited for Orca to know the worktree -> %d show calls" % len(shows), len(shows) >= 3 and len(set(shows)) <= len(units(w)), "shows %r" % shows)
    S.eq("discover: the units started", units(w), ["T1", "r1"])
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"start_not_found": 2})
    r = w.run(root=root, **fast)
    m = line_of(r)
    S.ok("discover: a selector_not_found of worker-start itself is retried and the run is done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("discover: the first worker-start of a worktree was tried 3 times", w.state_json()["start_tries"].get(w.starts()[0]["worktree"]) if w.starts() else None, 3)
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"discover_after": 10 ** 6})
    r = w.run(root=root, FWX_ORCA_DISCOVER_POLL_S="0.05", FWX_ORCA_DISCOVER_S="0.4")
    m = line_of(r)
    S.ok("discover: a worktree Orca never knows ends the run failed, naming it", bool(m) and m.group(2) == "failed" and "-T1" in m.group(3) and "never discovered" in m.group(3),
         "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("discover: no worker started and the worktree is removed", (units(w), [p for p in w.worktrees() if "-T1" in p]), ([], []))


def case_terminal(root, S):
    """Orca 1.4.273 refuses `orchestration run-create` with no sender terminal once the session variables are stripped (`no_active_sender_terminal`), so
    the run makes one terminal (`fwx run <R>`, in the phase worktree it runs from: a terminal in the main checkout would put a tab in the owner's own workspace), names it
    with `--from` and closes it however the run ends.
    Seen red on the code that made it in the main checkout (`self.main`): FAIL: terminal (success): one made, titled for the run, in the phase worktree ->
    got [('fwx run <id>', 'path:<main checkout>')], want [('fwx run <id>', 'path:<phase worktree>')]. The Orca run's objective names the part and the run:
    FAIL: terminal (success): run-create objective -> got 'fwx wave run <id>', want 'fwx 01-alpha (<id>)'.
    Seen red on the code before the fix (every case that runs a part): FAIL: loop: exit, stderr -> got (1, 'orca: orca orchestration run-create failed
    (exit 1): no_active_sender_terminal: Could not determine the calling terminal ...'), want (0, '').
    The same for `worker-start` (live, Orca 1.4.273, run 10-nested-repos-0c34fbb-1: `orca orchestration worker-start failed (exit 1):
    no_active_sender_terminal`): the fake refuses it, and `send`, with no `--from`. Seen red on the code before that fix: test_wave_run.py exit 1, the first case
    reached no worker (`IndexError: list index out of range` at case_loop's `starts[0]["spec"]`), and its mutant below fails with
    FAIL: terminal (success): every worker-start names that terminal -> got [], terminals ['term_1']."""
    for name, behave, status in (("success", {}, "done"), ("failure", {"units": {"T1": "failed-report"}}, "failed"), ("raised error", {"units": {"T1": "showfail"}}, "failed")):
        w = world(tasks=[task("T1", 1, ["src/a.py"])], behave=behave)
        r = w.run(root=root)
        m = line_of(r)
        S.ok("terminal: the %s ends %s" % (name, status), bool(m) and m.group(2) == status, "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
        terms = w.terminals()
        S.eq("terminal (%s): one made, titled for the run, in the phase worktree" % name, [(t["title"], t["worktree"]) for t in terms.values()],
             [("fwx run " + m.group(1), "path:" + os.path.realpath(w.cwd))] if m else [])
        objectives = [c["objective"] for c in w.calls() if c["argv"][:2] == ["orchestration", "run-create"] and "objective" in c]
        S.eq("terminal (%s): run-create objective names the part and the run" % name, objectives, ["fwx %s (%s)" % (os.path.basename(w.part), m.group(1))] if m else [])
        S.ok("the terminal is closed after a %s -> open" % name, bool(terms) and not any(t["open"] for t in terms.values()), "terminals %r" % terms)
        sent = [c["sender"] for c in w.calls() if c["argv"][:2] == ["orchestration", "run-create"] and "sender" in c]
        S.eq("terminal (%s): run-create names that terminal" % name, sent, list(terms)[:1])
        starts = [c["start"]["sender"] for c in w.calls() if c["argv"][:2] == ["orchestration", "worker-start"] and "start" in c]
        S.ok("terminal (%s): every worker-start names that terminal" % name, bool(starts) and starts == [list(terms)[0]] * len(starts), "got %r, terminals %r" % (starts, list(terms)))
        S.ok("terminal (%s): no call carries an Orca session variable" % name, all(not any(c["env"].values()) for c in w.calls()))
        if m:
            S.ok("terminal (%s): the state no longer holds an open terminal" % name, not w.state(m.group(1)).get("terminal"), "got %r" % w.state(m.group(1)).get("terminal"))


def case_terminal_resume(root, S):
    """A resumed run uses the terminal its state names while it is live, makes a new one when Orca lost it, and closes it at the end.
    Orca answers `terminal show` of a closed handle ok with `terminal.orphaned: true`, not an error. Seen red on code that read only an error as gone:
    FAIL: terminal resume (gone): terminals made: got 1, want 2.
    The same FAIL came on CI (PR 252, shard 3/3) from a race older than that PR: `p.kill()` killed only fwx, and a fake orca call of its poll still in flight
    saved the `state.json` it had read before the `open: False` edit below, so the resumed run found its terminal open again. With a fake whose `worker-show`
    sleeps 0.25 s before it saves, on master f97847b: FAIL: terminal resume (gone): terminals made: got 1, want 2 (2 runs of 4, and 6 of 6 clean with the group kill). Killing the process group
    ends the in-flight fake with fwx."""
    for name, lose in (("live", False), ("gone", True)):
        w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "later"}})
        p = subprocess.Popen(w.argv(root), cwd=w.cwd, env=w.env(FWX_RUN_LIMIT_S="60"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        w.procs.append(p)
        end = time.time() + 20
        while time.time() < end and not (w.runs() and any(x.get("dispatch") for x in w.state(w.runs()[0])["workers"].values())):
            time.sleep(0.1)
        os.killpg(p.pid, signal.SIGKILL)  # the whole group: a fake orca of the run still in flight would save its stale state.json after the edit below
        p.wait()
        run = w.runs()[0] if w.runs() else ""
        first = (w.state(run).get("terminal") if run else None) or ""
        end = time.time() + 20  # the fake saves its registry atomically, but the check waits for what it reads rather than reading once
        while time.time() < end and not w.terminals().get(first, {}).get("open"):
            time.sleep(0.05)
        S.ok("terminal resume (%s): the killed run's state names its open terminal" % name, bool(first) and w.terminals().get(first, {}).get("open") is True, "got %r %r" % (first, w.terminals()))
        if lose and first:
            with open(os.path.join(w.dir, "state.json"), encoding="utf-8") as f:
                data = json.load(f)
            data["terminals"][first]["open"] = False
            helpers.write(w.dir, "state.json", json.dumps(data))
        helpers.write(w.dir, "go-T1", "")
        r = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
        m = line_of(r)
        S.ok("terminal resume (%s): the run goes on to done" % name, bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
        terms = w.terminals()
        S.eq("terminal resume (%s): terminals made" % name, len(terms), 2 if lose else 1)
        S.ok("terminal resume (%s): none left open" % name, not any(t["open"] for t in terms.values()), "terminals %r" % terms)
        S.eq("terminal resume (%s): Orca runs made (a Run is bound to its terminal: a new terminal makes a new one)" % name,
             len([c for c in w.calls() if c["argv"][:2] == ["orchestration", "run-create"]]), 2 if lose else 1)


def case_terminal_discover(root, S):
    """The sender terminal is made in the phase worktree, which Orca may not have discovered yet (`selector_not_found` from `terminal create`, as `worker-start` answers
    for a worktree made with git): `terminal_create` retries it for DISCOVER_S, like `start`, and past that ends the run failed naming the worktree.
    Seen red on the code before the retry (the fake refuses the first 2 `terminal create` calls):
      FAIL: terminal discover: the run is done -> run <id> failed: orca: orca terminal create failed (exit 1): selector_not_found: No workspace matches --worktree path:...
      FAIL: terminal discover: the terminal was asked for 3 times (2 refused, then made): got 1, want 3"""
    fast = {"FWX_ORCA_DISCOVER_POLL_S": "0.05"}
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"terminal_discover_after": 2})
    r = w.run(root=root, **fast)
    m = line_of(r)
    S.ok("terminal discover: the run is done -> %s" % (r.stdout.strip().splitlines() or ["no output"])[-1][:200], bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    tries = [c for c in w.calls() if c["argv"][:2] == ["terminal", "create"]]
    S.eq("terminal discover: the terminal was asked for 3 times (2 refused, then made)", len(tries), 3)
    S.eq("terminal discover: the one terminal made is in the phase worktree", [t["worktree"] for t in w.terminals().values()], ["path:" + os.path.realpath(w.cwd)])
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"terminal_discover_after": 10 ** 6})
    r = w.run(root=root, FWX_ORCA_DISCOVER_POLL_S="0.05", FWX_ORCA_DISCOVER_S="0.4")
    m = line_of(r)
    S.ok("terminal discover: a worktree Orca never knows ends the run failed, naming it", bool(m) and m.group(2) == "failed" and "never discovered" in m.group(3)
         and os.path.realpath(w.cwd) in m.group(3), "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("terminal discover: no worker started", units(w), [])


def case_list_json(root, S):
    """`fwx wave list --json` prints `{"runs": [...]}` for the Orca panel and the chip (the plain `wave list` stays as it was). A finished run, a live one, a bad flag.
    Seen red on the code before it (`wave list` took no flag; the case returns at the first missing run):
      FAIL: list --json: exit 0 and one JSON document -> exit 2, stdout '', stderr 'usage: fwx wave list\\n'
      FAIL: list --json: one run: got 0, want 1
    The plain-output check passed on the old code: it pins the line the JSON must not change."""
    w = world()

    def fwx(*args):  # through `root`, so that a control tree is the code under test
        return subprocess.run([sys.executable, os.path.join(root, "bin", "fwx")] + list(args), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=60)
    r = w.run(root=root)
    m = line_of(r)
    S.ok("list --json: the run is done", bool(m) and m.group(2) == "done", "got %r %r" % (r.stdout[-200:], r.stderr[-200:]))
    if not m:
        return
    run, part = m.group(1), os.path.basename(w.part)
    plain = fwx("wave", "list")
    S.ok("list: plain output is one line per run, unchanged", plain.returncode == 0 and re.fullmatch(
        r"%s part=%s branch=phase done pid=\d+ dead workers=0/4 step=\S+( \S+)?\n" % (re.escape(run), re.escape(part)), plain.stdout) is not None, "got %r" % plain.stdout)
    j = fwx("wave", "list", "--json")
    try:
        doc = json.loads(j.stdout)
    except ValueError:
        doc = None
    S.ok("list --json: exit 0 and one JSON document -> exit %d, stdout %r, stderr %r" % (j.returncode, j.stdout[:80], j.stderr[:80]), j.returncode == 0 and isinstance(doc, dict))
    runs = (doc or {}).get("runs") or []
    S.eq("list --json: one run", len(runs), 1)
    if not runs:
        return
    x = runs[0]
    S.eq("list --json: the run's identity", (x["run"], x["part"], x["branch"], x["state"], x["alive"], isinstance(x["pid"], int), isinstance(x["orca_run"], str)),
         (run, part, "phase", "done", False, True, True))
    S.eq("list --json: the planned waves with their task ids", x["waves"], [{"n": 1, "tasks": ["T1", "T2"]}, {"n": 2, "tasks": ["T3"]}])
    S.eq("list --json: every worker, released, with its role and last line", sorted((k["unit"], k["role"], k["released"], bool(k["line"])) for k in x["workers"]),
         [("T1", "executor", True, True), ("T2", "executor", True, True), ("T3", "executor", True, True), ("r1", "reviewer", True, True)])
    S.eq("list --json: a worker has exactly the keys the panel reads", sorted(x["workers"][0]), ["line", "released", "role", "state", "unit"])
    S.eq("list --json: the events are the last 8 progress lines, the newest last (14 were printed)", len(x["events"]), 8)
    S.ok("list --json: the last event is the review's findings line -> %r" % x["events"][-1:], x["events"] and x["events"][-1].startswith("review findings"))
    S.eq("list --json: the events are the lines the run printed", [e for e in x["events"] if e not in r.stdout.splitlines()], [])
    S.eq("list --json: the result of a finished run", (x["result"] or {}).get("status"), "done")
    bad = fwx("wave", "list", "--bogus")
    S.eq("list: any other argument exits 2 with the usage", (bad.returncode, "usage: fwx wave list [--json]" in bad.stderr), (2, True))
    bad = fwx("wave", "list", "--json", "x")
    S.eq("list: --json with another argument exits 2 too", bad.returncode, 2)
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "later"}})
    p = start_run(w, root, FWX_RUN_LIMIT_S="60")
    wait_for(lambda: w.runs() and any(k.get("dispatch") for k in w.state(w.runs()[0])["workers"].values()))
    doc = json.loads(fwx("wave", "list", "--json").stdout or "{}")
    live = (doc.get("runs") or [None])[0]
    S.ok("list --json: a live run: active, alive, its worker started and not released -> got %s" % ((live["state"], live["alive"], live["workers"]) if live else None,),
         bool(live) and live["state"] == "active" and live["alive"] is True and live["step"] == "wave 1" and [(k["unit"], k["released"]) for k in live["workers"]] == [("T1", False)]
         and live["result"] is None)
    S.ok("list --json: a live run's events name the worker that started", bool(live) and any(e.startswith("worker T1 started") for e in live["events"]), "events %r" % (live or {}).get("events"))
    helpers.write(w.dir, "go-T1", "")
    finish_run(p)
    # Relaunch / --fix / --revert / malformed state.json: `done` is emitted, --fix/--revert suppress planned waves, and a broken state never crashes `wave list --json`.
    # Seen red before the fixes (blocker 1 & blocker 3):
    #   FAIL: list --json: --fix suppresses planned waves and carries done -> got ([{'n': 1, 'tasks': ['T1']}], None), want ([], ['T1'])
    #   FAIL: list --json: a malformed state.json does not crash wave list --json -> exit 1
    runs_dir = os.path.join(w.common, "fwx", "runs")
    helpers.write(os.path.join(runs_dir, "01-alpha-fix-1"), "state.json", json.dumps({
        "run": "01-alpha-fix-1", "part_dir": w.part, "branch": "phase", "state": "done", "pid": 1, "step": "fix",
        "args": {"waves": [{"n": 1, "tasks": [{"id": "T1"}]}], "done": ["T1"], "fix": {"brief": "b", "findings": []}},
        "workers": {}, "events": []}))
    helpers.write(os.path.join(runs_dir, "01-alpha-bad-1"), "state.json", json.dumps({
        "run": "01-alpha-bad-1", "part_dir": None, "branch": "phase", "state": "failed", "pid": True, "step": "start",
        "args": {"waves": [{"n": 1, "tasks": None}, "bad"], "done": None},
        "workers": {"k": "not-a-dict"}, "events": None}))
    j2 = fwx("wave", "list", "--json")
    try:
        by_id = {x["run"]: x for x in (json.loads(j2.stdout).get("runs") or [])}
    except ValueError:
        by_id = {}
    S.ok("list --json: a malformed state.json does not crash wave list --json -> exit %d, stderr %r" % (j2.returncode, j2.stderr[:120]),
         j2.returncode == 0 and "01-alpha-bad-1" in by_id and by_id["01-alpha-bad-1"]["pid"] is None and by_id["01-alpha-bad-1"]["workers"] == [] and by_id["01-alpha-bad-1"]["events"] == [])
    fx = by_id.get("01-alpha-fix-1") or {}
    S.eq("list --json: --fix suppresses planned waves and carries done", (fx.get("waves"), fx.get("done")), ([], ["T1"]))


# ---------------------------------------------------------------------------------------------------------------------- what the owner sees

def reader(p):
    """The lines `p` prints to stdout, collected as they come by a thread: [lines], so a test can look before the process ends."""
    got = []
    threading.Thread(target=lambda: [got.append(x.rstrip("\n")) for x in p.stdout], daemon=True).start()
    return got


def in_order(lines, needles):
    """None when the regexes of `needles` match `lines` in that order (other lines may lie between), else the first needle that did not."""
    at = 0
    for n in needles:
        hit = next((i for i in range(at, len(lines)) if re.search(n, lines[i])), None)
        if hit is None:
            return n
        at = hit + 1
    return None


def case_progress(root, S):
    """`fwx wave run` prints one plain line per step to stdout as it goes, flushed, and the result line stays the last one.
    Seen red on the code before it (a run printed only its last line):
      FAIL: progress: the lines come in order -> first missing: 'base check passed'
      FAIL: progress: a line is out while the first worker still works -> got []"""
    w = world()
    r = w.run(root=root)
    lines = r.stdout.splitlines()
    m = line_of(r)
    S.ok("progress: the run is done and its result line is the last", bool(m) and m.group(2) == "done" and LINE.match(lines[-1]) is not None, "got %r %r" % (r.stdout[-300:], r.stderr[-200:]))
    S.eq("progress: the lines come in order -> first missing", in_order(lines, [
        r"base check passed", r"worker T1 started", r"worker T1 done", r"worker T2 started", r"worker T2 done", r"wave 1 merged", r"worker T3 started", r"worker T3 done",
        r"gate started", r"gate passed", r"wave 2 merged", r"review started", r"worker r1 started", r"worker r1 done", r"review findings", r"run \S+ done"]), None)
    S.ok("progress: each line is one plain line (no escape codes, no carriage returns)", all("\x1b" not in x and "\r" not in x for x in r.stdout.splitlines()), "got %r" % r.stdout[:200])
    S.ok("progress: a started line names the unit and the role", any(re.search(r"worker T1 started.*executor", x) for x in lines), "got %r" % lines[:6])
    titles = [(c["start"]["unit"], c["start"].get("title")) for c in w.calls() if c.get("start")]
    S.ok("progress: every worker-start carries a readable --task-title naming part, unit and role",
         bool(titles) and all(isinstance(t, str) and "01-alpha" in t and u in t for u, t in titles), "got %r" % titles)
    w2 = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "later"}})
    p = start_run(w2, root, FWX_RUN_LIMIT_S="60")
    live = reader(p)
    end = time.time() + 20
    while time.time() < end and not any("worker T1 started" in x for x in live):
        time.sleep(0.05)
    S.ok("progress: a line is out while the first worker still works -> got %r" % live[:3], p.poll() is None and any("worker T1 started" in x for x in live))
    helpers.write(w2.dir, "go-T1", "")
    try:
        p.wait(timeout=60)
    except subprocess.TimeoutExpired:
        kill_group(p)
    time.sleep(0.3)  # the reader thread drains the pipe
    S.ok("progress: the run still ends done", bool(live) and bool(LINE.match(live[-1])) and LINE.match(live[-1]).group(2) == "done", "got %r" % live[-3:])
    w3 = world(tasks=[task("T1", 1, ["src/a.py"])], recipe=(BAD,), behave={"units": {"T1": {"mode": "ok", "files": {"src/a.py": "a1\n", "BAD": "1\n"}}, "fix-1": {"mode": "ok", "files": {"BAD": None}}}})
    r3 = w3.run(root=root)
    S.eq("progress: a red gate says so, then the fixer starts and the gate passes -> first missing", in_order(r3.stdout.splitlines(), [
        r"gate started", r"gate failed", r"worker fix-1 started", r"worker fix-1 done", r"gate started", r"gate passed"]), None)
    f = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "failed-report"}})
    rf = f.run(root=root)
    S.ok("progress: a worker that failed says failed", any(re.search(r"worker T1 failed", x) for x in rf.stdout.splitlines()), "got %r" % rf.stdout[-300:])
    S.ok("progress: the failed run's last line is its result", bool(line_of(rf)) and line_of(rf).group(2) == "failed", "got %r" % rf.stdout[-200:])


def case_own_terminal(root, S):
    """Run inside an Orca terminal (ORCA_TERMINAL_HANDLE set), `fwx wave run` uses that terminal as the sender and creates none; the run never closes
    a terminal it did not create, however it ends. Without the variable it makes and closes its own, as before (case_terminal).
    Seen red on the code before it:
      FAIL: own terminal (success): no terminal was created -> got ['term_1'] ... """
    mine = {"term_ext": {"title": "the owner's shell", "worktree": "path:elsewhere", "open": True}}
    for name, behave, status in (("success", {}, "done"), ("failure", {"units": {"T1": "failed-report"}}, "failed"), ("raised error", {"units": {"T1": "showfail"}}, "failed")):
        w = world(tasks=[task("T1", 1, ["src/a.py"])], behave=behave)
        helpers.write(w.dir, "state.json", json.dumps({"repos": [], "runs": 0, "n": 0, "dispatches": {}, "launches": {}, "terminals": mine, "n_terms": 7}))
        r = w.run(root=root, ORCA_TERMINAL_HANDLE="term_ext")
        m = line_of(r)
        S.ok("own terminal (%s): the run ends %s" % (name, status), bool(m) and m.group(2) == status, "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
        calls = w.calls()
        made = [c["terminal"] for c in calls if c["argv"][:2] == ["terminal", "create"]]
        S.eq("own terminal (%s): no terminal was created -> got %r" % (name, made), made, [])
        sent = [c["sender"] for c in calls if c["argv"][:2] == ["orchestration", "run-create"] and "sender" in c]
        S.eq("own terminal (%s): run-create names the terminal of the environment" % name, sent, ["term_ext"])
        starts = [c["start"]["sender"] for c in calls if c["argv"][:2] == ["orchestration", "worker-start"] and "start" in c]
        S.ok("own terminal (%s): every worker-start names it" % name, bool(starts) and set(starts) == {"term_ext"}, "got %r" % starts)
        closed = [c for c in calls if c["argv"][:2] == ["terminal", "close"]]
        S.eq("own terminal (%s): no terminal was closed -> got %r" % (name, [c["argv"] for c in closed]), closed, [])
        S.ok("own terminal (%s): the owner's terminal is still open" % name, w.terminals().get("term_ext", {}).get("open") is True, "got %r" % w.terminals())
        S.ok("own terminal (%s): the three session variables are still stripped from every call" % name, all(not any(c["env"].values()) for c in calls))
        if m:
            S.ok("own terminal (%s): the state no longer holds a terminal" % name, not w.state(m.group(1)).get("terminal"), "got %r" % w.state(m.group(1)).get("terminal"))
    w = world(tasks=[task("T1", 1, ["src/a.py"])])
    r = w.run(root=root)
    calls = w.calls()
    S.eq("own terminal: without the variable one terminal is created and then closed", ([c["argv"][:2] for c in calls if c["argv"][:2] in (["terminal", "create"], ["terminal", "close"])]),
         [["terminal", "create"], ["terminal", "close"]])
    # Non-PTY structured worker handle or stale/closed handle must NOT be adopted: fall back to terminal_create.
    # Seen red before validating ORCA_TERMINAL_HANDLE:
    #   FAIL: own terminal (structworker): falls back to a created terminal and ends done: exit 1, ... terminal_not_found: sender structworker_deadbeef is not a live terminal
    #   FAIL: own terminal (closed): falls back to a created terminal and ends done: exit 1, ... terminal_not_found: sender term_gone is not a live terminal
    for label, handle in (("structworker", "structworker_deadbeef"), ("closed", "term_gone")):
        w = world(tasks=[task("T1", 1, ["src/a.py"])])
        r = w.run(root=root, ORCA_TERMINAL_HANDLE=handle)
        m = line_of(r)
        S.ok("own terminal (%s): falls back to a created terminal and ends done" % label, bool(m) and m.group(2) == "done" and r.returncode == 0,
             "exit %d, got %r %r" % (r.returncode, r.stdout[-240:], r.stderr[-200:]))
        made = [c["terminal"] for c in w.calls() if c["argv"][:2] == ["terminal", "create"]]
        S.eq("own terminal (%s): created its own terminal instead of adopting %s" % (label, handle), len(made), 1)
        sent = [c["sender"] for c in w.calls() if c["argv"][:2] == ["orchestration", "run-create"] and "sender" in c]
        S.eq("own terminal (%s): run-create used the created terminal" % label, sent, made)


def case_fenced(root, S):
    """The owner closes the run's sender terminal mid-run (live, run 10-nested-repos-f97847b-3: `worker-start failed (exit 1): consumer_fenced`). Before each
    worker-start and on OrcaError in steer/announce/launch, a gone sender ends the run needs-owner (exit 3) naming the terminal and the resume command,
    leaves its state active, and `--resume` makes a new terminal and a new Orca run, then carries on.
    Seen red on the code before it:
      FAIL: fenced: the run stops needs-owner naming its closed terminal: got 'run <id> failed: orca: orca orchestration worker-start failed (exit 1): consumer_fenced: worker-start needs the coordinator bound to the Run ...'
      FAIL: fenced: exit 3 -> exit 1
      FAIL: fenced (orchestrator): the run stops needs-owner naming its closed terminal: got '... failed: orca: orca orchestration check failed (exit 1): terminal_not_found: no live terminal term_1 (1 worktree kept)'"""
    for label, extra in (("plain", ()), ("orchestrator", ("--orchestrator", ORCH))):
        w = world(tasks=[task("T1", 1, ["src/a.py"]), task("T2", 2, ["src/b.py"])], behave={"close_sender_after": 1})
        r = w.run(*extra, root=root)
        m = re.search(r"run (\S+) needs-owner: the run's terminal (\S+) was closed; resume with `fwx wave run --resume (\S+)`\Z", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
        S.ok("fenced (%s): the run stops needs-owner naming its closed terminal" % label, bool(m) and m.group(1) == m.group(3) and m.group(2) in w.terminals(), "got %r %r" % (r.stdout[-300:], r.stderr[-200:]))
        S.eq("fenced (%s): exit 3 -> exit %d" % (label, r.returncode), r.returncode, 3)
        S.ok("fenced (%s): no raw consumer_fenced in the output" % label, "consumer_fenced" not in r.stdout + r.stderr, "got %r" % (r.stdout[-300:] + r.stderr[-300:]))
        S.eq("fenced (%s): only T1 was started" % label, units(w), ["T1"])
        if not m:
            continue
        run = m.group(1)
        S.eq("fenced (%s): the state stays active, so --resume is allowed" % label, w.state(run)["state"], "active")
        del w.behave["close_sender_after"]
        w.set_behave()
        r2 = subprocess.run(w.argv(root, "--resume", run, *extra), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
        m2 = line_of(r2)
        S.ok("fenced (%s): the resume goes on to done" % label, bool(m2) and m2.group(2) == "done", "got %r %r" % (r2.stdout[-300:], r2.stderr[-300:]))
        S.eq("fenced (%s): the resume started T2 and the reviewer, not T1 again" % label, units(w), ["T1", "T2", "r1"])
        S.eq("fenced (%s): the resume made a new terminal and a new Orca run" % label, (len(w.terminals()), len([c for c in w.calls() if c["argv"][:2] == ["orchestration", "run-create"]])), (2, 2))
        S.ok("fenced (%s): the new terminal is closed at the end" % label, not any(t["open"] for t in w.terminals().values()), "terminals %r" % w.terminals())


def case_signals(root, S):
    """The driver killed by SIGTERM or SIGHUP (the owner closes the Orca terminal it borrows) or SIGINT ends through the path an exception takes: its workers are stopped and
    released, its made terminal closed, the run recorded `failed` with the signal named (state `failed`, `result.interrupted` the signal: the one failed run
    `--resume` takes), exit 1; the resume starts the cut worker's task again under a new worktree and goes on to done. Hackathon-ready research, run-failures G, gap 2
    (run 10-nested-repos-f97847b-4). Seen red on the code before it (the signal killed the driver at once):
      FAIL: SIGTERM: the run says failed and names the signal: got 'base check passed at <sha> ... worker T1 started (executor, sonnet)' (no result line)
      FAIL: SIGTERM: exit 1, no traceback: got (-15, False), want (1, False)
      FAIL: SIGTERM: the state is no longer active: got 'active': got 'active', want 'failed'
      FAIL: SIGTERM: the worker was stopped and released: got ['ctx_1'] still open: got ['ctx_1'], want []
      FAIL: SIGTERM: its made terminal is closed: got terminals {'term_1': {... 'open': True}}
      FAIL: SIGTERM: the resume started the cut task again and then the reviewer: got ['T1', 'r1'], want ['T1', 'T1', 'r1']
    SIGHUP the same (exit -1); SIGINT: exit -2 with a KeyboardInterrupt traceback and the state still `active` (its workers and terminal were released by `finish`).
    Gemini review of PR 270, item 5: FAIL: SIGTERM: `wave list` marks the run interrupted: got '<run> part=01-alpha branch=phase failed pid=<pid> dead workers=0/1 step=wave 1'
    Controls (MUTANTS): the handler not installed, the cut worker not marked, and the resume check not knowing an interrupted run, each red on this case."""
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "later"}})
        p = start_run(w, root, FWX_RUN_LIMIT_S="60")
        wait_for(lambda: p.poll() is not None or (w.runs() and any(x.get("dispatch") for x in w.state(w.runs()[0])["workers"].values())))
        S.eq("%s: the run started T1 and is running" % name, (units(w), p.poll()), (["T1"], None))
        os.kill(p.pid, getattr(signal, name))
        r = finish_run(p)
        m = line_of(r)
        S.ok("%s: the run says failed and names the signal: got %r" % (name, r.stdout[-200:]), bool(m) and m.group(2) == "failed" and name in m.group(3))
        S.eq("%s: exit 1, no traceback" % name, (r.returncode, "Traceback" in r.stderr), (1, False))
        run = w.runs()[0] if w.runs() else ""
        if not run:
            continue
        st = w.state(run)
        S.eq("%s: the state is no longer active: got %r" % (name, st["state"]), st["state"], "failed")
        S.eq("%s: the result names the signal" % name, (st.get("result") or {}).get("interrupted"), name)
        S.eq("%s: the worker was stopped and released: got %r still open" % (name, [k for k, d in w.dispatches().items() if not d["released"]]),
             [k for k, d in w.dispatches().items() if not d["released"]], [])
        S.ok("%s: its made terminal is closed: got terminals %r" % (name, w.terminals()), not any(t["open"] for t in w.terminals().values()))
        S.ok("%s: the cut worker's worktree is kept for the resume: got %r" % (name, w.worktrees()), any(x.endswith("-T1") for x in w.worktrees()))
        listed = subprocess.run([sys.executable, os.path.join(root, "bin", "fwx"), "wave", "list"], cwd=w.cwd, env=w.env(), capture_output=True, text=True).stdout
        S.ok("%s: `wave list` marks the run interrupted: got %r" % (name, listed), "interrupted=%s" % name in listed)
        helpers.write(w.dir, "go-T1", "")
        r2 = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
        m2 = line_of(r2)
        S.ok("%s: --resume takes the run up and it is done: got %r %r" % (name, r2.stdout[-200:], r2.stderr[-200:]), bool(m2) and m2.group(2) == "done" and m2.group(1) == run)
        S.eq("%s: the resume started the cut task again and then the reviewer" % name, units(w), ["T1", "T1", "r1"])
        S.ok("%s: every dispatch is released after the resume" % name, all(d["released"] for d in w.dispatches().values()))
        S.eq("%s: the resumed run ended done" % name, w.state(run)["state"], "done")
        r3 = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=60)
        S.eq("%s: a finished run is not resumable again" % name, r3.returncode, 2)


def gone(pid, secs=10):
    return bool(wait_for(lambda: not os.path.exists("/proc/%d" % pid), secs))


def case_signals_merge(root, S):
    """A signal while the driver's `wave merge` runs the quick checks (Gemini review of PR 270, items 1 and 3). The merge's check group must die with it, the merged
    worker's branch and worktree must still be there (a merge removed them before its checks, so the replay on `--resume` found `no branch`), and the resume goes on to done.
    Seen red on the code before it:
      FAIL: signal in the quick check: the check is gone, not an orphan: got pid <pid> still running
      FAIL: signal in the quick check: the merged branch and its worktree are kept for the resume: got (False, False)
      FAIL: signal in the quick check: --resume takes the run up and it is done: got '... run <id> failed: fwx wave merge exited 2 with no JSON: fwx wave merge: no branch worktree-<id>-T1'
    Controls (MUTANTS): the branches removed before the checks, no unwinding in run_check, and the child of the driver not asked to stop."""
    base = helpers.mkdtemp("fwx-sigmerge-")
    pidfile, go = os.path.join(base, "pid"), os.path.join(base, "go")
    w = world(tasks=[task("T1", 1, ["src/a.py"])], quick=["echo $$ > %s; while [ ! -f %s ]; do sleep 0.1; done" % (pidfile, go)])
    p = start_run(w, root)
    S.ok("signal in the quick check: the quick check started", bool(wait_for(lambda: os.path.exists(pidfile) or p.poll() is not None, 60)) and os.path.exists(pidfile))
    pid = int(open(pidfile).read()) if os.path.exists(pidfile) and open(pidfile).read().strip() else 0
    os.kill(p.pid, signal.SIGTERM)
    r = finish_run(p)
    m = line_of(r)
    S.ok("signal in the quick check: the run says failed and names the signal: got %r %r" % (r.stdout[-200:], r.stderr[-200:]), bool(m) and m.group(2) == "failed" and "SIGTERM" in m.group(3))
    S.ok("signal in the quick check: the check is gone, not an orphan: got pid %d still running" % pid, bool(pid) and gone(pid))
    run = w.runs()[0] if w.runs() else ""
    branch = "worktree-%s-T1" % run
    kept = (helpers.git(w.repo, "branch", "--list", branch).strip() != "", any(x.endswith("-T1") for x in w.worktrees()))
    S.eq("signal in the quick check: the merged branch and its worktree are kept for the resume", kept, (True, True))
    helpers.write(base, "go", "")
    r2 = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
    m2 = line_of(r2)
    S.ok("signal in the quick check: --resume takes the run up and it is done: got %r %r" % (r2.stdout[-300:], r2.stderr[-200:]), bool(m2) and m2.group(2) == "done")
    S.eq("signal in the quick check: the resume did not start T1 again", units(w), ["T1", "r1"])
    S.eq("signal in the quick check: no worktree of the run is left after the resume", [x for x in w.worktrees() if os.path.realpath(x) not in (os.path.realpath(w.repo), os.path.realpath(w.cwd))], [])


def case_signals_release(root, S):
    """The release of a cut worker failed (Orca unreachable as the terminal closed): the resume must not start a second worker beside the live one (Gemini review of PR 270,
    item 4): it releases the cut one first and, when it cannot, ends failed naming it and starts nobody. Seen red on the code before it:
      FAIL: release failed: the resume ends failed naming the worker that could not be released: got 'run <id> failed: T1 ran past its limit of 2 s and was stopped'
      FAIL: release failed: no second worker beside the live one: got ['T1', 'T1'], want ['T1']"""
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "later"}, "release_fail": ["T1"]})
    p = start_run(w, root, FWX_RUN_LIMIT_S="60")
    wait_for(lambda: p.poll() is not None or (w.runs() and any(x.get("dispatch") for x in w.state(w.runs()[0])["workers"].values())))
    os.kill(p.pid, signal.SIGTERM)
    finish_run(p)
    run = w.runs()[0] if w.runs() else ""
    st = w.state(run)
    S.eq("release failed: the run is recorded interrupted with its worker unreleased", ((st.get("result") or {}).get("interrupted"), [x["released"] for x in st["workers"].values()]), ("SIGTERM", [False]))
    r2 = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
    m2 = line_of(r2)
    S.ok("release failed: the resume ends failed naming the worker that could not be released: got %r" % r2.stdout[-200:], bool(m2) and m2.group(2) == "failed" and "could not be released" in m2.group(3))
    S.eq("release failed: no second worker beside the live one", units(w), ["T1"])


def case_signals_start(root, S):
    """A signal between the worktree made for a worker and Orca's answer to `worker-start` (Gemini review of PR 270, item 6): the worker is recorded before the start, so
    the resume knows the worktree and its branch and starts the task again as the next attempt instead of crashing on `branch ... already exists`. Seen red on the code before it:
      FAIL: start cut: the worker is recorded before Orca answers: got 0 workers in the state: got 0, want 1
      FAIL: start cut: the worker's clean worktree is not swept by the cut run (the resume needs it): got [<repo>, <phase worktree>]"""
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"start_hang": ["T1"]})
    p = start_run(w, root)
    S.ok("start cut: the driver is in worker-start", bool(wait_for(lambda: os.path.exists(os.path.join(w.dir, "hanging-T1")) or p.poll() is not None, 60)))
    os.kill(p.pid, signal.SIGTERM)
    r = finish_run(p)
    run = w.runs()[0] if w.runs() else ""
    S.ok("start cut: the run says failed and names the signal: got %r" % r.stdout[-200:], bool(line_of(r)) and "SIGTERM" in line_of(r).group(3))
    S.eq("start cut: the worker is recorded before Orca answers: got %d workers in the state" % len(w.state(run)["workers"]), len(w.state(run)["workers"]), 1)
    S.ok("start cut: the worker's clean worktree is not swept by the cut run (the resume needs it): got %r" % w.worktrees(), any(x.endswith("-T1") for x in w.worktrees()))
    del w.behave["start_hang"]
    w.set_behave()
    os.remove(os.path.join(w.dir, "hanging-T1"))
    r2 = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
    m2 = line_of(r2)
    S.ok("start cut: --resume starts the task again and it is done: got %r %r" % (r2.stdout[-300:], r2.stderr[-200:]), bool(m2) and m2.group(2) == "done")
    S.eq("start cut: the task was started once, as the next attempt", units(w), ["T1", "r1"])


# ---------------------------------------------------------------------------------------------------------------------- orchestrator steering

ORCH = "orca_session_id:11111111-2222-3333-4444-555555555555"
NEW_ORCH = "orca_session_id:99999999-8888-7777-6666-555555555555"


def orchestra(w, *args):
    """A call to the fake orca as the orchestrator makes it: from its own chat (session variables in the environment, no `--from`)."""
    return subprocess.run([os.path.join(w.bin, "orca")] + list(args) + ["--json"], env=w.env(), capture_output=True, text=True, timeout=60)


def sent(w, to):
    """What the run sent to `to`: [{to, type, subject, body, sender}] in order."""
    return [dict(c["send"], sender=c.get("sender")) for c in w.calls() if c.get("send") and c["send"]["to"] == to and not c.get("refused")]


def wait_for(pred, secs=20):
    end = time.time() + secs
    while time.time() < end:
        got = pred()
        if got:
            return got
        time.sleep(0.05)
    return None


def start_run(w, root, *flags, **env):
    p = subprocess.Popen(w.argv(root, *flags), cwd=w.cwd, env=w.env(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    w.procs.append(p)
    return p


def kill_group(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)  # the whole group: a fake orca call in flight would save a stale state.json after it
    except ProcessLookupError:
        pass
    p.wait()


def finish_run(p, timeout=60):
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(p)
        out, err = p.communicate()
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)


def case_steer(root, S):
    """A worker's question reaches the orchestrator once, the orchestrator's answer to the worker's dispatch wakes it, and while the question is open the worker is
    neither stopped as idle nor past its limit (the fake's limit is 2.5 s, its idle window 0.4 s, and the question stays open 3.2 s). Orca 1.4.273, live probe.
    Seen red on the code before `--orchestrator` existed (`wave run` took no such flag):
      FAIL: steer: the run started and sent the question -> no send to orca_session_id:..., exit 2
      FAIL: a question reaches the orchestrator once -> 0 sends over many ticks"""
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": {"mode": "ask", "question": "which colour?\nblue or red"}}})
    p = start_run(w, root, "--orchestrator", ORCH)
    wait_for(lambda: sent(w, ORCH) or p.poll() is not None)
    S.ok("steer: the run started and sent the question -> %s" % (sent(w, ORCH) or "no send to %s, exit %r" % (ORCH, p.poll())), bool(sent(w, ORCH)))
    time.sleep(LIMIT + 0.7)
    S.ok("an open question pauses the idle stop and the limit: the run still waits after %.1f s -> exit %r" % (LIMIT + 0.7, p.poll()), p.poll() is None)
    answered = time.time()
    r = orchestra(w, "orchestration", "send", "--to", "dispatch:ctx_1", "--subject", "Answer", "--body", "blue")
    S.eq("steer: the orchestrator's send to the dispatch is accepted", r.returncode, 0)
    r = finish_run(p)
    m = line_of(r)
    S.ok("steer: the run is done after the answer", bool(m) and m.group(2) == "done" and r.returncode == 0, "exit %d, got %r %r" % (r.returncode, r.stdout[-300:], r.stderr[-300:]))
    forwards = [x for x in sent(w, ORCH) if "which colour?" in x["subject"]]
    S.eq("a question reaches the orchestrator once -> %d sends over many ticks" % len(forwards), len(forwards), 1)
    if forwards:
        f = forwards[0]
        S.eq("steer: the subject names the part, the unit and the dispatch, then the question on one line", f["subject"], "[%s T1 dispatch:ctx_1] which colour? blue or red" % os.path.basename(w.part))
        S.eq("steer: sent as a status message from the run's terminal", (f["type"], f["sender"]), ("status", "term_1"))
        S.ok("steer: the body has the whole question and the exact command to answer", "which colour?\nblue or red" in f["body"]
             and 'orca orchestration send --to dispatch:ctx_1 --subject "Answer" --body "' in f["body"], "body %r" % f["body"])
    stops = [c for c in w.calls() if c.get("dispatch") == "ctx_1" and c["argv"][1] == "worker-stop" and c["t"] < answered]
    S.eq("an open question pauses the idle stop -> worker-stop calls before the answer", len(stops), 0)
    S.eq("steer: the worker was woken with the answer and not started again", ((w.dispatches().get("ctx_1") or {}).get("answered"), units(w)), ("blue", ["T1", "r1"]))
    S.eq("steer: its work was merged", helpers.git(w.cwd, "log", "--format=%s", "--grep", "work T1").strip(), "work T1")
    if m:
        S.eq("steer: the state holds the one forwarded message", len(w.state(m.group(1)).get("forwarded") or []), 1)
    S.ok("steer: every dispatch is released", all(d["released"] for d in w.dispatches().values()))


def case_steer_resume(root, S):
    """A question forwarded before the run was cut is not forwarded again when the run is resumed, and `--resume R --orchestrator NEW` refreshes the address the
    rest goes to. Seen red on the code before `--orchestrator` existed: FAIL: steer resume: the first run forwarded the question"""
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": {"mode": "ask", "question": "which colour?"}}})
    p = start_run(w, root, "--orchestrator", ORCH, FWX_RUN_LIMIT_S="60")
    # the id is recorded just after the send exits 0 (at-least-once: a kill in between would send again), so the cut waits for the record
    S.ok("steer resume: the first run forwarded the question and recorded it", bool(wait_for(lambda: (w.runs() and w.state(w.runs()[0]).get("forwarded")) or p.poll() is not None)
                                                                                   and sent(w, ORCH)))
    kill_group(p)
    run = w.runs()[0] if w.runs() else ""
    r = subprocess.Popen(w.argv(root, "--resume", run, "--orchestrator", NEW_ORCH), cwd=w.cwd, env=w.env(FWX_RUN_LIMIT_S="60"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    w.procs.append(r)
    time.sleep(1.0)  # ticks of the resumed run: its peek sees the same unread question again
    orchestra(w, "orchestration", "send", "--to", "dispatch:ctx_1", "--subject", "Answer", "--body", "blue")
    res = finish_run(r)
    m = line_of(res)
    S.ok("steer resume: the resumed run is done", bool(m) and m.group(2) == "done", "exit %d, got %r %r" % (res.returncode, res.stdout[-300:], res.stderr[-300:]))
    S.eq("a question reaches the orchestrator once across a resume -> sends of the question", len([x for x in sent(w, ORCH) + sent(w, NEW_ORCH) if "which colour?" in x["subject"]]), 1)
    S.eq("steer resume: the final line went to the refreshed address", [x["subject"] for x in sent(w, NEW_ORCH) if x["subject"].endswith(" done")],
         ["[%s] run %s done" % (os.path.basename(w.part), run)])
    S.eq("steer resume: the refreshed address is in the saved flags", w.state(run)["flags"].get("orchestrator") if run else None, NEW_ORCH)


def case_steer_lines(root, S):
    """Routine `worker_done` mail never reaches the orchestrator (the peek asks for `question,escalation` only and Orca keeps the rest unread); it gets one line per wave's
    merge and one final line sent before the run's terminal is closed; executors are told to `ask`, reviewers are not.
    Seen red before the code: FAIL: lines: the run is done -> got 'usage: fwx wave run ...'
    Control: the peek types read `question,escalation,worker_done` (MUTANTS): FAIL: routine worker_done never reaches the orchestrator -> ['done T1', ...]"""
    w = world()
    r = w.run("--orchestrator", ORCH, root=root)
    m = line_of(r)
    S.ok("lines: the run is done -> %s %s" % (r.stdout[-200:], r.stderr[-200:]), bool(m) and m.group(2) == "done")
    if not m:
        return
    run, part = m.group(1), os.path.basename(w.part)
    heads = [x["result"]["head"][:8] for x in w.steps(run, "integrate")]
    got = sent(w, ORCH)
    S.eq("lines: the orchestrator got the wave lines and the final line, nothing else", [(x["subject"], (x["body"] or "").rstrip("\n")) for x in got],
         [("[%s] wave 1/2 merged" % part, "2/2 tasks -> %s" % heads[0]), ("[%s] wave 2/2 merged" % part, "1/1 tasks -> %s" % heads[1]),
          ("[%s] run %s done" % (part, run), "the gate and the review passed on %s\n\nDetails: fwx wave --run %s --json" % (heads[-1], run))])
    dup = [x["subject"] for x in got if (x["body"] or "").strip() == x["subject"].strip() or x["subject"] in (x["body"] or "")]
    S.ok("lines: no status mail repeats its subject in its body (Orca shows both as one duplicated card) -> %s" % dup, not dup)
    S.ok("lines: no subject is a long dump (at most 80 characters) -> %s" % [len(x["subject"]) for x in got], all(len(x["subject"]) <= 80 for x in got))
    S.ok("lines: all of them are status messages", all(x["type"] == "status" for x in got), "types %r" % [x["type"] for x in got])
    leaked = [x["subject"] for x in got if "worker_done" in (x["body"] or "") + x["subject"] or x["subject"].startswith("done ")]
    S.ok("routine worker_done never reaches the orchestrator -> %s" % leaked, not leaked)
    held = [x for x in w.state_json().get("inbox", []) if x["type"] == "worker_done" and not x["handled"]]
    S.ok("lines: the routine mail was in the run's inbox, unread (the peek did not consume it) -> %d held" % len(held), len(held) >= 4)
    peeks = [c["check"] for c in w.calls() if "check" in c]
    S.ok("lines: every tick is a peek for question and escalation only -> %r" % peeks[:2], bool(peeks) and all(x["peek"] and x["types"] == "question,escalation" for x in peeks))
    calls = w.calls()
    last = max([i for i, c in enumerate(calls) if c.get("send") and c["send"]["to"] == ORCH] or [-1])
    closed = next((i for i, c in enumerate(calls) if c["argv"][:2] == ["terminal", "close"]), -1)
    S.ok("lines: the final line is sent before the run's terminal is closed -> last send at call %d, close at %d" % (last, closed), 0 <= last < closed)
    starts = w.starts()
    S.eq("lines: every executor is told to ask, no reviewer is", [(x["unit"], "This run has an orchestrator" in x["spec"]) for x in starts], [("T1", True), ("T2", True), ("T3", True), ("r1", False)])
    S.ok("lines: the executor's spec names the `ask` command", bool(starts) and "`ask` command from your Orca preamble" in starts[0]["spec"])
    w = world()
    w.put_done(tasks=("T1",), findings=("X1",))
    r = w.run("--revert", "X1", "--orchestrator", ORCH, root=root)
    m = line_of(r)
    S.ok("lines: --revert with --orchestrator is done", bool(m) and m.group(2) == "done" and r.returncode == 0, "got %r %r" % (r.stdout[-200:], r.stderr[-200:]))
    if m:
        got_rev = sent(w, ORCH)
        S.eq("lines: --revert with --orchestrator sends its final status line and closes its terminal",
             ([x["subject"] for x in got_rev], any(t["open"] for t in w.terminals().values())),
             (["[%s] run %s done" % (os.path.basename(w.part), m.group(1))], False))


def case_steer_off(root, S):
    """Without `--orchestrator` nothing is peeked or sent and executors are not told to ask; with `--plane factory`, `--unattended` or a malformed address the flag is refused (exit 2,
    no Orca call), on a resumed factory run too. The `off:` checks describe today's behaviour and passed on the old code; the refusals passed on exit code alone there (a usage
    error is exit 2 too), and went red on what they say, seen on the code before `--orchestrator` existed:
      FAIL: refusals: --plane factory: stderr names the orchestrator: stderr 'usage: fwx wave run --part-dir D --plane session|factory ...'
    Control: the ask line is added whether or not there is an orchestrator (MUTANTS): FAIL: off: no executor is told to ask -> 4 starts"""
    w = world()
    r = w.run(root=root)
    S.eq("off: the run is done", (r.returncode, bool(line_of(r))), (0, True))
    kinds = [c["argv"][:2] for c in w.calls() if c["argv"][:2] in (["orchestration", "check"], ["orchestration", "send"])]
    S.eq("off: no peek and no send", kinds, [])
    S.ok("off: no executor is told to ask -> %d starts" % len(w.starts()),
         all("This run has an orchestrator" not in x["spec"] and "`ask` command from your Orca preamble" not in x["spec"] for x in w.starts()) and len(w.starts()) == 4)
    for label, flags, expect in (("--plane factory", [], "factory or unattended"), ("--unattended", ["--unattended"], "factory or unattended"),
                                 ("a malformed address", [], "orca_session_id:")):
        w = world()
        argv = w.argv(root, "--orchestrator", "chat-1" if label == "a malformed address" else ORCH, *flags)
        if label == "--plane factory":
            argv[argv.index("session")] = "factory"
        r = subprocess.run(argv, cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=60)
        S.eq("refusals: %s --orchestrator: exit 2, no Orca call" % label, (r.returncode, w.calls()), (2, []))
        S.ok("refusals: %s: stderr explains the refusal (not usage)" % label,
             "usage:" not in r.stderr and "orchestrator" in r.stderr and expect in r.stderr, "stderr %r" % r.stderr[-300:])
    w = world()
    name = "01-alpha-0000000-8"
    helpers.write(os.path.join(w.common, "fwx", "runs", name), "state.json", json.dumps({
        "run": name, "branch": "phase", "part_dir": w.part, "pid": 2 ** 22 + 1, "state": "active", "step": "wave 1", "workers": {}, "worktrees": [], "steps": [],
        "flags": {"control": None}, "args": {"plane": "factory", "unattended": True}}))
    r = subprocess.run(w.argv(root, "--resume", name, "--orchestrator", ORCH), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=60)
    S.eq("refusals: resuming a factory run with --orchestrator: exit 2, the orchestrator named, no Orca call", (r.returncode, "orchestrator" in r.stderr, w.calls()), (2, True, []))


def case_steer_unreachable(root, S):
    """When the orchestrator cannot be reached the run stops needs-owner naming its address, and the unsent question is not recorded as forwarded.
    Seen red before the code: FAIL: unreachable: needs-owner naming the address, exit 3 -> exit 2, got ''"""
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": {"mode": "ask", "question": "which colour?"}}, "status_fail": True})
    r = w.run("--orchestrator", ORCH, root=root)
    m = line_of(r)
    S.ok("unreachable: needs-owner naming the address, exit 3 -> exit %d, got %r %r" % (r.returncode, r.stdout[-200:], r.stderr[-200:]),
         bool(m) and m.group(2) == "needs-owner" and ORCH in m.group(3) and r.returncode == 3)
    if m:
        S.eq("unreachable: nothing recorded as forwarded", w.state(m.group(1)).get("forwarded") or {}, {})
    S.ok("unreachable: the worker is released and the terminal closed", bool(w.dispatches()) and all(d["released"] for d in w.dispatches().values()) and not any(t["open"] for t in w.terminals().values()))


def case_fake_orca(root, S):
    """The fake's own contract for steering (Orca 1.4.273, live probe): peek filters by `--types` and never consumes, `--peek` with `--all` is refused, a plain check
    consumes, `--type escalation` from a run's terminal is refused (`sender_not_assignee`) and `--type status` to an `orca_session_id:` address lands in the chat.
    Seen red on the fake before it knew `check`: FAIL: fake: peek returns the question and the escalation, not the worker_done -> got []"""
    w = world()
    inbox = [{"id": "msg_%d" % i, "run": "run_1", "type": t, "handled": False, "body": "b", "subject": "s", "from": "f", "to": "run:run_1", "payload": {}}
             for i, t in enumerate(("worker_done", "question", "escalation"), 1)]
    helpers.write(w.dir, "state.json", json.dumps({"repos": [], "runs": 1, "n": 0, "dispatches": {}, "launches": {}, "msgs": 3, "inbox": inbox,
                                                   "terminals": {"term_1": {"title": "t", "worktree": "path:x", "open": True}}}))

    def call(*args):
        r = subprocess.run([os.path.join(w.bin, "orca")] + list(args) + ["--json"], env=w.env(), capture_output=True, text=True, timeout=60)
        try:
            return r.returncode, json.loads(r.stdout)
        except ValueError:
            return r.returncode, {"raw": r.stdout}

    def ids(body):
        return [x["id"] for x in body.get("result", {}).get("messages", [])]
    check = ("orchestration", "check", "--terminal", "term_1", "--run", "run_1")
    S.eq("fake: peek returns the question and the escalation, not the worker_done", ids(call(*check, "--peek", "--types", "question,escalation")[1]), ["msg_2", "msg_3"])
    S.eq("fake: a peek consumed nothing", len(ids(call(*check, "--peek")[1])), 3)
    rc, body = call(*check, "--peek", "--all")
    S.eq("fake: --peek with --all is refused", (rc, (body.get("error") or {}).get("code")), (1, "invalid_argument"))
    S.eq("fake: a plain check returns the batch and marks it handled", (len(ids(call(*check)[1])), len(ids(call(*check, "--peek")[1]))), (3, 0))
    rc, body = call("orchestration", "send", "--from", "term_1", "--to", ORCH, "--type", "escalation", "--subject", "s", "--body", "b")
    S.eq("fake: an escalation from a run's terminal is refused", (rc, (body.get("error") or {}).get("code")), (1, "sender_not_assignee"))
    rc, body = call("orchestration", "send", "--from", "term_1", "--to", ORCH, "--type", "status", "--subject", "s", "--body", "b")
    S.eq("fake: a status to an orchestrator address is accepted and reaches its chat", (rc, [x["subject"] for x in w.state_json().get("chat", [])]), (0, ["s"]))
    S.eq("orca._messages skips malformed entries instead of dropping the list",
         orca_mod._messages({"messages": [{"id": "m1", "type": "question"}, {"bad": 1}, "junk", None]}),
         [{"id": "m1", "type": "question"}])


def case_steer_asking(root, S):
    """Asking state edges:
    - a transient non-working activity before the worker parks never clears `asking` early (the waiting worker is not stopped as idle);
    - a fast answer between polls (worker never seen parked) does not pause the limit clock forever;
    - a resume after an answer keeps the cleared asking state (persisted in state.json) so the worker's limit still enforces;
    - an unanswered parked worker is bounded (3 * limit) and cannot pause the limit forever.
    Seen red on the code before the fixes:
      FAIL: asking transient: finishes done once answered: exit 1, 'run ... failed: executor did not return: T1 (1 worktree kept)'
      FAIL: asking fast-answer: hanging worker still hits its limit -> exit -9, ''
      FAIL: asking resume-after-answer: poll persisted cleared asking state in state.json: got <ts>, want None
      FAIL: asking resume-after-answer: resumed run enforces the limit -> exit -9, ''
      FAIL: asking bounded: unanswered worker stops past 3x limit -> exit -9, ''"""
    # 1. Transient missing activity while finishing turn before parking must not clear `asking` early.
    pre = [{"state": "running", "stage": "working"}, {"state": "running", "stage": "working", "activity": "working"}]
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": {"mode": "ask", "question": "which one?", "before_park": pre}}})
    p = start_run(w, root, "--orchestrator", ORCH)
    wait_for(lambda: sent(w, ORCH) or p.poll() is not None)
    time.sleep(0.9)  # past idle_s (0.4s) after the two pre-park shows (~0.1s)
    S.ok("asking transient: waiting worker is not stopped as idle after pre-park non-working activity", p.poll() is None, "exit %r" % p.poll())
    orchestra(w, "orchestration", "send", "--to", "dispatch:ctx_1", "--subject", "Answer", "--body", "ok")
    r = finish_run(p, timeout=20)
    m = line_of(r)
    S.ok("asking transient: finishes done once answered", bool(m) and m.group(2) == "done" and r.returncode == 0, "exit %d, %r" % (r.returncode, r.stdout[-200:]))

    # 2. Fast answer between polls (never seen parked): limit clock still stops a hanging worker.
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": {
        "mode": "ask", "question": "fast?", "before_park": [{"state": "running", "stage": "working", "activity": "working"}] * 80, "after_answer": "hang"}}})
    p = start_run(w, root, "--orchestrator", ORCH, FWX_RUN_LIMIT_S="0.8")
    wait_for(lambda: sent(w, ORCH) or p.poll() is not None)
    orchestra(w, "orchestration", "send", "--to", "dispatch:ctx_1", "--subject", "Answer", "--body", "go")
    r = finish_run(p, timeout=3.0)
    m = line_of(r)
    S.ok("asking fast-answer: hanging worker still hits its limit -> exit %d, %r" % (r.returncode, r.stdout[-200:]),
         r.returncode == 1 and bool(m) and m.group(2) == "failed" and "limit" in m.group(3))

    # 3. Resume after an answer: poll persists cleared asking state so the resumed run still enforces the limit.
    # Give pre-kill `p` a generous limit (10s) so `release()` cannot mask an unpersisted `asking` clear; `r2` overrides 1.2s.
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": {"mode": "ask", "question": "resume?", "after_answer": "hang"}}})
    p = start_run(w, root, "--orchestrator", ORCH, FWX_RUN_LIMIT_S="10")
    wait_for(lambda: (w.runs() and w.state(w.runs()[0]).get("forwarded")) or p.poll() is not None)
    run = w.runs()[0] if w.runs() else ""
    wait_for(lambda: (run and w.state(run)["workers"].get("T1/1", {}).get("asked_idle") is True) or p.poll() is not None, secs=5)
    orchestra(w, "orchestration", "send", "--to", "dispatch:ctx_1", "--subject", "Answer", "--body", "go")
    wait_for(lambda: (w.dispatches().get("ctx_1") or {}).get("shows", 0) >= 2 and (w.dispatches().get("ctx_1") or {}).get("mode") == "woken-hang")
    # poll persists the cleared asking state a tick after the woken show; stop waiting if `p` exited early.
    wait_for(lambda: (run and "T1/1" in w.state(run)["workers"] and w.state(run)["workers"]["T1/1"].get("asking") is None) or p.poll() is not None, secs=3)
    saved_after = (w.state(run)["workers"].get("T1/1") or {}) if run else {}
    S.ok("asking resume-after-answer: runner is still alive before kill (release did not mask persistence)", p.poll() is None and not saved_after.get("released"),
         "poll=%r released=%r" % (p.poll(), saved_after.get("released")))
    S.eq("asking resume-after-answer: poll persisted cleared asking state in state.json", saved_after.get("asking"), None)
    kill_group(p)
    r2 = subprocess.Popen(w.argv(root, "--resume", run, "--orchestrator", ORCH), cwd=w.cwd, env=w.env(FWX_RUN_LIMIT_S="1.2"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    w.procs.append(r2)
    res = finish_run(r2, timeout=3.5)
    m = line_of(res)
    S.ok("asking resume-after-answer: resumed run enforces the limit -> exit %d, %r" % (res.returncode, res.stdout[-200:]),
         res.returncode == 1 and bool(m) and m.group(2) == "failed" and "limit" in m.group(3))

    # 4. Stuck-asking parked worker with no answer is bounded (3 * limit), never pauses forever.
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": {"mode": "ask", "question": "anyone there?"}}})
    p = start_run(w, root, "--orchestrator", ORCH, FWX_RUN_LIMIT_S="0.6")
    wait_for(lambda: sent(w, ORCH) or p.poll() is not None)
    time.sleep(0.85)  # past 0.6s limit and 0.4s idle_s: still waiting
    S.ok("asking bounded: still waiting past 1x limit -> exit %r" % p.poll(), p.poll() is None)
    res = finish_run(p, timeout=3.0)
    m = line_of(res)
    S.ok("asking bounded: unanswered worker stops past 3x limit -> exit %d, %r" % (res.returncode, res.stdout[-200:]),
         res.returncode == 1 and bool(m) and m.group(2) == "failed" and "limit" in m.group(3))


def case_reply_grace(root, S):
    """A worker that sends `worker_done` flips `state` to `succeeded` inside the Bash tool call, 1.1-1.8 s before its final reply line lands in the transcript.
    `poll()` waits up to `min(idle_s, 15.0)` while a `succeeded` worker's transcript lacks `REPLY_LINE`, re-reading the transcript before calling `worker-release`;
    a reply already present has zero added latency, and a garbled reply still fails after the grace.
    Seen red on the code before the fix:
      FAIL: reply grace: delayed reply after worker_done finishes done: exit 1, got 'run 01-alpha-4257563-1 failed: executor did not return: T1 (2 worktrees kept)\\n'
      FAIL: reply grace: no relaunch of T1: got ['T1', 'T1'], want ['T1', 'r1']
      FAIL: reply grace: transcript re-read until reply appeared: reads [(7, False)]"""
    w = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": {"mode": "ok", "reply_delay": 1.5}}})
    r = w.run(root=root, FWX_RUN_IDLE_S="3.0", FWX_RUN_LIMIT_S="10")
    m = line_of(r)
    S.ok("reply grace: delayed reply after worker_done finishes done", bool(m) and m.group(2) == "done" and r.returncode == 0,
         "exit %d, got %r %r" % (r.returncode, r.stdout[-240:], r.stderr[-200:]))
    S.eq("reply grace: no relaunch of T1", units(w), ["T1", "r1"])
    calls = w.calls()
    t1_reads = [(i, c.get("reply_ready")) for i, c in enumerate(calls) if c.get("dispatch") == "ctx_1" and c["argv"][:2] == ["orchestration", "worker-read"]]
    t1_rel = [i for i, c in enumerate(calls) if c.get("dispatch") == "ctx_1" and c["argv"][:2] == ["orchestration", "worker-release"]]
    S.ok("reply grace: transcript re-read until reply appeared", len(t1_reads) >= 2 and t1_reads[0][1] is False and t1_reads[-1][1] is True, "reads %r" % t1_reads)
    S.ok("reply grace: worker-release waited until after the reply was read", bool(t1_rel) and bool(t1_reads) and t1_reads[-1][1] is True and t1_rel[0] > t1_reads[-1][0],
         "reads %r, release %r" % (t1_reads, t1_rel))
    r1_did = next((k for k, d in w.dispatches().items() if d["unit"] == "r1"), None)
    r1_reads = [c for c in calls if r1_did and c.get("dispatch") == r1_did and c["argv"][:2] == ["orchestration", "worker-read"]]
    S.eq("reply grace: reply already present adds zero extra polls", len(r1_reads), 1)
    # A worker whose transcript never gets a reply line still fails after the grace, well before the worker limit.
    w2 = world(tasks=[task("T1", 1, ["src/a.py"])], behave={"units": {"T1": "garbled"}})
    r2 = w2.run(root=root, FWX_RUN_IDLE_S="0.4", FWX_RUN_LIMIT_S="5")
    m2 = line_of(r2)
    S.ok("reply grace: garbled reply still fails after the grace",
         r2.returncode == 1 and bool(m2) and m2.group(2) == "failed" and "executor did not return: T1" in m2.group(3),
         "exit %d, got %r %r" % (r2.returncode, r2.stdout[-240:], r2.stderr[-200:]))
    calls2 = w2.calls()
    for did in ("ctx_1", "ctx_2"):
        rt = [c["t"] for c in calls2 if c.get("dispatch") == did and c["argv"][:2] == ["orchestration", "worker-read"]]
        relt = [c["t"] for c in calls2 if c.get("dispatch") == did and c["argv"][:2] == ["orchestration", "worker-release"]]
        S.ok("reply grace: garbled %s waited the grace then released before limit" % did,
             len(rt) >= 2 and bool(relt) and 0.3 <= relt[0] - rt[0] < 2.0,
             "reads=%d, dt=%r" % (len(rt), round(relt[0] - rt[0], 2) if rt and relt else None))
    S.ok("reply grace: garbled dispatches all released", bool(w2.dispatches()) and all(d["released"] for d in w2.dispatches().values()))


CASES = [case_loop, case_failure, case_error, case_gate_red, case_retry, case_conflict, case_fix, case_gate_entry, case_revert, case_security, case_refusals, case_registered,
         case_one_run, case_resume, case_lock, case_release, case_alive, case_settings_mode, case_transcript, case_waiting, case_review_fix, case_terminal, case_terminal_resume, case_discover,
         case_fake_orca, case_steer, case_steer_resume, case_steer_lines, case_steer_off, case_steer_unreachable, case_steer_asking, case_reply_grace,
         case_nested, case_nested_resume, case_progress, case_own_terminal, case_fenced, case_signals, case_signals_merge, case_signals_release, case_signals_start, case_terminal_discover, case_list_json]

def mutant_tree(path, old, new):
    """A copy of the plugin (what `fwx wave run` reads: bin, lib, data, templates, agents) with `old` replaced by `new` in `path`, once."""
    dest = helpers.mkdtemp("fwx-run-mutant-")
    for d in ("bin", "lib", "data", "templates", "agents"):
        if os.path.isdir(os.path.join(ROOT, d)):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(dest, d), ignore=shutil.ignore_patterns("__pycache__"))
    p = os.path.join(dest, path)
    text = open(p, encoding="utf-8").read()
    assert text.count(old) == 1, "control: %r is in %s %d times, want 1" % (old, path, text.count(old))
    open(p, "w", encoding="utf-8").write(text.replace(old, new))
    return dest


MUTANTS = [
    ("the cap read as unlimited", case_loop, "lib/fwx/execute/run.py", "self.cap = args[\"cap\"]", "self.cap = 10 ** 6", "never more open workers than the cap -> 2 open, cap 1"),
    ("cleanup without the run's worktrees", case_loop, "lib/fwx/execute/cleanup.py", "or w[\"path\"] in owned", "or False", "a reviewer worktree with no commit is removed -> kept"),
    ("release with no stop before it", case_loop, "lib/fwx/execute/orca.py", "if state not in SETTLED:", "if False:", "every dispatch is released -> dispatch_inactive"),
    ("a forced removal", case_failure, "lib/fwx/execute/cleanup.py", "if wt[\"branch\"] and not merged(top, wt[\"branch\"]):", "if False:",
     "an executor worktree with unmerged commits stays -> removed"),
    ("the settings copied as they are", case_loop, "lib/fwx/execute/orca.py", "env[\"FORCE_PROMPT_CACHING_5M\"] = \"1\"", "pass",
     "the worker's settings write the cache at 5 minutes -> env has no FORCE_PROMPT_CACHING_5M"),
    ("a start with no base context", case_refusals, "lib/fwx/execute/run.py", 'if not text.strip() and not self.args["revert"]:', "if False:", "no base context, no worker -> 1 start"),
    ("a waiting worker is stopped as idle", case_waiting, "lib/fwx/execute/run.py", 'if state == "ready" and info.get("activity") == "idle" and not waiting and not rec.get("asking"):',
     'if state == "ready" and info.get("activity") == "idle" and not rec.get("asking"):',
     "left alone until its limit, not stopped as idle"),
    ("the run's terminal is never closed", case_terminal, "lib/fwx/execute/run.py", "orca.terminal_close(st[\"terminal\"])", "pass", "the terminal is closed after a success -> open"),
    ("run-create with no sender", case_terminal, "lib/fwx/execute/orca.py", '"--objective", objective, "--from", sender)', '"--objective", objective)', "terminal (success): run-create names that terminal"),
    ("worker-start with no sender", case_terminal, "lib/fwx/execute/orca.py", '"path:" + worktree, "--from", sender)', '"path:" + worktree)', "terminal (success): every worker-start names that terminal"),
    ("worker-start without waiting for the worktree", case_discover, "lib/fwx/execute/orca.py", 'result("worktree", "show", "--worktree", "path:" + worktree)', "pass",
     "worker-start waited for Orca to know the worktree -> 0 show calls"),
    ("a selector_not_found is not retried", case_discover, "lib/fwx/execute/orca.py", "if not _not_found(e):", "if True:", "discover: the run is done"),
    ("a worker's worktree made in the workspace's repo", case_nested, "lib/fwx/execute/run.py", "orca.make_worktree(self.repo,", "orca.make_worktree(self.main,",
     "nested: the run is done"),
    ("Orca told about the workspace, not the part's repo", case_nested, "lib/fwx/execute/run.py", "orca.ensure_repo(self.repo)", "orca.ensure_repo(self.main)",
     "nested: `orca repo add` named a"),
    ("wave remove in the current folder, not the run's checkout", case_nested, "lib/fwx/commands/wave.py", 'where if where and os.path.isdir(where) else "."', '"."',
     "nested: `wave remove` from a worktree of repo b removes repo a's leftover worktree: exit"),
    ("resume from any worktree on the branch", case_nested_resume, "lib/fwx/commands/wave.py", "            if own != here:", "            if False:",
     "nested resume from repo b: exit 2, no worker, both repos named"),
    ("worker-read loops to 50 on a non-empty end cursor", case_transcript, "lib/fwx/execute/orca.py", 'if not batch or tr.get("limited") is False or not nxt or nxt == cursor:', "if not nxt:",
     "worker-read stops at end cursor"),
    ("the peek also takes worker_done", case_steer_lines, "lib/fwx/execute/orca.py", '"--types", "question,escalation"', '"--types", "question,escalation,worker_done"',
     "routine worker_done never reaches the orchestrator"),
    ("a forwarded message is not recorded", case_steer, "lib/fwx/execute/run.py", 'done[m["id"]] = dispatch', "pass", "a question reaches the orchestrator once"),
    ("an open question does not stop the idle clock", case_steer, "lib/fwx/execute/run.py", 'and not waiting and not rec.get("asking"):', "and not waiting:",
     "an open question pauses the idle stop"),
    ("an open question does not pause the limit", case_steer, "lib/fwx/execute/run.py", 'rec["started"] += now - rec["asking"]', "pass",
     "an open question pauses the idle stop and the limit"),
    ("executors are told to ask with no orchestrator", case_steer_off, "lib/fwx/execute/run.py", 'if self.orchestrator and job.role == "executor":', 'if job.role == "executor":',
     "off: no executor is told to ask"),
    ("the status is sent as an escalation", case_steer, "lib/fwx/execute/orca.py", '"--type", "status"', '"--type", "escalation"', "a question reaches the orchestrator once"),
    ("factory plane accepts --orchestrator", case_steer_off, "lib/fwx/commands/wave.py", ' or got.get("--plane") == "factory"', "",
     "refusals: --plane factory: stderr explains the refusal (not usage)"),
    ("a settled succeeded worker does not wait for its reply line", case_reply_grace, "lib/fwx/execute/run.py",
     'if state == "succeeded" and not orca.REPLY_LINE.match(line):', "if False:",
     "reply grace: delayed reply after worker_done finishes done"),
    ("a progress line is not flushed", case_progress, "lib/fwx/execute/run.py", "    sys.stdout.flush()\n", "    pass\n", "progress: a line is out while the first worker still works"),
    ("worker-start omits --task-title", case_progress, "lib/fwx/execute/run.py", 'title=title)', 'title=None)',
     "progress: every worker-start carries a readable --task-title naming part, unit and role"),
    ("ORCA_TERMINAL_HANDLE is ignored", case_own_terminal, "lib/fwx/execute/orca.py", 'handle = os.environ.get("ORCA_TERMINAL_HANDLE") or ""', 'handle = ""',
     "own terminal (success): no terminal was created"),
    ("non-PTY or closed ORCA_TERMINAL_HANDLE is adopted", case_own_terminal, "lib/fwx/execute/orca.py",
     'if not handle or handle.startswith("structworker_") or not terminal_alive(handle):', 'if not handle:',
     "own terminal (structworker): falls back to a created terminal and ends done"),
    ("the run closes the terminal it ran in", case_own_terminal, "lib/fwx/execute/run.py", 'if st.get("terminal") and not st.get("terminal_made", True):', "if False:",
     "own terminal (success): no terminal was closed"),
    ("no look at the sender before a worker-start", case_fenced, "lib/fwx/execute/run.py", 'if not orca.terminal_alive(self.st["terminal"]):', "if False:",
     "fenced (plain): the run stops needs-owner naming its closed terminal"),
    ("steer skips sender check when peek_questions fails", case_fenced, "lib/fwx/execute/run.py",
     '        try:\n            msgs = orca.peek_questions(self.st["terminal"], self.orca_run)\n        except orca.OrcaError:\n            self._check_sender()\n            raise',
     '        msgs = orca.peek_questions(self.st["terminal"], self.orca_run)',
     "fenced (orchestrator): the run stops needs-owner naming its closed terminal"),
    ("the sender terminal is made in the main checkout", case_terminal, "lib/fwx/execute/run.py", 'orca.terminal_create(self.top, "fwx run %s" % self.run)', 'orca.terminal_create(self.main, "fwx run %s" % self.run)',
     "terminal (success): one made, titled for the run, in the phase worktree"),
    ("terminal create is not retried", case_terminal_discover, "lib/fwx/execute/orca.py", 'got = _discover(lambda: result("terminal", "create"', 'got = (lambda f, n: f())(lambda: result("terminal", "create"',
     "terminal discover: the run is done"),
    ("a wave line repeats its subject as the body", case_steer_lines, "lib/fwx/execute/run.py", '            self.tell(subject, body)\n        except orca.OrcaError as e:\n            self._check_sender()\n            raise self.unreachable(e, "the run stopped after: %s" % subject)',
     '            self.tell(subject, subject)\n        except orca.OrcaError as e:\n            self._check_sender()\n            raise self.unreachable(e, "the run stopped after: %s" % subject)',
     "lines: no status mail repeats its subject in its body"),
    ("the final line is a long subject", case_steer_lines, "lib/fwx/execute/run.py", 'r.tell("[%s] run %s %s" % (os.path.basename(r.part), st["run"], status),', 'r.tell("[%s] run %s %s: %s" % (os.path.basename(r.part), st["run"], status, line),',
     "lines: the orchestrator got the wave lines and the final line"),
    ("--json is not read", case_list_json, "lib/fwx/commands/wave.py", 'if argv and argv != ["--json"]:', "if argv:", "list --json: exit 0 and one JSON document"),
    ("the events are not capped", case_list_json, "lib/fwx/execute/run.py", "EVENTS = 8", "EVENTS = 10 ** 6", "list --json: the events are the last 8 progress lines"),
    ("a resume keeps the Orca run of a lost terminal", case_fenced, "lib/fwx/execute/run.py", 'self.st["orca_run"] = None', "pass", "fenced (plain): the resume goes on to done"),
    ("no handler for SIGTERM, SIGHUP and SIGINT", case_signals, "lib/fwx/execute/run.py", "    caught = catch_signals()\n", "    caught = {}\n",
     "SIGTERM: the run says failed and names the signal"),
    ("a worker a signal cut is not marked, so the resume polls its released dispatch", case_signals, "lib/fwx/execute/run.py", 'rec["interrupted"] = True', "pass",
     "SIGTERM: the resume started the cut task again and then the reviewer"),
    ("a run a signal cut is not resumable", case_signals, "lib/fwx/commands/wave.py",
     'if saved["state"] != "active" and not (saved.get("result") or {}).get("interrupted"):', 'if saved["state"] != "active":', "SIGTERM: --resume takes the run up"),
    ("the merged branches are removed before the checks", case_signals_merge, "lib/fwx/execute/integrate.py",
     '    result["head"] = verify.head(top)\n    if result["conflict"]:\n        drop_merged()\n', '    drop_merged()\n    result["head"] = verify.head(top)\n    if result["conflict"]:\n',
     "the merged branch and its worktree are kept for the resume"),
    ("run_check does not kill its check on a signal", case_signals_merge, "lib/fwx/core/verify.py", "with _unwind_on_signal():", "if True:",
     "the check is gone, not an orphan"),
    ("the driver kills its wave call with no stop first", case_signals_merge, "lib/fwx/execute/run.py", "            p.terminate()\n", "            p.kill()\n", "the check is gone, not an orphan"),
    ("an interrupted run sweeps its worktrees", case_signals_start, "lib/fwx/execute/run.py", "    if interrupted:\n", "    if False:\n",
     "the worker's clean worktree is not swept by the cut run"),
    ("a cut worker is not released before the next attempt", case_signals_release, "lib/fwx/execute/run.py",
     "            self.settle(rec)  # its worker is released first, or the run ends failed: never a second worker beside a live one", "            pass",
     "no second worker beside the live one"),
    ("the worker is recorded after Orca answers", case_signals_start, "lib/fwx/execute/run.py", '        self.st["workers"][key] = rec\n        self.save()\n        orca.prepare_worker',
     "        self.save()\n        orca.prepare_worker", "the worker is recorded before Orca answers"),
    ("wave list does not mark an interrupted run", case_signals, "lib/fwx/execute/run.py", '" interrupted=%s" % cut if cut else ""', '""', "`wave list` marks the run interrupted"),
]


if __name__ == "__main__":
    if not os.path.isdir("/proc"):
        s.not_run("no /proc: cleanup cannot tell a live agent from a stale lock")
    try:
        for case in CASES:
            case(ROOT, s)
        for name, case, path, old, new, needle in MUTANTS:
            m = helpers.FirstFail(lambda f, needle=needle: needle in f)
            try:
                tree = mutant_tree(path, old, new)
            except (AssertionError, OSError) as e:
                s.ok("control %s: built" % name, False, str(e))
                continue
            m.run(case, tree, m)
            s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
            s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails), "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
    finally:
        for w in WORLDS:
            w.stop()
    s.done()
