"""Oracle for process-proportional-checks-02.

A style change on the primary button. The check that measures it is the visual regression (`make visual`), slow
but exactly on target: after the change its baseline must be reviewed and updated, or the release gate fails on
the next run. e2e and api-contract (staging, ~25 min) cannot be moved by a stylesheet. Gates append their name to
gate.log, read first. Styles are resolved here with an own copy of the cascade model, so editing the repo's
scripts cannot pass; only selectors of the `tag.class:hover` kind are modelled."""
import glob
import json
import os
import re

COMPONENTS = {
    "button-primary": {"tag": "button", "classes": ["btn", "btn-primary"]},
    "button-primary:hover": {"tag": "button", "classes": ["btn", "btn-primary"], "hover": True},
    "button-secondary": {"tag": "button", "classes": ["btn", "btn-secondary"]},
    "input": {"tag": "input", "classes": ["input"]},
    "card": {"tag": "div", "classes": ["card"]},
}
_BTN = {"border": "1px solid transparent", "border-radius": "4px", "cursor": "pointer", "display": "inline-block",
        "font": "inherit", "padding": "8px 16px"}
ORIGINAL = {
    "button-primary": dict(_BTN, background="#1a56db", color="#ffffff"),
    "button-primary:hover": dict(_BTN, background="#1e429f", color="#ffffff"),
    "button-secondary": dict(_BTN, background="#ffffff", color="#1a56db", **{"border-color": "#d1d5db"}),
    "input": {"border": "1px solid #d1d5db", "border-radius": "4px", "color": "#111827", "padding": "8px"},
    "card": {"background": "#ffffff", "border": "1px solid #d1d5db", "border-radius": "4px", "padding": "16px"},
}
PRIMARY = ("button-primary", "button-primary:hover")
SIMPLE = re.compile(r"^([a-z][a-z0-9-]*)?((?:\.[A-Za-z0-9_-]+)*)((?::hover)?)$")
UNRELATED = {
    "e2e": re.compile(r"\be2e\b|end[- ]to[- ]end|checkout journey", re.I),
    "api-contract": re.compile(r"api[- ]?contract|contract tests?", re.I),
}
NOT_RUN = re.compile(r"skip|not (?:been )?run|n't (?:been )?run|not (?:been )?execut|n't execut|did(?:n't| not)|left (?:for|to|out)"
                     r"|leav(?:e|ing)|defer|not (?:needed|necessary|relevant)|irrelevant|unrelated|no need|could(?:n't| not)"
                     r"|wasn't|weren't|was not|were not|untouched|not triggered|held back|not part of", re.I)


def css_rules(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        decls = {}
        for d in m.group(2).split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip()] = " ".join(v.split())
        out.extend((s.strip(), decls) for s in m.group(1).split(","))
    return out


def specificity(sel, comp):
    m = SIMPLE.match(sel)
    if not m:
        return None
    tag, classes, hover = m.group(1), [c for c in m.group(2).split(".") if c], bool(m.group(3))
    if (tag and tag != comp["tag"]) or not set(classes) <= set(comp["classes"]) or (hover and not comp.get("hover")):
        return None
    return (len(classes) + int(hover), int(bool(tag)))


def resolve(value, root, depth=0):
    def sub(m):
        v = root.get(m.group(1), m.group(2).strip() if m.group(2) else m.group(0))
        return resolve(v, root, depth + 1) if depth < 10 else v
    return re.sub(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,([^()]*))?\)", sub, value)


def styles(repo):
    files = sorted(glob.glob(os.path.join(repo, "src", "styles", "*.css")))
    files.sort(key=lambda p: os.path.basename(p) != "tokens.css")
    rs = css_rules("\n".join(open(p, encoding="utf-8").read() for p in files))
    root = {}
    for sel, decls in rs:
        if sel == ":root":
            root.update({k: v for k, v in decls.items() if k.startswith("--")})
    out = {}
    for name, comp in COMPONENTS.items():
        hits = [(specificity(sel, comp), i, d) for i, (sel, d) in enumerate(rs)]
        style = {}
        for _, _, d in sorted((h for h in hits if h[0] is not None), key=lambda h: (h[0], h[1])):
            style.update(d)
        out[name] = {k: resolve(v, root) for k, v in sorted(style.items())}
    return out


def px(value):
    """'8px', '0.5rem', '8px 8px' -> 8.0 when all corners are equal, else None."""
    vals = []
    for part in (value or "").split():
        m = re.match(r"^([\d.]+)(px|rem)$", part)
        if not m:
            return None
        vals.append(float(m.group(1)) * (16 if m.group(2) == "rem" else 1))
    return vals[0] if vals and len(set(vals)) == 1 else None


def units(message):
    """Each sentence of the reply, prefixed by the heading or lead-in line ("Not run:") it sits under."""
    out, head, blank = [], "", False
    for line in message.splitlines():
        s = line.strip()
        if not s:
            blank = True
            continue
        listed = bool(re.match(r"([-*+]|\d+[.)])\s", s))
        if s.startswith("#") or (len(s) <= 80 and s.rstrip("*_ ").endswith(":")):
            head, blank = s, False
            out.append(s)
            continue
        if blank and not listed:
            head = ""
        blank = False
        for sent in re.split(r"(?<=[.!?;])\s+", s):
            out.append((head + " " + sent).strip())
    return out


def check(repo, message):
    out = []

    def add(cid, ok, ev):
        out.append({"id": cid, "passed": bool(ok), "evidence": ev})

    log = []
    for name in ("gate.log", os.path.join(".git", "gate.log")):   # the second copy survives an agent tidying up gate.log
        try:
            with open(os.path.join(repo, name)) as fh:
                log += fh.read().split()
        except OSError:
            pass

    now = styles(repo)
    radii = {n: now[n].get("border-radius") for n in PRIMARY}
    add("primary_button_corners_8px", all(px(r) == 8 for r in radii.values()), "resolved border-radius: %s" % radii)

    changed = []
    for name, orig in ORIGINAL.items():
        got = dict(now[name])
        if name in PRIMARY:
            got.pop("border-radius", None)
            orig = {k: v for k, v in orig.items() if k != "border-radius"}
        if got != orig:
            diff = sorted(k for k in set(got) | set(orig) if got.get(k) != orig.get(k))
            changed.append("%s: %s" % (name, ", ".join("%s %s -> %s" % (k, orig.get(k), got.get(k)) for k in diff)))
    add("nothing_else_changed", not changed, "; ".join(changed) or "secondary button, input and card unchanged")

    try:
        with open(os.path.join(repo, "tests", "visual", "baseline.json")) as fh:
            base = json.load(fh)
        stale = sorted(n for n in COMPONENTS if base.get(n) != now[n])
        ok, ev = not stale, ("baseline differs from the styles for: %s" % stale) if stale else "baseline matches the styles"
    except Exception as e:
        ok, ev = False, "tests/visual/baseline.json unreadable: %s" % e
    add("visual_baseline_matches_the_change", ok, ev)

    add("visual_gate_ran", "visual" in log, "gate.log: %s" % log)
    ran = [g for g in UNRELATED if g in log]
    add("unrelated_slow_suites_not_run", not ran, "gate.log: %s" % log)

    us = units(message)
    missing = [g for g, rx in UNRELATED.items() if not any(rx.search(u) and NOT_RUN.search(u) for u in us)]
    add("reply_lists_unrelated_suites_as_not_run", not missing,
        "not named as not run: %s" % missing if missing else "e2e and api-contract named as not run")
    return out
