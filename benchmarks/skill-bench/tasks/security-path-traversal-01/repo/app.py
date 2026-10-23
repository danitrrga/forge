"""Attachments server: GET /files/<name> returns a file from the uploads folder.

Run: python3 app.py   (serves on 127.0.0.1:8000)
"""
import os
from wsgiref.simple_server import make_server

from files import read_file_from_dir

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(HERE, "uploads"))


def app(environ, start_response):
    path = environ.get("PATH_INFO", "")  # already percent-decoded by the WSGI server
    if not path.startswith("/files/"):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found\n"]
    content = read_file_from_dir(path[len("/files/"):], UPLOAD_DIR)
    if not content:
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"no such file\n"]
    start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
    return [content.encode("utf-8")]


if __name__ == "__main__":
    with make_server("127.0.0.1", 8000, app) as srv:
        srv.serve_forever()
