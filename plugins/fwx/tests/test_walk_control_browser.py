#!/usr/bin/env python3
"""The walk's planted control, run in a real headless browser (lib/fwx/commands/walk.py, CONTROL_JS).

The other walk tests use a fake `agent-browser`, and a fake cannot show that a style reaches the inside of a title. This one serves a toy
page whose title holds an inner element with a font size of its own (the shape of a real site's `<h1>Student <span class="text-7xl">...`),
launches the real `agent-browser` with the control's init script exactly as `fwx walk ab` does (`--init-script`, a namespace of its own, a
socket dir of its own), and measures the computed font size and weight of every text node of the title.

Cases: the page without the plant reads at its own sizes (so the measurement can tell a plant from none: the negative control of the
others); with the plant every text node of the title computes to half the title's own size and normal weight, inner element included; the plant leaves no
attribute on the element (a walker that reads the DOM must not find a self-describing tag) and no more than the inline style.
With a target (`walk.control_code(path, selector)`, what `fwx control new --target` writes) the element the selector names is the one whose
box changes (a paragraph at 40px bold goes to 20px normal), and the title keeps its size and its box: the fault lands inside what the part
changed and not on the first title of the screen.

Seen red against the script before the change (the plant restyled the `h1` element only):
  FAIL: plant: every text node of the title reads at the body's size: got ['16px', '60px'], want ['16px', '16px']
  FAIL: plant: every text node of the title reads at the body's weight: got ['400', '700'], want ['400', '400']
  FAIL: plant: the title carries no attribute that names the tooling: got ['data-fwx-ctl'], want []

Which element is planted when a selector matches several (`querySelector` took the first match, seen or not), and what an invalid
selector reads as. Seen red on head 21222d1 (the plant and the read-back took `document.querySelector`'s first match):
  FAIL: pick off-screen: the plant is on the second match, the one a walker sees: got ['16px', '40px'], want ['40px', '16px']
  (the same for "below the fold" and "closed details")
  FAIL: pick no visible match: nothing is planted: got ['16px', '40px'], want ['40px', '40px']
  FAIL: pick no visible match: the read-back says missing (one plain refusal follows): got 'fwx:16px|400|12x18', want 'fwx:missing'
  FAIL: invalid selector "a'b": the read-back says invalid (one line, no stack): got "eval exited 1: ... SyntaxError: Failed to execute 'querySelector' ... at <anonymous>:6:3", want 'fwx:invalid'
  (the same for "h3:not(" and "")
(three visible siblings: the first is planted, green on both: the positive control of the cases above.)

The fault is relative (round 3): half the element's own font size, 8px at least, weight 400, so it shows on any text. Seen red on head 4e9c350
(the plant set the body's 16px / 400):
  FAIL: plant: every text node of the title reads at half its own size (60px to 30px, inner element included): got ['16px', '16px'], want ['30px', '30px']
  FAIL: target: the element the part changed takes half its own size and normal weight (40px/700 to 20px/400): got ['16px', '400'], want ['20px', '400']
  FAIL: half a paragraph at 18px/300: after the plant the font size and weight: got ['16px', '400'], want ['9px', '400']
  FAIL: half a heading at 36px/700: after the plant the font size and weight: got ['16px', '400'], want ['18px', '400']
  FAIL: half text at 12px: ...: got ['16px', '400'], want ['8px', '400']   (and walk.seen_change does not exist)

Seen red against the script before `--target` (`walk` had no `control_code`; the same toy page):
  FAIL: target: the browser measured the page: AttributeError: module 'fwx.commands.walk' has no attribute 'control_code'

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
<span style="font-size:60px;font-weight:700;color:#06c">and Content Creator</span></h1><p>Body text.</p>
<p class="lede" style="font-size:40px;font-weight:700">What the part changed.</p></body></html>"""
# The title's text nodes, each as its parent element's computed style; the title's attribute names; the body's own style.
MEASURE = """(() => {
  const h = document.querySelector("h1"), w = document.createTreeWalker(h, NodeFilter.SHOW_TEXT), out = [];
  for (let n = w.nextNode(); n; n = w.nextNode()) if (n.textContent.trim()) { const c = getComputedStyle(n.parentElement); out.push([c.fontSize, c.fontWeight]); }
  const b = getComputedStyle(document.body);
  const box = (e) => { const r = e.getBoundingClientRect(), c = getComputedStyle(e); return [c.fontSize, c.fontWeight, Math.round(r.width), Math.round(r.height)]; };
  return JSON.stringify({text: out, attrs: h.getAttributeNames(), body: [b.fontSize, b.fontWeight], h1: box(h), lede: box(document.querySelector(".lede"))});
})()"""


def browser_exe():
    return os.environ.get("FWX_TEST_BROWSER") or next((p for p in map(shutil.which, ("chromium", "google-chrome", "chromium-browser")) if p), None)


# Pages whose selector `.t` matches several elements; the body is 16px / 400, each `.t` is 40px / 700 unless the plant restyles it.
T = '<p class="t" style="font-size:40px;font-weight:700%s">%s</p>'
HEAD = '<!doctype html><html><head><meta charset="utf-8"></head><body style="font-size:16px;font-weight:400;margin:0">'
PAGES = {
    "/": PAGE,
    "/off": HEAD + T % (";position:absolute;left:-9999px", "A") + T % ("", "B") + "</body></html>",
    "/fold": HEAD + '<div style="height:3000px"></div>' + T % ("", "A") + T % (";position:absolute;top:10px;left:10px", "B") + "</body></html>",
    "/details": HEAD + "<details><summary>more</summary>" + T % ("", "A") + "</details>" + T % ("", "B") + "</body></html>",
    "/siblings": HEAD + T % ("", "A") + T % ("", "B") + T % ("", "C") + "</body></html>",
    "/para": HEAD + '<p class="t" style="width:300px;font-size:18px;font-weight:300">Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor.</p></body></html>',
    "/head": HEAD + '<h2 class="t" style="font-size:36px;font-weight:700">A heading</h2></body></html>',
    "/small": HEAD + '<p class="t" style="font-size:12px;font-weight:400">Small print that wraps over a few words of text.</p></body></html>',
    "/tiny": HEAD + '<p class="t" style="font-size:9px;font-weight:400">Tiny print that wraps over a few words of text.</p></body></html>',
    "/none": HEAD + T % (";position:absolute;left:-9999px", "A") + "<details><summary>more</summary>" + T % ("", "B") + "</details></body></html>",
}


class Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], PAGE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def measure(ab, exe, sock, url, script=None, js=MEASURE, raw=False):
    """The measurement JSON of the toy page in a fresh browser session, launched with the init script when there is one; the session is closed."""
    ns = "fwxctl" + uuid.uuid4().hex[:8]
    common = [ab, "--namespace", ns, "--session", "t", "--executable-path", exe]
    env = dict(os.environ, AGENT_BROWSER_SOCKET_DIR=sock)
    try:
        r = subprocess.run(common + (["--init-script", script] if script else []) + ["open", url], env=env, capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
        if r.returncode:
            return None, "open exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-300:])
        r = subprocess.run(common + ["eval", js], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        if r.returncode:
            return None, "eval exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-300:])
        out = r.stdout.strip()
        got = json.loads(out)
        return (got if raw else json.loads(got) if isinstance(got, str) else got), None
    except (subprocess.TimeoutExpired, ValueError) as e:
        return None, "%s: %s" % (type(e).__name__, e)
    finally:
        subprocess.run(common + ["close", "--all"], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, check=False)


def sizes_js(sel):
    """Every match's computed font size, and what the read-back (walk.READ_JS) reads for the selector."""
    return ('(() => JSON.stringify({sizes: Array.from(document.querySelectorAll(%s)).map(e => getComputedStyle(e).fontSize), read: %s}))()'
            % (json.dumps(sel), walk.READ_JS % json.dumps(sel)))


def boxes_js(sel):
    """Each match as [font-size, font-weight, width, height] (whole pixels), the tuple walk.read_target gives the read-back."""
    return ('(() => JSON.stringify(Array.from(document.querySelectorAll(%s)).map(e => { const c = getComputedStyle(e), r = e.getBoundingClientRect(); '
            'return [c.fontSize, c.fontWeight, Math.round(r.width), Math.round(r.height)]; })))()' % json.dumps(sel))


def half_cases(ab, exe, sock, work, base):
    """The fault is relative to the element: half its own font size (8px at least) and normal weight, and the read-back (walk.seen_change) says
    whether a person can see it: the height falls by a quarter or the font size by a third."""
    seen = getattr(walk, "seen_change", None)
    for path, before_want, after_want, visible, why in (
            ("/para", ["18px", "300"], ["9px", "400"], True, "a paragraph at 18px/300"),
            ("/head", ["36px", "700"], ["18px", "400"], True, "a heading at 36px/700"),
            ("/small", ["12px", "400"], ["8px", "400"], True, "text at 12px: the 8px floor is reached, a third off, so it is seen"),
            ("/tiny", ["9px", "400"], ["8px", "400"], False, "text at 9px: the 8px floor leaves 1px, so the read-back refuses it")):
        url = base.rstrip("/") + path
        script = os.path.join(work, "init-half%s.js" % path.replace("/", "-"))
        with open(script, "w", encoding="utf-8") as f:
            f.write(walk.control_code(path, ".t"))
        plain, why1 = measure(ab, exe, sock, url, None, boxes_js(".t"))
        hit, why2 = measure(ab, exe, sock, url, script, boxes_js(".t"))
        if plain is None or hit is None:
            s.ok("half %s: the browser measured the page" % why, False, why1 or why2)
            continue
        b, a = plain[0], hit[0]
        s.eq("half %s: before the plant" % why, b[:2], before_want)
        s.eq("half %s: after the plant the font size and weight" % why, a[:2], after_want)
        if path == "/para":
            s.ok("half %s: its height fell by at least a quarter (%d to %d px)" % (why, b[3], a[3]), a[3] <= 0.75 * b[3], "before %r after %r" % (b, a))
        if seen is None:
            s.ok("half %s: walk.seen_change exists" % why, False, "AttributeError: module 'fwx.commands.walk' has no attribute 'seen_change'")
        else:
            s.eq("half %s: the read-back says visible=%s" % (why, visible), seen(tuple(b), tuple(a)), visible)


def pick_cases(ab, exe, sock, work, base):
    """Which of several matches is planted: the first that is rendered, has a box and shows in the viewport when the screen loads."""
    for path, want, why in (("/off", ["40px", "20px"], "off-screen"), ("/fold", ["40px", "20px"], "below the fold"),
                            ("/details", ["40px", "20px"], "closed details"), ("/siblings", ["20px", "40px", "40px"], "three visible siblings: the first"),
                            ("/none", ["40px", "40px"], "no visible match")):
        url = base.rstrip("/") + path
        script = os.path.join(work, "init-pick%s.js" % path.replace("/", "-"))
        with open(script, "w", encoding="utf-8") as f:
            f.write(walk.control_code(path, ".t"))
        plain, why1 = measure(ab, exe, sock, url, None, sizes_js(".t"))
        hit, why2 = measure(ab, exe, sock, url, script, sizes_js(".t"))
        if plain is None or hit is None:
            s.ok("pick %s: the browser measured the page" % why, False, why1 or why2)
            continue
        label = "pick %s" % why
        if path == "/siblings":
            s.eq("%s: the plant is on the first of three visible matches" % label, hit["sizes"], want)
        elif path == "/none":
            s.eq("%s: nothing is planted" % label, hit["sizes"], want)
            s.eq("%s: the read-back says missing (one plain refusal follows)" % label, hit["read"], "fwx:missing")
        else:
            s.eq("%s: the plant is on the second match, the one a walker sees" % label, hit["sizes"], want)
            s.ok("%s: the read-back reads the visible match too (its font size), not the first" % label, plain["read"].startswith("fwx:40px|700|"), "plain %r" % plain["read"])
            s.ok("%s: and it moved with the plant (40px before, 20px after)" % label, hit["read"].startswith("fwx:20px|400|"), "hit %r" % hit["read"])
    # an invalid selector reads as `invalid`, with no exception on the page
    for sel in ("a'b", "h3:not(", ""):
        got, why = measure(ab, exe, sock, base, None, walk.READ_JS % json.dumps(sel), raw=True)
        s.eq("invalid selector %s: the read-back says invalid (one line, no stack)" % json.dumps(sel), got if got is not None else why, "fwx:invalid")


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
        s.eq("plant: the page's body is 16px / 400 (the toy's own)", planted["body"], ["16px", "400"])
        s.eq("plant: every text node of the title reads at half its own size (60px to 30px, inner element included)", [t[0] for t in planted["text"]], ["30px"] * len(planted["text"]))
        s.eq("plant: every text node of the title reads at normal weight (700 to 400)", [t[1] for t in planted["text"]], ["400"] * len(planted["text"]))
        s.ok("plant: the title has the two text nodes of the toy (the walk looked at both)", len(planted["text"]) == 2, "got %r" % planted["text"])
        s.eq("plant: the title carries no attribute that names the tooling", [a for a in planted["attrs"] if "fwx" in a or "ctl" in a], [])
        # a target: the planted element is the paragraph the part changed, and the title is as the app draws it
        tscript = os.path.join(work, "init-target.js")
        try:
            code = walk.control_code("/", ".lede")
        except AttributeError as e:
            s.ok("target: the browser measured the page", False, "AttributeError: %s" % e)
            return
        with open(tscript, "w", encoding="utf-8") as f:
            f.write(code)
        hit, why = measure(ab, exe, sock, url, tscript)
        if hit is None:
            s.ok("target: the browser measured the page", False, why)
            return
        s.eq("target: the title's size, weight and box are as the app draws them (the plant is not on the title)", hit["h1"], plain["h1"])
        s.eq("target: the element the part changed takes half its own size and normal weight (40px/700 to 20px/400)", hit["lede"][:2], ["20px", "400"])
        s.ok("target: and its box changes (it was %r without the plant)" % (plain["lede"],), hit["lede"][3] < plain["lede"][3], "got %r" % (hit["lede"],))
        pick_cases(ab, exe, sock, work, url)
        half_cases(ab, exe, sock, work, url)
        s.eq("target: no plant, the element is at its own 40px (the measurement can tell a plant from none)", plain["lede"][:2], ["40px", "700"])
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
    s.done()
    sys.exit(1 if s.fails else 0)
