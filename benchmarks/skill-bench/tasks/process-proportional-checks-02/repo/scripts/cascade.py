"""A small model of the CSS cascade for the selectors this project uses: `tag`, `.class`, `:hover` compounds.

resolved(css_text, component) -> {property: value} with var() resolved from :root, rules applied by
(specificity, source order). Complex selectors (descendant, child) do not apply to a lone component."""
import re

SIMPLE = re.compile(r"^([a-z][a-z0-9-]*)?((?:\.[A-Za-z0-9_-]+)*)((?::hover)?)$")


def rules(css_text):
    text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        decls = {}
        for d in m.group(2).split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip()] = " ".join(v.split())
        for sel in m.group(1).split(","):
            out.append((sel.strip(), decls))
    return out


def matches(sel, component):
    m = SIMPLE.match(sel)
    if not m:
        return None
    tag, classes, hover = m.group(1), [c for c in m.group(2).split(".") if c], bool(m.group(3))
    if tag and tag != component.get("tag"):
        return None
    if not set(classes) <= set(component.get("classes", [])):
        return None
    if hover and not component.get("hover"):
        return None
    return (len(classes) + int(hover), int(bool(tag)))


def resolve(value, root, depth=0):
    def sub(m):
        name, fallback = m.group(1), m.group(2)
        v = root.get(name, fallback.strip() if fallback else m.group(0))
        return resolve(v, root, depth + 1) if depth < 10 else v
    return re.sub(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,([^()]*))?\)", sub, value)


def resolved(css_text, component):
    rs = rules(css_text)
    root = {}
    for sel, decls in rs:
        if sel == ":root":
            root.update({k: v for k, v in decls.items() if k.startswith("--")})
    hits = []
    for order, (sel, decls) in enumerate(rs):
        spec = matches(sel, component)
        if spec is not None:
            hits.append((spec, order, decls))
    style = {}
    for _, _, decls in sorted(hits, key=lambda h: (h[0], h[1])):
        style.update(decls)
    return {k: resolve(v, root) for k, v in sorted(style.items())}
