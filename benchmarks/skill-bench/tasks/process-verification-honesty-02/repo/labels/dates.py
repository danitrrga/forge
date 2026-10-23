def format_delivery_date(d):
    """The delivery date as printed on the label, e.g. '09 Mar'."""
    return d.strftime("%d %b")
