"""Oracle for ui-states-01 (authored). Imports the shop package from the repo and renders the orders section through
shop.views.render_orders(customer_id, transport) with stub transports (the same seam the existing tests use): a 200
with two orders, a 200 with an empty list, a refused connection, a timeout, and 500 / 503 answers. The empty list must
render the empty state and no error; every failure must render an error state (role="alert" or wording such as
"couldn't", "unable", "failed", "error", "unavailable", "try again") and must not render the empty state (the sentence
"You have no orders yet." or an element with an "empty" class) or crash.
The repo's own tests must still pass.

What it cannot see: how the message reads to a customer, whether a retry link works, styling, and what the page does
in a browser; it judges the HTML the function returns. It recognises an error state by role="alert" or by any of a
list of error words, so an error message using none of them (or an empty state that happens to use one) is misread.
"""
import html
import json
import os
import re
import subprocess
import sys
import traceback

ORDERS = [
    {"id": "A-2077", "placed_on": "20 Oct 2026", "total": "€18.50", "status": "processing"},
    {"id": "A-2051", "placed_on": "30 Sep 2026", "total": "€64.00", "status": "delivered"},
]
ERROR_WORDS = re.compile(r"couldn.?t|could not|can.?t|cannot|unable|fail|error|problem|went wrong|unavailable|"
                         r"not available|try again|retry|reload|refresh|out of service|outage", re.I)
EMPTY_SENTENCE = "you have no orders yet"


def _text(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _kind(markup):
    """Which states the markup shows: a set of 'error', 'empty', 'list'."""
    text = _text(markup)
    found = set()
    if re.search(r"""role\s*=\s*["']?alert""", markup, re.I) or ERROR_WORDS.search(text):
        found.add("error")
    if EMPTY_SENTENCE in text.lower() or re.search(r"""class\s*=\s*["'][^"']*\bempty\b""", markup, re.I):
        found.add("empty")
    if any(o["id"] in text for o in ORDERS):
        found.add("list")
    return found, text


def _status(code, payload):
    def transport(method, path):
        return code, json.dumps(payload)
    return transport


def _raises(exc):
    def transport(method, path):
        raise exc
    return transport


def check(repo, message):
    sys.path.insert(0, repo)
    out = []
    try:
        from shop import views
    except Exception as e:  # noqa: BLE001 - any import failure is the finding
        return [{"id": "imports", "passed": False, "evidence": "shop.views does not import: %r" % e}]

    def render(transport):
        try:
            markup = views.render_orders("c-1001", transport)
        except Exception as e:  # noqa: BLE001
            return None, "render_orders raised %s: %s" % (type(e).__name__, e)
        if not isinstance(markup, str):
            return None, "render_orders returned %r, not HTML" % type(markup).__name__
        return markup, None

    m, err = render(_status(200, {"orders": ORDERS}))
    k, text = _kind(m or "")
    out.append({"id": "lists-orders", "passed": err is None and k == {"list"},
                "evidence": err or "states shown: %s; text: %s" % (sorted(k), text[:120])})
    m, err = render(_status(200, {"orders": []}))
    k, text = _kind(m or "")
    out.append({"id": "empty-state-only-when-no-orders", "passed": err is None and k == {"empty"},
                "evidence": err or "200 with no orders shows %s; text: %s" % (sorted(k), text[:120])})
    for cid, cases in (("error-state-when-unreachable", [("connection refused", _raises(ConnectionRefusedError("refused"))),
                                                         ("timeout", _raises(TimeoutError("timed out")))]),
                       ("error-state-on-error-status", [("HTTP 500", _status(500, {"error": "boom"})),
                                                        ("HTTP 503", _status(503, {"error": "maintenance"}))])):
        bad = []
        for label, tr in cases:
            m, err = render(tr)
            if err:
                bad.append("%s: %s" % (label, err))
                continue
            k, text = _kind(m)
            if "error" not in k or "empty" in k or "list" in k:
                bad.append("%s shows %s: %s" % (label, sorted(k) or "no recognisable state", text[:100]))
        out.append({"id": cid, "passed": not bad,
                    "evidence": "; ".join(bad) or "every case renders an error state and no empty state"})
    try:
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-t", "."], cwd=repo, capture_output=True,
                           text=True, timeout=40, env={k: v for k, v in os.environ.items() if not k.startswith("PYTHON")})
        tail = (r.stderr.strip().splitlines() or ["no output"])[-1]
        ran = re.search(r"Ran (\d+) test", r.stderr)
        out.append({"id": "repo-tests-pass", "passed": r.returncode == 0 and bool(ran) and int(ran.group(1)) > 0,
                    "evidence": "python3 -m unittest: %s (%s)" % (tail, ran.group(0) if ran else "no tests ran")})
    except subprocess.TimeoutExpired:
        out.append({"id": "repo-tests-pass", "passed": False, "evidence": "the test run timed out"})
    except Exception:  # noqa: BLE001
        out.append({"id": "repo-tests-pass", "passed": False, "evidence": traceback.format_exc(limit=1)})
    return out
