#!/usr/bin/env python3
"""The walk's planted control, run in a real headless browser (lib/fwx/commands/walk.py, CONTROL_JS).

The other walk tests use a fake `agent-browser`, and a fake cannot show that a style reaches the inside of a title. This one serves a toy
page whose title holds an inner element with a font size of its own (the shape of a real site's `<h1>Student <span class="text-7xl">...`),
launches the real `agent-browser` with the control's init script exactly as `fwx walk ab` does (`--init-script`, a namespace of its own, a
socket dir of its own), and measures the computed font size and weight of every text node of the title.

Cases: the page without the plant reads at its own sizes (so the measurement can tell a plant from none: the negative control of the
others); with the plant every text node of the title computes to the body's size and weight, inner element included; the plant leaves no
attribute on the element (a walker that reads the DOM must not find a self-describing tag) and no more than the inline style.

Seen red against the script before the change (the plant restyled the `h1` element only):
  FAIL: plant: every text node of the title reads at the body's size: got ['16px', '60px'], want ['16px', '16px']
  FAIL: plant: every text node of the title reads at the body's weight: got ['400', '700'], want ['400', '400']
  FAIL: plant: the title carries no attribute that names the tooling: got ['data-fwx-ctl'], want []

Needs `agent-browser` on the PATH and a Chromium-family browser (FWX_TEST_BROWSER, else chromium, google-chrome or chromium-browser on the PATH);
without either it prints `NOT RUN, NOT ARMED` and exits 77. Every process it starts is closed and every temp dir removed in a `finally`.
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx.commands import walk  # noqa: E402

s = helpers.Suite()
PAGE = """<!doctype html><html><head><meta charset="utf-8"></head>
<body style="font-size:16px;font-weight:400"><h1 style="font-size:60px;font-weight:700">Student<br>
<span style="font-size:60px;font-weight:700;color:#06c">and Content Creator</span></h1><p>Body text.</p></body></html>"""
# The title's text nodes, each as its parent element's computed style; the title's attribute names; the body's own style.
MEASURE = """(() => {
  const h = document.querySelector("h1"), w = document.createTreeWalker(h, NodeFilter.SHOW_TEXT), out = [];
  for (let n = w.nextNode(); n; n = w.nextNode()) if (n.textContent.trim()) { const c = getComputedStyle(n.parentElement); out.push([c.fontSize, c.fontWeight]); }
  const b = getComputedStyle(document.body);
  return JSON.stringify({text: out, attrs: h.getAttributeNames(), body: [b.fontSize, b.fontWeight]});
})()"""


def browser_exe():
    return os.environ.get("FWX_TEST_BROWSER") or next((p for p in map(shutil.which, ("chromium", "google-chrome", "chromium-browser")) if p), None)


class Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def measure(ab, exe, sock, url, script=None):
    """The measurement JSON of the toy page in a fresh browser session, launched with the init script when there is one; the session is closed."""
    ns = "fwxctl" + uuid.uuid4().hex[:8]
    common = [ab, "--namespace", ns, "--session", "t", "--executable-path", exe]
    env = dict(os.environ, AGENT_BROWSER_SOCKET_DIR=sock)
    try:
        r = subprocess.run(common + (["--init-script", script] if script else []) + ["open", url], env=env, capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
        if r.returncode:
            return None, "open exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-300:])
        r = subprocess.run(common + ["eval", MEASURE], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        if r.returncode:
            return None, "eval exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-300:])
        out = r.stdout.strip()
        got = json.loads(out)
        return (json.loads(got) if isinstance(got, str) else got), None
    except (subprocess.TimeoutExpired, ValueError) as e:
        return None, "%s: %s" % (type(e).__name__, e)
    finally:
        subprocess.run(common + ["close", "--all"], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, check=False)


def main():
    ab, exe = shutil.which("agent-browser"), browser_exe()
    if not ab:
        s.not_run("agent-browser is not on the PATH, so the plant cannot be run in a real browser")
    if not exe:
        s.not_run("no Chromium-family browser found (set FWX_TEST_BROWSER), so the plant cannot be run in a real browser")
    work = helpers.mkdtemp("fwx-walk-ctl-")
    sock = os.path.join(work, "sock")
    os.makedirs(sock)
    script = os.path.join(work, "init.js")
    with open(script, "w", encoding="utf-8") as f:
        f.write(walk.CONTROL_JS % {"path": json.dumps("/"), "target": json.dumps(walk.TARGET)})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    try:
        plain, why = measure(ab, exe, sock, url)
        if plain is None:
            s.ok("no plant: the browser measured the page", False, why)
            return
        s.eq("no plant: the title's own sizes show (60px inside and out), so the measurement can tell a plant from none",
             [t[0] for t in plain["text"]], ["60px", "60px"])
        s.eq("no plant: the title carries no attribute of the tooling", [a for a in plain["attrs"] if "fwx" in a], [])
        planted, why = measure(ab, exe, sock, url, script)
        if planted is None:
            s.ok("plant: the browser measured the page", False, why)
            return
        size, weight = planted["body"]
        s.eq("plant: the page's body is 16px / 400 (the toy's own)", planted["body"], ["16px", "400"])
        s.eq("plant: every text node of the title reads at the body's size", [t[0] for t in planted["text"]], [size] * len(planted["text"]))
        s.eq("plant: every text node of the title reads at the body's weight", [t[1] for t in planted["text"]], [weight] * len(planted["text"]))
        s.ok("plant: the title has the two text nodes of the toy (the walk looked at both)", len(planted["text"]) == 2, "got %r" % planted["text"])
        s.eq("plant: the title carries no attribute that names the tooling", [a for a in planted["attrs"] if "fwx" in a or "ctl" in a], [])
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
    s.done()
    sys.exit(1 if s.fails else 0)
