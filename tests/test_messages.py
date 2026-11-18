#!/usr/bin/env python3
"""Every refusal of `forge start @NAME`, `forge list @`, `forge switch @NAME` and `forge run @NAME` names the command that fixes it
(forge/profiles.py, forge/launch.py, forge/run.py), and `forge switch @B` in a session no `forge start` launched opens a terminal with
`forge start @B --resume ID --fork-session` instead of only refusing (4.4 U2).

The world is test_profiles' (an engine copy, a toy HOME, the projects `multi`, `none`, `frozen-p`, `errs`) and three directories that
stand for PATH, each holding only fake programs (ORDERS 10): `full` (python3, git, a fake claude, a fake terminal called
`xdg-terminal-exec`), `noclaude` and `noterm`. The fake terminal records its arguments, its working directory, the session variables it
inherited and its process group, then waits for a release file: a `forge switch` that waited for it would be seen waiting. No real
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
C. `forge start @list --resume ID --fork-session` does not write the record of ID: claude gives the fork an id of its own, so the
   original session's record, which may belong to a live launcher, is left as it was; `--dry-run` says there is no record.

Written first, run against the code of base 41bd475 (forge/ unchanged, this file as it is now): 48 FAIL lines, 46 refusals looked at, among them
  "FAIL sweep: start: an unknown name with a near one: no next step in: ! forge start: no profile '@toy-' in project 'multi'; did you mean '@toy-b'? There are: @code, @list, @toy-b"
  "FAIL sweep: switch: no terminal on PATH: no next step in: ! forge switch: this is not a session started by `forge start @NAME` (it has no launcher to restart claude): ..."
  "FAIL fork: no terminal was opened (or more than one): 0 run(s)" (the old `forge switch` refused: exit 2, nothing started),
  "FAIL the record of the original session was overwritten: ..." (`forge start @list --resume ID --fork-session` rewrote the record of ID).
Negative controls (CONTROLS: an engine copy with one line broken, the same scenario; the first message each printed, FORGE_MESSAGES_SHOW=1):
  sweep   a doc pointer left out of the no-profiles reason  -> "sweep: start: a project without profiles: no next step in: ! forge start: project 'none' declares no profiles"
  fork    a switch that signals the session (CLAUDE_PID)    -> "killed a session it did not launch: the session's process ended (-15)"
  fork    a fork without --fork-session                     -> "fork: terminal arguments end with `start @list --resume ID --fork-session`: [..., '--resume', 'ID'], want [..., '--fork-session']"
  fork    a missing id taken as an id                       -> "a terminal was opened without a session id: exit 0, [{'argv': [..., '--resume', 'none', '--fork-session'], ...}]"
  fork    a switch that waits for the terminal              -> "forge switch waited for the terminal: no exit in 15 s"
  record  a start that records a fork                       -> "the record of the original session was overwritten: ..."
"""
import json
import os
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
import json, os, sys
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "session": os.environ.get("FORGE_SESSION")}) + "\\n")
"""
FAKE_TERMINAL = """#!%s
import json, os, sys, time
log = os.environ["FAKE_TERM_LOG"]
mine = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PID", "CLAUDECODE", "FORGE_SESSION", "FORGE_LAUNCHER_PID")
def put(doc):
    with open(log, "a") as fh:
        fh.write(json.dumps(doc) + "\\n")
put({"argv": sys.argv[1:], "cwd": os.getcwd(), "inherited": [k for k in mine if k in os.environ], "pgid": os.getpgid(0),
     "ppid_pgid": os.getpgid(os.getppid()) if os.getppid() > 1 else None, "sid": os.getsid(0), "pid": os.getpid()})
t0 = time.time()
while not os.path.exists(log + ".release") and time.time() - t0 < 25:
    time.sleep(0.05)
put({"done": True})
"""


class Ctx:
    """One toy world with its three PATHs, the fake terminal's log and the helpers every scenario uses."""

    def __init__(self, mutate=None, terminal=None):
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
        self.bins = {name: self.bindir(name, claude="noclaude" != name, term="noterm" != name) for name in ("full", "noclaude", "noterm")}
        self.term_log = os.path.join(self.scratch, "terminal.jsonl")
        self.claude_log = os.path.join(self.scratch, "claude.jsonl")
        self.state = os.path.join(w.home, ".local", "state", "forge")
        self.pids = []

    def bindir(self, name, claude, term):
        d = os.path.join(self.scratch, "bin-" + name)
        os.makedirs(d)
        os.symlink(sys.executable, os.path.join(d, "python3"))
        os.symlink(shutil.which("git"), os.path.join(d, "git"))
        for program, text, wanted in (("claude", FAKE_CLAUDE, claude), ("xdg-terminal-exec", FAKE_TERMINAL, term), ("fake-term", FAKE_TERMINAL, term)):
            if wanted:
                with open(os.path.join(d, program), "w") as fh:
                    fh.write(text % sys.executable)
                os.chmod(os.path.join(d, program), 0o755)
        return d

    def forge(self, args, cwd=None, extra=None, path="full", timeout=60):
        """(exit code, stdout, stderr) of `forge ARGS` in the world, from `cwd` (default: project multi)."""
        e = sandbox.bare_env(self.w.home, self.w.root, FAKE_TERM_LOG=self.term_log, FAKE_CLAUDE_LOG=self.claude_log, **(extra or {}))
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
            message = se if stream == "err" else so
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
        if started:
            out.append("sweep: a refusal opened a terminal: %s" % started)
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
        code, so, se = c.forge(["switch", "@list"], extra={"CLAUDE_CODE_SESSION_ID": sid, "CLAUDE_PID": str(session.pid), "CLAUDECODE": "1",
                                                           "FORGE_SESSION": "outer", "FORGE_LAUNCHER_PID": "1"}, timeout=15)
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
    want("fork: none of the session's variables reach the terminal", t["inherited"], [])
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

    # no session id: a refusal, and the terminal never opened (a control opens one with an id of "none")
    code, so, se = c.forge(["switch", "@list"])
    if code == 0 or c.terminals()[0]:  # exit 0 is only said once the terminal was started, which may log a moment later
        out.append("a terminal was opened without a session id: exit %d, %s" % (code, c.terminals()[0]))
        c.release()
    want("fork: no session id: exit 2 and the next step", (code, "`forge start @list`" in se), (2, True))
    return out


# ---- C. a fork is not the session it forks -------------------------------------------------------------------------------------------

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
    want("fork-record: claude gets --resume ID --fork-session and no --session-id",
         ("--fork-session" in last["argv"], "--resume" in last["argv"], "--session-id" in last["argv"]), (True, True, False))
    want("fork-record: FORGE_SESSION is not set for a fork", last["session"], None)
    code, so, se = c.forge(["start", "@list", "--dry-run", "--resume", str(uuid.uuid4()), "--fork-session"])
    want("fork-record: --dry-run says no record, a fork", (code, "no session record" in so and "fork" in so), (0, True))
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
    ("fork", "forge/launch.py", "start_new_session=True)", "start_new_session=True).wait()", "forge switch waited for the terminal", {}),
    ("record", "forge/launch.py", "forked = not fresh and forks(args)", "forked = False",
     "the record of the original session was overwritten", {}),
)
SCENARIOS = {"sweep": scenario_sweep, "fork": scenario_fork, "record": scenario_record}


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
