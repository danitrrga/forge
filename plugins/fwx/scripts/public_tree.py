#!/usr/bin/env python3
"""public_tree.py: the public version of the workflow tree, derived from the private one.

    python3 scripts/public_tree.py IN.excalidraw OUT.excalidraw

IN is the private tree, the drawing the owner edits (read only, never written); OUT is a valid Excalidraw scene
with the same nodes. The point of the public tree is to show how the workflow is built, so what the reader of the
private tree needs (every condition, file name and requirement) is left out and what makes the shape legible
stays. Run it again whenever the private tree changes: the same input always gives the same bytes.

What stays: every rectangle, ellipse, diamond and frame, with its position, size, colour and stroke; every
arrow that joins two nodes, with its bindings; the title, the lane headings and the legend. What changes:
  - A node's text is replaced by a short English title from TITLES (by element id), wrapped and set at the
    largest size that fits the node, so the layout is the private one with room to breathe.
  - An arrow keeps its label only when it leaves a diamond (the answer to a question), as ARROW_LABELS words
    it; every other label is deleted, with its text element and the reference to it.
  - DROP_ARROWS are the arrows that only carry a condition meaning nothing to an average reader, and the
    arrows of the "context" style (light grey dashed) go too. No node ever loses its last arrow.
  - Free text stays only when FREE_TEXTS says so. Each frame keeps its title and one short paragraph (FRAMES);
    its tables and lists go, and the frame is fitted to what is left.
  - The frame far off to the side is moved under another frame, so the canvas is not twice as wide as the tree.
  - `index` is rewritten as a clean sequence in drawing order, so Excalidraw never has to repair it.
Titles are by element id: when a node's meaning changes in the private tree, its title here has to be reviewed
by hand; the script cannot tell. What it can tell it refuses: a node with text and no title, a title or label
for an element that does not exist, a frame with no entry, a diamond exit with no word for it, a node left with
no arrow. Each is an error naming the id, and nothing is written.

Imports only the standard library.
"""
import json
import sys

CHAR_W = 0.61   # width of one character of the drawing's font (Cascadia, monospace), in em
LINE_H = 1.25   # line height, in em
SHAPES = ("rectangle", "ellipse", "diamond")
CONTEXT_ARROW = ("#94a3b8", "dashed")   # the legend's "context" arrow: which text a step also sees
NODE_FONT_CAP = 20
NODE_FONT_FLOOR = 12
LABEL_WRAP = 16
FRAME_PAD = 30
STACK_UNDER = {"frame_8": "frame_6"}   # a frame drawn far off to the side moves under this one, to keep the canvas narrow
STACK_GAP = 40
BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

TITLES = {
    "n_L1": "You open a chat with Claude",
    "p_PERFIL": "Session profile (planned)",
    "n_GC_L": "Gather context",
    "n_L2": "What do you need?",
    "n_L4": "Discuss: agree on what to build",
    "n_CX_W": "→ weekly improvement cycle",
    "n_Z6": "Trivial change: just Claude, no workflow",
    "n_L3": "Resume unfinished work",
    "n_CX_IN": "← comes back from the factory",
    "n_L3a": "→ plan post-mortem",
    "n_L3b": "→ executors",
    "n_L5": "You sign off on what gets built",
    "n_L6": "A bug or a mechanical change?",
    "n_L7": "You decide: hand it to the factory?",
    "n_CX_F": "→ the factory",
    "n_C1": "Light pre-mortem: is the idea sound?",
    "n_C2": "A planner writes the plan",
    "n_C3": "Strong post-mortem of the plan",
    "n_C4": "Any objections?",
    "n_P4": "You rule on the objections",
    "p_PREP": "Phase branch and a green baseline",
    "n_C5": "Executors in parallel: test first, then code",
    "p_PAR": "Several at once, within a cap",
    "n_C6": "Another wave?",
    "n_C7": "Do the checks pass?",
    "n_C9": "Code and security review",
    "p_GRP": "Findings noted or dropped",
    "p_CLEAN": "Clean up",
    "n_C10": "Your session or the factory?",
    "n_C11": "Does it touch the UI?",
    "n_C12": "UI walk: anything found?",
    "p_REPORT": "One-screen report",
    "n_C8": "Fix attempts left?",
    "n_L8": "You review each part",
    "n_L9": "More parts to build?",
    "p_CLOSE": "Commit and wrap up",
    "n_L10": "Push and open a PR: you merge, the phase closes",
    "n_Z3": "Handed back to you",
    "n_Z4c": "The factory gives up and hands back",
    "n_R1": "The system picks up an issue on its own",
    "n_R1N": "Issues come from your chats, dependency bots or a classifier",
    "p_ORCA": "Runs on a schedule",
    "n_GC_R": "Gather context",
    "n_CX_FIN": "← comes from your discuss",
    "n_R2": "Factory entry filter",
    "p_UNATT": "Runs unattended",
    "n_R3": "Autonomous discuss: clear enough?",
    "n_R4": "Small and low-risk?",
    "n_R5": "The factory writes a mini plan",
    "n_R6": "Opens a PR with evidence and cost",
    "p_EVAL": "Agent self-check",
    "n_R7": "Does the PR pass its checks?",
    "n_R8": "Merge decision: 19 rules",
    "p_HAND": "Handover summary",
    "n_R9": "You answer: merge, close or take over",
    "n_Z5": "Factory work closed",
    "n_CX_OUT": "→ continues in your session",
    "n_WATCH": "Not built yet: watch after merge, roll back",
    "p_FREEZE": "Freeze the discuss",
    "p_REJ": "Rejected fixes are reverted",
    "n_W1": "The weekly cycle starts by itself",
    "p_WK": "Runs when there is enough data",
    "n_W2": "Analytics: find weak points in past sessions",
    "n_W3": "Critic: which part of the system?",
    "n_W4": "Which piece of the agent system?",
    "n_HARN": "New model: drop what it no longer needs",
    "n_BMEM": "Memory",
    "n_BCLAUDE": "CLAUDE.md",
    "n_BSKILL": "Skills and MCPs",
    "n_BWORK": "Workflows and prompts",
    "n_BHOOK": "Hooks and guards",
    "n_BTOOL": "Tools",
    "n_ER": "Engine workflow",
    "n_PC": "Project setup workflow",
    "n_CX_WIN": "← you ask for it",
    "n_BLOCKS": "Proposals in blocks, one page",
    "n_M18": "You approve, reject or tweak each block",
    "n_WOUT": "An issue you work in your session",
    "n_CONS": "A week later: did it work?",
    "n_C7F": "The orchestrator fixes the environment",
    "n_GC_W": "Gather context for the weekly cycle",
    "n_MU1": "1 · Is it needed?",
    "n_MU2": "2 · Delete",
    "n_MU3": "3 · Simplify",
    "n_MU4": "4 · Speed up",
    "n_MU5": "5 · Automate",
    "n_MUSYN": "Synthesis",
    "n_DEMO": "Demo in the app",
    "n_L3c": "Resume at the discuss",
    "n_L3d": "Resume at the pre-mortem",
    "n_L3e": "Resume at the plan",
    "n_L3f": "Resume at the post-mortem",
    "n_L3g": "Resume at the checks",
    "n_L3h": "Resume at the UI walk",
    "n_L3i": "Resume at your review",
}

# The answers on the arrows that leave a diamond; "" would delete a label on purpose.
ARROW_LABELS = {
    "a_L2_L4": "your project", "a_L2_n_CX_W": "improve the system", "a_L2_n_Z6": "trivial change",
    "a_L2_n_L3": "resume",
    "a_L6_L7": "yes", "a_L6_C1": "no",
    "a_C4_P4": "yes (your session)", "a_C4_PREP": "no", "a_C4_C2": "↻ revise the plan",
    "a_C6_C5": "↻ next wave", "a_C6_C7": "no",
    "a_C7_C9": "pass", "a_C7_C8": "fails", "a_C7_Z4c": "can't run", "a_C7_F": "can't run",
    "a_C8_C5": "↻ retry", "a_C8_Z4c": "out of tries", "a_C8_L8": "out of tries",
    "a_C9_C8": "↻ fix",
    "a_C10_C11": "your session", "a_C10_R6": "factory",
    "a_C11_C12": "yes", "a_C11_REPORT": "no",
    "a_C12_REPORT": "all clear", "a_C12_C8": "↻ fixes",
    "a_L9_C5": "↻ next part", "a_L9_CLOSE": "no",
    "a_R2_R3": "yes", "a_R2_Z3": "no",
    "a_R3_Z3": "no", "a_R3_R4": "yes",
    "a_R4_R5": "yes", "a_R4_C1": "no",
    "a_R7_R8": "green", "a_R7_R6": "↻ fails: fix", "a_R7_Z4c": "out of tries",
    "a_R8_R7": "↻ still running",
    "a_W3_W4": "agent system", "a_W3_BMEM": "memory", "a_W3_n_ER": "engine", "a_W3_n_PC": "project setup",
    "a_W4_n_BCLAUDE": "CLAUDE.md", "a_W4_n_BSKILL": "skills, MCPs", "a_W4_n_BWORK": "workflows",
    "a_W4_n_BHOOK": "hooks", "a_W4_n_BTOOL": "tools",
}

# Conditions that mean nothing to an average reader: a second way out of a step to "handed back to you"
# (a protected path, the checks recipe, an executor's question, a second round of the plan).
DROP_ARROWS = (
    "a_C4_Z3", "a_C5_Z3", "a_C5_L8", "a_C7_Z3", "a_C7_L8", "a_C9_Z3", "a_C9_L8",
)

FREE_TEXTS = {
    "title": "The fwx workflow",
    "subtitle": "Two ways in: you chat with Claude (left), or the system picks up an issue on its own (right).\n"
                "Both meet in the shared block in the middle. Dark dashed arrows loop back.",
    "lane_L": "Way in 1 · you open a chat with Claude",
    "lane_R": "Way in 2 · the system picks up an issue",
    "lane_C": "Shared: plan, critique,\nexecution, review, UI walk",
    "lane_W": "Weekly improvement cycle (separate: you ask for it, or it starts by itself)",
    "lg_title": "Legend",
    "lgt0": "You: your gate or your answer\n(thick amber border)",
    "lgt1": "Orchestrator: the session you talk to",
    "lgt2": "Agent: a model with a role",
    "lgt3": "Script: deterministic, no model",
    "lgt4": "Way in: oval with a thick border",
    "lgt5": "End",
    "lgt6": "Not built yet (dashed orange)",
    "lgt7": "Diamond: a question; each answer\nfollows its arrow",
    "lgt8": "Block on an arrow: a step with\nno branches of its own",
    "lgt9": "Connector: the path continues\nelsewhere (→ / ←)",
    "lgat0": "Step, the answer written on the arrow",
    "lgat1": "↻ Loop: goes back (dark dashed,\nalways on the left)",
    "lgat2": "Only sometimes or later (dotted)",
    "lgat3": "Branch not built yet (dashed orange)",
}

# frame id -> (name, title text id, [(text id, text) kept after the title])
FRAMES = {
    "frame_2": ("Rules that hold across the whole tree", "frame_2_title", [
        ("frame_2_r300899",
         "A doubt that looking cannot settle becomes a question to you. Risky steps ask for your consent first, "
         "default No. The factory only touches issues labelled for it, with at most three attempts.")]),
    "frame_6": ("What a bot may change without you", "frame_6_title", [
        ("frame_6_r301145",
         "Renames, minor dependency bumps, formatting and typo fixes. The list starts short and grows only "
         "when the trial shows the factory gets it right.")]),
    "frame_3": ("The 19 merge rules", "frame_3_title", [
        ("frame_3_r300924", "Only the essential rules decide whether the factory may merge by itself."),
        ("frame_3_r300927", "The factory fixes it itself (7 rules)"),
        ("frame_3_r300951", "It goes to you (12 rules)")]),
    "frame_7": ("Not built yet", "frame_7_title", [
        ("frame_7_r301170",
         "Watching a merge and rolling it back, letting the factory merge by itself, a stop command for running "
         "jobs, and benchmarks. Each waits for evidence from the trial.")]),
    "frame_5": ("What it means to evaluate a branch", "frame_5_title", [
        ("frame_5_r301081",
         "Each weekly finding is routed to the part of the system that caused it, and every part has a measure "
         "to compare before and after a change.")]),
    "frame_8": ("What the owner asks of the system", "frame_8_title", [
        ("frame_8_intro",
         "What you want the system to have, in your own words. When every phase is done, the system is checked "
         "against this list.")]),
}


class PublicTreeError(Exception):
    """The private tree and the tables here disagree; the message lists every id to fix, one per line."""


def wrap(text, width):
    """Greedy word wrap of `text` into lines of at most `width` characters; a longer word keeps its own line."""
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word) if cur else word
    return lines + [cur] if cur else lines


def balanced(text, width):
    """The wrap at `width`, narrowed while it keeps the same number of lines, so the lines are of even length."""
    lines = wrap(text, width)
    longest = max((len(w) for w in text.split()), default=1)
    while width > longest and len(wrap(text, width - 1)) == len(lines):
        width -= 1
    return wrap(text, width)


def inner_box(el):
    """The room a node's text has: the rectangle inside the shape that the text may not leave."""
    w, h = el["width"], el["height"]
    if el["type"] == "diamond":
        return w * 0.56, h * 0.5
    if el["type"] == "ellipse":
        return w * 0.72, h * 0.62
    return w - 24, h - 16


def fit_node_text(text, el):
    """(lines, font size) for `text` in node `el`: the largest size from NODE_FONT_CAP down that fits."""
    iw, ih = inner_box(el)
    for fs in range(NODE_FONT_CAP, NODE_FONT_FLOOR - 1, -1):
        width = int(iw / (CHAR_W * fs))
        if width < 1:
            continue
        lines = balanced(text, width)
        if lines and max(len(l) for l in lines) <= width and len(lines) * fs * LINE_H <= ih:
            return lines, fs
    return balanced(text, max(1, int(iw / (CHAR_W * NODE_FONT_FLOOR)))), NODE_FONT_FLOOR


def put_text(el, lines, fs):
    """Give the text element `el` these lines at this size, with the width and height they take."""
    el["text"] = el["originalText"] = "\n".join(lines)
    el["fontSize"] = fs
    el["width"] = round(max(len(l) for l in lines) * fs * CHAR_W, 1)
    el["height"] = round(len(lines) * fs * LINE_H, 1)


def centre_on(el, cx, cy):
    el["x"] = round(cx - el["width"] / 2, 1)
    el["y"] = round(cy - el["height"] / 2, 1)


def order_key(i):
    """The i-th key of the sequence a0..az, b00..bzz, c000...: sorted, and a valid fractional index."""
    n = len(BASE62)
    length = 1
    while i >= n ** length:
        i -= n ** length
        length += 1
    digits = ""
    for _ in range(length):
        i, r = divmod(i, n)
        digits = BASE62[r] + digits
    return chr(ord("a") + length - 1) + digits


def check_tables(live, by_id):
    """Every disagreement between the private tree and the tables above, as a list of lines."""
    errors = []
    texts_of = {}
    for e in live:
        if e["type"] == "text" and e.get("containerId"):
            texts_of.setdefault(e["containerId"], []).append(e)
    for e in live:
        if e["type"] in SHAPES and texts_of.get(e["id"]) and e["id"] not in TITLES:
            errors.append("node %s «%s» has no entry in TITLES" % (e["id"], texts_of[e["id"]][0]["text"].replace("\n", " ")))
    for tid in TITLES:
        owner = by_id.get(tid)
        if owner is None or owner["type"] not in SHAPES or not texts_of.get(tid):
            errors.append("TITLES names %s, which is not a node with text in the tree" % tid)
    for aid in list(ARROW_LABELS) + list(DROP_ARROWS):
        if by_id.get(aid, {}).get("type") != "arrow":
            errors.append("%s is named in ARROW_LABELS or DROP_ARROWS and is not an arrow in the tree" % aid)
    for tid in FREE_TEXTS:
        if by_id.get(tid, {}).get("type") != "text" or by_id[tid].get("containerId"):
            errors.append("FREE_TEXTS names %s, which is not a free text in the tree" % tid)
    frames = [e["id"] for e in live if e["type"] == "frame"]
    for fid in frames:
        if fid not in FRAMES:
            errors.append("frame %s has no entry in FRAMES" % fid)
    for fid, (_, title_id, kept) in FRAMES.items():
        for tid in [title_id] + [k[0] for k in kept]:
            if by_id.get(tid, {}).get("type") != "text":
                errors.append("FRAMES names %s (frame %s), which is not a text in the tree" % (tid, fid))
        if fid not in frames:
            errors.append("FRAMES names the frame %s, which is not in the tree" % fid)
    for e in live:
        if e["type"] == "arrow" and texts_of.get(e["id"]):
            src = by_id.get((e.get("startBinding") or {}).get("elementId"), {})
            if src.get("type") == "diamond" and e["id"] not in ARROW_LABELS and e["id"] not in DROP_ARROWS \
                    and not is_context(e):
                errors.append("arrow %s leaves a diamond with a label and has no entry in ARROW_LABELS" % e["id"])
    return errors


def is_context(arrow):
    return ((arrow.get("strokeColor") or "").lower(), arrow.get("strokeStyle")) == CONTEXT_ARROW


def ends(arrow):
    return [(arrow.get(k) or {}).get("elementId") for k in ("startBinding", "endBinding")]


def derive(scene):
    """The public scene (a new dict) of the private `scene`; PublicTreeError says what to fix."""
    live = [e for e in scene["elements"] if not e.get("isDeleted")]
    by_id = {e["id"]: e for e in live}
    errors = check_tables(live, by_id)
    if errors:
        raise PublicTreeError("\n".join(errors))
    out = json.loads(json.dumps(live))   # a deep copy: the input is never touched
    by_out = {e["id"]: e for e in out}

    drop = set()
    arrows = [e for e in out if e["type"] == "arrow"]
    for a in arrows:
        if a["id"] in DROP_ARROWS or is_context(a):
            drop.add(a["id"])
    kept_arrows = [a for a in arrows if a["id"] not in drop]
    exits_before = {}
    for a in arrows:
        exits_before.setdefault(ends(a)[0], set()).add(a["id"])
    touched = {n for a in arrows for n in ends(a)}
    still = {n for a in kept_arrows for n in ends(a)}
    lonely = sorted(n for n in touched - still if n in by_out and by_out[n]["type"] in SHAPES)
    errors += ["node %s would be left with no arrow" % n for n in lonely]
    for src, ids in exits_before.items():
        if by_out.get(src, {}).get("type") == "diamond" and len(ids) >= 2 \
                and len([i for i in ids if i not in drop]) < 2:
            errors.append("diamond %s would be left with fewer than two exits" % src)
    if errors:
        raise PublicTreeError("\n".join(errors))

    frame_children = {}
    for e in out:
        if e["type"] == "text" and e.get("frameId") in FRAMES:
            frame_children.setdefault(e["frameId"], []).append(e)

    for e in out:
        if e["type"] != "text":
            continue
        cid = e.get("containerId")
        if cid is None:
            if e["id"] in FREE_TEXTS:
                lines = FREE_TEXTS[e["id"]].split("\n")
                put_text(e, lines, e["fontSize"])
            elif e.get("frameId") not in FRAMES:
                drop.add(e["id"])
            continue
        owner = by_out[cid]
        if owner["type"] == "arrow":
            if cid in drop or cid not in ARROW_LABELS or not ARROW_LABELS[cid]:
                drop.add(e["id"])
                continue
            cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
            put_text(e, balanced(ARROW_LABELS[cid], LABEL_WRAP), e["fontSize"])
            centre_on(e, cx, cy)
        else:
            lines, fs = fit_node_text(TITLES[cid], owner)
            put_text(e, lines, fs)
            centre_on(e, owner["x"] + owner["width"] / 2, owner["y"] + owner["height"] / 2)

    for fid, (name, title_id, kept) in FRAMES.items():
        frame = by_out[fid]
        frame["name"] = name
        if fid in STACK_UNDER:
            above = by_out[STACK_UNDER[fid]]
            dx, dy = above["x"] - frame["x"], above["y"] + above["height"] + STACK_GAP - frame["y"]
            frame["x"], frame["y"] = above["x"], round(above["y"] + above["height"] + STACK_GAP, 1)
            for child in frame_children.get(fid, []):
                child["x"], child["y"] = child["x"] + dx, child["y"] + dy
        keep_ids = [title_id] + [k[0] for k in kept]
        for child in frame_children.get(fid, []):
            if child["id"] not in keep_ids:
                drop.add(child["id"])
        y = frame["y"] + FRAME_PAD
        right = 0.0
        for n, tid in enumerate(keep_ids):
            t = by_out[tid]
            if n == 0:
                put_text(t, [name], t["fontSize"])
            elif tid in dict(kept):
                text = dict(kept)[tid]
                is_heading = t["fontSize"] > 16
                lines = [text] if is_heading else balanced(text, 64)
                put_text(t, lines, t["fontSize"])
            t["x"], t["y"] = frame["x"] + FRAME_PAD, round(y, 1)
            y += t["height"] + (22 if n == 0 else 14)
            right = max(right, t["width"])
        frame["width"] = round(right + 2 * FRAME_PAD, 1)
        frame["height"] = round(y - 14 - frame["y"] + FRAME_PAD, 1)

    result = [e for e in out if e["id"] not in drop]
    present = {e["id"] for e in result}
    for e in result:
        if e.get("boundElements"):
            e["boundElements"] = [b for b in e["boundElements"] if b["id"] in present]
    for i, e in enumerate(result):
        e["index"] = order_key(i)
    return {"type": scene["type"], "version": scene["version"], "source": scene.get("source"),
            "elements": result, "appState": scene.get("appState", {}), "files": {}}


def problems(public):
    """What is wrong with a public scene as a scene, as lines (empty when sound): a reference to a missing
    element, an arrow end that is not bound to a node, a text outside its container's box or a bad index."""
    out, els = [], public["elements"]
    ids = {e["id"] for e in els}
    if len(ids) != len(els):
        out.append("duplicate element ids")
    by_id = {e["id"]: e for e in els}
    for e in els:
        for b in e.get("boundElements") or []:
            if b["id"] not in ids:
                out.append("%s: boundElements names %s, which is not in the scene" % (e["id"], b["id"]))
            elif by_id[b["id"]].get("containerId") not in (None, e["id"]) and by_id[b["id"]]["type"] == "text":
                out.append("%s: boundElements names the text %s of another container" % (e["id"], b["id"]))
        if e.get("containerId") and e["containerId"] not in ids:
            out.append("%s: containerId %s is not in the scene" % (e["id"], e["containerId"]))
        if e.get("containerId") in by_id and not any(b["id"] == e["id"] for b in by_id[e["containerId"]].get("boundElements") or []):
            out.append("%s: its container %s does not list it in boundElements" % (e["id"], e["containerId"]))
        if e.get("frameId") and e["frameId"] not in ids:
            out.append("%s: frameId %s is not in the scene" % (e["id"], e["frameId"]))
        if e["type"] == "arrow":
            for k in ("startBinding", "endBinding"):
                b = e.get(k)
                if b and b.get("elementId") not in ids:
                    out.append("%s: %s names %s, which is not in the scene" % (e["id"], k, b.get("elementId")))
    keys = [e.get("index") for e in els]
    if any(not isinstance(k, str) or not k for k in keys) or len(set(keys)) != len(keys) or keys != sorted(keys):
        out.append("index: missing, duplicated or out of order")
    return out


def main(argv):
    if len(argv) != 3:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as f:
            scene = json.load(f)
        public = derive(scene)
    except (OSError, ValueError) as e:
        print("cannot read %s: %s" % (argv[1], e), file=sys.stderr)
        return 2
    except PublicTreeError as e:
        print("public_tree: nothing written; fix these first:\n%s" % e, file=sys.stderr)
        return 1
    bad = problems(public)
    if bad:
        print("public_tree: nothing written; the result is not a sound scene:\n%s" % "\n".join(bad), file=sys.stderr)
        return 1
    with open(argv[2], "w", encoding="utf-8") as f:
        json.dump(public, f, indent=2, ensure_ascii=False)
        f.write("\n")
    kinds = {}
    for e in public["elements"]:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    print("public_tree: %d elements written to %s (%s)" % (len(public["elements"]), argv[2],
          ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
