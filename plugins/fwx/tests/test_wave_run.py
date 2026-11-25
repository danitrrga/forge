#!/usr/bin/env python3
"""`fwx wave run` and `fwx wave list` (09.6 T66): lib/fwx/commands/wave.py, execute/run.py, execute/orca.py, execute/cleanup.py.

The command runs against a fake `orca` (tests/fake_orca.py) on a PATH of its own, which records every call with the Orca variables it
carried, refuses `worker-release` of a dispatch that is not settled (`dispatch_inactive`, as Orca does) and the creation flags beside
`--worktree path:`, and plays each worker at `worker-start`: it commits in the worktree and writes its report as an executor does. The
toy repos are test_wave_prepare.py's. Nothing here reads the real HOME, the real Orca or a real project.

Seen red before the code existed (python3 tests/test_wave_run.py, first lines; `fwx wave run` was not a verb):
  FAIL: loop: exit: got 2, want 0 (stderr 'fwx wave: unknown verb: run' ...)
  FAIL: loop: stdout is the result line: got '', want 'run <id> done: ...'

Controls, each a copy of lib/ with one line changed (MUTANTS), seen red on the case named:
  the cap read as unlimited:                  FAIL: never more open workers than the cap -> 2 open, cap 1
  cleanup without the run's worktrees:        FAIL: a reviewer worktree with no commit is removed -> kept
  release with no stop before it:             FAIL: every dispatch is released -> dispatch_inactive
  a forced removal:                           FAIL: an executor worktree with unmerged commits stays -> removed
  the settings copied as they are:            FAIL: the worker's settings write the cache at 5 minutes -> env has no FORCE_PROMPT_CACHING_5M
  a start with no base context:               FAIL: no base context, no worker -> 1 start
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
from test_wave_prepare import CRIT, Scene, task  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
from fwx import context_base  # noqa: E402

s = helpers.Suite()
FAKE = os.path.join(ROOT, "tests", "fake_orca.py")
LIMIT = 2.5
LINE = re.compile(r"run (\S+) (done|failed|needs-owner): (.*)\Z")
BAD = "python3 -c \"import os,sys; sys.exit(1 if os.path.exists('BAD') else 0)\""
THREE = [task("T1", 1, ["src/a.py"]), task("T2", 1, ["src/b.py"]), task("T3", 2, ["src/c.py"])]
FILES = {"T1": {"src/a.py": "a1\n"}, "T2": {"src/b.py": "b1\n"}, "T3": {"src/c.py": "c1\n"}}


class World:
    """A Scene (toy repo, phase worktree, the part's plan) with a fake orca on a PATH of its own and the base context in place."""

    def __init__(self, tasks=None, recipe=("true",), cap=1, behave=None, context=True, registered=()):
        self.scene = Scene(tasks=tasks or THREE, recipe=recipe, settings={"worktree": {"baseRef": "head"}, "env": {"KEEP_ME": "1"}},
                           config={"limits": {"per_project": {"executor": cap}, "default_cap": {"supervised": 3, "unattended": 4}}})
        sc = self.scene
        self.repo, self.cwd, self.part = sc.repo, sc.cwd, sc.part
        self.dir = helpers.mkdtemp("fwx-orca-")
        self.bin = os.path.join(self.dir, "bin")
        helpers.write(self.bin, "orca", "#!/bin/sh\nexec %s %s \"$@\"\n" % (sys.executable, FAKE), 0o755)
        self.behave = dict({"files": FILES, "criteria": [c["id"] for c in CRIT], "registered": list(registered)}, **(behave or {}))
        self.set_behave()
        if context:
            path = context_base.base_path(self.part)
            helpers.write(os.path.dirname(path), os.path.basename(path), "# map\nBASE-MAP-TEXT\n## Decided\nBASE-DECIDED-TEXT\n")
        self.common = os.path.join(self.repo, ".git")
        self.procs = []

    def set_behave(self):
        helpers.write(self.dir, "behave.json", json.dumps(self.behave))

    def env(self, **extra):
        e = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "FAKE_ORCA_DIR": self.dir, "CLAUDE_CONFIG_DIR": self.scene.conf,
             "FWX_RUN_POLL_S": "0.05", "FWX_RUN_IDLE_S": "0.4", "FWX_RUN_LIMIT_S": str(LIMIT),
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
             "ORCA_AGENT_SESSION_ID": "leak", "ORCA_AGENT_SESSION_SPAWN_TOKEN": "leak", "ORCA_STRUCTURED_SESSION": "leak"}
        e.update(extra)
        return helpers.clean_env(**e)

    def argv(self, root, *flags):
        return [sys.executable, os.path.join(root, "bin", "fwx"), "wave", "run", "--part-dir", self.part, "--plane", "session", "--branch", "phase"] + list(flags)

    def run(self, *flags, root=ROOT, cwd=None, **env):
        return subprocess.run(self.argv(root, *flags), cwd=cwd or self.cwd, env=self.env(**env), capture_output=True, text=True, timeout=120)

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
    for unit in ("T1", "T3"):
        k = next(k for k, d in w.dispatches().items() if d["unit"] == unit)
        started = next(c["t"] for c in calls if c.get("start", {}).get("unit") == unit)
        stopped = [c["t"] for c in calls if c.get("dispatch") == k and c["argv"][1] == "worker-stop"]
        S.ok("failure: %s (%s) is left alone until its limit, then stopped" % (unit, "waiting on a prompt" if unit == "T1" else "running"),
             len(stopped) == 1 and stopped[0] - started >= LIMIT - 0.3, "stopped after %r s" % ([round(t - started, 2) for t in stopped]))
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
    helpers.write(w.dir, "go-T1", "")
    r = subprocess.run(w.argv(root, "--resume", run), cwd=w.cwd, env=w.env(), capture_output=True, text=True, timeout=120)
    m = line_of(r)
    S.ok("resume: the run goes on to done", bool(m) and m.group(2) == "done" and m.group(1) == run, "got %r %r" % (r.stdout[-300:], r.stderr[-300:]))
    S.eq("resume: no worker the state already held is started again", units(w), ["T1", "r1"])
    S.ok("resume: every dispatch is released", all(d["released"] for d in w.dispatches().values()))


CASES = [case_loop, case_failure, case_error, case_gate_red, case_retry, case_conflict, case_fix, case_gate_entry, case_revert, case_security, case_refusals, case_registered,
         case_one_run, case_resume]

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
