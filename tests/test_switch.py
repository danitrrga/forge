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
     for session 1 naming launcher 2's pid, or for session 2 naming launcher 1's, relaunches nobody. Session 2 stays until the
     test creates a file, not for a number of seconds, so a slow machine cannot make the check look at nothing.
  g  `forge start NAME` with a launcher name behaves as before (test_launch covers it; here only that `switch` is not mixed in).
  h  a TERM, and a HUP, sent to the launcher while claude takes 3 s to end for a switch: the launcher ends and claude is not
     started again.
  i  the relaunch keeps --model, --permission-mode, --dangerously-skip-permissions, --effort and --add-dir (every value) as they
     were given, in `--opt value` and `--opt=value` form and again at a second switch; the prompt is not repeated; any other
     flag is named on the launcher's line (`; not carried over: --agent, --odd`), and nothing is said when nothing was dropped.
  j  a session started with -p (or --print): `forge switch` exits 2 with one line naming -p, no request, no relaunch.
  k  a claude that ignores TERM is killed after KILL_AFTER (1 s in that world, so the case takes seconds) and the new one starts.
  l  whatever fails while a switch is honoured (here the registry is no object: an AttributeError), claude comes back with the profile
     it had, resumed, and one line says why; no traceback.
  m  the profile asked for is looked up in the project file as it is now: one added since the start can be switched to.
  n  a request the watch accepted is honoured although claude took seconds to end and the request is older than the limit by then.
  o  `forge start NAME` (a named launcher) run inside a switchable session does not inherit FORGE_SESSION and FORGE_LAUNCHER_PID.
  p  `forge start @A --resume UUID` (also `--resume=UUID`, `-r UUID`) is switchable, the record under that id and --resume not named as
     dropped; a title, `-c` and a bare `--resume` are refused by `forge switch`.
  i  also: --disallowedTools / --allowedTools (and the --disallowed-tools / --allowed-tools spellings) come back with every value.

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
  e  a switch with no name check and no profile build (resolve() is the second guard, through _flags)
                                                 -> "request written for an unknown profile: [], 2 run(s)"
  h  a launcher that starts claude again after TERM/HUP -> "SIGTERM to the launcher during a switch: claude was started again: 2 run(s), want 1"
  i  a relaunch without the carried options     -> "i: --model keeps its value: None, want haiku"
  i  a relaunch that names nothing it dropped   -> "i: what is dropped is named on the launcher's line: False, want True"
  j  a switch that does not look at -p          -> "j: -p: the switch is refused with one line naming -p: (0, 0, False, ...), want (2, 1, True, '')"
  k  a loop that never kills                    -> "k: a claude that ignores TERM was not killed: the launcher took 10.2 s with KILL_AFTER 1 ..."
  f  a launcher that does not look at the pid   -> "request of session 1 relaunched launcher 2"
  l  an `except` that is ProfileError and OSError only -> "l: a failure that is no ProfileError: claude comes back ..."
  m  a launcher that looks the profile up in the project as it was at the start -> "m: a profile added while the session runs ..."
  n  a launcher that reads the request again after claude ended -> "n: an accepted request is honoured after a slow end ..."
  o  a named launcher that keeps the outer session's variables -> "o: a named launcher ..."
  p  a start that records no id of a resume       -> "p: --resume ID: relaunch missing: 1 run(s), want 2"
  h  a watch that never fires                     -> "h: SIGTERM: the switch did not end claude with TERM ... the case looked at nothing"
  i  tool lists left out of the carried options   -> "i: --disallowedTools keeps all its values"
  i  options carried at the first relaunch only   -> "i: a second switch carries the options again: None, want haiku"
  a  a list that does not mark                  -> "current not marked"

The red of the external review's round (cases against 4c5e2de): "m: ... (2, 'toy-b', 'toy-b.json'), want (2, 'late', 'late.json')", "n: ... (1, []),
want (2, 'list')", "o: ... (1, 'outer-session', '4242'), want (1, None, None)", "p: --resume ID: relaunch missing: 1 run(s), want 2". Case l cannot be
red against 4c5e2de: its launcher looked the profile up in the project as it was at the start, so only the new lookup reaches the failing
build; its control (the narrow `except` back) prints "l: a failure that is no ProfileError ...: (1, [], []), want (2, 'list', True)".
The four test findings: a ("a: a list outside any session: exit 0 and the profiles: (2, []), want (0, ['code', 'list', 'toy-b'])" when that list
exits 2), f part B (a fake that dies before writing: "f: both foreign requests were written, as meant: [], want [...]", "f: both launchers
exit 0: (1, 0), want (0, 0)"), h and the second relaunch (controls below). The base head also failed `control f` intermittently: the
peer file was read half written.

The red of the fix round (the cases h, i and j against b56990f): "SIGTERM to the launcher during a switch: claude was started again:
2 run(s), want 1", "i: --model keeps its value: None, want haiku", "j: -p: ... (0, 0, False, ...), want (2, 1, True, '')". Case f's part B
had read the info file of part A's launcher 2 (gone) as its peer; it has a file of its own now.

The red before forge switch existed (the plan's cases against master at 14a340f, `switch` not a subcommand):
  "FAIL b: relaunch missing: 1 run(s), want 2", "FAIL d: exit of a switch outside a session: 2, ... invalid choice: 'switch'"
  (an argparse exit 2 that passes the exit code by accident, so each d/e case also checks the message and the files)."""
import json
import os
import signal
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
import json, os, signal, subprocess, sys, time
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
        with open(act[1] + ".tmp", "w") as fh:  # atomic: a peer that reads it while it is written would get half a JSON (CodeRabbit, 446)
            json.dump({"session": env["FORGE_SESSION"], "ppid": os.getppid()}, fh)
        os.replace(act[1] + ".tmp", act[1])
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
        put({"request": {"sid": sid, "pid": pid, "to": spec["to"]}})  # what was written, and that it was
    elif kind == "edit":  # a user edits a file of the engine copy while claude runs: {"a.b": value} sets that nested key, null removes it
        p = os.path.join(os.path.dirname(os.path.dirname(env["FAKE_FORGE"])), act[1])
        doc = json.load(open(p)) if os.path.exists(p) else {}
        for dotted, value in act[2].items():
            if dotted == "=":  # the whole document
                doc = value
                continue
            d, keys = doc, dotted.split(".")
            for k in keys[:-1]:
                d = d.setdefault(k, {})
            if value is None:
                d.pop(keys[-1], None)
            else:
                d[keys[-1]] = value
        with open(p, "w") as fh:
            json.dump(doc, fh)
    elif kind == "sleep":
        time.sleep(act[1])
    elif kind == "ignoreterm":  # a claude that does not end when asked
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    elif kind == "slowterm":  # a claude that leaves a marker file when asked to end by TERM or HUP, then stays until act[2] seconds have
        # passed or the file `marker`.release exists (the test's handshake: it signals the launcher first, then releases)
        def slow(sig, frame, marker=act[1], secs=act[2]):
            if not os.path.exists(marker):
                open(marker, "w").close()
                t0 = time.time()
                while not os.path.exists(marker + ".release") and time.time() - t0 < secs:
                    time.sleep(0.05)
                os._exit(143)
        signal.signal(signal.SIGTERM, slow)
        signal.signal(signal.SIGHUP, slow)
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

    def __init__(self, mutate=None, edits=()):
        self.w = tp.World(["multi", "none", "frozen-p"], mutate=mutate, skills=tp.SKILLS + ("toy-other",))
        w = self.w
        for rel, old, new in edits:  # more replacements in the engine copy (World takes one): a control may need two guards removed
            p = os.path.join(w.forge, rel)
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            assert text.count(old) == 1, "the control's anchor is not in %s: %r" % (rel, old)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text.replace(old, new))
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
    # a list that failed is not an empty one: exit 0 and the project's three profiles, or the check looked at nothing (CodeRabbit, 271)
    want("a: a list outside any session: exit 0 and the profiles", (code, sorted(r["name"] for r in rows)), (0, ["code", "list", "toy-b"]))
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
    if c.switch_files() or len(runs(log)) != 1:
        out.append("request written for an unknown profile: %s, %d run(s)" % (c.switch_files(), len(runs(log))))
        return out  # claude was ended after the first request: the other results are not there
    if len(sw) != 5:
        out.append("expected five switch results, got %d" % len(sw))
        return out
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
    # Session 2 stays until the test says so (a file), not for a number of seconds: how long launcher 1 takes to start is the machine's.
    done = os.path.join(c.scratch, "done-a-%d" % c.n)
    p2, log2 = c.launcher([{"do": [["info", info2], ["wait", done]]}], args=("@list",))
    p1, log1 = c.launcher([{"do": [["wait", info2], ["switch", ["@code"]], ["sleep", 60]]}, {}])
    so1, se1 = p1.communicate(timeout=90)
    open(done, "w").close()
    so2, se2 = p2.communicate(timeout=90)
    r1, r2 = runs(lines(log1)), runs(lines(log2))
    want("f: a switch of session 1 relaunches session 1 (twice) and not session 2 (once)", (len(r1), len(r2), p1.returncode, p2.returncode), (2, 1, 0, 0))
    want("f: and session 2 stays on its profile", r2 and r2[0]["profile"], "list")
    # B: requests written for the other launcher, by hand, relaunch nobody.
    # a file of its own: part A's info file exists already, and launcher 1 would read launcher 2 of part A (gone) as its peer
    info2 = os.path.join(c.scratch, "info-2b-%d.json" % c.n)
    done = os.path.join(c.scratch, "done-b-%d" % c.n)
    p2, log2 = c.launcher([{"do": [["info", info2], ["wait", done]]}], args=("@list",))
    p1, log1 = c.launcher([{"do": [["wait", info2], ["request", {"for": "own", "to": "code", "pid": "peer", "peer": info2, "age": 1}],
                                   ["request", {"for": "peer", "to": "code", "pid": "ppid", "peer": info2, "age": 1}], ["sleep", 2]]}])
    p1.communicate(timeout=90)
    open(done, "w").close()  # launcher 2's claude was alive for the whole of launcher 1's, and ends only now
    p2.communicate(timeout=90)
    r1, r2 = runs(lines(log1)), runs(lines(log2))
    # both requests were written, as meant: the first in session 1 naming launcher 2's pid, the second in session 2 naming launcher 1's
    # (a fake that died before writing them, or wrote others, leaves a run that "ignored" nothing); and both claudes ended well
    written = [x["request"] for x in lines(log1) if "request" in x]
    want("f: both foreign requests were written, as meant", [(x["sid"], x["pid"]) for x in written],
         r1 and r2 and [(r1[0]["session"], r2[0]["ppid"]), (r2[0]["session"], r1[0]["ppid"])])
    want("f: both launchers exit 0", (p1.returncode, p2.returncode), (0, 0))
    if len(r1) != 1:
        out.append("request of session 1 relaunched launcher 2's pid: launcher 1 ran %d time(s), want 1" % len(r1))
    if len(r2) != 1:
        out.append("request of session 1 relaunched launcher 2: %d run(s), want 1" % len(r2))
    return out


def scenario_h(c):
    """a TERM or HUP that reaches the launcher while a switch is being honoured ends the session."""
    out = []
    for sig in (signal.SIGTERM, signal.SIGHUP):
        marker = os.path.join(c.scratch, "termed-%d-%d" % (sig, c.n))
        c.n += 1
        # The request is honoured (TERM to claude, which leaves the marker) and claude stays in its shutdown handler until the test has
        # signalled the launcher and released it: no number of seconds decides it. If the marker never comes, or the launcher is gone,
        # the case looked at nothing and fails (CodeRabbit, 461).
        p, log = c.launcher([{"do": [["slowterm", marker, 30], ["switch", ["@list"]], ["sleep", 60]]}, {}])
        t0 = time.time()
        while not os.path.exists(marker) and time.time() - t0 < 15 and p.poll() is None:
            time.sleep(0.05)
        asked, alive = os.path.exists(marker), p.poll() is None
        if not (asked and alive):
            out.append("h: %s: the switch did not end claude with TERM before the test signalled the launcher (claude asked to end: %s, "
                       "launcher alive: %s): the case looked at nothing" % (sig.name, asked, alive))
        if alive:
            p.send_signal(sig)
            time.sleep(0.5)  # the launcher has the signal noted before claude is let go
        open(marker + ".release", "w").close()
        so, se = p.communicate(timeout=60)
        if len(runs(lines(log))) != 1:
            out.append("%s to the launcher during a switch: claude was started again: %d run(s), want 1" % (sig.name, len(runs(lines(log)))))
        want("h: %s: no request left behind" % sig.name, c.switch_files(), [])
    return out


def scenario_i(c):
    """the relaunch keeps the options the session was started with, names what it drops."""
    out = []
    args = ("@toy-b", "--model", "haiku", "--permission-mode=acceptEdits", "--dangerously-skip-permissions", "--effort", "high",
            "--add-dir", "/x", "/y", "--disallowedTools", "Bash", "Edit", "--allowed-tools=Read", "--allowedTools", "Grep", "Glob",
            "--agent", "reviewer", "--odd=1", "the prompt")
    code, so, se, log, _ = c.run([{"do": [["switch", ["@list"]], ["sleep", 60]]}, {}], args=args)
    rs = runs(log)
    if len(rs) != 2:
        return out + ["relaunch missing: %d run(s), want 2" % len(rs)]
    second = rs[1]["argv"]
    want("i: --model keeps its value", flag(second, "--model"), "haiku")
    want("i: --permission-mode=VALUE is kept as given", "--permission-mode=acceptEdits" in second, True)
    want("i: --dangerously-skip-permissions is kept", "--dangerously-skip-permissions" in second, True)
    want("i: --effort keeps its value", flag(second, "--effort"), "high")
    want("i: --add-dir keeps all its values", second[second.index("--add-dir"):][:3] if "--add-dir" in second else None, ["--add-dir", "/x", "/y"])
    # a restriction that is dropped fails open: the tool lists come back with every value, in both spellings (CodeRabbit, 112)
    want("i: --disallowedTools keeps all its values", second[second.index("--disallowedTools"):][:3] if "--disallowedTools" in second else None,
         ["--disallowedTools", "Bash", "Edit"])
    want("i: --allowed-tools=VALUE is kept as given", "--allowed-tools=Read" in second, True)
    want("i: --allowedTools keeps all its values", second[second.index("--allowedTools"):][:3] if "--allowedTools" in second else None,
         ["--allowedTools", "Grep", "Glob"])
    want("i: the prompt is never repeated", "the prompt" in second, False)
    want("i: the profile's flags and --resume are there", (os.path.basename(flag(second, "--settings") or ""), flag(second, "--resume") == flag(rs[0]["argv"], "--session-id")),
         ("list.json", True))
    want("i: what is dropped is named on the launcher's line", "forge: profile toy-b \u2192 list; not carried over: --agent, --odd" in so, True)
    want("i: the prompt and the kept options are not named as dropped", any(x in so for x in ("the prompt", "--model", "--effort")), False)
    # the second switch of one session carries them again (the launcher keeps them, not the first relaunch's argv)
    code, so, se, log, _ = c.run([{"do": [["switch", ["@list"]], ["sleep", 60]]}, {"do": [["switch", ["@code"]], ["sleep", 60]]}, {}],
                                 args=("@toy-b", "--model", "haiku"))
    rs = runs(log)
    want("i: a second switch carries the options again", rs[2:] and flag(rs[2]["argv"], "--model"), "haiku")
    want("i: nothing to drop, nothing said", "not carried over" in so, False)
    return out


def scenario_j(c):
    """a session started with -p cannot be switched."""
    out = []
    for flags in (("-p", "do the thing"), ("--print", "do the thing", "--output-format", "json")):
        code, so, se, log, _ = c.run([{"do": [["switch", ["@list"]]]}], args=("@toy-b",) + flags)
        sw = [x for x in log if "switch" in x]
        if not sw:
            out.append("no switch result for %s" % (flags,))
            continue
        want("j: %s: the switch is refused with one line naming -p" % flags[0],
             (sw[0]["rc"], len(sw[0]["err"].strip().splitlines()), "-p" in sw[0]["err"], sw[0]["out"]), (2, 1, True, ""))
        want("j: %s: no request written, claude not started again" % flags[0], (c.switch_files(), len(runs(log))), ([], 1))
    return out


def scenario_k(c):
    """a claude that ignores TERM is killed after KILL_AFTER (set to 1 s in this world), and the new one starts."""
    out = []
    code, so, se, log, secs = c.run([{"do": [["ignoreterm"], ["switch", ["@list"]], ["sleep", 10]]}, {}])
    want("k: a claude that ignores TERM is killed and the new one starts", (len(runs(log)), code), (2, 0))
    if secs > 7:
        out.append("k: a claude that ignores TERM was not killed: the launcher took %.1f s with KILL_AFTER 1 (it waited for claude's own 10 s)" % secs)
    return out


class restored:
    """With-block: the files `rels` (relative to the engine copy) are what they were when it ends, also when a case raised: a fake that
    edits the shared toy world must not leave the next scenario another one."""

    def __init__(self, c, *rels):
        self.paths = [os.path.join(c.w.forge, r) for r in rels]

    def __enter__(self):
        self.saved = {}
        for p in self.paths:
            self.saved[p] = open(p, "rb").read() if os.path.exists(p) else None

    def __exit__(self, *exc):
        for p, data in self.saved.items():
            if data is None:
                if os.path.exists(p):
                    os.remove(p)
            else:
                with open(p, "wb") as fh:
                    fh.write(data)


PROJECT_FILE = "config/projects/multi.claude.json"
REGISTRY = "config/mcp-registry.json"


def scenario_l(c):
    """whatever fails while a switch is honoured, claude comes back with the profile it had, resumed, and one line says why."""
    out = []
    # The registry becomes something that is no object while claude runs (an edit gone wrong): building the target's files raises an
    # AttributeError, which is neither a ProfileError nor an OSError. (A server named in the project and missing from the registry is the
    # KeyError CodeRabbit found; resolve() checks every server of a profile against the registry first, so only an edit between its look and
    # the next one reaches it, and no case can place one there.) The request is for the profile the session is on, written by hand.
    with restored(c, REGISTRY):
        code, so, se, log, _ = c.run([{"do": [["edit", REGISTRY, {"=": ["not", "an", "object"]}], ["request", {"to": "list", "pid": "ppid", "age": 1}],
                                              ["sleep", 60]]}, {}], args=("@list",))
    rs = runs(log)
    want("l: a failure that is no ProfileError: claude comes back with the old profile, resumed",
         (len(rs), rs[1:] and rs[1]["profile"], rs[1:] and flag(rs[1]["argv"], "--resume") == flag(rs[0]["argv"], "--session-id")), (2, "list", True))
    want("l: one line says why, no traceback, the launcher exits 0", ("cannot switch to @list" in se and "AttributeError" in se, "Traceback" in se, code),
         (True, False, 0))
    return out


def scenario_m(c):
    """the profile asked for is looked up in the project file as it is now: one added since the start can be switched to."""
    out = []
    with restored(c, PROJECT_FILE, "config/profile-defs/late.json"):
        code, so, se, log, _ = c.run([{"do": [["edit", PROJECT_FILE, {"profiles.offered.late": {}}],
                                              ["edit", "config/profile-defs/late.json", {"description": "added meanwhile", "color": "green", "skills": ["toy-a"]}],
                                              ["request", {"to": "late", "pid": "ppid", "age": 1}], ["sleep", 60]]}, {}])
    rs = runs(log)
    want("m: a profile added while the session runs: claude comes back with it",
         (len(rs), rs[1:] and rs[1]["profile"], rs[1:] and os.path.basename(flag(rs[1]["argv"], "--settings") or "")), (2, "late", "late.json"))
    want("m: said, and no error", ("profile toy-b \u2192 late" in so, se), (True, ""))
    return out


def scenario_n(c):
    """a request the watch accepted is honoured although claude takes seconds to end and the request has aged past the limit meanwhile."""
    out = []
    marker = os.path.join(c.scratch, "slow-end-%d" % c.n)
    # age 116 s at the write; claude needs 5 s to end (nobody releases it), so by then the request is 121 s old, over SWITCH_TTL (120)
    code, so, se, log, _ = c.run([{"do": [["slowterm", marker, 5], ["request", {"to": "list", "pid": "ppid", "age": 116}], ["sleep", 60]]}, {}])
    rs = runs(log)
    want("n: an accepted request is honoured after a slow end: the second run", (len(rs), rs[1:] and rs[1]["profile"]), (2, "list"))
    want("n: nothing left behind, exit 0", (code, c.switch_files()), (0, []))
    return out


def scenario_o(c):
    """a named launcher (`forge start NAME`) started inside a switchable session does not inherit its id and launcher pid."""
    out = []
    with restored(c, "config/forge.json"):
        doc = tp.read_json(os.path.join(c.w.forge, "config", "forge.json"))
        doc["launchers"] = {"plain": {"env": {"PLAIN": "1"}}}
        tp.write_json(os.path.join(c.w.forge, "config", "forge.json"), doc)
        code, so, se, log, _ = c.run([{}], args=("plain",), extra={"FORGE_SESSION": "outer-session", "FORGE_LAUNCHER_PID": "4242"})
    rs = runs(log)
    want("o: a named launcher: claude started once, with neither the session id nor the launcher pid of the outer session",
         (len(rs), rs and rs[0]["session"], rs and rs[0]["launcher"]), (1, None, None))
    return out


def scenario_p(c):
    """`forge start @A --resume ID` (a uuid) is a switchable session: the record is under that id, and --resume is not named as dropped."""
    out = []
    sid = str(uuid.uuid4())
    for form in (("--resume", sid), ("--resume=" + sid,), ("-r", sid)):
        code, so, se, log, _ = c.run([{"do": [["switch", ["@list"]], ["sleep", 60]], "exit": 3}, {}], args=("@toy-b",) + form)
        rs = runs(log)
        label = form[0]
        if len(rs) != 2:
            out.append("p: %s ID: relaunch missing: %d run(s), want 2" % (label, len(rs)))
            continue
        want("p: %s ID: the first run is the user's command, session %s kept" % (label, sid[:8]),
             (rs[0]["session"], "--session-id" in rs[0]["argv"]), (sid, False))
        want("p: %s ID: the second run resumes it with the new profile, once" % label,
             (rs[1]["argv"].count("--resume"), flag(rs[1]["argv"], "--resume"), os.path.basename(flag(rs[1]["argv"], "--settings") or ""), "-r" in rs[1]["argv"]),
             (1, sid, "list.json", False))
        want("p: %s ID: the line names nothing as dropped" % label, ("forge: profile toy-b \u2192 list" in so, "not carried over" in so), (True, False))
        want("p: %s ID: the record is under that id" % label, (c.record(sid) or {}).get("profile"), "list")
    # an id that is not a uuid (a title, a search term), --continue and the picker: no record, so no switch, and the refusal says so
    for form in (("--resume", "my title"), ("-c",), ("--resume",)):
        code, so, se, log, _ = c.run([{"do": [["switch", ["@list"]]]}], args=("@toy-b",) + form)
        sw = [x for x in log if "switch" in x]
        want("p: %s: not switchable: exit 2, one line, nothing written" % " ".join(form),
             (sw and (sw[0]["rc"], len(sw[0]["err"].strip().splitlines())), c.switch_files(), len(runs(log))), ((2, 1), [], 1))
    return out


KILL_1S = ("forge/launch.py", "KILL_AFTER = 15 ", "KILL_AFTER = 1 ")


def scenarios(c):
    return {"a": scenario_a, "b": scenario_b, "c": scenario_c, "d": scenario_d, "e": scenario_e, "f": scenario_f,
            "h": scenario_h, "i": scenario_i, "j": scenario_j, "l": scenario_l, "m": scenario_m, "n": scenario_n,
            "o": scenario_o, "p": scenario_p}


# (name of the scenario, file, text to replace, replacement, the message the scenario must print)
CONTROLS = (
    ("b", "forge/launch.py", "taken = profiles.take_switch(sid, me)", "taken = None", "relaunch missing", (("forge/launch.py", "req = profiles.pending_switch(sid, me)", "req = None"),)),
    ("c", "forge/profiles.py", "now - req[\"at\"] > SWITCH_TTL", "False", "stale request obeyed"),
    ("c", "forge/profiles.py", "req[\"launcher_pid\"] != pid", "False", "foreign request obeyed"),
    ("d", "forge/launch.py", "rec = _launcher_above(sid)", "rec = _launcher_above(sid) or {\"launcher_pid\": 1, \"project\": project, \"profile\": \"x\"}",
     "request written for a session without a launcher"),
    ("d", "forge/launch.py", "rec = _launcher_above(sid)", "rec = _launcher_above(sid)\n    if rec is None and profiles.read_session(sid):\n        os.kill(profiles.read_session(sid)[\"launcher_pid\"], 15)",
     "killed a session it did not launch"),
    ("e", "forge/launch.py", "if profile not in known:", "if False:", "e: an unknown name: exit 2, one line, the closest"),
    # resolve() (reached through _flags) refuses an unknown name too, so the name check alone cannot make "a request is written for an
    # unknown profile" fail: both are taken out here, and then the launcher honours the request (a second run, the old profile's).
    ("e", "forge/launch.py", "if profile not in known:", "if False:", "request written for an unknown profile",
     (("forge/launch.py", "_flags(project, prof, profile)  # a profile that cannot", "(project, prof, profile)  # a profile that cannot"),)),
    ("h", "forge/launch.py", "if not req or stopped:", "if not req:", "claude was started again"),
    ("i", "forge/launch.py", "argv = flags + list(carry) + [\"--resume\"", "argv = flags + [\"--resume\"", "--model keeps its value"),
    ("i", "forge/launch.py", "if dropped else \"\"", "if False else \"\"", "named on the launcher's line"),
    # the tool lists left out of the carried options (the first relaunch already lacks them): the restriction would be gone
    ("i", "forge/launch.py", "VARIADIC = (\"--add-dir\", \"--allowedTools\", \"--allowed-tools\", \"--disallowedTools\", \"--disallowed-tools\")",
     "VARIADIC = (\"--add-dir\", \"--allowedTools\", \"--allowed-tools\")", "i: --disallowedTools keeps all its values"),
    # carried at the first relaunch and dropped from the second on: the diagnostic is the second-switch assertion's, not the first one's
    ("i", "forge/launch.py", "argv = flags + list(carry) + [\"--resume\", _resume_id(req, sid)]",
     "argv = flags + list(carry) + [\"--resume\", _resume_id(req, sid)]\n        carry = ()", "i: a second switch carries the options again"),
    ("l", "forge/launch.py", "except Exception as e:  # not only", "except (profiles.ProfileError, OSError) as e:  # not only",
     "l: a failure that is no ProfileError"),
    ("m", "forge/launch.py", "now = lib.projects().get(project) or {}", "now = _stale",
     "m: a profile added while the session runs", (("forge/launch.py", "    me = os.getpid()\n    note = ", "    me = os.getpid()\n    _stale = lib.projects().get(project)\n    note = "),)),
    ("n", "forge/launch.py", "req = seen[0] if seen else taken", "req = taken", "n: an accepted request is honoured after a slow end"),
    ("o", "forge/launch.py", "    # not a session of a profile launcher, so not the switchable one it may run inside: a `forge switch` from here would restart that one\n    for var in (",
     "    for var in () and (", "o: a named launcher"),
    ("p", "forge/launch.py", "else resumed_id(args)  #", "else None  #", "p: --resume ID: relaunch missing"),
    ("h", "forge/launch.py", "watch=watch, stopped=stopped)", "watch=lambda: False, stopped=stopped)", "the case looked at nothing"),
    ("j", "forge/launch.py", "if rec.get(\"print\"):", "if False:", "j: -p: the switch is refused"),
    ("k", "forge/launch.py", "child.kill()", "pass", "was not killed", (KILL_1S,)),
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
    failures.extend(collect(scenario_k, Ctx(edits=(KILL_1S,))))
    # g: a launcher name is not a profile: `forge switch` is not mixed into it
    code, so, se = c.forge(["start", "nolauncher"])
    want("g: forge start NAME with no such launcher is still exit 2 naming it", (code, "nolauncher" in se), (2, True))
    if "--controls" in sys.argv or not os.environ.get("FORGE_SWITCH_NO_CONTROLS"):
        for name, rel, old, new, message, *more in CONTROLS:
            try:
                m = Ctx(mutate=(rel, old, new), edits=more[0] if more else ())
            except AssertionError as e:
                failures.append("control %s: %s" % (name, e))
                continue
            got = collect({**scenarios(m), "k": scenario_k}[name], m)
            if not any(message in x for x in got):
                failures.append("control %s (%s -> %s) did not fail with %r: %s" % (name, old[:40], new[:20], message, got))
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print("ok: switch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
