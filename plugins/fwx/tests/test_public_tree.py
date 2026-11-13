#!/usr/bin/env python3
"""scripts/public_tree.py (the public workflow tree, derived from the private one) and docs/workflow-tree.excalidraw.

Checked on a toy scene with its own tables (the module's tables are replaced for the toy):
  - every node (rectangle, ellipse, diamond, frame) survives with its id, position and size;
  - the text of a node is the table's title, wrapped, inside the node;
  - a label on an arrow that leaves a diamond is kept as the table words it; a label on any other arrow is
    deleted, with its text element and the reference to it; free text not in the table, and the lists inside
    a frame, are deleted; the frame is fitted to what is left;
  - an arrow in DROP_ARROWS and an arrow of the context style are deleted; the arrows that stay keep their bindings;
  - no reference dangles: boundElements, containerId, frameId and the bindings of every arrow name elements
    that exist, checked by `check_refs` below, which is independent of the script's own `problems`;
  - `index` is unique, sorted and valid, and the output is the same bytes on a second run;
  - the input is not changed.
And on the committed output: it is a sound scene with the nodes of the tree (rectangles, ellipses, diamonds,
frames), and a toy repo holding it passes `forge lint` (no person, no private project, no home path), while
a toy repo with a home path in the same file fails it. NOT RUN, NOT ARMED when forge is not at FORGE_ROOT or two
folders above this plugin. With FWX_PRIVATE_TREE set to the private tree, the committed output must also equal
what the script derives from it now (drift); without it that check prints NOT RUN, NOT ARMED.

Controls (each toy is the good one with one change and must fail with the message given):
  - a node with text and no title:      public_tree: ... has no entry in TITLES (exit 1, nothing written)
  - a title for an element not in tree: TITLES names n_x, which is not a node with text in the tree
  - a diamond exit with a label and no word: leaves a diamond with a label and has no entry in ARROW_LABELS
  - a drop that leaves a node alone:    node b would be left with no arrow
  - a dangling reference (made by hand in the output): check_refs reports it, so the check can fail
Seen red before the script existed: FAIL: scripts/public_tree.py does not exist (every check below it fails
the same way). Seen red again on a copy of the script with one rule switched off (`if <rule>:` made `if False:`):
  - the label of an arrow that leaves a rectangle kept:   FAIL: label on an arrow that does not leave a diamond is deleted
  - boundElements not cleaned after a drop:               FAIL: no reference dangles: got ['a.boundElements -> a_c', ...], want []
"""
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()
ROOT = helpers.ROOT
SCRIPT = os.path.join(ROOT, "scripts", "public_tree.py")
OUTPUT = os.path.join(ROOT, "docs", "workflow-tree.excalidraw")
NODES = ("rectangle", "ellipse", "diamond", "frame")

if not os.path.isfile(SCRIPT):
    s.ok("scripts/public_tree.py exists", False, "scripts/public_tree.py does not exist")
    s.done()


def load_module(path, name="public_tree_under_test"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def el(id, type, x=0, y=0, w=200, h=80, **kw):
    e = {"id": id, "type": type, "x": x, "y": y, "width": w, "height": h, "isDeleted": False, "boundElements": [],
         "strokeColor": "#64748b", "strokeStyle": "solid", "frameId": None, "index": "a0"}
    e.update(kw)
    return e


def text(id, container, content, fs=16, **kw):
    return el(id, "text", 5, 5, 100, 20, text=content, originalText=content, fontSize=fs, containerId=container,
              textAlign="center", **kw)


def arrow(id, src, dst, **kw):
    return el(id, "arrow", 0, 0, 10, 10, startBinding={"elementId": src}, endBinding={"elementId": dst},
              points=[[0, 0], [0, 10]], **kw)


def bind(scene, owner, *ids):
    by = {e["id"]: e for e in scene}
    by[owner]["boundElements"] += [{"type": by[i]["type"], "id": i} for i in ids]


def toy():
    """a (rectangle) -> q (diamond) -> b (ellipse) and -> c (rectangle); a -> c (to drop); a -> q context;
    labels on a->q (rectangle source) and q->b, q->c (diamond source); one frame with a title, a kept text, a list."""
    els = [el("zone", "rectangle", 0, 0, 900, 900),
           el("a", "rectangle", 100, 100, 220, 90), text("a_t", "a", "texto de a"),
           el("q", "diamond", 100, 300, 260, 120), text("q_t", "q", "pregunta"),
           el("b", "ellipse", 100, 560, 240, 110), text("b_t", "b", "texto de b"),
           el("c", "rectangle", 500, 560, 200, 80), text("c_t", "c", "texto de c"),
           arrow("a_q", "a", "q"), text("a_q_l", "a_q", "se pasa"),
           arrow("q_b", "q", "b"), text("q_b_l", "q_b", "si"),
           arrow("q_c", "q", "c"), text("q_c_l", "q_c", "no"),
           arrow("a_c", "a", "c"), text("a_c_l", "a_c", "por la derecha"),
           arrow("ctx", "a", "q", strokeColor="#94a3b8", strokeStyle="dashed"),
           el("note", "text", 700, 10, 100, 20, text="suelto", originalText="suelto", fontSize=16, containerId=None),
           el("heading", "text", 700, 40, 100, 20, text="titulo", originalText="titulo", fontSize=16, containerId=None),
           el("fr", "frame", 1000, 0, 1400, 600, name="marco"),
           el("fr_t", "text", 1030, 30, 300, 35, text="titulo del marco", originalText="titulo del marco", fontSize=28,
              containerId=None, frameId="fr"),
           el("fr_gist", "text", 1030, 80, 900, 20, text="uno", originalText="uno", fontSize=16, containerId=None,
              frameId="fr"),
           el("fr_list", "text", 1030, 120, 900, 400, text="a\nb\nc", originalText="a\nb\nc", fontSize=16,
              containerId=None, frameId="fr")]
    for owner, kids in (("a", ["a_t"]), ("q", ["q_t"]), ("b", ["b_t"]), ("c", ["c_t"]), ("a_q", ["a_q_l"]),
                        ("q_b", ["q_b_l"]), ("q_c", ["q_c_l"]), ("a_c", ["a_c_l"])):
        bind(els, owner, *kids)
    bind(els, "a", "a_q", "a_c", "ctx")
    bind(els, "q", "a_q", "q_b", "q_c", "ctx")
    bind(els, "b", "q_b")
    bind(els, "c", "q_c", "a_c")
    return {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com", "elements": els,
            "appState": {"viewBackgroundColor": "#ffffff"}, "files": {}}


def set_tables(mod, **over):
    mod.TITLES = {"a": "Step A", "q": "Is it fine?", "b": "End B", "c": "Step C"}
    mod.ARROW_LABELS = {"q_b": "yes", "q_c": "no"}
    mod.DROP_ARROWS = ("a_c",)
    mod.FREE_TEXTS = {"heading": "Heading"}
    mod.FRAMES = {"fr": ("The frame", "fr_t", [("fr_gist", "One short paragraph.")])}
    mod.STACK_UNDER = {}
    for k, v in over.items():
        setattr(mod, k, v)


def check_refs(scene):
    """Dangling references of a scene, written here and not taken from the script, so that the two can disagree."""
    ids = {e["id"] for e in scene["elements"]}
    bad = []
    for e in scene["elements"]:
        bad += ["%s.boundElements -> %s" % (e["id"], b["id"]) for b in e.get("boundElements") or [] if b["id"] not in ids]
        if e.get("containerId") and e["containerId"] not in ids:
            bad.append("%s.containerId -> %s" % (e["id"], e["containerId"]))
        if e.get("frameId") and e["frameId"] not in ids:
            bad.append("%s.frameId -> %s" % (e["id"], e["frameId"]))
        for k in ("startBinding", "endBinding"):
            if e.get(k) and e[k]["elementId"] not in ids:
                bad.append("%s.%s -> %s" % (e["id"], k, e[k]["elementId"]))
    return bad


def valid_index(k):
    """A fractional index as Excalidraw's library takes it: a head letter a-z fixing the length of the integer part
    (a -> 2 characters, b -> 3...), base 62 digits, and no trailing zero in a fractional part."""
    if not re.fullmatch(r"[a-z][0-9A-Za-z]+", k):
        return False
    n = ord(k[0]) - ord("a") + 2
    return len(k) >= n and not (len(k) > n and k.endswith("0"))


mod = load_module(SCRIPT)
set_tables(mod)
src = toy()
frozen = json.dumps(src, sort_keys=True)
out = mod.derive(src)
by = {e["id"]: e for e in out["elements"]}
ids = set(by)
s.eq("the input is not changed", json.dumps(src, sort_keys=True), frozen)

for e in src["elements"]:
    if e["type"] in NODES:
        o = by.get(e["id"])
        s.ok("node %s survives" % e["id"], o is not None and o["type"] == e["type"])
        if o and e["type"] != "frame":
            s.eq("node %s keeps its place and size" % e["id"], [o[k] for k in ("x", "y", "width", "height")],
                 [e[k] for k in ("x", "y", "width", "height")])
s.eq("the nodes, counted, are the same",
     sorted(e["id"] for e in out["elements"] if e["type"] in NODES),
     sorted(e["id"] for e in src["elements"] if e["type"] in NODES))

for nid, title in (("a", "Step A"), ("q", "Is it fine?"), ("b", "End B"), ("c", "Step C")):
    t = by.get(nid + "_t")
    s.ok("node %s has its title" % nid, t is not None and t["text"].replace("\n", " ") == title,
         "got %r" % (t and t["text"]))
    if t:
        n = by[nid]
        s.ok("the text of %s is inside it" % nid, t["x"] >= n["x"] and t["y"] >= n["y"]
             and t["x"] + t["width"] <= n["x"] + n["width"] and t["y"] + t["height"] <= n["y"] + n["height"])

s.ok("label on an arrow that does not leave a diamond is deleted", "a_q_l" not in ids and "a_c_l" not in ids)
s.eq("label on an arrow that leaves a diamond is kept, as the table words it",
     (by["q_b_l"]["text"], by["q_c_l"]["text"]), ("yes", "no"))
s.ok("the deleted label is no longer in its arrow's boundElements",
     all(b["id"] != "a_q_l" for b in by["a_q"]["boundElements"]))
s.ok("an arrow in DROP_ARROWS is gone, with its label", "a_c" not in ids and "a_c_l" not in ids)
s.ok("an arrow of the context style is gone", "ctx" not in ids)
s.eq("the arrows that stay keep their bindings",
     [(by[a]["startBinding"]["elementId"], by[a]["endBinding"]["elementId"]) for a in ("a_q", "q_b", "q_c")],
     [("a", "q"), ("q", "b"), ("q", "c")])
s.ok("the drops are gone from the nodes' boundElements",
     all(b["id"] not in ("a_c", "ctx") for n in ("a", "c", "q") for b in by[n]["boundElements"]))
s.ok("free text in the table stays, as worded", by.get("heading", {}).get("text") == "Heading")
s.ok("free text not in the table is deleted", "note" not in ids)
s.ok("the list inside a frame is deleted", "fr_list" not in ids)
s.eq("the frame keeps its title and its paragraph, and is named",
     (by["fr_t"]["text"], by["fr_gist"]["text"].replace("\n", " "), by["fr"]["name"]),
     ("The frame", "One short paragraph.", "The frame"))
f = by["fr"]
s.ok("the frame is fitted to what is left", f["height"] < 600 and f["width"] < 1400
     and all(f["x"] <= by[t]["x"] and by[t]["x"] + by[t]["width"] <= f["x"] + f["width"]
             and by[t]["y"] + by[t]["height"] <= f["y"] + f["height"] for t in ("fr_t", "fr_gist")),
     "frame %sx%s" % (f["width"], f["height"]))
s.eq("no reference dangles", check_refs(out), [])
s.eq("the script's own check agrees", mod.problems(out), [])
keys = [e["index"] for e in out["elements"]]
s.ok("index is unique, sorted and valid", len(set(keys)) == len(keys) and keys == sorted(keys)
     and all(valid_index(k) for k in keys), str(keys[:6]))
s.eq("the same input gives the same output", json.dumps(mod.derive(toy())), json.dumps(out))

# many elements: the index sequence stays valid and sorted past the first hundreds
seq = [mod.order_key(i) for i in range(5000)]
s.ok("order_key: 5000 keys, sorted, unique, valid", seq == sorted(seq) and len(set(seq)) == 5000
     and all(valid_index(k) for k in seq))

# the command line: writes the file, the same bytes twice, and refuses without writing
d = helpers.mkdtemp("fwx-pubtree-")
inp, o1, o2 = (os.path.join(d, n) for n in ("in.json", "o1.json", "o2.json"))
with open(inp, "w") as fh:
    json.dump(toy(), fh)
runner = os.path.join(d, "run.py")
with open(runner, "w") as fh:  # the CLI with the toy tables, on a copy of the script
    fh.write("import sys, importlib.util\nspec = importlib.util.spec_from_file_location('pt', %r)\n"
             "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
             "m.TITLES = {'a': 'Step A', 'q': 'Is it fine?', 'b': 'End B', 'c': 'Step C'}\n"
             "m.ARROW_LABELS = {'q_b': 'yes', 'q_c': 'no'}; m.DROP_ARROWS = ('a_c',); m.FREE_TEXTS = {'heading': 'Heading'}\n"
             "m.FRAMES = {'fr': ('The frame', 'fr_t', [('fr_gist', 'One short paragraph.')])}; m.STACK_UNDER = {}\n"
             "sys.exit(m.main(['x'] + sys.argv[1:]))\n" % SCRIPT)
r1 = subprocess.run([sys.executable, "-I", runner, inp, o1], capture_output=True, text=True)
r2 = subprocess.run([sys.executable, "-I", runner, inp, o2], capture_output=True, text=True)
s.eq("CLI: exit code", (r1.returncode, r2.returncode), (0, 0))
s.ok("CLI: two runs, the same bytes", os.path.exists(o1) and open(o1, "rb").read() == open(o2, "rb").read())
s.ok("CLI: the file is JSON of an Excalidraw scene",
     os.path.exists(o1) and json.load(open(o1)).get("type") == "excalidraw", r1.stderr.strip()[:200])
r = subprocess.run([sys.executable, "-I", SCRIPT], capture_output=True, text=True)
s.eq("CLI: no arguments: exit code 2", r.returncode, 2)


def refused(label, mutate, tables, want):
    """The good toy with one change must make derive() raise with `want`, and the CLI exit 1 with nothing written."""
    m = load_module(SCRIPT, "pt_" + label.replace(" ", "_")[:20])
    set_tables(m, **tables)
    sc = toy()
    mutate(sc)
    try:
        m.derive(sc)
        got = "no error"
    except m.PublicTreeError as e:
        got = str(e)
    s.ok("control %s: refused with %r" % (label, want), want in got, "got %r" % got)


refused("a node with text and no title", lambda sc: None, {"TITLES": {"a": "A", "q": "Q", "b": "B"}},
        "node c «texto de c» has no entry in TITLES")
refused("a title for an element not in the tree", lambda sc: None,
        {"TITLES": {"a": "A", "q": "Q", "b": "B", "c": "C", "n_x": "X"}},
        "TITLES names n_x, which is not a node with text in the tree")
refused("a diamond exit with a label and no word", lambda sc: None, {"ARROW_LABELS": {"q_b": "yes"}},
        "arrow q_c leaves a diamond with a label and has no entry in ARROW_LABELS")
refused("a drop that leaves a node alone", lambda sc: None, {"DROP_ARROWS": ("a_c", "q_c", "a_q", "q_b")},
        "would be left with no arrow")
refused("a frame with no entry", lambda sc: sc["elements"].append(el("fr2", "frame", 0, 2000, 100, 100, name="x")),
        {}, "frame fr2 has no entry in FRAMES")

bad = copy.deepcopy(out)
bad["elements"] = [e for e in bad["elements"] if e["id"] != "q_b_l"]
s.ok("control a dangling reference: check_refs reports it", check_refs(bad) != [], "got %r" % check_refs(bad))
s.ok("control a dangling reference: the script's check reports it too", mod.problems(bad) != [])
worse = copy.deepcopy(out)
worse["elements"][1]["index"] = worse["elements"][2]["index"]
s.ok("control a duplicate index: the script's check reports it", any("index" in p for p in mod.problems(worse)))
s.ok("control a bad index: valid_index refuses 'd01k' (4 characters under head d)", not valid_index("d01k"))

# the committed output
if not os.path.isfile(OUTPUT):
    s.ok("docs/workflow-tree.excalidraw exists", False, "docs/workflow-tree.excalidraw does not exist")
else:
    with open(OUTPUT, encoding="utf-8") as fh:
        real = json.load(fh)
    kinds = {}
    for e in real["elements"]:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    s.ok("the committed tree has nodes of every kind (looked at %s)" % kinds,
         all(kinds.get(k, 0) > 0 for k in NODES) and kinds.get("arrow", 0) > 0 and kinds.get("text", 0) > 0)
    s.eq("the committed tree is a sound scene (script's check)", mod.problems(real), [])
    s.eq("the committed tree has no dangling reference (the test's check)", check_refs(real), [])
    s.ok("every index of the committed tree is valid, unique and sorted",
         all(valid_index(e["index"]) for e in real["elements"])
         and [e["index"] for e in real["elements"]] == sorted({e["index"] for e in real["elements"]}))
    s.ok("the committed tree has no deleted element", not any(e.get("isDeleted") for e in real["elements"]))
    dump = json.dumps(real, ensure_ascii=False)
    s.eq("no home path, no email address in the committed tree",
         re.findall(r"/home/\S+|/Users/\S+|[\w.+-]+@[\w-]+\.[\w.]+", dump), [])
    private = os.environ.get("FWX_PRIVATE_TREE")
    if private and os.path.isfile(private):
        real_mod = load_module(SCRIPT, "pt_real")
        with open(private, encoding="utf-8") as fh:
            src_real = json.load(fh)
        derived = real_mod.derive(src_real)
        s.ok("the committed tree is what the script derives from the private tree now (drift)", derived == real)
        want = {k: sum(1 for e in src_real["elements"] if e["type"] == k and not e.get("isDeleted")) for k in NODES}
        s.eq("the committed tree has as many nodes as the private one", {k: kinds.get(k, 0) for k in NODES}, want)
    else:
        print("NOT RUN, NOT ARMED: drift against the private tree (FWX_PRIVATE_TREE is not set)")

    forge_root = os.environ.get("FORGE_ROOT") or os.path.dirname(os.path.dirname(ROOT))
    forge = os.path.join(forge_root, "bin", "forge")
    if not os.access(forge, os.X_OK):
        print("NOT RUN, NOT ARMED: forge lint on the committed tree (no bin/forge at %s)" % forge_root)
    else:
        def public_check(files):
            repo = helpers.toy_repo(files)
            r = subprocess.run([sys.executable, "-I", forge, "lint", "--root", repo, "--all"],
                               capture_output=True, text=True, env=helpers.clean_env(PYTHONDONTWRITEBYTECODE="1"))
            helpers.remove(repo)
            return r
        r = public_check({"docs/workflow-tree.excalidraw": open(OUTPUT, encoding="utf-8").read()})
        s.eq("forge lint on the committed tree: exit code", r.returncode, 0)
        r = public_check({"docs/workflow-tree.excalidraw": dump.replace('"The fwx workflow"', '"%s"' % os.path.expanduser("~"), 1)})
        s.ok("control: the same file with a home path in it fails forge lint", r.returncode != 0,
             "exit code %d, output %r" % (r.returncode, (r.stdout + r.stderr)[:200]))

s.done()
