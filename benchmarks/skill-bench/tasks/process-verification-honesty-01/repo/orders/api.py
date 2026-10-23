"""The order JSON the mobile app reads. Amounts are integer cents."""


def line_to_json(line):
    return {"sku": line.sku, "qty": line.qty, "unit_cents": line.unit_cents}


def order_to_json(order):
    return {
        "id": order.id,
        "customer": order.customer,
        "status": order.status,
        "items": [line_to_json(l) for l in order.lines],
        "total": sum(l.qty * l.unit_cents for l in order.lines),
    }
