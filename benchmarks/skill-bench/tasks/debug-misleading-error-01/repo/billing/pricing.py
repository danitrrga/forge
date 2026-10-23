from datetime import timedelta


def tax_cents(subtotal_cents, cfg):
    return round(subtotal_cents * cfg["tax_rate"])


def invoice_total(lines, cfg):
    """lines: (description, quantity, unit price in cents)."""
    subtotal = sum(qty * unit_cents for _, qty, unit_cents in lines)
    return subtotal + tax_cents(subtotal, cfg)


def late_fee_cents(amount_cents, months_late, cfg):
    return round(amount_cents * cfg["late_fee_rate"] * months_late)


def due_date(issued, cfg):
    return issued + timedelta(days=cfg["net_days"])


def format_money(cents, cfg):
    return "%s %d.%02d" % (cfg["currency"], cents // 100, cents % 100)
