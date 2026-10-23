import io
import json
import unittest
from wsgiref.util import setup_testing_defaults

from app import app


def get(path, session=None):
    environ = {}
    setup_testing_defaults(environ)
    environ["PATH_INFO"], _, environ["QUERY_STRING"] = path.partition("?")
    if session:
        environ["HTTP_COOKIE"] = "session=" + session
    status = []
    body = b"".join(app(environ, lambda s, h: status.append(s)))
    return int(status[0].split()[0]), json.loads(body)


class OrdersApiTest(unittest.TestCase):
    def test_lists_my_orders(self):
        code, data = get("/api/orders", session="s-ana-6b1f")
        self.assertEqual(code, 200)
        self.assertEqual([o["id"] for o in data["orders"]], [101, 103])

    def test_requires_login(self):
        code, _ = get("/api/orders")
        self.assertEqual(code, 401)


if __name__ == "__main__":
    unittest.main()
