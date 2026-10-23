"""Customer emails: render(event) -> (subject, body)."""
from shop import events
from shop.emails import delivered, payment_failed, placed, shipped

_RENDERERS = {
    events.OrderPlaced: placed.render,
    events.PaymentFailed: payment_failed.render,
    events.OrderShipped: shipped.render,
    events.OrderDelivered: delivered.render,
}


def render(event):
    return _RENDERERS[type(event)](event)
