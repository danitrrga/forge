"""Glue between the notifications service and the panel."""
from .render import render_panel
from .state import INITIAL, reduce


class Panel:
    def __init__(self, fetch, paint):
        """fetch() returns the items or raises; paint(html) puts the panel's HTML on screen."""
        self.fetch, self.paint = fetch, paint
        self.state = INITIAL

    def dispatch(self, event):
        self.state = reduce(self.state, event)
        self.paint(render_panel(self.state))

    def open(self):
        """Called when the bell is clicked, and again by the panel's refresh button."""
        self.dispatch({"type": "fetch_started"})
        try:
            items = self.fetch()
        except Exception as e:  # the service client raises on any failure
            self.dispatch({"type": "fetch_failed", "error": str(e)})
        else:
            self.dispatch({"type": "fetch_succeeded", "items": items})
