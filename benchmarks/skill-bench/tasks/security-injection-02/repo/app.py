"""Members area login: POST /login with form fields username and password.

Run: python3 app.py   (serves on 127.0.0.1:8000, database members.db next to this file)
"""
import os
import sqlite3
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from users import get_user

DB_PATH = os.environ.get("MEMBERS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "members.db"))


def app(environ, start_response):
    if environ.get("PATH_INFO") != "/login" or environ.get("REQUEST_METHOD") != "POST":
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found\n"]
    size = int(environ.get("CONTENT_LENGTH") or 0)
    form = parse_qs(environ["wsgi.input"].read(size).decode("utf-8"))
    username = form.get("username", [""])[0]
    password = form.get("password", [""])[0]
    conn = sqlite3.connect(DB_PATH)
    try:
        info = get_user(conn.cursor(), username, password)
    finally:
        conn.close()
    if info is None:
        start_response("401 Unauthorized", [("Content-Type", "text/plain")])
        return [b"wrong username or password\n"]
    start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
    return [("Welcome, %s\n" % info).encode("utf-8")]


if __name__ == "__main__":
    with make_server("127.0.0.1", 8000, app) as srv:
        srv.serve_forever()
