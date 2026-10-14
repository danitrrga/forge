#!/usr/bin/env python3
"""S3 of the memory design doc: a session start in the memory project that finds the local Hindsight
(127.0.0.1:9077) not answering waits a bounded time for it, then says so in its systemMessage, so a
session is never silently memory-less. Every other project's session start never looks at it.

Nothing here touches the real Hindsight: cli.MEMORY_HEALTH is pointed at a stand-in HTTP server on an
ephemeral port (live), or at a port that was bound and closed (down), systemctl is replaced by a
stub, and the sync steps, the lock and the project resolver are patched out, so no file is written.

Seen failing on ca32a0e, where session start never looks at the server:
  "down: stdout = '', want one systemMessage naming 'memory is starting'"
  "slow: stdout = '', want ... no message once the stand-in answers after 1 s"  (the late-answer case
  also needs the wait to return at the first answer: asserted by elapsed time below)
"""
import contextlib
import http.server
import io
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import cli, lib  # noqa: E402
import sandbox  # noqa: E402

failures = []
# The settings are a toy file naming the project that waits, never this machine's config/forge.json:
# a copy_engine copy has none. Red there before (M1): 'FAIL down: message: stdout = {"systemMessage":
# "forge -- session-start: memory wait: SystemExit: ! config/forge.json missing -- run bin/forge init"}'.
WAITER, OTHER = "mem-app", "other-app"
TOY = sandbox.mkdtemp("memory-wait-test-")
lib.SETTINGS = os.path.join(TOY, "forge.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {n: True for n in lib.INTEGRATIONS},
               "session_wait": {"project": WAITER, "health": "http://127.0.0.1:9/health", "unit": "toy-memory"}}, fh)
lib.settings.cache_clear()


def check(label, ok, got):
    if not ok:
        failures.append("%s: %s" % (label, got))


class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"healthy"}')

    def log_message(self, *a):
        pass


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run(project, port, wait):
    """(stdout, seconds) of cmd_session_start for a session in `project` with the health URL on `port`."""
    cli.MEMORY_HEALTH = "http://127.0.0.1:%d/health" % port
    cli.MEMORY_WAIT = wait
    cli.MEMORY_POLL = 0.2
    cli.unit_state = lambda: "activating"
    cli.SYNC = []
    lib.resolve_project = lambda path: project
    lib.profiles = lambda skipped=None: {project: {}}
    lib.lock = lambda timeout=20: contextlib.nullcontext()
    out = io.StringIO()
    t = time.monotonic()
    with contextlib.redirect_stdout(out):
        rc = cli.cmd_session_start(None)
    check("exit code", rc == 0, rc)
    return out.getvalue(), time.monotonic() - t


def message(out):
    return json.loads(out)["systemMessage"] if out.strip() else ""


# down, the waiting project: bounded wait, then one plain message with unit state and seconds
port = closed_port()
out, took = run(WAITER, port, 1.0)
msg = message(out)
check("down: message", "memory is starting" in msg and "activating" in msg and "no automatic memory" in msg
      and "hindsight_recall" in msg, "stdout = %r, want one systemMessage naming 'memory is starting', "
      "the unit state 'activating', 'no automatic memory' and 'hindsight_recall'" % out)
check("down: waited", 0.9 <= took < 3.0, "took %.2f s, want a wait of about 1 s" % took)
check("down: seconds in message", "1 s" in msg or "1s" in msg, "message %r names no seconds" % msg)

# live, the waiting project: returns at once, no message
srv = http.server.HTTPServer(("127.0.0.1", 0), Health)
threading.Thread(target=srv.serve_forever, daemon=True).start()
out, took = run(WAITER, srv.server_address[1], 5.0)
check("live: no message", out.strip() == "", "stdout = %r, want nothing" % out)
check("live: at once", took < 1.0, "took %.2f s, want under 1 s" % took)
srv.shutdown()

# comes up during the wait: returns as soon as it answers, no message
port = closed_port()
holder = {}


def late():
    time.sleep(1.0)
    holder["srv"] = http.server.HTTPServer(("127.0.0.1", port), Health)
    holder["srv"].serve_forever()


threading.Thread(target=late, daemon=True).start()
out, took = run(WAITER, port, 6.0)
check("slow: no message", out.strip() == "", "stdout = %r, want no message once the stand-in answers after 1 s" % out)
check("slow: returned at the first answer", 0.8 <= took < 3.0, "took %.2f s, want about 1 s" % took)
if "srv" in holder:
    holder["srv"].shutdown()

# any other project: never looks (a closed port costs no wait and says nothing)
out, took = run(OTHER, closed_port(), 5.0)
check("other project: silent", out.strip() == "", "stdout = %r, want nothing for a project that is not the one in session_wait" % out)
check("other project: no wait", took < 1.0, "took %.2f s" % took)

cli.MEMORY_WAIT = 30  # the shipped cap, which run() lowers for the cases above
budget = getattr(cli, 'memory_budget', lambda elapsed: 'no cli.memory_budget')
# a wait that does not fit: the budget is the hook's 60 s minus the 10 s margin minus what the sync took
check("budget caps at 30", budget(0) == 30, budget(0))
check("budget shrinks with elapsed", budget(35) == 15, budget(35))
check("budget never negative", budget(80) == 0, budget(80))

for m in failures:
    print("FAIL", m)
print("%d failure(s)" % len(failures))
sandbox.cleanup(failures)
sys.exit(1 if failures else 0)
