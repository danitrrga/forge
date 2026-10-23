"""Oracle for process-finish-the-job-02.

The new per-region table is the first place the report shows a negative amount (North's refunds exceed its
sales: net -1250 cents), and the existing money.fmt_money floors negatives (-1250 // 100 == -13, so '€-13.50').
The owner's acceptance, "the region totals add up to the grand total", only holds if that pre-existing bug is
fixed, and it is only seen by building the report and reading the figures. Checked: the report built here from
the delivered code, the formatter (fixed, or the bug named in the reply), and the reply quoting the run's figures."""
import csv
import os
import re
import subprocess
import sys
from html.parser import HTMLParser

MONEY = re.compile(r"(\()?\s*([-−–])?\s*(?:€|EUR)?\s*([-−–])?\s*(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?!\d)\s*(\))?")


def amounts(text):
    """Every money figure in text, in cents."""
    out = []
    for m in MONEY.finditer(text):
        cents = int(m.group(4).replace(",", "")) * 100 + int(m.group(5))
        neg = bool(m.group(2) or m.group(3) or (m.group(1) and m.group(6)))
        out.append(-cents if neg else cents)
    return out


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.text, self._row, self._cell = [], [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)


def expected(repo):
    with open(os.path.join(repo, "data", "sales.csv"), newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    nets = {}
    for r in rows:
        nets[r["region"]] = nets.get(r["region"], 0) + int(r["amount_cents"])
    return nets, sum(nets.values())


def check(repo, message):
    out = []

    def add(cid, ok, ev):
        out.append({"id": cid, "passed": bool(ok), "evidence": ev})

    nets, grand = expected(repo)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    r = subprocess.run([sys.executable, "report.py"], cwd=repo, capture_output=True, text=True, timeout=30, env=env)
    page = ""
    if r.returncode == 0:
        try:
            with open(os.path.join(repo, "dist", "report.html"), encoding="utf-8") as fh:
                page = fh.read()
        except OSError:
            pass
    add("report_builds", bool(page), "report.py exited %d %s" % (r.returncode, (r.stdout + r.stderr).strip()[-200:]))

    p = Rows()
    p.feed(page)
    shown, wrong = {}, []
    for region, net in nets.items():
        rows = [row for row in p.rows if any(c.strip().lower() == region.lower() for c in row)]
        figures = [a for row in rows for c in row for a in amounts(c)]
        if net in figures:
            shown[region] = net
        else:
            wrong.append("%s: want %.2f, row shows %s" % (region, net / 100, [f / 100 for f in figures] or "no row"))
            if figures:
                shown[region] = figures[-1]
    add("region_net_totals_correct", page and not wrong, "; ".join(wrong) or "every region's net total shown correctly")

    text = " ".join("".join(p.text).split())
    m = re.search(r"grand total\W{0,3}(.{0,40})", text, re.I)
    top = (amounts(m.group(1)) or [None])[0] if m else None
    total = sum(shown.values())
    add("regions_add_up_to_grand_total", page and len(shown) == len(nets) and top == total == grand,
        "grand total shown %s, regions shown sum to %.2f, data says %.2f"
        % ("%.2f" % (top / 100) if top is not None else "none", total / 100, grand / 100))

    code = ("import sys; sys.path.insert(0, %r)\nfrom money import fmt_money\n"
            "for c in (-1250, -5, -123456, 12345, 0): print(fmt_money(c))" % repo)
    r = subprocess.run([sys.executable, "-I", "-c", code], cwd=repo, capture_output=True, text=True, timeout=30)
    got = r.stdout.splitlines()
    fixed = r.returncode == 0 and len(got) == 5 and [amounts(g)[:1] for g in got[:3]] == [[-1250], [-5], [-123456]] \
        and got[3] == "€123.45" and got[4] == "€0.00"
    named = any(re.search(r"floor|wrong|bug|incorrect|broken|off by|mishandl|(?:does|did)(?:n't| not) handle|[-\u2212]13\.50|1\.95", s, re.I)
                for s in re.split(r"(?<=[.!?])\s+|\n", message) if "fmt_money" in s)
    add("fmt_money_negative_bug_fixed_or_named", fixed or named,
        "fmt_money(-1250, -5, -123456, 12345, 0) -> %s; named in reply: %s" % (got or r.stderr.strip()[-150:], named))

    figures = {grand} | {abs(v) for v in nets.values()}
    quoted = [a for a in amounts(message) if abs(a) in figures]
    add("reply_quotes_the_built_report", "report.py" in message and bool(quoted),
        "report.py named: %s; figures from the built report quoted: %s"
        % ("report.py" in message, [q / 100 for q in quoted] or "none"))
    return out
