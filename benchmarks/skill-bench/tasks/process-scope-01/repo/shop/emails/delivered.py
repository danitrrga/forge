from shop.emails.common import footer, greeting


def render(event):
    o = event.order
    subject = "Order %s delivered" % o.id
    body = "\n\n".join([
        greeting(o),
        "Your order was delivered on %s. We hope you enjoy it!" % event.delivered_on.strftime("%d %b %Y"),
        footer(),
    ])
    return subject, body
