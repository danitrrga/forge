#!/usr/bin/env python3
"""`project.worktree_setup`: the commands that make a fresh worktree able to run the project's checks (`fwx wave setup`,
lib/fwx/execute/worktree_setup.py), and where they are called: `fwx wave check-base` (every executor's step 0) and `fwx wave
prepare` (the phase worktree, before its base runs).

Toy repos only, commands like `touch` and `sh -c`: no package manager, no network, no real project. The user's Claude Code
folder is a toy one (`CLAUDE_CONFIG_DIR`).

Seen red before the code existed (python3 tests/test_worktree_setup.py, first lines; `fwx wave setup` was not a command):
  FAIL: setup: ran in a task worktree: exit: got (2, 'usage: fwx wave <prepare|check-base|scratch|integrate|fix-round|revert|cleanup|summary> ...\\n'), want (0, ...)
  FAIL: check-base: the setup ran before the first check: setup did not run before the check
  FAIL: prepare: the base check ran with the setup done: setup did not run before the base check: exit 1, ... base ... is red
The controls at the bottom plant the defect in a copy of the plugin and demand the case fail with the text named there.
"""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
from test_wave_prepare import Scene as PrepScene, mutant_tree, runner  # noqa: E402
from test_wave_integrate import Scene as IntScene, IDENT  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))

s = helpers.Suite()
MK = "mkdir -p deps && touch deps/installed"


def slurp(path):
    """The text of a file, empty when it is not there: a missing log is a FAIL of the check that reads it, not a crash."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


class Scene:
    """A toy repo on master whose `deps/` is git-ignored, the project's configuration (untracked, as forge writes it) and
    a linked worktree `worktree-agent-t1` born from master, the way a task's worktree is."""

    def __init__(self, setup=(MK,), ignore="deps/\n", files=None):
        self.repo = helpers.toy_repo(dict({"README": "toy\n", ".gitignore": ".fwx/\n.claude/\n" + ignore}, **(files or {})))
        helpers.write(self.repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"worktree_setup": setup}}))
        self.wt = helpers.add_worktree(self.repo, "worktree-agent-t1")
        self.conf = helpers.mkdtemp("fwx-claude-")
        self.env = {"CLAUDE_CONFIG_DIR": self.conf}

    def head(self):
        return helpers.git(self.wt, "rev-parse", "HEAD").strip()

    def has(self, rel, cwd=None):
        return os.path.exists(os.path.join(cwd or self.wt, rel))

    def lines(self, rel, cwd=None):
        p = os.path.join(cwd or self.wt, rel)
        return len(open(p).read().splitlines()) if os.path.exists(p) else 0

    def clean(self, cwd=None):
        return helpers.git(cwd or self.wt, "status", "--porcelain") == ""


def case_run(R, S):
    sc = Scene()
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("setup: ran in a task worktree: exit", (r.returncode, r.stderr), (0, ""))
    S.ok("setup: says how many commands ran", "1 command ran" in r.stdout, r.stdout)
    S.ok("setup: the command ran in the worktree", sc.has("deps/installed"))
    S.ok("setup: and not in the main checkout", not sc.has("deps/installed", sc.repo))
    log = os.path.join(os.path.realpath(sc.wt), ".fwx-agent", "worktree-setup.log")
    S.ok("setup: the output is kept in a log under .fwx-agent/, and the line names it", os.path.isfile(log) and log in r.stdout, r.stdout)
    S.ok("setup: the worktree is still clean (the log and the marker are ignored)", sc.clean(), helpers.git(sc.wt, "status", "--porcelain"))
    two = Scene(setup=[MK, "mkdir -p deps && echo b >> deps/second"])
    r = R(two.wt, "wave", "setup", env=two.env)
    S.ok("setup: two commands, both ran, in order, and the line says 2", "2 commands ran" in r.stdout and two.has("deps/second") and two.has("deps/installed"), r.stdout + r.stderr)
    out = Scene(setup=["echo building; echo oops >&2"])
    R(out.wt, "wave", "setup", env=out.env)
    text = slurp(os.path.join(os.path.realpath(out.wt), ".fwx-agent", "worktree-setup.log"))
    S.ok("setup: the log holds the command, its stdout and its stderr", all(w in text for w in ("echo building", "building", "oops")), text)


def case_none(R, S):
    for label, setup in (("an empty list", []), ("the key missing", None)):
        sc = Scene(setup=[])
        if setup is None:
            helpers.write(sc.repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": {}}))
        r = R(sc.wt, "wave", "setup", env=sc.env)
        S.eq("setup, %s: exit 0 and not silent" % label, (r.returncode, "no worktree_setup configured" in r.stdout), (0, True))
        S.ok("setup, %s: nothing was made in the worktree" % label, not sc.has(".fwx-agent") and sc.clean())


def case_second_call(R, S):
    sc = Scene(setup=["mkdir -p deps && echo run >> deps/count"], files={"package-lock.json": "{}\n"})
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("second call: the first runs it", (r.returncode, sc.lines("deps/count")), (0, 1))
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("second call: exit 0", r.returncode, 0)
    S.ok("second call: a no-op that says so and says how to run it again", "already" in r.stdout and "--force" in r.stdout, r.stdout)
    S.eq("second call: the command did not run again", sc.lines("deps/count"), 1)
    r = R(sc.wt, "wave", "setup", "--force", env=sc.env)
    S.eq("--force: runs it again", (r.returncode, sc.lines("deps/count")), (0, 2))
    helpers.write(sc.wt, "package-lock.json", '{"changed": 1}\n')
    helpers.git(sc.wt, "add", "-A")
    helpers.git(sc.wt, "commit", "-q", "-m", "a dependency changed")
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("a changed lockfile: the setup runs again by itself", (r.returncode, sc.lines("deps/count")), (0, 3))
    helpers.write(sc.wt, "README", "not a dependency file\n")
    helpers.git(sc.wt, "add", "-A")
    helpers.git(sc.wt, "commit", "-q", "-m", "docs")
    R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("a changed file that defines no dependency: still a no-op", sc.lines("deps/count"), 3)
    helpers.write(sc.repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"worktree_setup": ["mkdir -p deps && echo other >> deps/count"]}}))
    R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("a changed setup list: runs again", sc.lines("deps/count"), 4)


def case_failing(R, S):
    sc = Scene(setup=["mkdir -p deps && touch deps/first", "sh -c 'echo boom-text; exit 3'", "touch deps/after"])
    r = R(sc.wt, "wave", "setup", env=sc.env)
    log = os.path.join(os.path.realpath(sc.wt), ".fwx-agent", "worktree-setup.log")
    S.eq("failing: exit", r.returncode, 1)
    S.ok("failing: names the command, its exit code and the log path", all(w in r.stderr for w in ("sh -c 'echo boom-text; exit 3'", "exit 3", log)), r.stderr)
    S.ok("failing: starts with `worktree setup failed:`", "worktree setup failed: sh -c" in r.stderr, r.stderr)
    S.ok("failing: the earlier command ran and the later one did not", sc.has("deps/first") and not sc.has("deps/after"))
    S.ok("failing: the log has what the command printed", "boom-text" in slurp(log))
    S.ok("failing: no success line on stdout", "ran" not in r.stdout, r.stdout)
    helpers.write(sc.repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"worktree_setup": ["mkdir -p deps && touch deps/fixed"]}}))
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("failing: a failure leaves no marker, so the next call runs", (r.returncode, sc.has("deps/fixed")), (0, True))
    r = R(Scene(setup=["exit 0", "false"]).wt, "wave", "setup")
    S.ok("failing: `false` is exit 1 and is named", r.returncode == 1 and "false" in r.stderr and "exit 1" in r.stderr, r.stderr)


def case_dirty(R, S):
    sc = Scene(setup=["touch stray.txt"])
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("dirty: an untracked, non-ignored file is refused: exit", r.returncode, 1)
    S.ok("dirty: and named, with the way out", "stray.txt" in r.stderr and ".gitignore" in r.stderr, r.stderr)
    S.ok("dirty: no success line", "ran" not in r.stdout, r.stdout)
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("dirty: the refusal leaves no marker: the second call runs, and refuses again", r.returncode, 1)
    sc = Scene(setup=["echo more >> README"])
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.ok("dirty: a tracked file the setup changed is named too", r.returncode == 1 and "README" in r.stderr, r.stderr)
    sc = Scene(setup=["mkdir -p deps/a/b && touch deps/a/b/c", "mkdir -p lib/x && touch lib/x/one lib/x/two"])
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.ok("dirty: every file of an untracked folder is named, not the folder", "lib/x/one" in r.stderr and "lib/x/two" in r.stderr, r.stderr)
    S.ok("dirty: an ignored folder is not named", "deps/" not in r.stderr.replace(".gitignore", ""), r.stderr)
    sc = Scene(setup=["touch stray.txt"])
    helpers.write(sc.wt, "stray.txt", "was here before\n")
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.ok("dirty: a worktree that was already dirty is refused too (its checks would refuse it), naming the file", r.returncode == 1 and "stray.txt" in r.stderr, r.stderr)
    sc = Scene(setup=[MK])
    helpers.write(sc.wt, ".fwx/milestones/v1/note", "documents the clean-tree checks do not count\n")
    S.eq("dirty: .fwx/ is not counted, as in `fwx verify`", R(sc.wt, "wave", "setup", env=sc.env).returncode, 0)


def case_main_checkout(R, S):
    sc = Scene()
    r = R(sc.repo, "wave", "setup", env=sc.env)
    S.eq("main checkout: refused with exit 2", r.returncode, 2)
    S.ok("main checkout: says why", "linked worktree" in r.stderr, r.stderr)
    S.ok("main checkout: nothing ran there", not sc.has("deps/installed", sc.repo) and not sc.has(".fwx-agent", sc.repo))
    outside = helpers.mkdtemp("fwx-nogit-")
    r = R(outside, "wave", "setup", env=sc.env)
    S.eq("outside a repository: exit 2, nothing made", (r.returncode, os.listdir(outside)), (2, []))
    for argv in (["--bogus"], ["extra"]):
        r = R(sc.wt, "wave", "setup", *argv, env=sc.env)
        S.eq("usage: %s: exit 2, nothing ran" % argv, (r.returncode, "usage: fwx wave setup" in r.stderr, sc.has("deps/installed")), (2, True, False))


def case_config(R, S):
    for label, bad in (("a string", "npm ci"), ("a non-string", ["a", 3]), ("an empty command", ["a", ""]), ("a blank command", ["  "])):
        sc = Scene(setup=bad)
        r = R(sc.wt, "wave", "setup", env=sc.env)
        S.ok("config: worktree_setup as %s: exit 2, names the key, nothing ran" % label,
             r.returncode == 2 and "worktree_setup" in r.stderr and not sc.has("deps/installed"), "%d %s" % (r.returncode, r.stderr))


def case_timeout(R, S):
    """The setup's command is killed with everything it started when it runs past the limit. Called as a function: the limit is
    an argument, not a flag. Control: a kill of the shell alone leaves the `sleep` it started running."""
    sys.path.insert(0, os.path.join(R.root, "lib"))
    for name in [m for m in sys.modules if m == "fwx" or m.startswith("fwx.")]:
        del sys.modules[name]
    try:
        from fwx.execute import worktree_setup as ws
    except ImportError as e:
        S.ok("timeout: the module is there", False, str(e))
        return
    sc = Scene()
    pids = helpers.mkdtemp("fwx-pids-")
    pidfile = os.path.join(pids, "sleeper.pid")
    command = "sh -c 'sleep 300 & echo $! > %s; wait'" % pidfile
    started = time.monotonic()
    try:
        ws.run(sc.wt, [command, "touch deps/after"], timeout=1)
        S.ok("timeout: raises SetupFailed", False, "it returned")
    except ws.SetupFailed as e:
        text = str(e)
        S.ok("timeout: reported as failed, naming the command, the time and the log", all(w in text for w in ("worktree setup failed:", "sleep 300", "timed out after 1 s", "worktree-setup.log")), text)
    S.ok("timeout: came back near the limit, not after 300 s", time.monotonic() - started < 20, "%.1f s" % (time.monotonic() - started))
    pid = int(open(pidfile).read().strip()) if os.path.exists(pidfile) else None
    S.ok("timeout: the process the command started was written", pid is not None)
    alive = True
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, TypeError):
            alive = False
            break
        time.sleep(0.1)
    if alive and pid:
        os.kill(pid, 9)
    S.ok("timeout: no process is left (pid %s)" % pid, not alive)
    S.ok("timeout: the commands after it did not run", not sc.has("deps/after"))
    S.ok("timeout: the worktree is clean", sc.clean())


def check_after(R, sc, sha):
    """What an executor does: `check-base`, then its checks. Returns (check-base result, whether the check ran, its exit)."""
    r = R(sc.wt, "wave", "check-base", sha, env=sc.env)
    if r.returncode != 0:
        return r, False, None
    c = subprocess.run(["sh", "-c", "test -f deps/installed"], cwd=sc.wt)
    return r, True, c.returncode


def case_check_base(R, S):
    sc = Scene()
    r, ran, rc = check_after(R, sc, sc.head())
    S.eq("check-base: exit", (r.returncode, ran), (0, True))
    S.ok("check-base: the setup ran before the first check: setup did not run before the check", rc == 0, "deps/installed missing at the check")
    S.ok("check-base: says that it ran", "worktree setup: 1 command ran" in r.stderr, r.stderr)
    S.eq("check-base: stdout stays empty", r.stdout, "")
    r, ran, rc = check_after(R, sc, sc.head())
    S.ok("check-base: a second call is a no-op", r.returncode == 0 and "already" in r.stderr, r.stderr)
    bad = Scene(setup=["mkdir -p deps && touch deps/one", "sh -c 'exit 7'"])
    r, ran, rc = check_after(R, bad, bad.head())
    S.eq("check-base: a failing setup: exit 43, and the task's check did not run", (r.returncode, ran), (43, False))
    S.ok("check-base: the line is the reason: `worktree setup failed: <command>`", r.stderr.startswith("worktree setup failed: sh -c 'exit 7'") and "exit 7" in r.stderr and "worktree-setup.log" in r.stderr, r.stderr)
    stray = Scene(setup=["touch stray.txt"])
    S.eq("check-base: a setup that leaves a stray file: exit 43", R(stray.wt, "wave", "check-base", stray.head(), env=stray.env).returncode, 43)
    wrong = Scene()
    r = R(wrong.wt, "wave", "check-base", "abcdef1", env=wrong.env)
    S.eq("check-base: a wrong base is still 42, and runs no setup", (r.returncode, wrong.has("deps/installed")), (42, False))
    r = R(wrong.repo, "wave", "check-base", wrong.head(), env=wrong.env)
    S.eq("check-base: the main checkout is still 42, and runs no setup", (r.returncode, wrong.has("deps/installed", wrong.repo)), (42, False))
    none = Scene(setup=[])
    r = R(none.wt, "wave", "check-base", none.head(), env=none.env)
    S.eq("check-base: nothing configured: silent, as before", (r.returncode, r.stdout, r.stderr), (0, "", ""))
    broken = Scene(setup="npm ci")
    r = R(broken.wt, "wave", "check-base", broken.head(), env=broken.env)
    S.ok("check-base: a configuration that cannot be read: exit 43 and the setup is the reason", r.returncode == 43 and r.stderr.startswith("worktree setup failed:") and "worktree_setup" in r.stderr, "%d %r" % (r.returncode, r.stderr))
    helpers.write(sc.wt, "package-lock.json", "{}\n")
    helpers.git(sc.wt, "add", "-A")
    helpers.git(sc.wt, "commit", "-q", "-m", "lock")
    r = R(sc.wt, "wave", "check-base", sc.head(), env=sc.env)
    S.ok("check-base: the head moved to a commit that changes a dependency file: setup runs again", r.returncode == 0 and "worktree setup: 1 command ran" in r.stderr, r.stderr)


def case_prepare(R, S):
    """The phase worktree's base check is the project's own recipe: it runs after the setup, or it is red for a reason that has
    nothing to do with the work."""
    mk = "mkdir -p .claude && touch .claude/installed"
    cfg = {"project": {"checks": ["test -f .claude/installed"], "worktree_setup": [mk]}}
    sc = PrepScene(config=cfg)
    r = sc.prepare(R)
    S.ok("prepare: the base check ran with the setup done: setup did not run before the base check: exit %s, %s" % (r.returncode, r.stderr[-160:]),
         r.returncode == 0, r.stderr[-300:])
    S.ok("prepare: the setup's line is on stderr, stdout is still the args (one JSON)", "worktree setup: 1 command ran" in r.stderr and r.stdout.strip().startswith("{"), r.stderr[-200:])
    r = sc.prepare(R)
    S.ok("prepare: run again, the setup is a no-op", r.returncode == 0 and "already" in r.stderr, r.stderr[-200:])
    bad = PrepScene(config={"project": {"checks": ["true"], "worktree_setup": ["sh -c 'exit 5'"]}})
    r = bad.prepare(R)
    S.ok("prepare: a failing setup stops the run before the base, exit 2, naming the command", r.returncode == 2 and "worktree setup failed: sh -c 'exit 5'" in r.stderr and r.stdout == "", "%d %s" % (r.returncode, r.stderr[-200:]))
    S.ok("prepare: and runs no check (no briefs written)", not os.path.isdir(os.path.join(bad.repo, ".git", "fwx", "runs")) or not os.listdir(os.path.join(bad.repo, ".git", "fwx", "runs")))
    main = PrepScene(config=cfg, wt=False)
    r = main.prepare(R, cwd=main.cwd)
    S.ok("prepare: in the main checkout (no linked worktree) the setup is not run there", not os.path.exists(os.path.join(main.repo, ".claude", "installed")) and "worktree setup" not in r.stderr, r.stderr[-200:])


def tolerant(R, S, label, cfg_text, want):
    """check-base and `wave setup` on a worktree whose configuration file is `cfg_text` (None: no file): the exits `want`
    ((check-base, setup)), no traceback, and nothing on stderr when `want` is zero."""
    sc = Scene()
    if cfg_text is None:
        os.remove(os.path.join(sc.repo, ".claude", "fwx.json"))
    else:
        helpers.write(sc.repo, ".claude/fwx.json", cfg_text)
    r = R(sc.wt, "wave", "check-base", sc.head(), env=sc.env)
    S.eq("config tolerance, %s: check-base exit" % label, r.returncode, want[0])
    S.ok("config tolerance, %s: check-base prints no traceback%s" % (label, ", and nothing at all" if want[0] == 0 else ""),
         "Traceback" not in r.stderr and (want[0] != 0 or r.stderr == ""), r.stderr)
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("config tolerance, %s: setup exit" % label, r.returncode, want[1])
    S.ok("config tolerance, %s: setup prints no traceback" % label, "Traceback" not in r.stderr, r.stderr)
    return r


def case_unrelated_config(R, S):
    """A project with no worktree_setup behaves as before the field existed: check-base reads nothing but that field.

    Red before the fix (check-base loaded the whole configuration; same toy worktree, base right):
      FAIL: config tolerance, a model table error: check-base exit: got 43, want 0       (stderr `worktree setup failed: ... unknown role`)
      FAIL: config tolerance, schema 2: check-base exit: got 43, want 0
      FAIL: config tolerance, project null: check-base exit: got 1, want 0                (TypeError: 'NoneType' object is not subscriptable)
      FAIL: config tolerance, project a list: check-base exit: got 1, want 0              (TypeError: list indices must be integers)
      FAIL: config tolerance, no fwx.json: check-base prints no traceback, and nothing at all: ... fwx: no .claude/fwx.json at ...; using defaults
    """
    cases = (("a model table error", '{"schema":1,"models":{"foo":{}}}'), ("schema 2", '{"schema":2}'), ("project null", '{"schema":1,"project":null}'),
             ("project a list", '{"schema":1,"project":[]}'), ("project a string", '{"schema":1,"project":"x"}'), ("no fwx.json", None))
    for label, text in cases:
        tolerant(R, S, label, text, (0, 0))
    r = tolerant(R, S, "no worktree_setup in a project table", '{"schema":1,"project":{"checks":["true"]}}', (0, 0))
    S.ok("config tolerance: wave setup says nothing is configured", "no worktree_setup configured" in r.stdout, r.stdout)
    # What cannot be read cannot say whether a setup is owed, so it fails closed, naming the file, and never with a traceback.
    for label, text in (("invalid JSON", "{not json"), ("not an object", "[1]"), ("worktree_setup a string", '{"project":{"worktree_setup":"npm ci"}}')):
        r = tolerant(R, S, label, text, (43, 2))
    sc = Scene(setup=[MK])
    helpers.write(sc.repo, ".claude/fwx.json", json.dumps({"schema": 2, "models": {"foo": {}}, "project": {"worktree_setup": [MK]}}))
    r = R(sc.wt, "wave", "check-base", sc.head(), env=sc.env)
    S.ok("config tolerance: with a setup configured, an unrelated bad value does not stop it", r.returncode == 0 and sc.has("deps/installed"), r.stderr)


def case_integrate_setup(R, S):
    """The phase worktree gets its dependencies again when a merge changes a lockfile, before the checks of the join.

    Red before the fix (nothing called the setup after a merge; the quick check counts the runs of the setup):
      FAIL: two waves: wave 1 changes the lockfile: the setup ran again before its checks (count 2): ... quick rc 1, count 1
    """
    sc = IntScene(quick=['test "$(wc -l < deps/count | tr -d " ")" = 2'])
    with open(os.path.join(sc.repo, ".git", "info", "exclude"), "a") as f:
        f.write("deps/\n")
    helpers.write(sc.repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": {
        "checks": ["true"], "checks_quick": ['test "$(wc -l < deps/count | tr -d " ")" = 2'], "worktree_setup": ["mkdir -p deps && echo run >> deps/count"]}}))
    first = R(sc.cwd, "wave", "setup", env=IDENT)
    S.eq("two waves: prepare's setup of the phase worktree", (first.returncode, slurp(os.path.join(sc.cwd, "deps", "count")).count("\n")), (0, 1))
    b1 = sc.agent("w1", [("package-lock.json", '{"lock": 1}\n', None)])
    r = sc.integrate(R, b1)
    v = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
    count = slurp(os.path.join(sc.cwd, "deps", "count")).count("\n")
    S.ok("two waves: wave 1 changes the lockfile: the setup ran again before its checks (count 2): exit %s, quick rc %s, count %d" % (r.returncode, (v.get("quick") or {}).get("rc"), count),
         r.returncode == 0 and v.get("ok") is True and count == 2, r.stderr + r.stdout[:300])
    b2 = sc.agent("w2", [("src/b.py", "b2\n", None)])
    r = sc.integrate(R, b2)
    count = slurp(os.path.join(sc.cwd, "deps", "count")).count("\n")
    S.ok("two waves: wave 2 changes no dependency file: the setup does not run again (count %d)" % count, r.returncode == 0 and count == 2, r.stderr + r.stdout[:300])
    # a setup that fails after a merge ends the join with its own line in `setup`, and the run's `ok` is false
    helpers.write(sc.repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"checks": ["true"], "worktree_setup": ["sh -c 'exit 6'"]}}))
    b3 = sc.agent("w3", [("src/a.py", "a3\n", None)])
    r = sc.integrate(R, b3)
    v = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
    S.ok("two waves: a failing setup after the merge: exit 1, `setup` carries the line, ok false, no round spent",
         r.returncode == 1 and v.get("ok") is False and str(v.get("setup", "")).startswith("worktree setup failed: sh -c 'exit 6'") and sc.rounds() == "rounds 0/3",
         "%s %s %s" % (r.returncode, r.stdout[:300], r.stderr))
    plain = IntScene()
    pb = plain.agent("n", [("src/a.py", "n\n", None)])
    pv = json.loads(plain.integrate(R, pb).stdout)
    S.ok("a join of a project with no setup: no `setup` key (the result is as before)", "setup" not in pv, repr(sorted(pv)))


def case_io_errors(R, S):
    """An OSError in the setup's own files is one line and an exit, never a traceback.

    Red before the fix:
      FAIL: log is a directory: setup: exit 1 and a traceback: got (1, 'Traceback (most recent call last): ... IsADirectoryError: [Errno 21] Is a directory: ...worktree-setup.log')
      FAIL: marker cannot be written: setup: ... PermissionError: [Errno 13] Permission denied: '.../worktree-setup.json'
    """
    sc = Scene()
    os.makedirs(os.path.join(sc.wt, ".fwx-agent", "worktree-setup.log"))
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.ok("log is a directory: setup: a one-line error, exit 2, no traceback: got %d %r" % (r.returncode, r.stderr[-200:]),
         r.returncode == 2 and "Traceback" not in r.stderr and len(r.stderr.strip().splitlines()) == 1 and "worktree-setup.log" in r.stderr, r.stderr)
    S.ok("log is a directory: the command did not run", not sc.has("deps/installed"))
    r = R(sc.wt, "wave", "check-base", sc.head(), env=sc.env)
    S.ok("log is a directory: check-base: exit 43, the reason on one line, no traceback: got %d %r" % (r.returncode, r.stderr[-200:]),
         r.returncode == 43 and "Traceback" not in r.stderr and r.stderr.startswith("worktree setup failed:"), r.stderr)
    if os.geteuid() == 0:
        S.ok("marker cannot be written: NOT RUN (root writes anywhere)", True)
        return
    sc = Scene(setup=[MK + " && chmod a-w .fwx-agent"])
    try:
        r = R(sc.wt, "wave", "setup", env=sc.env)
        S.ok("marker cannot be written: setup: a one-line error, exit 2, no traceback: got %d %r" % (r.returncode, r.stderr[-200:]),
             r.returncode == 2 and "Traceback" not in r.stderr and len(r.stderr.strip().splitlines()) == 1 and "worktree-setup.json" in r.stderr, r.stderr)
    finally:
        os.chmod(os.path.join(sc.wt, ".fwx-agent"), 0o755)


def _load_ws(R, S):
    sys.path.insert(0, os.path.join(R.root, "lib"))
    for name in [m for m in sys.modules if m == "fwx" or m.startswith("fwx.")]:
        del sys.modules[name]
    try:
        from fwx.execute import worktree_setup as ws
    except ImportError as e:
        S.ok("the module is there", False, str(e))
        return None
    return ws


def _gone(pid, tries=40):
    for _ in range(tries):
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, TypeError):
            return True
        time.sleep(0.1)
    return False


def case_detached_child(R, S):
    """A child that left the process group with `setsid` is killed at the limit too, as far as the platform allows: found through
    its parent (the shell, still alive at the limit) in /proc. Not covered, and said in the module's docstring: a child that
    detached and whose parent had already exited (init's now), and anything left running after a command that exited by itself.

    Red before the fix (killpg alone):
      FAIL: detached child: no process is left (pid N)
    """
    ws = _load_ws(R, S)
    if ws is None:
        return
    sc = Scene()
    pids = helpers.mkdtemp("fwx-pids-")
    pidfile = os.path.join(pids, "d.pid")
    command = "sh -c 'setsid sleep 300 >/dev/null 2>&1 & echo $! > %s; wait'" % pidfile
    try:
        ws.run(sc.wt, [command], timeout=1)
        S.ok("detached child: the timeout is reported", False, "it returned")
    except ws.SetupFailed as e:
        S.ok("detached child: the timeout is reported", "timed out after 1 s" in str(e), str(e))
    pid = int(open(pidfile).read().strip()) if os.path.exists(pidfile) else None
    S.ok("detached child: its pid was written", pid is not None)
    gone = pid is not None and _gone(pid)
    if not gone and pid:
        os.kill(pid, 9)
    S.ok("detached child: no process is left (pid %s)" % pid, gone)


def case_log_cap(R, S):
    """The log has a size cap: a command that writes past it is killed and the setup fails, naming the cap and the log.

    Red before the fix (`run` had no `log_cap`; the command wrote 60000066 bytes and the setup passed):
      FAIL: log cap: a runaway output fails the setup: TypeError: run() got an unexpected keyword argument 'log_cap'
    """
    ws = _load_ws(R, S)
    if ws is None:
        return
    sc = Scene()
    started = time.monotonic()
    try:
        ws.run(sc.wt, ["head -c 60000000 /dev/zero | tr '\\0' a", "touch deps/after"], log_cap=100000)
        S.ok("log cap: a runaway output fails the setup", False, "it returned")
    except ws.SetupFailed as e:
        S.ok("log cap: a runaway output fails the setup, naming the cap and the log", "output past 100000 bytes" in str(e) and "worktree-setup.log" in str(e), str(e))
    except TypeError as e:
        S.ok("log cap: a runaway output fails the setup: %s" % e, False, str(e))
    log = os.path.join(sc.wt, ".fwx-agent", "worktree-setup.log")
    size = os.path.getsize(log) if os.path.exists(log) else -1
    S.ok("log cap: the log stays near the cap (%d bytes), not 60 MB" % size, 0 < size < 20000000, str(size))
    S.ok("log cap: the next command did not run, no marker", not sc.has("deps/after") and not sc.has(".fwx-agent/worktree-setup.json"))
    S.ok("log cap: it came back at once", time.monotonic() - started < 20, "%.1f s" % (time.monotonic() - started))
    S.eq("log cap: the default cap is a number of megabytes", 1 << 20 <= ws.LOG_CAP <= 1 << 30, True) if hasattr(ws, "LOG_CAP") else S.ok("log cap: the default cap exists", False, "no LOG_CAP")


def case_marker_validity(R, S):
    """The marker vouches for what the setup made and for the dependency files that were there.

    Red before the fix:
      FAIL: marker: the folder the setup made is gone: the setup runs again: got (0, 1), want (0, 2)
      FAIL: marker: a new untracked lockfile: not a no-op: got 'already done ...'
    """
    sc = Scene(setup=["mkdir -p deps && echo run >> deps/count"], files={"package-lock.json": "{}\n"})
    R(sc.wt, "wave", "setup", env=sc.env)
    shutil.rmtree(os.path.join(sc.wt, "deps"))
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.eq("marker: the folder the setup made is gone: the setup runs again", (r.returncode, sc.lines("deps/count")), (0, 1))
    S.ok("marker: and says it ran", "1 command ran" in r.stdout, r.stdout)
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.ok("marker: with the folder back, a no-op again", r.returncode == 0 and "already" in r.stdout and sc.lines("deps/count") == 1, r.stdout + r.stderr)
    helpers.write(sc.wt, "yarn.lock", "# a new lockfile, not committed\n")
    r = R(sc.wt, "wave", "setup", env=sc.env)
    S.ok("marker: a new untracked lockfile: not a no-op (it is refused as an untracked file): got %d %r" % (r.returncode, (r.stdout + r.stderr)[:120]),
         "already" not in r.stdout and r.returncode == 1 and "yarn.lock" in r.stderr, r.stdout + r.stderr)
    # ignored things that were there before the setup are not its to vouch for
    pre = Scene(setup=["mkdir -p deps && echo run >> deps/count"])
    os.makedirs(os.path.join(pre.wt, "deps"))
    R(pre.wt, "wave", "setup", env=pre.env)
    shutil.rmtree(os.path.join(pre.wt, "deps"))
    r = R(pre.wt, "wave", "setup", env=pre.env)
    S.ok("marker: a folder that was there before the setup is not vouched for (the run after its removal is a no-op)", r.returncode == 0 and "already" in r.stdout, r.stdout + r.stderr)


CASES = [case_run, case_none, case_second_call, case_failing, case_dirty, case_main_checkout, case_config, case_timeout, case_check_base,
         case_prepare, case_unrelated_config, case_integrate_setup, case_io_errors, case_detached_child, case_log_cap, case_marker_validity]

# ---------------------------------------------------------------------------------------------------- the controls
# (name, case, file, old text, new text, the FAIL text it must produce); each `old` is in the file exactly once.
W, C, P = "lib/fwx/execute/worktree_setup.py", "lib/fwx/commands/wave.py", "lib/fwx/execute/prepare.py"
MUTANTS = [
    ("check-base does not call the setup", case_check_base, C,
     "    # The base is right: the agent's checks need the project's dependencies in this worktree, so the setup is part of step 0.\n",
     "    return 0\n", "setup did not run before the check"),
    ("check-base swallows a failed setup", case_check_base, C, '        sys.stderr.write("%s\\n" % e)\n        return base.SETUP_FAILED\n',
     '        sys.stderr.write("%s\\n" % e)\n        return 0\n', "a failing setup: exit 43, and the task's check did not run"),
    ("prepare does not call the setup", case_prepare, P, "    _setup(top, cfg, say)\n", "    pass\n", "setup did not run before the base check"),
    ("prepare swallows a failed setup", case_prepare, P, "    except worktree_setup.SetupFailed as e:\n        raise WaveError(str(e))\n",
     "    except worktree_setup.SetupFailed as e:\n        pass\n", "a failing setup stops the run before the base"),
    ("a failing command does not stop the sequence", case_failing, W, "                if why:\n                    raise SetupFailed(", "                if False:\n                    raise SetupFailed(",
     "failing: the earlier command ran and the later one did not"),
    ("files left behind are not refused", case_dirty, W, "    left = sorted(_status(top))", "    left = []", "dirty: an untracked, non-ignored file is refused: exit"),
    ("no marker is read", case_second_call, W, "if not force and _valid(_read_marker(marker_path), fingerprint, top):", "if False:", "second call: a no-op that says so"),
    ("the dependency files are not hashed", case_second_call, W, '"dependencies": _dependency_digest(top)}', '"dependencies": ""}',
     "a changed lockfile: the setup runs again by itself"),
    ("the main checkout is allowed", case_main_checkout, W, "    if not linked(top):", "    if False:", "main checkout: refused with exit 2"),
    ("a timeout kills the shell only", case_timeout, W, "    for kill, target in [(os.killpg, pid)] + [(os.kill, p) for p in below]:", "    for kill, target in [(os.kill, pid)]:",
     "timeout: no process is left"),
    ("a timeout kills nothing outside the group", case_detached_child, W, "    below = _descendants(pid)\n", "    below = []\n", "detached child: no process is left"),
    ("the log has no cap", case_log_cap, W, "if len(chunk) > room and not self.over:", "if False:", "log cap: a runaway output fails the setup"),
    ("the marker ignores what the setup made", case_marker_validity, W, "all(isinstance(m, str) and os.path.exists(os.path.join(top, m)) for m in made))", "True)",
     "marker: the folder the setup made is gone"),
    ("the digest ignores untracked lockfiles", case_marker_validity, W, '"--cached", "--others", "--exclude-standard", "--",', '"--cached", "--",',
     "marker: a new untracked lockfile"),
    ("a failure to write the log is a traceback", case_io_errors, W, "    except OSError as e:\n        raise WaveError(\"cannot write the log of the setup",
     "    except ZeroDivisionError as e:\n        raise WaveError(\"cannot write the log of the setup", "log is a directory: setup"),
    ("integrate does not call the setup", case_integrate_setup, "lib/fwx/execute/integrate.py", "            worktree_setup.run(top, commands)\n", "            pass\n",
     "two waves: wave 1 changes the lockfile"),
    ("check-base reads the whole configuration", case_unrelated_config, C, "worktree_setup.run(os.getcwd(), config.setup_commands(os.getcwd()))",
     'worktree_setup.run(os.getcwd(), config.load(os.getcwd())["project"]["worktree_setup"])', "config tolerance, a model table error: check-base exit"),
    ("an empty config entry is accepted", case_config, "lib/fwx/config.py", "isinstance(c, str) and c.strip() for c in setup", "isinstance(c, str) for c in setup",
     "config: worktree_setup as a blank command"),
]

if __name__ == "__main__":
    real = runner(ROOT)
    real.root = ROOT
    for case in CASES:
        case(real, s)
    for name, case, path, old, new, needle in MUTANTS:
        m = helpers.Suite()
        try:
            tree = mutant_tree(path, old, new)
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        r = runner(tree)
        r.root = tree
        case(r, m)
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
    s.done()
