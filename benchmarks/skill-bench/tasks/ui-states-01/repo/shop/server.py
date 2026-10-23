"""Development server: python3 -m shop.server"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .views import render_orders

PAGE = "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>Your orders</title><body>%s</body></html>"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/orders":
            self.send_error(404)
            return
        customer = parse_qs(url.query).get("customer", [""])[0]
        html = (PAGE % render_orders(customer)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
