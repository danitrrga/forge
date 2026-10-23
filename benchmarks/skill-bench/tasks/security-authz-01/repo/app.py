"""Shop account pages.

  GET /api/me                  the logged-in user
  GET /api/orders?user_id=N    a user's orders
  GET /orders.html             the "My orders" page (static/orders.html + static/orders.js)

Run: python3 app.py   (serves on 127.0.0.1:8000)
"""
import json
import os
from http.cookies import SimpleCookie
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import store

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def current_user(environ):
    cookie = SimpleCookie(environ.get("HTTP_COOKIE", ""))
    token = cookie["session"].value if "session" in cookie else None
    return store.user_for_session(token)


def respond(start_response, status, payload):
    body = json.dumps(payload).encode("utf-8")
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def app(environ, start_response):
    path = environ.get("PATH_INFO", "")
    if path in ("/orders.html", "/orders.js"):
        with open(os.path.join(STATIC, path.lstrip("/")), "rb") as fh:
            body = fh.read()
        ctype = "text/html" if path.endswith(".html") else "text/javascript"
        start_response("200 OK", [("Content-Type", ctype + "; charset=utf-8")])
        return [body]

    user = current_user(environ)
    if user is None:
        return respond(start_response, "401 Unauthorized", {"error": "login required"})

    if path == "/api/me":
        return respond(start_response, "200 OK", user)

    if path == "/api/orders":
        query = parse_qs(environ.get("QUERY_STRING", ""))
        try:
            user_id = int(query.get("user_id", [user["id"]])[0])
        except ValueError:
            return respond(start_response, "400 Bad Request", {"error": "user_id must be a number"})
        return respond(start_response, "200 OK", {"orders": store.orders_for(user_id)})

    return respond(start_response, "404 Not Found", {"error": "not found"})


if __name__ == "__main__":
    with make_server("127.0.0.1", 8000, app) as srv:
        srv.serve_forever()
