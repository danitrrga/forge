#!/usr/bin/env python3
"""The Excalidraw tree reader (lib/fwx/tree.py), `fwx playbooks tree`, and playbooks/scope.tsv.

The tree is the owner's drawing, kept in private data, so every check here reads a toy tree this test builds
(six nodes, a connector, a note, a shape with no text, one arrow of each type, a legend arrow, neutral names).

Seen red before lib/fwx/tree.py existed (the whole file: `cannot import fwx.tree`):
  ModuleNotFoundError: No module named 'fwx.tree'

Each control is the toy with one change, and must fail with the message the reader gives for it:
  unknown colour #123456 on node <id>           a node border that is not in the legend
  arrow <id> has no end binding (near ...)      an arrow with one end loose
  unknown stroke #123456 solid on arrow <id>    a line that is not in the legend
  two arrows <a> -> <b> of type to              the same pair and type twice
  0 nodes: looked at nothing                    a tree with nothing in it
  a deleted node and a deleted arrow            must not be counted

Seen red, each on a copy of lib/fwx/tree.py or commands/playbooks.py with one check switched off (exit 1 each):
  colour check off:         FAIL: control: a colour outside the legend: got None
  loose binding unreported: FAIL: control: an arrow with no end binding: got None
  stroke check off:         FAIL: control: a stroke outside the legend: got None
  duplicate check off:      FAIL: control: two equal arrows between a pair: got None
  empty check off:          FAIL: control: an empty tree: got None
  deleted ones counted:     FAIL: deleted elements are ignored: err=None nodes=8 arrows=7
  legend arrows counted, connectors not read from the text, notes counted as nodes, scope.tsv checks off, the pair
  read unordered: each fails its own line above (4, 6, 1 and 2 FAILs).
  command: an unreadable tree exiting 1, --scope showing everything, no path exiting 0, exits not printed, paths.tree
  ignored: each fails its own `tree:` line.
The toy has six nodes, not five: the sixth is the `later` node, so every kind of the legend is read once.
"""
import copy
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
try:
    from fwx import tree  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.tree: %s" % e)
    sys.exit(1)

s = helpers.Suite()
ENV = {"PYTHONDONTWRITEBYTECODE": "1"}

# the legend's colours (border -> role) and strokes, as the real tree draws them
OWNER, ORCH, AGENT, SCRIPT, BLOCK, LATER, NOTE = "#b45309", "#1e3a5f", "#6d28d9", "#047857", "#64748b", "#c2410c", "#94a3b8"
SOLID, DASHED, DOTTED = "solid", "dashed", "dotted"


def shape(id, kind, stroke, text, x, y, style=SOLID, deleted=False):
    box = {"type": kind, "id": id, "x": x, "y": y, "width": 200, "height": 60, "strokeColor": stroke,
           "strokeStyle": style, "backgroundColor": "#ffffff", "isDeleted": deleted,
           "boundElements": [{"type": "text", "id": id + "_t"}] if text is not None else []}
    if text is None:
        return [box]
    label = {"type": "text", "id": id + "_t", "x": x + 10, "y": y + 10, "width": 180, "height": 40, "text": text,
             "originalText": text, "containerId": id, "isDeleted": deleted, "strokeColor": "#1f2937"}
    return [box, label]


def arrow(id, src, dst, stroke, style, label=None, deleted=False, start=True, end=True, at=(0, 0)):
    a = {"type": "arrow", "id": id, "x": at[0], "y": at[1], "width": 0, "height": 100, "strokeColor": stroke,
         "strokeStyle": style, "isDeleted": deleted, "points": [[0, 0], [0, 100]],
         "startBinding": {"elementId": src} if start else None, "endBinding": {"elementId": dst} if end else None,
         "boundElements": [{"type": "text", "id": id + "_t"}] if label else []}
    if not label:
        return [a]
    return [a, {"type": "text", "id": id + "_t", "x": at[0], "y": at[1] + 40, "width": 60, "height": 20,
                "text": label, "originalText": label, "containerId": id, "isDeleted": deleted}]


def toy(deleted_extras=False):
    e = []
    e += shape("n_owner", "rectangle", OWNER, "Alex opens\na chat", 0, 0)
    e += shape("n_orch", "ellipse", ORCH, "The orchestrator decides", 0, 200)
    e += shape("n_agent", "diamond", AGENT, "An agent reads", 0, 400)
    e += shape("n_script", "rectangle", SCRIPT, "A script checks", 0, 600)
    e += shape("n_block", "rectangle", BLOCK, "A block on an arrow", 300, 300)
    e += shape("n_later", "rectangle", LATER, "NOT BUILT YET\nsomething", 300, 600, style=DASHED)
    e += shape("n_conn", "rectangle", ORCH, "→ goes to another lane", 600, 0)
    e += shape("n_note", "rectangle", NOTE, "A remark that is not a step", 600, 200)
    e += shape("z_zone", "rectangle", OWNER, None, -50, -50, style=DASHED)
    e += shape("lg_a", "ellipse", BLOCK, None, 900, 0)
    e += shape("lg_b", "ellipse", BLOCK, None, 900, 100)
    e += arrow("a_lg", "lg_a", "lg_b", BLOCK, SOLID)
    e += arrow("a_to", "n_owner", "n_orch", BLOCK, SOLID, label="Alex asks", at=(0, 60))
    e += arrow("a_loop", "n_agent", "n_orch", ORCH, DASHED, label="it fails")
    e += arrow("a_some", "n_orch", "n_agent", BLOCK, DOTTED, label="sometimes")
    e += arrow("a_later", "n_script", "n_later", LATER, DASHED)
    e += arrow("a_ctx", "n_orch", "n_script", NOTE, DASHED, label="context")
    e += arrow("a_conn", "n_conn", "n_owner", BLOCK, SOLID)
    if deleted_extras:
        e += shape("n_gone", "rectangle", AGENT, "Deleted node", 900, 400, deleted=True)
        e += arrow("a_gone", "n_owner", "n_gone", BLOCK, SOLID, deleted=True)
    return {"type": "excalidraw", "version": 2, "elements": e}


def write_tree(data, name="tree.excalidraw"):
    d = helpers.mkdtemp("fwx-tree-")
    return helpers.write(d, name, json.dumps(data))


def read(data):
    """(tree, None) or (None, error text)."""
    try:
        return tree.read(write_tree(data)), None
    except tree.TreeError as e:
        return None, str(e)


def element(data, id):
    return next(x for x in data["elements"] if x["id"] == id)


# ---- the reader, on the good toy
t, err = read(toy())
s.eq("the good toy reads", err, None)
if t:
    s.eq("kinds by border colour", {n.id: n.kind for n in t.nodes},
         {"n_owner": "owner", "n_orch": "orchestrator", "n_agent": "agent", "n_script": "script", "n_block": "block",
          "n_later": "later", "n_conn": "connector"})
    s.eq("the node text is one line", t.node("n_owner").text, "Alex opens a chat")
    s.eq("a note is counted and is not a node", (t.notes, "n_note" in [n.id for n in t.nodes]), (1, False))
    s.eq("a shape with no text is no node", "z_zone" in [n.id for n in t.nodes], False)
    s.eq("arrows: the legend's one does not count", sorted(a.id for a in t.arrows),
         ["a_conn", "a_ctx", "a_later", "a_loop", "a_some", "a_to"])
    s.eq("arrow types from the stroke", {a.id: a.kind for a in t.arrows},
         {"a_to": "to", "a_loop": "loop", "a_some": "sometimes", "a_later": "later", "a_ctx": "context",
          "a_conn": "to"})
    s.eq("an arrow's ends and label", [(a.src, a.dst, a.label) for a in t.arrows if a.id == "a_to"],
         [("n_owner", "n_orch", "Alex asks")])
    s.eq("an arrow with no label has an empty one", t.arrow("a_later").label, "")
    s.eq("the arrows of one node", [a.id for a in t.exits("n_orch")], ["a_some", "a_ctx"])
    s.eq("arrows from a connector", sum(1 for a in t.arrows if t.node(a.src).kind == "connector"), 1)

# ---- a deleted node and a deleted arrow are not counted (control: the same toy with them alive)
t, err = read(toy(deleted_extras=True))
s.ok("deleted elements are ignored", t is not None and len(t.nodes) == 7 and len(t.arrows) == 6,
     "err=%s nodes=%s arrows=%s" % (err, t and len(t.nodes), t and len(t.arrows)))
alive = toy(deleted_extras=True)
for x in alive["elements"]:
    x["isDeleted"] = False
t, err = read(alive)
s.ok("control: the same elements not deleted do count", t is not None and len(t.nodes) == 8 and len(t.arrows) == 7,
     "err=%s nodes=%s arrows=%s" % (err, t and len(t.nodes), t and len(t.arrows)))

# ---- mutations: each must fail with its message
bad = toy()
element(bad, "n_agent")["strokeColor"] = "#123456"
_, err = read(bad)
s.ok("control: a colour outside the legend", err and "unknown colour #123456 on node n_agent" in err, "got %r" % err)

bad = toy()
element(bad, "a_loop")["endBinding"] = None
_, err = read(bad)
s.ok("control: an arrow with no end binding",
     err and "arrow a_loop has no end binding" in err and "it fails" in err, "got %r" % err)

bad = toy()
element(bad, "a_to")["startBinding"] = None
element(bad, "a_to_t")["isDeleted"] = True
element(bad, "a_to")["boundElements"] = []
element(bad, "a_to")["x"], element(bad, "a_to")["y"] = 500, 500
bad["elements"] += shape("n_near", "rectangle", BLOCK, "A text next to the loose end", 480, 490)
_, err = read(bad)
s.ok("control: a loose start names the nearest text",
     err and "arrow a_to has no start binding" in err and "A text next to the loose end" in err, "got %r" % err)

bad = toy()
element(bad, "a_some")["strokeColor"] = "#123456"
_, err = read(bad)
s.ok("control: a stroke outside the legend", err and "unknown stroke #123456 dotted on arrow a_some" in err,
     "got %r" % err)

bad = toy()
element(bad, "a_to")["strokeStyle"] = "dotted"
element(bad, "a_to")["strokeColor"] = LATER
_, err = read(bad)
s.ok("control: a colour and a style that the legend does not pair",
     err and "unknown stroke %s dotted on arrow a_to" % LATER in err, "got %r" % err)

bad = toy()
bad["elements"] += arrow("a_to2", "n_owner", "n_orch", BLOCK, SOLID)
_, err = read(bad)
s.ok("control: two equal arrows between a pair",
     err and "two arrows n_owner -> n_orch of type to" in err and "a_to" in err and "a_to2" in err, "got %r" % err)

bad = toy()
bad["elements"] += arrow("a_back", "n_orch", "n_owner", BLOCK, SOLID)
_, err = read(bad)
s.eq("control of the control: the reverse pair is not a duplicate", err, None)

bad = toy()
bad["elements"] += arrow("a_loop2", "n_agent", "n_orch", ORCH, DASHED)
_, err = read(bad)
s.ok("control: the same pair twice with another type is fine only when the type differs",
     err and "two arrows n_agent -> n_orch of type loop" in err, "got %r" % err)
bad = toy()
bad["elements"] += arrow("a_to3", "n_agent", "n_orch", BLOCK, SOLID)
_, err = read(bad)
s.eq("a different type on the same pair is fine", err, None)

bad = toy()
bad["elements"] += arrow("a_end", "n_owner", "z_zone", BLOCK, SOLID)
_, err = read(bad)
s.ok("control: an arrow to a shape with no text", err and "arrow a_end" in err and "z_zone" in err, "got %r" % err)

bad = toy()
bad["elements"] += arrow("a_nt", "n_owner", "n_note", BLOCK, SOLID)
_, err = read(bad)
s.ok("control: an arrow to a note", err and "arrow a_nt" in err and "note" in err, "got %r" % err)

_, err = read({"type": "excalidraw", "elements": []})
s.ok("control: an empty tree", err and "0 nodes: looked at nothing" in err, "got %r" % err)

_, err = read({"type": "excalidraw", "elements": toy()["elements"][:0] + shape("z", "rectangle", OWNER, None, 0, 0)})
s.ok("control: a tree of shapes with no text", err and "0 nodes: looked at nothing" in err, "got %r" % err)

# ---- the file itself
d = helpers.mkdtemp("fwx-tree-")
try:
    tree.read(os.path.join(d, "absent.excalidraw"))
    s.ok("a missing file", False, "no error")
except tree.TreeError as e:
    s.ok("a missing file", "absent.excalidraw" in str(e), str(e))
try:
    tree.read(helpers.write(d, "broken.excalidraw", "{not json"))
    s.ok("a file that is not JSON", False, "no error")
except tree.TreeError as e:
    s.ok("a file that is not JSON", "not valid JSON" in str(e), str(e))
try:
    tree.read(helpers.write(d, "other.json", '{"type": "not-excalidraw", "elements": []}'))
    s.ok("a JSON that is not an Excalidraw file", False, "no error")
except tree.TreeError as e:
    s.ok("a JSON that is not an Excalidraw file", "not an Excalidraw" in str(e), str(e))

# ---- scope.tsv: the reader
rows = helpers.write(d, "scope.tsv", "# a comment\n\nn_owner\tsession\nn_orch\texecute\n")
s.eq("scope.tsv: rows, comments and blank lines", tree.read_scope(rows), {"n_owner": "session", "n_orch": "execute"})
for label, text, needle in (("a row with one column", "n_owner\n", "n_owner"),
                            ("an id twice", "n_owner\tsession\nn_owner\texecute\n", "twice"),
                            ("an unknown playbook", "n_owner\tnosuch\n", "nosuch")):
    try:
        tree.read_scope(helpers.write(d, "bad.tsv", text))
        s.ok("control: scope.tsv with %s" % label, False, "no error")
    except tree.TreeError as e:
        s.ok("control: scope.tsv with %s" % label, needle in str(e), str(e))

# ---- the command, in a copy of the code with a toy scope.tsv of its own
code = helpers.mkdtemp("fwx-code-")
for top in ("bin", "lib"):
    shutil.copytree(os.path.join(helpers.ROOT, top), os.path.join(code, top),
                    ignore=shutil.ignore_patterns("__pycache__"))
helpers.write(code, "playbooks/scope.tsv", "n_owner\tsession\nn_orch\tsession\nn_agent\texecute\nn_conn\tconnector\n")
toy_path = write_tree(toy())


def cli(*args, cwd=None, **env):
    import subprocess
    return subprocess.run([sys.executable, os.path.join(code, "bin", "fwx"), "playbooks"] + list(args),
                           cwd=cwd or code, env=helpers.clean_env(**ENV, **env), capture_output=True, text=True)


r = cli("tree", "--tree", toy_path)
s.eq("tree: exit code", r.returncode, 0)
lines = r.stdout.splitlines()
s.eq("tree: a node line is `id | kind | scope | text`", lines[0], "n_owner | owner | session | Alex opens a chat")
s.ok("tree: its exits sit under it, `kind id «label»`", lines[1:2] == ["    to n_orch «Alex asks»"], "got %r" % lines[1:2])
s.ok("tree: a node with no scope row says `-`", "n_block | block | - | A block on an arrow" in lines, r.stdout)
s.ok("tree: a connector line", "n_conn | connector | connector | → goes to another lane" in lines, r.stdout)
s.ok("tree: an exit with no label has no guillemets", "    later n_later" in lines, r.stdout)
s.eq("tree: the counts close the output", lines[-1], "6 nodes, 1 connectors, 1 notes, 6 arrows (1 from a connector)")

r = cli("tree", "--tree", toy_path, "--scope", "session")
s.eq("tree --scope: exit code", r.returncode, 0)
ids = [ln.split(" | ")[0] for ln in r.stdout.splitlines() if " | " in ln]
s.eq("tree --scope: only that playbook's nodes", ids, ["n_owner", "n_orch"])
r = cli("tree", "--tree", toy_path, "--scope", "nosuch")
s.ok("tree --scope nosuch: exit 2 and the valid names", r.returncode == 2 and "session" in r.stderr, r.stderr)

r = cli("tree", "--tree", os.path.join(code, "absent"))
s.ok("tree: a missing file exits 2", r.returncode == 2 and "absent" in r.stderr and "Traceback" not in r.stderr, r.stderr)
bad = toy()
element(bad, "n_agent")["strokeColor"] = "#123456"
r = cli("tree", "--tree", write_tree(bad))
s.ok("tree: a tree with a fault exits 1 and says it",
     r.returncode == 1 and "unknown colour #123456 on node n_agent" in r.stderr and r.stdout == "", "%s %r" % (r.returncode, r.stderr))

repo = helpers.toy_repo()
r = cli("tree", cwd=repo)
s.ok("tree: no path anywhere exits 2 and says how to give one",
     r.returncode == 2 and "--tree" in r.stderr and "paths.tree" in r.stderr, "%s %r" % (r.returncode, r.stderr))
helpers.write(repo, ".claude/fwx.json", json.dumps({"schema": 1, "paths": {"tree": toy_path}}))
r = cli("tree", cwd=repo)
s.ok("tree: the path defaults to paths.tree", r.returncode == 0 and "n_owner | owner" in r.stdout, "%s %r" % (r.returncode, r.stderr))
wt = helpers.add_worktree(repo, "side")
r = cli("tree", cwd=wt)
s.ok("tree: paths.tree is found from a worktree", r.returncode == 0 and "n_owner | owner" in r.stdout, "%s %r" % (r.returncode, r.stderr))
r = cli("tree", "--tree", toy_path, cwd=repo)
s.eq("tree: --tree wins over paths.tree", r.returncode, 0)

for args, label in (([], "no subcommand"), (["nosuch"], "an unknown subcommand"), (["tree", "extra"], "a stray argument"),
                    (["tree", "--tree"], "--tree with no value")):
    r = cli(*args)
    s.ok("playbooks %s: usage and exit 2" % label, r.returncode == 2 and "usage" in r.stderr and "Traceback" not in r.stderr,
         "%s %r" % (r.returncode, r.stderr))

# ---- the real scope.tsv, without the real tree: its shape (the tree is private; U7's check compares them)
real = tree.read_scope(os.path.join(helpers.ROOT, "playbooks", "scope.tsv"))
per = {}
for pb in real.values():
    per[pb] = per.get(pb, 0) + 1
s.eq("scope.tsv rows per playbook", per,
     {"session": 23, "execute": 10, "ui-walk": 3, "factory": 18, "improve": 23, "engine-review": 1,
      "project-config": 1, "connector": 15})
s.eq("scope.tsv holds every node and connector of the real tree", len(real), 94)

s.done()
