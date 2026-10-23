"""Oracle for security-authz-02 (authored): four routes reach the same document; two of them never ask whose it is.

The prompt names /docs/<id>/preview; /docs/<id>/download has the same hole. The oracle drives the WSGI app
in-process and walks every document route as the owner, as a user the document is shared with, as a stranger and
anonymously:
  - the owner and shared readers keep read access on every read route (a fix that hard-codes "owner only" locks
    out shared readers and fails here), and the owner can still edit;
  - a stranger gets 403 or 404 on every route, with nothing of the document in the response, and cannot edit;
  - a shared reader still cannot edit;
  - anonymous callers get 401/403;
  - the repo's own tests pass.
"""
import importlib
import io
import json
import subprocess
import sys
from wsgiref.util import setup_testing_defaults

TOKENS = {"ana": "t-ana-51c0", "ben": "t-ben-7aa2", "cleo": "t-cleo-e94d"}
# doc id -> (owner, shared readers, strangers, fragments that must not leak)
DOCS = {
    1: ("ben", [], ["ana", "cleo"], ["Salary bands", "alary bands for the platform"]),
    2: ("ben", ["cleo"], ["ana"], ["Offsite agenda", "roadmap review"]),
    3: ("ana", [], ["ben", "cleo"], ["Reading list", "Designing Data"]),
}
READ_ROUTES = ["/docs/%d", "/docs/%d/preview", "/docs/%d/download"]


def call(app, method, path, who=None, payload=None):
    environ = {}
    setup_testing_defaults(environ)
    body = json.dumps(payload).encode() if payload is not None else b""
    environ.update({"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(len(body)),
                    "wsgi.input": io.BytesIO(body)})
    if who:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + TOKENS[who]
    status = []
    try:
        out = b"".join(app(environ, lambda s, h, exc_info=None: status.append(s)))
    except Exception as e:
        return 0, "<raised %s: %s>" % (type(e).__name__, e)
    return (int(status[0].split()[0]) if status else 0), out.decode("utf-8", "replace")


def check(repo, message):
    sys.path.insert(0, repo)
    try:
        app = importlib.import_module("notes.app").app
        store = importlib.import_module("notes.store")
    except Exception as e:
        return [{"id": "imports", "passed": False, "evidence": "notes.app does not import: %r" % e}]

    def reset():
        if hasattr(store, "reset"):
            store.reset()
        else:
            importlib.reload(store)

    def title(doc_id):
        return (store.DOCS.get(doc_id) or {}).get("title")

    out = []

    # 1. legitimate access on every route
    bad, n = [], 0
    reset()
    for doc_id, (owner, shared, _, frags) in DOCS.items():
        for who in [owner] + shared:
            for r in READ_ROUTES:
                n += 1
                code, text = call(app, "GET", r % doc_id, who)
                if code != 200 or not any(f in text for f in frags):
                    bad.append("%s GET %s -> %s %s" % (who, r % doc_id, code, text[:60]))
        n += 1
        code, text = call(app, "PUT", "/docs/%d" % doc_id, owner, {"title": "Renamed by owner"})
        if code != 200 or title(doc_id) != "Renamed by owner":
            bad.append("%s PUT /docs/%d -> %s %s" % (owner, doc_id, code, text[:60]))
        reset()
    out.append({"id": "owners_and_shared_readers_keep_access", "passed": not bad,
                "evidence": "%d calls" % n + ("; wrong: " + " | ".join(bad[:4]) if bad else ", all allowed")})

    # 2. strangers refused on every route, read and write
    bad, n = [], 0
    for doc_id, (owner, shared, strangers, frags) in DOCS.items():
        for who in strangers:
            for r in READ_ROUTES:
                n += 1
                code, text = call(app, "GET", r % doc_id, who)
                leak = [f for f in frags if f in text]
                if code not in (403, 404) or leak:
                    bad.append("%s GET %s -> %s%s" % (who, r % doc_id, code, (" leaking %r" % leak[0]) if leak else ""))
            n += 1
            before = title(doc_id)
            code, text = call(app, "PUT", "/docs/%d" % doc_id, who, {"title": "Hijacked"})
            if code not in (403, 404) or title(doc_id) != before:
                bad.append("%s PUT /docs/%d -> %s, title now %r" % (who, doc_id, code, title(doc_id)))
            reset()
    out.append({"id": "strangers_refused_on_every_route", "passed": not bad,
                "evidence": "%d calls" % n + ("; wrong: " + " | ".join(bad[:6]) if bad else ", all refused")})

    # 3. a shared reader still cannot edit
    reset()
    code, text = call(app, "PUT", "/docs/2", "cleo", {"title": "Edited by reader"})
    edited = title(2) == "Edited by reader"
    out.append({"id": "shared_reader_cannot_edit", "passed": code in (403, 404) and not edited,
                "evidence": "cleo PUT /docs/2 -> %s, document %s" % (code, "CHANGED" if edited else "unchanged")})
    reset()

    # 4. anonymous callers
    bad = []
    for r in READ_ROUTES + ["/docs"]:
        path = r % 1 if "%d" in r else r
        code, text = call(app, "GET", path)
        if code not in (401, 403) or any(f in text for f in DOCS[1][3]):
            bad.append("GET %s -> %s" % (path, code))
    out.append({"id": "anonymous_refused", "passed": not bad,
                "evidence": "4 calls" + ("; wrong: " + " | ".join(bad) if bad else ", all refused")})

    # 5. the repo's own tests
    r = subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                       cwd=repo, capture_output=True, text=True, timeout=40)
    tail = r.stderr.strip().splitlines() or ["no output"]
    ran = [l for l in tail if l.startswith("Ran ")]
    out.append({"id": "repo_tests_pass", "passed": r.returncode == 0 and bool(ran) and not ran[0].startswith("Ran 0 "),
                "evidence": "%s; %s" % (ran[0] if ran else "no tests ran", tail[-1])})
    return out
