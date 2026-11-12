#!/usr/bin/env python3
"""`fwx capacity` (3.4 U1): lib/fwx/commands/capacity.py, the `limits` defaults of lib/fwx/config.py.

Every case goes through `bin/fwx capacity` in a toy repo. Nothing here depends on this machine's memory: MemAvailable comes
from a fake meminfo file (`FWX_MEMINFO`), the quota from a budget file in the toy repo's git dir, and the live executors are
planted: a `sleep` for a live agent (its pid and the start time of /proc/<pid>/stat go into the worktree's lock, as Claude Code
writes them), a finished one for a dead agent.

Seen red before the command existed (bin/fwx exited 2 "unknown command: capacity"; first lines of python3 tests/test_capacity.py):
  FAIL: no limits.per_project, want 5: allowed=<no JSON object>, want 3: got '<no JSON object>', want 3
  FAIL: no limits.per_project: exit 0 with room: got 2, want 0
  FAIL: ram_min_free_gb above the free RAM: exit: got 2, want 1
  FAIL: three live, cap 3: exit 1: got 2, want 1

Controls: each case also runs on a copy of bin/ and lib/ with one line changed (`MUTANTS`, each `old` must be in its file exactly
once) and must fail with the text shown (the good code passes first; 119 checks with the controls). The FAIL line of each:
  no RAM brake:                  FAIL: ram_min_free_gb above the free RAM: allowed=3, want 0: got 3, want 0
  the exit ignores allowed:      FAIL: ram_min_free_gb above the free RAM: exit: got 0, want 1
  the room rounds up:            FAIL: 3.9 GB free: room for one executor: got 2, want 1
  running not subtracted:        FAIL: one live agent, cap 3: allowed=3, want 2: got 3, want 2
  every lock counts:             FAIL: a lock with a dead pid: allowed 2 with a dead pid, want 3: got 2, want 3
  any live lock counts:          FAIL: ... locks that are not Claude Code's: running: got 1, want 0
  no cap by plane:               FAIL: no limits.per_project, want 5: allowed=5, want 3: got 5, want 3
  --unattended ignored:          FAIL: unattended allowed 3, want 4: got 3, want 4
  limits.per_project ignored:    FAIL: limits.per_project.executor 2 supervised: allowed=3, want 2: got 3, want 2
  --per-agent-mb ignored:        FAIL: read-only role, room for 2, --per-agent-mb 1024: allowed=4, want 2: got 4, want 2
  read-only counted as worktree: FAIL: read-only role: running is not counted: got 1, want 'not counted (read-only role)'
  limits.on ignored:             FAIL: limits.on false: allowed=<no JSON object>, want 5: got ('<no JSON object>', 77), want (5, 0)
  limits.on False by default:    FAIL: no configuration file: the limits are on: got 9, want 3
  a limit of 0 accepted:         FAIL: limits.per_project.executor 0: exit 2: got 1, want 2
  an unknown role accepted:      FAIL: unknown role: exit 2: got 0, want 2
  no meminfo is zero RAM:        FAIL: no meminfo: exit: got 1, want 77
  --wait ignored:                FAIL: --wait 4, the RAM is back after 1 s: exit and allowed: got (1, 0), want (0, 2)
  --wait sleeps a whole interval: FAIL: --wait 1, never any room: it waited: took 15.0 s
  the quota is never read:       FAIL: a tight week: week_tight in the report: got 'unknown', want True
  a tight week caps allowed:     FAIL: a tight week: allowed is not changed by it: got 0, want 3
  no /proc is exit 2:            FAIL: no /proc, an executor: exit: got 2, want 77
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
from test_wave_prepare import mutant_tree, runner  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
GB = 1024 * 1024  # kB per GiB


class Scene:
    """A main checkout on master with a linked worktree `phase` (where the session runs), a fake meminfo and planted agents."""

    def __init__(self, limits=None, on=True):
        self.repo = helpers.toy_repo({"README": "toy\n", ".gitignore": ".claude/\n"})
        if limits is not None or not on:
            lim = dict(limits or {})
            if not on:
                lim["on"] = False
            helpers.write(self.repo, ".claude/fwx.json", json.dumps({"schema": 1, "limits": lim}))
        self.cwd = helpers.add_worktree(self.repo, "phase")
        self.meminfo = os.path.join(helpers.mkdtemp("fwx-mem-"), "meminfo")
        self.ram(8)
        self.procs = []
        self.n = 0

    def ram(self, gb):
        """MemAvailable of the fake /proc/meminfo, in GiB (other lines as the real file has them)."""
        with open(self.meminfo, "w") as f:
            f.write("MemTotal:       32000000 kB\nMemFree:          100000 kB\nMemAvailable:   %d kB\nBuffers:           1000 kB\n" % int(gb * GB))

    def tree(self, lock=None, branch=None):
        """A linked worktree (an agent's, when `lock` is its lock reason); returns its path."""
        self.n += 1
        name = branch or "worktree-agent-t%d" % self.n
        wt = os.path.join(helpers.mkdtemp("fwx-agent-"), name)
        helpers.git(self.repo, "worktree", "add", "-q", "-b", name, wt, "phase")
        if lock is not None:
            helpers.git(self.repo, "worktree", "lock", "--reason", lock, wt)
        return wt

    def live(self):
        p = subprocess.Popen(["sleep", "300"])
        self.procs.append(p)
        return p.pid, start_of(p.pid)

    def dead(self):
        p = subprocess.Popen(["sleep", "300"])
        start = start_of(p.pid)
        p.kill()
        p.wait()
        return p.pid, start

    def agent(self, who="live", form="claude agent agent-%s (pid %d start %s)", ident="a1b2"):
        if who == "other-start":
            pid, start = self.live()[0], "1"
        else:
            pid, start = self.live() if who == "live" else self.dead()
        return self.tree(form % (ident, pid, start))

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
        self.procs = []

    def budget(self, sid, week_used, week_elapsed_pct):
        sessions = os.path.join(self.repo, ".git", "fwx", "sessions")
        os.makedirs(sessions, exist_ok=True)
        resets = time.time() + (100 - week_elapsed_pct) / 100 * 7 * 86400
        rl = {"five_hour": {"used_percentage": 5, "resets_at": time.time() + 3600},
              "seven_day": {"used_percentage": week_used, "resets_at": resets}}
        with open(os.path.join(sessions, sid + ".budget.json"), "w") as f:
            json.dump({"context_window": {"used_percentage": 10, "remaining_percentage": 90}, "rate_limits": rl,
                       "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, f)

    def cap(self, R, *args, env=None, cwd=None):
        """(exit, stdout JSON or None, the CompletedProcess) of `fwx capacity <args> --json`."""
        e = {"FWX_MEMINFO": self.meminfo, "CLAUDE_CODE_SESSION_ID": ""}
        e.update(env or {})
        r = R(cwd or self.cwd, "capacity", *args, "--json", env=e)
        try:
            data = json.loads(r.stdout)
        except ValueError:
            data = None
        return r.returncode, data, r


def start_of(pid):
    with open("/proc/%d/stat" % pid) as f:
        return f.read().rsplit(")", 1)[1].split()[19]


def field(d, k):
    return d.get(k) if isinstance(d, dict) else "<no JSON object>"


def case_defaults(R, s):
    """The default cap: 3, and 4 with --unattended; limits.per_project overrides both."""
    sc = Scene()
    rc, d, r = sc.cap(R, "--role", "executor", "--want", "5")
    s.eq("no limits.per_project, want 5: allowed=%s, want 3" % field(d, "allowed"), field(d, "allowed"), 3)
    s.eq("no limits.per_project: exit 0 with room", rc, 0)
    s.eq("no limits.per_project: limit", field(d, "limit"), 3)
    s.ok("no limits.per_project: reasons say where the cap comes from", "default cap" in " ".join(field(d, "reasons") or []),
         "reasons %r" % field(d, "reasons"))
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "5", "--unattended")
    s.eq("unattended allowed %s, want 4" % field(d, "allowed"), field(d, "allowed"), 4)
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "2")
    s.eq("want under the cap: allowed", field(d, "allowed"), 2)
    for flag in ((), ("--unattended",)):
        sc2 = Scene({"per_project": {"executor": 2}})
        rc, d, _ = sc2.cap(R, "--role", "executor", "--want", "5", *flag)
        s.eq("limits.per_project.executor 2 %s: allowed=%s, want 2" % (flag or "supervised", field(d, "allowed")), field(d, "allowed"), 2)
        s.ok("limits.per_project: reasons name it", "limits.per_project" in " ".join(field(d, "reasons") or []), "reasons %r" % field(d, "reasons"))
    sc3 = Scene({"per_project": {"executor": 6}})
    rc, d, _ = sc3.cap(R, "--role", "executor", "--want", "9")
    s.eq("limits.per_project.executor 6 above the default: allowed", field(d, "allowed"), 6)
    sc4 = Scene({"default_cap": {"supervised": 2, "unattended": 5}})
    s.eq("limits.default_cap.supervised 2: allowed", field(sc4.cap(R, "--role", "executor", "--want", "9")[1], "allowed"), 2)
    s.eq("limits.default_cap.unattended 5: allowed", field(sc4.cap(R, "--role", "executor", "--want", "9", "--unattended")[1], "allowed"), 5)


def case_ram_floor(R, s):
    """A free RAM under the floor is allowed 0 and exit 1; the reserve per executor makes the rest of the room."""
    sc = Scene({"ram_min_free_gb": 100})
    rc, d, r = sc.cap(R, "--role", "executor", "--want", "5")
    s.eq("ram_min_free_gb above the free RAM: allowed=%s, want 0" % field(d, "allowed"), field(d, "allowed"), 0)
    s.eq("ram_min_free_gb above the free RAM: exit", rc, 1)
    s.eq("the free RAM is reported", field(d, "ram_free_gb"), 8.0)
    s.eq("the floor is reported", field(d, "ram_min_gb"), 100)
    s.ok("the reason names the floor", "floor" in " ".join(field(d, "reasons") or []), "reasons %r" % field(d, "reasons"))
    sc = Scene()
    sc.ram(2.9)
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "3")
    s.eq("default floor 3 GB, 2.9 GB free: allowed=%s, want 0" % field(d, "allowed"), (rc, field(d, "allowed")), (1, 0))
    sc.ram(3.9)  # 0.9 GB over the floor, 0.5 GB reserved per executor: room for 1
    s.eq("3.9 GB free: room for one executor", field(sc.cap(R, "--role", "executor", "--want", "3")[1], "allowed"), 1)
    sc.ram(4.0)
    s.eq("4.0 GB free: room for two", field(sc.cap(R, "--role", "executor", "--want", "3")[1], "allowed"), 2)
    sc2 = Scene({"ram_per_agent_mb": 1024})
    sc2.ram(5.0)
    s.eq("limits.ram_per_agent_mb 1024, 5 GB free: room for two", field(sc2.cap(R, "--role", "executor", "--want", "3")[1], "allowed"), 2)
    sc2.stop()


def case_running(R, s):
    """Only a worktree locked by a live `claude agent` counts; a dead pid, another start or another lock does not."""
    sc = Scene()
    sc.agent("live")
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "5")
    s.eq("one live agent, cap 3: allowed=%s, want 2" % field(d, "allowed"), field(d, "allowed"), 2)
    s.eq("one live agent: running", field(d, "running"), 1)
    s.ok("counted_from names the worktree list", "git worktree list" in str(field(d, "counted_from")), "counted_from %r" % field(d, "counted_from"))
    sc.stop()

    sc = Scene()
    sc.agent("live")
    sc.agent("live", form="claude agent wf_%s-1 (pid %d start %s)", ident="71ceafe1")
    s.eq("a live agent and a live workflow executor: running", field(sc.cap(R, "--role", "executor", "--want", "5")[1], "running"), 2)
    s.eq("two live, cap 3: allowed", field(sc.cap(R, "--role", "executor", "--want", "5")[1], "allowed"), 1)
    s.eq("three live, cap 3: exit 1", (sc.agent("live") and sc.cap(R, "--role", "executor", "--want", "5")[0]), 1)
    sc.stop()

    sc = Scene()
    sc.agent("dead")
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "5")
    s.eq("a lock with a dead pid: allowed %s with a dead pid, want 3" % field(d, "allowed"), field(d, "allowed"), 3)
    s.eq("a lock with a dead pid: running", field(d, "running"), 0)
    sc.agent("other-start")
    s.eq("a live pid with another start: running", field(sc.cap(R, "--role", "executor", "--want", "5")[1], "running"), 0)
    sc.tree()  # an agent's worktree that finished with work: no lock
    sc.tree(branch="feature-x")  # not an agent's
    sc.tree(lock="claude agent agent-q (pid not-a-number)")
    pid, start = sc.live()
    sc.tree(lock="some other tool (pid %d start %s)" % (pid, start))
    sc.tree(lock="held by hand")
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "5")
    s.eq("an unlocked worktree, a branch that is no agent's, and locks that are not Claude Code's: running", field(d, "running"), 0)
    s.eq("... allowed", field(d, "allowed"), 3)
    sc.stop()

    # the count is the repository's, whichever worktree asks
    sc = Scene()
    sc.agent("live")
    s.eq("asked from the main checkout: running", field(sc.cap(R, "--role", "executor", "--want", "5", cwd=sc.repo)[1], "running"), 1)
    sc.stop()


def case_read_only(R, s):
    """A read-only role (no worktree): RAM and limits.per_project only; --per-agent-mb is the size of one."""
    sc = Scene()
    sc.ram(5.0)
    sc.agent("live")  # an executor alive does not count against a walker
    rc, d, _ = sc.cap(R, "--role", "ui-walker", "--want", "5", "--per-agent-mb", "1024")
    s.eq("read-only role, room for 2, --per-agent-mb 1024: allowed=%s, want 2" % field(d, "allowed"), field(d, "allowed"), 2)
    s.eq("read-only role: running is not counted", field(d, "running"), "not counted (read-only role)")
    s.eq("read-only role: exit", rc, 0)
    rc, d, _ = sc.cap(R, "--role", "ui-walker", "--want", "5")
    s.eq("read-only role without --per-agent-mb: the configured 512 MB, room for 4", field(d, "allowed"), 4)
    rc, d, _ = sc.cap(R, "--role", "ui-walker", "--want", "5", "--per-agent-mb", "4096")
    s.eq("read-only role, room for none: allowed and exit", (field(d, "allowed"), rc), (0, 1))
    sc2 = Scene({"per_project": {"reviewer": 1}})
    rc, d, _ = sc2.cap(R, "--role", "reviewer", "--want", "4", "--per-agent-mb", "100")
    s.eq("read-only role, limits.per_project.reviewer 1: allowed", field(d, "allowed"), 1)
    s.eq("read-only role, limits.per_project.reviewer 1: limit", field(d, "limit"), 1)
    rc, d, _ = sc.cap(R, "--role", "reviewer", "--want", "4", "--per-agent-mb", "100")
    s.eq("read-only role without a per_project entry: only the RAM and want cap it", field(d, "allowed"), 4)
    sc.stop()


def case_off(R, s):
    """limits.on false: allowed = want, whatever the RAM and the agents, and no RAM is read."""
    sc = Scene({"ram_min_free_gb": 100}, on=False)
    sc.agent("live")
    sc.agent("live")
    sc.agent("live")
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "5", env={"FWX_MEMINFO": "/nonexistent/meminfo"})
    s.eq("limits.on false: allowed=%s, want 5" % field(d, "allowed"), (field(d, "allowed"), rc), (5, 0))
    s.eq("limits.on false: no RAM read", field(d, "ram_free_gb"), None)
    rc, d, _ = sc.cap(R, "--role", "ui-walker", "--want", "7")
    s.eq("limits.on false, read-only role: allowed", field(d, "allowed"), 7)
    sc.stop()
    sc = Scene()  # no file at all: the defaults are on
    s.eq("no configuration file: the limits are on", field(sc.cap(R, "--role", "executor", "--want", "9")[1], "allowed"), 3)


def case_usage(R, s):
    """What it refuses: a bad limit (named), an unknown role, a missing flag; no meminfo is NOT RUN, not a number."""
    sc = Scene({"per_project": {"executor": 0}})
    rc, d, r = sc.cap(R, "--role", "executor", "--want", "2")
    s.eq("limits.per_project.executor 0: exit 2", rc, 2)
    s.ok("limits.per_project.executor 0: the message names it", "limits.per_project.executor" in r.stderr, "stderr %r" % r.stderr)
    sc = Scene({"per_project": {"executor": "three"}})
    rc, d, r = sc.cap(R, "--role", "executor", "--want", "2")
    s.eq("limits.per_project.executor 'three': exit 2", rc, 2)
    s.ok("... named", "limits.per_project.executor" in r.stderr and "three" in r.stderr, "stderr %r" % r.stderr)
    sc = Scene()
    rc, d, r = sc.cap(R, "--role", "executor", "--want", "2", "--per-agent-mb", "0")
    s.eq("--per-agent-mb 0: exit 2", rc, 2)
    rc, d, r = sc.cap(R, "--role", "nobody", "--want", "2")
    s.eq("unknown role: exit 2", rc, 2)
    s.ok("unknown role: the roles are named", "executor" in r.stderr and "ui-walker" in r.stderr, "stderr %r" % r.stderr)
    s.eq("no --want: exit 2", sc.cap(R, "--role", "executor")[0], 2)
    s.eq("no --role: exit 2", sc.cap(R, "--want", "2")[0], 2)
    s.eq("--want two: exit 2", sc.cap(R, "--role", "executor", "--want", "two")[0], 2)
    s.eq("an option nobody knows: exit 2", sc.cap(R, "--role", "executor", "--want", "2", "--fast")[0], 2)
    rc, d, r = sc.cap(R, "--role", "executor", "--want", "2", cwd=helpers.mkdtemp("fwx-nogit-"))
    s.eq("outside a repository: exit 2", rc, 2)
    # no meminfo: not a number, and not a pass either
    rc, d, r = sc.cap(R, "--role", "executor", "--want", "2", env={"FWX_MEMINFO": "/nonexistent/meminfo"})
    s.eq("no meminfo: exit", rc, 77)
    s.ok("no meminfo: NOT RUN, NOT ARMED on stderr", "NOT RUN, NOT ARMED: no /nonexistent/meminfo" in r.stderr, "stderr %r" % r.stderr)
    with open(sc.meminfo, "w") as f:
        f.write("MemTotal: 1 kB\n")
    rc, d, r = sc.cap(R, "--role", "executor", "--want", "2")
    s.eq("meminfo without MemAvailable: exit 2", rc, 2)
    s.ok("... named", "MemAvailable" in r.stderr, "stderr %r" % r.stderr)


def case_wait(R, s):
    """--wait S asks again every 15 s (never past S) until there is room."""
    sc = Scene()
    sc.ram(1)
    t0 = time.monotonic()
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "2")
    s.ok("no --wait: answers at once", time.monotonic() - t0 < 2.0, "took %.1f s" % (time.monotonic() - t0))
    s.eq("no --wait, no room: exit", rc, 1)
    t0 = time.monotonic()
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "2", "--wait", "1")
    took = time.monotonic() - t0
    s.eq("--wait 1, never any room: exit", rc, 1)
    s.ok("--wait 1, never any room: it waited", 0.9 <= took < 5, "took %.1f s" % took)
    timer = threading.Timer(1.0, sc.ram, args=(8,))
    timer.start()
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "2", "--wait", "4")
    timer.join()
    s.eq("--wait 4, the RAM is back after 1 s: exit and allowed", (rc, field(d, "allowed")), (0, 2))


def case_quota(R, s):
    """The quota is reported from the saved budget, as information: it never changes `allowed`."""
    sc = Scene()
    sc.budget("s-tight", 90, 40)
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "5", env={"CLAUDE_CODE_SESSION_ID": "s-tight"})
    q = field(d, "quota")
    s.eq("a tight week: week_tight in the report", q.get("week_tight") if isinstance(q, dict) else q, True)
    s.eq("a tight week: allowed is not changed by it", field(d, "allowed"), 3)
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "5")
    s.eq("no session: quota unknown", field(d, "quota"), "unknown")
    rc, d, _ = sc.cap(R, "--role", "executor", "--want", "5", env={"CLAUDE_CODE_SESSION_ID": "s-missing"})
    s.eq("a session with no budget file: quota unknown", field(d, "quota"), "unknown")


def case_text(R, s):
    """Without --json: the first line is `allowed N`, then what it looked at and where the cap comes from."""
    sc = Scene()
    sc.agent("live")
    r = R(sc.cwd, "capacity", "--role", "executor", "--want", "5", env={"FWX_MEMINFO": sc.meminfo, "CLAUDE_CODE_SESSION_ID": ""})
    lines = r.stdout.splitlines()
    s.eq("text: first line", lines[0] if lines else None, "allowed 2")
    s.eq("text: exit", r.returncode, 0)
    s.ok("text: says the free RAM and the cap's source", "8.0 GB" in r.stdout and "default cap" in r.stdout, "stdout %r" % r.stdout)
    s.ok("text: says what it counted", "running 1" in r.stdout and "git worktree list" in r.stdout, "stdout %r" % r.stdout)
    sc.stop()


def case_no_proc(R, s):
    """Without /proc the agents cannot be counted: NOT RUN, NOT ARMED and exit 77, never a number (a tree whose cleanup.PROC
    names a folder that is not there stands in for a machine with none)."""
    tree = helpers.mkdtemp("fwx-noproc-")
    for d in ("bin", "lib"):
        shutil.copytree(os.path.join(R.root, d), os.path.join(tree, d), ignore=shutil.ignore_patterns("__pycache__"))
    p = os.path.join(tree, "lib", "fwx", "execute", "cleanup.py")
    text = open(p, encoding="utf-8").read()
    assert text.count('PROC = "/proc"') == 1
    open(p, "w", encoding="utf-8").write(text.replace('PROC = "/proc"', 'PROC = "/nonexistent-proc"'))
    sc = Scene()
    sc.agent("live")  # a lock to read: only then is liveness asked
    rc, d, r = sc.cap(runner(tree), "--role", "executor", "--want", "2")
    sc.stop()
    s.eq("no /proc, an executor: exit", rc, 77)
    s.ok("no /proc: NOT RUN, NOT ARMED: no /proc on stderr", "NOT RUN, NOT ARMED: no /proc" in r.stderr, "stderr %r" % r.stderr)


CASES = [case_defaults, case_ram_floor, case_running, case_read_only, case_off, case_usage, case_wait, case_quota, case_text,
         case_no_proc]
C = "lib/fwx/commands/capacity.py"
MUTANTS = [
    ("no RAM brake", case_ram_floor, C, 'min(want, res["limit"] - len(live), room))', 'min(want, res["limit"] - len(live)))',
     "ram_min_free_gb above the free RAM: allowed="),
    ("the exit ignores allowed", case_ram_floor, C, "return 0 if res[\"allowed\"] > 0 else 1", "return 0", "above the free RAM: exit"),
    ("the room rounds up", case_ram_floor, C, "math.floor(", "math.ceil(", "3.9 GB free: room for one executor"),
    ("running agents are not subtracted", case_running, C, 'min(want, res["limit"] - len(live), room))', 'min(want, res["limit"], room))',
     "one live agent, cap 3: allowed="),
    ("every lock counts", case_running, C, 'and cleanup.lock_state(w) == "live"', "and True", "allowed 2 with a dead pid, want 3"),
    ("any live lock counts, Claude Code's or not", case_running, C, '_AGENT_LOCK.match(w["locked"] or "") and ', "",
     "locks that are not Claude Code's: running"),
    ("no cap by plane", case_defaults, C, 'res["limit"] = lim["default_cap"][kind]', 'res["limit"] = want', "no limits.per_project, want 5: allowed=5, want 3"),
    ("--unattended ignored", case_defaults, C, 'kind = "unattended" if unattended else "supervised"', 'kind = "supervised"',
     "unattended allowed 3, want 4"),
    ("limits.per_project ignored", case_defaults, C, 'per = lim["per_project"].get(role)', "per = None", "limits.per_project.executor 2 supervised: allowed="),
    ("--per-agent-mb ignored", case_read_only, C, "per_mb = per_agent_mb if per_agent_mb is not None else lim[\"ram_per_agent_mb\"]",
     'per_mb = lim["ram_per_agent_mb"]', "read-only role, room for 2, --per-agent-mb 1024: allowed="),
    ("a read-only role is counted like an executor", case_read_only, C, "if role in WORKTREE_ROLES:", "if True:", "read-only role: running is not counted"),
    ("limits.on ignored", case_off, C, 'if not lim["on"]:', "if False:", "limits.on false: allowed="),
    ("limits.on false by default", case_off, "lib/fwx/config.py", '"limits": {"on": True,', '"limits": {"on": False,',
     "no configuration file: the limits are on"),
    ("a limit of 0 accepted", case_usage, C, "if role in per and not _count(per[role]):", "if False:", "limits.per_project.executor 0: exit 2"),
    ("an unknown role accepted", case_usage, C, 'if got["role"] not in config.ROLES:', "if False:", "unknown role: exit 2"),
    ("no meminfo is zero RAM", case_usage, C, 'raise NotRun("no %s" % path)', "return 0.0", "no meminfo: exit"),
    ("--wait ignored", case_wait, C, "time.sleep(min(INTERVAL_S, left))", "break", "--wait 4, the RAM is back after 1 s"),
    ("--wait sleeps a whole interval past S", case_wait, C, "time.sleep(min(INTERVAL_S, left))", "time.sleep(INTERVAL_S)", "--wait 1, never any room: it waited"),
    ("the quota is never read", case_quota, C, 'return budget.quota(data.get("rate_limits"), now)', 'return "unknown"', "a tight week: week_tight in the report"),
    ("a tight week caps allowed", case_quota, C, 'res["allowed"] = max(0, min(want, res["limit"] - len(live), room))',
     'res["allowed"] = 0 if isinstance(q, dict) and q["week_tight"] else max(0, min(want, res["limit"] - len(live), room))',
     "a tight week: allowed is not changed by it"),
    ("no /proc is exit 2", case_no_proc, C, "    except cleanup.NoProc as e:\n        sys.stderr.write(\"fwx capacity: %s\\n\" % e)\n        return 77",
     "    except cleanup.NoProc as e:\n        sys.stderr.write(\"fwx capacity: %s\\n\" % e)\n        return 2", "no /proc, an executor: exit"),
]


if __name__ == "__main__":
    if not os.path.isdir("/proc"):
        s.not_run("no /proc")
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
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
    s.done()
