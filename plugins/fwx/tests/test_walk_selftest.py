#!/usr/bin/env python3
"""`fwx walk selftest` (3.5 U8) and the clean-browser key `walk.browser_executable` (lib/fwx/commands/walk.py, lib/fwx/config.py).

Every case goes through `bin/fwx walk` in a toy repo, reusing test_walk.py's Scene (toy repo, toy app that `up` starts and `down`
kills, a fake `agent-browser` that records its argv). The fakes here replace three things: `agent-browser` (a smarter fake that
answers `snapshot` and writes the PNGs `screenshot` is asked for, steered by FAKE_AB_* variables), the toy app's `up` (it serves
the status FAKE_APP_STATUS and, with FAKE_LEAK, leaves a marked `sleep` behind that its `down` does not kill) and the app's server.
No browser is opened. The PATH of the command under test holds only the fakes' directory plus python3 and git (ORDERS.md rule 10).
Every temp dir is made by helpers.mkdtemp and removed at exit; each leaked `sleep` and each app is killed in a `finally`.

Seen red before the subcommand existed (python3 tests/test_walk_selftest.py; `fwx walk selftest` exited 2 with its usage line):
  FAIL: selftest green: exit: got 2, want 0
  FAIL: selftest green: stdout is JSON: got <not JSON: ''>, want an object
  (and the same two lines for each of the red cases; the clean-browser cases failed on `--executable-path` missing from every call)

Controls: each case also runs on a copy of bin/ and lib/ with one line of walk.py or config.py changed (`MUTANTS`, each `old` is in
its file exactly once) and must fail with the text shown; the good code passes first. The FAIL line each mutant produced:
  app answers any status:        FAIL: app not answering: exit: got 0, want 1
  probe outside the rig prefix:  FAIL: prefix: the probe of the url ran through the rig prefix: [['run', '--', 'agent-browser', ...]]
  empty snapshot counted as one: FAIL: empty snapshot: exit: got 0, want 1
  only a bare [ref=eN] counts:   FAIL: real snapshot, agent-browser-snapshot.txt: the selftest counts the 7 elements: got 4, want 7
  blank not compared:            FAIL: screenshot blank: exit: got 0, want 1
  blank taken after open:        FAIL: selftest green: the blank reference is taken before the page is opened: got ['cookies', 'open', 'screenshot', ...]
  down's left not counted:       FAIL: process left: stderr names the check and says '1 process left': fwx walk selftest: FAIL down: down failed:
  down passes with a process:    FAIL: process left: exit: got 0, want 1
  not armed exits 0:             FAIL: not armed, no app_run: exit 2: got 0, want 2
  old selftest.json kept:        FAIL: not armed, no app_run: no selftest.json, and an old one is removed
  --executable-path not added:   FAIL: clean browser: every call carries --executable-path <path>: ...
  key not kept in run.json:      FAIL: clean browser: every call carries --executable-path <path>: ...
  caller may pass the flag:      FAIL: clean browser: the caller passing --executable-path still exits 2: rc 0
  missing file ignored:          FAIL: clean browser missing: armed false: got True, want False
  key type unchecked:            FAIL: clean browser: key 5 is a configuration error (exit 2 naming the key): rc 0
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
import test_walk as W  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
PY = sys.executable
SLEEP = shutil.which("sleep")
NAMES = ["up", "app answers", "snapshot", "capture", "down"]

FAKE_AB = """#!%(py)s
import json, os, struct, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"prog": "agent-browser", "argv": argv}) + "\\n")
state = os.environ["FAKE_AB_STATE"]


def png(tag):
    return (b"\\x89PNG\\r\\n\\x1a\\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1309, 818) + b"\\x08\\x06\\x00\\x00\\x00"
            + b"\\0\\0\\0\\0" + tag)


cmd = next((a for a in argv if a in ("open", "snapshot", "screenshot", "close")), "")
if cmd == "open":
    open(state, "w").write(argv[argv.index("open") + 1])
elif cmd == "close":
    if os.path.exists(state):
        os.remove(state)
elif cmd == "snapshot" and int(os.environ.get("FAKE_AB_EMPTY_FIRST", "0")) > (int(open(state + ".n").read()) if os.path.exists(state + ".n") else 0):
    # a cold dev server: the first N snapshots of the run see a blank page, or FAKE_AB_FIRST_FILE (the login skeleton the app shows first)
    if os.environ.get("FAKE_AB_FIRST_FILE"):
        sys.stdout.write(open(os.environ["FAKE_AB_FIRST_FILE"]).read())
    seen = int(open(state + ".n").read()) if os.path.exists(state + ".n") else 0
    open(state + ".n", "w").write(str(seen + 1))
elif cmd == "snapshot" and os.environ.get("FAKE_AB_SNAPSHOT"):
    sys.stdout.write(open(os.environ["FAKE_AB_SNAPSHOT"]).read())
elif cmd == "snapshot":
    for k in range(int(os.environ.get("FAKE_AB_ELEMENTS", "3"))):
        print('- button "Item %%d" [ref=e%%d]' %% (k, k + 1))
elif cmd == "screenshot":
    out = argv[-1]
    mode = os.environ.get("FAKE_AB_SHOT", "page")
    if not os.path.exists(state) or mode == "blank":
        open(out, "wb").write(png(b"about:blank"))
    elif mode == "empty":
        open(out, "wb").close()
    elif mode == "text":
        open(out, "wb").write(b"not a png")
    else:
        open(out, "wb").write(png(b"the page, drawn: " + open(state).read().encode()))
"""
SRV = """import http.server, os, sys
code = int(os.environ.get("FAKE_APP_STATUS", "200"))


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<h1>toy</h1>"
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""
UP = """import json, os, subprocess, sys
port, pidfile = int(sys.argv[1]), sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(here, "up-ran"), "a").write("x\\n")
if os.environ.get("FWX_WALK_STATE") and not os.environ.get("FAKE_NO_SESSION"):
    json.dump({"cookies": [{"name": "sess", "value": "s3cret", "domain": "localhost", "path": "/"}], "origins": []},
              open(os.environ["FWX_WALK_STATE"], "w"))
p = subprocess.Popen([sys.executable, os.path.join(here, "srv.py"), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)
open(pidfile, "a").write(str(p.pid) + "\\n")
if os.environ.get("FAKE_LEAK"):
    q = subprocess.Popen([os.environ["FAKE_SLEEP"], "300"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    open(os.environ["FAKE_LEAK"], "a").write(str(q.pid) + "\\n")
"""


class Scene(W.Scene):
    """test_walk's Scene with the toy app serving a steerable status, and the smarter agent-browser."""

    def __init__(self, exe=None, config=None, app_run=None, **kw):
        W.Scene.__init__(self, **kw)
        helpers.write(self.repo, "up.py", UP)
        helpers.write(self.repo, "srv.py", SRV)
        W.script(os.path.join(self.bin, "agent-browser"), FAKE_AB % {"py": PY})
        self.leak = os.path.join(self.state, "leak.pids")
        self.env.update({"FAKE_AB_STATE": os.path.join(self.state, "opened"), "FAKE_SLEEP": SLEEP})
        if exe is not None or config or app_run:
            path = os.path.join(self.repo, ".claude", "fwx.json")
            cfg = json.load(open(path))
            cfg["walk"] = dict(config or {})
            if exe is not None:
                cfg["walk"]["browser_executable"] = exe
            if app_run:
                cfg["project"]["app_run"].update(app_run)
            helpers.write(self.repo, ".claude/fwx.json", json.dumps(cfg))

    def selftest(self, R, *extra, env=None, use_dir=True):
        args = ["walk", "selftest", "--repo", self.repo] + (["--dir", self.run_dir_root] if use_dir else []) + list(extra)
        r = R(self.repo, *args, env=dict(self.env, **(env or {})))
        return r, W.obj(r.stdout)

    def stop(self):
        W.Scene.stop(self)
        for p in (open(self.leak).read().split() if os.path.exists(self.leak) else []):
            try:
                os.kill(int(p), 9)
            except OSError:
                pass

    def result_file(self):
        return W.jfile(os.path.join(self.run_dir_root, "ui-walk", "1-1", "selftest.json"))


def by_name(o):
    return {c["name"]: c for c in (o or {}).get("checks", [])}


def red_case(S, label, r, o, sc, failing, message, unreached=()):
    """The shape every red shares: exit 1, the failing check named, its message on stderr and in the JSON, the file says not passed."""
    S.eq("%s: exit" % label, r.returncode, 1)
    S.ok("%s: stderr names the check and says %r" % (label, message), message in r.stderr and failing in r.stderr, r.stderr)
    cs = by_name(o)
    S.eq("%s: five checks, in order" % label, [c["name"] for c in (o or {}).get("checks", [])], NAMES)
    S.eq("%s: passed is false" % label, (o or {}).get("passed"), False)
    S.ok("%s: only %r failed (besides the unreached)" % (label, failing),
         [n for n, c in cs.items() if not c["ok"]] == [failing] + [n for n in unreached], str([(n, c["ok"]) for n, c in cs.items()]))
    S.ok("%s: the message is in the JSON" % label, message in (cs.get(failing) or {}).get("detail", ""), str(cs.get(failing)))
    S.eq("%s: selftest.json is what was printed" % label, sc.result_file(), o)
    return cs


def case_green(R, S):
    sc = Scene()
    try:
        r, o = sc.selftest(R, "--json", "--image-id", "img-1")
        S.eq("selftest green: exit", r.returncode, 0)
        S.ok("selftest green: stdout is JSON", o is not None, "got <not JSON: %r>, want an object" % r.stdout[:80])
        cs = by_name(o)
        S.eq("selftest green: five checks, in order", [c["name"] for c in (o or {}).get("checks", [])], NAMES)
        S.ok("selftest green: all ok, each looked at more than 0", all(c["ok"] and c["looked_at"] > 0 for c in cs.values()) and len(cs) == 5,
             str(cs))
        S.eq("selftest green: passed", (o or {}).get("passed"), True)
        S.eq("selftest green: the image id is carried", (o or {}).get("image_id"), "img-1")
        S.eq("selftest green: selftest.json is what was printed", sc.result_file(), o)
        S.ok("selftest green: the app's up and down ran", os.path.exists(os.path.join(sc.repo, "up-ran")) and os.path.exists(
            os.path.join(sc.repo, "down-ran")))
        S.ok("selftest green: nothing answers at the url after it", not W._answers(sc.port))
        calls = [c["argv"] for c in sc.calls("agent-browser")]
        words = [next((a for a in c if a in ("screenshot", "open", "snapshot", "close", "cookies", "viewport")), "?") for c in calls]
        S.eq("selftest green: the blank reference is taken before the page is opened", words,
             ["cookies", "viewport", "screenshot", "open", "snapshot", "screenshot", "close"])
        S.ok("selftest green: the demo session was set (a cookie call)", any(c[-6:-3] == ["cookies", "set", "sess"] for c in calls), str(calls))
        # without --json: lines, and no image id when none is given; the default folder is under the git common dir
        r, _ = sc.selftest(R, use_dir=False)
        S.eq("selftest lines: exit", r.returncode, 0)
        S.ok("selftest lines: a PASS line per check", all(("PASS %s" % n) in r.stdout for n in NAMES), r.stdout)
        got = W.jfile(os.path.join(sc.repo, ".git", "fwx", "selftest", "ui-walk", "1-1", "selftest.json"))
        S.ok("selftest lines: default folder under the git common dir, and no image_id key", got is not None and "image_id" not in got, str(got))
    finally:
        sc.stop()


def case_red_app(R, S):
    sc = Scene()
    try:
        r, o = sc.selftest(R, "--json", env={"FAKE_APP_STATUS": "500"})
        cs = red_case(S, "app not answering", r, o, sc, "app answers", "app not answering", unreached=("snapshot", "capture"))
        S.ok("app not answering: 500 is named", "500" in (cs.get("app answers") or {}).get("detail", ""), str(cs.get("app answers")))
        S.ok("app not answering: the checks after it say they were not reached, looking at 0",
             all(cs.get(n, {}).get("looked_at") == 0 for n in ("snapshot", "capture")), str(cs))
        S.ok("app not answering: down still ran and left 0", cs.get("down", {}).get("ok") is True and os.path.exists(
            os.path.join(sc.repo, "down-ran")), str(cs.get("down")))
        S.eq("app not answering: no page was opened (only down's close --all reached the binary)",
             [c["argv"][-2:] for c in sc.calls("agent-browser")], [["close", "--all"]])
    finally:
        sc.stop()


def case_red_snapshot(R, S):
    sc = Scene(app_run={"ready_timeout_s": 1})  # the wait for the page is bounded by it: a page that never shows an element fails after 1 s
    try:
        r, o = sc.selftest(R, "--json", env={"FAKE_AB_ELEMENTS": "0"})
        cs = red_case(S, "empty snapshot", r, o, sc, "snapshot", "empty snapshot")
        S.ok("empty snapshot: it counted 0", cs.get("snapshot", {}).get("looked_at") == 0, str(cs.get("snapshot")))
    finally:
        sc.stop()


def case_red_blank(R, S):
    sc = Scene()
    try:
        r, o = sc.selftest(R, "--json", env={"FAKE_AB_SHOT": "blank"})
        cs = red_case(S, "screenshot blank", r, o, sc, "capture", "screenshot is blank")
        S.eq("screenshot blank: it compared two images", cs.get("capture", {}).get("looked_at"), 2)
        for mode, message in (("empty", "screenshot is empty"), ("text", "screenshot is not a PNG")):
            r, o = sc.selftest(R, "--json", env={"FAKE_AB_SHOT": mode})
            S.ok("screenshot %s: exit 1 saying %r" % (mode, message), r.returncode == 1 and message in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        sc.stop()


def case_red_down(R, S):
    sc = Scene()
    try:
        r, o = sc.selftest(R, "--json", env={"FAKE_LEAK": sc.leak})
        cs = red_case(S, "process left", r, o, sc, "down", "1 process left")
        S.ok("process left: down looked at processes", cs.get("down", {}).get("looked_at", 0) > 0, str(cs.get("down")))
        leaked = open(sc.leak).read().split() if os.path.exists(sc.leak) else []
        S.ok("process left: it names the pid", len(leaked) == 1 and leaked[0] in r.stderr, "%s %s" % (leaked, r.stderr))
    finally:
        sc.stop()


def case_not_armed(R, S):
    """No app_run, the browser switch off, no agent-browser, a missing clean browser: exit 2 with the words, never 0 and never 1."""
    exe_missing = "/srv/missing/headless-shell"
    for label, kw, drop in (("no app_run", {"app": False}, False), ("agent_browser off", {"ab": False}, False),
                            ("no agent-browser on the PATH", {}, True), ("browser_executable missing", {"exe": exe_missing}, False)):
        sc = Scene(**kw)
        try:
            if drop:
                sc.drop("agent-browser")
            stale = helpers.write(sc.run_dir_root, "ui-walk/1-1/selftest.json", json.dumps({"passed": True, "checks": []}))
            r, o = sc.selftest(R, "--json")
            S.eq("not armed, %s: exit 2" % label, r.returncode, 2)
            S.ok("not armed, %s: NOT RUN, NOT ARMED" % label, "NOT RUN, NOT ARMED" in r.stderr, r.stderr)
            S.ok("not armed, %s: no selftest.json, and an old one is removed (it would say passed or failed)" % label,
                 sc.result_file() is None and not os.path.exists(stale))
            S.ok("not armed, %s: nothing is left answering" % label, not W._answers(sc.port))
            if label == "browser_executable missing":
                S.ok("not armed, %s: the path is named" % label, "browser_executable %s missing" % exe_missing in r.stderr, r.stderr)
        finally:
            sc.stop()
    # the factory: the image's scripts act as app_run, none is needed (here the image dir is empty: up fails, the check says so)
    sc = Scene(app=False)
    try:
        r, o = sc.selftest(R, "--json", env={"FWX_FACTORY_CONTAINER": "1"})
        S.ok("factory: no app_run is not 'not armed' (the image's scripts are tried)", r.returncode == 1 and "NOT RUN" not in r.stderr and (
            by_name(o).get("up") or {}).get("ok") is False, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        sc.stop()


def case_prefix(R, S):
    """The app answers over the app's network: the probe goes through `app_run.run`. Three probes of the url: `up` asks before it starts the
    app (nothing there), once after (the app answers) and the selftest's own check "app answers"; before 3.5 U3c only the last went through the prefix."""
    sc = Scene(prefix="fakerig run --")
    try:
        r, o = sc.selftest(R, "--json")
        S.ok("prefix: green", r.returncode == 0 and (o or {}).get("passed") is True, "rc %d %s" % (r.returncode, r.stderr))
        probes = [c for c in sc.calls("fakerig") if "-c" in c["argv"] and sc.url in c["argv"]]
        S.ok("prefix: the probe of the url ran through the rig prefix", len(probes) == 3, str([c["argv"][:4] for c in sc.calls("fakerig")]))
    finally:
        sc.stop()


def case_clean_browser(R, S):
    """walk.browser_executable: every call of `ab` carries --executable-path <path>; the caller still cannot pass it; a missing file is
    NOT RUN, NOT ARMED from `up`; a key of the wrong type is a configuration error; unset changes nothing."""
    exe_dir = helpers.mkdtemp("fwx-walk-exe-")
    exe = helpers.write(exe_dir, "headless-shell", "#!/bin/sh\n", 0o755)
    sc = W.Scene()
    cfg_path = os.path.join(sc.repo, ".claude", "fwx.json")
    try:
        cfg = json.load(open(cfg_path))
        cfg["walk"] = {"browser_executable": exe}
        helpers.write(sc.repo, ".claude/fwx.json", json.dumps(cfg))
        r, o = sc.up(R)
        S.ok("clean browser: up arms", r.returncode == 0 and o and o.get("armed") is True, "rc %d %s %s" % (r.returncode, r.stdout, r.stderr))
        if not o:
            return
        rd = o["run_dir"]
        sc.clear()
        for args in (["open", sc.url + "/board"], ["snapshot", "-i"], ["eval", "1+1"]):
            r = sc.walk(R, "ab", "--run", rd, "w1", *args)
            S.eq("clean browser: ab %s: exit" % " ".join(args), r.returncode, 0)
        calls = sc.calls("agent-browser")
        S.ok("clean browser: calls were made (cookies, open, snapshot, eval)", len(calls) >= 4, str(len(calls)))
        for c in calls:
            a = c["argv"]
            S.ok("clean browser: every call carries --executable-path <path>: %s" % " ".join(a[-3:]),
                 "--executable-path" in a and a[a.index("--executable-path") + 1] == exe, str(a))
        sc.clear()
        r = sc.walk(R, "ab", "--run", rd, "w1", "--executable-path", "/usr/bin/other", "snapshot")
        S.ok("clean browser: the caller passing --executable-path still exits 2", r.returncode == 2 and "--executable-path is set by `fwx walk`" in r.stderr,
             "rc %d %s" % (r.returncode, r.stderr))
        S.eq("clean browser: a refused call never reached the binary", sc.calls(), [])
        sc.walk(R, "down", "--run", rd)
    finally:
        sc.stop()
    # a path that is not there: NOT RUN, NOT ARMED, exit 0, armed false, the app never started
    sc = W.Scene()
    try:
        cfg = json.load(open(os.path.join(sc.repo, ".claude", "fwx.json")))
        cfg["walk"] = {"browser_executable": "/srv/missing/headless-shell"}
        helpers.write(sc.repo, ".claude/fwx.json", json.dumps(cfg))
        r, o = sc.up(R)
        S.eq("clean browser missing: exit 0", r.returncode, 0)
        S.eq("clean browser missing: armed false", (o or {}).get("armed"), False)
        S.ok("clean browser missing: says it", "NOT RUN, NOT ARMED: browser_executable /srv/missing/headless-shell missing" in r.stderr, r.stderr)
        S.ok("clean browser missing: the app was not started", not os.path.exists(os.path.join(sc.repo, "up-ran")))
        # a key of the wrong type
        for bad in (5, "", ["x"]):
            cfg["walk"] = {"browser_executable": bad}
            helpers.write(sc.repo, ".claude/fwx.json", json.dumps(cfg))
            r, o = sc.up(R)
            S.ok("clean browser: key %r is a configuration error (exit 2 naming the key)" % (bad,),
                 r.returncode == 2 and "walk.browser_executable" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        sc.stop()
    # unset: no flag at all
    sc = W.Scene()
    try:
        r, o = sc.up(R)
        sc.clear()
        sc.walk(R, "ab", "--run", o["run_dir"], "w1", "snapshot")
        S.ok("clean browser unset: no call carries --executable-path", sc.calls("agent-browser") and all(
            "--executable-path" not in c["argv"] for c in sc.calls("agent-browser")), str(sc.calls()))
        S.eq("clean browser unset: run.json says none", W.jfile(os.path.join(o["run_dir"], "run.json")).get("browser_executable"), None)
        sc.walk(R, "down", "--run", o["run_dir"])
    finally:
        sc.stop()


FIXTURES = os.path.join(ROOT, "tests", "fixtures", "walk")


LOGIN_SKELETON = """- heading "Welcome back" [level=1, ref=e1]
- textbox "Email" [ref=e2]
- textbox "Password" [ref=e3]
- button "Sign in" [ref=e4]
"""
APP_SNAPSHOT = LOGIN_SKELETON.replace("Welcome back", "Dashboard") + '- link "Pipeline" [ref=e5]\n'


def case_cold_start(R, S):
    """3.5 U3f (acceptance D7): `open` returns before a cold dev server has drawn the app, and the first snapshot is blank. The selftest waits
    (it polls the snapshot until it has an element, bounded by app_run.ready_timeout_s, default 30 s) before judging.

    Red before the wait existed (python3 tests/test_walk_selftest.py, FAKE_AB_EMPTY_FIRST=2):
      FAIL: cold start, blank twice: exit: got 1, want 0
      (stderr: FAIL snapshot: empty snapshot: http://127.0.0.1:... opened with the demo session shows no element)
    """
    sc = Scene()
    try:
        r, o = sc.selftest(R, "--json", env={"FAKE_AB_EMPTY_FIRST": "2"})
        S.eq("cold start, blank twice: exit", r.returncode, 0)
        S.eq("cold start, blank twice: the check counts the elements of the snapshot that had some", by_name(o).get("snapshot", {}).get("looked_at"), 3)
        snaps = [c["argv"] for c in sc.calls("agent-browser") if "snapshot" in c["argv"]]
        S.eq("cold start, blank twice: it asked three times", len(snaps), 3)
    finally:
        sc.stop()


def case_login_skeleton(R, S):
    """3.5 U3f (acceptance D7): the snapshot of the login screen has elements too, so "has an element" cannot tell it from the app. With
    `app_run.ready` set (a text that only the logged-in app shows in its snapshot) the check fails on the skeleton, naming the marker, and
    passes on the app; unset, today's behaviour (any element) stays.

    Red before `ready` existed (the skeleton passed): FAIL: login skeleton, ready set: exit: got 0, want 1
    """
    snap = os.path.join(helpers.mkdtemp("fwx-walk-snap-"), "snap.txt")
    for label, text, ready, want in (("login skeleton, ready set", LOGIN_SKELETON, "Dashboard", 1), ("app, ready set", APP_SNAPSHOT, "Dashboard", 0),
                                     ("login skeleton, ready unset", LOGIN_SKELETON, None, 0)):
        open(snap, "w").write(text)
        sc = Scene(app_run={"ready": ready, "ready_timeout_s": 1} if ready else {"ready_timeout_s": 1})
        try:
            r, o = sc.selftest(R, "--json", env={"FAKE_AB_SNAPSHOT": snap})
            S.eq("%s: exit" % label, r.returncode, want)
            if want:
                red_case(S, label, r, o, sc, "snapshot", "ready marker 'Dashboard' is not in the snapshot")
                S.ok("%s: it says how long it waited and how many elements it saw" % label,
                     "1 s" in by_name(o)["snapshot"]["detail"] and "4 element(s)" in by_name(o)["snapshot"]["detail"], str(by_name(o)["snapshot"]))
        finally:
            sc.stop()
    # the login skeleton first, the app a moment later: the wait for the marker, not only for an element, turns it into a pass
    first = os.path.join(os.path.dirname(snap), "first.txt")
    open(first, "w").write(LOGIN_SKELETON)
    open(snap, "w").write(APP_SNAPSHOT)
    sc = Scene(app_run={"ready": "Dashboard", "ready_timeout_s": 10})
    try:
        r, o = sc.selftest(R, "--json", env={"FAKE_AB_SNAPSHOT": snap, "FAKE_AB_FIRST_FILE": first, "FAKE_AB_EMPTY_FIRST": "2"})
        S.eq("skeleton then app, ready set: exit", r.returncode, 0)
        S.eq("skeleton then app, ready set: it asked three times", len([c for c in sc.calls("agent-browser") if "snapshot" in c["argv"]]), 3)
        S.eq("skeleton then app, ready set: the check counts the app's 5 elements", by_name(o).get("snapshot", {}).get("looked_at"), 5)
    finally:
        sc.stop()
    sc = Scene(app_run={"ready": 5})
    try:
        r, o = sc.selftest(R, "--json")
        S.ok("ready of the wrong type: the snapshot check says app_run.ready is not text", r.returncode == 1 and "app_run.ready" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        sc.stop()


def case_real_snapshot(R, S):
    """The selftest counts the elements of what `agent-browser` really prints (3.5 U3d). The two fixtures are real output of agent-browser 0.41.1
    (headless Chromium, `open` then `snapshot` and `snapshot -i`) on a static page of a heading, a link, a text field, a button and a select
    (7 elements; the plain snapshot adds navigation, label and popup rows without a ref). Elements with an attribute carry it inside the same
    brackets as the ref (`[level=1, ref=e1]`, `[expanded=false, ref=e4]`, `[selected, ref=e6]`).

    Red against the pattern as first written, `\\[ref=e\\d+\\]|@e\\d+`, which only matches a bare `[ref=eN]` (4 of the 7):
      FAIL: real snapshot, agent-browser-snapshot.txt: the selftest counts the 7 elements: got 4, want 7
      FAIL: real snapshot, agent-browser-snapshot-i.txt: the selftest counts the 7 elements: got 4, want 7
    """
    for name in ("agent-browser-snapshot.txt", "agent-browser-snapshot-i.txt"):
        sc = Scene()
        try:
            r, o = sc.selftest(R, "--json", env={"FAKE_AB_SNAPSHOT": os.path.join(FIXTURES, name)})
            S.eq("real snapshot, %s: the selftest counts the 7 elements" % name, by_name(o).get("snapshot", {}).get("looked_at"), 7)
            S.eq("real snapshot, %s: exit" % name, r.returncode, 0)
        finally:
            sc.stop()


def case_no_login(R, S):
    """F-9: an app without `app_run.login` has no demo session to check. Seen red on the base (python3 tests/test_walk_selftest.py), the toy app
    leaving no session and declaring no login, which is a healthy app:
      FAIL: no login: exit: got 1, want 0
      FAIL: no login: all five checks ok, each looked at more than 0: ...'snapshot': {'name': 'snapshot', 'looked_at': 0, 'ok': False, 'detail': 'no demo session: .../demo-state.json holds no cookie ...
    The same app declaring a login (`app_run.login`) and still leaving no session is the negative control: it stays a FAIL naming the missing session."""
    sc = Scene()
    try:
        r, o = sc.selftest(R, "--json", env={"FAKE_NO_SESSION": "1"})
        S.eq("no login: exit", r.returncode, 0)
        cs = by_name(o)
        S.ok("no login: all five checks ok, each looked at more than 0", len(cs) == 5 and all(c["ok"] and c["looked_at"] > 0 for c in cs.values()), str(cs))
        S.ok("no login: the snapshot check says it opened the app without a demo session, and why",
             "no app_run.login" in (cs.get("snapshot") or {}).get("detail", "") and "without a demo session" in cs["snapshot"]["detail"], str(cs.get("snapshot")))
        calls = [c["argv"] for c in sc.calls("agent-browser")]
        S.ok("no login: no cookie was set and the page was opened and captured", not any("cookies" in c for c in calls) and any("open" in c for c in calls)
             and sum(1 for c in calls if "screenshot" in c) == 2, str(calls))
    finally:
        sc.stop()
    sc = Scene(app_run={"login": "python3 login.py"})
    try:
        r, o = sc.selftest(R, "--json", env={"FAKE_NO_SESSION": "1"})
        cs = red_case(S, "login declared, no session", r, o, sc, "snapshot", "no demo session", unreached=("capture",))
        S.ok("login declared, no session: it looked at 0 and says where the session should be", (cs.get("snapshot") or {}).get("looked_at") == 0 and "holds no cookie" in (
            cs.get("snapshot") or {}).get("detail", ""), str(cs.get("snapshot")))
        S.ok("login declared, no session: no page was opened", not any("open" in c["argv"] for c in sc.calls("agent-browser")), str(sc.calls("agent-browser")))
    finally:
        sc.stop()
    sc = Scene(app_run={"login": "python3 login.py"})
    try:
        r, o = sc.selftest(R, "--json")
        S.eq("login declared, with a session: exit", r.returncode, 0)
        S.eq("login declared, with a session: the session is used (a cookie call)", any("cookies" in c["argv"] for c in sc.calls("agent-browser")), True)
    finally:
        sc.stop()
    # a malformed `login`: an empty text declares none (forge refuses it, the plugin reads it as no login); anything else that is set declares one, so
    # a session is demanded (fail closed)
    for value, code in (("", 0), (5, 1)):
        sc = Scene(app_run={"login": value})
        try:
            r, o = sc.selftest(R, "--json", env={"FAKE_NO_SESSION": "1"})
            S.eq("login %r, no session: exit" % (value,), r.returncode, code)
        finally:
            sc.stop()


CASES = [case_green, case_red_app, case_red_snapshot, case_cold_start, case_login_skeleton, case_real_snapshot, case_red_blank, case_red_down, case_not_armed, case_prefix, case_clean_browser, case_no_login]

WALK = "lib/fwx/commands/walk.py"
CONFIG = "lib/fwx/config.py"
# (name, case, file, old text, new text, the FAIL text it must produce); each `old` is in its file exactly once.
MUTANTS = [
    ("app answers: any status", case_red_app, WALK, 'if got != "200":', "if False:", "app not answering: exit: got 0, want 1"),
    ("app answers: probe outside the prefix", case_prefix, WALK, 'argv = prefix + ["python3" if prefix else sys.executable, "-c", PROBE, url]',
     'argv = [sys.executable, "-c", PROBE, url]', "prefix: the probe of the url ran through the rig prefix"),
    ("snapshot: empty counted as one", case_red_snapshot, WALK, "return sum(1 for line", "return 1 + sum(1 for line", "empty snapshot: exit: got 0, want 1"),
    ("snapshot: no wait for the page", case_cold_start, WALK, "while True:  # settle", "while False:  # settle", "cold start, blank twice: exit"),
    ("snapshot: ready marker unchecked", case_login_skeleton, WALK, 'if n and ready and ready not in got["snapshot"]:', "if False:", "login skeleton, ready set: exit"),
    ("snapshot: wait for the marker dropped", case_login_skeleton, WALK, "(not ready or ready in out)", "(not ready or True)", "skeleton then app, ready set: exit"),
    ("snapshot: ready type unchecked", case_login_skeleton, WALK, "not isinstance(ready, str)", "False", "ready of the wrong type"),
    ("snapshot: only a bare [ref=eN] counts", case_real_snapshot, WALK, 're.search(r"\\bref=e\\d+\\b|@e\\d+", line)', 're.search(r"\\[ref=e\\d+\\]|@e\\d+", line)',
     "the selftest counts the 7 elements"),
    ("capture: blank not compared", case_red_blank, WALK, "elif b[2] == p[2]:", "elif False:", "screenshot blank: exit: got 0, want 1"),
    ("capture: blank taken after open", case_green, WALK, '(("blank", ["screenshot", blank]), ("open", ["open", url]),',
     '(("open", ["open", url]), ("blank", ["screenshot", blank]),', "selftest green: the blank reference is taken before the page is opened"),
    ("down: left not counted", case_red_down, WALK, 'left = len(res["left"])', "left = 0", "process left: stderr names the check and says '1 process left'"),
    ("down: left passes", case_red_down, WALK, 'rec("down", res["looked"], detail, not left and not code)', 'rec("down", res["looked"], detail, True)',
     "process left: exit: got 0, want 1"),
    ("not armed: exit 0", case_not_armed, WALK, "return 2  # `up` said why on stderr: NOT RUN, NOT ARMED, and 2 is not green", "return 0",
     "not armed, no app_run: exit 2: got 0, want 2"),
    ("not armed: stale result kept", case_not_armed, WALK, "os.remove(result_file)", "pass", "an old one is removed"),
    ("clean browser: flag not added", case_clean_browser, WALK, 'common += ["--executable-path", run["browser_executable"]]', "pass",
     "clean browser: every call carries --executable-path"),
    ("clean browser: key not stored", case_clean_browser, WALK, '"hosts": hosts, "browser_executable": exe,', '"hosts": hosts, "browser_executable": None,',
     "clean browser: every call carries --executable-path"),
    ("clean browser: caller may pass it", case_clean_browser, WALK, '"--init-script", "--executable-path")', '"--init-script")',
     "clean browser: the caller passing --executable-path still exits 2"),
    ("clean browser: missing file ignored", case_clean_browser, WALK, "if exe and not os.path.isfile(exe):", "if False:", "clean browser missing: armed false"),
    ("clean browser: key type unchecked", case_clean_browser, CONFIG, "if exe is not None and (not isinstance(exe, str) or not exe.strip()):", "if False:",
     "clean browser: key 5 is a configuration error"),
    ("login: every app needs a session", case_no_login, WALK, 'return bool((config.load(run["repo"])["project"].get("app_run") or {}).get("login"))', "return True",
     "no login: exit: got 1, want 0"),
    ("login: an empty text is a login", case_no_login, WALK, 'return bool((config.load(run["repo"])["project"].get("app_run") or {}).get("login"))',
     'return "login" in (config.load(run["repo"])["project"].get("app_run") or {})', "login '', no session: exit"),
    ("login: only a text is a login", case_no_login, WALK, 'return bool((config.load(run["repo"])["project"].get("app_run") or {}).get("login"))',
     'return isinstance((config.load(run["repo"])["project"].get("app_run") or {}).get("login"), str)', "login 5, no session: exit"),
    ("login: no app has a login", case_no_login, WALK, 'return bool((config.load(run["repo"])["project"].get("app_run") or {}).get("login"))', "return False",
     "login declared, no session: exit: got 0, want 1"),
]
if __name__ == "__main__":
    W.CWD[0] = helpers.mkdtemp("fwx-walk-cwd-")
    W.FAKE_DIR_FOR[0] = helpers.mkdtemp("fwx-walk-bin-")
    real = W.runner(ROOT)
    for case in CASES:
        W.guarded(case, real, s)
    for name, case, path, old, new, needle in MUTANTS:
        m = helpers.FirstFail(lambda f, needle=needle: needle in f)  # the control reads one FAIL: the case stops at it
        try:
            tree = W.copy_tree(ROOT, (path, old, new))
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        m.run(W.guarded, case, W.runner(tree), m)
        W.stop_scenes()
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
        helpers.remove(tree)
    s.done()
