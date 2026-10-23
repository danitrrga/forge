"""Oracle for logic-money-01 (authored): VAT rounded half away from zero, computed without binary floats.

The module docstring is the contract: VAT once on the subtotal, rounded to the cent half away from zero, amounts
as two-decimal strings. Each invoice below is a case where a float path gives the wrong cent: round() rounds an
exact float tie to even (12.50 * 0.21), Decimal(float) and Decimal(str(float)) inherit the binary error
(16.50 * 0.21, 1.15 * 0.10), a float subtotal 3 * 3.05 + 3.35 is 12.499999999999998, and a credit note must round
away from zero. Expected strings are written out by hand."""
import json
import re
import subprocess
import sys

INVOICES = {
    "reported-half-cent": [
        (([["Consulting hour", "12.50", 1]], "0.21"), ("12.50", "2.63", "15.13")),
    ],
    "half-cent-not-exact-in-binary": [
        (([["Desk lamp", "16.50", 1]], "0.21"), ("16.50", "3.47", "19.97")),
        (([["Pencil", "1.15", 1]], "0.10"), ("1.15", "0.12", "1.27")),
        (([["Sticker", "0.35", 1]], "0.10"), ("0.35", "0.04", "0.39")),
    ],
    "subtotal-summed-exactly": [
        (([["Notebook", "3.05", 3], ["Folder", "3.35", 1]], "0.21"), ("12.50", "2.63", "15.13")),
        (([["Notebook", "2.10", 3], ["Pen", "0.70", 5], ["Tape", "1.05", 1]], "0.21"), ("10.85", "2.28", "13.13")),
    ],
    "credit-note-rounds-away-from-zero": [
        (([["Refund: desk lamp", "16.50", -1]], "0.21"), ("-16.50", "-3.47", "-19.97")),
        (([["Refund: consulting", "12.50", -1]], "0.21"), ("-12.50", "-2.63", "-15.13")),
    ],
    "ordinary-invoices-unchanged": [
        (([["Server rack", "4999.95", 3]], "0.21"), ("14999.85", "3149.97", "18149.82")),
        (([["Bread", "1.25", 9]], "0.04"), ("11.25", "0.45", "11.70")),
        (([["Widget", "10.00", 2]], "0.21"), ("20.00", "4.20", "24.20")),
    ],
}

RUN = r'''
import json
from billing.invoice import invoice_totals
out = {}
for group, cases in INVOICES.items():
    res = []
    for (lines, rate), _ in cases:
        try:
            t = invoice_totals([tuple(l) for l in lines], rate)
            res.append(["ok", [str(t["subtotal"]), str(t["vat"]), str(t["total"])]])
        except Exception as e:
            res.append(["err", "%s: %s" % (type(e).__name__, e)])
    out[group] = res
print(json.dumps(out))
'''


def _py(repo, code, timeout=40):
    prog = "import sys\nsys.path.insert(0, %r)\n" % repo + code
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", prog], cwd=repo, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    lines = r.stdout.strip().splitlines()
    if r.returncode or not lines:
        return None, (r.stderr.strip().splitlines() or ["exit %d" % r.returncode])[-1][:300]
    try:
        return json.loads(lines[-1]), None
    except ValueError:
        return None, "unparseable output: " + lines[-1][:200]


def _repo_tests(repo):
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=repo, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    ran = re.search(r"Ran (\d+) test", r.stderr)
    n = int(ran.group(1)) if ran else 0
    return r.returncode == 0 and n > 0, "%d test(s) ran, exit %d: %s" % (n, r.returncode, r.stderr.strip().splitlines()[-1:])


def check(repo, message):
    res, err = _py(repo, "INVOICES = %r\n" % (INVOICES,) + RUN)
    out = []
    for group, cases in INVOICES.items():
        got_all = (res or {}).get(group, [])
        bad = []
        for ((lines, rate), want), got in zip(cases, got_all):
            label = " + ".join("%s x %s" % (l[2], l[1]) for l in lines) + " @ " + rate
            if got[0] != "ok":
                bad.append("%s raised %s" % (label, got[1]))
            elif got[1] != list(want):
                bad.append("%s -> subtotal/vat/total %s, want %s" % (label, "/".join(got[1]), "/".join(want)))
        ok = not err and len(got_all) == len(cases) and not bad
        out.append({"id": group, "passed": ok, "evidence": err or "; ".join(bad) or "%d invoice(s) right" % len(cases)})
    ok, ev = _repo_tests(repo)
    out.append({"id": "project-tests-pass", "passed": ok, "evidence": ev})
    return out
