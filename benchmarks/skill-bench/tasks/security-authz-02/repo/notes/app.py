"""Notes service API (JSON over HTTP, token in `Authorization: Bearer <token>`).

  GET  /docs                    documents the caller owns or that are shared with them
  GET  /docs/<id>               one document
  PUT  /docs/<id>               update title and/or body (owner only)
  GET  /docs/<id>/preview       title and the first 40 characters, for the sidebar
  GET  /docs/<id>/download      the body as a text/plain attachment
"""
import json
import re

from notes import store
from notes.permissions import can_edit, can_read

ROUTES = []


def route(method, pattern):
    def register(handler):
        ROUTES.append((method, re.compile("^" + pattern + "$"), handler))
        return handler
    return register


def json_response(status, payload):
    return status, [("Content-Type", "application/json")], json.dumps(payload).encode("utf-8")


NOT_FOUND = json_response("404 Not Found", {"error": "not found"})


@route("GET", r"/docs")
def list_docs(user, body):
    docs = [{"id": d["id"], "title": d["title"]} for d in store.DOCS.values() if can_read(user, d)]
    return json_response("200 OK", {"docs": docs})


@route("GET", r"/docs/(\d+)")
def get_doc(user, body, doc_id):
    doc = store.get_doc(int(doc_id))
    if doc is None or not can_read(user, doc):
        return NOT_FOUND
    return json_response("200 OK", doc)


@route("PUT", r"/docs/(\d+)")
def update_doc(user, body, doc_id):
    doc = store.get_doc(int(doc_id))
    if doc is None or not can_read(user, doc):
        return NOT_FOUND
    if not can_edit(user, doc):
        return json_response("403 Forbidden", {"error": "only the owner can edit"})
    changes = json.loads(body or b"{}")
    for field in ("title", "body"):
        if field in changes:
            doc[field] = str(changes[field])
    return json_response("200 OK", doc)


@route("GET", r"/docs/(\d+)/preview")
def preview_doc(user, body, doc_id):
    doc = store.get_doc(int(doc_id))
    if doc is None:
        return NOT_FOUND
    return json_response("200 OK", {"id": doc["id"], "title": doc["title"], "excerpt": doc["body"][:40]})


@route("GET", r"/docs/(\d+)/download")
def download_doc(user, body, doc_id):
    doc = store.get_doc(int(doc_id))
    if doc is None:
        return NOT_FOUND
    headers = [("Content-Type", "text/plain; charset=utf-8"),
               ("Content-Disposition", 'attachment; filename="doc-%d.txt"' % doc["id"])]
    return "200 OK", headers, doc["body"].encode("utf-8")


def current_user(environ):
    auth = environ.get("HTTP_AUTHORIZATION", "")
    token = auth[len("Bearer "):] if auth.startswith("Bearer ") else None
    return store.USERS.get(store.TOKENS.get(token))


def app(environ, start_response):
    user = current_user(environ)
    if user is None:
        status, headers, payload = json_response("401 Unauthorized", {"error": "missing or bad token"})
    else:
        size = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(size) if size else b""
        method, path = environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO", "")
        for m, pattern, handler in ROUTES:
            match = pattern.match(path)
            if match and m == method:
                status, headers, payload = handler(user, body, *match.groups())
                break
        else:
            status, headers, payload = NOT_FOUND
    start_response(status, headers)
    return [payload]
