"""The reader of the workflow tree, an Excalidraw file: its nodes, its arrows, and playbooks/scope.tsv.

The tree is a drawing the owner edits, so this module only reads it and says what is wrong with it; it never
writes it. A node is identified by the id of its Excalidraw element, which does not depend on the language of
its text.

Node: a rectangle, ellipse or diamond with text of its own, deleted elements ignored. Its kind is the border
colour of the tree's legend (NODE_COLOURS); a colour outside it is an error. A node whose text starts with an
arrow character is a `connector` (it carries no block and is a legal destination of an exit); a light grey
figure is a note, counted and otherwise ignored. A figure with no text (a zone, a legend swatch) is nothing.
Arrow: joins two nodes by its bindings; its kind is read from its stroke (ARROW_STROKES). An arrow between
two figures with no text is the legend's and does not count. Anything else wrong with an arrow is an error.

Imports only the standard library.
"""
import json
import math
import os
import re

NODE_COLOURS = {"#b45309": "owner", "#1e3a5f": "orchestrator", "#6d28d9": "agent", "#047857": "script",
                "#64748b": "block", "#c2410c": "later", "#94a3b8": "note"}
ARROW_STROKES = {("#64748b", "solid"): "to", ("#1e3a5f", "dashed"): "loop", ("#64748b", "dotted"): "sometimes",
                 ("#c2410c", "dashed"): "later", ("#94a3b8", "dashed"): "context"}
SHAPES = ("rectangle", "ellipse", "diamond")
CONNECTOR_MARKS = ("→", "←")
PLAYBOOKS = ("session", "execute", "ui-walk", "factory", "improve", "engine-review", "project-config", "connector")
SCOPE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
                          "playbooks", "scope.tsv")


class TreeError(Exception):
    """The tree or the scope file cannot be used; the message says what to change (one problem per line)."""


class Unreadable(TreeError):
    """The file cannot be opened or is not JSON: not a fault of the drawing but of the path."""


class Node:
    def __init__(self, id, kind, text):
        self.id, self.kind, self.text = id, kind, text


class Arrow:
    def __init__(self, id, kind, src, dst, label):
        self.id, self.kind, self.src, self.dst, self.label = id, kind, src, dst, label


class Tree:
    def __init__(self, nodes, arrows, notes):
        self.nodes, self.arrows, self.notes = nodes, arrows, notes  # nodes include the connectors
        self._by_id = {n.id: n for n in nodes}

    def node(self, id):
        return self._by_id[id]

    def arrow(self, id):
        return next(a for a in self.arrows if a.id == id)

    def exits(self, id):
        return [a for a in self.arrows if a.src == id]


def _one_line(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _distance(el, point):
    """How far `point` is from the box of the text element `el` (0 inside it)."""
    x, y = point
    dx = max(el["x"] - x, 0, x - (el["x"] + el.get("width", 0)))
    dy = max(el["y"] - y, 0, y - (el["y"] + el.get("height", 0)))
    return math.hypot(dx, dy)


def _near(arrow, end, label, texts):
    """The text to name a loose arrow by: its own label, else the live text closest to the loose end."""
    if label:
        return label
    pts = arrow.get("points") or [[0, 0]]
    dx, dy = pts[0] if end == "start" else pts[-1]
    point = (arrow.get("x", 0) + dx, arrow.get("y", 0) + dy)
    best = min(texts, key=lambda t: _distance(t, point), default=None)
    return _one_line(best.get("originalText") or best.get("text")) if best else ""


def parse(data):
    """The Tree of a loaded Excalidraw document; TreeError lists every fault found."""
    if not isinstance(data, dict) or data.get("type") != "excalidraw" or not isinstance(data.get("elements"), list):
        raise TreeError("not an Excalidraw file: expected a JSON object with type \"excalidraw\" and an elements list")
    live = [e for e in data["elements"] if isinstance(e, dict) and not e.get("isDeleted")]
    by_id = {e["id"]: e for e in live if "id" in e}
    texts = [e for e in live if e.get("type") == "text"]
    own_text = {}
    for t in texts:
        if t.get("containerId"):
            own_text.setdefault(t["containerId"], []).append(_one_line(t.get("originalText") or t.get("text")))
    errors, nodes, notes, drawn = [], [], 0, {}  # drawn: id -> node, or "note", for every figure with text
    for e in live:
        if e.get("type") not in SHAPES:
            continue
        text = " ".join(t for t in own_text.get(e["id"], []) if t)
        if not text:
            continue
        colour = (e.get("strokeColor") or "").lower()
        if colour not in NODE_COLOURS:
            errors.append("unknown colour %s on node %s «%s»: the legend has %s"
                          % (colour, e["id"], text, ", ".join(sorted(NODE_COLOURS))))
            continue
        if NODE_COLOURS[colour] == "note":
            notes += 1
            drawn[e["id"]] = "note"
            continue
        kind = "connector" if text.startswith(CONNECTOR_MARKS) else NODE_COLOURS[colour]
        drawn[e["id"]] = Node(e["id"], kind, text)
        nodes.append(drawn[e["id"]])
    arrows, seen = [], {}
    for e in live:
        if e.get("type") != "arrow":
            continue
        label = " ".join(t for t in own_text.get(e["id"], []) if t)
        ends, loose = [], False
        for end, key in (("start", "startBinding"), ("end", "endBinding")):
            b = e.get(key)
            target = b.get("elementId") if isinstance(b, dict) else None
            if target is None:
                errors.append("arrow %s has no %s binding (near text «%s»): bind it to a node"
                              % (e["id"], end, _near(e, end, label, texts)))
                loose = True
            elif target not in by_id:
                errors.append("arrow %s %s is bound to %s, which is deleted or missing (near text «%s»)"
                              % (e["id"], end, target, _near(e, end, label, texts)))
                loose = True
            ends.append(target)
        if loose:
            continue
        src, dst = ends
        if not any(t in drawn for t in ends) and all(by_id[t].get("type") in SHAPES for t in ends):
            continue  # between two figures with no text: the legend's arrow
        bad = [t for t in ends if not isinstance(drawn.get(t), Node)]
        if bad:
            what = "a note" if any(drawn.get(t) == "note" for t in bad) else "a figure with no text"
            errors.append("arrow %s ends at %s (%s): arrows join nodes (near text «%s»)"
                          % (e["id"], what, ", ".join(bad), _near(e, "end", label, texts)))
            continue
        colour, style = (e.get("strokeColor") or "").lower(), e.get("strokeStyle") or "solid"
        kind = ARROW_STROKES.get((colour, style))
        if kind is None:
            errors.append("unknown stroke %s %s on arrow %s (%s -> %s): the legend has %s"
                          % (colour, style, e["id"], src, dst,
                             ", ".join("%s %s" % k for k in sorted(ARROW_STROKES))))
            continue
        seen.setdefault((src, dst, kind), []).append(e["id"])
        arrows.append(Arrow(e["id"], kind, src, dst, label))
    for (src, dst, kind), ids in seen.items():
        if len(ids) > 1:
            errors.append("two arrows %s -> %s of type %s: %s; delete one" % (src, dst, kind, ", ".join(ids)))
    if not nodes:
        errors.append("0 nodes: looked at nothing")
    if errors:
        raise TreeError("\n".join(errors))
    return Tree(nodes, arrows, notes)


def read(path):
    """The Tree of the Excalidraw file at `path`."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise Unreadable("cannot read the tree %s (%s)" % (path, e.strerror))
    except ValueError as e:
        raise Unreadable("the tree %s is not valid JSON (%s)" % (path, e))
    try:
        return parse(data)
    except TreeError as e:
        raise TreeError("%s: %s" % (path, e) if str(e).startswith("not an Excalidraw") else str(e))


def read_scope(path=SCOPE_FILE):
    """{element id: playbook name} from a scope file (`id<TAB>playbook`; `#` comments and blank lines skipped)."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        raise Unreadable("cannot read the scope file %s (%s)" % (path, e.strerror))
    scope, errors = {}, []
    for n, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) != 2 or not all(c.strip() for c in cols):
            errors.append("%s:%d: expected `id<TAB>playbook`, got %r (node %s)" % (path, n, line, cols[0]))
        elif cols[1] not in PLAYBOOKS:
            errors.append("%s:%d: unknown playbook %r for %s (playbooks: %s)" % (path, n, cols[1], cols[0], ", ".join(PLAYBOOKS)))
        elif cols[0] in scope:
            errors.append("%s:%d: %s twice" % (path, n, cols[0]))
        else:
            scope[cols[0]] = cols[1]
    if errors:
        raise TreeError("\n".join(errors))
    return scope
