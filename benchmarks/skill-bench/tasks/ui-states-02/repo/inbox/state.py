"""State of the notifications panel."""

INITIAL = {"items": []}


def reduce(state, event):
    """The state after one event. Never mutates `state`."""
    if event["type"] == "fetch_succeeded":
        return {**state, "items": list(event["items"])}
    return state
