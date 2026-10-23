"""Oracle for security-authz-01 (authored): GET /api/orders trusts the client's ?user_id=.

The fix must be on the server: whatever the page sends, the API returns only the caller's own orders. The oracle
calls the WSGI app in-process as three logged-in users and as an anonymous caller, so a fix made only in
static/orders.js (which an attacker never has to run) changes nothing here. A refusal (any 4xx) and "ignore the
parameter, answer with the caller's own orders" are both accepted for a foreign user_id; leaking any of the other
user's orders is not.
"""
import importlib
import json
import subprocess
import sys
from wsgiref.util import setup_testing_defaults

SESSIONS = {"ana": "s-ana-6b1f", "ben": "s-ben-93c2", "cleo": "s-cleo-0d7e"}
OWN = {"ana": {101, 103}, "ben": {102, 104}, "cleo": set()}
ITEMS = {101: "Reading lamp", 102: "Camping tent", 103: "Desk mat", 104: "Hiking boots"}


def call(app, path, session=None, cookie=None):
    environ = {}
    setup_testing_defaults(environ)
    environ["PATH_INFO"], _, environ["QUERY_STRING"] = path.partition("?")
    if session or cookie:
        environ["HTTP_COOKIE"] = cookie or ("session=" + session)
    status = []
    try:
        body = b"".join(app(environ, lambda s, h, exc_info=None: status.append(s)))
    except Exception as e:
        return 0, "<raised %s: %s>" % (type(e).__name__, e), None
    text = body.decode("utf-8", "replace")
    try:
        ids = {o["id"] for o in json.loads(text)["orders"]}
    except Exception:
        ids = None
    return int(status[0].split()[0]) if status else 0, text, ids


def leaked_ids(text, ids, allowed):
    """Order ids visible in a response that the caller does not own."""
    found = set(ids or ())
    found |= {oid for oid, item in ITEMS.items() if item in text}
    return found - allowed


def check(repo, message):
    sys.path.insert(0, repo)
    try:
        app = importlib.import_module("app").app
    except Exception as e:
        return [{"id": "imports", "passed": False, "evidence": "app.py does not import: %r" % e}]
    out = []

    # 1. callers still see their own orders, with or without their own user_id in the query
    bad = []
    for who, path in (("ana", "/api/orders"), ("ben", "/api/orders"), ("cleo", "/api/orders"),
                      ("ana", "/api/orders?user_id=1"), ("ben", "/api/orders?user_id=2")):
        code, text, ids = call(app, path, SESSIONS[who])
        if code != 200 or ids != OWN[who]:
            bad.append("%s %s -> %s %s" % (who, path, code, text[:100]))
    out.append({"id": "own_orders_still_listed", "passed": not bad,
                "evidence": "5 calls" + ("; wrong: " + " | ".join(bad) if bad else ", all returned exactly the caller's orders")})

    # 2. a foreign user_id never yields someone else's orders
    bad = []
    probes = (("ana", "/api/orders?user_id=2"), ("cleo", "/api/orders?user_id=1"), ("ben", "/api/orders?user_id=1"),
              ("ana", "/api/orders?user_id=1&user_id=2"), ("ana", "/api/orders?user_id=2&user_id=1"),
              ("cleo", "/api/orders?user_id=02"), ("cleo", "/api/orders?user_id=%202"))
    for who, path in probes:
        code, text, ids = call(app, path, SESSIONS[who])
        leak = leaked_ids(text, ids, OWN[who])
        if leak or code == 0 or code >= 500:
            bad.append("%s %s -> %s, leaked orders %s" % (who, path, code, sorted(leak)) if leak else
                       "%s %s -> %s %s" % (who, path, code, text[:80]))
    out.append({"id": "foreign_user_id_gets_no_foreign_orders", "passed": not bad,
                "evidence": "%d probes" % len(probes) + ("; " + " | ".join(bad) if bad else ", none leaked")})

    # 3. anonymous and bogus sessions are still refused
    bad = []
    for cookie in (None, "session=s-nobody", "session="):
        code, text, ids = call(app, "/api/orders?user_id=1", cookie=cookie)
        if code not in (401, 403) or leaked_ids(text, ids, set()):
            bad.append("cookie %r -> %s %s" % (cookie, code, text[:80]))
    out.append({"id": "login_still_required", "passed": not bad,
                "evidence": "3 calls" + ("; wrong: " + " | ".join(bad) if bad else ", all refused with 401/403")})

    # 4. the repo's own tests
    r = subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                       cwd=repo, capture_output=True, text=True, timeout=40)
    tail = r.stderr.strip().splitlines() or ["no output"]
    ran = [l for l in tail if l.startswith("Ran ")]
    out.append({"id": "repo_tests_pass", "passed": r.returncode == 0 and bool(ran) and not ran[0].startswith("Ran 0 "),
                "evidence": "%s; %s" % (ran[0] if ran else "no tests ran", tail[-1])})
    return out
