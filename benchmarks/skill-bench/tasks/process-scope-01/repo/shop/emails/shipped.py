from shop.emails.common import footer, greeting


def render(event):
    o = event.order
    subject = "Order %s is on its way" % o.id
    body = "\n\n".join([
        greeting(o),
        "Good news: your order has left our warehouse with %s." % event.shipment.carrier,
        footer(),
    ])
    return subject, body
