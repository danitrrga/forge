"""HTML for the customer pages."""
from html import escape

from . import api


def _order_row(order):
    return ('<li class="order"><span class="order__id">%s</span> <span class="order__date">%s</span> '
            '<span class="order__total">%s</span> <span class="order__status">%s</span></li>'
            % (escape(order["id"]), escape(order["placed_on"]), escape(order["total"]), escape(order["status"])))


def render_orders(customer_id, transport=None):
    """The 'Your orders' section for one customer."""
    orders = api.fetch_orders(customer_id, transport)
    if not orders:
        body = '<p class="empty">You have no orders yet.</p>'
    else:
        body = '<ul class="order-list">%s</ul>' % "".join(_order_row(o) for o in orders)
    return '<section class="orders"><h1>Your orders</h1>%s</section>' % body
