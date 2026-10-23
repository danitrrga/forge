from billing.invoice import invoice_totals


def render(lines, vat_rate="0.21"):
    totals = invoice_totals(lines, vat_rate)
    rows = ["%-24s %3d x %8s" % (description, quantity, price) for description, price, quantity in lines]
    rows.append("%-24s %16s" % ("Subtotal", totals["subtotal"]))
    rows.append("%-24s %16s" % ("VAT at %s" % vat_rate, totals["vat"]))
    rows.append("%-24s %16s" % ("Total", totals["total"]))
    return "\n".join(rows)


if __name__ == "__main__":
    print(render([("Consulting hour", "12.50", 1), ("Desk lamp", "16.50", 2)]))
