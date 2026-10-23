from labels.address import format_address
from labels.dates import format_delivery_date


def label_fields(shipment):
    """The printed fields of a label, in print order."""
    return {
        "to": format_address(shipment["address"]),
        "deliver": format_delivery_date(shipment["delivery_date"]),
        "ref": shipment["ref"],
    }


def render_label(shipment):
    import acme_barcode  # only installed on the packing-station image

    fields = label_fields(shipment)
    label = acme_barcode.Label(width_mm=100, height_mm=150)
    for name, value in fields.items():
        label.text(name, value if isinstance(value, str) else "\n".join(value))
    label.barcode(acme_barcode.CODE128, shipment["ref"])
    return label
