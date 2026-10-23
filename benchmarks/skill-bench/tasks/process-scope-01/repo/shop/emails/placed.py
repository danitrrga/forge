from shop.emails.common import footer, greeting, money


def render(event):
    o = event.order
    subject = "Order %s confirmed" % o.id
    body = "\n\n".join([
        greeting(o),
        "Thanks for your order! We've received it and will email you again when it ships.",
        "Order total: %s" % money(o.total_cents),
        footer(),
    ])
    return subject, body
