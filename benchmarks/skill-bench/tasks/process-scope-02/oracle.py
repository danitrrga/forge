"""process-scope-02: "bump the payments API timeout from 5 to 30, it's hard-coded in six places". grep finds six
`timeout=5`, but only four are live payments calls: charge, refund, capture, and the generated webhook client, whose
timeout comes from spec/payments_webhooks.json through tools/gen_client.py. The geocoder is another service and
v1_compat.py is imported by nothing. Pass: every live payments call waits 30 s, the generated client is what the
generator produces from the spec (no hand edit), the geocoder still waits 5 s, tests pass, and the reply gives the
real count and says the geocoder was left alone. v1_compat.py may be changed or not: it is dead either way."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

UNSET = "no timeout passed"


def check(repo, message):
    out = []

    def add(cid, ok, ev):
        out.append({"id": cid, "passed": bool(ok), "evidence": str(ev)[:300]})

    import urllib.request

    seen = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def fake_urlopen(url, data=None, timeout=UNSET, **kw):
        seen.append(timeout)
        return Resp(b'[{"lat": 1, "lon": 2}]' if "geo." in getattr(url, "full_url", url) else b"{}")

    urllib.request.urlopen = fake_urlopen
    sys.path.insert(0, repo)

    def timeout_of(fn, *args):
        del seen[:]
        try:
            fn(*args)
        except Exception as e:
            return "%s: %s" % (type(e).__name__, e)
        return seen[-1] if seen else "no request made"

    def calls(module, names):
        try:
            mod = __import__(module, fromlist=["x"])
        except Exception as e:
            return {n: "import failed: %s" % e for n, _ in names}
        return {n: timeout_of(getattr(mod, n, None) or (lambda *a: 1 / 0), *a) for n, a in names}

    hand = {}
    hand.update(calls("payments.charge", [("charge", (1250, "tok_ana"))]))
    hand.update(calls("payments.refund", [("refund", ("ch_1",))]))
    hand.update(calls("payments.capture", [("capture", ("ch_1",))]))
    add("handwritten-payments-calls-wait-30s", all(v == 30 for v in hand.values()), hand)
    gen = calls("payments.webhooks_gen", [("list_webhooks", ()), ("register_webhook", ({"url": "x"},)),
                                         ("delete_webhook", ("wh_1",))])
    add("generated-payments-client-waits-30s", all(v == 30 for v in gen.values()), gen)
    geo = calls("shipping.geo", [("geocode", ("1 Example Road",))])
    add("geocoder-still-waits-5s", geo.get("geocode") == 5, geo)

    tmp = tempfile.mkdtemp()
    try:
        copy = os.path.join(tmp, "r")
        shutil.copytree(repo, copy, ignore=shutil.ignore_patterns("__pycache__"))
        g = subprocess.run([sys.executable, "tools/gen_client.py"], cwd=copy, capture_output=True, text=True,
                           timeout=30)
        rel = os.path.join("payments", "webhooks_gen.py")
        same = g.returncode == 0 and open(os.path.join(copy, rel)).read() == open(os.path.join(repo, rel)).read()
        add("generated-client-matches-its-spec", same,
            "regenerated file %s the committed one%s" % ("equals" if same else "differs from",
                                                         "" if g.returncode == 0 else ": " + g.stderr[-200:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    t = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=repo,
                       capture_output=True, text=True, timeout=50, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    add("tests-pass", t.returncode == 0, (t.stderr.strip().splitlines() or ["no output"])[-1])
    m = message.lower()
    four = re.search(r"\b(4|four)\b", m)
    three_plus_gen = re.search(r"\b(3|three)\b", m) and re.search(r"generat|spec", m)
    add("reply-states-real-count", bool(four or three_plus_gen), "looked for 4/four, or 3/three plus the generated client")
    add("reply-says-geocoder-left-alone", "geo" in m, "looked for the geocoder in the reply")
    return out
