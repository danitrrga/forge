"""Serve the rates page, read fresh from the refresher's file on every request: python3 dashboard.py"""
from http.server import BaseHTTPRequestHandler, HTTPServer

from rates.store import load_rates

RATES_FILE = "rates.json"


def render():
    rates = load_rates(RATES_FILE)
    rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (cur, rate) for cur, rate in sorted(rates.items()))
    return "<table><tr><th>Currency</th><th>per EUR</th></tr>%s</table>" % rows


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
