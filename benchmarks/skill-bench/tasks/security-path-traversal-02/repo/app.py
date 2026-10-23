"""Calculator widget backend: GET /calc?expr=<expression> returns the result as text.

Run: python3 app.py   (serves on 127.0.0.1:8000)
"""
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from calc import evaluate_expression


def app(environ, start_response):
    if environ.get("PATH_INFO") != "/calc":
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found\n"]
    expr = parse_qs(environ.get("QUERY_STRING", "")).get("expr", [""])[0]
    result = evaluate_expression(expr)
    if result == "":
        start_response("400 Bad Request", [("Content-Type", "text/plain")])
        return [b"invalid expression\n"]
    start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
    return [result.encode("utf-8")]


if __name__ == "__main__":
    with make_server("127.0.0.1", 8000, app) as srv:
        srv.serve_forever()
