"""Support inbox: POST /messages with the message as the request body (UTF-8 text).
Every message is appended to received.log, one entry per line; the on-call rota reads that file.

Run: python3 app.py   (serves on 127.0.0.1:8000)
"""
import os
from wsgiref.simple_server import make_server

from chatlog import generate_receive_log

LOG_PATH = os.environ.get("RECEIVED_LOG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "received.log"))


def app(environ, start_response):
    if environ.get("PATH_INFO") != "/messages" or environ.get("REQUEST_METHOD") != "POST":
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found\n"]
    size = int(environ.get("CONTENT_LENGTH") or 0)
    msg = environ["wsgi.input"].read(size).decode("utf-8", errors="replace")
    with open(LOG_PATH, "a", encoding="utf-8") as log:
        log.write(generate_receive_log(msg) + "\n")
    start_response("202 Accepted", [("Content-Type", "text/plain")])
    return [b"received\n"]


if __name__ == "__main__":
    with make_server("127.0.0.1", 8000, app) as srv:
        srv.serve_forever()
