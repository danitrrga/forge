"""Oracle for debug-misleading-error-01: a TypeError in pricing whose cause is the settings loader.

The traceback ends in tax_cents(), but load_config() is where it goes wrong twice: configparser keeps an
inline `; comment` as part of the value (README.md says comments after a value are allowed), and the loader
then swallows the failed float() and hands the raw string on, so the crash surfaces far from the setting.
Editing settings.ini or casting in pricing.py makes run_invoices.py work and leaves both. The oracle loads
its own settings files: commented ones must give typed values and right invoices, and a bad or missing
value must fail inside load_config() with a message that names the setting."""
import json
import os
import subprocess
import sys
import tempfile

GOOD = """# acme billing
[billing]
currency = EUR       ; ISO code
tax_rate = 0.21      ; standard VAT
late_fee_rate = 0.015  # per month late
net_days = 30        ; days
"""
BAD = {
    "tax_rate": GOOD.replace("0.21      ; standard VAT", "0,21"),
    "net_days": GOOD.replace("30        ; days", "30 days"),
    "late_fee_rate": GOOD.replace("late_fee_rate = 0.015  # per month late\n", ""),
}

PROBE = r'''
import json, sys
from datetime import date
from decimal import Decimal
repo, good = sys.argv[1], sys.argv[2]
bad = json.loads(sys.argv[3])
sys.path.insert(0, repo)
from billing.config import load_config
from billing.pricing import due_date, format_money, invoice_total, late_fee_cents
res = {}
try:
    cfg = load_config(good)
    res["cfg"] = {k: [type(v).__name__, str(v)] for k, v in cfg.items()}
    def num(v):
        return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
    res["typed"] = (cfg.get("currency") == "EUR" and num(cfg.get("tax_rate")) and abs(float(cfg["tax_rate"]) - 0.21) < 1e-12
                    and num(cfg.get("late_fee_rate")) and abs(float(cfg["late_fee_rate"]) - 0.015) < 1e-12
                    and cfg.get("net_days") == 30 and isinstance(cfg.get("net_days"), int))
    try:
        total = invoice_total([("Widget", 3, 4000)], cfg)
        res["money"] = [total, late_fee_cents(total, 2, cfg), str(due_date(date(2026, 10, 1), cfg)), format_money(total, cfg)]
    except Exception as e:
        res["money"] = "%s: %s" % (type(e).__name__, str(e)[:120])
except Exception as e:
    res["cfg"] = "load_config raised %s: %s" % (type(e).__name__, str(e)[:200])
    res["typed"], res["money"] = False, None
res["bad"] = {}
for key, path in bad.items():
    try:
        got = load_config(path)
        res["bad"][key] = [False, "load_config returned %s=%r" % (key, got.get(key) if hasattr(got, "get") else got)]
    except Exception as e:
        msg = "%s: %s" % (type(e).__name__, e)
        res["bad"][key] = [key in str(e), msg[:200]]
print(json.dumps(res))
'''


def check(repo, message):
    repo = os.path.abspath(repo)
    with tempfile.TemporaryDirectory() as tmp:
        good = os.path.join(tmp, "good.ini")
        open(good, "w").write(GOOD)
        bad = {}
        for key, text in BAD.items():
            bad[key] = os.path.join(tmp, "bad_%s.ini" % key)
            open(bad[key], "w").write(text)
        r = subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, repo, good, json.dumps(bad)],
                           capture_output=True, text=True, timeout=30, cwd=repo)
    lines = r.stdout.strip().splitlines()
    ids = ("commented-settings-typed", "invoice-from-commented-settings", "bad-value-fails-at-load-naming-key",
           "missing-value-fails-at-load-naming-key")
    if r.returncode or not lines:
        err = (r.stderr.strip().splitlines() or ["no output"])[-1]
        return [{"id": i, "passed": False, "evidence": "probe failed: " + err} for i in ids]
    res = json.loads(lines[-1])
    want = [14520, 436, "2026-10-31", "EUR 145.20"]
    b = res["bad"]
    return [
        {"id": ids[0], "passed": bool(res["typed"]), "evidence": "settings with inline ; and # comments load as %r" % (res["cfg"],)},
        {"id": ids[1], "passed": res["money"] == want,
         "evidence": "total, late fee (2 months), due date, formatted total: %r, want %r" % (res["money"], want)},
        {"id": ids[2], "passed": b["tax_rate"][0] and b["net_days"][0],
         "evidence": "tax_rate = 0,21 -> %s | net_days = 30 days -> %s" % (b["tax_rate"][1], b["net_days"][1])},
        {"id": ids[3], "passed": b["late_fee_rate"][0], "evidence": "late_fee_rate missing -> %s" % b["late_fee_rate"][1]},
    ]
