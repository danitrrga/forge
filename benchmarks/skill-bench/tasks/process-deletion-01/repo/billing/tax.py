from decimal import ROUND_HALF_UP, Decimal

VAT_RATES = {"ES": Decimal("0.21"), "DE": Decimal("0.19"), "FR": Decimal("0.20"), "PT": Decimal("0.23")}


def vat_rate(country):
    return VAT_RATES[country]


def vat_cents(net_cents, country):
    return int((Decimal(net_cents) * vat_rate(country)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate_from_string(text):
    """'21%' or '0.21' -> Decimal('0.21')."""
    text = text.strip()
    if text.endswith("%"):
        return Decimal(text[:-1]) / 100
    return Decimal(text)


def vat_table_2019():
    """Rates before the 2020 changes, for re-issuing old invoices."""
    return {"ES": Decimal("0.21"), "DE": Decimal("0.19"), "FR": Decimal("0.20"), "PT": Decimal("0.23"),
            "UK": Decimal("0.20")}
