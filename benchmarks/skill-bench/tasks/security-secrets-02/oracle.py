"""Oracle for security-secrets-02 (authored): the billing API key must stop leaking at its source.

The client builds a URL with ?api_key=<key> and then logs that URL and puts it in every BillingError. A redacting
logging filter (masking at the sink) cleans the log records but leaves the key in the URL sent to the API (proxy and
access logs, per docs/billing-api.md) and in the error text that sync_invoices.py prints to stderr. So the oracle
drives BillingClient through a fake transport, as the repo's own tests do, and checks every channel:
  - the invoice is still fetched, which needs the key to reach the fake API in a documented way (header or query);
  - no URL the transport received contains the key;
  - no log record (any logger, any level, as rendered) and nothing printed contains the key;
  - on an HTTP 500 and on a network error a BillingError is still raised, and its full traceback text, chained
    causes included, does not contain the key;
  - the repo's own unittest suite passes.
"""
import contextlib
import importlib
import io
import json
import logging
import os
import subprocess
import sys
import traceback
import urllib.error

KEY = "not-a-real-billing-key"
BASE = "https://billing.example.test"
INVOICES = {"inv_1": {"id": "inv_1", "customer": "cus_ana", "total_cents": 4200}}
CUSTOMERS = {"cus_ana": [INVOICES["inv_1"]]}


class FakeResponse(io.BytesIO):
    status = 200

    def getcode(self):
        return 200


class FakeApi:
    """Stands in for urllib.request.urlopen; records what each request carried."""

    def __init__(self):
        self.seen = []  # (url, {header-name-lower: value})

    def __call__(self, req, data=None, timeout=None, **kw):
        url = getattr(req, "full_url", req)
        headers = {}
        if hasattr(req, "header_items"):
            headers = {k.lower(): v for k, v in req.header_items()}
        self.seen.append((url, headers))
        path, _, query = url.partition("?")
        authorized = (headers.get("authorization") == "Bearer " + KEY or headers.get("x-api-key") == KEY
                      or ("api_key=" + KEY) in query.split("&"))
        if not authorized:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b'{"error": "unauthorized"}'))
        tail = path[len(BASE):]
        if tail.endswith("/inv_boom"):
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, io.BytesIO(b"{}"))
        if tail.endswith("/inv_offline"):
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        if tail.startswith("/v1/invoices/") and tail.rsplit("/", 1)[-1] in INVOICES:
            return FakeResponse(json.dumps(INVOICES[tail.rsplit("/", 1)[-1]]).encode())
        if tail.startswith("/v1/customers/") and tail.endswith("/invoices"):
            cid = tail.split("/")[3]
            if cid in CUSTOMERS:
                return FakeResponse(json.dumps(CUSTOMERS[cid]).encode())
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append("%s %s %s" % (record.name, record.levelname, record.getMessage()))
        except Exception as e:
            self.lines.append("unrenderable record %r %r (%s)" % (record.msg, record.args, e))


def check(repo, message):
    sys.path.insert(0, repo)
    try:
        client_mod = importlib.import_module("billing.client")
    except Exception as e:
        return [{"id": "imports", "passed": False, "evidence": "billing.client does not import: %r" % e}]
    root = logging.getLogger()
    cap = Capture()
    root.addHandler(cap)
    root.setLevel(logging.DEBUG)
    api = FakeApi()
    printed = io.StringIO()
    out = []

    def make():
        return client_mod.BillingClient(BASE, KEY, opener=api)

    # 1. normal calls still work
    results = {}
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
        for name, call in (("get_invoice", lambda c: c.get_invoice("inv_1")),
                           ("list_invoices", lambda c: c.list_invoices("cus_ana"))):
            try:
                results[name] = call(make())
            except Exception as e:
                results[name] = "<raised %s: %s>" % (type(e).__name__, e)
    ok = results.get("get_invoice") == INVOICES["inv_1"] and results.get("list_invoices") == CUSTOMERS["cus_ana"]
    out.append({"id": "invoices_still_fetched_and_authorized", "passed": ok,
                "evidence": "; ".join("%s -> %s" % (k, str(v)[:120]) for k, v in results.items())})

    # 2. error paths: still a BillingError, and nothing in it carries the key (sync_invoices.py prints str(e))
    err_problems = []
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
        for invoice_id in ("inv_boom", "inv_offline", "inv_missing"):
            try:
                make().get_invoice(invoice_id)
                err_problems.append("%s: no exception raised" % invoice_id)
            except Exception as e:
                text = "".join(traceback.format_exception(e))
                if not isinstance(e, client_mod.BillingError):
                    err_problems.append("%s: raised %s, not BillingError" % (invoice_id, type(e).__name__))
                if KEY in text:
                    line = next(l for l in text.splitlines() if KEY in l)
                    err_problems.append("%s: key in error text: %s" % (invoice_id, line.strip()[:160]))
    out.append({"id": "key_not_in_errors", "passed": not err_problems,
                "evidence": "3 error paths raised" + ("; " + " | ".join(err_problems) if err_problems else
                                                      ", none carries the key")})

    # 3. URLs sent to the API
    in_url = [u for u, _ in api.seen if KEY in u]
    out.append({"id": "key_not_in_any_url", "passed": bool(api.seen) and not in_url,
                "evidence": "%d request(s) seen; %d URL(s) contain the key%s"
                % (len(api.seen), len(in_url), (": " + in_url[0]) if in_url else "")})

    # 4. logs and printed output, across all the calls above
    root.removeHandler(cap)
    leaked = [l for l in cap.lines if KEY in l] + [l for l in printed.getvalue().splitlines() if KEY in l]
    out.append({"id": "key_not_in_logs_or_output", "passed": not leaked,
                "evidence": "%d log record(s) and %d printed line(s) read; %d contain the key%s"
                % (len(cap.lines), len(printed.getvalue().splitlines()), len(leaked),
                   (": " + leaked[0][:160]) if leaked else "")})

    # 5. the repo's own tests
    r = subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                       cwd=repo, capture_output=True, text=True, timeout=40)
    tail = (r.stderr.strip().splitlines() or ["no output"])
    ran = [l for l in tail if l.startswith("Ran ")]
    out.append({"id": "repo_tests_pass", "passed": r.returncode == 0 and bool(ran) and not ran[0].startswith("Ran 0 "),
                "evidence": "%s; %s" % (ran[0] if ran else "no tests ran", tail[-1])})
    return out
