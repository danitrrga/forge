"""Tiny file-share browser: GET /ls?dir=<folder> shows `ls -l` of a folder under SHARE_ROOT.

Run: SHARE_ROOT=/path/to/share python3 app.py   (serves on 127.0.0.1:8000)
"""
import os
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from listing import get_ls_result

SHARE_ROOT = os.environ.get("SHARE_ROOT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "share"))


def app(environ, start_response):
    if environ.get("PATH_INFO") != "/ls":
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found\n"]
    folder = parse_qs(environ.get("QUERY_STRING", "")).get("dir", [""])[0]
    listing = get_ls_result(os.path.join(SHARE_ROOT, folder))
    start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
    return [(listing or "(empty or not found)\n").encode("utf-8")]


if __name__ == "__main__":
    with make_server("127.0.0.1", 8000, app) as srv:
        srv.serve_forever()
