#!/usr/bin/env python3
"""`fwx screenshot` (3.5 U4): lib/fwx/commands/screenshot.py.

Every case goes through `bin/fwx screenshot` against a run that the real `fwx walk up` made in a toy repo (test_walk.py's Scene: the
toy HTTP app, the toy repo, the only-PATH directory of fakes; ORDERS.md rule 10). `agent-browser` is replaced by a fake that
records its argv, writes one PNG per `screenshot` call, and fails on a given screen (FAKE_FAIL_URL, on `open`) or exits 0 without
writing the file (FAKE_NOSHOT_URL). No browser is opened. Every temp dir is made by helpers.mkdtemp and removed at exit.

Seen red before the command existed (python3 tests/test_screenshot.py; `fwx screenshot` was not a command, so every call exited 2):
  FAIL: all captured: exit: got 2, want 0
  FAIL: all captured: no stderr: got "fwx: unknown command: screenshot\n\nusage: fwx <command> [args] ..."
  (and the same for each case: 45 FAILs, the 9 controls "built: ... screenshot.py ... No such file")

Controls: each case also runs on a copy of bin/ and lib/ with one line of screenshot.py changed (`MUTANTS`, each `old` is in the file
exactly once) and must fail with the text shown; the good code passes first (60 checks). The unit's control, "a `screenshot` that
ignores errors", is the first; the FAIL lines the mutants produced:
  ignores errors:      FAIL: one screen fails: exit: got 0, want 1
                       FAIL: one screen fails: the output says why (the browser's own message): 'ok /.../01-a-light-1440.png http://127.0.0 ...'
  exit code only:      FAIL: no file: exit 1 naming /ghost: rc 0 ok /.../01-a-light-1440.png ...
  old file kept:       FAIL: stale: an old PNG at the same name is not taken for a new capture: rc 0 ok ...
  agent-browser direct:FAIL: guard: a URL outside the app is missing (the `walk ab` guard refused it), the other is taken: rc 1 missing https://evil.example.test/x ...
  theme ignored / width not set: FAIL: all captured: the first screen is dark, at 1440 wide: [['viewport', '1440', '900'], ['open', ...
  run.json ignored:    FAIL: run.json screens: exit: got 2, want 0
  zero screens passes: FAIL: no screens anywhere: exit 2 and says so: rc 1 Traceback ...
  77 as missing:       FAIL: no agent-browser: NOT RUN, NOT ARMED and exit 77, not a list of missing screens: rc 1 fwx screenshot: 1 of 1 missing ...
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402
import test_walk as tw  # noqa: E402

ROOT = helpers.ROOT
S0 = "lib/fwx/commands/screenshot.py"

AB_TAIL = """
rest = sys.argv[sys.argv.index("--allowed-domains") + 2:]
if rest[:1] == ["open"] and os.environ.get("FAKE_FAIL_URL") and os.environ["FAKE_FAIL_URL"] in rest[1]:
    sys.stderr.write("page crashed: " + rest[1] + "\\n")
    sys.exit(1)
if rest[:1] == ["screenshot"]:
    cur = [r for r in open(os.environ["FAKE_LOG"]) if '"open"' in r]
    url = json.loads(cur[-1])["argv"][-1] if cur else ""
    if os.environ.get("FAKE_NOSHOT_URL") and os.environ["FAKE_NOSHOT_URL"] in url:
        sys.exit(0)
    open(rest[1], "wb").write(b"\\x89PNG\\r\\n\\x1a\\n" + url.encode())
sys.exit(0)
"""


class Rig:
    """A Scene with the screenshot fake in place of its agent-browser, and a run made by `fwx walk up`."""

    def __init__(self, R):
        self.R = R
        self.sc = tw.Scene()
        tw.script(os.path.join(self.sc.bin, "agent-browser"), tw.FAKE % {"py": tw.PY, "tail": AB_TAIL})
        self.rd = None

    def up(self, S):
        r, o = self.sc.up(self.R)
        if not S.ok("up: armed", r.returncode == 0 and o and o.get("armed") is True, "rc %d: %s %s" % (r.returncode, r.stdout, r.stderr)):
            return False
        self.rd = o["run_dir"]
        self.shots = tw.jfile(os.path.join(self.rd, "run.json"))["shots"]
        return True

    def fwx(self, *args, env=None):
        return self.R(self.sc.repo, *args, env=dict(self.sc.env, **(env or {})))

    def shot(self, *args, env=None):
        return self.fwx("screenshot", "--run", self.rd, *args, env=env)

    def stop(self):
        try:
            if self.rd:
                self.sc.walk(self.R, "down", "--run", self.rd)
        finally:
            self.sc.stop()

    def url(self, path):
        return self.sc.url + path


def screens_arg(rig, *items):
    return json.dumps([{"url": rig.url(p), "theme": t} if t else {"url": rig.url(p)} for p, t in items])


def case_all_captured(R, S):
    """Exit 0, one line per capture, the files where the run keeps its captures (outside the tree), theme and width on the line."""
    rig = Rig(R)
    try:
        if not rig.up(S):
            return
        r = rig.shot("--screens", screens_arg(rig, ("/a", "dark"), ("/b", "light"), ("/c", None)))
        S.eq("all captured: exit", r.returncode, 0)
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        S.eq("all captured: one line per capture", len(lines), 3)
        files = sorted(os.listdir(rig.shots)) if os.path.isdir(rig.shots) else []
        S.eq("all captured: one PNG per screen under the run's captures folder", len(files), 3)
        for ln, path, theme in zip(lines, ("/a", "/b", "/c"), ("dark", "light", "light")):
            S.ok("all captured: line for %s names its URL, theme and width" % path,
                 rig.url(path) in ln and ("theme=" + theme) in ln and "width=1440" in ln, ln)
        for ln in lines:
            p = [w for w in ln.split() if w.startswith(os.sep)]
            S.ok("all captured: the line cites an absolute path that exists and is a PNG", bool(p) and os.path.isfile(p[0])
                 and open(p[0], "rb").read(8) == tw.PNG, ln)
        S.ok("all captured: the files are outside the repo's work tree", all(not f.startswith(rig.sc.repo + os.sep + "ui-walk") for f in files))
        calls = [c["argv"][c["argv"].index("--allowed-domains") + 2:] for c in rig.sc.calls("agent-browser")]
        calls = [c for c in calls if c[:1] != ["cookies"] and c[:1] != ["close"]]
        S.ok("all captured: the first screen is dark, at 1440 wide", ["media", "dark"] in calls and ["viewport", "1440", "900"] in calls, str(calls))
        S.eq("all captured: no stderr", r.stderr, "")
        out = os.path.join(helpers.mkdtemp("fwx-shot-out-"), "pics")
        r2 = rig.shot("--screens", screens_arg(rig, ("/a", "dark")), "--out", out)
        S.ok("out: --out puts the capture there (and makes the folder)", r2.returncode == 0 and len(os.listdir(out)) == 1, "%d %s" % (r2.returncode, r2.stderr))
    finally:
        rig.stop()


def case_one_fails(R, S):
    """THE control: a screen on which the browser fails is named, the others are still taken, exit 1."""
    rig = Rig(R)
    try:
        if not rig.up(S):
            return
        r = rig.shot("--screens", screens_arg(rig, ("/a", None), ("/broken", "dark"), ("/c", None)),
                     env={"FAKE_FAIL_URL": "/broken"})
        S.eq("one screen fails: exit", r.returncode, 1)
        out = r.stdout + r.stderr
        S.ok("one screen fails: the output names /broken", rig.url("/broken") in out, repr(out[:300]))
        S.ok("one screen fails: the output says why (the browser's own message)", "page crashed" in out, repr(out[:300]))
        S.ok("one screen fails: the summary counts it", "1 of 3" in r.stderr, r.stderr)
        S.ok("one screen fails: the screens that worked are named as captured and the broken one is not",
             sum(1 for ln in r.stdout.splitlines() if ln.startswith("ok ")) == 2, r.stdout)
        S.eq("one screen fails: only 2 PNGs", len(os.listdir(rig.shots)), 2)
        # the browser exits 0 but writes no file: also missing
        r = rig.shot("--screens", screens_arg(rig, ("/a", None), ("/ghost", None)), env={"FAKE_NOSHOT_URL": "/ghost"})
        S.ok("no file: exit 1 naming /ghost", r.returncode == 1 and rig.url("/ghost") in r.stdout + r.stderr, "rc %d %s" % (r.returncode, r.stdout + r.stderr))
        # a file left by an earlier run is not this run's capture
        r = rig.shot("--screens", screens_arg(rig, ("/a", None)))
        S.eq("stale: the first capture of /a", r.returncode, 0)
        r = rig.shot("--screens", screens_arg(rig, ("/a", None)), env={"FAKE_NOSHOT_URL": "/a"})
        S.ok("stale: an old PNG at the same name is not taken for a new capture", r.returncode == 1 and rig.url("/a") in r.stdout + r.stderr,
             "rc %d %s" % (r.returncode, r.stdout + r.stderr))
    finally:
        rig.stop()


def case_from_run(R, S):
    """Without --screens: the `screens` of run.json (strings, or {url, theme})."""
    rig = Rig(R)
    try:
        if not rig.up(S):
            return
        r = rig.shot()
        S.ok("no screens anywhere: exit 2 and says so", r.returncode == 2 and "no screens" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
        S.eq("no screens anywhere: nothing was called", rig.sc.calls("agent-browser"), [])
        path = os.path.join(rig.rd, "run.json")
        run = tw.jfile(path)
        run["screens"] = [rig.url("/x"), {"url": rig.url("/y"), "theme": "dark"}]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(run, f)
        r = rig.shot()
        S.eq("run.json screens: exit", r.returncode, 0)
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        S.ok("run.json screens: one line each, in order, the second dark",
             len(lines) == 2 and rig.url("/x") in lines[0] and rig.url("/y") in lines[1] and "theme=dark" in lines[1], r.stdout)
        # --screens wins over run.json
        r = rig.shot("--screens", screens_arg(rig, ("/z", None)))
        S.ok("--screens wins over run.json", r.returncode == 0 and len(r.stdout.splitlines()) == 1 and rig.url("/z") in r.stdout, r.stdout)
        # --screens as a file
        f = os.path.join(helpers.mkdtemp("fwx-shot-in-"), "s.json")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(screens_arg(rig, ("/w", "dark")))
        r = rig.shot("--screens", f)
        S.ok("--screens as a file path", r.returncode == 0 and rig.url("/w") in r.stdout, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        rig.stop()


def case_guards(R, S):
    """It goes through `walk ab`: a URL outside the app is refused there, and shows as missing here; bad input is exit 2."""
    rig = Rig(R)
    try:
        if not rig.up(S):
            return
        r = rig.shot("--screens", json.dumps([{"url": "https://evil.example.test/x"}, {"url": rig.url("/ok")}]))
        S.ok("guard: a URL outside the app is missing (the `walk ab` guard refused it), the other is taken",
             r.returncode == 1 and "evil.example.test" in r.stdout + r.stderr and "refused" in r.stdout + r.stderr
             and len(os.listdir(rig.shots)) == 1, "rc %d %s %s" % (r.returncode, r.stdout, r.stderr))
        opened = [c["argv"][-1] for c in rig.sc.calls("agent-browser") if "open" in c["argv"]]
        S.ok("guard: the browser was never asked to open the foreign URL", all("evil" not in u for u in opened), str(opened))
        for label, arg in (("not JSON", "{nope"), ("a number", "3"), ("empty list", "[]"), ("no url", '[{"theme": "dark"}]'),
                           ("theme unknown", json.dumps([{"url": rig.url("/a"), "theme": "sepia"}]))):
            rig.sc.clear()
            r = rig.shot("--screens", arg)
            S.ok("bad --screens (%s): exit 2, nothing called" % label, r.returncode == 2 and rig.sc.calls("agent-browser") == [], "rc %d %s" % (r.returncode, r.stderr))
        r = rig.fwx("screenshot", "--screens", "[]")
        S.eq("no --run: exit 2", r.returncode, 2)
        r = rig.fwx("screenshot", "--run", "/srv/no-such-run", "--screens", screens_arg(rig, ("/a", None)))
        S.ok("unknown run: exit 2", r.returncode == 2, "rc %d %s" % (r.returncode, r.stderr))
        rig.sc.drop("agent-browser")
        r = rig.shot("--screens", screens_arg(rig, ("/a", None)))
        S.ok("no agent-browser: NOT RUN, NOT ARMED and exit 77, not a list of missing screens",
             r.returncode == 77 and "NOT RUN, NOT ARMED" in r.stderr, "rc %d %s" % (r.returncode, r.stderr))
    finally:
        rig.stop()


CASES = [case_all_captured, case_one_fails, case_from_run, case_guards]
# (name, case, old text, new text, the FAIL text it must produce); each `old` is in screenshot.py exactly once
MUTANTS = [
    ("ignores errors", case_one_fails, "            if why:\n                miss.append", "            if False:\n                miss.append",
     "one screen fails: exit: got 0, want 1"),
    ("trusts the exit code, not the file", case_one_fails, "if not os.path.isfile(stage) or not os.path.getsize(stage):", "if False:",
     "no file: exit 1 naming /ghost"),
    ("keeps the old file", case_one_fails, "            if os.path.lexists(dest):\n                os.remove(dest)\n", "",
     "stale: an old PNG at the same name is not taken for a new capture"),
    ("calls agent-browser itself", case_guards, 'cmd = [sys.executable, os.path.join(walk.ROOT, "bin", "fwx"), "walk", "ab", "--run", run_dir, session]',
     'cmd = ["agent-browser", "--session", session]', "guard: a URL outside the app is missing"),
    ("theme ignored", case_all_captured, 'if sc["theme"] != state["theme"]:', "if False:", "the first screen is dark, at 1440 wide"),
    ("width not set", case_all_captured, 'if not state["sized"]:', "if False:", "the first screen is dark, at 1440 wide"),
    ("run.json screens ignored", case_from_run, 'else run.get("screens")', "else None", "run.json screens: exit"),
    ("no screens is a pass", case_from_run, "if not isinstance(raw, list) or not raw:", "if False:", "no screens anywhere: exit 2 and says so"),
    ("77 flattened to missing", case_guards, "if rc == 77:", "if False:", "no agent-browser: NOT RUN, NOT ARMED and exit 77"),
]


def guarded(case, R, S):
    try:
        case(R, S)
    except Exception as e:  # noqa: BLE001
        S.ok("%s: raised" % case.__name__, False, "%s: %s" % (type(e).__name__, e))


if __name__ == "__main__":
    s = helpers.Suite()
    real = tw.runner(ROOT)
    for case in CASES:
        guarded(case, real, s)
    for name, case, old, new, needle in MUTANTS:
        m = helpers.Suite()
        try:
            tree = tw.copy_tree(ROOT, (S0, old, new))
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        guarded(case, tw.runner(tree), m)
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
        helpers.remove(tree)
    s.done()
