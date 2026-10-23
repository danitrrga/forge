"""HTML for the notifications panel."""
from html import escape


def render_panel(state):
    items = state["items"]
    if not items:
        body = '<p class="panel__empty">You\'re all caught up.</p>'
    else:
        body = '<ul class="panel__list">%s</ul>' % "".join(
            '<li class="panel__item" data-id="%s">%s <time>%s</time></li>'
            % (escape(i["id"]), escape(i["text"]), escape(i["when"])) for i in items)
    return '<div class="panel" aria-label="Notifications">%s</div>' % body
