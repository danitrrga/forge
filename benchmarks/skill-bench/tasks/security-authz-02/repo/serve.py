"""Run the notes API locally: python3 serve.py   (127.0.0.1:8000)"""
from wsgiref.simple_server import make_server

from notes.app import app

if __name__ == "__main__":
    with make_server("127.0.0.1", 8000, app) as srv:
        srv.serve_forever()
