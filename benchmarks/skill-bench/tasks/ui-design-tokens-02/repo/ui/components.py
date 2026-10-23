"""Acme Console components. Every page is built from these; each returns an HTML string."""
from html import escape

TONES = ("info", "success", "warning", "danger")


def button(label, href=None, variant="primary"):
    """A button, or a link styled as one when href is given. variant: primary or secondary."""
    cls = "btn btn--%s" % variant
    if href:
        return '<a class="%s" href="%s">%s</a>' % (cls, escape(href), escape(label))
    return '<button class="%s" type="button">%s</button>' % (cls, escape(label))


def alert(message, tone="info", title=None, action=None):
    """A banner across the content. tone: one of TONES. action: optional (label, href) link."""
    if tone not in TONES:
        raise ValueError("unknown tone %r" % tone)
    parts = []
    if title:
        parts.append('<p class="alert__title">%s</p>' % escape(title))
    parts.append('<p class="alert__body">%s</p>' % escape(message))
    if action:
        label, href = action
        parts.append('<a class="alert__action" href="%s">%s</a>' % (escape(href), escape(label)))
    role = "alert" if tone == "danger" else "status"
    return '<div class="alert alert--%s" role="%s">%s</div>' % (tone, role, "".join(parts))


def badge(text, tone="info"):
    if tone not in TONES:
        raise ValueError("unknown tone %r" % tone)
    return '<span class="badge badge--%s">%s</span>' % (tone, escape(text))


def stat(label, value):
    return '<div class="stat"><dt class="stat__label">%s</dt><dd class="stat__value">%s</dd></div>' % (
        escape(label), escape(value))


def card(title, body_html, actions_html=""):
    actions = '<div class="card__actions">%s</div>' % actions_html if actions_html else ""
    return '<section class="card"><h2 class="card__title">%s</h2>%s%s</section>' % (escape(title), body_html, actions)
