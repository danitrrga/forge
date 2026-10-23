"""Invoice totals.

Unit prices arrive as strings with two decimals ("12.50") and quantities as integers; a credit
note has negative quantities. VAT is charged once, on the invoice subtotal, and rounded to the
cent half away from zero (2.625 -> 2.63, -2.625 -> -2.63). The total is subtotal plus VAT.
Amounts are returned as strings with two decimals, ready to print.
"""


def invoice_totals(lines, vat_rate="0.21"):
    """{"subtotal", "vat", "total"} for lines of (description, unit_price, quantity)."""
    subtotal = 0.0
    for _description, unit_price, quantity in lines:
        subtotal += float(unit_price) * quantity
    vat = round(subtotal * float(vat_rate), 2)
    total = subtotal + vat
    return {"subtotal": f"{subtotal:.2f}", "vat": f"{vat:.2f}", "total": f"{total:.2f}"}
