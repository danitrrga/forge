# Acme Desk: notifications panel

The bell-icon panel of the help desk. The panel is a small state machine: `inbox/panel.py` dispatches events to
`inbox/state.py`'s `reduce()`, and `inbox/render.py` turns the state into the panel's HTML after every event.

Events: `{"type": "fetch_started"}`, `{"type": "fetch_succeeded", "items": [...]}`,
`{"type": "fetch_failed", "error": "..."}`. An item is `{"id", "text", "when"}`.

    python3 -m unittest
