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
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import unquote, urlsplit

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
# The commands the pinned agent-browser knows: the top-level words of `agent-browser --help` of AB_VERSION (the Core, Navigation, Get Info,
# Check State, Find, Mouse, Browser Settings (`set`), Network, Storage, Tabs, Diff, Debug, Streaming, WebMCP, React, Performance, A11y, SPA, Init
# scripts, Batch, Auth, Plugins, Confirmation, Sessions, MCP, Chat, Dashboard, Setup and `skills` sections), and the settings of `set`. The fake
# agent-browser of this file and of test_screenshot.py refuses any other command with the real tool's line and exit code (`Unknown command: viewport`,
# exit 1: measured on 0.41.1), so a step the real tool would reject cannot pass here. Update it with the version: `agent-browser --help`.
AB_VERSION = "0.41.1"
AB_COMMANDS = ("open read click dblclick type fill press keyboard hover focus check uncheck select drag upload download scroll scrollintoview wait screenshot pdf "
               "snapshot eval connect close back forward reload get is find mouse set network cookies storage tab diff trace profiler record console errors "
               "highlight inspect clipboard stream webmcp react vitals a11y pushstate removeinitscript batch auth plugin confirm deny session mcp chat "
               "dashboard install upgrade doctor profiles skills "
               # accepted by 0.41.1 though `--help` does not print them (probed by running each with no argument: `Missing arguments for: goto`,
               # `✓ Browser closed`, never `Unknown command`); `walk.py` names goto, navigate and state in its own guards
               "goto navigate quit exit state frame dialog window").split()
# `agent-browser set --help` lists viewport, device, geo, offline, headers, credentials and media; `agent-browser set bogus` answers
# `Valid options: viewport, device, geo, geolocation, offline, headers, credentials, auth, media` (geolocation and auth are aliases)
AB_SET = "viewport device geo geolocation offline headers credentials auth media".split()
AB_GUARD = '''
_COMMANDS, _SET = %r, %r
_VALUED = ("--namespace", "--session", "--idle-timeout", "--screenshot-dir", "--args", "--allowed-domains", "--init-script", "--executable-path", "--state")
_a, _i = sys.argv[1:], 0
while _i < len(_a) and _a[_i].startswith("-"):
    _i += 2 if _a[_i] in _VALUED else 1
if _a[_i:_i + 1] and (_a[_i] not in _COMMANDS or (_a[_i] == "set" and _a[_i + 1:_i + 2] and _a[_i + 1] not in _SET)):
    sys.stderr.write("Unknown command: %%s\\n" %% _a[_i])
    sys.exit(1)
''' % (AB_COMMANDS, AB_SET)
TAILS = {
    "agent-browser": AB_GUARD + """
# `get url` answers FAKE_PAGE_URL (the page the session is on); a `screenshot` with no path writes FAKE_SHOT_PATH and prints a line that names
# it (the real tool's names the path after `Screenshot saved to`), when the case sets them.
if _a[_i:_i + 2] == ["get", "url"]:
    sys.stdout.write(os.environ.get("FAKE_PAGE_URL", "") + "\\n")
    sys.exit(0)
if _a[_i:] == ["screenshot"] and os.environ.get("FAKE_SHOT_PATH"):
    open(os.environ["FAKE_SHOT_PATH"], "wb").write(b"PNG")
    sys.stdout.write("Screenshot saved to " + os.environ["FAKE_SHOT_PATH"] + "\\n")
    sys.exit(0)
# The read-back of arm-control asks the page for the target's style and rendered box with a call of the browser's eval command whose code
# carries the word fwx: and answers with the line that code builds, `fwx:<font-size>|<font-weight>|<width>x<height>` (a string result comes
# back quoted: measured live). FAKE_READ says what the page holds, as (without the plant, with it):
#   changes (the default): 24px/700 in 300x40, then 16px/400 in 300x30      same: 16px/400 in 300x30 both times (the title already has the
#   planted style)      weight: 16px/500, then 16px/400, the box 300x30 both times (a style that changes nothing a reader can see)
#   grow10: the box goes from 300x30 to 310x30     missing: no title
# FAKE_QUOTE=1 wraps the line in quotes (the shape of a string result is not measured; the parser takes both).
# The plant is on from the moment the session was launched with --init-script, or the plant's code was run on the page by eval, until a
# `close`; FAKE_INIT=ignore is a browser that drops the --init-script (the launch path the walkers use does not plant: the F-3 defect).
planted = os.environ["FAKE_LOG"] + ".planted"
if "--init-script" in sys.argv and os.environ.get("FAKE_INIT") != "ignore":
    open(planted, "w").write("1")
if "eval" in sys.argv and "MutationObserver" in sys.argv[-1]:
    open(planted, "w").write("1")
if _a[_i:_i + 1] == ["close"] and os.path.exists(planted):
    os.remove(planted)
if "eval" in sys.argv and "fwx:" in sys.argv[-1]:
    mode = os.environ.get("FAKE_READ", "changes")
    reads = {"changes": ("fwx:24px|700|300x40", "fwx:16px|400|300x30"), "same": ("fwx:16px|400|300x30",) * 2,
             "weight": ("fwx:16px|500|300x30", "fwx:16px|400|300x30"), "grow10": ("fwx:16px|400|300x30", "fwx:16px|400|310x30")}
    line = "fwx:missing" if mode == "missing" else reads[mode][1 if os.path.exists(planted) else 0]
    print('"%s"' % line if os.environ.get("FAKE_QUOTE") else line)
sys.exit(int(os.environ.get("FAKE_RC", "0")))
""",
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
        for f in (self.log, self.log + ".planted"):
            if os.path.exists(f):
                os.remove(f)

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


NS = """#!%(py)s
import os, sys
mode = os.environ["FAKE_NS"]
with open(os.path.join(os.environ["FAKE_NS_DIR"], "calls"), "a") as f:
    f.write(" ".join(sys.argv[1:5] + sys.argv[-1:]) + "\\n")
print("200" if mode == "always" or (mode == "after" and os.path.exists("up-ran")) else "error: refused")
"""


def case_run_prefix(R, S):
    """An app brought up through a `run` prefix lives where the prefix says (a private network), so `up` asks from there, never from
    the host. `fakens run --` stands for the prefix: it answers the probe from FAKE_NS (none: nothing answers there, always: the app is
    there, after: the app answers once `up` has run). Seen red on the code that asked from the host (FWX_WALK_WAIT_S=6 keeps the wait short):
      FAIL: run prefix: a host server the prefix cannot see: up armed: rc 2: fwx walk up: http://127.0.0.1:N is already answering before up: another app (or a run that was not closed) is there
      FAIL: run prefix: the app answers inside the prefix only after up: up armed: rc 1: fwx walk up: nothing answered at http://127.0.0.1:N within 6 s after up
      FAIL: run prefix: an app already answering inside the prefix: exit: got 1, want 2   (the host saw nothing, so the guard never bit)"""
    def scene(mode):
        sc = Scene(prefix="fakens run --")
        script(os.path.join(sc.bin, "fakens"), NS % {"py": PY})
        sc.env.update(FAKE_NS=mode, FAKE_NS_DIR=sc.state, FWX_WALK_WAIT_S="6")
        return sc
    nothing_up = "python3 -c \"open('up-ran', 'w').close()\""
    # a host server on the app's port that the prefix cannot see: not the app, so up arms (the pre-up check asks inside the prefix)
    sc = scene("none")
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
        app = json.dumps({"up": "python3 up.py %d %s" % (sc.port, sc.pidfile), "run": "fakens run --", "down": "true", "url": sc.url})
        # nothing answers inside the prefix, and up leaves nothing that answers there: the post-up wait must time out, not take the host server
        r, o = sc.up(R, "--app", app)
        S.ok("run prefix: a host server the prefix cannot see: up ran", os.path.exists(os.path.join(sc.repo, "up-ran")), "rc %d: %s" % (r.returncode, r.stderr))
        S.ok("run prefix: a host server is not the app: the wait asks inside the prefix too (exit 1, nothing answered)",
             r.returncode == 1 and "nothing answered at %s" % sc.url in r.stderr, "rc %d: %s" % (r.returncode, r.stderr))
    finally:
        srv.terminate()
        srv.wait()
        sc.stop()
    sc = scene("after")
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
        app = json.dumps({"up": nothing_up, "run": "fakens run --", "down": "true", "url": sc.url})
        r, o = sc.up(R, "--app", app)
        S.ok("run prefix: a host server the prefix cannot see: up armed", r.returncode == 0 and o and o.get("armed") is True,
             "rc %d: %s %s" % (r.returncode, r.stdout, r.stderr))
        got = open(os.path.join(sc.state, "calls")).read().splitlines() if os.path.exists(os.path.join(sc.state, "calls")) else []
        S.ok("run prefix: the probe went through the prefix, asking for the app's url, before and after up",
             [ln.split()[-1] for ln in got] == [sc.url] * 2 and all(ln.startswith("run -- python3 -c ") for ln in got), str(got)[:300])
        if o and o.get("run_dir"):
            sc.walk(R, "down", "--run", o["run_dir"])
    finally:
        srv.terminate()
        srv.wait()
        sc.stop()
    # the host port is free and the app answers inside the prefix only after up: up waits and arms
    sc = scene("after")
    try:
        app = json.dumps({"up": nothing_up, "run": "fakens run --", "down": "true", "url": sc.url})
        r, o = sc.up(R, "--app", app)
        S.ok("run prefix: the app answers inside the prefix only after up: up armed", r.returncode == 0 and o and o.get("armed") is True,
             "rc %d: %s %s" % (r.returncode, r.stdout, r.stderr))
        if o and o.get("run_dir"):
            sc.walk(R, "down", "--run", o["run_dir"])
    finally:
        sc.stop()
    # the guard still bites: something already answers inside the prefix's network
    sc = scene("always")
    try:
        app = json.dumps({"up": nothing_up, "run": "fakens run --", "down": "true", "url": sc.url})
        r, o = sc.up(R, "--app", app)
        S.eq("run prefix: an app already answering inside the prefix: exit", r.returncode, 2)
        S.ok("run prefix: an app already answering inside the prefix: says so", "already answering before up" in r.stderr and sc.url in r.stderr, r.stderr)
        S.ok("run prefix: an app already answering inside the prefix: up was not run", not os.path.exists(os.path.join(sc.repo, "up-ran")))
    finally:
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
        # arm-control read the page in session w1 and closed it (case_arm_control_readback checks that); this case is about `ab`'s own session
        # handling, so it starts from no session even under the mutant that keeps one after `close`
        mark = os.path.join(rd, "sessions", "ab-w1")
        if os.path.exists(mark):
            os.remove(mark)
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
        S.ok("ab session: a walker session (w2) launches with the planted control", any("--init-script" in c["argv"] for c in sc.calls()), str(sc.calls()))
        # only the walkers carry the plant: a verifier (v1) launches without the init script, with the planted control armed all the same.
        # Seen red on the branch before it: FAIL: ab session: a verifier session (v1) launches without the planted control: [['run', '--', 'agent-browser', '--namespace'], ...
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "v1", "open", sc.url + "/board")
        S.eq("ab session: a verifier session: exit", r.returncode, 0)
        S.ok("ab session: a verifier session (v1) launches without the planted control",
             len(sc.calls()) > 1 and not any("--init-script" in c["argv"] for c in sc.calls()), str([c["argv"][:4] for c in sc.calls()]))
        # `close` of a session no agent opened (no mark): nothing to close, so no browser is launched just to close it, and it is not a failure.
        # Seen red on the branch before it: FAIL: ab session: close of a session never opened: no browser call: got ['fakerig', 'agent-browser', 'agent-browser', 'agent-browser'], want []
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w9", "close")
        S.eq("ab session: close of a session never opened: exit", r.returncode, 0)
        S.eq("ab session: close of a session never opened: no browser call", [c["prog"] for c in sc.calls()], [])
        S.ok("ab session: and it leaves no session mark", not os.path.exists(os.path.join(rd, "sessions", "ab-w9")))
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w9", "close", "--all")
        S.ok("ab session: close --all is not a no-op (it reaches the other sessions of the run)",
             r.returncode == 0 and any(c["argv"][-2:] == ["close", "--all"] for c in sc.calls()), "rc %d %s" % (r.returncode, [c["argv"][-2:] for c in sc.calls()]))
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
                     ["type", "@e1", "stream"], ["eval", "1+1"], ["record", "start", os.path.join(rd, "c.webm")], ["read"],
                     # words the real 0.41.1 accepts though its `--help` does not print them (the fake takes them too, so a test of the guards on
                     # them is possible; red before: `Unknown command: goto` from the fake):
                     ["goto", sc.url], ["navigate", sc.url], ["quit"], ["set", "geolocation", "1", "2"]):
            sc.clear()
            r = sc.walk(R, "ab", "--run", rd, "w1", *args)
            S.ok("ab commands: %s: still accepted" % " ".join(args), r.returncode == 0 and sc.calls("agent-browser")
                 and sc.calls("agent-browser")[-1]["argv"][-len(args):] == list(args), "rc %d: %s" % (r.returncode, r.stderr))
        # A verifier session's `close` in a run with one app: no browser was opened, so it is a no-op with exit 0 (the workflow counts it as a
        # confirmed close and keeps the slot free). The container run with several apps refuses `v<k>` (see case_container; the session-to-app
        # assignment is a unit of its own), but this run is not affected.
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "v1", "close")
        S.ok("ab commands: a verifier session's close in a run with one app is a no-op, exit 0", r.returncode == 0 and sc.calls() == [], "rc %d: %s %s" % (r.returncode, r.stderr, sc.calls()))
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
        # (the real tool has no top-level `viewport`, the fake refuses it with exit 1: these two checks use `set viewport` and want exit 0, as the
        # review of PR 125 asked; before, they passed on calls the fake had rejected)
        r = sc.walk(R, "ab", "--run", rd, "w1", "set", "viewport", "1440", "900")
        S.eq("ab viewport: an explicit viewport is accepted", r.returncode, 0)
        S.eq("ab viewport: an explicit viewport is passed through untouched", [c["argv"][-4:] for c in sc.calls("agent-browser")],
             [["set", "viewport", "1440", "900"]])
        # a session whose first call is the caller's own viewport keeps only that one
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w2", "set", "viewport", "1440", "900")
        S.eq("ab viewport: a first call that is a viewport is accepted", r.returncode, 0)
        S.eq("ab viewport: a first call that is a viewport is not preceded by ours", sized(sc.calls("agent-browser")), [["set", "viewport", "1440", "900"]])
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


BOUNDARY_URLS = ["http://localhost:3000/", "http://127.0.0.1:3000/x", "http://other.localhost:3000/", "http://sub.other.localhost/", "http://198.51.100.7:3000/",
                 "http://[::1]:3000/", "http://a.example.test/", "http://localhost.example.test/"]
NODE = shutil.which("node")


def pac_table(cfg, urls):
    """({url: True when the config's proxy-autoconfig script lets Firefox reach it directly}, why): the script run by node, with the host as
    Firefox passes it (no brackets round an IPv6 literal). (None, why) when the config has no such script, (None, "node") with no node."""
    prefs = cfg.get("browser", {}).get("launchOptions", {}).get("firefoxUserPrefs") or {}
    src = prefs.get("network.proxy.autoconfig_url") or ""
    if prefs.get("network.proxy.type") != 2 or not src.startswith("data:text/javascript,"):
        return None, "got no PAC: %r" % prefs
    if not NODE:
        return None, "node"
    js = unquote(src[len("data:text/javascript,"):]) + (
        "\nfor (const u of JSON.parse(process.argv[1])) console.log(JSON.stringify([u, FindProxyForURL(u, new URL(u).hostname.replace(/^\\[|\\]$/g, ''))]))")
    r = subprocess.run([NODE, "-e", js, json.dumps(urls)], capture_output=True, text=True, timeout=30)
    if r.returncode:
        return None, "the script did not run: %s" % r.stderr[-200:]
    got = {u: v for u, v in (json.loads(line) for line in r.stdout.splitlines() if line.strip())}
    return {u: v == "DIRECT" for u, v in got.items()}, ""


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
        # The Firefox context starts logged in like `ab` does: the app's own storageState (the file its `up` left) is the context's. Seen red
        # on the base (the context had the viewport only, so a Firefox walker met the login screen):
        #   FAIL: pw: the config is Firefox, headless, 1309x818 at 1.1, with the demo session: got (..., {'viewport': {...}, 'deviceScaleFactor': 1.1}), want (..., {..., 'storageState': '<run>/demo-state.json'})
        S.eq("pw: the config is Firefox, headless, 1309x818 at 1.1, with the demo session", (
            cfg.get("browser", {}).get("browserName"), cfg.get("browser", {}).get("launchOptions", {}).get("headless"),
            cfg.get("browser", {}).get("contextOptions")),
             ("firefox", True, {"viewport": {"width": 1309, "height": 818}, "deviceScaleFactor": 1.1, "storageState": os.path.join(rd, "demo-state.json")}))
        # Firefox has no counterpart of `ab`'s --allowed-domains (Playwright's origin filter is no boundary and blind to redirects), so the
        # config carries a proxy-autoconfig script (a `data:` URL, Firefox's own `network.proxy.autoconfig_url`) that lets the app's hosts
        # through (exact host names, as `--allowed-domains` does) and sends every other host to a proxy nothing listens on: a link or a
        # redirect out of the app is refused by the browser. Measured live on toy pages (Playwright Firefox 158 through @playwright/cli
        # 0.1.23): with no rule a 302 to another host was followed and that server answered; with a static proxy and `bypass=localhost` a
        # redirect to `other.localhost` was still followed (the bypass matches the suffix); with the script it is refused
        # (`NS_ERROR_PROXY_CONNECTION_REFUSED`), as are another loopback address and every other name, while the app's own hosts load.
        # Seen red on the base (PR 103 review threads, "Enforce the local-app boundary for Firefox" and the review of PR 125; no rule, then a
        # static proxy that let `*.localhost` through):
        #   FAIL: pw: the config carries a proxy-autoconfig script for the app's hosts: got no PAC: {}
        hosts = (jfile(os.path.join(rd, "run.json")) or {}).get("hosts")
        S.ok("pw: the run has the app's hosts to let through", bool(hosts) and "127.0.0.1" in hosts, repr(hosts))
        # the same table of URLs through both browsers' guards: `ab` by `fwx walk ab open` (its arg guard, and --allowed-domains = the hosts)
        # and `pw` by the script the config carries, run by node; they must agree on every URL
        ab_allowed = {}
        for u in BOUNDARY_URLS:
            sc.clear()
            ab_allowed[u] = sc.walk(R, "ab", "--run", rd, "w1", "open", u).returncode == 0
        S.ok("pw/ab boundary: the table has urls of both kinds", True in ab_allowed.values() and False in ab_allowed.values(), repr(ab_allowed))
        S.eq("pw/ab boundary: `ab` lets through only the app's hosts, exact", {u for u, ok in ab_allowed.items() if ok},
             {u for u in BOUNDARY_URLS if urlsplit(u).hostname in (hosts or [])})
        pw_allowed, why = pac_table(cfg, BOUNDARY_URLS)
        if why == "node":
            print("NOT RUN, NOT ARMED: node is not on the PATH: the Firefox boundary table was not checked")
        else:
            S.ok("pw: the config carries a proxy-autoconfig script for the app's hosts", pw_allowed is not None, why)
            S.eq("pw/ab boundary: Firefox and Chromium refuse the same urls (the sink for the rest)", pw_allowed, ab_allowed)
        first_cfg = argv[-1]
        # an app that left no session file (the state is only a path until `up` writes it): no storageState, the launch still works
        os.remove(os.path.join(rd, "demo-state.json"))
        sc.clear()
        S.eq("pw: no session file: open exit", sc.walk(R, "pw", "--run", rd, "w2", "open", sc.url).returncode, 0)
        # Two sessions opened one after the other each name their own config file: with one shared `pw.config.json` a container run's second
        # open could overwrite the first's before the CLI read it, and the first browser would load the second app's demo session.
        # Seen red on the base (PR 103 review thread, "Use a separate Playwright configuration file for each session"):
        #   FAIL: pw: a second session's config is its own file and leaves the first's alone: got (False, False), want (True, True)
        second_cfg = sc.calls("npx")[-1]["argv"][-1]
        S.eq("pw: a second session's config is its own file and leaves the first's alone", (
            first_cfg != second_cfg, "storageState" in (((jfile(first_cfg) or {}).get("browser") or {}).get("contextOptions") or {})), (True, True))
        # the boundary is the run's, not a walker's: a verifier's Firefox session (`v*`) is held to it too (a mutant that set it only for `w*`
        # sessions passed every check of the first version of this case)
        sc.clear()
        S.eq("pw: a verifier's session opens", sc.walk(R, "pw", "--run", rd, "v1", "open", sc.url).returncode, 0)
        vcfg = jfile(sc.calls("npx")[-1]["argv"][-1]) or {}
        S.ok("pw: a verifier's session (v1) has the same boundary as a walker's", vcfg.get("browser", {}).get("launchOptions", {}).get("firefoxUserPrefs") ==
             cfg.get("browser", {}).get("launchOptions", {}).get("firefoxUserPrefs") and bool(vcfg.get("browser", {}).get("launchOptions", {}).get("firefoxUserPrefs")), repr(vcfg))
        S.ok("pw: no session file: the context has no storageState (Playwright would refuse a missing file)",
             "storageState" not in ((jfile(sc.calls("npx")[-1]["argv"][-1]) or {}).get("browser", {}).get("contextOptions") or {}), str(sc.calls("npx")[-1]["argv"]))
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


def case_hygiene(R, S):
    """3.5 acceptance, second pass, D8 and D9: what a walk leaves behind, and where its captures go. A toy HOME (Scene.home) holds
    agent-browser's namespaces folder, so nothing reads the real one.
    Red before the change (python3 tests/test_walk.py, the code of f8a3082):
      FAIL: hygiene pw: the config's outputDir is the run's captures folder: got None, want '.../fwx/walks/<ns>/shots'
      FAIL: hygiene pw: a later call runs in the captures folder, not in the project: got '<repo>', want '<shots>'
      FAIL: hygiene capture path: ab screenshot /tmp/v1b.png: exit: got 0, want 2   (and the same for pw --filename and --filename=)
      FAIL: hygiene down: the target files of the namespace are gone: got ['a.target', 'b.target'], want []"""
    sc = Scene()
    try:
        o = armed(sc, R, S, "hygiene")
        if not o:
            return
        rd = o["run_dir"]
        run = jfile(os.path.join(rd, "run.json"))
        ns, shots = run["namespace"], run["shots"]
        # D9: Playwright's CLI keeps its files in the captures folder (outputDir), and runs there
        sc.clear()
        S.eq("hygiene pw: open exit", sc.walk(R, "pw", "--run", rd, "w1", "open", sc.url).returncode, 0)
        argv = sc.calls("npx")[-1]["argv"]
        S.eq("hygiene pw: the config's outputDir is the run's captures folder", (jfile(argv[-1]) or {}).get("outputDir"), shots)
        sc.clear()
        sc.walk(R, "pw", "--run", rd, "w1", "snapshot")
        S.eq("hygiene pw: a later call runs in the captures folder, not in the project", os.path.realpath(sc.calls("npx")[-1]["cwd"]), os.path.realpath(shots))
        # D8: no capture goes to a temp folder
        for label, tool, args in (("ab screenshot /tmp/v1b.png", "ab", ["screenshot", "/tmp/v1b.png"]),
                                  ("ab screenshot @e1 /tmp/v1b.png", "ab", ["screenshot", "@e1", "/tmp/v1b.png"]),
                                  ("ab screenshot /dev/shm/v.png", "ab", ["screenshot", "/dev/shm/v.png"]),
                                  ("pw screenshot --filename /tmp/v1b.png", "pw", ["screenshot", "--filename", "/tmp/v1b.png"]),
                                  ("pw screenshot --filename=/tmp/v1b.png", "pw", ["screenshot", "--filename=/tmp/v1b.png"])):
            sc.clear()
            r = sc.walk(R, tool, "--run", rd, "w1", *args)
            S.ok("hygiene capture path: %s: exit 2, nothing run, says where the capture goes" % label,
                 r.returncode == 2 and sc.calls() == [] and "temp folder" in r.stderr and shots in r.stderr, "rc %d %s calls %s" % (r.returncode, r.stderr, sc.calls()))
        for label, tool, args in (("ab screenshot (no path)", "ab", ["screenshot"]),
                                  ("ab screenshot @e1 in the captures folder", "ab", ["screenshot", "@e1", os.path.join(shots, "a.png")]),
                                  ("ab screenshot in the walker's scratch folder", "ab", ["screenshot", os.path.join(rd, "w1-scratch", "a.png")]),
                                  ("ab screenshot a path outside any temp folder", "ab", ["screenshot", "/srv/profile/a.png"]),  # not the toy repo: it is itself under /tmp
                                  ("ab fill with a /tmp word (typed text, not a path)", "ab", ["fill", "@e1", "/tmp/v1b.png"]),
                                  ("pw screenshot (no filename)", "pw", ["screenshot"]),
                                  ("pw screenshot --filename in the captures folder", "pw", ["screenshot", "--filename", os.path.join(shots, "a.png")]),
                                  ("pw screenshot --filename relative", "pw", ["screenshot", "--filename", "a.png"])):
            sc.clear()
            r = sc.walk(R, tool, "--run", rd, "w1", *args)
            S.ok("hygiene capture path: %s: runs" % label, r.returncode == 0 and len(sc.calls()) >= 1, "rc %d %s" % (r.returncode, r.stderr))
        # D9: down removes the *.target files of this namespace only
        base = os.path.join(sc.home, ".agent-browser", "namespaces")
        mine, other = os.path.join(base, ns, "run"), os.path.join(base, "another-walk", "run")
        for d, names in ((mine, ("a.target", "b.target")), (other, ("c.target",))):
            os.makedirs(d)
            for n in names:
                open(os.path.join(d, n), "w").close()
        r = sc.walk(R, "down", "--run", rd)
        S.eq("hygiene down: exit", r.returncode, 0)
        S.eq("hygiene down: the target files of the namespace are gone", sorted(os.listdir(mine)) if os.path.isdir(mine) else [], [])
        S.eq("hygiene down: another walk's target file stays", os.listdir(other), ["c.target"])
        steps = (jfile(os.path.join(rd, "down.json")) or {}).get("steps", [])
        S.eq("hygiene down: down.json says how many it removed", [x.get("removed") for x in steps if "target" in x.get("step", "")], [2])
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


def case_arm_control_readback(R, S):
    """D14: the control is proved visible on the screen it is armed on, or the arming fails. Seen red on the branch before the read-back
    (arm-control wrote control.json without opening the page; the lines below are that run, FAKE_READ naming what the page holds):
      FAIL: arm-control read-back: control.json records both readings: got [None, None], want [{'font-size': '24px', 'font-weight': '700'}, {'font-size': '16px', 'font-weight': '400'}]
      FAIL: arm-control read-back: reads, plants (the init script's code), reads again: []
      FAIL: arm-control read-back: the probe session is closed last (the walkers launch their own): got [], want ['close']
      FAIL: arm-control read-back: the title already has the planted style: exit: got 0, want 1
      FAIL: arm-control read-back: the title already has the planted style: says no visible change, and where: rc 0:
      FAIL: arm-control read-back: a failed arming leaves no control.json (an old plant is not kept)
      FAIL: arm-control read-back: no title on the screen: exit: got 0, want 1
      FAIL: arm-control read-back: no title on the screen: says target not found, and where: rc 0:
    (a) is the positive control of (b) and (c): the same call, the same fake, only what the page holds differs."""
    def scene(read, quote=False):
        sc = Scene()
        sc.env.update(FAKE_READ=read, FWX_WALK_CONTROL_WAIT_S="1")
        if quote:
            sc.env["FAKE_QUOTE"] = "1"
        return sc
    screen = "/board"
    # (a) the target is there and the plant changes its computed style: armed, both readings recorded, the browser left closed
    sc = scene("changes")
    try:
        o = armed(sc, R, S, "arm-control read-back")
        if not o:
            return
        rd = o["run_dir"]
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + screen)
        S.eq("arm-control read-back: the plant changes the style: exit", r.returncode, 0)
        c = jfile(os.path.join(rd, "control.json")) or {}
        rb = c.get("readback") or {}
        S.eq("arm-control read-back: control.json records both readings", [rb.get("before"), rb.get("after")],
             [{"font-size": "24px", "font-weight": "700"}, {"font-size": "16px", "font-weight": "400"}])
        S.ok("arm-control read-back: and the selector they were read from", "h1" in str(rb.get("selector")), str(rb))
        S.eq("arm-control read-back: the boxes are recorded beside the styles", rb.get("box"),
             {"before": {"width": 300, "height": 40}, "after": {"width": 300, "height": 30}})
        calls = [x["argv"] for x in sc.calls("agent-browser")]
        reads = [i for i, a in enumerate(calls) if "eval" in a and "fwx:" in a[-1]]
        inits = [i for i, a in enumerate(calls) if "--init-script" in a]
        # F-3 (the plant went to the page by an eval of its code, not by the launch the walkers' sessions use). Seen red on the base:
        #   FAIL: arm-control read-back: reads without the plant, then in a session launched with the plant (the walkers' launch path): reads [2, 4], launches with --init-script []
        S.ok("arm-control read-back: reads without the plant, then in a session launched with the plant (the walkers' launch path)",
             len(reads) == 2 and len(inits) == 1 and reads[0] < inits[0] < reads[1], "reads %r, launches with --init-script %r" % (reads, inits))
        S.ok("arm-control read-back: the code is never run on the page by hand",
             not any("eval" in a and "MutationObserver" in a[-1] for a in calls), repr([a[-1][:40] for a in calls if "eval" in a]))
        ctl_script = c.get("script") or ""
        S.ok("arm-control read-back: the launch carries the init script control.json names, which holds the plant",
             len(inits) == 1 and ctl_script in calls[inits[0]] and "MutationObserver" in open(ctl_script, encoding="utf-8").read(), repr(calls[inits[0]][:6] if inits else None))
        S.eq("arm-control read-back: the probe session is closed last (the walkers launch their own)", [a[-1] for a in calls][-1:], ["close"])
        S.ok("arm-control read-back: and no session mark is left", not os.path.exists(os.path.join(rd, "sessions", "ab-w1")))
        # (b) the title already has the planted style: nothing a walker could see; refuses, and the earlier control.json does not survive
        sc.env["FAKE_READ"] = "same"
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + screen)
        S.eq("arm-control read-back: the title already has the planted style: exit", r.returncode, 1)
        S.ok("arm-control read-back: the title already has the planted style: says no visible change, and where",
             "no visible change" in r.stderr and sc.url + screen in r.stderr, "rc %d: %s" % (r.returncode, r.stderr))
        S.eq("arm-control read-back: the title already has the planted style: one line", len(r.stderr.strip().splitlines()), 1)
        out = obj(r.stdout) or {}
        S.ok("arm-control read-back: and the same reason on stdout as {armed: false} (the workflow's runner hands back stdout only)",
             out.get("armed") is False and "no visible change" in str(out.get("reason")), r.stdout)
        S.ok("arm-control read-back: a failed arming leaves no control.json (an old plant is not kept)", not os.path.exists(os.path.join(rd, "control.json")))
        # (c) no title on the screen
        sc.env["FAKE_READ"] = "missing"
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + screen)
        S.eq("arm-control read-back: no title on the screen: exit", r.returncode, 1)
        S.ok("arm-control read-back: no title on the screen: says target not found, and where",
             "target not found" in r.stderr and sc.url + screen in r.stderr, "rc %d: %s" % (r.returncode, r.stderr))
        S.ok("arm-control read-back: no title on the screen: nothing written", not os.path.exists(os.path.join(rd, "control.json")))
        # (d) the layout is what counts: a plant that changes the style and leaves the title's box as it was (a weight 500 title already at the
        # body's size) is refused, with both boxes in the reason. Seen red on the branch before it (the read-back compared styles):
        #   FAIL: arm-control read-back: a weight-only change that leaves the box as it was: exit: got 0, want 1
        #   FAIL: arm-control read-back: a box that grew 10 px arms it (the default is 1 px): exit: got 1, want 0   (same style, wider box)
        #   FAIL: arm-control read-back: a 10 px change with FWX_WALK_CONTROL_MIN_BOX_PX=10: armed: got 1, want 0
        #   FAIL: arm-control read-back: the boxes are recorded beside the styles: got None, want {'before': {'width': 300, 'height': 40}, 'after': {'width': 300, 'height': 30}}
        sc.env["FAKE_READ"] = "weight"
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + screen)
        S.eq("arm-control read-back: a weight-only change that leaves the box as it was: exit", r.returncode, 1)
        S.ok("arm-control read-back: and the reason says no visible change, where, and both boxes",
             "no visible change" in r.stderr and sc.url + screen in r.stderr and r.stderr.count("300x30") == 2 and len(r.stderr.strip().splitlines()) == 1, r.stderr)
        S.ok("arm-control read-back: and nothing is written", not os.path.exists(os.path.join(rd, "control.json")))
        # (e) a box that changes by the constant (default 1 px, so any change) arms it, both boxes recorded
        sc.env["FAKE_READ"] = "grow10"
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + screen)
        S.eq("arm-control read-back: a box that grew 10 px arms it (the default is 1 px): exit", r.returncode, 0)
        rb = (jfile(os.path.join(rd, "control.json")) or {}).get("readback") or {}
        S.eq("arm-control read-back: the boxes are recorded beside the styles", rb.get("box"),
             {"before": {"width": 300, "height": 30}, "after": {"width": 310, "height": 30}})
        S.eq("arm-control read-back: and the number the change was measured against", rb.get("min_box_px"), 1)
        # (f) the number is one constant read from the environment: 50 refuses the same 10 px, 10 still arms it (at least, not more than)
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + screen, env={"FWX_WALK_CONTROL_MIN_BOX_PX": "50"})
        S.eq("arm-control read-back: a 10 px change with FWX_WALK_CONTROL_MIN_BOX_PX=50: exit", r.returncode, 1)
        S.ok("arm-control read-back: and the reason names the number and both boxes",
             "no visible change" in r.stderr and "50" in r.stderr and "300x30" in r.stderr and "310x30" in r.stderr, r.stderr)
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + screen, env={"FWX_WALK_CONTROL_MIN_BOX_PX": "10"})
        S.eq("arm-control read-back: a 10 px change with FWX_WALK_CONTROL_MIN_BOX_PX=10: armed", r.returncode, 0)
        S.eq("arm-control read-back: and the number recorded is the one in force", ((jfile(os.path.join(rd, "control.json")) or {}).get("readback") or {}).get("min_box_px"), 10)
        # a string result may come back quoted
        sc.env.update(FAKE_READ="changes", FAKE_QUOTE="1")
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + screen)
        S.eq("arm-control read-back: a quoted answer is read too: exit", r.returncode, 0)
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
        # What a container run with fewer apps than the workflow's sessions does today (the ui-walk workflow names sessions `w1`..`w5` and `v1`..):
        # a verifier session has no app either, so its every call, `close` included, exits 2. A run with one app (container false) takes any
        # session name: `ab session` and `pw` above use w2, w3 and v1 on it. The session-to-app assignment is its own unit; this pins both sides.
        r = sc.walk(R, "ab", "--run", rd, "v1", "close")
        S.ok("container: a verifier session has no app either, `close` included (known, left: the workflow's v<k> sessions need slot numbers)",
             r.returncode == 2 and "v1" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
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


def case_capacity_resize(R, S):
    """`walk capacity --run R --tramos N` asks `fwx capacity` again for the tramos the workflow only learns after `up` (3.5 U3d: `up` is
    called without --tramos, so its quota was sized for one tramo whatever the walk). It rewrites `capacity` in run.json.

    Red before the subcommand existed (python3 tests/test_walk.py):
      FAIL: capacity resize: three tramos: exit and JSON: rc 2  usage: fwx walk <up|ab|pw|arm-control|findings|review-page|...> ...
      FAIL: capacity resize: three tramos: asked for 6, so a quota that can pass 2: got (None, False), want (6, True)
      FAIL: capacity resize: run.json carries the new answer: got 2, want 6
    """
    sc = Scene()
    try:
        o = armed(sc, R, S, "capacity resize")
        if not o:
            return
        rd = o["run_dir"]
        S.eq("capacity resize: `up` without --tramos asked for 2", (o.get("capacity") or {}).get("want"), 2)
        r = sc.walk(R, "capacity", "--run", rd, "--tramos", "3")
        c = obj(r.stdout)
        S.ok("capacity resize: three tramos: exit and JSON", r.returncode == 0 and c is not None and c.get("role") == "ui-walker", "rc %d %s %s" % (r.returncode, r.stdout, r.stderr))
        S.eq("capacity resize: three tramos: asked for 6, so a quota that can pass 2", ((c or {}).get("want"), ((c or {}).get("allowed") or 0) > 2), (6, True))
        S.eq("capacity resize: run.json carries the new answer", ((jfile(os.path.join(rd, "run.json")) or {}).get("capacity") or {}).get("want"), 6)
        for argv in (["capacity"], ["capacity", "--run", rd], ["capacity", "--run", rd, "--tramos", "0"], ["capacity", "--run", rd, "--tramos", "x"]):
            r = sc.walk(R, *argv)
            S.ok("capacity resize: walk %s: exit 2 and a usage line" % " ".join(argv[1:]), r.returncode == 2 and "usage: fwx walk capacity" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()
    sc = Scene(container=True, limits={"ui-walker": 4})
    try:
        app = {"up": "python3 up.py %d %s" % (sc.port, sc.pidfile), "run": "fakerig run --name {name} --", "down": "python3 down.py %s" % sc.pidfile,
               "url": sc.url + "/{name}", "container": True}
        r, o = sc.up(R, "--app", json.dumps(app))
        if not S.ok("capacity resize, container: up armed", r.returncode == 0 and o and o.get("armed") is True, "rc %d %s %s" % (r.returncode, r.stdout, r.stderr)):
            return
        n = len(o["apps"])
        r = sc.walk(R, "capacity", "--run", o["run_dir"], "--tramos", "5")
        c = obj(r.stdout)
        S.ok("capacity resize: container: the quota never passes the apps `up` started (%d)" % n, r.returncode == 0 and c is not None and n == 2 and c.get("allowed") == n,
             "rc %d %s %s" % (r.returncode, r.stdout, r.stderr))
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


def case_planted_captures(R, S):
    """A walker's `screenshot` taken on the control's route is a picture of the plant, whichever finding it is attached to later (review of
    PR 125: a finding filed under /billing can carry a picture of /settings). `fwx walk ab` notes the route at the moment of the capture:
    after a `screenshot` in a session that launched with the plant it asks the page for its url (`get url`) and lists the picture in
    `control-pictures.txt` when the route is the control's, or when the route cannot be read (a doubt is not a clean picture). The tool's own
    output goes through unchanged. Verifier sessions and runs with no control.json are not looked at. Seen red on the base:
      FAIL: planted captures: a walker's capture of the control's route is listed: got [], want ['<shots>/on-settings.png']"""
    sc = Scene()
    try:
        o = armed(sc, R, S, "planted captures")
        if not o:
            return
        rd = o["run_dir"]
        shots = jfile(os.path.join(rd, "run.json"))["shots"]
        listing = os.path.join(rd, "control-pictures.txt")

        def listed():
            return [ln for ln in open(listing, encoding="utf-8").read().splitlines() if ln] if os.path.exists(listing) else []

        def shoot(session, page, name, *path):
            pic = os.path.join(shots, name)
            return sc.walk(R, "ab", "--run", rd, session, "screenshot", *path, env={"FAKE_PAGE_URL": page, "FAKE_SHOT_PATH": pic}), pic
        r, _ = shoot("w1", sc.url + "/settings", "before-the-plant.png")
        S.eq("planted captures: no control.json, nothing is looked at", (r.returncode, listed(), [c["argv"][-2:] for c in sc.calls("agent-browser") if "url" in c["argv"]]), (0, [], []))
        sc.walk(R, "ab", "--run", rd, "w1", "close")
        helpers.write(rd, "init.js", "//")
        helpers.write(rd, "control.json", json.dumps({"screen": sc.url + "/settings", "path": "/settings", "script": os.path.join(rd, "init.js")}))
        sc.walk(R, "ab", "--run", rd, "w2", "close")
        r, pic = shoot("w2", sc.url + "/settings/", "on-settings.png")
        S.ok("planted captures: the tool's own output goes through", r.returncode == 0 and "Screenshot saved to " + pic in r.stdout, "rc %d %s" % (r.returncode, r.stdout))
        S.eq("planted captures: a walker's capture of the control's route is listed", listed(), [pic])
        r, _ = shoot("w2", sc.url + "/billing", "on-billing.png")
        S.eq("planted captures: a capture of another route is not", listed(), [pic])
        r, _ = shoot("v1", sc.url + "/settings", "verifier.png")
        S.eq("planted captures: a verifier's capture is not (its browser has no plant)", listed(), [pic])
        explicit = os.path.join(shots, "named.png")
        r, _ = shoot("w2", sc.url + "/settings?tab=2", "ignored.png", explicit)
        S.eq("planted captures: a capture with a path of the caller's is listed under that path", listed(), [pic, explicit])
        r, pic3 = shoot("w2", "", "unreadable.png")
        S.eq("planted captures: a page whose route cannot be read is listed (a doubt is not a clean picture)", listed(), [pic, explicit, pic3])
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


def case_findings_control_pictures(R, S):
    """The planted control is restyled by an init script that every walker's browser loads, so a walker's screenshot of the control screen
    shows the shrunken title. A genuine finding the walkers filed on that screen carries such screenshots as its `evidence`, which `findings`
    copies to fix.json (the fixer) and `review-page` shows the owner as the `today` figure. `findings` leaves the pictures of the control's
    screen out of `evidence` (listing them in `evidence_dropped`) and keeps every other row and every text. Seen red on the base:
      FAIL: control pictures: a finding on the control's screen keeps no walker picture: got ['/.../walker-1.png', 'the title is cut off'], want ['the title is cut off']
      FAIL: control pictures: the owner's page shows no `today` picture of the control's screen: got ['today'], want []"""
    rd = helpers.mkdtemp("fwx-walk-run-")
    os.makedirs(os.path.join(rd, "shots"))
    pics = {n: os.path.join(rd, "shots", "walker-%s.png" % n) for n in ("1", "2", "3", "4", "5", "6", "7")}
    vpic = os.path.join(rd, "shots", "verifier-5.png")  # a verifier's own capture: its browser never carried the plant
    for p in list(pics.values()) + [vpic]:
        with open(p, "wb") as fh:
            fh.write(PNG)

    def f(i, screen, evidence, **kw):
        return dict({"id": i, "file": "src/a.ts", "line": 3, "claim": "claim " + i, "evidence": evidence, "severity": "major", "screen": screen,
                     "verdict": "CONFIRMED", "expected": "x", "type": "layout", "kind": "observed"}, **kw)
    rows = [f("T1-1", "/settings", [pics["1"], "the title is cut off"]), f("T1-2", "http://127.0.0.1:3000/settings/?tab=a", pics["2"]),
            f("T1-3", "/billing", [pics["3"]]), f("T1-4", "/settings", {"before": pics["4"], "note": "the title is cut off", "all": [pics["4"], "x"]}),
            f("T1-5", "/settings", [pics["5"]], evidence_verifier=[vpic]),
            # a finding filed under another route that carries a picture `fwx walk ab` listed as taken on the control's route (review of PR 125)
            f("T1-6", "/billing", [pics["6"], "seen from the billing page"]),
            # object evidence on another screen: its text and its picture reach the review item
            f("T1-7", "/billing", {"before": pics["7"], "note": "seven"})]
    helpers.write(rd, "control-pictures.txt", pics["6"] + "\n")
    helpers.write(rd, "verified-T1.json", json.dumps({"findings": rows}))
    helpers.write(rd, "control.json", json.dumps({"screen": "http://127.0.0.1:3000/settings", "path": "/settings", "script": os.path.join(rd, "init.js")}))
    r = runner_walk(R, "findings", "--run", rd)
    S.eq("control pictures: exit", r.returncode, 0)
    fix = {x["id"]: x for x in jfile(os.path.join(rd, "fix.json")) or []}
    S.eq("control pictures: a finding on the control's screen keeps no walker picture", (fix.get("T1-1") or {}).get("evidence"), ["the title is cut off"])
    S.eq("control pictures: ...and says which it left out", (fix.get("T1-1") or {}).get("evidence_dropped"), [pics["1"]])
    S.eq("control pictures: the same screen as an absolute url with a trailing slash and a query, evidence a single path", (
        (fix.get("T1-2") or {}).get("evidence"), (fix.get("T1-2") or {}).get("evidence_dropped")), ([], [pics["2"]]))
    S.eq("control pictures: another screen keeps its evidence and has no list of dropped ones", (
        (fix.get("T1-3") or {}).get("evidence"), "evidence_dropped" in (fix.get("T1-3") or {})), ([pics["3"]], False))
    # Seen red on a11691f: FAIL: control pictures: a picture listed as taken on the control's route is left out wherever it is attached: got [...walker-6.png, 'seen from the billing page'], want ['seen from the billing page']
    S.eq("control pictures: a picture listed as taken on the control's route is left out wherever it is attached", (
        (fix.get("T1-6") or {}).get("evidence"), (fix.get("T1-6") or {}).get("evidence_dropped")), (["seen from the billing page"], [pics["6"]]))
    # evidence given as an object is filtered by the same rule (its picture values go, its text stays), and the verifier's own capture
    # (`evidence_verifier`, taken in a browser without the plant) is never dropped. Seen red on 1afad4d:
    #   FAIL: control pictures: evidence given as an object is filtered by the same rule: got ({'before': '.../walker-4.png', ...}, None), want ({'note': ..., 'all': ['x']}, [...])
    S.eq("control pictures: evidence given as an object is filtered by the same rule", ((fix.get("T1-4") or {}).get("evidence"), (fix.get("T1-4") or {}).get("evidence_dropped")),
         ({"note": "the title is cut off", "all": ["x"]}, [pics["4"], pics["4"]]))
    S.eq("control pictures: the verifier's own capture is kept, the walker's is not", ((fix.get("T1-5") or {}).get("evidence_verifier"), (fix.get("T1-5") or {}).get("evidence"),
         (fix.get("T1-5") or {}).get("evidence_dropped")), ([vpic], [], [pics["5"]]))
    fixed = os.path.join(helpers.mkdtemp("fwx-walk-fixed-"), "fixed.json")
    helpers.write(os.path.dirname(fixed), "fixed.json", json.dumps([{"id": "T1-1", "commit": "a1"}, {"id": "T1-3", "commit": "c3"}, {"id": "T1-4", "commit": "d4"},
                                                                    {"id": "T1-5", "commit": "e5"}, {"id": "T1-7", "commit": "g7"}]))
    r = runner_walk(R, "review-page", "--run", rd, "--fixed", fixed)
    S.eq("control pictures: the review page is built", r.returncode, 0)
    items = {i["id"]: i for i in (jfile(os.path.join(rd, "review", "decisions.json")) or {}).get("items", [])}
    caps = {k: [fg["caption"] for fg in v["figures"]] for k, v in items.items()}
    S.eq("control pictures: the owner's page shows no `today` picture of the control's screen", caps.get("T1-1"), [])
    S.eq("control pictures: and still shows the other screen's", caps.get("T1-3"), ["today"])
    # what was left out is said on the item, not left as an empty space, and the verifier's capture is the picture the owner gets instead
    # Seen red on 1afad4d: FAIL: control pictures: the item says a picture was left out and why: ['Screen: /settings', 'Commit: a1', 'the title is cut off']
    S.ok("control pictures: the item says a picture was left out and why", any("left out" in w and "planted control" in w for w in items.get("T1-1", {}).get("what", [])),
         repr(items.get("T1-1", {}).get("what")))
    S.ok("control pictures: an item with nothing left out says nothing of it", not any("left out" in w for w in items.get("T1-3", {}).get("what", [])), repr(items.get("T1-3", {}).get("what")))
    S.eq("control pictures: the verifier's own capture is the item's picture", caps.get("T1-5"), ["verified"])
    # evidence given as an object is rendered on the review item (its text, and its pictures as figures), not skipped. Seen red on a11691f:
    #   FAIL: control pictures: an object's retained text reaches the item: ['Screen: /settings', ...] has no 'x'
    S.ok("control pictures: an object's retained text reaches the item", all(w in items.get("T1-4", {}).get("what", []) for w in ("the title is cut off", "x")),
         repr(items.get("T1-4", {}).get("what")))
    S.eq("control pictures: an object's picture is a figure and its text is on the item", (caps.get("T1-7"), "seven" in items.get("T1-7", {}).get("what", [])), (["today"], True))
    # no control in the run (a recheck's folder, or a walk whose plant was refused): nothing is left out
    rd2 = helpers.mkdtemp("fwx-walk-run-")
    helpers.write(rd2, "verified-T1.json", json.dumps({"findings": [f("T1-1", "/settings", [pics["1"]])]}))
    runner_walk(R, "findings", "--run", rd2)
    S.eq("control pictures: with no control.json the evidence is as it came", (jfile(os.path.join(rd2, "fix.json")) or [{}])[0].get("evidence"), [pics["1"]])
    # a control.json that names no route cannot say which pictures to leave out: exit 2, nothing written (not read as "no control")
    rd3 = helpers.mkdtemp("fwx-walk-run-")
    helpers.write(rd3, "verified-T1.json", json.dumps({"findings": [f("T1-1", "/settings", [pics["1"]])]}))
    helpers.write(rd3, "control.json", json.dumps({"screen": "http://127.0.0.1:3000/settings"}))
    r = runner_walk(R, "findings", "--run", rd3)
    S.ok("control pictures: a control.json with no route is exit 2 and writes no fix.json", r.returncode == 2 and not os.path.exists(os.path.join(rd3, "fix.json")),
         "rc %d %s" % (r.returncode, r.stderr))


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
    S.ok("review page: only fields the verdict builder knows", keys <= {"id", "title", "what", "figures", "ask", "recommend", "options", "needs_note"}, str(keys))
    # the verdict of a fix has three choices, and the two that refuse it need the owner's reason (3.5 review U3; the choice keys are the contract of
    # review-answers). Seen red on the branch before it:
    #   FAIL: review page: a fix has the choices ok, redo and not_defect: got [[], []], want [['ok', 'redo', 'not_defect'], ['ok', 'redo', 'not_defect']]
    #   FAIL: review page: redo and not_defect need a note: got [None, None], want [['redo', 'not_defect'], ['redo', 'not_defect']]
    S.eq("review page: a fix has the choices ok, redo and not_defect", [[o.get("key") for o in i.get("options", [])] for i in items[:2]], [["ok", "redo", "not_defect"]] * 2)
    S.ok("review page: and each choice says what it is", all(o.get("text") for i in items[:2] for o in i.get("options", [])) and len(items[0].get("options", [])) == 3,
         json.dumps(items[0].get("options")))
    S.eq("review page: redo and not_defect need a note", [i.get("needs_note") for i in items[:2]], [["redo", "not_defect"]] * 2)
    S.ok("review page: a contradicted item keeps its yes/no", "options" not in items[2] and "needs_note" not in items[2] and items[2].get("ask"), json.dumps(items[2]))
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


def tree_hashes(rd):
    """{relative path: sha256} of every file under a run folder."""
    got = {}
    for base, _, names in os.walk(rd):
        for n in names:
            p = os.path.join(base, n)
            with open(p, "rb") as fh:
                got[os.path.relpath(p, rd)] = hashlib.sha256(fh.read()).hexdigest()
    return got


def case_review_answers(R, S):
    """Control 11, and the verdict of a walk's fixes (3.5 review, unit U3): `redo` and `not_defect` are two lists, each with the note and the
    fix's commit; a pick that needs a note and has none is `missing_note` and `open`; FILE is the pasted text, prose around the JSON included.
    Seen red on the branch before it (review-answers knew `ok`/`no`, printed `rejected` and stopped at the page's own `missing_note` key):
      FAIL: review answers: exit: got 2, want 0
      FAIL: review answers: a redo with its note and the fix's commit (null when the run holds none): got None, want [{'id': 'F2', 'note': 'the clip is too slow', 'commit': 'cF2'}, ...]
      FAIL: review answers: a redo with a blank note is missing_note: got None, want ['F3']
      FAIL: review answers: the run folder changes only in review/answers.json: got [], want ['review/answers.json']
      FAIL: review answers: a fix answered `no` is open, in neither list: {'accepted': [], 'rejected': [{'id': 'F2', 'note': 'x'}], ...
    (the keys, the commit and the prose cases fail the same way; 19 FAILs in all)"""
    bindir = helpers.mkdtemp("fwx-walk-bin-")
    for name, target in (("python3", PY), ("git", GIT)):
        os.symlink(target, os.path.join(bindir, name))
    env = {"PATH": bindir}
    rd = fixed_run(("F1", "F2", "F3", "F4", "F6", "F7"), "F5", with_clip=False)  # F1..F4, F6, F7 are fixes, F5 is contradicted
    fixed = os.path.join(helpers.mkdtemp("fwx-walk-fixed-"), "fixed.json")
    # F7 has no commit in the data the page was built from
    helpers.write(os.path.dirname(fixed), "fixed.json", json.dumps([{"id": i, "commit": "c" + i} for i in ("F1", "F2", "F3", "F4", "F6")] + [{"id": "F7"}]))
    r = runner_walk(R, "review-page", "--run", rd, "--fixed", fixed, env=env)
    S.eq("review answers: the page for the case", r.returncode, 0)
    answers = {"v": 2, "F1": {"pick": "ok"}, "F2": {"pick": "redo", "note": "the clip is too slow"}, "F3": {"pick": "redo", "note": "   "},
               "F4": {"pick": "ok"}, "F5": {"pick": "ok"}, "F6": {"pick": "not_defect", "note": "on purpose"}, "F7": {"pick": "redo", "note": "still wrong"},
               "open": ["F3"], "missing_note": ["F3"], "stale": ["F4"], "global": "thanks"}
    af = os.path.join(helpers.mkdtemp("fwx-walk-ans-"), "pasted.txt")
    adir = os.path.dirname(af)
    helpers.write(adir, "pasted.txt", json.dumps(answers) + "\n")
    before = tree_hashes(rd)
    r = runner_walk(R, "review-answers", "--run", rd, af, env=env)
    d = obj(r.stdout) or {}
    S.eq("review answers: exit", r.returncode, 0)
    S.eq("review answers: the keys printed", sorted(d), ["accepted", "contradicted_wanted", "missing_note", "not_defect", "open", "redo", "stale"])
    S.ok("review answers: open item F3 in accepted", d.get("accepted") == ["F1"], "accepted %s" % d.get("accepted"))
    S.eq("review answers: a redo with its note and the fix's commit (null when the run holds none)", d.get("redo"),
         [{"id": "F2", "note": "the clip is too slow", "commit": "cF2"}, {"id": "F7", "note": "still wrong", "commit": None}])
    S.eq("review answers: a not_defect with its note and commit", d.get("not_defect"), [{"id": "F6", "note": "on purpose", "commit": "cF6"}])
    S.eq("review answers: a contradicted one he wants", d.get("contradicted_wanted"), ["F5"])
    S.eq("review answers: a redo with a blank note is open", d.get("open"), ["F3"])
    S.eq("review answers: a redo with a blank note is missing_note", d.get("missing_note"), ["F3"])
    S.ok("review answers: and it is in neither list of picks", all(x["id"] != "F3" for k in ("redo", "not_defect") for x in d.get(k, [])), str(d))
    S.eq("review answers: stale (answered ok, but not accepted)", d.get("stale"), ["F4"])
    S.ok("review answers: a stale id is in no other list", all("F4" not in json.dumps(v) for k, v in d.items() if k != "stale"), str(d))
    S.eq("review answers: review/answers.json is what is printed", jfile(os.path.join(rd, "review", "answers.json")), d)
    after = tree_hashes(rd)
    S.eq("review answers: the run folder changes only in review/answers.json",
         sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)), ["review/answers.json"])
    first = d
    # the pasted text: prose before and after, two v 2 objects (the last wins), pretty-printed, stray braces in the prose
    older = {"v": 2, "F1": {"pick": "redo", "note": "old"}}
    helpers.write(adir, "prose.txt", "Here are my answers {not json}:\n" + json.dumps(older) + "\nno wait, this one:\n" + json.dumps(answers, indent=2) + "\nthanks {x\n")
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(adir, "prose.txt"), env=env)
    S.eq("review answers: prose around the JSON, two v 2 objects: the last wins and the result is the same", obj(r.stdout), first)
    helpers.write(adir, "oneline.txt", "my answers " + json.dumps(answers) + " end")
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(adir, "oneline.txt"), env=env)
    S.eq("review answers: the object in the middle of a line", obj(r.stdout), first)
    helpers.write(adir, "v1.txt", json.dumps(answers) + "\n" + json.dumps({"F1": {"pick": "redo", "note": "x"}, "v": 1}))
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(adir, "v1.txt"), env=env)
    S.eq("review answers: a later object that is not v 2 does not win", obj(r.stdout), first)
    # an item missing from the answers and from `open` is open all the same; a contradicted one he declines is neither
    helpers.write(adir, "wait2.out", json.dumps({"v": 2, "F1": {"pick": "ok"}, "F5": {"pick": "no"}}))
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(adir, "wait2.out"), env=env)
    d = obj(r.stdout) or {}
    S.eq("review answers: what he did not touch is open", d.get("open"), ["F2", "F3", "F4", "F6", "F7"])
    S.eq("review answers: untouched is not missing_note", d.get("missing_note"), [])
    S.eq("review answers: a contradicted one declined is not wanted", d.get("contradicted_wanted"), [])
    # the old `no` of a fix meant two things and counts for neither
    helpers.write(adir, "oldno.txt", json.dumps({"v": 2, "F2": {"pick": "no", "note": "x"}}))
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(adir, "oldno.txt"), env=env)
    d = obj(r.stdout) or {}
    S.ok("review answers: a fix answered `no` is open, in neither list", "F2" in d.get("open", []) and d.get("redo") == [] and d.get("not_defect") == [], str(d))
    # not an answer, an id the page never had, no page
    helpers.write(adir, "junk.out", 'no json here {"v": 1}\n')
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(adir, "junk.out"), env=env)
    S.ok("review answers: no v 2 object in the file is exit 2, one line", r.returncode == 2 and len(r.stderr.strip().splitlines()) == 1, "rc %d %s" % (r.returncode, r.stderr))
    helpers.write(adir, "other.out", json.dumps({"v": 2, "F9": {"pick": "ok"}}))
    r = runner_walk(R, "review-answers", "--run", rd, os.path.join(adir, "other.out"), env=env)
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
                  ["check-screens"], ["up", "--bogus"], ["capacity"], ["up", "--dir", "x", "--part", "x", "--round", "1"]):
        r = sc.walk(R, *argv)
        S.ok("usage: walk %s: exit 2 and a usage line" % " ".join(argv), r.returncode == 2 and "usage: fwx walk" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    h = R(sc.repo, "help")
    S.ok("`fwx help` lists walk", "walk" in h.stdout, h.stdout)


DOWNENV = """import json, os
with open("down-env.jsonl", "a") as f:
    f.write(json.dumps({k: v for k, v in os.environ.items() if k.startswith("FWX_WALK_")}) + "\\n")
"""


def case_rollback_env(R, S):
    """When an app's `up` fails, the rollback runs its `down` with the environment that app's `up` had (FWX_WALK_NAME, FWX_WALK_RUN,
    FWX_WALK_STATE): a container teardown by name (`docker rm -f "$FWX_WALK_NAME"`) needs it, and no run.json exists yet for `down` or
    `sweep` to recover the startup from. Seen red on the base (the rollback got the caller's environment):
      FAIL: rollback: the down of the failed app ran with the env its up had: got {}, want {'FWX_WALK_NAME': '<ns>-w1', 'FWX_WALK_RUN': '<ns>', 'FWX_WALK_STATE': '<run>/demo-state-w1.json'}"""
    sc = Scene(container=True, limits={"ui-walker": 2})
    try:
        helpers.write(sc.repo, "downenv.py", DOWNENV)
        app = {"up": "python3 up.py %d %s fail" % (sc.port, sc.pidfile), "run": "", "down": "python3 downenv.py", "url": sc.url + "/{name}", "container": True}
        r, o = sc.up(R, "--app", json.dumps(app))
        S.ok("rollback: a failing up exits 1", r.returncode == 1 and "up failed" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
        upenv = [json.loads(line) for line in open(sc.pidfile + ".env")]
        downenv = [json.loads(line) for line in open(os.path.join(sc.repo, "down-env.jsonl"))] if os.path.exists(os.path.join(sc.repo, "down-env.jsonl")) else []
        S.eq("rollback: the down of the failed app ran with the env its up had", downenv, upenv[:1])
        S.ok("rollback: that env names the container", bool(downenv) and downenv[0].get("FWX_WALK_NAME", "").endswith("-w1"), str(downenv))
    finally:
        sc.stop()


def case_up_restart(R, S):
    """A second `up` of the same part and round (a recheck, or a rerun after a failed one) starts clean. Seen red on the base:
      FAIL: restart: control.json of the earlier run is gone: it is still there
      FAIL: restart: a verified file of the earlier run is not left for `findings`: ['verified-T9.json']
      FAIL: restart: down leaves no session mark: ['ab-w1']
      FAIL: restart: the first call after the restart launches again (the demo session is set): calls []
    The marker case is the real consequence: a mark that `down` left made the next `ab` see an open browser and skip the demo session."""
    sc = Scene()
    try:
        o = armed(sc, R, S, "restart")
        if not o:
            return
        rd = o["run_dir"]
        S.eq("restart: first call exit", sc.walk(R, "ab", "--run", rd, "w1", "open", sc.url).returncode, 0)
        S.ok("restart: the session has its mark", os.path.exists(os.path.join(rd, "sessions", "ab-w1")))
        sc.walk(R, "pw", "--run", rd, "w1", "open", sc.url)
        S.eq("restart: down", sc.walk(R, "down", "--run", rd).returncode, 0)
        S.eq("restart: down leaves no session mark", sorted(os.listdir(os.path.join(rd, "sessions"))) if os.path.isdir(os.path.join(rd, "sessions")) else [], [])
        helpers.write(rd, "control.json", json.dumps({"screen": sc.url + "/a", "path": "/a", "script": os.path.join(rd, "init.js")}))
        helpers.write(rd, "verified-T9.json", json.dumps([{"id": "T9-1", "verdict": "CONFIRMED"}]))
        # A recheck's capture is joined to a finding by id (`review-page`), and a new walk numbers its findings T9-1 again: the earlier
        # recheck's file must not stay where the page reads it. Seen red on the base (PR 103 review thread, "Exclude recheck captures from
        # earlier walk invocations"):
        #   FAIL: restart: a rechecked file of the earlier run is not left for `review-page`: ['rechecked-T9.json']
        helpers.write(rd, "rechecked-T9.json", json.dumps({"findings": [{"id": "T9-1", "verdict": "NOT REPRODUCED", "evidence_after": "/srv/old-after.png"}]}))
        # a tramo id is whatever the tramos agent named it (`safe` in ui-walk.js lets any letter or digit start it): not only `T<n>`. A glob
        # narrowed to `rechecked-T*.json` passed the first version of this case.
        helpers.write(rd, "rechecked-x7.json", json.dumps({"findings": [{"id": "x7-1", "verdict": "NOT REPRODUCED", "evidence_after": "/srv/old-after.png"}]}))
        r, o2 = sc.up(R)
        if not S.ok("restart: up armed again", r.returncode == 0 and o2 and o2.get("armed") is True, "rc %d %s" % (r.returncode, r.stderr)):
            return
        S.ok("restart: control.json of the earlier run is gone", not os.path.exists(os.path.join(rd, "control.json")), "it is still there")
        S.eq("restart: a verified file of the earlier run is not left for `findings`", sorted(f for f in os.listdir(rd) if f.startswith("verified-")), [])
        S.ok("restart: and it is kept, not deleted", os.path.exists(os.path.join(rd, "earlier", "verified-T9.json")))
        S.eq("restart: a rechecked file of the earlier run is not left for `review-page`", sorted(f for f in os.listdir(rd) if f.startswith("rechecked-")), [])
        S.ok("restart: and it is kept, not deleted (rechecked)", os.path.exists(os.path.join(rd, "earlier", "rechecked-T9.json"))
             and os.path.exists(os.path.join(rd, "earlier", "rechecked-x7.json")))
        sc.clear()
        sc.walk(R, "ab", "--run", rd, "w1", "snapshot")
        S.ok("restart: the first call after the restart launches again (the demo session is set)",
             any(c["argv"][-6:-4] == ["cookies", "set"] for c in sc.calls("agent-browser")), "calls %s" % [c["argv"][-6:] for c in sc.calls("agent-browser")])
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


def case_finding_ids(R, S):
    """A finding id names files (the review figures, the clip), so one that is a path is refused before any file is built from it.
    Seen red on the base (`findings` took any non-empty string, and `review-page` joined it into the figures folder):
      FAIL: finding ids: ../../escape (CONTRADICTED): exit: got 0, want 2
      FAIL: finding ids: review-page with the id ../../evil: exit: got 0, want 2
      FAIL: finding ids: review-page with the id ../../evil: nothing was written outside review/: ['evil-today-1.png']
    A normal id (F1, T1-3, a.b_c) is the negative control: it still goes through, and every other test of the file uses them."""
    for label, fid in (("../../escape", "../../escape"), ("a/b", "a/b"), ("a\\b", "a\\b"), ("empty after trim", " "), ("leading dot", ".hidden")):
        bad = helpers.mkdtemp("fwx-walk-run-")
        helpers.write(bad, "verified-1.json", json.dumps([{"id": fid, "file": "a.ts", "line": 1, "claim": "c", "evidence": "e", "severity": "minor",
                                                           "verdict": "CONTRADICTED"}]))
        r = runner_walk(R, "findings", "--run", bad)
        S.ok("finding ids: %s (CONTRADICTED): exit 2, nothing written" % label, r.returncode == 2 and not os.path.exists(os.path.join(bad, "contradicted.json"))
             and "id" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    ok = helpers.mkdtemp("fwx-walk-run-")
    helpers.write(ok, "verified-1.json", json.dumps([{"id": i, "file": "a.ts", "line": 1, "claim": "c", "evidence": "e", "severity": "minor", "verdict": "CONTRADICTED"}
                                                     for i in ("F1", "T1-3", "a.b_c")]))
    r = runner_walk(R, "findings", "--run", ok)
    S.ok("finding ids: F1, T1-3 and a.b_c are ids", r.returncode == 0 and [x["id"] for x in jfile(os.path.join(ok, "contradicted.json"))] == ["F1", "T1-3", "a.b_c"],
         "rc %d %s" % (r.returncode, r.stderr))
    # a contradicted.json that was not made by `findings` (the review page builds file names from it too)
    rd = fixed_run(("F1",), "F3", images=("F3",))
    con = jfile(os.path.join(rd, "contradicted.json"))
    con[0]["id"] = "../../evil"
    helpers.write(rd, "contradicted.json", json.dumps(con))
    fixed = os.path.join(helpers.mkdtemp("fwx-walk-fixed-"), "fixed.json")
    helpers.write(os.path.dirname(fixed), "fixed.json", json.dumps([{"id": "F1", "commit": "abc1234"}]))
    r = runner_walk(R, "review-page", "--run", rd, "--fixed", fixed)
    S.eq("finding ids: review-page with the id ../../evil: exit", r.returncode, 2)
    S.eq("finding ids: review-page with the id ../../evil: nothing was written outside review/",
         sorted(f for f in os.listdir(rd) if f.startswith("evil")), [])


def case_review_recheck(R, S):
    """The recheck's capture of a fixed finding is its `built` figure on the review page. The verifier of a recheck saves it in
    rechecked-<tramo>.json (`evidence_after`), not in fix.json, so the page joins it by finding id; a finding the recheck did not cover
    keeps what fix.json has. Seen red on the base (review-page read fix.json only):
      FAIL: review recheck: F1 has today and built (the recheck's capture): got ['today'], want ['today', 'built']"""
    bindir = helpers.mkdtemp("fwx-walk-bin-")
    for name, target in (("python3", PY), ("git", GIT)):
        os.symlink(target, os.path.join(bindir, name))
    env = {"PATH": bindir}
    rd = fixed_run(("F1", "F2", "F4"), "F3", images=("F1", "F2", "F3"), with_clip=False)
    fix = jfile(os.path.join(rd, "fix.json"))
    fix[0].pop("evidence_after")  # F1: the walk's own fix.json has no `built`; only the recheck does
    helpers.write(rd, "fix.json", json.dumps(fix))
    with open(os.path.join(rd, "shots", "after-F1.png"), "wb") as fh:
        fh.write(PNG)
    helpers.write(rd, "rechecked-T1.json", json.dumps({"findings": [{"id": "F1", "verdict": "NOT REPRODUCED", "evidence_after": os.path.join(rd, "shots", "after-F1.png")},
                                                                    {"id": "F2", "verdict": "NOT REPRODUCED"}]}))
    fixed = os.path.join(helpers.mkdtemp("fwx-walk-fixed-"), "fixed.json")
    helpers.write(os.path.dirname(fixed), "fixed.json", json.dumps([{"id": "F1", "commit": "a1"}, {"id": "F2", "commit": "b2"}, {"id": "F4", "commit": "c4"}]))
    r = runner_walk(R, "review-page", "--run", rd, "--fixed", fixed, env=env)
    S.eq("review recheck: exit", r.returncode, 0)
    items = {i["id"]: i for i in (jfile(os.path.join(rd, "review", "decisions.json")) or {}).get("items", [])}
    caps = {k: [fg["caption"] for fg in v["figures"]] for k, v in items.items()}
    S.eq("review recheck: F1 has today and built (the recheck's capture)", caps.get("F1"), ["today", "built"])
    S.eq("review recheck: F2 was rechecked without a capture and keeps the one fix.json has", caps.get("F2"), ["today", "built"])
    S.eq("review recheck: F4 was not rechecked and has no figure", caps.get("F4"), [])


def case_arm_control_root(R, S):
    """The plant's route test is the same for `/` as for any route: the page's pathname with its trailing slashes cut is `""` for the
    root, and the plant stores `/`. Seen red on the base (the script compared `""` with `"/"`, so on the root screen it never applied
    and arm-control's read-back refused it as `no visible change`):
      FAIL: arm-control root: the plant restyles the title on /: got {}, want {'font-size': '16px', 'font-weight': '400'}
    The same script on another route is the negative control: it leaves the title alone."""
    if not shutil.which("node"):
        sys.stderr.write("NOT RUN, NOT ARMED: node missing: the plant's route match for the root screen was not run\n")
        return
    sc = Scene()
    try:
        o = armed(sc, R, S, "arm-control root")
        if not o:
            return
        rd = o["run_dir"]
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + "/")
        S.eq("arm-control root: exit", r.returncode, 0)
        c = jfile(os.path.join(rd, "control.json")) or {}
        S.eq("arm-control root: the plant's path", c.get("path"), "/")
        harness = ("let styled = {};\n"
                   "const h = {dataset: {}, style: {setProperty(k, v) { styled[k] = v; }}};\n"
                   "global.location = {pathname: process.argv[3]};\n"
                   "global.document = {querySelector: () => h, body: {}, addEventListener() {}};\n"
                   "global.getComputedStyle = () => ({fontSize: '16px', fontWeight: '400'});\n"
                   "global.MutationObserver = class { observe() {} };\n"
                   "eval(require('fs').readFileSync(process.argv[2], 'utf8'));\n"
                   "console.log(JSON.stringify(styled));\n")
        hp = os.path.join(helpers.mkdtemp("fwx-walk-node-"), "harness.js")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(harness)
        for pathname, want in (("/", {"font-size": "16px", "font-weight": "400"}), ("/other", {})):
            out = subprocess.run(["node", hp, c["script"], pathname], capture_output=True, text=True)
            got = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else out.stderr[-200:]
            S.eq("arm-control root: the plant restyles the title on %s" % pathname if want else "arm-control root: it leaves the title alone on %s" % pathname, got, want)
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


def case_arm_control_launch_path(R, S):
    """F-3: the control is proved in a browser launched the way the walkers' sessions are (control.json written first, so the launch carries
    --init-script), not by running its code on the page by hand. A fake agent-browser that drops --init-script (FAKE_INIT=ignore: the
    walkers' launch path does not plant) is the case that exposed it. Seen red on the base (it ran the code by eval, so the plant showed
    on the page and the arming passed):
      FAIL: arm-control launch path: a browser that ignores --init-script: exit: got 0, want 1
      FAIL: arm-control launch path: a browser that ignores --init-script: says no visible change, in a fresh walker session, and where: rc 0:
      FAIL: arm-control launch path: a browser that ignores --init-script: no control.json is left
    The same call on a browser that takes the script is the negative control (armed, the readings differ)."""
    sc = Scene()
    sc.env["FWX_WALK_CONTROL_WAIT_S"] = "1"
    try:
        o = armed(sc, R, S, "arm-control launch path")
        if not o:
            return
        rd = o["run_dir"]
        label = "arm-control launch path: a browser that ignores --init-script"
        sc.env["FAKE_INIT"] = "ignore"
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + "/board")
        S.eq(label + ": exit", r.returncode, 1)
        S.ok(label + ": says no visible change, in a fresh walker session, and where",
             "no visible change" in r.stderr and "fresh walker session" in r.stderr and sc.url + "/board" in r.stderr, "rc %d: %s" % (r.returncode, r.stderr))
        S.ok(label + ": the same reason on stdout as {armed: false}", (obj(r.stdout) or {}).get("armed") is False, r.stdout)
        S.ok(label + ": no control.json is left", not os.path.exists(os.path.join(rd, "control.json")))
        shots = (jfile(os.path.join(rd, "run.json")) or {}).get("shots", "")
        S.ok(label + ": and no init script", bool(shots) and not os.path.exists(os.path.join(shots, "init.js")), shots)
        del sc.env["FAKE_INIT"]
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + "/board")
        S.eq("arm-control launch path: a browser that takes the script: exit", r.returncode, 0)
        S.ok("arm-control launch path: a browser that takes the script: control.json is there", os.path.isfile(os.path.join(rd, "control.json")))
        # armed again over the earlier plant: the reading without the plant is still taken before any launch that carries it
        sc.clear()
        r = sc.walk(R, "arm-control", "--run", rd, "--screen", sc.url + "/board")
        calls = [x["argv"] for x in sc.calls("agent-browser")]
        first_read = next((i for i, a in enumerate(calls) if "eval" in a and "fwx:" in a[-1]), None)
        first_init = next((i for i, a in enumerate(calls) if "--init-script" in a), None)
        S.ok("arm-control launch path: armed again over an earlier plant, the first reading is taken with no plant",
             r.returncode == 0 and first_read is not None and first_init is not None and first_read < first_init, "rc %d reads %r launch %r" % (r.returncode, first_read, first_init))
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()


class Pages:
    """A toy app on a port chosen free at run time, in a thread of this process: /ok answers 200, /docs/docs 404, /go-local redirects to /ok
    and /go-away to a host that is not local. `hits` lists the paths it was asked for."""

    def __init__(self):
        import http.server
        import threading
        outer = self
        self.hits = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(self.path)
                code, loc = {"/go-local": (302, outer.url + "/ok"), "/go-away": (302, "http://example.test/ok"),
                             "/docs/docs": (404, None)}.get(self.path, (200, None))
                self.send_response(code)
                if loc:
                    self.send_header("Location", loc)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def case_check_screens(R, S):
    """F-1: `fwx walk check-screens --run R --screens JSON` asks each screen through the probe `up` uses (the app's `run` prefix, local
    redirects followed, any other redirect refused) and exits 1 naming each screen that does not answer 2xx. Seen red before it existed
    (the walk went on to walk /docs/docs for 13 minutes in the rehearsal; every call exited 2 with the usage line):
      FAIL: check-screens: all answer 200: exit: got 2, want 0
      FAIL: check-screens: one answers 404: exit: got 2, want 1
      FAIL: check-screens: one answers 404: stderr names the screen and the status: rc 2: fwx walk: usage ...
    The all-200 call is the negative control of the 404 one: same command, same toy app, only the path differs."""
    sc = Scene()
    pg = Pages()
    try:
        o = armed(sc, R, S, "check-screens")
        if not o:
            return
        rd = o["run_dir"]

        def check(*paths):
            r = sc.walk(R, "check-screens", "--run", rd, "--screens", json.dumps([p if "://" in p else pg.url + p for p in paths]))
            return r, obj(r.stdout) or {}
        r, out = check("/ok", "/other")
        S.eq("check-screens: all answer 200: exit", r.returncode, 0)
        S.eq("check-screens: all answer 200: JSON", (out.get("checked"), out.get("bad"), [x.get("status") for x in out.get("screens", [])]), (2, 0, [200, 200]))
        r, out = check("/ok", "/docs/docs", "/other")
        S.eq("check-screens: one answers 404: exit", r.returncode, 1)
        S.ok("check-screens: one answers 404: stderr names the screen and the status", pg.url + "/docs/docs" in r.stderr and "404" in r.stderr, "rc %d: %s" % (r.returncode, r.stderr))
        S.ok("check-screens: one answers 404: stderr does not name the screens that answer", "/ok" not in r.stderr and "/other" not in r.stderr, r.stderr)
        S.eq("check-screens: one answers 404: JSON says which", [(x.get("url"), x.get("status"), x.get("ok")) for x in out.get("screens", [])],
             [(pg.url + "/ok", 200, True), (pg.url + "/docs/docs", 404, False), (pg.url + "/other", 200, True)])
        S.eq("check-screens: one answers 404: checked and bad", (out.get("checked"), out.get("bad")), (3, 1))
        r, out = check("/go-local")
        S.eq("check-screens: a redirect to a local host is followed: exit", r.returncode, 0)
        S.eq("check-screens: a redirect to a local host is followed: the final status", [x.get("status") for x in out.get("screens", [])], [200])
        r, out = check("/go-away")
        S.eq("check-screens: a redirect to a host that is not local is not followed: exit", r.returncode, 1)
        S.ok("check-screens: a redirect to a host that is not local is not followed: it names the screen and the redirect's status",
             pg.url + "/go-away" in r.stderr and "302" in r.stderr, r.stderr)
        r, out = check("/docs/docs", "/go-away", "/ok")
        S.ok("check-screens: every bad screen is named, not the first", pg.url + "/docs/docs" in r.stderr and pg.url + "/go-away" in r.stderr, r.stderr)
        pg.hits.clear()
        r, out = check("http://example.test/ok", "file:///etc/hostname", "/ok")
        S.eq("check-screens: a screen that is not on the app: exit", r.returncode, 1)
        S.ok("check-screens: a screen that is not on the app: named, and not asked", "example.test/ok" in r.stderr and "file:///etc/hostname" in r.stderr
             and "not on the app" in r.stderr and "etc/hostname" not in "".join(pg.hits), "rc %d: %s hits %r" % (r.returncode, r.stderr, pg.hits))
        pg.hits.clear()
        r, out = check("/ok", "/ok")
        S.eq("check-screens: a screen listed twice is asked once", (out.get("checked"), pg.hits), (1, ["/ok"]))
        # nothing to look at is a refusal, not a pass; a usage error is exit 2
        for label, argv in (("an empty list", ["--screens", "[]"]), ("not JSON", ["--screens", "nope"]), ("a list of numbers", ["--screens", "[1]"]), ("no --screens", [])):
            r = sc.walk(R, "check-screens", "--run", rd, *argv)
            S.ok("check-screens: %s: exit 2 and a usage line" % label, r.returncode == 2 and "usage: fwx walk check-screens" in r.stderr, "rc %d: %s" % (r.returncode, r.stderr))
        r = sc.walk(R, "check-screens", "--screens", "[]")
        S.eq("check-screens: no --run: exit 2", r.returncode, 2)
        sc.walk(R, "down", "--run", rd)
    finally:
        pg.stop()
        sc.stop()
    # the probe runs from where the app lives: through the app's `run` prefix, as the selftest's does
    sc = Scene(prefix="fakerig run --")
    pg = Pages()
    try:
        o = armed(sc, R, S, "check-screens prefix")
        if not o:
            return
        sc.clear()
        r = sc.walk(R, "check-screens", "--run", o["run_dir"], "--screens", json.dumps([pg.url + "/ok"]))
        S.eq("check-screens prefix: exit", r.returncode, 0)
        S.ok("check-screens prefix: the screen was asked through the rig prefix", [c["prog"] for c in sc.calls()] == ["fakerig"] and pg.hits == ["/ok"],
             "%r hits %r" % ([c["prog"] for c in sc.calls()], pg.hits))
        sc.walk(R, "down", "--run", o["run_dir"])
    finally:
        pg.stop()
        sc.stop()


CASES = [case_url_guard, case_probe, case_run_prefix, case_up, case_ab_guard, case_ab_session, case_ab_commands, case_ab_viewport, case_run_empty, case_pw, case_hygiene, case_arm_control, case_arm_control_readback, case_down_count,
         case_off, case_container, case_capacity_missing, case_capacity_resize, case_factory, case_findings, case_review_page, case_review_answers, case_sweep,
         case_usage, case_rollback_env, case_up_restart, case_finding_ids, case_review_recheck, case_arm_control_root, case_planted_captures, case_findings_control_pictures,
         case_arm_control_launch_path, case_check_screens]

W = "lib/fwx/commands/walk.py"
# (name, case, old text, new text, the FAIL text it must produce); each `old` is in walk.py exactly once, and a control whose `old`
# has gone is an error, never a silent pass. The first eleven are the unit's controls, in its order.
MUTANTS = [
    ("1 url guard", case_url_guard, 'if a["url"] and not local_host(a["url"]):', "if False:", "url guard: up with https://app.example.test: exit: got 1, want 2"),
    ("2 probe", case_probe, 'if a["url"] and answering(a["url"], a["run"], repo):', "if False:", "probe: a server already answering: exit: got 1, want 2"),
    ("2 pre-up asked from the host", case_run_prefix, 'if a["url"] and answering(a["url"], a["run"], repo):', 'if a["url"] and answering(a["url"]):',
     "run prefix: a host server the prefix cannot see: up armed"),
    ("2 post-up asked from the host", case_run_prefix, 'if not wait_for(a["url"], a["run"], repo):', 'if not wait_for(a["url"]):',
     "run prefix: the app answers inside the prefix only after up: up armed"),
    ("2 guard off inside the prefix", case_run_prefix, 'if a["url"] and answering(a["url"], a["run"], repo):', "if False:",
     "run prefix: an app already answering inside the prefix: exit: got 0, want 2"),
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
    ("6 run '' as a prefix", case_run_empty, 'prefix = shlex.split(app["run"])\n    seen = ',
     'prefix = [app["run"]]\n    seen = ', 'run "": ab was called'),
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
    ("10 no choices on a fix", case_review_page, "notes, choices=True))", "notes))", "review page: a fix has the choices ok, redo and not_defect"),
    ("10 no needs_note", case_review_page, "item.update(options=[dict(c) for c in FIX_CHOICES], needs_note=list(NEEDS_NOTE))",
     "item.update(options=[dict(c) for c in FIX_CHOICES])", "review page: redo and not_defect need a note"),
    ("11 unanswered counted", case_review_answers, 'pick = a.get("pick")', 'pick = a.get("pick") or "ok"', "review answers: what he did not touch is open"),
    ("11 stale counted", case_review_answers, "        if fid in stale:\n            continue", "        if False:\n            continue",
     "review answers: a stale id is in no other list"),
    ("11 no note needed", case_review_answers, "if isinstance(note, str) and note.strip():", "if True:", "review answers: a redo with a blank note is open"),
    ("11 the first object wins", case_review_answers, "found, at = v, end", "return v", "review answers: prose around the JSON, two v 2 objects: the last wins"),
    ("11 commit not carried", case_review_answers, '"commit": m.get("commit")}', '"commit": None}', "review answers: a redo with its note and the fix's commit"),
    ("11 not_defect is a redo", case_review_answers, 'out[pick].append({"id": fid', 'out["redo"].append({"id": fid', "review answers: a not_defect with its note and commit"),
    ("ab: the prefix on every call", case_ab_session, 'rc = execute((prefix if launch else []) + ["agent-browser"] + a, env, run["repo"], quiet, seen',
     'rc = execute(prefix + ["agent-browser"] + a, env, run["repo"], quiet, seen',
     "ab session: only the call that launches the daemon goes through the rig prefix"),
    ("ab: no socket dir", case_ab_session, 'env = clean_env({"AGENT_BROWSER_SOCKET_DIR": socket_dir()} if prefix and not launch else None)',
     "env = clean_env()", "ab session: a later call carries the socket dir"),
    ("ab: no cookies", case_ab_session, 'for name, value in cookies_of(app["state"]):', "for name, value in []:",
     "ab session: the first call is a cookie of the demo session"),
    ("ab: no init script", case_ab_session, "if fresh and planted:", "if False:", "ab session: --init-script rides on the launch only"),
    ("ab: the plant on a verifier", case_ab_session, ' and not session.startswith("v") and os.path.isfile(ctl)', " and os.path.isfile(ctl)", "ab session: a verifier session (v1) launches without the planted control"),
    ("ab: close of a session never opened launches it", case_ab_session, 'if fresh and words[:1] == ["close"] and "--all" not in args:', "if False:",
     "ab session: close of a session never opened: no browser call"),
    ("ab: close --all is a no-op too", case_ab_session, 'if fresh and words[:1] == ["close"] and "--all" not in args:', 'if fresh and words[:1] == ["close"]:',
     "ab session: close --all is not a no-op"),
    ("ab: close keeps the session", case_ab_session, 'if "close" in words:', "if False:", "ab session: after close the next call launches again"),
    ("ab: commands refused", case_ab_commands, 'REFUSED_COMMANDS = (', 'REFUSED_COMMANDS = () and (', "ab commands: inspect: exit 2 naming the word"),
    ("ab: no viewport", case_ab_viewport, "if sized_first:", "if False:", "ab viewport: the first open sets the viewport once"),
    ("ab: viewport on every call", case_ab_viewport, "if sized_first:", "if True:", "ab viewport: a second open of the same session does not repeat it"),
    ("ab: viewport over the caller's", case_ab_viewport, "sized_first = fresh and not own_size", "sized_first = fresh",
     "ab viewport: a first call that is a viewport is not preceded by ours"),
    ("pw: not offline", case_pw, '"npx", "--offline", "--no-install", ', '"npx", "--no-install", ', "pw: offline, no install, the pinned CLI"),
    ("pw: no Firefox check", case_pw, "if not os.path.isdir(os.path.join(pw_browsers(), PW_FIREFOX)):", "if False:", "pw: no Firefox"),
    ("arm-control: any screen", case_arm_control, 'if host_of(screen) not in run["hosts"]:', "if False:", "arm-control: a screen outside the app is refused"),
    ("arm-control: no visible change accepted", case_arm_control_readback, "if max(abs(after[2] - before[2]), abs(after[3] - before[3])) < CONTROL_MIN_BOX_PX:", "if False:",
     "arm-control read-back: the title already has the planted style: exit"),
    ("arm-control: the styles decide, not the box", case_arm_control_readback, "if max(abs(after[2] - before[2]), abs(after[3] - before[3])) < CONTROL_MIN_BOX_PX:",
     "if after[:2] == before[:2]:", "arm-control read-back: a weight-only change that leaves the box as it was: exit"),
    ("arm-control: the box number is not from the environment", case_arm_control_readback, 'int(os.environ.get("FWX_WALK_CONTROL_MIN_BOX_PX") or 1)', "1",
     "arm-control read-back: a 10 px change with FWX_WALK_CONTROL_MIN_BOX_PX=50: exit"),
    ("arm-control: the box must change by more than the number", case_arm_control_readback, ") < CONTROL_MIN_BOX_PX:", ") <= CONTROL_MIN_BOX_PX:",
     "arm-control read-back: a 10 px change with FWX_WALK_CONTROL_MIN_BOX_PX=10: armed"),
    ("arm-control: the boxes not recorded", case_arm_control_readback, '"box": {"before": box(before), "after": box(after)}, ', "",
     "arm-control read-back: the boxes are recorded beside the styles"),
    ("arm-control: a missing target accepted", case_arm_control_readback, "if before is None:", "if False:",
     "arm-control read-back: no title on the screen: says target not found"),
    ("arm-control: an old control.json kept", case_arm_control_launch_path, "os.remove(ctl_file)", "pass",
     "arm-control launch path: armed again over an earlier plant, the first reading is taken with no plant"),
    ("arm-control: the reason not on stdout", case_arm_control_readback, 'say({"armed": False, "reason": str(e)})', "pass",
     "arm-control read-back: and the same reason on stdout"),
    ("arm-control: the probe session left open", case_arm_control_readback, 'browser_call(run, ["close"])', "pass",
     "arm-control read-back: the probe session is closed last"),
    ("sweep: every owner alive", case_sweep, "return start is not None and start == w.get(\"owner_start\")", "return True",
     "sweep: took down the one without an owner"),
    ("capacity resize: tramos not doubled", case_capacity_resize, 'cap = capacity(run["repo"], tramos * 2, run["container"])', 'cap = capacity(run["repo"], tramos, run["container"])',
     "capacity resize: three tramos: asked for 6"),
    ("capacity resize: always 2 (the `up` default)", case_capacity_resize, 'cap = capacity(run["repo"], tramos * 2, run["container"])', 'cap = capacity(run["repo"], 2, run["container"])',
     "capacity resize: three tramos: asked for 6"),
    ("capacity resize: run.json not rewritten", case_capacity_resize, '    run["capacity"] = cap\n    write_json(os.path.join(rd, "run.json"), run)\n', "",
     "capacity resize: run.json carries the new answer"),
    ("capacity resize: container quota past the apps", case_capacity_resize, 'cap["allowed"] = min(cap["allowed"], len(run["apps"]))', "pass",
     "capacity resize: container: the quota never passes the apps"),
    ("8 temp capture path allowed", case_hygiene, 'return temp_path_problem(args, run, pw, run["shots"] if pw else run["repo"])', "return None",
     "hygiene capture path: ab screenshot /tmp/v1b.png: exit 2"),
    ("8 run folder not exempt", case_hygiene, 'if not (inside(full, run["run_dir"]) or inside(full, run["shots"])) and any(', "if any(",
     "hygiene capture path: ab screenshot @e1 in the captures folder: runs"),
    ("8 every path is a temp path", case_hygiene, 'and any(inside(full, d) for d in temps):', "and True:",
     "hygiene capture path: ab screenshot a path outside any temp folder: runs"),
    ("8 fill words read as paths", case_hygiene, 'elif words[:1] == ["screenshot"]:', "elif words[:1]:",
     "hygiene capture path: ab fill with a /tmp word"),
    ("9 pw outputDir missing", case_hygiene, '"outputDir": run["shots"],', '"x": 0,', "hygiene pw: the config's outputDir"),
    ("9 pw runs in the project", case_hygiene, 'run["repo"] if prefix else run["shots"])', 'run["repo"])', "hygiene pw: a later call runs in the captures folder"),
    ("9 target files kept", case_hygiene, '"removed": drop_targets(ns)', '"removed": 0', "hygiene down: the target files of the namespace are gone"),
    ("9 every namespace's targets", case_hygiene, 'os.path.join(socket_dir(), "namespaces", ns, "run")', 'os.path.join(socket_dir(), "namespaces", "*", "run")',
     "hygiene down: another walk's target file stays"),
    ("rollback with the caller's env", case_rollback_env, "stop_apps(started, repo, lambda a: app_env(a, ns, container, env_base))",
     "stop_apps(started, repo, lambda a: env_base)", "rollback: the down of the failed app ran with the env its up had"),
    ("control.json kept at up", case_up_restart, '("down.json", "run.json", "control.json", "control-pictures.txt")', '("down.json", "run.json")', "restart: control.json of the earlier run is gone"),
    ("verified files kept at up", case_up_restart, 'os.replace(old, os.path.join(run_dir, "earlier", os.path.basename(old)))', "pass",
     "restart: a verified file of the earlier run is not left for `findings`"),
    ("session marks kept by down", case_up_restart, 'for p in glob.glob(os.path.join(rd, "sessions", "ab-*")) + glob.glob(os.path.join(rd, "sessions", "pw-*")):',
     "for p in []:", "restart: down leaves no session mark"),
    ("finding id not checked", case_finding_ids, "if not brief.ID.match(fid):", "if False:", "finding ids: ../../escape (CONTRADICTED)"),
    ("recheck captures not joined", case_review_recheck, 'dict(f, evidence_after=after[x["id"]]) if x["id"] in after else f', "f",
     "review recheck: F1 has today and built"),
    ("pw: no proxy for outside hosts", case_pw, 'launch = {"headless": True, "firefoxUserPrefs": {"network.proxy.type": 2, "network.proxy.autoconfig_url": pw_pac(run["hosts"])}}',
     'launch = {"headless": True}', "pw: the config carries a proxy-autoconfig script"),
    ("pw: the boundary only for walker sessions", case_pw, 'launch = {"headless": True, "firefoxUserPrefs": {"network.proxy.type": 2, "network.proxy.autoconfig_url": pw_pac(run["hosts"])}}',
     'launch = {"headless": True, "firefoxUserPrefs": {"network.proxy.type": 2, "network.proxy.autoconfig_url": pw_pac(run["hosts"])}} if session.startswith("w") else {"headless": True}', "pw: a verifier's session (v1) has the same boundary as a walker's"),
    ("pw: hosts matched by suffix", case_pw, '.indexOf(h)>=0?', '.some(function(x){return h.slice(-x.length)===x})?',
     "pw/ab boundary: Firefox and Chromium refuse the same urls"),
    ("pw: one config file for every session", case_pw, '"pw.config-%s.json" % session', '"pw.config.json"', "pw: a second session's config is its own file"),
    ("rechecked files kept at up, only those of a tramo named T<n>", case_up_restart, 'glob.glob(os.path.join(run_dir, "rechecked-*.json"))',
     'glob.glob(os.path.join(run_dir, "rechecked-T*.json"))', "restart: a rechecked file of the earlier run is not left for `review-page`"),
    ("rechecked files kept at up", case_up_restart, ' + glob.glob(os.path.join(run_dir, "rechecked-*.json")):', ":",
     "restart: a rechecked file of the earlier run is not left for `review-page`"),
    ("a control.json with no route is read as no control", case_findings_control_pictures, 'if not isinstance(route, str) or not route.startswith("/"):', "if False:",
     "control pictures: a control.json with no route is exit 2 and writes no fix.json"),
    ("a listed picture is kept wherever it is attached", case_findings_control_pictures, "(on_route or os.path.realpath(resolve(rd, v)) in taint)", "on_route",
     "control pictures: a picture listed as taken on the control's route is left out wherever it is attached"),
    ("a capture on the control's route is not listed", case_planted_captures, "if url and route_of(url) != ctl.get(\"path\"):\n        return", "if True:\n        return",
     "planted captures: a walker's capture of the control's route is listed"),
    ("a capture of a page whose route cannot be read is not listed", case_planted_captures, 'if url and route_of(url) != ctl.get("path"):', 'if route_of(url or "") != ctl.get("path"):',
     "planted captures: a page whose route cannot be read is listed"),
    ("a capture of another route is listed", case_planted_captures, 'if url and route_of(url) != ctl.get("path"):', "if False:",
     "planted captures: a capture of another route is not"),
    ("a verifier's capture is listed", case_planted_captures, 'planted = not os.environ.get("FWX_WALK_NO_CONTROL") and not session.startswith("v") and os.path.isfile(ctl)',
     'planted = not os.environ.get("FWX_WALK_NO_CONTROL") and os.path.isfile(ctl)', "planted captures: a verifier's capture is not"),
    ("the tool's output swallowed", case_planted_captures, "                sys.stdout.write(r.stdout)\n", "", "planted captures: the tool's own output goes through"),
    ("object evidence is not rendered", case_findings_control_pictures, "        elif isinstance(x, dict):\n            for y in x.values():\n                yield from leaves(y)\n", "",
     "control pictures: an object's picture is a figure and its text is on the item"),
    ("evidence given as an object kept whole",case_findings_control_pictures, "return {k: x for k, (x, gone) in ((k, strip(y)) for k, y in v.items()) if not gone}, False",
     "return v, False", "control pictures: evidence given as an object is filtered by the same rule"),
    ("a picture left out is not said on the item", case_findings_control_pictures, 'if isinstance(left, list) and left else ""]', 'if False else ""]',
     "control pictures: the item says a picture was left out and why"),
    ("the verifier's own capture is not shown", case_findings_control_pictures, 'seen, t4 = figures_of(rd, rev, fid, "verified", f.get("evidence_verifier"))',
     "seen, t4 = [], []", "control pictures: the verifier's own capture is the item's picture"),
    ("the control's pictures reach the fixer",case_findings_control_pictures, 'return dict(f, evidence=kept, evidence_dropped=left) if left else f', "return f",
     "control pictures: a finding on the control's screen keeps no walker picture"),
    ("firefox without the demo session", case_pw, 'if os.path.isfile(app["state"]):', "if False:", "pw: the config is Firefox, headless, 1309x818 at 1.1, with the demo session"),
    ("root route never matches", case_arm_control_root, '|| "/") !== PATH', ') !== PATH', "arm-control root: the plant restyles the title on /"),
    ("capacity unavailable is 0", case_capacity_missing, '"allowed": 1, "note"', '"allowed": 0, "note"', "capacity unavailable: armed with a quota of 1"),
    ("check-screens: any status is ok", case_check_screens, "ok = got.isdigit() and 200 <= int(got) < 300", "ok = got.isdigit()",
     "check-screens: one answers 404: exit: got 0, want 1"),
    ("check-screens: a failing run exits 0", case_check_screens, "return 1 if bad else 0", "return 0", "check-screens: one answers 404: exit: got 0, want 1"),
    ("check-screens: a screen off the app is asked for", case_check_screens, 'if not (local_host(u) and host_of(u) in run["hosts"]):', "if False:",
     "check-screens: a screen that is not on the app: named, and not asked"),
    ("check-screens: a redirect off the app is followed", case_check_screens,
     'return super().redirect_request(req, fp, code, msg, headers, newurl) if host in LOCAL or host.endswith(".localhost") else None',
     "return super().redirect_request(req, fp, code, msg, headers, newurl)", "check-screens: a redirect to a host that is not local is not followed: it names the screen"),
    ("check-screens: only the first bad screen is named", case_check_screens, "    for r in bad:\n", "    for r in bad[:1]:\n",
     "check-screens: every bad screen is named, not the first"),
    ("check-screens: a screen listed twice is asked twice", case_check_screens, "for u in dict.fromkeys(screens):", "for u in screens:",
     "check-screens: a screen listed twice is asked once"),
    ("check-screens: an empty list is a pass", case_check_screens, "or not screens or not all(", "or not all(", "check-screens: an empty list: exit 2 and a usage line"),
    ("arm-control: the plant is written after the proof", case_arm_control_launch_path, "    arm()\n    after = read_fresh(run, screen)", "    after = read_fresh(run, screen)",
     "arm-control launch path: a browser that takes the script: exit"),
    ("arm-control: control.json left after a refusal", case_arm_control_launch_path, "for left in (ctl_file, script):", "for left in (script,):",
     "arm-control launch path: a browser that ignores --init-script: no control.json is left"),
    ("check-screens: asked from the host, not through the prefix", case_check_screens, 'got = ask(u, run["run"], run["repo"])', 'got = ask(u, "", run["repo"])',
     "check-screens prefix: the screen was asked through the rig prefix"),
    ("arm-control: init.js left after a refusal", case_arm_control_launch_path, "for left in (ctl_file, script):", "for left in (ctl_file,):",
     "arm-control launch path: a browser that ignores --init-script: and no init script"),
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
