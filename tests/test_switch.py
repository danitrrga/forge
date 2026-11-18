#!/usr/bin/env python3
"""`forge switch @NAME` (forge/launch.py, forge/profiles.py): change the profile of the session you are in. The launcher that
`forge start @A` runs keeps `claude` as a child in a loop; `switch` writes a request, the launcher sees it while claude runs,
ends its own child with TERM and starts `claude --resume <id>` with the other profile's flags (4.3 U5, the plan's Control and
the brief's two additions: decided points 2 and 3, and two sessions of one project).

The world is test_profiles' (an engine copy, a toy HOME, the project `multi` with the profiles `toy-b` and `list`, `none`
without `profiles`, `frozen-p`) and a PATH that holds only a fake directory (claude, python3, git; ORDERS 10). The fake claude
is driven by a plan file, one step per run of it: it logs what it was started with, then does its actions (run `forge switch`
from inside the session and log the result, write a request file by hand, wait for a file, sleep) and exits. It is a new fake
because test_launch's dumps one file per start and cannot tell the second run of one launcher from the first.

Cases (S = the session id the first run was started with):
  a  `forge list @ --session S` marks the current profile, text and --json (`current`); without a record the default is the
     current one; with no session at all nothing is marked and the output is what it was.
  b  `forge switch @list` from inside the session: claude is ended and started again with `--resume S`, the new profile's
     --settings and servers, FORGE_PROFILE the new one, no --session-id; the record says the new profile; the launcher prints
     `forge: profile toy-b → list`, exits with the last claude's code, and ran claude twice, not more. To the default label:
     no profile flags. A CLAUDE_CODE_SESSION_ID in the session (a /clear gave it a new id) is what is resumed, unless it is
     not an id.
  c  a request that is two minutes old, one for another launcher's pid, and one for an unknown profile never relaunch into a
     wrong state: the first two are ignored and deleted (one run); the third is reported and claude comes back with the old
     profile, resumed (a terminal is never left without claude).
  d  outside a session, or with a record whose launcher is not the one above the session, or a launcher that is gone:
     exit 2, one line naming `forge start @NAME`, no request written, and a `sleep` child that stands for a session it did
     not launch is still alive.
  e  inside a session the refusals of `forge start @NAME` are the same ones: an unknown name (and the closest), a profile that
     is `@-x`, a project without `profiles`, a frozen one, a folder that is no project: exit 2, one line, no request.
     `forge switch` and `forge switch @` list the profiles with the current one marked; `switch @current` says so and relaunches
     nothing.
  f  two sessions of the same project, each with its own launcher: a switch of one relaunches that one only; a request written
     for session 1 naming launcher 2's pid, or for session 2 naming launcher 1's, relaunches nobody.
  g  `forge start NAME` with a launcher name behaves as before (test_launch covers it; here only that `switch` is not mixed in).

Negative controls (a copy of the engine with one line broken, run through the same scenario; the check must fail with the
message after the arrow, which is what the version without the behaviour printed). They run at the end of this file as
CONTROLS, so the harness is reused and nothing is kept as a one-off script:
  b  a loop that ignores the request            -> "relaunch missing: 1 run(s), want 2"
  c  a loop that accepts an old request         -> "stale request obeyed: 2 run(s), want 1"
  c  a loop that accepts another pid's request  -> "foreign request obeyed: 2 run(s), want 1"
  d  a switch that needs no launcher            -> "request written for a session without a launcher"
  d  a switch that signals the record's pid     -> "killed a session it did not launch" (the sleeping child is the witness)
  e  a start/switch that skips the name check   -> "e: an unknown name: exit 2, one line, the closest: (2, 1, False), want (2, 1, True)"
     (resolve() still refuses the unknown name, so no request is written; what is lost is the closest-name hint)
  f  a launcher that does not look at the pid   -> "request of session 1 relaunched launcher 2"
  a  a list that does not mark                  -> "current not marked"

The red before forge switch existed (the plan's cases against master at 14a340f, `switch` not a subcommand):
  "FAIL b: relaunch missing: 1 run(s), want 2", "FAIL d: exit of a switch outside a session: 2, ... invalid choice: 'switch'"
  (an argparse exit 2 that passes the exit code by accident, so each d/e case also checks the message and the files)."""
import json
import os
import subprocess
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
import test_profiles as tp  # noqa: E402

FAKE = """#!%s
import json, os, subprocess, sys, time
log, plan_file = os.environ["FAKE_LOG"], os.environ["FAKE_PLAN"]
with open(plan_file) as fh:
    plan = json.load(fh)
n = sum(1 for x in open(log) if x.startswith('{"run"')) if os.path.exists(log) else 0
step = plan[n] if n < len(plan) else {}
def put(doc):
    with open(log, "a") as fh:
        fh.write(json.dumps(doc) + "\\n")
env = os.environ
put({"run": n, "argv": sys.argv[1:], "ppid": os.getppid(), "profile": env.get("FORGE_PROFILE"), "session": env.get("FORGE_SESSION"),
     "launcher": env.get("FORGE_LAUNCHER_PID")})
def read_peer(path):
    with open(path) as fh:
        return json.load(fh)
for act in step.get("do", []):
    kind = act[0]
    if kind == "info":  # tell the peer who this is
        with open(act[1], "w") as fh:
            json.dump({"session": env["FORGE_SESSION"], "ppid": os.getppid()}, fh)
    elif kind == "wait":
        t0 = time.time()
        while not os.path.exists(act[1]) and time.time() - t0 < 30:
            time.sleep(0.05)
    elif kind == "switch":
        e = dict(env, **(act[2] if len(act) > 2 else {}))
        r = subprocess.run([sys.executable, env["FAKE_FORGE"], "switch"] + act[1], env=e, capture_output=True, text=True, timeout=60)
        put({"switch": act[1], "rc": r.returncode, "out": r.stdout, "err": r.stderr})
    elif kind == "request":  # a request file by hand: {"for": "own"|<peer info file>, "to", "age", "pid": "ppid"|"peer"|int}
        spec = act[1]
        peer = read_peer(spec["peer"]) if spec.get("peer") else None
        sid = peer["session"] if spec.get("for") == "peer" else env["FORGE_SESSION"]
        pid = {"ppid": os.getppid(), "peer": peer and peer["ppid"]}.get(spec["pid"], spec["pid"])
        d = os.path.join(env["HOME"], ".local", "state", "forge", "profile-switch")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".json"), "w") as fh:
            json.dump({"to": spec["to"], "launcher_pid": pid, "at": time.time() - spec.get("age", 0)}, fh)
    elif kind == "sleep":
        time.sleep(act[1])
sys.exit(step.get("exit", 0))
"""
failures = []
_sink = [failures]  # where want() writes: the real run's list, or the one of a control's scenario


def want(label, got, expected):
    if got != expected:
        _sink[-1].append("%s: %s, want %s" % (label, got, expected))


def collect(fn, c):
    """The failure lines of one scenario against one world, kept apart from the real run's."""
    mine = []
    _sink.append(mine)
    try:
        return mine + fn(c)
    finally:
        _sink.pop()


class Ctx:
    """One toy world, with the fake claude on its own PATH, and the way to start a launcher in it."""

    def __init__(self, mutate=None):
        self.w = tp.World(["multi", "none", "frozen-p"], mutate=mutate, skills=tp.SKILLS + ("toy-other",))
        w = self.w
        tp.write_json(os.path.join(w.forge, "config", "mcp-registry.json"),
                      {"servers": {"toy-echo": {"type": "stdio", "command": "toy-echo", "args": [], "env": {}}}})
        tp.write_json(os.path.join(w.home, ".claude", "settings.json"),
                      {"enabledPlugins": {"p-def@m": True, "p-only-default@m": True, "toy-plugin@x": True, "p-other@m": True}})
        tp.write_json(os.path.join(w.home, ".claude.json"), {"projects": {}, "mcpServers": {}})
        self.multi = w.pp("multi")
        self.fakebin = os.path.join(w.root, "fakebin")
        os.makedirs(self.fakebin)
        with open(os.path.join(self.fakebin, "claude"), "w") as fh:
            fh.write(FAKE % sys.executable)
        os.chmod(os.path.join(self.fakebin, "claude"), 0o755)
        os.symlink(sys.executable, os.path.join(self.fakebin, "python3"))
        import shutil
        os.symlink(shutil.which("git"), os.path.join(self.fakebin, "git"))
        self.state = os.path.join(w.home, ".local", "state", "forge")
        self.scratch = sandbox.mkdtemp("forge-switch-")  # the fakes' logs and plans stay out of the world the tests compare
        self.n = 0

    def env(self, log, plan, extra=None):
        self.n += 1
        e = sandbox.bare_env(self.w.home, self.w.root, FAKE_LOG=log, FAKE_PLAN=plan,
                             FAKE_FORGE=os.path.join(self.w.forge, "bin", "forge"), **(extra or {}))
        e["PATH"] = self.fakebin
        return e

    def plan(self, steps):
        self.n += 1
        p = os.path.join(self.scratch, "plan-%d.json" % self.n)
        with open(p, "w") as fh:
            json.dump(steps, fh)
        return p, os.path.join(self.scratch, "log-%d.jsonl" % self.n)

    def launcher(self, steps, args=("@toy-b",), cwd=None, extra=None):
        """Popen of `forge start ARGS` whose fake claude follows `steps`; (process, log path)."""
        plan, log = self.plan(steps)
        p = subprocess.Popen([sys.executable, os.path.join(self.w.forge, "bin", "forge"), "start"] + list(args), cwd=cwd or self.multi,
                             env=self.env(log, plan, extra), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return p, log

    def run(self, steps, args=("@toy-b",), cwd=None, extra=None, timeout=90):
        """(exit code, stdout, stderr, the fake's log lines, seconds) of one launcher, to its end."""
        t0 = time.time()
        p, log = self.launcher(steps, args, cwd, extra)
        so, se = p.communicate(timeout=timeout)
        return p.returncode, so, se, lines(log), time.time() - t0

    def forge(self, args, cwd=None, extra=None):
        e = sandbox.bare_env(self.w.home, self.w.root, **(extra or {}))
        e["PATH"] = self.fakebin
        r = subprocess.run([sys.executable, os.path.join(self.w.forge, "bin", "forge")] + list(args), cwd=cwd or self.multi, env=e,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def switch_files(self):
        d = os.path.join(self.state, "profile-switch")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def record(self, sid):
        p = os.path.join(self.state, "profile-sessions", sid + ".json")
        return tp.read_json(p) if os.path.exists(p) else None


def lines(log):
    if not os.path.exists(log):
        return []
    with open(log) as fh:
        return [json.loads(x) for x in fh if x.strip()]


def runs(log_lines):
    return [x for x in log_lines if "run" in x]


def flag(argv, name):
    return argv[argv.index(name) + 1] if argv and name in argv and argv.index(name) + 1 < len(argv) else None


# ---- the scenarios: each returns its own failure lines so a control can run it against a broken engine -----------------------

def scenario_a(c):
    """list marks the current profile."""
    out = []
    sid = str(uuid.uuid4())
    tp.write_json(os.path.join(c.state, "profile-sessions", sid + ".json"),
                  {"profile": "toy-b", "project": "multi", "launcher_pid": 1, "at": 1.0})
    code, so, se = c.forge(["list", "@", "--session", sid, "--json"])
    rows = json.loads(so) if code == 0 else []
    cur = [r["name"] for r in rows if r.get("current")]
    if cur != ["toy-b"]:
        out.append("current not marked: %s (exit %d, %r), want ['toy-b']" % (cur, code, se))
    want_color = {r["name"]: r["color"] for r in rows}
    if want_color.get("toy-b") != "red" or any("color" not in r for r in rows):
        out.append("color missing from --json rows: %s" % want_color)
    code, so, se = c.forge(["list", "@", "--session", sid])
    marked = [x for x in so.splitlines() if x.startswith("* ")]
    if not (code == 0 and len(marked) == 1 and "toy-b" in marked[0]):
        out.append("current not marked in the text: %r" % so)
    code, so, se = c.forge(["list", "@", "--session", str(uuid.uuid4()), "--json"])
    cur = [r["name"] for r in json.loads(so) if r.get("current")] if code == 0 else None
    if cur != ["code"]:
        out.append("current not marked: %s without a record, want ['code'] (the project's default)" % cur)
    code, so, se = c.forge(["list", "@", "--json"])
    rows = json.loads(so) if code == 0 else []
    if any("current" in r for r in rows):
        out.append("a list outside any session marks one: %s" % [r["name"] for r in rows if "current" in r])
    code, so, se = c.forge(["list", "@"], extra={"FORGE_SESSION": sid})
    if not any(x.startswith("* ") and "toy-b" in x for x in so.splitlines()):
        out.append("current not marked: FORGE_SESSION of the environment is the session of `forge list @`: %r" % so)
    return out


def scenario_b(c):
    """a switch from inside the session relaunches with --resume and the new flags."""
    out = []
    code, so, se, log, secs = c.run([{"do": [["switch", ["@list"]], ["sleep", 60]], "exit": 3}, {"exit": 5}])
    rs = runs(log)
    if len(rs) != 2:
        out.append("relaunch missing: %d run(s), want 2" % len(rs))
        return out
    first, second = rs
    sid = flag(first["argv"], "--session-id")
    sw = [x for x in log if "switch" in x]
    if sw and (sw[0]["rc"] != 0 or sw[0]["err"]):
        out.append("switch from inside the session: exit %s, %r" % (sw[0]["rc"], sw[0]["err"]))
    want("b: the first run is a new session of the first profile", (bool(sid), first["profile"], "--resume" in first["argv"]), (True, "toy-b", False))
    want("b: the second run resumes the same conversation", (flag(second["argv"], "--resume"), "--session-id" in second["argv"]), (sid, False))
    want("b: the second run has the new profile's flags",
         (os.path.basename(flag(second["argv"], "--settings") or ""), os.path.basename(flag(second["argv"], "--mcp-config") or ""),
          "--strict-mcp-config" in second["argv"]), ("list.json", "list.mcp.json", True))
    want("b: FORGE_PROFILE of the second run, and the session it keeps", (second["profile"], second["session"]), ("list", sid))
    want("b: the launcher prints the change and exits with the last claude's code", (code, "forge: profile toy-b → list" in so, se), (5, True, ""))
    rec = c.record(sid)
    want("b: the record says the new profile, the same launcher", rec and (rec["profile"], rec["project"], rec["launcher_pid"]),
         ("list", "multi", int(first["launcher"])))
    want("b: the request is gone", c.switch_files(), [])
    want("b: the switch took seconds, not a hang", secs < 30, True)
    # to the default label: the project file as it is, no profile flags
    code, so, se, log, _ = c.run([{"do": [["switch", ["@code"]], ["sleep", 60]]}, {}])
    rs = runs(log)
    want("b: to the default label: two runs, no profile flags, FORGE_PROFILE the label",
         (len(rs), rs[1:] and [f for f in ("--settings", "--mcp-config", "--strict-mcp-config") if f in rs[1]["argv"]],
          rs[1:] and rs[1]["profile"], rs[1:] and "--resume" in rs[1]["argv"]), (2, [], "code", True))
    # the switch the other way back: the default label first, then a profile
    code, so, se, log, _ = c.run([{"do": [["switch", ["@toy-b"]], ["sleep", 60]]}, {}], args=("@code",))
    rs = runs(log)
    want("b: from the default label to a profile: two runs, the profile's flags", (len(rs), rs[1:] and "--settings" in rs[1]["argv"]), (2, True))
    # a /clear gave the conversation a new id: that one is resumed; a value that is not an id is not passed to claude
    new = str(uuid.uuid4())
    code, so, se, log, _ = c.run([{"do": [["switch", ["@list"], {"CLAUDE_CODE_SESSION_ID": new}], ["sleep", 60]]}, {}])
    rs = runs(log)
    want("b: the id claude reports is the one resumed", rs[1:] and flag(rs[1]["argv"], "--resume"), new)
    code, so, se, log, _ = c.run([{"do": [["switch", ["@list"], {"CLAUDE_CODE_SESSION_ID": "--model"}], ["sleep", 60]]}, {}])
    rs = runs(log)
    want("b: a value that is no id is not resumed", rs[1:] and flag(rs[1]["argv"], "--resume") == flag(rs[0]["argv"], "--session-id"), True)
    return out


def scenario_c(c):
    """old, foreign and unknown-profile requests."""
    out = []
    code, so, se, log, _ = c.run([{"do": [["request", {"to": "list", "pid": "ppid", "age": 130}]]}, {}])
    if len(runs(log)) != 1:
        out.append("stale request obeyed: %d run(s), want 1" % len(runs(log)))
    want("c: a stale request: the launcher exits with claude's code", (code, c.switch_files()), (0, []))
    code, so, se, log, _ = c.run([{"do": [["request", {"to": "list", "pid": 4000000, "age": 1}]]}, {}])
    if len(runs(log)) != 1:
        out.append("foreign request obeyed: %d run(s), want 1" % len(runs(log)))
    want("c: a request for another pid: ignored and deleted", (code, c.switch_files()), (0, []))
    code, so, se, log, _ = c.run([{"do": [["request", {"to": "ghost", "pid": "ppid", "age": 1}]]}, {}])
    rs = runs(log)
    want("c: an unknown profile: reported, claude comes back with the old one, resumed", (len(rs), "ghost" in se, rs[1:] and rs[1]["profile"],
         rs[1:] and flag(rs[1]["argv"], "--resume") == flag(rs[0]["argv"], "--session-id")), (2, True, "toy-b", True))
    want("c: an unknown profile: the request is gone, the launcher exits 0", (code, c.switch_files()), (0, []))
    return out


def scenario_d(c):
    """no session, no launcher above it."""
    out = []
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # stands for a session it did not launch
    try:
        sid = str(uuid.uuid4())
        tp.write_json(os.path.join(c.state, "profile-sessions", sid + ".json"),
                      {"profile": "toy-b", "project": "multi", "launcher_pid": sleeper.pid, "at": time.time()})
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        sid_dead = str(uuid.uuid4())
        tp.write_json(os.path.join(c.state, "profile-sessions", sid_dead + ".json"),
                      {"profile": "toy-b", "project": "multi", "launcher_pid": dead.pid, "at": time.time()})
        cases = (("outside a session", {}),
                 ("a session id with a record and no launcher environment", {"FORGE_SESSION": sid}),
                 ("a launcher pid that is not the record's", {"FORGE_SESSION": sid, "FORGE_LAUNCHER_PID": str(sleeper.pid + 1)}),
                 ("a session id with no record", {"FORGE_SESSION": str(uuid.uuid4()), "FORGE_LAUNCHER_PID": str(sleeper.pid)}),
                 ("a launcher that is gone", {"FORGE_SESSION": sid_dead, "FORGE_LAUNCHER_PID": str(dead.pid)}))
        for label, extra in cases:
            code, so, se, = c.forge(["switch", "@list"], extra=extra)
            if c.switch_files():
                out.append("request written for a session without a launcher: %s: %s" % (label, c.switch_files()))
                for f in c.switch_files():
                    os.remove(os.path.join(c.state, "profile-switch", f))
            want("d: %s: exit 2, one line that names forge start @NAME" % label,
                 (code, len(se.strip().splitlines()), "forge start @" in se, so), (2, 1, True, ""))
            if sleeper.poll() is not None:
                out.append("killed a session it did not launch: %s (exit %s)" % (label, sleeper.returncode))
                return out
    finally:
        sleeper.kill()
        sleeper.wait()
    return out


def scenario_e(c):
    """inside a session: the refusals of forge start, the list, the current profile."""
    out = []
    steps = [{"do": [["switch", ["@toy-"]], ["switch", ["@-x"]], ["switch", ["@toy-b"]], ["switch", []], ["switch", ["@"]]]}]
    code, so, se, log, _ = c.run(steps)
    sw = [x for x in log if "switch" in x]
    if len(sw) != 5:
        out.append("expected five switch results, got %d" % len(sw))
        return out
    if c.switch_files() or len(runs(log)) != 1:
        out.append("request written for an unknown profile: %s, %d run(s)" % (c.switch_files(), len(runs(log))))
    want("e: an unknown name: exit 2, one line, the closest", (sw[0]["rc"], len(sw[0]["err"].strip().splitlines()), "did you mean '@toy-b'" in sw[0]["err"]), (2, 1, True))
    want("e: a name that cannot be one: exit 2", (sw[1]["rc"], len(sw[1]["err"].strip().splitlines())), (2, 1))
    want("e: the current profile: exit 0, says so", (sw[2]["rc"], "already" in sw[2]["out"] + sw[2]["err"]), (0, True))
    for i, label in ((3, "no argument"), (4, "@")):
        rows = sw[i]["out"].splitlines()
        want("e: %s: lists the profiles, the current one marked" % label,
             (sw[i]["rc"], [r for r in rows if r.startswith("* ")] and "toy-b" in [r for r in rows if r.startswith("* ")][0]), (0, True))
    # the same reasons as forge start, in the other projects
    tests = (("a project without profiles", w_none(c), "declares no profiles"), ("a frozen project", w_frozen(c), "frozen"),
             ("a folder that is no project", c.w.home, "not inside a project"))
    for label, cwd, why in tests:
        before = c.w.files("")
        code, so, se = c.forge(["switch", "@toy-b"], cwd=cwd)
        want("e: %s: exit 2, the reason %r, one line, nothing written" % (label, why),
             (code, why in se, len(se.strip().splitlines()), c.w.files("") == before), (2, True, 1, True))
    return out


def w_none(c):
    return c.w.pp("none")


def w_frozen(c):
    return c.w.pp("frozen-p")


def scenario_f(c):
    """two sessions of one project."""
    out = []
    info1, info2 = os.path.join(c.scratch, "info-1-%d.json" % c.n), os.path.join(c.scratch, "info-2-%d.json" % c.n)
    # A: session 1 switches by the command, session 2 only waits: only session 1 relaunches.
    p2, log2 = c.launcher([{"do": [["info", info2], ["sleep", 6]]}], args=("@list",))
    p1, log1 = c.launcher([{"do": [["wait", info2], ["switch", ["@code"]], ["sleep", 60]]}, {}])
    so1, se1 = p1.communicate(timeout=90)
    so2, se2 = p2.communicate(timeout=90)
    r1, r2 = runs(lines(log1)), runs(lines(log2))
    want("f: a switch of session 1 relaunches session 1 (twice) and not session 2 (once)", (len(r1), len(r2), p1.returncode, p2.returncode), (2, 1, 0, 0))
    want("f: and session 2 stays on its profile", r2 and r2[0]["profile"], "list")
    # B: requests written for the other launcher, by hand, relaunch nobody.
    p2, log2 = c.launcher([{"do": [["info", info2], ["sleep", 6]]}], args=("@list",))
    p1, log1 = c.launcher([{"do": [["wait", info2], ["request", {"for": "own", "to": "code", "pid": "peer", "peer": info2, "age": 1}],
                                   ["request", {"for": "peer", "to": "code", "pid": "ppid", "peer": info2, "age": 1}], ["sleep", 2]]}])
    p1.communicate(timeout=90)
    p2.communicate(timeout=90)
    r1, r2 = runs(lines(log1)), runs(lines(log2))
    if len(r1) != 1:
        out.append("request of session 1 relaunched launcher 2's pid: launcher 1 ran %d time(s), want 1" % len(r1))
    if len(r2) != 1:
        out.append("request of session 1 relaunched launcher 2: %d run(s), want 1" % len(r2))
    return out


def scenarios(c):
    return {"a": scenario_a, "b": scenario_b, "c": scenario_c, "d": scenario_d, "e": scenario_e, "f": scenario_f}


# (name of the scenario, file, text to replace, replacement, the message the scenario must print)
CONTROLS = (
    ("b", "forge/launch.py", "profiles.take_switch(sid, me)", "None", "relaunch missing"),
    ("c", "forge/profiles.py", "now - req[\"at\"] > SWITCH_TTL", "False", "stale request obeyed"),
    ("c", "forge/profiles.py", "req[\"launcher_pid\"] != pid", "False", "foreign request obeyed"),
    ("d", "forge/launch.py", "rec = _launcher_above(sid)", "rec = _launcher_above(sid) or {\"launcher_pid\": 1, \"project\": project, \"profile\": \"x\"}",
     "request written for a session without a launcher"),
    ("d", "forge/launch.py", "rec = _launcher_above(sid)", "rec = _launcher_above(sid)\n    if rec is None and profiles.read_session(sid):\n        os.kill(profiles.read_session(sid)[\"launcher_pid\"], 15)",
     "killed a session it did not launch"),
    ("e", "forge/launch.py", "if profile not in known:", "if False:", "e: an unknown name: exit 2, one line, the closest"),
    ("f", "forge/profiles.py", "req[\"launcher_pid\"] != pid", "False", "relaunched launcher 2"),
    ("a", "forge/profiles.py", "r[\"current\"] = r[\"name\"] == current", "r[\"current\"] = False", "current not marked"),
)


def main():
    try:
        return run_all()
    finally:
        sandbox.cleanup()  # also when a case raised: a test that leaves a folder in /tmp is a bug in that test (ORDERS 14)


def run_all():
    c = Ctx()
    for name, fn in scenarios(c).items():
        failures.extend(collect(fn, c))
    # g: a launcher name is not a profile: `forge switch` is not mixed into it
    code, so, se = c.forge(["start", "nolauncher"])
    want("g: forge start NAME with no such launcher is still exit 2 naming it", (code, "nolauncher" in se), (2, True))
    if "--controls" in sys.argv or not os.environ.get("FORGE_SWITCH_NO_CONTROLS"):
        for name, rel, old, new, message in CONTROLS:
            try:
                m = Ctx(mutate=(rel, old, new))
            except AssertionError as e:
                failures.append("control %s: %s" % (name, e))
                continue
            got = collect(scenarios(m)[name], m)
            if not any(message in x for x in got):
                failures.append("control %s (%s -> %s) did not fail with %r: %s" % (name, old[:40], new[:20], message, got))
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print("ok: switch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
