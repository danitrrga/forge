#!/usr/bin/env python3
"""Part 1.1 (consent window), unit U2: the `omarchy` adapter, scripts/consent/omarchy. The security part is the
deadline (the hook's own timeout kills the call and fails closed, so an adapter that waits forever turns a
forgotten window into a hung session) and "exit 0 only on yes"; the window (`omarchy --show`, UI) is not tested
beyond the one mapping that decides yes.

Nothing here opens a window: the launcher (`omarchy-launch-floating-terminal-with-presentation`) and `gum` are
fakes on PATH, and the adapter is copied into a toy forge root whose config/gateway.json has timeout_s 4.

  (a) a launcher that never answers: the adapter exits non-zero (4) before timeout_s, and its launcher is gone
  (b) the launcher writes yes: exit 0          (c) it writes no: exit 1; anything but yes (garbage) is not 0 either
  (d) no WAYLAND_DISPLAY / no gum / no launcher / unreadable gateway.json: exit 3 at once (under 1 s), reason on stderr
  (e) the viewer: gum confirm is asked with --default=false and a --timeout; gum 0 -> yes, gum 1 / timeout (124) /
      anything else -> no, exit 130; control characters in the request are shown escaped, never raw

Seen failing before the adapter existed (the test run on the tree without scripts/consent/omarchy):
  FAIL adapter exists -- adapter missing: .../scripts/consent/omarchy   (1 FAIL, rc=1)
Negative controls, each a one-line mutation of the finished adapter (FAIL counts of this file):
  answer == "yes" -> always 0 (3): "c: no: exit 1 -- rc=0 after 0.2 s"
  WAYLAND_DISPLAY check removed (2): "d: no WAYLAND_DISPLAY: exit 3 ... -- rc=4 after 2.05 s"
  gum --default=false -> true (1): "confirm --default=true --timeout=1s Run it?"
  viewer writes yes whatever gum said (4): "e: gum exit 1 writes no ... -- result='yes'"
  launcher not killed at the deadline (1): "a: the launcher it started is not left running -- alive=[True]"
Control, the finished adapter with its wait-loop deadline taken out (`while time.monotonic() < deadline:` ->
`while True:`), case (a) run against that copy: red on time, as designed --
  FAIL (the control, expected): still running after 6.0 s (timeout_s 4), rc=None -- the harness killed it
and the same harness is green on the real adapter (exit 4 after 2.0 s). The control is asserted inside this file."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
ADAPTER = os.path.join(os.path.dirname(HERE), "scripts", "consent", "omarchy")
BAD = []


def need(ok, what, detail=""):
    print(("PASS " if ok else "FAIL ") + what + ("" if ok or not detail else " -- " + detail))
    if not ok:
        BAD.append(what)


# The fake launcher: it gets what the real one gets, one string, the viewer command line. It checks the shape
# (`... omarchy --show REQUEST RESULT`, the request readable), then answers as FAKE_ANSWER says: a word to write
# to RESULT, or `never` to sleep (the pid is recorded so the test can clean up and check the adapter kills it).
LAUNCHER = """#!/usr/bin/env python3
import os, shlex, sys, time
argv = shlex.split(sys.argv[1])
i = argv.index("--show")
request, result = argv[i + 1], argv[i + 2]
open(request).read()
open(os.environ["FAKE_LOG"], "a").write("launched pid=%d\\n" % os.getpid())
answer = os.environ["FAKE_ANSWER"]
if answer == "never":
    time.sleep(8)
else:
    open(result, "w").write(answer)
"""
GUM = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
exit "${FAKE_GUM_RC:-0}"
"""


def world(tmp, timeout_s=4, gateway=True):
    root = os.path.join(tmp, "forge")
    os.makedirs(os.path.join(root, "scripts", "consent"))
    os.makedirs(os.path.join(root, "config"))
    adapter = os.path.join(root, "scripts", "consent", "omarchy")
    shutil.copy(ADAPTER, adapter)
    if gateway:
        with open(os.path.join(root, "config", "gateway.json"), "w") as f:
            json.dump({"consent": {"adapter": "omarchy", "timeout_s": timeout_s, "rules": []}}, f)
    return adapter


def fakebin(tmp, launcher=True, gum=True):
    # PATH is this directory and nothing else (python3 is linked in for the fakes' shebang): the real gum and the
    # real launcher live in /usr/bin, and a missing fake must mean "missing", never "the real window opens".
    d = os.path.join(tmp, "bin")
    os.makedirs(d, exist_ok=True)
    if not os.path.exists(os.path.join(d, "python3")):
        os.symlink(sys.executable, os.path.join(d, "python3"))
    for name, body, on in (("omarchy-launch-floating-terminal-with-presentation", LAUNCHER, launcher),
                           ("gum", GUM, gum)):
        if on:
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
    return d


def request(tmp, **over):
    r = {"project": "toy", "cwd": "/tmp/x", "session_id": "s", "command": "git push origin main",
         "what": "Push to a production branch: ship it", "changes": ["1 commit: abc123 fix"],
         "risks": ["What is pushed goes live"], "requested_at": "t"}
    r.update(over)
    p = os.path.join(tmp, "req.json")
    with open(p, "w") as f:
        json.dump(r, f)
    os.chmod(p, 0o600)
    return p


def run(adapter, req, tmp, answer="never", wayland="wayland-0", launcher=True, gum=True, limit=12):
    """-> (rc, seconds, stderr); rc None when the harness had to kill it after `limit` seconds."""
    env = {"PATH": fakebin(tmp, launcher, gum), "FAKE_ANSWER": answer,
           "FAKE_LOG": os.path.join(tmp, "log"), "XDG_RUNTIME_DIR": tmp, "HOME": tmp}
    if wayland:
        env["WAYLAND_DISPLAY"] = wayland
    t0 = time.monotonic()
    p = subprocess.Popen([sys.executable, "-I", adapter, req], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        _, err = p.communicate(timeout=limit)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        _, err = p.communicate()
        rc = None
    return rc, time.monotonic() - t0, err


def launcher_pids(tmp):
    try:
        return [int(l.split("pid=")[1]) for l in open(os.path.join(tmp, "log")) if l.startswith("launched")]
    except OSError:
        return []


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def reap(tmp):
    for pid in launcher_pids(tmp):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def case_a(adapter, tmp):
    """-> (rc, seconds, stderr, ok): ok when the adapter exited non-zero before timeout_s=4."""
    rc, secs, err = run(adapter, request(tmp), tmp, limit=6)
    return rc, secs, err, rc is not None and rc != 0 and secs < 4


def main():
    if not os.path.exists(ADAPTER):
        need(False, "adapter exists", "adapter missing: " + ADAPTER)
        return
    with open(ADAPTER) as f:
        src = f.read()
    tmps = []

    def tmpdir():
        d = tempfile.mkdtemp(prefix="consent-adapter-")
        tmps.append(d)
        return d

    try:
        # (a) never answers
        t = tmpdir()
        rc, secs, err, ok = case_a(world(t), t)
        need(ok, "a: a launcher that never answers: non-zero before timeout_s",
             "rc=%s after %.1f s, stderr=%r" % (rc, secs, err.strip()[:200]))
        need(rc == 4, "a: the exit code is 4 (timeout)", "rc=%s" % rc)
        time.sleep(0.2)
        pids = launcher_pids(t)
        need(len(pids) == 1 and not alive(pids[0]), "a: the launcher it started is not left running",
             "pids=%s alive=%s" % (pids, [alive(p) for p in pids]))
        left = [n for n in os.listdir(t) if n.startswith("forge-consent-")]
        need(not left, "a: the private directory is removed", "left=%s" % left)
        reap(t)

        # control: the same case against a copy with the deadline taken out must be red on time
        t = tmpdir()
        mutant = world(t)
        needle = "while time.monotonic() < deadline:"
        need(needle in src, "control: the wait loop is where the control expects it", needle)
        with open(mutant, "w") as f:
            f.write(src.replace(needle, "while True:"))
        rc2, secs2, _, ok2 = case_a(mutant, t)
        need(not ok2 and rc2 is None,
             "control: without the deadline case (a) is red on time (still running after %.1f s, timeout_s 4)" % secs2,
             "rc=%s after %.1f s" % (rc2, secs2))
        reap(t)

        # (b) yes, (c) no, and anything else
        for answer, want, label in (("yes", 0, "b: yes"), ("no", 1, "c: no"), ("yes\n", 0, "b: yes with a newline"),
                                    ("YES", 1, "c: not exactly yes (YES) is not a yes"),
                                    ("", 4, "c: an empty result is not a yes (and not an answer: it waits, then times out)"),
                                    ("garbage", 1, "c: garbage is not a yes")):
            t = tmpdir()
            rc, secs, err = run(world(t), request(t), t, answer=answer, limit=6)
            need(rc == want and secs < 3, label + ": exit %d" % want, "rc=%s after %.1f s, stderr=%r" % (rc, secs, err[:200]))
            reap(t)

        # (d) cannot ask: exit 3 at once
        for label, kw, mk in (("d: no WAYLAND_DISPLAY", {"wayland": ""}, {}),
                              ("d: no gum", {"gum": False}, {}),
                              ("d: no launcher", {"launcher": False}, {}),
                              ("d: no gateway.json", {}, {"gateway": False})):
            t = tmpdir()
            rc, secs, err = run(world(t, **mk), request(t), t, limit=6, **kw)
            need(rc == 3 and secs < 1 and err.strip(), label + ": exit 3 in under 1 s, reason on stderr",
                 "rc=%s after %.2f s, stderr=%r" % (rc, secs, err[:200]))
            need(not launcher_pids(t), label + ": nothing was launched")
        t = tmpdir()
        rc, secs, err = run(world(t), os.path.join(t, "nope.json"), t, limit=6)
        need(rc == 3 and secs < 1, "d: a request file that is not there: exit 3", "rc=%s %r" % (rc, err[:200]))
        # (e) the viewer, with a fake gum; stdin is not a tty here, so no input is drained
        for gum_rc, want in ((0, "yes"), (1, "no"), (124, "no"), (130, "no"), (2, "no")):
            t = tmpdir()
            adapter = world(t)
            req, res = request(t, command="echo \x1b[2J\x1b]0;pwned\x07 hi"), os.path.join(t, "res")
            env = {"PATH": fakebin(t), "FAKE_LOG": os.path.join(t, "log"), "FAKE_GUM_RC": str(gum_rc)}
            p = subprocess.run([sys.executable, "-I", adapter, "--show", req, res], env=env, capture_output=True,
                               text=True, timeout=10, stdin=subprocess.DEVNULL)
            got = open(res).read() if os.path.exists(res) else None
            need(got == want and p.returncode == 130, "e: gum exit %d writes %s and the viewer exits 130" % (gum_rc, want),
                 "result=%r rc=%s" % (got, p.returncode))
            if gum_rc == 0:
                args = open(os.path.join(t, "log")).read()
                need("confirm" in args and "--default=false" in args and "--timeout=" in args,
                     "e: gum confirm --default=false --timeout=...", args.strip())
                need("\x1b" not in p.stdout and "\x07" not in p.stdout, "e: control characters are not printed raw",
                     repr(p.stdout[:200]))
                need("echo" in p.stdout and "Push to a production branch" in p.stdout
                     and "What is pushed goes live" in p.stdout and "abc123" in p.stdout,
                     "e: what, command, changes and risks are on screen", p.stdout[:300])
    finally:
        for d in tmps:
            reap(d)
            shutil.rmtree(d, ignore_errors=True)


main()
print("%d FAIL" % len(BAD) if BAD else "all passed")
sys.exit(1 if BAD else 0)
