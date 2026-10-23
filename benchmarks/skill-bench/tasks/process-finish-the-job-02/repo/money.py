def fmt_money(cents):
    """Integer cents as euros for the report: 123456 -> '€1,234.56'."""
    return "€{:,}.{:02d}".format(cents // 100, cents % 100)
