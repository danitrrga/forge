from shop.emails.common import footer, greeting


def render(event):
    o = event.order
    subject = "Payment problem with order %s" % o.id
    body = "\n\n".join([
        greeting(o),
        "We couldn't take payment for your order (%s). It is on hold until the payment goes through." % event.reason,
        "Update your payment details: https://shop.example.test/orders/%s/pay" % o.id,
        footer(),
    ])
    return subject, body
