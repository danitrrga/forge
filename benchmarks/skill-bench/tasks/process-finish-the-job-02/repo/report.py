"""Build dist/report.html from data/sales.csv."""
import csv
import html
import os
from collections import OrderedDict

from money import fmt_money

ROOT = os.path.dirname(os.path.abspath(__file__))


def load(path=os.path.join(ROOT, "data", "sales.csv")):
    with open(path, newline="", encoding="utf-8") as fh:
        return [dict(r, amount_cents=int(r["amount_cents"])) for r in csv.DictReader(fh)]


def by_month(rows):
    out = OrderedDict()
    for r in sorted(rows, key=lambda r: r["date"]):
        month = r["date"][:7]
        out[month] = out.get(month, 0) + r["amount_cents"]
    return out


def table(title, pairs):
    body = "".join("<tr><td>%s</td><td class=\"num\">%s</td></tr>" % (html.escape(k), fmt_money(v)) for k, v in pairs)
    return "<h2>%s</h2>\n<table>%s</table>\n" % (html.escape(title), body)


def build(rows):
    grand = sum(r["amount_cents"] for r in rows)
    parts = [
        "<!doctype html>\n<meta charset=\"utf-8\">\n<title>Acme sales</title>\n<h1>Acme sales</h1>\n",
        "<p class=\"grand-total\">Grand total: %s</p>\n" % fmt_money(grand),
        table("By month", by_month(rows).items()),
    ]
    return "".join(parts), grand


def main():
    rows = load()
    page, grand = build(rows)
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    with open(os.path.join(ROOT, "dist", "report.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    print("wrote dist/report.html: %d rows, grand total %s" % (len(rows), fmt_money(grand)))


if __name__ == "__main__":
    main()
