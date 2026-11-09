#!/usr/bin/env python3
"""`fwx playbooks check` against a tree (lib/fwx/playbooks.py): what compares a playbook with the Excalidraw drawing.

Two parts. First a toy tree and a toy playbook of five nodes (plus a connector), with neutral names: the good pair
passes, and each control is the pair with one change and must fail with the message the checker gives for it. Then the
real tree, which is the owner's private drawing: found through `paths.tree` of the configuration, and absent on a machine
without it, where the file ends `NOT RUN, NOT ARMED: no tree` and exits 77 (a pass of the toy part is not a pass of the
real one). With the real tree, the real playbooks/ and scope.tsv must have no problem.

Seen red before lib/fwx/playbooks.py existed (the whole file):
  FAIL: cannot import fwx.playbooks: cannot import name 'playbooks' from 'fwx'

Seen red, each on a copy of lib/fwx/playbooks.py with that one check switched off (`if <check>:` made `if False:`), the
first FAIL line each gave:
  a missing exit, an extra exit, Who script on a purple node, the box and decide_rules.json differing, a tree fault not
  reported:                  FAIL: control: <its label>: got []
  a node with no row:        FAIL: control: a node of the tree with no row in scope.tsv: got ['session.md:40 n_d exits to n_e, which is not in scope.tsv ...
  a row with no node:        FAIL: control: a row of scope.tsv with no node in the tree: got ['scope.tsv gives session.md the node n_gone and it has no block ...
  a loop written as a to (the pairing by destination removed):
                             FAIL: control: a loop written as a to: got ['n_d has no exit to n_c: «falla un check» (the loop arrow ... add `  - loop n_c: <condition>` ...
  no box of rules (check off): FAIL: control: a tree with no box of rules: got ["the merge-rule box of the tree («None», 0 rules) and decide_rules.json differ ...
  the box read is the one with fewest rules, not most:  FAIL: the good pair has no problem: got ["the merge-rule box of the tree («Otra caja», 1 rules) ...
  a block for a connector (check off): FAIL: control: a block for a connector: got ['session.md:51 n_k is in session.md but scope.tsv assigns it to connector ...
The real part was run once with `config.load` patched to name the real tree: 32 checks, exit 0.
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
    from fwx import config, playbooks  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.playbooks: %s" % e)
    sys.exit(1)

s = helpers.Suite()
ENV = {"PYTHONDONTWRITEBYTECODE": "1"}
OWNER, ORCH, AGENT, SCRIPT, BLOCK, LATER = "#b45309", "#1e3a5f", "#6d28d9", "#047857", "#64748b", "#c2410c"
SOLID, DASHED, DOTTED = "solid", "dashed", "dotted"
RULES = ["review-label", "ci-failed", "still-running"]


def shape(id, kind, stroke, text, x, y):
    box = {"type": kind, "id": id, "x": x, "y": y, "width": 200, "height": 60, "strokeColor": stroke,
           "strokeStyle": SOLID, "isDeleted": False, "boundElements": [{"type": "text", "id": id + "_t"}]}
    label = {"type": "text", "id": id + "_t", "x": x + 10, "y": y + 10, "width": 180, "height": 40, "text": text,
             "originalText": text, "containerId": id, "isDeleted": False, "strokeColor": "#1f2937"}
    return [box, label]


def arrow(id, src, dst, stroke, style, label=None):
    a = {"type": "arrow", "id": id, "x": 0, "y": 0, "width": 0, "height": 100, "strokeColor": stroke, "strokeStyle": style,
         "isDeleted": False, "points": [[0, 0], [0, 100]], "startBinding": {"elementId": src},
         "endBinding": {"elementId": dst}, "boundElements": [{"type": "text", "id": id + "_t"}] if label else []}
    if not label:
        return [a]
    return [a, {"type": "text", "id": id + "_t", "x": 0, "y": 40, "width": 60, "height": 20, "text": label,
                "originalText": label, "containerId": id, "isDeleted": False}]


def bullets(frame, ids, y):
    return [{"type": "text", "id": "%s_b%d" % (frame, i), "x": 900, "y": y + 30 * i, "width": 300, "height": 20,
             "text": "• %s: a reason" % r, "originalText": "• %s: a reason" % r, "containerId": None,
             "frameId": frame, "isDeleted": False} for i, r in enumerate(ids)]


def toy_tree(rules=RULES, n_e_colour=BLOCK):
    e = []
    e += shape("n_a", "rectangle", OWNER, "Alex abre un chat", 0, 0)
    e += shape("n_b", "ellipse", ORCH, "El orquestador decide", 0, 200)
    e += shape("n_c", "diamond", AGENT, "Un planificador escribe el plan", 0, 400)
    e += shape("n_d", "rectangle", SCRIPT, "Los checks corren", 0, 600)
    e += shape("n_e", "rectangle", n_e_colour, "Un bloque sobre una flecha", 300, 300)
    e += shape("n_k", "rectangle", ORCH, "→ sigue en otro carril", 600, 0)
    e += arrow("a_ab", "n_a", "n_b", BLOCK, SOLID, "Alex pide")
    e += arrow("a_bc", "n_b", "n_c", BLOCK, SOLID, "se quiere el plan")
    e += arrow("a_cd", "n_c", "n_d", BLOCK, SOLID, "el plan está escrito")
    e += arrow("a_dc", "n_d", "n_c", ORCH, DASHED, "falla un check")
    e += arrow("a_de", "n_d", "n_e", BLOCK, DOTTED, "un bloqueo")
    e += arrow("a_ek", "n_e", "n_k", BLOCK, SOLID, "sigue")
    e += arrow("a_ka", "n_k", "n_a", BLOCK, SOLID)
    e += [{"type": "frame", "id": "f_rules", "name": "Las reglas de fusión", "x": 880, "y": 0, "width": 500, "height": 200,
           "isDeleted": False}, {"type": "frame", "id": "f_other", "name": "Otra caja", "x": 880, "y": 400,
                                 "width": 500, "height": 100, "isDeleted": False}]
    e += bullets("f_rules", rules, 40) + bullets("f_other", ["linear-note"], 440)
    return {"type": "excalidraw", "version": 2, "elements": e}


SCOPE = {"n_a": "session", "n_b": "session", "n_c": "session", "n_d": "session", "n_e": "session", "n_k": "connector"}
GOOD = [
    dict(id="n_a", title="Alex opens a chat", who="owner", stage="discuss", writes="nothing", invokes="nothing",
         exits=[("to", "n_b", "Alex asks")]),
    dict(id="n_b", title="The orchestrator decides", who="orchestrator", stage="premortem", writes="state.md",
         invokes="nothing", exits=[("to", "n_c", "the plan is wanted")]),
    dict(id="n_c", title="A planner writes the plan", who="agent planner", stage="planning", writes="plan.md",
         invokes="nothing", exits=[("to", "n_d", "the plan is written")]),
    dict(id="n_d", title="The checks run", who="script `fwx verify`", stage="postmortem", writes="audit.tsv",
         invokes="command `fwx verify`", exits=[("loop", "n_c", "a check fails"), ("sometimes", "n_e", "a blocker")]),
    dict(id="n_e", title="A block on an arrow", who="orchestrator", stage="-", writes="nothing", invokes="nothing",
         exits=[("to", "n_k", "goes on in another lane")]),
]


def render(b):
    out = ["### %s · %s" % (b["id"], b["title"])]
    for field, key in (("Who", "who"), ("Stage", "stage"), ("Writes", "writes"), ("Invokes", "invokes")):
        out.append("- **%s:** %s" % (field, b[key]))
    out.append("- **Does:** Does one thing.")
    if b["exits"]:
        out.append("- **Exits:**")
        out += ["  - %s %s: %s" % e for e in b["exits"]]
    else:
        out.append("- **Exits:** none")
    return "\n".join(out) + "\n"


def doc(blocks):
    return "# Session\n\nVersion: 1\n\n" + "\n".join(render(b) for b in blocks)


def good():
    return copy.deepcopy(GOOD)


def run(blocks, tree_data=None, scope=SCOPE, rules=RULES):
    d = helpers.mkdtemp("fwx-pbt-")
    helpers.write(d, "scope.tsv", "".join("%s\t%s\n" % kv for kv in scope.items()))
    helpers.write(d, "session.md", doc(blocks))
    tree_path = helpers.write(d, "tree.excalidraw", json.dumps(tree_data or toy_tree()))
    rules_path = helpers.write(d, "decide_rules.json", json.dumps({"rules": [{"id": r} for r in rules]}))
    return playbooks.check(d, tree_path=tree_path, rules_path=rules_path)


def has(report, *needles):
    return any(all(n in e for n in needles) for e in report.errors)


def control(label, report, *needles):
    s.ok("control: %s" % label, has(report, *needles), "got %r" % report.errors)


# ---- the good pair passes and counts what it compared
r = run(good())
s.eq("the good pair has no problem", r.errors, [])
s.eq("it compared five blocks with six arrows (the connector's own arrow is exempt)", (r.blocks, r.arrows), (5, 6))
s.eq("the tree ran, so the exit is 0", (r.tree_ran, r.exit_code), (True, 0))
s.ok("the summary says what it compared", any("5 blocks" in l and "6 arrows" in l for l in r.lines()), "got %r" % r.lines())

# ---- one change each
r = run(good(), scope={k: v for k, v in SCOPE.items() if k != "n_e"})
control("a node of the tree with no row in scope.tsv", r, "n_e", "«Un bloque sobre una flecha»", "no row in scope.tsv")

r = run(good(), scope=dict(SCOPE, n_gone="session"))
control("a row of scope.tsv with no node in the tree", r, "scope.tsv has a row for n_gone", "no such node")

b = good()
b[3]["exits"] = [("loop", "n_c", "a check fails")]
r = run(b)
control("an exit the tree draws and the block lacks", r, "n_d has no exit to n_e: «un bloqueo»", "sometimes")
control("... with the Spanish text of the node it leaves", r, "«Los checks corren»")

b = good()
b[0]["exits"] += [("to", "n_c", "invented")]
r = run(b)
control("an exit the tree does not draw", r, "n_a", "exits to n_c", "the tree draws no such arrow", "«Alex abre un chat»")

b = good()
b[3]["exits"][0] = ("to", "n_c", "a check fails")
r = run(b)
control("a loop written as a to", r, "n_d", "written as `to`", "the tree draws `loop`", "«falla un check»")
s.eq("... and it is one problem, not a missing exit and an extra one", len(r.errors), 1)

b = good()
b[2]["who"] = "script `fwx verify`"
r = run(b)
control("Who script on a purple node", r, "n_c", "node of kind agent", "«Un planificador escribe el plan»", "Who is script")

b = good()
b[0]["who"] = "agent planner"
r = run(b)
control("Who agent on an amber node", r, "n_a", "node of kind owner", "Who is agent")

r = run(good(), toy_tree(n_e_colour=LATER))
control("a later node whose Who is not later", r, "n_e", "node of kind later", "Who is orchestrator")
b = good()
b[4]["who"] = "later"
r = run(b, toy_tree(n_e_colour=LATER))
s.eq("control of the control: Who later on a later node is right", r.errors, [])
b = good()
b[4]["who"] = "later"
r = run(b)
control("Who later on a grey block", r, "n_e", "Who is later")

r = run(good(), rules=RULES + ["new-rule"])
control("a rule in decide_rules.json that the box lacks", r, "merge-rule box", "«Las reglas de fusión»", "new-rule")
r = run(good(), rules=RULES[:2])
control("a rule in the box that decide_rules.json lacks", r, "merge-rule box", "still-running")
no_box = toy_tree(rules=[])
no_box["elements"] = [x for x in no_box["elements"] if x.get("frameId") != "f_other"]
r = run(good(), no_box)
control("a tree with no box of rules", r, "no box of merge rules")
r = run(good(), toy_tree(rules=RULES[:2]), rules=RULES[:2])
s.eq("the box with most rules is the one read: the one-bullet box is not it", r.errors, [])

b = good()
b.append(dict(id="n_zz", title="A block of no node", who="owner", stage="-", writes="nothing", invokes="nothing", exits=[]))
r = run(b, scope=dict(SCOPE, n_zz="session"))
control("a block whose row has no node in the tree", r, "scope.tsv has a row for n_zz")
r = run(b)
control("a block whose id is nowhere", r, "n_zz", "not in scope.tsv")

bad_tree = toy_tree()
next(x for x in bad_tree["elements"] if x["id"] == "n_c")["strokeColor"] = "#123456"
r = run(good(), bad_tree)
s.ok("control: a tree with a fault is a problem, and says which", has(r, "the tree has faults", "unknown colour #123456 on node n_c")
     and r.exit_code == 1, "got %r" % r.errors)

# a block of a connector id, and a block in the tree-free part still reported alongside
r = run(good() + [dict(id="n_k", title="A connector", who="owner", stage="-", writes="nothing", invokes="nothing", exits=[])])
control("a block for a connector", r, "n_k", "connector", "has no block")

# ---- the command with the tree from `paths.tree`, in a copy of the code with a toy playbooks dir
code = helpers.mkdtemp("fwx-code-")
for top in ("bin", "lib", "data"):
    shutil.copytree(os.path.join(helpers.ROOT, top), os.path.join(code, top), ignore=shutil.ignore_patterns("__pycache__"))
helpers.write(code, "playbooks/scope.tsv", "".join("%s\t%s\n" % kv for kv in SCOPE.items()))
helpers.write(code, "playbooks/session.md", doc(good()))
helpers.write(code, "lib/fwx/core/decide_rules.json", json.dumps({"rules": [{"id": r} for r in RULES]}))
toy_path = helpers.write(helpers.mkdtemp("fwx-tree-"), "tree.excalidraw", json.dumps(toy_tree()))
repo = helpers.toy_repo()


def cli(*args, cwd=None):
    import subprocess
    return subprocess.run([sys.executable, os.path.join(code, "bin", "fwx"), "playbooks", "check"] + list(args),
                          cwd=cwd or repo, env=helpers.clean_env(**ENV), capture_output=True, text=True)


r = cli("--tree", toy_path)
s.ok("check --tree: clean, exit 0, and the counts", r.returncode == 0 and "5 blocks" in r.stdout and "6 arrows" in r.stdout
     and "NOT RUN" not in r.stdout, "%s %r %r" % (r.returncode, r.stdout, r.stderr))
helpers.write(repo, ".claude/fwx.json", json.dumps({"schema": 1, "paths": {"tree": toy_path}}))
r = cli()
s.ok("check: the tree defaults to paths.tree", r.returncode == 0 and "6 arrows" in r.stdout, "%s %r" % (r.returncode, r.stdout))
wt = helpers.add_worktree(repo, "side")
r = cli(cwd=wt)
s.ok("check: paths.tree is found from a worktree", r.returncode == 0 and "6 arrows" in r.stdout, "%s %r" % (r.returncode, r.stdout))
b = good()
b[3]["exits"] = [("loop", "n_c", "a check fails")]
helpers.write(code, "playbooks/session.md", doc(b))
r = cli("--tree", toy_path)
s.ok("check: a missing exit exits 1 and prints it with the Spanish label",
     r.returncode == 1 and "n_d has no exit to n_e: «un bloqueo»" in r.stdout, "%s %r" % (r.returncode, r.stdout))
r = cli("--tree", os.path.join(code, "absent"))
s.ok("check: a tree that is not there exits 2", r.returncode == 2 and "absent" in r.stderr and "Traceback" not in r.stderr,
     "%s %r" % (r.returncode, r.stderr))

# ---- the real tree
try:
    real = (config.load().get("paths") or {}).get("tree")
except config.ConfigError:
    real = None
if not (real and os.path.exists(real)):
    if s.fails:
        s.done()
    print("%d toy checks passed" % s.checks)
    s.not_run("no tree (set `paths.tree` in .claude/fwx.json to the Excalidraw tree)")
r = playbooks.check(tree_path=real)
s.eq("the real tree against the real playbooks/: no problem", r.errors, [])
s.ok("... and it compared something: the tree ran", r.tree_ran, "no tree")
s.eq("... and the seven playbooks of scope.tsv are each written or NOT CHECKED",
     len(r.not_checked) + sum(1 for n in playbooks.NAMES if os.path.exists(os.path.join(playbooks.PLAYBOOK_DIR, n + ".md"))),
     len(playbooks.NAMES))
s.done()
