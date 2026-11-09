#!/usr/bin/env python3
"""`fwx walk` (3.5 U3): lib/fwx/commands/walk.py.

Every case goes through `bin/fwx walk` in a toy repo. No case opens a browser: `agent-browser`, `npx` (Playwright CLI), `ffmpeg`,
`docker` and the rig prefix are fakes that record their argv, their cwd and the AGENT_BROWSER_* variables in a log, and the only
directory on the PATH of the command under test is the one holding them (ORDERS.md rule 10: `python3` and `git` are symlinked in,
nothing else of the system). The app is a detached `python3 -m http.server` that the toy app's `up` starts and its `down` kills;
the ports are free ones the test picked. Every temp dir is made by helpers.mkdtemp, removed at exit, and each app a case started
is stopped in a `finally`.

Seen red before the command existed (python3 tests/test_walk.py; `fwx walk` was not a command, so every call exited 2):
  FAIL: url guard: up with https://app.example.test: exit 2 naming the URL: got (2, 'fwx: unknown command: walk ...'), want (2, True)
  FAIL: probe: a server already answering: the app's up was not run: ... (the app was never reached)
  FAIL: up, the base case: stdout is JSON: got <not JSON: ''>, want an object
  (and the same first line for each of the 11 cases of the unit)

Controls: each case also runs on a copy of bin/ and lib/ with one line of walk.py changed (`MUTANTS`, each `old` is in the file
exactly once) and must fail with the text shown; the good code passes first (363 checks). The unit's eleven controls, the FAIL
line each mutant produced:
  1  url guard removed:       FAIL: url guard: up with https://app.example.test: exit: got 1, want 2
  2  probe removed:           FAIL: probe: a server already answering: exit: got 1, want 2
  3  refusal lists emptied:   FAIL: ab guard: --cdp 9222 snapshot: exit: rc 0:   (and: connect 9222; no --idle-timeout: "carries --idle-timeout")
  4  count ignores the env:   FAIL: down: a process with the run's mark in its environment: exit: got 0, want 1
  5  agent_browser ignored:   FAIL: switch off: exit and JSON: got (0, {'armed': True, ...
  6  run "" as a prefix:      FAIL: run "": ab was called: got [], want ['agent-browser', 'agent-browser', 'agent-browser']
     run "" as absent:        FAIL: run "": run is the empty string, not an absent field: {'armed': True, 'run': None, ...
  7  one app, two walkers:    FAIL: container: 1 app for 2 walkers: got 1, want 2
     containers not removed:  FAIL: container: down removed both by their exact names: got [], want [['rm', '-f', ...
  8  FWX_FACTORY_CONTAINER ignored: FAIL: factory: host app_run used in container mode: the toy app_run up ran
     run dir outside the job: FAIL: factory: run dir outside the job dir: got '.../ui-walk/1-1', want '<job>/ui-walk/1-1'
  9  contradicted in fix.json:FAIL: findings: contradicted finding in fix.json: got ['F1', 'F2', 'F3'], want ['F1', 'F2']
  10 ids numbered:            FAIL: review page: item ids 01,02,03, want F1,F2,F3 (the finding's id, not a number)
     clip kept as webm:       FAIL: review page: figure src is .webm: [..., 'figs/F1-clip.webm', ...]
     no ffmpeg run anyway:    FAIL: review page: no ffmpeg: exit: got 1, want 0
  11 unanswered counted:      FAIL: review answers: open item F3 in accepted: accepted ['F1', 'F3']
The rest of MUTANTS (walk.py's own guards, the rig prefix, the sockets, pw, arm-control, sweep, capacity) each name their FAIL text.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
PY = sys.executable
GIT = shutil.which("git")
SLEEP = shutil.which("sleep")
URL_OFF = "https://app.example.test"
PNG = b"\x89PNG\r\n\x1a\n"

FAKE = """#!%(py)s
import json, os, sys
rec = {"prog": os.path.basename(sys.argv[0]), "argv": sys.argv[1:], "cwd": os.getcwd(),
       "env": {k: v for k, v in os.environ.items() if k.startswith("AGENT_BROWSER_")}}
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\\n")
%(tail)s
"""
TAILS = {
    "agent-browser": 'sys.exit(int(os.environ.get("FAKE_RC", "0")))',
    "npx": 'sys.exit(int(os.environ.get("FAKE_RC", "0")))',
    "fakerig": 'i = sys.argv.index("--"); os.execvp(sys.argv[i + 1], sys.argv[i + 1:])',
    "ffmpeg": 'open(sys.argv[-1], "wb").write(b"RIFF")',
    "docker": """
db = os.environ["FAKE_DOCKER"]
names = [n for n in open(db).read().split() if n] if os.path.exists(db) else []
if sys.argv[1:2] == ["ps"]:
    print("\\n".join(names))
elif sys.argv[1:3] == ["rm", "-f"]:
    open(db, "w").write("\\n".join(n for n in names if n != sys.argv[3]) + "\\n")
""",
}
UP = """import json, os, socket, subprocess, sys
port, pidfile = int(sys.argv[1]), sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(here, "up-ran"), "a").write("x\\n")
with open(pidfile + ".env", "a") as f:
    f.write(json.dumps({k: v for k, v in os.environ.items() if k.startswith("FWX_WALK_")}) + "\\n")
if os.environ.get("FWX_WALK_STATE"):
    json.dump({"cookies": [{"name": "sess", "value": "s3cret", "domain": "localhost", "path": "/"},
                           {"name": "last", "value": "pwd", "domain": "localhost", "path": "/"}], "origins": []},
              open(os.environ["FWX_WALK_STATE"], "w"))
if os.environ.get("FAKE_DOCKER") and os.environ.get("FWX_WALK_NAME"):
    open(os.environ["FAKE_DOCKER"], "a").write(os.environ["FWX_WALK_NAME"] + "\\n")
if len(sys.argv) > 3 and sys.argv[3] == "fail":
    sys.exit(1)
c = socket.socket()
busy = c.connect_ex(("127.0.0.1", port)) == 0
c.close()
if not busy:
    p = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True, cwd=here)
    open(pidfile, "a").write(str(p.pid) + "\\n")
"""
DOWN = """import os, signal, sys
here = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(here, "down-ran"), "a").write("x\\n")
pidfile = sys.argv[1]
for pid in (open(pidfile).read().split() if os.path.exists(pidfile) else []):
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        pass
if os.path.exists(pidfile):
    os.remove(pidfile)
"""


def runner(root):
    def run(cwd, *args, env=None):
        return subprocess.run([sys.executable, os.path.join(root, "bin", "fwx")] + list(args), cwd=cwd,
                              env=helpers.clean_env(**(env or {})), capture_output=True, text=True)
    run.root = root
    return run


def copy_tree(root, *patches):
    """A copy of bin/, lib/, data/ and templates/ of `root` with each (path, old, new) applied; each `old` is in its file exactly once."""
    dest = helpers.mkdtemp("fwx-walk-tree-")
    for d in ("bin", "lib", "data", "templates"):
        if os.path.isdir(os.path.join(root, d)):
            shutil.copytree(os.path.join(root, d), os.path.join(dest, d), ignore=shutil.ignore_patterns("__pycache__"))
    for path, old, new in patches:
        p = os.path.join(dest, path)
        text = open(p, encoding="utf-8").read()
        assert text.count(old) == 1, "control: %r is in %s %d times, want 1" % (old, path, text.count(old))
        open(p, "w", encoding="utf-8").write(text.replace(old, new))
    return dest


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def script(path, text):
    helpers.write(os.path.dirname(path), os.path.basename(path), text, 0o755)
    return path


class Scene:
    """A toy repo with its configuration, an app (`up.py`/`down.py` in the repo) and the fakes on the only PATH."""

    def __init__(self, ab=True, prefix="", container=False, url_tpl=None, limits=None, app=True, firefox=True, fake_up=None):
        self.port = free_port()
        self.pidfile = None
        self.url = "http://127.0.0.1:%d" % self.port
        files = {"README": "toy\n", "up.py": UP, "down.py": DOWN, ".gitignore": "*.pid*\nup-ran\ndown-ran\n"}
        self.repo = helpers.toy_repo(files)
        self.pidfile = os.path.join(self.repo, "app.pid")
        self.run_dir_root = helpers.mkdtemp("fwx-walk-phase-")
        app_run = {"up": "python3 up.py %d %s" % (self.port, self.pidfile), "run": prefix,
                   "down": "python3 down.py %s" % self.pidfile, "url": url_tpl or self.url}
        if container:
            app_run["container"] = True
        cfg = {"schema": 1, "integrations": {"agent_browser": ab},
               "project": {"app_run": app_run if app else None}}
        if limits is not None:
            cfg["limits"] = {"per_project": limits}
        helpers.write(self.repo, ".claude/fwx.json", json.dumps(cfg))
        self.bin = helpers.mkdtemp("fwx-walk-bin-")
        for name, target in (("python3", PY), ("git", GIT)):
            os.symlink(target, os.path.join(self.bin, name))
        self.state = helpers.mkdtemp("fwx-walk-state-")
        self.log = os.path.join(self.state, "calls.jsonl")
        for name, tail in TAILS.items():
            self.fake(name)
        self.docker = os.path.join(self.state, "docker.txt")
        self.home = helpers.mkdtemp("fwx-walk-home-")
        self.browsers = helpers.mkdtemp("fwx-walk-browsers-")
        if firefox:
            os.makedirs(os.path.join(self.browsers, "firefox-1569"))
        meminfo = os.path.join(self.state, "meminfo")
        helpers.write(self.state, "meminfo", "MemAvailable: %d kB\n" % (64 * 1024 * 1024))
        self.env = {"PATH": self.bin, "FAKE_LOG": self.log, "FAKE_DOCKER": self.docker, "FWX_MEMINFO": meminfo,
                    "HOME": self.home, "PLAYWRIGHT_BROWSERS_PATH": self.browsers, "FWX_FACTORY_CONTAINER": "",
                    "FWX_WALK_OWNER_PID": str(os.getpid())}
        self.started = []

    def fake(self, name):
        script(os.path.join(self.bin, name), FAKE % {"py": PY, "tail": TAILS[name]})

    def drop(self, name):
        os.remove(os.path.join(self.bin, name))

    def calls(self, prog=None):
        if not os.path.exists(self.log):
            return []
        recs = [json.loads(line) for line in open(self.log, encoding="utf-8") if line.strip()]
        return [r for r in recs if prog is None or r["prog"] == prog]

    def clear(self):
        if os.path.exists(self.log):
            os.remove(self.log)

    def up(self, R, *extra, part=1, rnd=1, env=None, tramos=None):
        args = ["walk", "up", "--dir", self.run_dir_root, "--part", str(part), "--round", str(rnd), "--repo", self.repo]
        if tramos:
            args += ["--tramos", str(tramos)]
        r = R(self.repo, *args, *extra, env=dict(self.env, **(env or {})))
        return r, obj(r.stdout)

    def walk(self, R, *args, env=None):
        return R(self.repo, "walk", *args, env=dict(self.env, **(env or {})))

    def stop(self):
        """Kill what `up` left behind, whatever the case did."""
        for pf in [self.pidfile]:
            for p in (open(pf).read().split() if os.path.exists(pf) else []):
                try:
                    os.kill(int(p), 15)
                except OSError:
                    pass


def obj(text):
    try:
        v = json.loads(text.strip().splitlines()[-1]) if text.strip() else None
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def jfile(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def case_url_guard(R, S):
    """Control 1."""
    sc = Scene()
    try:
        app = json.dumps({"up": "python3 up.py %d %s fail" % (sc.port, sc.pidfile), "run": "", "down": "true", "url": URL_OFF})
        r, o = sc.up(R, "--app", app)
        S.eq("url guard: up with %s: exit" % URL_OFF, r.returncode, 2)
        S.ok("url guard: up with %s: exit 2 naming the URL" % URL_OFF, URL_OFF in r.stderr, r.stderr)
        S.ok("url guard: the app's up was not run", not os.path.exists(os.path.join(sc.repo, "up-ran")))
        for url in ("http://x.localhost:3000", "http://[::1]:3000", "http://localhost:3000"):
            sc.clear()
            app = json.dumps({"up": "python3 up.py %d %s fail" % (sc.port, sc.pidfile), "run": "", "down": "true", "url": url})
            r, o = sc.up(R, "--app", app)
            S.ok("url guard: %s is local, so up is run (and fails in the toy)" % url,
                 r.returncode == 1 and os.path.exists(os.path.join(sc.repo, "up-ran")), "rc %d: %s" % (r.returncode, r.stderr))
        r, o = sc.up(R)
        S.ok("url guard: a local server arms", r.returncode == 0 and o and o.get("armed") is True, "rc %d %s %s" % (r.returncode, r.stdout, r.stderr))
    finally:
        sc.stop()


def case_probe(R, S):
    """Control 2."""
    sc = Scene()
    srv = subprocess.Popen([PY, "-m", "http.server", str(sc.port), "--bind", "127.0.0.1"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, cwd=sc.state)
    try:
        for _ in range(50):
            c = socket.socket()
            ok = c.connect_ex(("127.0.0.1", sc.port)) == 0
            c.close()
            if ok:
                break
            time.sleep(0.1)
        app = json.dumps({"up": "python3 up.py %d %s fail" % (sc.port, sc.pidfile), "run": "", "down": "true", "url": sc.url})
        r, o = sc.up(R, "--app", app)
        S.eq("probe: a server already answering: exit", r.returncode, 2)
        S.ok("probe: a server already answering: says so", "already answering before up" in r.stderr and sc.url in r.stderr, r.stderr)
        S.ok("probe: a server already answering: the app's up was not run", not os.path.exists(os.path.join(sc.repo, "up-ran")))
    finally:
        srv.terminate()
        srv.wait()
        sc.stop()


def armed(sc, R, S, label, **kw):
    r, o = sc.up(R, **kw)
    if not S.ok("%s: up armed" % label, r.returncode == 0 and o and o.get("armed") is True, "rc %d: %s %s" % (r.returncode, r.stdout, r.stderr)):
        return None
    return o


def case_up(R, S):
    """What `up` leaves: run.json, the state file the app wrote, the capacity, the owner."""
    sc = Scene()
    try:
        o = armed(sc, R, S, "up, the base case")
        if not o:
            return
        rd = os.path.join(sc.run_dir_root, "ui-walk", "1-1")
        S.eq("up: run_dir", o.get("run_dir"), rd)
        S.eq("up: url", o.get("url"), sc.url)
        S.eq("up: capacity role", (o.get("capacity") or {}).get("role"), "ui-walker")
        S.eq("up: capacity is asked for two walkers per tramo", (o.get("capacity") or {}).get("want"), 2)
        run = jfile(os.path.join(rd, "run.json")) or {}
        S.eq("up: run.json holds the url", run.get("url"), sc.url)
        S.eq("up: run.json holds one app", [a["url"] for a in run.get("apps", [])], [sc.url])
        env = [json.loads(line) for line in open(sc.pidfile + ".env")]
        S.eq("up: FWX_WALK_STATE", env[0].get("FWX_WALK_STATE"), os.path.join(rd, "demo-state.json"))
        S.ok("up: the app wrote the demo session where it was told", os.path.exists(os.path.join(rd, "demo-state.json")))
        S.ok("up: no FWX_WALK_NAME outside container mode", "FWX_WALK_NAME" not in env[0], str(env[0]))
        S.eq("up: the app's processes carry the run's mark", env[0].get("FWX_WALK_RUN"), run.get("namespace"))
        # a second up of the same part and round: the app answers now, so it is refused
        r2, _ = sc.up(R)
        S.ok("up: twice on one run is refused, the app answers", r2.returncode == 2 and "already answering" in r2.stderr, r2.stderr)
        r = sc.walk(R, "down", "--run", rd)
        S.eq("up: down", r.returncode, 0)
    finally:
        sc.stop()
    # an app whose up fails: exit 1 with the log's tail, nothing armed
    sc = Scene()
    try:
        app = json.dumps({"up": "python3 up.py %d %s fail" % (sc.port, sc.pidfile), "run": "", "down": "true", "url": sc.url})
        r, o = sc.up(R, "--app", app)
        S.ok("up: a failing up exits 1", r.returncode == 1 and "up failed" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
        S.ok("up: a failing up leaves no run.json", not os.path.exists(os.path.join(sc.run_dir_root, "ui-walk", "1-1", "run.json")))
    finally:
        sc.stop()


def case_ab_guard(R, S):
    """Control 3."""
    sc = Scene()
    try:
        o = armed(sc, R, S, "ab guard")
        if not o:
            return
        rd = o["run_dir"]
        ns = jfile(os.path.join(rd, "run.json"))["namespace"]

        def ab(*args):
            return sc.walk(R, "ab", "--run", rd, "w1", *args)
        sc.clear()
        for args in (["--cdp", "9222", "snapshot"], ["--cdp=9222", "snapshot"], ["connect", "9222"], ["--profile", "x", "open", sc.url],
                     ["--auto-connect", "snapshot"], ["--headed", "open", sc.url], ["auth", "login", "x"],
                     ["--state", "/etc/passwd", "open", sc.url], ["--namespace", "other", "snapshot"],
                     ["--session", "other", "snapshot"], ["--allowed-domains", "example.test", "snapshot"], ["batch", "open x"],
                     ["open", "https://a.example.test"], ["open", "a.example.test/x"], ["goto", "http://evil.example.test"],
                     ["tab", "new", "https://a.example.test"], ["open", "file:///etc/passwd"],
                     ["eval", "location = 'https://a.example.test/x'"], ["eval", "fetch(`https://a.example.test/x`)"]):
            r = ab(*args)
            S.ok("ab guard: %s: exit" % " ".join(args), r.returncode == 2 and "fwx walk ab: refused" in r.stderr, "rc %d: %s" % (r.returncode, r.stderr))
        S.eq("ab guard: a refused call never reached the binary", sc.calls(), [])
        sc.clear()
        for args in (["snapshot", "-i"], ["open", sc.url + "/x"], ["fill", "@e1", "connect"], ["eval", "1+1"],
                     ["eval", "fetch('%s/api')" % sc.url], ["--state", os.path.join(rd, "s.json"), "snapshot"]):
            sc.clear()
            r = ab(*args)
            calls = sc.calls("agent-browser")
            S.ok("ab guard: %s: accepted, exit" % " ".join(args), r.returncode == 0 and len(calls) >= 1, "rc %d: %s" % (r.returncode, r.stderr))
            last = calls[-1]["argv"] if calls else []
            for want in ("--namespace", ns, "--session", "w1", "--idle-timeout", "20m", "--screenshot-dir", "--args",
                         "--font-render-hinting=none", "--allowed-domains"):
                S.ok("ab guard: %s: carries %s" % (" ".join(args), want), want in last, str(last))
            S.ok("ab guard: %s: the user's words come last" % " ".join(args), last[-len(args):] == list(args), str(last))
        # the namespace is the run's, not the session's; the screenshots go where the run says
        run = jfile(os.path.join(rd, "run.json"))
        S.ok("ab guard: screenshots under the git common dir", run["shots"].startswith(
            os.path.join(sc.repo, ".git", "fwx", "walks")), run["shots"])
        # the child never sees an AGENT_BROWSER_ variable the walker exported
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w1", "snapshot", env={"AGENT_BROWSER_PROFILE": "/srv/profile"})
        S.ok("ab guard: AGENT_BROWSER_PROFILE from the caller is dropped", all("AGENT_BROWSER_PROFILE" not in c["env"] for c in sc.calls()),
             str(sc.calls()))
        # without --run the only open run of the repository is the one meant
        sc.clear()
        r = sc.walk(R, "ab", "w1", "snapshot")
        S.ok("ab guard: no --run, one open run: that run", r.returncode == 0 and ns in sc.calls("agent-browser")[-1]["argv"], "rc %d %s" % (r.returncode, r.stderr))
        # a missing binary is NOT RUN, not an error of the walk
        sc.drop("agent-browser")
        r = ab("snapshot")
        S.ok("ab guard: no agent-browser on the PATH: NOT RUN, NOT ARMED, exit 77", r.returncode == 77 and "NOT RUN, NOT ARMED: agent-browser missing" in r.stderr,
             "rc %d: %s" % (r.returncode, r.stderr))
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


def case_ab_session(R, S):
    """What `ab` does around a session: the demo session by cookies, the init script at launch, `run` only on the launch."""
    sc = Scene(prefix="fakerig run --")
    try:
        o = armed(sc, R, S, "ab session")
        if not o:
            return
        rd = o["run_dir"]
        S.eq("ab session: run is the prefix", o.get("run"), "fakerig run --")
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + "/board")
        S.eq("ab session: arm-control exit", r.returncode, 0)
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w1", "open", sc.url + "/board")
        S.eq("ab session: first call exit", r.returncode, 0)
        recs = sc.calls()
        progs = [c["prog"] for c in recs]
        S.eq("ab session: only the call that launches the daemon goes through the rig prefix", progs,
             ["fakerig", "agent-browser", "agent-browser", "agent-browser", "agent-browser"])
        ab_calls = [c for c in recs if c["prog"] == "agent-browser"]
        S.eq("ab session: the first call is a cookie of the demo session, with the app's url", ab_calls[0]["argv"][-6:],
             ["cookies", "set", "sess", "s3cret", "--url", sc.url])
        S.eq("ab session: the second cookie follows", ab_calls[1]["argv"][-6:], ["cookies", "set", "last", "pwd", "--url", sc.url])
        S.eq("ab session: then the viewport, then the user's command", ab_calls[2]["argv"][-5:], ["set", "viewport", "1309", "818", "1.1"])
        S.ok("ab session: --init-script rides on the launch only", "--init-script" in ab_calls[0]["argv"] and all(
            "--init-script" not in c["argv"] for c in ab_calls[1:]), str([c["argv"] for c in ab_calls]))
        S.eq("ab session: the user's command last", ab_calls[-1]["argv"][-2:], ["open", sc.url + "/board"])
        sock = os.path.join(sc.home, ".agent-browser")
        S.eq("ab session: the calls after the launch find the daemon through the socket dir",
             [c["env"].get("AGENT_BROWSER_SOCKET_DIR") for c in ab_calls], [None, sock, sock, sock])
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w1", "snapshot", "-i")
        recs = sc.calls()
        S.eq("ab session: a later call is not wrapped and starts no cookies", [(c["prog"], c["argv"][-2:]) for c in recs],
             [("agent-browser", ["snapshot", "-i"])])
        S.eq("ab session: a later call carries the socket dir", recs[0]["env"].get("AGENT_BROWSER_SOCKET_DIR"), sock)
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w1", "close")
        S.eq("ab session: close exit", r.returncode, 0)
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w1", "snapshot")
        S.eq("ab session: after close the next call launches again (through the prefix)", sc.calls()[0]["prog"], "fakerig")
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w2", "snapshot")
        S.eq("ab session: another session launches on its own", sc.calls()[0]["prog"], "fakerig")
        r = sc.walk(R, "ab", "--run", rd, "bad name", "snapshot")
        S.eq("ab session: a session name with a space is refused", r.returncode, 2)
        sc.clear()
        r = sc.walk(R, "down", "--run", rd)
        S.ok("ab session: down closes the namespace through the socket dir", any(
            c["argv"][-2:] == ["close", "--all"] and c["env"].get("AGENT_BROWSER_SOCKET_DIR") == sock for c in sc.calls("agent-browser")),
             str(sc.calls()))
    finally:
        sc.stop()


REFUSED_COMMANDS = ("inspect", "stream", "dashboard", "mcp", "plugin", "install", "upgrade", "doctor", "profiles")


def case_ab_commands(R, S):
    """`ab` refuses the agent-browser commands that open a window or a listener or reach outside the session (3.5 U3b).

    Seen red before the refusal existed (`ab inspect` and `ab stream enable` were passed to the binary):
      FAIL: ab commands: inspect: exit 2 naming the word: rc 0:
      FAIL: ab commands: stream enable: exit 2 naming the word: rc 0:
      FAIL: ab commands: nothing refused reached the binary: got [{'prog': 'agent-browser', ...
    """
    sc = Scene()
    try:
        o = armed(sc, R, S, "ab commands")
        if not o:
            return
        rd = o["run_dir"]
        sc.clear()
        for args in (["inspect"], ["stream", "enable"], ["stream", "enable", "--port", "9999"], ["--json", "stream", "status"], ["dashboard", "start"],
                     ["mcp"], ["plugin", "add", "x"], ["install"], ["upgrade"], ["doctor", "--fix"], ["profiles"]):
            r = sc.walk(R, "ab", "--run", rd, "w1", *args)
            word = [a for a in args if not a.startswith("-")][0]
            S.ok("ab commands: %s: exit 2 naming the word" % " ".join(args),
                 r.returncode == 2 and "fwx walk ab: refused" in r.stderr and word in r.stderr, "rc %d: %s" % (r.returncode, r.stderr))
        r = sc.walk(R, "ab", "--run", rd, "w1", "read", "https://a.example.test/x")
        S.ok("ab commands: read <url> outside the app: refused (the CLI fetches it, not the browser)", r.returncode == 2, "rc %d: %s" % (r.returncode, r.stderr))
        S.eq("ab commands: nothing refused reached the binary", sc.calls(), [])
        # the words a walker needs, and a refused word typed as text, still go through
        for args in (["snapshot"], ["screenshot"], ["console"], ["errors"], ["get", "text", "h1"], ["wait", "10"], ["fill", "@e1", "inspect"],
                     ["type", "@e1", "stream"], ["eval", "1+1"], ["record", "start", os.path.join(rd, "c.webm")], ["read"]):
            sc.clear()
            r = sc.walk(R, "ab", "--run", rd, "w1", *args)
            S.ok("ab commands: %s: still accepted" % " ".join(args), r.returncode == 0 and sc.calls("agent-browser")
                 and sc.calls("agent-browser")[-1]["argv"][-len(args):] == list(args), "rc %d: %s" % (r.returncode, r.stderr))
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


def case_ab_viewport(R, S):
    """The first call of a session sets the viewport the `pw` path uses, once (3.5 U3b).

    Seen red before the code existed (`ab` passed only cookies and the user's command to the binary):
      FAIL: ab viewport: the first open sets the viewport once: got 0, want 1
      FAIL: ab viewport: it comes before the user's command: ...
    """
    sc = Scene()
    try:
        o = armed(sc, R, S, "ab viewport")
        if not o:
            return
        rd = o["run_dir"]

        def sized(calls):
            return [c["argv"][c["argv"].index("viewport") - (c["argv"][c["argv"].index("viewport") - 1] == "set"):]
                    for c in calls if "viewport" in c["argv"]]
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w1", "open", sc.url + "/a")
        calls = sc.calls("agent-browser")
        S.eq("ab viewport: first open exit", r.returncode, 0)
        S.eq("ab viewport: the first open sets the viewport once, with the pw size and scale", sized(calls), [["set", "viewport", "1309", "818", "1.1"]])
        S.eq("ab viewport: it comes before the user's command, which is last", [c["argv"][-1] for c in calls][-1], sc.url + "/a")
        S.ok("ab viewport: it carries the session", all("w1" in c["argv"] for c in calls), str([c["argv"] for c in calls]))
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w1", "open", sc.url + "/b")
        S.eq("ab viewport: a second open of the same session does not repeat it", sized(sc.calls("agent-browser")), [])
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w1", "viewport", "1440", "900")
        S.eq("ab viewport: an explicit viewport is passed through untouched", [c["argv"][-3:] for c in sc.calls("agent-browser")],
             [["viewport", "1440", "900"]])
        # a session whose first call is the caller's own viewport keeps only that one
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w2", "viewport", "1440", "900")
        S.eq("ab viewport: a first call that is a viewport is not preceded by ours", sized(sc.calls("agent-browser")), [["viewport", "1440", "900"]])
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w3", "set", "viewport", "800", "600")
        S.eq("ab viewport: `set viewport` as the first call likewise", sized(sc.calls("agent-browser")), [["set", "viewport", "800", "600"]])
        # another session sizes on its own
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w4", "open", sc.url + "/c")
        S.eq("ab viewport: another session is sized on its own", len(sized(sc.calls("agent-browser"))), 1)
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


def case_run_empty(R, S):
    """Control 6."""
    sc = Scene(prefix="")
    try:
        r, o = sc.up(R)
        S.ok('run "": armed', r.returncode == 0 and o and o.get("armed") is True, r.stderr)
        S.ok('run "": run is the empty string, not an absent field', o is not None and o.get("run") == "", str(o))
        rd = (o or {}).get("run_dir")
        if not rd:
            return
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w1", "snapshot")
        calls = sc.calls()
        S.eq('run "": ab was called', [c["prog"] for c in calls], ["agent-browser"] * 4)
        S.eq('run "": ab runs in the repo', {c["cwd"] for c in calls}, {sc.repo})
        S.ok('run "": no socket dir without a prefix', all("AGENT_BROWSER_SOCKET_DIR" not in c["env"] for c in calls), str(calls))
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


def case_pw(R, S):
    sc = Scene(prefix="fakerig run --")
    try:
        o = armed(sc, R, S, "pw")
        if not o:
            return
        rd = o["run_dir"]
        ns = jfile(os.path.join(rd, "run.json"))["namespace"]
        sc.clear()
        r = sc.walk(R, "pw", "--run", rd, "w1", "open", sc.url)
        S.eq("pw: open exit", r.returncode, 0)
        recs = sc.calls()
        S.eq("pw: open goes through the rig prefix, once", [c["prog"] for c in recs], ["fakerig", "npx"])
        argv = recs[-1]["argv"]
        S.eq("pw: offline, no install, the pinned CLI", argv[:3], ["--offline", "--no-install", "@playwright/cli@0.1.23"])
        S.ok("pw: the session is the run's", "-s=%s-w1" % ns in argv, str(argv))
        S.ok("pw: Firefox from the run's config", argv[-4:-2] == ["--browser", "firefox"] and argv[-2] == "--config", str(argv))
        cfg = jfile(argv[-1]) or {}
        S.eq("pw: the config is Firefox, headless, 1309x818 at 1.1", (
            cfg.get("browser", {}).get("browserName"), cfg.get("browser", {}).get("launchOptions", {}).get("headless"),
            cfg.get("browser", {}).get("contextOptions")), ("firefox", True, {"viewport": {"width": 1309, "height": 818}, "deviceScaleFactor": 1.1}))
        sc.clear()
        sc.walk(R, "pw", "--run", rd, "w1", "snapshot")
        S.eq("pw: a later call is not wrapped", [c["prog"] for c in sc.calls()], ["npx"])
        sc.clear()
        r = sc.walk(R, "pw", "--run", rd, "w1", "goto", "https://a.example.test")
        S.ok("pw: an outside url is refused", r.returncode == 2 and sc.calls() == [], "rc %d %s" % (r.returncode, r.stderr))
        r = sc.walk(R, "pw", "--run", rd, "w1", "open", sc.url, "--browser", "chromium")
        S.ok("pw: the browser is not the caller's to choose", r.returncode == 2 and sc.calls() == [], "rc %d %s" % (r.returncode, r.stderr))
        shutil.rmtree(os.path.join(sc.browsers, "firefox-1569"))
        r = sc.walk(R, "pw", "--run", rd, "w2", "open", sc.url)
        S.ok("pw: no Firefox: NOT RUN, NOT ARMED: Playwright Firefox missing", r.returncode == 77 and
             "NOT RUN, NOT ARMED: Playwright Firefox missing" in r.stderr and sc.calls() == [], "rc %d %s" % (r.returncode, r.stderr))
        os.makedirs(os.path.join(sc.browsers, "firefox-1569"))
        sc.clear()
        sc.walk(R, "down", "--run", rd)
        S.ok("pw: down closes the Playwright session it opened", any(c["prog"] == "npx" and "close" in c["argv"] and "-s=%s-w1" % ns in c["argv"]
                                                                      for c in sc.calls()), str(sc.calls()))
    finally:
        sc.stop()


def case_arm_control(R, S):
    sc = Scene()
    try:
        o = armed(sc, R, S, "arm-control")
        if not o:
            return
        rd = o["run_dir"]
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", "https://a.example.test/board")
        S.eq("arm-control: a screen outside the app is refused", r.returncode, 2)
        S.ok("arm-control: nothing written for it", not os.path.exists(os.path.join(rd, "control.json")))
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + "/board")
        S.eq("arm-control: exit", r.returncode, 0)
        c = jfile(os.path.join(rd, "control.json")) or {}
        S.eq("arm-control: control.json names the screen", c.get("screen"), sc.url + "/board")
        S.eq("arm-control: and its path", c.get("path"), "/board")
        script_text = open(c.get("script", os.devnull), encoding="utf-8").read() if c.get("script") else ""
        S.ok("arm-control: the init script acts on that route only", '"/board"' in script_text and "location.pathname" in script_text, script_text[:200])
        S.ok("arm-control: with a MutationObserver that watches no attribute",
             "MutationObserver" in script_text and "attributes" not in script_text, script_text[:300])
        S.ok("arm-control: the main title takes the body's size and weight",
             "font-size" in script_text and "font-weight" in script_text and "h1" in script_text, script_text[:300])
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


def case_down_count(R, S):
    """Control 4."""
    sc = Scene()
    sleeper = None
    try:
        o = armed(sc, R, S, "down")
        if not o:
            return
        rd = o["run_dir"]
        ns = jfile(os.path.join(rd, "run.json"))["namespace"]
        sleeper = subprocess.Popen([SLEEP, "300"], env=dict(os.environ, FWX_WALK_RUN=ns), stdout=subprocess.DEVNULL)
        r = sc.walk(R, "down", "--run", rd)
        d = obj(r.stdout) or {}
        S.eq("down: a process with the run's mark in its environment: exit", r.returncode, 1)
        S.ok("down: the process is named by its pid", str(sleeper.pid) in r.stdout + r.stderr, r.stdout + r.stderr)
        S.eq("down: down.json holds the pids left", [p.get("pid") for p in (jfile(os.path.join(rd, "down.json")) or {}).get("left", [])], [sleeper.pid])
        S.ok("down: it says how many it looked at", isinstance(d.get("looked"), int) and d["looked"] > 0, str(d))
        sleeper.kill()
        sleeper.wait()
        sleeper = None
        r = sc.walk(R, "down", "--run", rd)
        d = obj(r.stdout) or {}
        S.eq("down: without it: exit", r.returncode, 0)
        S.ok("down: without it: looked at N processes", "looked at" in r.stderr and " processes" in r.stderr and d.get("looked", 0) > 0 and d.get("left") == [],
             "%s %s" % (r.stderr, d))
        S.ok("down: the app's own down was run", os.path.exists(os.path.join(sc.repo, "down-ran")))
        S.ok("down: nothing answers at the url any more", not _answers(sc.port))
        # by the run's directory or by its namespace: both name the run
        r = sc.walk(R, "down", "--run", ns)
        S.eq("down: by namespace", r.returncode, 0)
        r = sc.walk(R, "down", "--run", "no-such-run")
        S.eq("down: a run nobody knows is exit 2", r.returncode, 2)
        # a failing down of the app is a failure of down
        helpers.write(sc.repo, "down.py", "import sys\nsys.exit(3)\n")
        r = sc.walk(R, "down", "--run", rd)
        S.ok("down: the app's down failing is exit 1", r.returncode == 1 and "down" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        if sleeper:
            sleeper.kill()
            sleeper.wait()
        sc.stop()


def _answers(port):
    c = socket.socket()
    c.settimeout(1)
    try:
        return c.connect_ex(("127.0.0.1", port)) == 0
    finally:
        c.close()


def case_off(R, S):
    """Control 5, and `up` without an app."""
    sc = Scene(ab=False)
    try:
        r, o = sc.up(R)
        S.ok("switch off: exit and JSON", r.returncode == 0 and bool(o) and o.get("armed") is False and "agent_browser" in o.get("reason", ""),
             "got (%d, %s) %s" % (r.returncode, o, r.stderr))
        S.ok("switch off: NOT RUN, NOT ARMED on stderr", "NOT RUN, NOT ARMED" in r.stderr, r.stderr)
        S.ok("switch off: the app's up was not run", not os.path.exists(os.path.join(sc.repo, "up-ran")))
    finally:
        sc.stop()
    sc = Scene(app=False)
    try:
        r, o = sc.up(R)
        S.ok("no app_run: NOT RUN, NOT ARMED, exit 0, armed false", r.returncode == 0 and o and o.get("armed") is False and
             "NOT RUN, NOT ARMED" in r.stderr and "app_run" in r.stderr, "got (%d, %s) %s" % (r.returncode, o, r.stderr))
        r, o = sc.up(R, "--app", json.dumps({"up": "x", "down": "y", "url": "http://localhost:1"}))
        S.ok("--app with a missing key: exit 2 naming it", r.returncode == 2 and "run" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        sc.stop()


def case_container(R, S):
    """Control 7."""
    sc = Scene(container=True, url_tpl=None, limits={"ui-walker": 2})
    try:
        tpl = sc.url + "/{name}"
        app = {"up": "python3 up.py %d %s" % (sc.port, sc.pidfile), "run": "fakerig run --name {name} --", "down": "python3 down.py %s" % sc.pidfile,
               "url": tpl, "container": True}
        r, o = sc.up(R, "--app", json.dumps(app))
        if not S.ok("container: armed", r.returncode == 0 and o and o.get("armed") is True, "rc %d %s %s" % (r.returncode, r.stdout, r.stderr)):
            return
        rd = o["run_dir"]
        run = jfile(os.path.join(rd, "run.json")) or {}
        apps = run.get("apps", [])
        S.eq("container: 1 app for 2 walkers", len(apps), 2)
        if len(apps) != 2:
            return
        S.eq("container: capacity", (o.get("capacity") or {}).get("allowed"), 2)
        envs = [json.loads(line) for line in open(sc.pidfile + ".env")]
        names = [e.get("FWX_WALK_NAME") for e in envs]
        ns = run["namespace"]
        S.eq("container: two ups with FWX_WALK_NAME <run>-w<k>", names, [ns + "-w1", ns + "-w2"])
        S.eq("container: each app has its own demo state", [e.get("FWX_WALK_STATE") for e in envs],
             [os.path.join(rd, "demo-state-w1.json"), os.path.join(rd, "demo-state-w2.json")])
        S.eq("container: the urls follow the names", [a["url"] for a in apps], [sc.url + "/" + ns + "-w1", sc.url + "/" + ns + "-w2"])
        S.eq("container: the run prefix follows the names", [a["run"] for a in apps], ["fakerig run --name %s-w%d --" % (ns, k) for k in (1, 2)])
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w2", "open", sc.url + "/" + ns + "-w2")
        recs = sc.calls()
        S.eq("container: ab w2 goes through the second app's prefix", [c["argv"][:3] for c in recs if c["prog"] == "fakerig"],
             [["run", "--name", ns + "-w2"]])
        cookie = [c["argv"] for c in recs if c["prog"] == "agent-browser"][0]
        S.eq("container: ab w2 uses the second app's url", cookie[-1], sc.url + "/" + ns + "-w2")
        r = sc.walk(R, "ab", "--run", rd, "w3", "snapshot")
        S.ok("container: a third walker has no app", r.returncode == 2 and "w3" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
        r = sc.walk(R, "ab", "--run", rd, "main", "snapshot")
        S.ok("container: a session that is not w<k> has no app", r.returncode == 2, "rc %d %s" % (r.returncode, r.stderr))
        # the toy up declared the two containers; its down does not remove them: `down` does, by exact name
        helpers.write(sc.state, "docker.txt", "%s-w1\n%s-w2\nother-%s-w1\nunrelated\n" % (ns, ns, ns))
        sc.clear()
        r = sc.walk(R, "down", "--run", rd)
        d = obj(r.stdout) or {}
        S.eq("container: down exit", r.returncode, 0)
        S.eq("container: down removed both by their exact names", [c["argv"] for c in sc.calls("docker") if c["argv"][:2] == ["rm", "-f"]],
             [["rm", "-f", ns + "-w1"], ["rm", "-f", ns + "-w2"]])
        S.eq("container: how many containers are left", (d.get("containers") or {}).get("left"), [])
        S.eq("container: the others are left alone", open(sc.docker).read().split(), ["other-%s-w1" % ns, "unrelated"])
        S.ok("container: the app's down ran once per app", len(open(os.path.join(sc.repo, "down-ran")).read().split()) == 2)
        # a container that docker cannot remove is a failure of down, and counted
        sc.fake("docker")
        script(os.path.join(sc.bin, "docker"), FAKE % {"py": PY, "tail": 'if sys.argv[1:2] == ["ps"]:\n    print(os.environ["FAKE_STUCK"])\nelse:\n    sys.exit(1)'})
        r = sc.walk(R, "down", "--run", rd, env={"FAKE_STUCK": ns + "-w1"})
        d = obj(r.stdout) or {}
        S.ok("container: a container still there after down: exit 1 and counted", r.returncode == 1 and (d.get("containers") or {}).get("left") == [ns + "-w1"],
             "rc %d %s" % (r.returncode, d))
        sc.drop("docker")
        r = sc.walk(R, "down", "--run", rd)
        S.ok("container: no docker to ask is exit 1, said", r.returncode == 1 and "docker" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        sc.stop()
    # no room: capacity 0 starts nothing
    sc = Scene(container=True, limits={"ui-walker": 1})
    try:
        meminfo = os.path.join(sc.state, "meminfo")
        helpers.write(sc.state, "meminfo", "MemAvailable: %d kB\n" % (1024 * 1024))  # 1 GiB, floor is 3
        r, o = sc.up(R)
        S.ok("container: no room for a walker: exit 1, the app not started", r.returncode == 1 and "no room" in r.stderr and
             not os.path.exists(os.path.join(sc.repo, "up-ran")), "rc %d %s" % (r.returncode, r.stderr))
    finally:
        sc.stop()


def case_capacity_missing(R, S):
    """`fwx capacity` that cannot answer is a quota of one, said."""
    sc = Scene()
    try:
        os.remove(sc.env["FWX_MEMINFO"])
        r, o = sc.up(R)
        S.ok("capacity unavailable: armed with a quota of 1, and it says why", r.returncode == 0 and o and (o.get("capacity") or {}).get("allowed") == 1 and
             "capacity" in json.dumps(o.get("capacity")).lower() and (o["capacity"].get("note") or "").startswith("capacity unavailable"),
             "rc %d %s %s" % (r.returncode, o, r.stderr))
        if o:
            sc.walk(R, "down", "--run", o["run_dir"])
    finally:
        sc.stop()


FACTORY_CONST = 'FACTORY_UI_DIR = "/opt/fwx/ui"'


def case_factory(R, S):
    """Control 8: the case runs on a copy of the tree whose FACTORY_UI_DIR (the module's constant) is a toy folder."""
    ui = helpers.mkdtemp("fwx-walk-ui-")
    R = runner(copy_tree(R.root, (W, FACTORY_CONST, "FACTORY_UI_DIR = %r" % ui)))
    sc = Scene()
    try:
        job = helpers.mkdtemp("fwx-walk-job-")
        script(os.path.join(ui, "up"), "#!%s\nimport json, os, subprocess, sys\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui-up-ran'), 'a').write(os.environ.get('FWX_WALK_STATE', 'no-state') + '\\n')\n"
               "p = subprocess.Popen([sys.executable, '-m', 'http.server', '%d', '--bind', '127.0.0.1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)\n"
               "open(%r, 'a').write(str(p.pid) + '\\n')\nprint('booting')\nprint(json.dumps({'url': %r}))\n" % (PY, sc.port, sc.pidfile, sc.url))
        script(os.path.join(ui, "down"), "#!%s\nimport os\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui-down-ran'), 'a').write('x\\n')\n"
               "import signal\nfor p in (open(%r).read().split() if os.path.exists(%r) else []):\n    os.kill(int(p), signal.SIGTERM)\nif os.path.exists(%r): os.remove(%r)\n" % (PY, sc.pidfile, sc.pidfile, sc.pidfile, sc.pidfile))
        r = sc.walk(R, "up", "--dir", job, "--part", "1", "--round", "1", "--repo", sc.repo, env={"FWX_FACTORY_CONTAINER": "1"})
        o = obj(r.stdout) or {}
        S.ok("factory: armed", r.returncode == 0 and o.get("armed") is True, "rc %d %s %s" % (r.returncode, r.stdout, r.stderr))
        S.ok("factory: the image's up was run", os.path.exists(os.path.join(ui, "ui-up-ran")), "the image's up never ran")
        S.ok("factory: host app_run used in container mode", not os.path.exists(os.path.join(sc.repo, "up-ran")), "the toy app_run up ran")
        S.eq("factory: the url is the last line of up", o.get("url"), sc.url)
        S.eq("factory: run dir outside the job dir", o.get("run_dir"), os.path.join(job, "ui-walk", "1-1"))
        S.eq("factory: the state file reaches the image's up", open(os.path.join(ui, "ui-up-ran")).read().strip(), os.path.join(job, "ui-walk", "1-1", "demo-state.json"))
        rd = o.get("run_dir")
        if rd:
            r = sc.walk(R, "down", "--run", rd, env={"FWX_FACTORY_CONTAINER": "1"})
            S.eq("factory: down exit", r.returncode, 0)
            S.ok("factory: down ran the image's down and not app_run's", os.path.exists(os.path.join(ui, "ui-down-ran")) and
                 not os.path.exists(os.path.join(sc.repo, "down-ran")), "image down ran: %s, host down ran: %s" % (
                     os.path.exists(os.path.join(ui, "ui-down-ran")), os.path.exists(os.path.join(sc.repo, "down-ran"))))
    finally:
        sc.stop()
    # an image whose up prints no url on its last line is not armed
    sc = Scene()
    try:
        job = helpers.mkdtemp("fwx-walk-job-")
        script(os.path.join(ui, "up"), "#!%s\nprint('no json here')\n" % PY)
        script(os.path.join(ui, "down"), "#!%s\n" % PY)
        r = sc.walk(R, "up", "--dir", job, "--part", "1", "--round", "1", "--repo", sc.repo, env={"FWX_FACTORY_CONTAINER": "1"})
        S.ok("factory: an up with no url on its last line: exit 1", r.returncode == 1 and "url" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        sc.stop()


def case_findings(R, S):
    """Control 9."""
    rd = helpers.mkdtemp("fwx-walk-run-")

    def f(i, verdict, sev="major"):
        return {"id": i, "file": "src/a.ts", "line": 3, "claim": "claim " + i, "evidence": "e", "severity": sev, "screen": "/x", "verdict": verdict}
    helpers.write(rd, "verified-1.json", json.dumps([f("F1", "CONFIRMED"), f("F2", "PLAUSIBLE", "minor"), f("F4", "NOT REPRODUCED")]))
    helpers.write(rd, "verified-2.json", json.dumps({"findings": [f("F3", "CONTRADICTED", "cosmetic"), f("F5", "DUPLICATE")]}))
    r = runner_walk(R, "findings", "--run", rd)
    d = obj(r.stdout) or {}
    S.eq("findings: exit", r.returncode, 0)
    fix = jfile(os.path.join(rd, "fix.json")) or []
    con = jfile(os.path.join(rd, "contradicted.json")) or []
    S.eq("findings: contradicted finding in fix.json", [x["id"] for x in fix], ["F1", "F2"])
    S.eq("findings: contradicted.json", [x["id"] for x in con], ["F3"])
    S.eq("findings: the counts", d.get("counts"), {"confirmed": 1, "plausible": 1, "contradicted": 1, "dropped": 2})
    S.eq("findings: severity in the 3.4 words (blocker and major high, minor medium, cosmetic low)", [x["severity"] for x in fix] + [x["severity"] for x in con],
         ["high", "medium", "low"])
    S.eq("findings: the paths", (d.get("fix_file"), d.get("contradicted_file")), (os.path.join(rd, "fix.json"), os.path.join(rd, "contradicted.json")))
    # a second pass changes nothing it already wrote
    r = runner_walk(R, "findings", "--run", rd)
    S.eq("findings: twice", [x["id"] for x in jfile(os.path.join(rd, "fix.json"))], ["F1", "F2"])
    # nothing to read, a finding with no id, two with one id, an unknown verdict
    empty = helpers.mkdtemp("fwx-walk-run-")
    r = runner_walk(R, "findings", "--run", empty)
    S.ok("findings: no verified-*.json is exit 2 (looking at zero)", r.returncode == 2 and "verified" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    for label, body in (("no id", [{"verdict": "CONFIRMED"}]), ("a repeated id", [f("F1", "CONFIRMED"), f("F1", "PLAUSIBLE")]),
                        ("an unknown verdict", [f("F1", "MAYBE")])):
        bad = helpers.mkdtemp("fwx-walk-run-")
        helpers.write(bad, "verified-1.json", json.dumps(body))
        r = runner_walk(R, "findings", "--run", bad)
        S.ok("findings: %s is exit 2" % label, r.returncode == 2 and not os.path.exists(os.path.join(bad, "fix.json")), "rc %d %s" % (r.returncode, r.stderr))


def runner_walk(R, *args, env=None):
    """`fwx walk ...` from a toy folder with the fakes' PATH (ffmpeg is added by the case that needs it)."""
    return R(CWD[0], "walk", *args, env=env or {"PATH": FAKE_DIR_FOR[0]})


FAKE_DIR_FOR = [None]
CWD = [None]


def fixed_run(fix_ids=("F1", "F2", "F3", "F4"), contra="F5", with_clip=True, images=("F1", "F2")):
    """A run folder with fix.json, contradicted.json and their evidence: F1 has a clip; the ids in `images` have a picture before
    and after (a fix) and the contradicted one a picture before; the others have a sentence."""
    rd = helpers.mkdtemp("fwx-walk-run-")
    os.makedirs(os.path.join(rd, "shots"))
    for i in list(images) + [contra]:
        for kind in ("today", "built"):
            with open(os.path.join(rd, "shots", "%s-%s.png" % (kind, i)), "wb") as fh:
                fh.write(PNG)
    helpers.write(rd, "shots/clip1.webm", "webm")

    def f(i, **kw):
        d = {"id": i, "file": "src/a.ts", "line": 3, "claim": "claim %s" % i, "evidence": "a sentence for %s" % i,
             "severity": "high", "screen": "/board", "expected": "title bigger", "type": "hierarchy", "kind": "observed"}
        if i in images or i == contra:
            d["evidence"] = os.path.join(rd, "shots", "today-%s.png" % i)
        if i in images:
            d["evidence_after"] = os.path.join(rd, "shots", "built-%s.png" % i)
        if i == "F1" and with_clip:
            d["clip"] = os.path.join(rd, "shots", "clip1.webm")
        d.update(kw)
        return d
    helpers.write(rd, "fix.json", json.dumps([f(i) for i in fix_ids]))
    helpers.write(rd, "contradicted.json", json.dumps([f(contra, kind="judgement")]))
    return rd


def case_review_page(R, S):
    """Control 10."""
    bindir = helpers.mkdtemp("fwx-walk-bin-")
    for name, target in (("python3", PY), ("git", GIT)):
        os.symlink(target, os.path.join(bindir, name))
    logdir = helpers.mkdtemp("fwx-walk-log-")
    log = os.path.join(logdir, "calls.jsonl")
    script(os.path.join(bindir, "ffmpeg"), FAKE % {"py": PY, "tail": TAILS["ffmpeg"]})
    env = {"PATH": bindir, "FAKE_LOG": log}
    rd = fixed_run(("F1", "F2"), "F3")
    fixed = os.path.join(helpers.mkdtemp("fwx-walk-fixed-"), "fixed.json")
    helpers.write(os.path.dirname(fixed), "fixed.json", json.dumps([{"id": "F1", "commit": "abc1234"}, {"id": "F2", "commit": "def5678"}]))
    r = runner_walk(R, "review-page", "--run", rd, "--fixed", fixed, env=env)
    S.eq("review page: exit", r.returncode, 0)
    page = jfile(os.path.join(rd, "review", "decisions.json")) or {}
    items = page.get("items", [])
    ids = [i.get("id") for i in items]
    S.ok("review page: item ids 01,02,03, want F1,F2,F3 (the finding's id, not a number)", ids == ["F1", "F2", "F3"],
         "item ids %s, want F1,F2,F3" % ",".join(ids) if ids else "no items")
    S.eq("review page: the asks", [i.get("ask") for i in items], ["¿Mantener este arreglo?", "¿Mantener este arreglo?", "¿Cambiar lo aprobado por esto?"])
    caps = [[fg.get("caption") for fg in i.get("figures", [])] for i in items]
    S.ok("review page: today and built on a fix, today on a contradicted", "today" in caps[0] and "built" in caps[0] and "built" in caps[1] and caps[2] == ["today"], str(caps))
    figs = [fg for i in items for fg in i.get("figures", [])]
    S.ok("review page: every figure exists next to decisions.json", all(os.path.exists(os.path.join(rd, "review", fg["src"])) for fg in figs), str(figs))
    S.ok("review page: figure src is .webm", not any(fg["src"].endswith(".webm") for fg in figs), str([fg["src"] for fg in figs]))
    S.ok("review page: with a clip and ffmpeg the figure is .webp", any(fg["src"].endswith(".webp") for fg in items[0]["figures"]),
         str([fg["src"] for fg in items[0]["figures"]]))
    ff = [json.loads(line) for line in open(log)] if os.path.exists(log) else []
    S.ok("review page: ffmpeg asked for 640 px, 12 fps, libwebp_anim, quality 60", len(ff) == 1 and all(
        w in " ".join(ff[0]["argv"]) for w in ("libwebp_anim", "fps=12", "scale=640:-1", "-quality 60")), str(ff))
    S.ok("review page: a finding's text evidence and commit are in the item", "abc1234" in json.dumps(items[0]), json.dumps(items[0]))
    S.ok("review page: top-level fields of the verdict format", set(page) <= {"title", "intro", "items", "v", "run"} and page.get("title"), str(sorted(page)))
    keys = {k for i in items for k in i}
    S.ok("review page: only fields the verdict builder knows", keys <= {"id", "title", "what", "figures", "ask", "recommend"}, str(keys))
    m = jfile(os.path.join(rd, "review", "map.json")) or {}
    S.eq("review page: map.json says which items are fixes and which are contradicted", {k: v["kind"] for k, v in m.items()}, {"F1": "fix", "F2": "fix", "F3": "contradicted"})
    # no ffmpeg
    os.remove(os.path.join(bindir, "ffmpeg"))
    rd2 = fixed_run(("F1", "F2"), "F3")
    r = runner_walk(R, "review-page", "--run", rd2, "--fixed", fixed, env=env)
    S.eq("review page: no ffmpeg: exit", r.returncode, 0)
    S.ok("review page: no ffmpeg: NOT RUN, NOT ARMED: ffmpeg missing", "NOT RUN, NOT ARMED: ffmpeg missing" in r.stderr, r.stderr)
    items2 = (jfile(os.path.join(rd2, "review", "decisions.json")) or {}).get("items", [])
    S.eq("review page: no ffmpeg: still three items", [i["id"] for i in items2], ["F1", "F2", "F3"])
    S.ok("review page: no ffmpeg: the item carries the captures and gives the clip's path", not any(
        fg["src"].endswith((".webm", ".webp")) for fg in items2[0]["figures"]) and os.path.join(rd2, "shots", "clip1.webm") in json.dumps(items2[0]),
         json.dumps(items2[0]))
    # bad input
    bad = os.path.join(os.path.dirname(fixed), "bad.json")
    helpers.write(os.path.dirname(fixed), "bad.json", json.dumps([{"id": "F9", "commit": "abc1234"}]))
    r = runner_walk(R, "review-page", "--run", rd2, "--fixed", bad, env=env)
    S.ok("review page: a fixed id that is no finding is exit 2", r.returncode == 2 and "F9" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    rd3 = fixed_run(("F1", "F2"), "F3")
    os.remove(os.path.join(rd3, "shots", "built-F2.png"))
    r = runner_walk(R, "review-page", "--run", rd3, "--fixed", fixed, env=env)
    S.ok("review page: an evidence image that is missing is exit 2 naming it", r.returncode == 2 and "built-F2.png" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))


def case_review_answers(R, S):
    """Control 11."""
    bindir = helpers.mkdtemp("fwx-walk-bin-")
    for name, target in (("python3", PY), ("git", GIT)):
        os.symlink(target, os.path.join(bindir, name))
    env = {"PATH": bindir}
    rd = fixed_run(with_clip=False)  # F1..F4 are fixes, F5 is contradicted
    fixed = os.path.join(helpers.mkdtemp("fwx-walk-fixed-"), "fixed.json")
    helpers.write(os.path.dirname(fixed), "fixed.json", json.dumps([{"id": i, "commit": "c" + i} for i in ("F1", "F2", "F3", "F4")]))
    r = runner_walk(R, "review-page", "--run", rd, "--fixed", fixed, env=env)
    S.eq("review answers: the page for the case", r.returncode, 0)
    answers = {"v": 2, "F1": {"pick": "ok"}, "F2": {"pick": "no", "note": "the clip is too slow"}, "F4": {"pick": "ok"}, "F5": {"pick": "ok"},
               "open": ["F3"], "stale": ["F4"], "global": "thanks"}
    af = os.path.join(helpers.mkdtemp("fwx-walk-ans-"), "wait.out")
    helpers.write(os.path.dirname(af), "wait.out", "waiting for the answers\n" + json.dumps(answers) + "\n")
    r = runner_walk(R, "review-answers", "--run", rd, af, env=env)
    d = obj(r.stdout) or {}
    S.eq("review answers: exit", r.returncode, 0)
    S.ok("review answers: open item F3 in accepted", d.get("accepted") == ["F1"], "accepted %s" % d.get("accepted"))
    S.eq("review answers: rejected with its note", d.get("rejected"), [{"id": "F2", "note": "the clip is too slow"}])
    S.eq("review answers: a contradicted one he wants", d.get("contradicted_wanted"), ["F5"])
    S.eq("review answers: open", d.get("open"), ["F3"])
    S.eq("review answers: stale (answered ok, but not accepted)", d.get("stale"), ["F4"])
    S.eq("review answers: review/answers.json is what is printed", jfile(os.path.join(rd, "review", "answers.json")), d)
    # an item missing from the answers and from `open` is open all the same; a contradicted one he declines is neither
    helpers.write(os.path.dirname(af), "wait2.out", json.dumps({"v": 2, "F1": {"pick": "ok"}, "F5": {"pick": "no"}}))
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(os.path.dirname(af), "wait2.out"), env=env)
    d = obj(r.stdout) or {}
    S.eq("review answers: what he did not touch is open", d.get("open"), ["F2", "F3", "F4"])
    S.eq("review answers: a contradicted one declined is not wanted", d.get("contradicted_wanted"), [])
    # not an answer, an id the page never had, no page
    helpers.write(os.path.dirname(af), "junk.out", "no json here\n")
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(os.path.dirname(af), "junk.out"), env=env)
    S.ok("review answers: no JSON in the file is exit 2", r.returncode == 2, "rc %d %s" % (r.returncode, r.stderr))
    helpers.write(os.path.dirname(af), "other.out", json.dumps({"v": 2, "F9": {"pick": "ok"}}))
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(os.path.dirname(af), "other.out"), env=env)
    S.ok("review answers: an id the page never had is exit 2", r.returncode == 2 and "F9" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    r = runner_walk(R, "review-answers", "--run", helpers.mkdtemp("fwx-walk-run-"), af, env=env)
    S.ok("review answers: a run with no page is exit 2", r.returncode == 2, "rc %d %s" % (r.returncode, r.stderr))


def case_sweep(R, S):
    sc = Scene()
    port2 = free_port()
    url2 = "http://127.0.0.1:%d" % port2
    dead = subprocess.Popen([SLEEP, "0"])
    dead.wait()
    try:
        r, a = sc.up(R, part=1, rnd=1)
        S.ok("sweep: a run with a live owner", r.returncode == 0 and a and a.get("armed"), r.stderr)
        # the second run lives in the same repo as the first (the walks folder is the repository's), owned by a process that is gone
        app = json.dumps({"up": "python3 up.py %d %s" % (port2, sc.pidfile + "2"), "run": "", "down": "python3 down.py %s" % (sc.pidfile + "2"), "url": url2})
        r, b = sc.up(R, "--app", app, part=1, rnd=2, env={"FWX_WALK_OWNER_PID": str(dead.pid)})
        S.ok("sweep: a run whose owner is gone", r.returncode == 0 and b and b.get("armed"), r.stderr)
        if not (a and b):
            return
        r = sc.walk(R, "ab", "w1", "snapshot")
        S.ok("sweep: two open runs and no --run: exit 2", r.returncode == 2 and "--run" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
        r = sc.walk(R, "sweep")
        d = obj(r.stdout) or {}
        S.eq("sweep: exit", r.returncode, 0)
        S.eq("sweep: looked at two runs", d.get("looked"), 2)
        S.eq("sweep: took down the one without an owner", [x.get("run_dir") for x in d.get("swept", [])], [b["run_dir"]])
        S.eq("sweep: left the one with a live owner", [x.get("run_dir") for x in d.get("kept", [])], [a["run_dir"]])
        S.ok("sweep: the swept run's app is down", not _answers(port2))
        S.ok("sweep: the kept run's app still answers", _answers(sc.port))
        S.ok("sweep: down.json written for the swept run", os.path.exists(os.path.join(b["run_dir"], "down.json")))
        r = sc.walk(R, "down", "--run", a["run_dir"])
        S.eq("sweep: the kept run goes down by hand", r.returncode, 0)
        r = sc.walk(R, "sweep")
        d = obj(r.stdout) or {}
        S.ok("sweep: a closed run is not swept again", r.returncode == 0 and d.get("swept") == [] and d.get("looked") == 0, str(d))
    finally:
        sc.stop()
        for pf in (sc.pidfile + "2",):
            for p in (open(pf).read().split() if os.path.exists(pf) else []):
                try:
                    os.kill(int(p), 15)
                except OSError:
                    pass


def case_usage(R, S):
    sc = Scene()
    for argv in ([], ["bogus"], ["up"], ["ab"], ["ab", "w1"], ["pw"], ["arm-control"], ["findings"], ["review-page"], ["review-answers"], ["down"],
                  ["up", "--bogus"], ["up", "--dir", "x", "--part", "x", "--round", "1"]):
        r = sc.walk(R, *argv)
        S.ok("usage: walk %s: exit 2 and a usage line" % " ".join(argv), r.returncode == 2 and "usage: fwx walk" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    h = R(sc.repo, "help")
    S.ok("`fwx help` lists walk", "walk" in h.stdout, h.stdout)


CASES = [case_url_guard, case_probe, case_up, case_ab_guard, case_ab_session, case_ab_commands, case_ab_viewport, case_run_empty, case_pw, case_arm_control, case_down_count,
         case_off, case_container, case_capacity_missing, case_factory, case_findings, case_review_page, case_review_answers, case_sweep,
         case_usage]

W = "lib/fwx/commands/walk.py"
# (name, case, old text, new text, the FAIL text it must produce); each `old` is in walk.py exactly once, and a control whose `old`
# has gone is an error, never a silent pass. The first eleven are the unit's controls, in its order.
MUTANTS = [
    ("1 url guard", case_url_guard, 'if a["url"] and not local_host(a["url"]):', "if False:", "url guard: up with https://app.example.test: exit: got 1, want 2"),
    ("2 probe", case_probe, 'if a["url"] and answering(a["url"]):', "if False:", "probe: a server already answering: exit: got 1, want 2"),
    ("3 refused flags", case_ab_guard, 'REFUSED_FLAGS = ("--cdp", "--auto-connect", "--profile", "--headed")', "REFUSED_FLAGS = ()",
     "ab guard: --cdp 9222 snapshot: exit"),
    ("3 refused words", case_ab_guard, 'REFUSED_WORDS = ("connect", "auth", "batch", "chat")', "REFUSED_WORDS = ()", "ab guard: connect 9222: exit"),
    ("3 no idle timeout", case_ab_guard, '"--idle-timeout", IDLE_TIMEOUT, ', "", "ab guard: snapshot -i: carries --idle-timeout"),
    ("3 no font flag", case_ab_guard, '"--args", FONT_ARGS, ', "", "ab guard: snapshot -i: carries --font-render-hinting=none"),
    ("3 open url unchecked", case_ab_guard, "urls = words[at + 1:]", "urls = []", "ab guard: open https://a.example.test: exit"),
    ("3 eval url unchecked", case_ab_guard, "urls += [m for c in code for m in URL_IN_CODE.findall(c)]", "pass",
     "ab guard: eval location = 'https://a.example.test/x': exit"),
    ("3 state anywhere", case_ab_guard, 'if not inside(path, run["run_dir"]):', "if False:", "ab guard: --state /etc/passwd open"),
    ("3 own flags by the caller", case_ab_guard, 'if flag_in(t, OWN_FLAGS) or (pw and flag_in(t, ("-s",))):', "if False:",
     "ab guard: --namespace other snapshot: exit"),
    ("3 caller's AGENT_BROWSER_ kept", case_ab_guard, 'e = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_BROWSER_")}',
     "e = dict(os.environ)", "ab guard: AGENT_BROWSER_PROFILE from the caller is dropped"),
    ("4 count without the environment", case_down_count, 'marked = marked or any(e.partition(b"=")[2] == ns.encode() for e in f.read().split(b"\\0"))',
     "marked = marked or False", "down: a process with the run's mark in its environment: exit: got 0, want 1"),
    ("4 left does not fail down", case_down_count, "return res, 0 if ok and not left else 1", "return res, 0 if ok else 1",
     "down: a process with the run's mark in its environment: exit: got 0, want 1"),
    ("5 switch ignored", case_off, 'if not cfg["integrations"].get("agent_browser"):', "if False:", "switch off: exit and JSON"),
    ("6 run '' as a prefix", case_run_empty, 'prefix = shlex.split(app["run"])\n    for i, (a, quiet)',
     'prefix = [app["run"]]\n    for i, (a, quiet)', 'run "": ab was called'),
    ("6 run '' as absent", case_run_empty, '"run": apps[0]["run"], "hosts"', '"run": apps[0]["run"] or None, "hosts"', 'run "": run is the empty string'),
    ("7 one app for two walkers", case_container, 'names = [ns + "-w%d" % k for k in range(1, cap["allowed"] + 1)] if container else [ns]',
     'names = [ns + "-w1"] if container else [ns]', "container: 1 app for 2 walkers: got 1, want 2"),
    ("7 containers not removed", case_container, 'subprocess.run(["docker", "rm", "-f", n], capture_output=True, text=True)', "pass",
     "container: down removed both by their exact names"),
    ("7 containers left not a failure", case_container, 'ok = ok and containers["left"] == []', "ok = ok",
     "container: a container still there after down: exit 1 and counted"),
    ("7 no room still starts", case_container, 'if cap["allowed"] < 1:', "if False:", "container: no room for a walker"),
    ("8 factory variable ignored", case_factory, 'factory = os.environ.get("FWX_FACTORY_CONTAINER") == "1"', "factory = False",
     "factory: host app_run used in container mode"),
    ("8 run dir outside the job dir", case_factory, 'run_dir = os.path.join(os.path.abspath(o["--dir"]), "ui-walk", "%d-%d" % (part, rnd))',
     'run_dir = os.path.join(repo, "ui-walk", "%d-%d" % (part, rnd))', "factory: run dir outside the job dir"),
    ("8 factory down is app_run's", case_factory, '"down": shlex.quote(os.path.join(FACTORY_UI_DIR, "down"))', '"down": "python3 down.py x"',
     "factory: down ran the image's down and not app_run's"),
    ("9 contradicted in fix.json", case_findings, 'if verdict in ("CONFIRMED", "PLAUSIBLE"):', 'if verdict in ("CONFIRMED", "PLAUSIBLE", "CONTRADICTED"):',
     "findings: contradicted finding in fix.json"),
    ("9 no files is fine", case_findings, "if not files:", "if False:", "findings: no verified-*.json is exit 2"),
    ("10 ids numbered", case_review_page, '"items": items})', '"items": [dict(i, id="%02d" % n) for n, i in enumerate(items, 1)]})',
     "review page: item ids 01,02,03, want F1,F2,F3"),
    ("10 clip kept as webm", case_review_page, 'return [{"src": name, "caption": "clip"}], []', 'return [{"src": name[:-5] + ".webm", "caption": "clip"}], []',
     "review page: figure src is .webm"),
    ("10 no ffmpeg run anyway", case_review_page, 'if not shutil.which("ffmpeg"):', "if False:", "review page: no ffmpeg: exit"),
    ("10 unknown fixed id", case_review_page, 'if x["id"] not in fix:', "if False:", "review page: a fixed id that is no finding is exit 2"),
    ("10 missing picture", case_review_page, "if not os.path.isfile(p):", "if False:", "review page: an evidence image that is missing is exit 2"),
    ("11 unanswered counted", case_review_answers, 'pick = a.get("pick")', 'pick = a.get("pick") or "ok"', "review answers: open item F3 in accepted"),
    ("11 stale counted", case_review_answers, "        if fid in stale:\n            continue", "        if False:\n            continue",
     "review answers: open item F3 in accepted"),
    ("ab: the prefix on every call", case_ab_session, 'rc = execute((prefix if launch else []) + ["agent-browser"] + a, env, run["repo"], quiet)',
     'rc = execute(prefix + ["agent-browser"] + a, env, run["repo"], quiet)',
     "ab session: only the call that launches the daemon goes through the rig prefix"),
    ("ab: no socket dir", case_ab_session, 'env = clean_env({"AGENT_BROWSER_SOCKET_DIR": socket_dir()} if prefix and not launch else None)',
     "env = clean_env()", "ab session: a later call carries the socket dir"),
    ("ab: no cookies", case_ab_session, 'for name, value in cookies_of(app["state"]):', "for name, value in []:",
     "ab session: the first call is a cookie of the demo session"),
    ("ab: no init script", case_ab_session, "if os.path.isfile(ctl):", "if False:", "ab session: --init-script rides on the launch only"),
    ("ab: close keeps the session", case_ab_session, 'if "close" in words:', "if False:", "ab session: after close the next call launches again"),
    ("ab: commands refused", case_ab_commands, 'REFUSED_COMMANDS = (', 'REFUSED_COMMANDS = () and (', "ab commands: inspect: exit 2 naming the word"),
    ("ab: no viewport", case_ab_viewport, "if sized_first:", "if False:", "ab viewport: the first open sets the viewport once"),
    ("ab: viewport on every call", case_ab_viewport, "if sized_first:", "if True:", "ab viewport: a second open of the same session does not repeat it"),
    ("ab: viewport over the caller's", case_ab_viewport, "sized_first = fresh and not own_size", "sized_first = fresh",
     "ab viewport: a first call that is a viewport is not preceded by ours"),
    ("pw: not offline", case_pw, '"npx", "--offline", "--no-install", ', '"npx", "--no-install", ', "pw: offline, no install, the pinned CLI"),
    ("pw: no Firefox check", case_pw, "if not os.path.isdir(os.path.join(pw_browsers(), PW_FIREFOX)):", "if False:", "pw: no Firefox"),
    ("arm-control: any screen", case_arm_control, 'if host_of(screen) not in run["hosts"]:', "if False:", "arm-control: a screen outside the app is refused"),
    ("sweep: every owner alive", case_sweep, "return start is not None and start == w.get(\"owner_start\")", "return True",
     "sweep: took down the one without an owner"),
    ("capacity unavailable is 0", case_capacity_missing, '"allowed": 1, "note"', '"allowed": 0, "note"', "capacity unavailable: armed with a quota of 1"),
]


def guarded(case, R, S):
    """A case that raises is a FAIL of its own (a crash must not hide the cases after it)."""
    try:
        case(R, S)
    except Exception as e:  # noqa: BLE001
        S.ok("%s: raised" % case.__name__, False, "%s: %s" % (type(e).__name__, e))


if __name__ == "__main__":
    CWD[0] = helpers.mkdtemp("fwx-walk-cwd-")
    FAKE_DIR_FOR[0] = helpers.mkdtemp("fwx-walk-bin-")
    for name, target in (("python3", PY), ("git", GIT)):
        os.symlink(target, os.path.join(FAKE_DIR_FOR[0], name))
    real = runner(ROOT)
    for case in CASES:
        guarded(case, real, s)
    for name, case, old, new, needle in MUTANTS:
        m = helpers.Suite()
        try:
            tree = copy_tree(ROOT, (W, old, new))
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        guarded(case, runner(tree), m)
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
        helpers.remove(tree)
    s.done()
