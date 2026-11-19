#!/usr/bin/env python3
"""Every refusal of `forge start @NAME`, `forge list @`, `forge switch @NAME` and `forge run @NAME` names the command that fixes it
(forge/profiles.py, forge/launch.py, forge/run.py), and `forge switch @B` in a session no `forge start` launched opens a terminal with
`forge start @B --resume ID --fork-session` instead of only refusing (4.4 U2, and its fix round).

The world is test_profiles' (an engine copy, a toy HOME, the projects `multi`, `none`, `frozen-p`, `errs`) and four directories that
stand for PATH, each holding only fake programs (ORDERS 10): `full` (python3, git, a fake claude, a fake terminal called
`xdg-terminal-exec`), `noclaude`, `noterm` and `badclaude` (a claude whose interpreter is not there).
The fake terminal records its arguments, its working directory, its environment and its process group, then waits for a release file: a `forge switch` that waited for it would be seen waiting. No real
terminal can open: the real `xdg-terminal-exec` is on no PATH here.

A. The sweep. Each refusal is provoked (each case runs the command in the world, exit code and stream checked) and its message must
   contain the exact next step the case names: a message without it fails with `no next step in: <message>`. The sweep says how many
   refusals it looked at; looking at none is a failure, and so is a provoked case that did not refuse. Every message is one line.
B. The fork. In a session that no launcher started (a CLAUDE_CODE_SESSION_ID, no FORGE_SESSION), `forge switch @list`:
   exit 0 and one line saying the old session stays open; the terminal started once, with the words of `profiles.terminal` (a custom one
   too) followed by `forge start @list --resume ID --fork-session`, in the session's working directory, in a process group of its own,
   with none of the session's own variables, and `forge switch` did not wait for it; a process that stands for the session is alive
   (nothing is signalled), no request and no record is written. A profile that does not resolve, no session id, an id that is not
   one, a terminal that is not on PATH and a `profiles.terminal` that is no list of words refuse with their next step and open nothing.
C. `forge start @list --resume ID --fork-session` is a session of ours: forge picks its id and passes `--session-id NEW` (measured with a
   real claude, framework-discuss/execution/runs/4.4-daily-use/u2-fork-measurement.md: the pair starts and the fork runs under NEW),
   writes its record under NEW with its profile, and sets FORGE_SESSION to NEW; the original session's record, which may belong to a
   live launcher, is never touched. A fork that gave its own `--session-id`, or of `-c` or a title, has no id of ours: no record.
D. A fork `forge start` launched is switched in place: its session asks `forge switch @toy-b`, its launcher restarts claude with
   `--resume NEW` and the new profile (no `--fork-session`, nothing "not carried over", no terminal). With a state file that cannot be
   written while the request is honoured, the launcher's line says so with its next step and claude still comes back.
E. The new terminal: none of the eleven names that say whose session it is or connect to it reach it, CLAUDE_CONFIG_DIR does; one
   whose program ends at once with an error is a refusal (exit 2, the command to run by hand), one that ends at once with 0 is a success
   that says forge cannot see the window.

Written first, run against the code of the first commit of this round (d5d6bc1, forge/ unchanged, this file as it is now): 14 FAIL lines, 52
refusals looked at (the sweep ends at 53: the 46 of the first round and seven cases added here: the launchers table, a claude that cannot
be executed for `forge start @B`, for a named launcher and for `forge run`, `forge run` past --timeout and with no result document, and a
terminal that ends with an error; the named launcher's was added after this run),
among them
  "FAIL sweep: start: a launchers table with a key that is not known: no next step in: ! forge start: launchers.x.bogus: only env is known"
  "FAIL sweep: start: claude is on PATH and cannot be executed: provoked, exit 1 ('Traceback (most recent call last): ..." (a traceback)
  "FAIL sweep: run: the session ran past --timeout: no next step in: ! forge run: profile toy-b session ... ran past --timeout 1 seconds and was ended"
  "FAIL sweep: switch: the terminal ends at once with an error: provoked, exit 0 (''), want one of (2,): it did not refuse"
  "FAIL fork: none of the session's variables reach the terminal: ['CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS', 'CLAUDE_AGENT_SDK_VERSION', 'CLAUDE_CODE_MESSAGING_SOCKET', 'CLAUDE_CODE_MESSAGING_TOKEN'], want []"
  "FAIL fork-record: claude gets --resume ID --fork-session and a --session-id of its own (a new uuid): (True, True, 0, False), want (True, True, 1, True)"
  "FAIL inplace: exit 0, two claudes, the switch asked inside the fork was accepted: (0, 1, 2), want (0, 2, 0)"
  "FAIL fallback: one line, with the next step `forge switch @toy-b`: (1, False), want (1, True)"
Fix round 2 (CodeRabbit, pull request 187), the register scenario, against forge/profiles.py as it was (6adc2cb), seen failing before the fix:
  "FAIL register 'My App': the suggested `forge new '.../projects/My App'` registers the folder (exit 0, project file my-app.claude.json): (1, False, None), want (0, True, True)"
  "FAIL register 'My App': --name only where the folder's name is no project name: False, want True"
The fake claude of the in-place scenarios defers its end (a SIGTERM handler set before it runs `forge switch`) until it wrote `.switch`. Seen
with a forced 3 s pause between `forge switch` and that write (not kept): the old fake, ended by the launcher meanwhile, left no `.switch`:
  "FAIL inplace: exit 0, two claudes, the switch asked inside the fork was accepted: (0, 2, None), want (0, 2, 0)"
and the new one, the same pause, passed.
(Against 41bd475, the base of the pull request, the first round of this file saw 48 FAIL lines and the refusal of `forge switch` where it
now opens a terminal.)
Negative controls (CONTROLS: an engine copy with one line broken, the same scenario; the first message each printed, FORGE_MESSAGES_SHOW=1):
  sweep   a doc pointer left out of the no-profiles reason  -> "sweep: start: a project without profiles: no next step in: ! forge start: project 'none' declares no profiles"
  sweep   `forge start` that lets the OSError of a claude that cannot run go -> "sweep: start: claude is on PATH and cannot be executed: provoked, exit 1 ('Traceback ..."
  sweep   `forge run`'s no-result line without its next step -> "no next step in: ! forge run: claude's output is not a result document (0 bytes)"
  fork    a switch that signals the session (CLAUDE_PID)    -> "killed a session it did not launch: the session's process ended (-15)"
  fork    a fork without --fork-session                     -> "fork: terminal arguments end with `start @list --resume ID --fork-session`: [..., '--resume', 'ID'], want [..., '--fork-session']"
  fork    a missing id taken as an id                       -> "a terminal was opened without a session id: exit 0, [{'argv': [..., '--resume', 'none', '--fork-session'], ...}]"
  fork    a switch that waits for the terminal              -> "forge switch waited for the terminal: no exit in 15 s"
  fork    a terminal that ends with an error taken as opened -> "fork: a terminal that ends at once with an error: exit, one line, and `forge start @list --resume ID --fork-session`: (0, True, 1), want (2, True, 1)"
  fork    an exit 0 that says nothing of the window         -> "fork: a terminal that hands the window over and ends with 0: exit, one line, and cannot see the window: (0, False, 1), want (0, True, 1)"
  fork    one session name left in the environment          -> "fork: none of the session's variables reach the terminal: ['CLAUDE_CODE_MESSAGING_TOKEN'], want []"
  record  a fork that is not given an id of ours            -> "fork-record: claude gets --resume ID --fork-session and a --session-id of its own (a new uuid): (True, True, 0, False), want (True, True, 1, True)"
  record  a fork with an id of the user's recorded under the original's -> "the record of the original session was overwritten: by a fork that gave its own --session-id, or one of -c or a title"
  inplace the fallback line without its next step           -> "fallback: one line, with the next step `forge switch @toy-b`: (1, False), want (1, True)"
  register a folder named `My App` suggested without --name -> "register 'My App': the suggested `forge new '.../My App'` registers the folder (exit 0, project file my-app.claude.json): (1, False, None), want (0, True, True)"
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
import test_profiles as tp  # noqa: E402

FAKE_CLAUDE = """#!%s
import json, os, signal, subprocess, sys, time
log = os.environ["FAKE_CLAUDE_LOG"]
with open(log, "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "session": os.environ.get("FORGE_SESSION"), "profile": os.environ.get("FORGE_PROFILE")}) + "\\n")
if os.environ.get("FAKE_CLAUDE_SLEEP"):
    time.sleep(float(os.environ["FAKE_CLAUDE_SLEEP"]))
target = os.environ.get("FAKE_CLAUDE_SWITCH")
if target and not os.path.exists(log + ".switched"):  # the first claude of a launcher asks for a switch, as a session would, and waits to be ended
    open(log + ".switched", "w").close()
    ended = []  # the launcher may end this process the moment the request is made: the end waits until the result is written
    signal.signal(signal.SIGTERM, lambda *_: ended.append(1))
    if "--session-id" in sys.argv:  # claude's own variable: the id the session runs under
        os.environ["CLAUDE_CODE_SESSION_ID"] = sys.argv[sys.argv.index("--session-id") + 1]
    if os.environ.get("FAKE_BREAK_DIR"):  # what the launcher writes while it honours the request cannot be written (before the request: the
        # launcher may end this process the moment it is made)
        os.rename(os.environ["FAKE_BREAK_DIR"], os.environ["FAKE_BREAK_DIR"] + ".aside")
        open(os.environ["FAKE_BREAK_DIR"], "w").close()
    r = subprocess.run([sys.executable, os.environ["FAKE_FORGE"], "switch", "@" + target], capture_output=True, text=True)
    with open(log + ".switch", "w") as fh:
        fh.write(json.dumps([r.returncode, r.stdout, r.stderr]))
    t0 = time.time()
    while not ended and time.time() - t0 < 30:  # waits to be ended, then ends
        time.sleep(0.05)
"""
BAD_CLAUDE = "#!/nonexistent/interpreter\n"  # passes `which`, cannot be executed
FAKE_TERMINAL = """#!%s
import json, os, sys, time
log = os.environ["FAKE_TERM_LOG"]
def put(doc):
    with open(log, "a") as fh:
        fh.write(json.dumps(doc) + "\\n")
put({"argv": sys.argv[1:], "cwd": os.getcwd(), "env": sorted(os.environ), "pgid": os.getpgid(0),
     "ppid_pgid": os.getpgid(os.getppid()) if os.getppid() > 1 else None, "sid": os.getsid(0), "pid": os.getpid()})
if os.environ.get("FAKE_TERM_MODE") == "fail":  # a terminal that cannot open: ends at once with an error
    sys.exit(3)
if os.environ.get("FAKE_TERM_MODE") == "hand":  # a terminal that hands the window to a running server and ends
    sys.exit(0)
t0 = time.time()
while not os.path.exists(log + ".release") and time.time() - t0 < 25:
    time.sleep(0.05)
put({"done": True})
"""
# What a new terminal must not inherit (the names this test asserts, written out here and not read from the code): whose session it is,
# and how to reach it. CLAUDE_CONFIG_DIR is not one of them: a fresh claude needs it.
SESSION_NAMES = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PID", "CLAUDECODE", "FORGE_SESSION", "FORGE_LAUNCHER_PID", "CLAUDE_CODE_ENTRYPOINT",
                 "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS", "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_CODE_MESSAGING_SOCKET",
                 "CLAUDE_CODE_MESSAGING_TOKEN")


class Ctx:
    """One toy world with its three PATHs, the fake terminal's log and the helpers every scenario uses."""

    def __init__(self, mutate=None, terminal=None):
        self.mutate = mutate
        self.w = tp.World(["multi", "none", "frozen-p", "errs"], mutate=mutate)
        w = self.w
        tp.write_json(os.path.join(w.forge, "config", "mcp-registry.json"),
                      {"servers": {"toy-echo": {"type": "stdio", "command": "toy-echo", "args": [], "env": {}}}})
        tp.write_json(os.path.join(w.home, ".claude", "settings.json"), {"enabledPlugins": {"p-def@m": True, "toy-plugin@x": True}})
        tp.write_json(os.path.join(w.home, ".claude.json"), {"projects": {}, "mcpServers": {}})
        if terminal is not None:
            p = os.path.join(w.forge, "config", "forge.json")
            doc = tp.read_json(p)
            doc["profiles"] = {"terminal": terminal}
            tp.write_json(p, doc)
        self.scratch = sandbox.mkdtemp("forge-msg-")
        self.bins = {name: self.bindir(name, claude=None if name == "noclaude" else BAD_CLAUDE if name == "badclaude" else FAKE_CLAUDE,
                                       term=None if name == "noterm" else FAKE_TERMINAL) for name in ("full", "noclaude", "noterm", "badclaude")}
        self.term_log = os.path.join(self.scratch, "terminal.jsonl")
        self.claude_log = os.path.join(self.scratch, "claude.jsonl")
        self.state = os.path.join(w.home, ".local", "state", "forge")
        self.pids = []

    def bindir(self, name, claude, term):
        """A directory standing for PATH: python3, git, and the text of the fake `claude` and of the fake terminal (None: not there)."""
        d = os.path.join(self.scratch, "bin-" + name)
        os.makedirs(d)
        os.symlink(sys.executable, os.path.join(d, "python3"))
        os.symlink(shutil.which("git"), os.path.join(d, "git"))
        for program, text in (("claude", claude), ("xdg-terminal-exec", term), ("fake-term", term)):
            if text:
                with open(os.path.join(d, program), "w") as fh:
                    fh.write(text % sys.executable if "%s" in text else text)
                os.chmod(os.path.join(d, program), 0o755)
        return d

    def forge(self, args, cwd=None, extra=None, path="full", timeout=60):
        """(exit code, stdout, stderr) of `forge ARGS` in the world, from `cwd` (default: project multi)."""
        e = sandbox.bare_env(self.w.home, self.w.root, FAKE_TERM_LOG=self.term_log, FAKE_CLAUDE_LOG=self.claude_log,
                            FAKE_FORGE=os.path.join(self.w.forge, "bin", "forge"), **(extra or {}))
        e["PATH"] = self.bins[path]
        r = subprocess.run([sys.executable, os.path.join(self.w.forge, "bin", "forge")] + list(args), cwd=cwd or self.w.pp("multi"), env=e,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
        return r.returncode, r.stdout, r.stderr

    def terminals(self):
        """The runs of the fake terminal that started (its first line each), and whether any of them ended."""
        if not os.path.exists(self.term_log):
            return [], False
        with open(self.term_log) as fh:
            rows = [json.loads(x) for x in fh if x.strip()]
        return [r for r in rows if "argv" in r], any("done" in r for r in rows)

    def release(self):
        """Let every fake terminal end, and wait until it did: nothing is left running by this test."""
        open(self.term_log + ".release", "w").close()
        t0 = time.time()
        started, _ = self.terminals()
        while time.time() - t0 < 30:
            done = sum(1 for x in open(self.term_log) if '"done"' in x) if os.path.exists(self.term_log) else 0
            if done >= len(started):
                break
            time.sleep(0.05)
        os.remove(self.term_log + ".release")
        if os.path.exists(self.term_log):
            os.remove(self.term_log)

    def record(self, sid, **doc):
        p = os.path.join(self.state, "profile-sessions", sid + ".json")
        tp.write_json(p, doc)
        return p

    def sleeper(self):
        """A process that stands for a session this code did not launch (and, with a record, for the launcher of one)."""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.pids.append(p)
        return p

    def cleanup(self):
        open(self.term_log + ".release", "w").close()  # a fake terminal that is still waiting ends now
        for p in self.pids:
            if p.poll() is None:
                p.kill()
            p.wait()


failures = []
_sink = [failures]  # where want() writes: the real run's list, or the one of a control's scenario


def want(label, got, expected):
    if got != expected:
        _sink[-1].append("%s: %s, want %s" % (label, got, expected))


def next_step(message, step):
    """None when `message` names `step`, else the sentence that is the failure."""
    return None if step in message else "no next step in: %s" % message.strip()


# ---- A. the sweep -----------------------------------------------------------------------------------------------------------------

DOC = 'docs/config-architecture.md, "Session profiles"'


class Broken:
    """STATE (or one folder of it) made a regular file, so that what forge writes there fails with an OSError; the folder that was there
    is put back after, with what it held."""

    def __init__(self, c, sub=None):
        self.target = os.path.join(c.state, sub) if sub else c.state
        self.aside = self.target + ".aside"

    def __enter__(self):
        os.makedirs(os.path.dirname(self.target), exist_ok=True)
        if os.path.isdir(self.target):
            os.rename(self.target, self.aside)
        with open(self.target, "w") as fh:
            fh.write("a file where a folder goes")

    def __exit__(self, *a):
        os.remove(self.target)
        if os.path.isdir(self.aside):
            os.rename(self.aside, self.target)


class Setting:
    """config/forge.json of the world with `fields` added to it, put back as it was after."""

    def __init__(self, c, **fields):
        self.path, self.fields = os.path.join(c.w.forge, "config", "forge.json"), fields

    def __enter__(self):
        with open(self.path, "rb") as fh:
            self.before = fh.read()
        doc = json.loads(self.before)
        doc.update(self.fields)
        tp.write_json(self.path, doc)

    def __exit__(self, *a):
        with open(self.path, "wb") as fh:
            fh.write(self.before)


def sweep_cases(c, sid, live):
    """[(label, args, cwd, extra, path, exit codes, stream, next step, context manager or None)]. `live` is the process that stands for
    a launcher that is alive; sid is a session id the cases may use."""
    w = c.w
    multi, none, frozen, errs, home = w.pp("multi"), w.pp("none"), w.pp("frozen-p"), w.pp("errs"), w.home
    new_here = "`forge new %s`" % shlex.quote(home)
    state = "`ls -ld %s`" % shlex.quote(c.state)
    other, printing, plain = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    c.record(other, profile="toy-b", project="none", launcher_pid=live.pid, at=time.time())
    c.record(printing, profile="toy-b", project="multi", launcher_pid=live.pid, at=time.time(), print=True)
    c.record(plain, profile="toy-b", project="multi", launcher_pid=live.pid, at=time.time())
    live_env = lambda s: {"FORGE_SESSION": s, "FORGE_LAUNCHER_PID": str(live.pid)}  # noqa: E731
    run_depth = lambda v: {"FORGE_RUN_DEPTH": v}  # noqa: E731
    unreadable = os.path.join(c.scratch, "unreadable")
    os.makedirs(unreadable, exist_ok=True)
    os.chmod(unreadable, 0)
    cases = [
        ("start: a name that cannot be one", ["start", "@-x"], multi, {}, "full", (2,), "err", "`forge list @`", None),
        ("start: not a profile at all", ["start", "@"], none, {}, "full", (1,), "out", DOC, None),
        ("start: outside a project", ["start", "@toy-b"], home, {}, "full", (2,), "err", new_here, None),
        ("start: a frozen project", ["start", "@list"], frozen, {}, "full", (2,), "err", "config/projects/frozen-p.claude.json", None),
        ("start: a project without profiles", ["start", "@toy-b"], none, {}, "full", (2,), "err", DOC, None),
        ("start: an unknown name with a near one", ["start", "@toy-"], multi, {}, "full", (2,), "err", "`forge start @toy-b`", None),
        ("start: an unknown name with none near", ["start", "@zzzzzz"], multi, {}, "full", (2,), "err", "`forge start @code`", None),
        ("start: a profile that does not resolve", ["start", "@err-set"], errs, {}, "full", (2,), "err", "`forge doctor errs`", None),
        ("start: --settings given", ["start", "@toy-b", "--settings", "x"], multi, {}, "full", (2,), "err", "`forge start @toy-b`", None),
        ("start: claude not on PATH", ["start", "@toy-b"], multi, {}, "noclaude", (127,), "err", "`forge toolchain --fix`", None),
        ("start: the state folder cannot be written", ["start", "@toy-b"], multi, {}, "full", (2,), "err", state, Broken(c)),
        ("start: an unknown launcher", ["start", "nolauncher"], multi, {}, "full", (2,), "err", "`forge start` lists them", None),
        ("start: a launchers table with a key that is not known", ["start", "x"], multi, {}, "full", (2,), "err", "config/forge.json",
         Setting(c, launchers={"x": {"bogus": 1}})),
        ("start: claude is on PATH and cannot be executed", ["start", "@toy-b"], multi, {}, "badclaude", (127,), "err", "`forge toolchain --fix`", None),
        ("start: a launcher, and claude cannot be executed", ["start", "x"], multi, {}, "badclaude", (127,), "err", "`forge toolchain --fix`",
         Setting(c, launchers={"x": {"env": {}}})),
        ("list: no argument", ["list"], multi, {}, "full", (2,), "err", "`forge list @`", None),
        ("list: a name that cannot be one", ["list", "@-x"], multi, {}, "full", (2,), "err", "`forge list @`", None),
        ("list: --names with a name", ["list", "@toy-b", "--names"], multi, {}, "full", (2,), "err", "`forge list @`", None),
        ("list: outside a project", ["list", "@"], home, {}, "full", (2,), "err", new_here, None),
        ("list: an unknown name", ["list", "@toy-"], multi, {}, "full", (2,), "err", "`forge list @toy-b`", None),
        ("list: a profile that does not resolve", ["list", "@err-set"], errs, {}, "full", (2,), "err", "`forge doctor errs`", None),
        ("list: a project without profiles, one profile asked", ["list", "@toy-b"], none, {}, "full", (1,), "err", DOC, None),
        ("list: a frozen project, one profile asked", ["list", "@list"], frozen, {}, "full", (1,), "err", "config/projects/frozen-p.claude.json", None),
        ("list: a project without profiles, the list", ["list", "@"], none, {}, "full", (1,), "out", DOC, None),
        ("switch: an unknown name", ["switch", "@toy-"], multi, {}, "full", (2,), "err", "`forge switch @toy-b`", None),
        ("switch: a project without profiles", ["switch", "@toy-b"], none, {}, "full", (2,), "err", DOC, None),
        ("switch: a session with no launcher and no session id", ["switch", "@list"], multi, {}, "full", (2,), "err", "`forge start @list`", None),
        ("switch: a session id that is not one", ["switch", "@list"], multi, {"CLAUDE_CODE_SESSION_ID": "not-an-id"}, "full", (2,), "err",
         "`forge start @list`", None),
        ("switch: no terminal on PATH", ["switch", "@list"], multi, {"CLAUDE_CODE_SESSION_ID": sid}, "noterm", (2,), "err",
         "`forge start @list --resume %s --fork-session`" % sid, None),
        ("switch: a profile that does not resolve, with a session id", ["switch", "@err-set"], errs, {"CLAUDE_CODE_SESSION_ID": sid}, "full", (2,),
         "err", "`forge doctor errs`", None),
        ("switch: a launcher of another project", ["switch", "@list"], multi, live_env(other), "full", (2,), "err", "`forge switch @list`", None),
        ("switch: a session started with -p", ["switch", "@list"], multi, live_env(printing), "full", (2,), "err", '`forge run @list "PROMPT"`', None),
        ("switch: the request cannot be written", ["switch", "@list"], multi, live_env(plain), "full", (2,), "err", state,
         Broken(c, "profile-switch")),
        ("run: FORGE_RUN_DEPTH is no number", ["run", "@toy-b", "hi"], multi, run_depth("x"), "full", (2,), "err", "`unset FORGE_RUN_DEPTH`", None),
        ("run: called from a run from a run", ["run", "@toy-b", "hi"], multi, run_depth("2"), "full", (2,), "err", '`forge run @NAME "PROMPT"`', None),
        ("run: an empty prompt", ["run", "@toy-b", " "], multi, {}, "full", (2,), "err", 'forge run @NAME "PROMPT"', None),
        ("run: an empty --model", ["run", "@toy-b", "hi", "--model", " "], multi, {}, "full", (2,), "err", "`--model sonnet`", None),
        ("run: a --permission-mode that is refused", ["run", "@toy-b", "hi", "--permission-mode", "bypassPermissions"], multi, {}, "full", (2,),
         "err", "`--permission-mode default`", None),
        ("run: a --timeout of 0", ["run", "@toy-b", "hi", "--timeout", "0"], multi, {}, "full", (2,), "err", "`--timeout 1800`", None),
        ("run: a --cwd that is no folder", ["run", "@toy-b", "hi", "--cwd", os.path.join(c.scratch, "nope")], multi, {}, "full", (2,), "err",
         "`--cwd .`", None),
        ("run: a bare @", ["run", "@", "hi"], multi, {}, "full", (2,), "err", "`forge list @`", None),
        ("run: not an @", ["run", "toy-b", "hi"], multi, {}, "full", (2,), "err", "`forge list @`", None),
        ("run: outside a project", ["run", "@toy-b", "hi"], home, {}, "full", (2,), "err", new_here, None),
        ("run: an unknown name", ["run", "@toy-", "hi"], multi, {}, "full", (2,), "err", '`forge run @toy-b "PROMPT"`', None),
        ("run: a project without profiles", ["run", "@toy-b", "hi"], none, {}, "full", (2,), "err", DOC, None),
        ("run: a profile that does not resolve", ["run", "@err-set", "hi"], errs, {}, "full", (2,), "err", "`forge doctor errs`", None),
        ("run: claude not on PATH", ["run", "@toy-b", "hi"], multi, {}, "noclaude", (127,), "err", "`forge toolchain --fix`", None),
        ("run: the state folder cannot be written", ["run", "@toy-b", "hi"], multi, {}, "full", (2,), "err", state, Broken(c)),
        ("run: claude is on PATH and cannot be executed", ["run", "@toy-b", "hi"], multi, {}, "badclaude", (127,), "err", "`forge toolchain --fix`", None),
        ("run: the session ran past --timeout", ["run", "@toy-b", "hi", "--timeout", "1"], multi, {"FAKE_CLAUDE_SLEEP": "60"}, "full", (124,), "err",
         "`--timeout 2`", None),
        ("run: claude's output is no result document", ["run", "@toy-b", "hi"], multi, {}, "full", (1,), "err", "`claude --resume ", None),
        ("switch: the terminal ends at once with an error", ["switch", "@list"], multi, {"CLAUDE_CODE_SESSION_ID": sid, "FAKE_TERM_MODE": "fail"},
         "full", (2,), "err", "`forge start @list --resume %s --fork-session`" % sid, None),
    ]
    if os.geteuid() != 0:  # root enters a folder with no permission bits
        cases.append(("run: a --cwd that cannot be entered", ["run", "@toy-b", "hi", "--cwd", unreadable], multi, {}, "full", (2,), "err",
                      "`ls -ld %s`" % shlex.quote(unreadable), None))
    return cases


def scenario_sweep(c):
    out = []
    live = c.sleeper()
    sid = str(uuid.uuid4())
    looked = 0
    cases = sweep_cases(c, sid, live)
    try:
        for label, args, cwd, extra, path, codes, stream, step, ctx in cases:
            if ctx:
                ctx.__enter__()
            try:
                code, so, se = c.forge(args, cwd=cwd, extra=extra, path=path)
            finally:
                if ctx:
                    ctx.__exit__()
            looked += 1
            # `forge run` says what the session cost on stderr first; that line is not a refusal
            message = "".join(x + "\n" for x in se.splitlines() if not (x.startswith("profile ") and " USD" in x)) if stream == "err" else so
            if code not in codes:
                out.append("sweep: %s: provoked, exit %d (%r), want one of %s: it did not refuse" % (label, code, message.strip(), codes))
                continue
            bad = next_step(message, step)
            if bad:
                out.append("sweep: %s: %s" % (label, bad))
            if len(message.strip().splitlines()) != 1:
                out.append("sweep: %s: one line wanted, got %d: %r" % (label, len(message.strip().splitlines()), message))
            if "Traceback" in se:
                out.append("sweep: %s: a traceback: %s" % (label, se))
        if live.poll() is not None:
            out.append("killed a session it did not launch: the sweep's sleeper ended (%s)" % live.returncode)
        started, _ = c.terminals()
        asked = sum(1 for case in cases if "FAKE_TERM_MODE" in case[3])  # the cases that make a terminal open and fail
        if len(started) != asked:
            out.append("sweep: %d terminal(s) opened, %d expected (a refusal must open none): %s" % (len(started), asked, started))
    finally:
        os.chmod(os.path.join(c.scratch, "unreadable"), 0o700)
    if looked == 0:
        out.append("sweep: looked at no refusal: a check that saw nothing is not a pass")
    print("sweep: looked at %d refusals" % looked)
    return out


# ---- B. the fork --------------------------------------------------------------------------------------------------------------------

def scenario_fork(c):
    out = []
    sid = str(uuid.uuid4())
    session = c.sleeper()  # the session: nobody launched it, so nothing may signal it
    multi = os.path.realpath(c.w.pp("multi"))
    before = c.w.files("")
    started = time.time()
    try:
        mine = {k: "1" for k in SESSION_NAMES}  # what a Bash tool call of an Orca session holds, and a launcher's two
        mine.update(CLAUDE_CODE_SESSION_ID=sid, CLAUDE_PID=str(session.pid), CLAUDE_CONFIG_DIR="/srv/claude-config")
        code, so, se = c.forge(["switch", "@list"], extra=mine, timeout=15)
    except subprocess.TimeoutExpired:
        out.append("forge switch waited for the terminal: no exit in 15 s")
        c.release()
        return out
    secs = time.time() - started
    want("fork: exit, one line on stdout, nothing on stderr", (code, len(so.strip().splitlines()), se), (0, 1, ""))
    want("fork: the line says the old session stays open and names the command",
         ("stays open" in so, "forge start @list --resume %s --fork-session" % sid in so), (True, True))
    deadline = time.time() + 10
    while not c.terminals()[0] and time.time() < deadline:  # the terminal is detached: it may write its line a moment after forge ended
        time.sleep(0.05)
    runs, _ = c.terminals()
    if len(runs) != 1:
        out.append("fork: no terminal was opened (or more than one): %d run(s)" % len(runs))
        c.release()
        return out
    t = runs[0]
    tail = ["start", "@list", "--resume", sid, "--fork-session"]
    want("fork: terminal arguments end with `start @list --resume ID --fork-session`", t["argv"][-5:], tail)
    head = t["argv"][:-5]
    want("fork: ... run through this checkout's bin/forge, with an interpreter",
         (len(head) >= 2 and head[-1].endswith(os.path.join("bin", "forge")), len(head) >= 2 and os.path.isabs(head[-2])), (True, True))
    want("fork: the terminal runs in the session's working directory", os.path.realpath(t["cwd"]), multi)
    want("fork: none of the session's variables reach the terminal", [k for k in SESSION_NAMES if k in t["env"]], [])
    want("fork: what a fresh claude needs does (CLAUDE_CONFIG_DIR)", "CLAUDE_CONFIG_DIR" in t["env"], True)
    want("fork: the terminal is detached (a process group of its own)", t["pgid"] == t["pid"] and t["sid"] == t["pid"], True)
    if session.poll() is not None:
        out.append("killed a session it did not launch: the session's process ended (%s)" % session.returncode)
    after = c.w.files("")
    want("fork: nothing is written (no request, no record)", sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)), [])
    want("fork: forge switch did not wait for the terminal", secs < 12, True)
    c.release()

    # a custom terminal: its words come first, whatever they are, and the program is looked up on PATH
    custom = Ctx(terminal=["fake-term", "--title", "forge switch"])
    try:
        code, so, se = custom.forge(["switch", "@list"], extra={"CLAUDE_CODE_SESSION_ID": sid})
        deadline = time.time() + 10
        while not custom.terminals()[0] and time.time() < deadline:
            time.sleep(0.05)
        runs, _ = custom.terminals()
        want("fork: profiles.terminal: exit and the words first", (code, runs and runs[0]["argv"][:2], runs and runs[0]["argv"][-5:]),
             (0, ["--title", "forge switch"], tail))
        custom.release()
        for label, words in (("a string", "xdg-terminal-exec"), ("an empty list", []), ("a list with a number", ["fake-term", 3]), ("a program that is not there", ["no-such-term"])):
            bad = Ctx(terminal=words)
            try:
                code, so, se = bad.forge(["switch", "@list"], extra={"CLAUDE_CODE_SESSION_ID": sid})
                want("fork: profiles.terminal is %s: exit 2, one line, the next step, no terminal" % label,
                     (code, len(se.strip().splitlines()), "`forge start @list --resume %s --fork-session`" % sid in se, bad.terminals()[0]), (2, 1, True, []))
            finally:
                bad.cleanup()
    finally:
        custom.cleanup()

    # a terminal that ends at once, or never opens: the first is refused, the second is a success that says forge cannot see the window
    for mode, label, expected in (("fail", "ends at once with an error", (2, "`forge start @list --resume %s --fork-session`" % sid)),
                                  ("hand", "hands the window over and ends with 0", (0, "cannot see the window"))):
        hand = Ctx(mutate=c.mutate)  # the same engine, broken or not, as the scenario's
        try:
            code, so, se = hand.forge(["switch", "@list"], extra={"CLAUDE_CODE_SESSION_ID": sid, "FAKE_TERM_MODE": mode})
            text = se if code else so
            want("fork: a terminal that %s: exit, one line, and %s" % (label, expected[1]),
                 (code, expected[1] in text, len(text.strip().splitlines())), (expected[0], True, 1))
            if code == 0:
                want("fork: ... and it still says the old session stays open", "stays open" in so, True)
        finally:
            hand.cleanup()

    # no session id: a refusal, and the terminal never opened (a control opens one with an id of "none")
    code, so, se = c.forge(["switch", "@list"])
    if code == 0 or c.terminals()[0]:  # exit 0 is only said once the terminal was started, which may log a moment later
        out.append("a terminal was opened without a session id: exit %d, %s" % (code, c.terminals()[0]))
        c.release()
    want("fork: no session id: exit 2 and the next step", (code, "`forge start @list`" in se), (2, True))
    return out


# ---- C. a fork is a session of ours, under its own id -------------------------------------------------------------------------------

def scenario_record(c):
    out = []
    sid = str(uuid.uuid4())
    path = c.record(sid, profile="toy-b", project="multi", launcher_pid=os.getpid(), at=1.0)
    with open(path, "rb") as fh:
        original = fh.read()
    code, so, se = c.forge(["start", "@list", "--resume", sid, "--fork-session"])
    with open(path, "rb") as fh:
        now = fh.read()
    if now != original:
        out.append("the record of the original session was overwritten: %r, was %r" % (now, original))
    last = [json.loads(x) for x in open(c.claude_log)][-1] if os.path.exists(c.claude_log) else None
    if not (code == 0 and last):
        out.append("fork-record: claude was not started: exit %d, %r" % (code, se))
        return out
    argv = last["argv"]
    new_id = argv[argv.index("--session-id") + 1] if "--session-id" in argv else None
    try:
        valid = new_id is not None and str(uuid.UUID(new_id)) == new_id and new_id != sid
    except ValueError:
        valid = False
    want("fork-record: claude gets --resume ID --fork-session and a --session-id of its own (a new uuid)",
         (argv[argv.index("--resume") + 1] == sid, "--fork-session" in argv, argv.count("--session-id"), valid), (True, True, 1, True))
    want("fork-record: FORGE_SESSION is the fork's id", last["session"], new_id)
    rec = tp.read_json(os.path.join(c.state, "profile-sessions", "%s.json" % new_id)) if valid and os.path.exists(
        os.path.join(c.state, "profile-sessions", "%s.json" % new_id)) else None
    want("fork-record: the fork has a record under its own id, with its profile and project",
         rec and (rec["profile"], rec["project"], isinstance(rec["launcher_pid"], int)), ("list", "multi", True))
    code, so, se = c.forge(["start", "@list", "--dry-run", "--resume", str(uuid.uuid4()), "--fork-session"])
    want("fork-record: --dry-run says the fork gets a record under a new id", (code, "no session record" in so, "a new uuid4" in so), (0, False, True))
    # an id of the user's own, or a fork of what has no id of ours (-c, a title): no id of ours is added and nothing is recorded
    for label, extra_args in (("the user's own --session-id", ["--resume", sid, "--fork-session", "--session-id", str(uuid.uuid4())]),
                              ("-c", ["-c", "--fork-session"]), ("a title", ["--resume", "some title", "--fork-session"])):
        before = len(os.listdir(os.path.join(c.state, "profile-sessions")))
        code, so, se = c.forge(["start", "@list"] + extra_args)
        last = [json.loads(x) for x in open(c.claude_log)][-1]
        want("fork-record: %s: exit 0, the arguments as given, no FORGE_SESSION, no new record" % label,
             (code, last["argv"][-len(extra_args):], last["argv"].count("--session-id"), last["session"], len(os.listdir(os.path.join(c.state, "profile-sessions"))) - before),
             (0, extra_args, extra_args.count("--session-id"), None, 0))
    with open(path, "rb") as fh:
        if fh.read() != original:
            out.append("the record of the original session was overwritten: by a fork that gave its own --session-id, or one of -c or a title")
    return out


# ---- D. a fork `forge start` launched is switched in place -----------------------------------------------------------------------------

def scenario_inplace(c):
    """The fork of `forge start @list --resume ID --fork-session` asks `forge switch @toy-b` as its session would: its launcher restarts
    it with `--resume NEW` and the other profile; no terminal opens. Then the same with a state folder that cannot be written while the
    request is honoured: the line that says so names the next step, and claude still comes back."""
    out = []
    sid = str(uuid.uuid4())
    code, so, se = c.forge(["start", "@list", "--resume", sid, "--fork-session"], extra={"FAKE_CLAUDE_SWITCH": "toy-b"}, timeout=90)
    rows = [json.loads(x) for x in open(c.claude_log)] if os.path.exists(c.claude_log) else []
    switched = json.load(open(c.claude_log + ".switch")) if os.path.exists(c.claude_log + ".switch") else None
    want("inplace: exit 0, two claudes, the switch asked inside the fork was accepted", (code, len(rows), switched and switched[0]), (0, 2, 0))
    if len(rows) == 2:
        new_id = rows[0]["session"]
        argv = rows[1]["argv"]
        want("inplace: the second claude resumes the fork's id with the other profile and no fork", (argv[-2:], "--fork-session" in argv, rows[1]["profile"]),
             (["--resume", new_id], False, "toy-b"))
        want("inplace: the line says the profile changed, and drops nothing it should not name", ("list \u2192 toy-b" in so, "not carried over" in so), (True, False))
        want("inplace: the fork's record names the new profile", (tp.read_json(os.path.join(c.state, "profile-sessions", new_id + ".json")) or {}).get("profile"), "toy-b")
    want("inplace: no terminal opened", c.terminals()[0], [])
    # the fallback line
    for x in (c.claude_log, c.claude_log + ".switched", c.claude_log + ".switch"):
        if os.path.exists(x):
            os.remove(x)
    code, so, se = c.forge(["start", "@list"], extra={"FAKE_CLAUDE_SWITCH": "toy-b", "FAKE_BREAK_DIR": os.path.join(c.state, "profile-settings")}, timeout=90)
    rows = [json.loads(x) for x in open(c.claude_log)] if os.path.exists(c.claude_log) else []
    want("fallback: claude came back (two runs) and the launcher's exit is 0", (code, len(rows)), (0, 2))
    line = [x for x in se.splitlines() if "cannot switch" in x]
    want("fallback: one line, with the next step `forge switch @toy-b`", (len(line), line and "`forge switch @toy-b`" in line[0]), (1, True))
    print("fallback: looked at 1 line")
    return out


def scenario_register(c):
    """The command a refusal outside a project suggests registers the folder it was run from: for a folder whose name is not a project name
    (`My App`) as well as for one whose name is. (CodeRabbit, pull request 187: `forge new '/srv/My App'` was refused as not kebab-case.)"""
    out = []
    looked = 0
    for base, label in (("My App", "my-app"), ("plain-app", "plain-app")):
        d = os.path.join(c.w.root, "projects", base)  # inside the toy world: its HOME check refuses projects outside it
        os.makedirs(d)
        code, so, se = c.forge(["start", "@toy-b"], cwd=d)
        found = re.search(r"`forge (new [^`]*)`", se)
        want("register %r: `forge start` outside a project refuses and suggests `forge new ...`" % base, (code, bool(found)), (2, True))
        if not found:
            continue
        words = shlex.split(found.group(1))
        code, so, se = c.forge(words, cwd=d)
        project = os.path.join(c.w.forge, "config", "projects", label + ".claude.json")
        want("register %r: the suggested `forge %s` registers the folder (exit 0, project file %s.claude.json)" % (base, found.group(1), label),
             (code, os.path.exists(project), (tp.read_json(project) or {}).get("project_path") == os.path.realpath(d) if os.path.exists(project) else None),
             (0, True, True))
        want("register %r: --name only where the folder's name is no project name" % base, "--name" in words, base == "My App")
        looked += 1
    want("register: looked at both folders", looked, 2)
    print("register: looked at %d folders" % looked)
    return out


# ---- the harness ----------------------------------------------------------------------------------------------------------------------

CONTROLS = (
    # (scenario, file, the line to break, what it becomes, the message that must appear)
    ("sweep", "forge/profiles.py", '    return "declares no profiles (the `profiles` field is described in %s)" % DOC',
     '    return "declares no profiles"', "no next step in: ! forge start: project 'none' declares no profiles", {}),
    ("fork", "forge/launch.py", "    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}",
     "    os.kill(int(os.environ['CLAUDE_PID']), 15)\n    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}",
     "killed a session it did not launch", {}),
    ("fork", "forge/launch.py", '"--resume", sid, "--fork-session"]', '"--resume", sid]', "terminal arguments", {}),
    ("fork", "forge/launch.py", 'sid = str(uuid.UUID(os.environ.get("CLAUDE_CODE_SESSION_ID") or ""))',
     'sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or "none"', "a terminal was opened without a session id", {}),
    ("fork", "forge/launch.py", "        code = child.wait(timeout=TERMINAL_LOOK)", "        code = child.wait()", "forge switch waited for the terminal", {}),
    ("fork", "forge/launch.py", "        code = child.wait(timeout=TERMINAL_LOOK)", "        code = None",
     "fork: a terminal that ends at once with an error", {}),
    ("fork", "forge/launch.py", "if code == 0 else", "if False else", "fork: a terminal that hands the window over and ends with 0", {}),
    ("fork", "forge/launch.py", '"CLAUDE_CODE_MESSAGING_TOKEN", "FORGE_SESSION"', '"FORGE_SESSION"', "none of the session's variables reach the terminal", {}),
    ("record", "forge/launch.py", "forked = not fresh and forks(args) and resumes is not None and not gave_session_id(args)", "forked = False",
     "fork-record: claude gets --resume ID --fork-session and a --session-id of its own", {}),
    ("record", "forge/launch.py", "else None if forks(args) else resumes", "else resumes", "the record of the original session was overwritten", {}),
    ("sweep", "forge/launch.py", '            profiles.drop_session(sid)\n        return cannot_exec("forge start", claude, e)\n',
     "            profiles.drop_session(sid)\n        raise\n",
     "sweep: start: claude is on PATH and cannot be executed: provoked, exit 1", {}),
    ("sweep", "forge/run.py", '"! forge run: %s; `claude --resume %s` in this folder opens that session to see why" % (problem, sid)', '"! forge run: %s" % problem',
     "no next step in: ! forge run: claude's output is not a result document", {}),
    ("inplace", "forge/launch.py", "; fix that, then run `forge switch @%s` again\" % (\n                target, why, profile, note, target)",
     "\" % (\n                target, why, profile, note)", "fallback: one line, with the next step", {}),
    ("register", "forge/profiles.py", "    if not new.KEBAB.match(base):", "    if False:", "register 'My App': the suggested", {}),
)
SCENARIOS = {"sweep": scenario_sweep, "fork": scenario_fork, "record": scenario_record, "inplace": scenario_inplace,
             "register": scenario_register}


def run_scenario(name, mutate=None):
    """The failure lines of one scenario in one world, kept apart from the real run's."""
    mine = []
    _sink.append(mine)
    c = Ctx(mutate=mutate)
    try:
        return mine + SCENARIOS[name](c)
    finally:
        _sink.pop()
        c.cleanup()


def self_check():
    """The checker itself can fail: a message with no next step is the failure line the task names."""
    msg = "! forge start: no profile '@x'"
    want("control: a message without its next step", next_step(msg, "`forge start @code`"), "no next step in: " + msg)
    want("control: a message with it", next_step(msg + "; run `forge start @code`", "`forge start @code`"), None)


def main():
    try:
        self_check()
        for name in SCENARIOS:
            failures.extend(run_scenario(name))
        if not os.environ.get("FORGE_MESSAGES_NO_CONTROLS"):
            for name, rel, old, new, message, _ in CONTROLS:
                try:
                    got = run_scenario(name, mutate=(rel, old, new))
                except AssertionError as e:  # the anchor is not in the file: the control would look at nothing
                    failures.append("control %s: %s" % (name, e))
                    continue
                if os.environ.get("FORGE_MESSAGES_SHOW"):
                    print("control %s: %s" % (name, next((x for x in got if message in x), got)))
                if not any(message in x for x in got):
                    failures.append("control %s (%s -> %s) did not fail with %r: %s" % (name, old[:40], new[:30], message, got))
    finally:
        sandbox.cleanup()
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print("ok: messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
