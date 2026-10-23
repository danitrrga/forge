"""CSV exports for the back office. Each function returns the file content as a string.

Rows are dicts: {"date": "2026-03-01", "customer": "Ana Ruiz", "amount_cents": 1250}.
"""


def sales_csv(rows):
    out = ["date,customer,amount"]
    for r in rows:
        name = r["customer"].replace('"', '""')
        if "," in name or '"' in name:
            name = '"%s"' % name
        amount = "%.2f" % (r["amount_cents"] / 100)
        out.append("%s,%s,%s" % (r["date"], name, amount))
    return "\n".join(out) + "\n"


def refunds_csv(rows):
    out = ["date,customer,amount"]
    for r in rows:
        name = r["customer"].replace('"', '""')
        if "," in name or '"' in name:
            name = '"%s"' % name
        amount = "%.2f" % (-r["amount_cents"] / 100)
        out.append("%s,%s,%s" % (r["date"], name, amount))
    return "\n".join(out) + "\n"


def payouts_csv(rows):
    out = ["date,customer,amount"]
    for r in rows:
        if r["amount_cents"] == 0:
            continue
        name = r["customer"].replace('"', '""')
        if "," in name or '"' in name or "\n" in name:
            name = '"%s"' % name
        amount = "%.2f" % (r["amount_cents"] / 100)
        out.append("%s,%s,%s" % (r["date"], name, amount))
    return "\r\n".join(out) + "\r\n"
