from billing.tax import vat_cents


def total_cents(lines):
    return sum(line["net_cents"] for line in lines)


def build_invoice(raw):
    net = total_cents(raw["lines"])
    vat = vat_cents(net, raw["country"])
    return {"number": raw["number"], "customer": raw["customer"], "net_cents": net, "vat_cents": vat,
            "gross_cents": net + vat}


def _render_fax_cover(invoice):
    return "FAX COVER\nTo: %s\nRe: invoice %s\nPages: 2" % (invoice["customer"], invoice["number"])
