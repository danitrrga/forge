import io
import json
import unittest
from wsgiref.util import setup_testing_defaults

from notes import store
from notes.app import app

ANA, BEN, CLEO = "t-ana-51c0", "t-ben-7aa2", "t-cleo-e94d"


def call(method, path, token=None, payload=None):
    environ = {}
    setup_testing_defaults(environ)
    body = json.dumps(payload).encode() if payload is not None else b""
    environ.update({"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(len(body)),
                    "wsgi.input": io.BytesIO(body)})
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    status = []
    out = b"".join(app(environ, lambda s, h: status.append(s)))
    return int(status[0].split()[0]), out


class NotesApiTest(unittest.TestCase):
    def setUp(self):
        store.reset()

    def test_owner_reads_document(self):
        code, body = call("GET", "/docs/1", BEN)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["title"], "Salary bands 2027")

    def test_stranger_cannot_read_document(self):
        code, _ = call("GET", "/docs/1", ANA)
        self.assertEqual(code, 404)

    def test_shared_user_reads_but_cannot_edit(self):
        self.assertEqual(call("GET", "/docs/2", CLEO)[0], 200)
        self.assertEqual(call("PUT", "/docs/2", CLEO, {"title": "x"})[0], 403)

    def test_list_shows_owned_and_shared(self):
        code, body = call("GET", "/docs", CLEO)
        self.assertEqual([d["id"] for d in json.loads(body)["docs"]], [2])


if __name__ == "__main__":
    unittest.main()
