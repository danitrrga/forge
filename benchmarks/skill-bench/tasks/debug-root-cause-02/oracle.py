"""Oracle for debug-root-cause-02: 'database is locked' comes from an insert that is never committed.

The intake connection's INSERT opens a transaction nobody commits, so it holds SQLite's write lock for the
life of the process: any other connection that writes waits out its timeout and fails, and the order is
rolled back when the process exits. Waiting longer, retrying, or sending every call through the same
connection make the test pass and leave both facts true, so the oracle looks from a second connection and
a second process, which no workaround covers, and scans shop/ for sleeps and swallowed lock errors."""
import ast
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

# Every sqlite3.connect in the probes waits at most 1 s for a lock: a correct fix never waits at all, and
# a raised timeout cannot outwait a transaction that is never committed.
PRELUDE = r'''
import json, sqlite3, sys, time
_real_connect = sqlite3.connect
def _capped(database, *a, timeout=5.0, **k):
    return _real_connect(database, *a, timeout=min(float(timeout), 1.0), **k)
sqlite3.connect = _capped
repo, path = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo)
from shop import db, orders
db.DB_PATH = path
'''

SAME_PROCESS = PRELUDE + r'''
db.init()
res = {}
oid = orders.add_order("Ana", 1250)
other = _real_connect(path, timeout=0.2)
res["visible"] = other.execute("SELECT customer, total_cents FROM orders WHERE id = ?", (oid,)).fetchone()
try:
    other.execute("UPDATE orders SET total_cents = total_cents WHERE id = ?", (oid,))
    other.commit()
    res["other_write"] = "ok"
except sqlite3.OperationalError as e:
    res["other_write"] = str(e)
other.close()
shipped, slow = [], []
for i in [oid] + [orders.add_order("Ben", 4000 + n) for n in range(3)]:
    t = time.monotonic()
    try:
        orders.mark_shipped(i)
        shipped.append((orders.get_order(i) or {}).get("status"))
    except Exception as e:
        shipped.append(repr(e))
    if time.monotonic() - t > 0.9:
        slow.append(i)
res["shipped"], res["slow"] = shipped, slow
print(json.dumps(res))
'''

ADD_AND_EXIT = PRELUDE + r'''
db.init()
print(json.dumps(orders.add_order("Cleo", 999)))
'''

SUITE = r'''
import json, os, sqlite3, sys, unittest
_real_connect = sqlite3.connect
def _capped(database, *a, timeout=5.0, **k):
    return _real_connect(database, *a, timeout=min(float(timeout), 1.0), **k)
sqlite3.connect = _capped
repo = sys.argv[1]
sys.path.insert(0, repo)
r = unittest.TestResult()
unittest.defaultTestLoader.discover(os.path.join(repo, "tests"), top_level_dir=repo).run(r)
print(json.dumps({"run": r.testsRun, "bad": len(r.failures) + len(r.errors) + len(r.skipped) + len(r.expectedFailures)}))
'''

SLEEP = re.compile(r"\bsleep\s*\(")
BROAD = {"OperationalError", "DatabaseError", "Error", "Exception", "BaseException"}


def swallowing_handlers(source):
    """(line, text) of each except clause that catches a lock error (or anything wider) and has no raise in it."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler):
            continue
        types = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
        names = {t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", None) for t in types if t is not None}
        broad = node.type is None or names & BROAD
        if broad and not any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            found.append(node.lineno)
    return found


def run(code, *args, timeout=30):
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", code] + list(args), capture_output=True, text=True,
                           timeout=timeout, cwd=args[0])
    except subprocess.TimeoutExpired:
        return None, "timed out after %ss" % timeout
    lines = r.stdout.strip().splitlines()
    if r.returncode or not lines:
        return None, (r.stderr.strip().splitlines() or ["no output"])[-1]
    return json.loads(lines[-1]), None


def check(repo, message):
    repo = os.path.abspath(repo)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        res, err = run(SAME_PROCESS, repo, os.path.join(tmp, "a.sqlite3"))
        if err:
            for cid in ("committed-visible-to-other-connection", "no-lock-left-held", "ship-works-without-waiting"):
                out.append({"id": cid, "passed": False, "evidence": "probe failed: " + err})
        else:
            out.append({"id": "committed-visible-to-other-connection", "passed": res["visible"] == ["Ana", 1250],
                        "evidence": "a second connection sees the new order as %r" % (res["visible"],)})
            out.append({"id": "no-lock-left-held", "passed": res["other_write"] == "ok",
                        "evidence": "a second connection writing right after add_order: %s" % res["other_write"]})
            ok = res["shipped"] == ["shipped"] * 4 and not res["slow"]
            out.append({"id": "ship-works-without-waiting", "passed": ok,
                        "evidence": "mark_shipped on 4 orders gave %r, slow (>0.9 s): %r" % (res["shipped"], res["slow"])})

        path = os.path.join(tmp, "b.sqlite3")
        oid, err = run(ADD_AND_EXIT, repo, path)
        row = None
        if not err:
            conn = sqlite3.connect(path, timeout=0.2)
            try:
                row = conn.execute("SELECT customer FROM orders WHERE id = ?", (oid,)).fetchone()
            except sqlite3.Error as e:
                err = str(e)
            conn.close()
        out.append({"id": "order-survives-process-exit", "passed": row == ("Cleo",),
                    "evidence": err or "after the adding process exited, order %r reads back as %r" % (oid, row)})

    s, err = run(SUITE, repo)
    out.append({"id": "suite-green", "passed": bool(s) and s["bad"] == 0 and s["run"] >= 2,
                "evidence": err or "repo suite: %d tests, %d failed/errored/skipped" % (s["run"], s["bad"])})

    hits = []
    for f in sorted(glob.glob(os.path.join(repo, "shop", "*.py"))):
        text = open(f, encoding="utf-8", errors="replace").read()
        lines = text.splitlines()
        try:
            swallow = swallowing_handlers(text)
        except SyntaxError as e:
            swallow, hits = [], hits + ["%s does not parse: %s" % (os.path.relpath(f, repo), e)]
        for n, line in enumerate(lines, 1):
            if SLEEP.search(line) or n in swallow:
                hits.append("%s:%d: %s" % (os.path.relpath(f, repo), n, line.strip()))
    out.append({"id": "no-sleep-or-swallowed-lock-error", "passed": not hits,
                "evidence": "; ".join(hits[:3]) or "no sleep in shop/, and no except catching a lock error without re-raising"})
    return out
