"""Oracle for ui-accessibility-01: row a11y-39 of pooriaarab/benchmark-accessibility-fix (MIT), graded by that benchmark's own
analyzer, ported line for line below. A pass on every check is the benchmark's score of exactly 1: every injected defect
(div-button, empty-link, missing-alt, tabindex-positive) fixed, no check that passed on the original page now failing, and none of its auto-zero causes (visible
words lost, an image/input/link/table/button/heading/control removed, content newly hidden, styles deleted, a defect
quieted instead of repaired).

What it cannot see (the benchmark's own limits): it is static, so no layout, zoom, real focus order or assistive
technology; it reads only <style> blocks and style= attributes of index.html (a linked stylesheet is invisible);
script behaviour is judged from handler text (a key handler that cancels Tab is a trap); it cannot tell whether alt
text is accurate, only that it is present; concealment that keeps an element rendered (clip-path, off-screen
positioning) is neither rewarded nor penalised. It also accepts a div with role, tabindex="0" and a key handler in place
of a native <button>, as the benchmark does; rubric.md asks the judge about that.
"""
# ---- Port of benchmark-accessibility-fix's grader (MIT, (c) 2026 Pooria Arab) ----
# Source: https://github.com/pooriaarab/benchmark-accessibility-fix at commit
# b014a71a69f5e19c80c4c9f4bf95a416faeb88f1: src/a11y-dom.ts, src/a11y.ts and gradeAnswer() in src/benchmark.ts,
# translated line for line to the Python standard library. No check was weakened or added.
import math
import re

NAMED_SRC = (
    "black=0,0,0 silver=192,192,192 gray=128,128,128 grey=128,128,128 white=255,255,255 maroon=128,0,0 red=255,0,0 purple=128,0,128"
    "fuchsia=255,0,255 magenta=255,0,255 green=0,128,0 lime=0,255,0 olive=128,128,0 yellow=255,255,0 navy=0,0,128 blue=0,0,255"
    "teal=0,128,128 aqua=0,255,255 cyan=0,255,255 orange=255,165,0 aliceblue=240,248,255 antiquewhite=250,235,215 aquamarine=127,255,212 azure=240,255,255"
    "beige=245,245,220 bisque=255,228,196 blanchedalmond=255,235,205 blueviolet=138,43,226 brown=165,42,42 burlywood=222,184,135 cadetblue=95,158,160 chartreuse=127,255,0"
    "chocolate=210,105,30 coral=255,127,80 cornflowerblue=100,149,237 cornsilk=255,248,220 crimson=220,20,60 darkblue=0,0,139 darkcyan=0,139,139 darkgoldenrod=184,134,11"
    "darkgray=169,169,169 darkgrey=169,169,169 darkgreen=0,100,0 darkkhaki=189,183,107 darkmagenta=139,0,139 darkolivegreen=85,107,47 darkorange=255,140,0 darkorchid=153,50,204"
    "darkred=139,0,0 darksalmon=233,150,122 darkseagreen=143,188,143 darkslateblue=72,61,139 darkslategray=47,79,79 darkslategrey=47,79,79 darkturquoise=0,206,209 darkviolet=148,0,211"
    "deeppink=255,20,147 deepskyblue=0,191,255 dimgray=105,105,105 dimgrey=105,105,105 dodgerblue=30,144,255 firebrick=178,34,34 floralwhite=255,250,240 forestgreen=34,139,34"
    "gainsboro=220,220,220 ghostwhite=248,248,255 gold=255,215,0 goldenrod=218,165,32 greenyellow=173,255,47 honeydew=240,255,240 hotpink=255,105,180 indianred=205,92,92"
    "indigo=75,0,130 ivory=255,255,240 khaki=240,230,140 lavender=230,230,250 lavenderblush=255,240,245 lawngreen=124,252,0 lemonchiffon=255,250,205 lightblue=173,216,230"
    "lightcoral=240,128,128 lightcyan=224,255,255 lightgoldenrodyellow=250,250,210 lightgray=211,211,211 lightgrey=211,211,211 lightgreen=144,238,144 lightpink=255,182,193 lightsalmon=255,160,122"
    "lightseagreen=32,178,170 lightskyblue=135,206,250 lightslategray=119,136,153 lightslategrey=119,136,153 lightsteelblue=176,196,222 lightyellow=255,255,224 limegreen=50,205,50 linen=250,240,230"
    "mediumaquamarine=102,205,170 mediumblue=0,0,205 mediumorchid=186,85,211 mediumpurple=147,112,219 mediumseagreen=60,179,113 mediumslateblue=123,104,238 mediumspringgreen=0,250,154 mediumturquoise=72,209,204"
    "mediumvioletred=199,21,133 midnightblue=25,25,112 mintcream=245,255,250 mistyrose=255,228,225 moccasin=255,228,181 navajowhite=255,222,173 oldlace=253,245,230 olivedrab=107,142,35"
    "orangered=255,69,0 orchid=218,112,214 palegoldenrod=238,232,170 palegreen=152,251,152 paleturquoise=175,238,238 palevioletred=219,112,147 papayawhip=255,239,213 peachpuff=255,218,185"
    "peru=205,133,63 pink=255,192,203 plum=221,160,221 powderblue=176,224,230 rebeccapurple=102,51,153 rosybrown=188,143,143 royalblue=65,105,225 saddlebrown=139,69,19"
    "salmon=250,128,114 sandybrown=244,164,96 seagreen=46,139,87 seashell=255,245,238 sienna=160,82,45 skyblue=135,206,235 slateblue=106,90,205 slategray=112,128,144"
    "slategrey=112,128,144 snow=255,250,250 springgreen=0,255,127 steelblue=70,130,180 tan=210,180,140 thistle=216,191,216 tomato=255,99,71 turquoise=64,224,208"
    "violet=238,130,238 wheat=245,222,179 whitesmoke=245,245,245 yellowgreen=154,205,50")
# Upstream packs the table without separators between string pieces, so a name can fuse with the previous triple's
# last digit ("128,0,128fuchsia"); its match(/[a-z]+=\d+,\d+,\d+/g) still finds every name. Same regex here.
NAMED = {}
for _e in re.findall(r"[a-z]+=\d+,\d+,\d+", NAMED_SRC):
    _k, _v = _e.split("=")
    NAMED[_k] = tuple(int(x) for x in _v.split(","))

_FLOAT = re.compile(r"\s*([+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|Infinity))")


def js_parse_float(s):
    m = _FLOAT.match(s or "")
    if not m:
        return float("nan")
    t = m.group(1)
    if t.endswith("Infinity"):
        return float("-inf") if t.startswith("-") else float("inf")
    return float(t)


def js_number(s):
    """JavaScript Number(string)."""
    t = (s or "").strip()
    if t == "":
        return 0.0
    if re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", t):
        return float(t)
    if re.fullmatch(r"[+-]?Infinity", t):
        return float("-inf") if t.startswith("-") else float("inf")
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", t):
        return float(int(t, 16))
    if re.fullmatch(r"0[oO][0-7]+", t):
        return float(int(t[2:], 8))
    if re.fullmatch(r"0[bB][01]+", t):
        return float(int(t[2:], 2))
    return float("nan")


def finite(x):
    return not (math.isnan(x) or math.isinf(x))


def rgba(r, g, b, a):
    return {"r": r, "g": g, "b": b, "a": a}


def parse_numeric_color(v):
    t = v.strip().lower()
    m = re.match(r"^#([0-9a-f]{3,8})\Z", t)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c + c for c in h)
        if len(h) == 6:
            h += "ff"
        if len(h) != 8:
            return None
        return rgba(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16) / 255)
    if t in NAMED:
        r, g, b = NAMED[t]
        return rgba(r, g, b, 1)
    m = re.match(r"^(rgba?|hsla?)\((.*)\)\Z", t)
    if m:
        name = m.group(1)
        body = re.sub(r"[/,]", " ", m.group(2))
        parts = [p for p in body.strip().split() if p]
        if len(parts) < 3:
            return None

        def num(s, scale):
            return js_parse_float(s) * scale / 100 if s.endswith("%") else js_parse_float(s)
        if len(parts) < 4:
            alpha = 1
        else:
            a0 = num(parts[3], 1)
            alpha = a0 if math.isnan(a0) else min(1, max(0, a0))  # Math.min/max propagate NaN in JS
        if name.startswith("rgb"):
            vals = [num(p, 255) for p in parts]
            r, g, b = vals[0], vals[1], vals[2]
            if any(math.isnan(x) for x in (r, g, b)):
                return None
            return rgba(r, g, b, alpha)
        h0 = js_parse_float(parts[0])
        h = (math.fmod(math.fmod(h0, 360) + 360, 360)) / 360 if finite(h0) else float("nan")
        s = num(parts[1], 100)
        lum = num(parts[2], 100)
        if any(math.isnan(x) for x in (h, s, lum)) or s < 0 or s > 100 or lum < 0 or lum > 100:
            return None
        sn, ln = s / 100, lum / 100
        q = ln * (1 + sn) if ln < 0.5 else ln + sn - ln * sn
        p = 2 * ln - q

        def hue(t2):
            x = t2
            if x < 0:
                x += 1
            if x > 1:
                x -= 1
            if x < 1 / 6:
                return p + (q - p) * 6 * x
            if x < 1 / 2:
                return q
            if x < 2 / 3:
                return p + (q - p) * (2 / 3 - x) * 6
            return p
        return rgba(hue(h + 1 / 3) * 255, hue(h) * 255, hue(h - 1 / 3) * 255, alpha)
    return None


def channel(v):
    c = v / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(c):
    return 0.2126 * channel(c["r"]) + 0.7152 * channel(c["g"]) + 0.0722 * channel(c["b"])


def ratio_of(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def over(fg, bg):
    a = fg["a"] + bg["a"] * (1 - fg["a"])
    if a == 0:
        return rgba(255, 255, 255, 1)
    return rgba((fg["r"] * fg["a"] + bg["r"] * bg["a"] * (1 - fg["a"])) / a,
                (fg["g"] * fg["a"] + bg["g"] * bg["a"] * (1 - fg["a"])) / a,
                (fg["b"] * fg["a"] + bg["b"] * bg["a"] * (1 - fg["a"])) / a, a)


# ---------- light DOM ----------

class El:
    __slots__ = ("tag", "attrs", "parent", "children", "order", "style_text")

    def __init__(self, tag, attrs, parent, order):
        self.tag, self.attrs, self.parent, self.children, self.order, self.style_text = tag, attrs, parent, [], order, None


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
RAW_TEXT = {"style", "script", "title", "textarea"}
_ATTR = re.compile(r"""([\w-]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s>"']+)))?""")
_TAG = re.compile(r"""<(/?)([a-zA-Z][\w-]*)((?:"[^"]*"|'[^']*'|[^'"<>])*)(/?)>""")


def parse_attrs(src):
    attrs = {}
    for m in _ATTR.finditer(src):
        name = m.group(1).lower()
        if name and name not in attrs:
            v = m.group(3)
            if v is None:
                v = m.group(4)
            if v is None:
                v = m.group(5)
            attrs[name] = v if v is not None else ""
    return attrs


class Doc:
    def __init__(self, root, els):
        self.root, self.els = root, els


def parse_doc(html):
    clean = re.sub(r"<!--[\s\S]*?-->", "", html)
    low = clean.lower()
    root = El("#root", {}, None, -1)
    els = []
    cur = root
    i = 0
    n = len(clean)
    while i < n:
        lt = clean.find("<", i)
        text = clean[i:] if lt == -1 else clean[i:lt]
        if text:
            cur.children.append(text)
        if lt == -1:
            break
        m = _TAG.match(clean, lt)
        if not m:
            i = lt + 1
            continue
        tag = m.group(2).lower()
        i = lt + len(m.group(0))
        if m.group(1) == "/":
            p = cur
            while p.parent is not None and p.tag != tag:
                p = p.parent
            if p.tag == tag and p.parent:
                cur = p.parent
            continue
        el = El(tag, parse_attrs(m.group(3) or ""), cur, len(els))
        cur.children.append(el)
        els.append(el)
        if tag in RAW_TEXT:
            end = low.find("</" + tag, i)
            raw = clean[i:] if end == -1 else clean[i:end]
            el.children.append(raw)
            if tag == "style":
                el.style_text = raw
            i = n if end == -1 else end
            continue
        if tag not in VOID and m.group(4) != "/":
            cur = el
    return Doc(root, els)


def ancestors(el):
    out = []
    p = el.parent
    while p is not None and p.tag != "#root":
        out.append(p)
        p = p.parent
    return out


def el_text(el):
    out = ""
    for c in el.children:
        out += (c + " ") if isinstance(c, str) else (el_text(c) + " ")
    return out


def decode(s):
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    s = re.sub(r"&#39;|&apos;", "'", s)
    return s.replace("&nbsp;", " ")


# ---------- tiny CSS cascade ----------

def parse_decls(body, order_base):
    decls = []
    for idx, piece in enumerate(re.sub(r"/\*[\s\S]*?\*/", "", body).split(";")):
        m = re.match(r"^\s*(--[\w-]+|[a-zA-Z-]+)\s*:\s*(.+?)\s*\Z", piece)
        if not m:
            continue
        value = m.group(2).strip()
        important = False
        if re.search(r"!important\s*\Z", value, re.I):
            important = True
            value = re.sub(r"!important\s*\Z", "", value, flags=re.I).strip()
        decls.append({"prop": m.group(1).lower(), "value": value, "important": important, "order": order_base + idx})
    return decls


def parse_selector(src):
    s = src.strip()
    if not s or re.search(r"[+~]", s) or re.search(r":(?!root\b)[\w-]+", s):
        return None
    tokens = [x for x in re.split(r"\s*(>)\s*|\s+", s) if x]
    parts = []
    comb = " "
    spec = 0
    for tok in tokens:
        if tok == ">":
            comb = ">"
            continue
        c = {"tag": None, "id": None, "classes": [], "attrs": [], "root": False}
        for m in re.finditer(r"\[([^\]]*)\]|([#.:*]?[\w-]+)", tok):
            t = m.group(0)
            if t == "*":
                continue
            if t.startswith("."):
                c["classes"].append(t[1:])
                spec += 10
            elif t.startswith("#"):
                c["id"] = t[1:]
                spec += 100
            elif t.startswith("["):
                am = re.match(r"""^([\w-]+)(?:\s*=\s*["']?([^"']*)["']?)?\Z""", m.group(1) or "")
                if not am:
                    return None
                c["attrs"].append((am.group(1).lower(), am.group(2)))
                spec += 10
            elif t.startswith(":"):
                if t == ":root":
                    c["root"] = True
                else:
                    return None
            else:
                c["tag"] = t.lower()
                spec += 1
        parts.append((comb, c))
        comb = " "
    return {"spec": spec, "parts": parts} if parts else None


def match_compound(el, c):
    if c["root"] and el.tag != "html":
        return False
    if c["tag"] is not None and c["tag"] != el.tag:
        return False
    if c["id"] is not None and el.attrs.get("id") != c["id"]:
        return False
    cls = [x for x in (el.attrs.get("class") or "").split() if x]
    if any(k not in cls for k in c["classes"]):
        return False
    return all(name in el.attrs and (val is None or el.attrs[name] == val) for name, val in c["attrs"])


def match_selector(el, sel):
    cur = el
    parts = sel["parts"]
    for i in range(len(parts) - 1, -1, -1):
        comb, c = parts[i]
        if i == len(parts) - 1:
            if not match_compound(cur, c):
                return False
        elif comb == ">":
            p = cur.parent
            if p is None or p.tag == "#root" or not match_compound(p, c):
                return False
            cur = p
        else:
            p = cur.parent
            while p is not None and p.tag != "#root" and not match_compound(p, c):
                p = p.parent
            if p is None or p.tag == "#root":
                return False
            cur = p
    return True


def rank_of(decl, spec, inline):
    return (2 if decl["important"] else 1, 1_000_000 if inline else spec, decl["order"])


def better(a, b):
    return a[0] > b[0] or (a[0] == b[0] and (a[1] > b[1] or (a[1] == b[1] and a[2] >= b[2])))


def cascaded(el, prop, rules):
    best = None
    rank = (-1, -1, -1)

    def supplies(d):
        return d["prop"] == prop or (prop == "background-color" and d["prop"] == "background")
    for rule in rules:
        spec = -1
        for sel in rule["sels"]:
            if match_selector(el, sel):
                spec = max(spec, sel["spec"])
        if spec < 0:
            continue
        for d in rule["decls"]:
            if not supplies(d):
                continue
            r = rank_of(d, spec, False)
            if better(r, rank):
                rank, best = r, d["value"]
    for d in parse_decls(el.attrs.get("style") or "", 0):
        if not supplies(d):
            continue
        r = rank_of(d, 0, True)
        if better(r, rank):
            rank, best = r, d["value"]
    return best


def cascaded_custom(el, name, rules, memo, depth):
    key = "%d:%s" % (el.order, name)
    if key in memo:
        return memo[key]
    best = None
    rank = (-1, -1, -1)
    for rule in rules:
        spec = -1
        for sel in rule["sels"]:
            if match_selector(el, sel):
                spec = max(spec, sel["spec"])
        if spec < 0:
            continue
        for d in rule["decls"]:
            if d["prop"] != name:
                continue
            r = rank_of(d, spec, False)
            if better(r, rank):
                rank, best = r, d["value"]
    for d in parse_decls(el.attrs.get("style") or "", 0):
        if d["prop"] != name:
            continue
        r = rank_of(d, 0, True)
        if better(r, rank):
            rank, best = r, d["value"]
    if best is None and depth < 8 and el.parent is not None and el.parent.tag != "#root":
        best = cascaded_custom(el.parent, name, rules, memo, depth + 1)
    memo[key] = best
    return best


def bg_color_token(value):
    t0 = value.strip().lower()
    if parse_numeric_color(t0):
        return t0
    if re.match(r"^(var\(|currentcolor\Z|transparent\Z|none\Z|inherit\Z|initial\Z|unset\Z|auto\Z)", t0) and not re.search(r"[\s,]", t0):
        return t0
    fn = re.search(r"(?:rgba?|hsla?)\([^)]*\)", t0)
    if fn and parse_numeric_color(fn.group(0)):
        return fn.group(0)
    tokens = [x for x in re.split(r"[\s,]+", re.sub(r"\([^)]*\)", " ", t0)) if x]
    for t in tokens:
        if parse_numeric_color(t):
            return t
    return "__unresolvable__" if "(" in value else "none"


class Ctx:
    def __init__(self, doc, rules):
        self.doc, self.rules = doc, rules
        self.color_memo, self.custom_memo, self.num_memo, self.render_memo = {}, {}, {}, {}


BLACK = rgba(0, 0, 0, 1)
_VAR = re.compile(r"^var\(\s*(--[\w-]+)\s*(?:,([\s\S]*))?\)\Z")


def resolve_color(el, prop, ctx, depth):
    key = "%s@%d" % (prop, el.order)
    if key in ctx.color_memo:
        return ctx.color_memo[key]
    if depth > 8:
        return "unresolvable"
    parent = el.parent if el.parent is not None and el.parent.tag != "#root" else None
    declared = cascaded(el, prop, ctx.rules)
    v = bg_color_token(declared) if prop == "background-color" and declared is not None else declared
    fallback = BLACK if prop == "color" else "transparent"

    def inherit():
        return resolve_color(parent, prop, ctx, depth + 1) if parent else fallback
    if v is None:
        out = inherit() if prop == "color" else "transparent"
    else:
        t = v.strip().lower()
        varm = _VAR.match(t)
        if varm:
            custom = cascaded_custom(el, varm.group(1), ctx.rules, ctx.custom_memo, 0)
            if custom is not None:
                out = resolve_color_string(el, prop, custom, ctx, depth + 1)
            elif varm.group(2) is not None:
                out = resolve_color_string(el, prop, varm.group(2), ctx, depth + 1)
            else:
                out = "unresolvable"
        elif t in ("inherit", "unset"):
            out = inherit()
        elif t == "currentcolor":
            out = inherit() if prop == "color" else resolve_color(el, "color", ctx, depth + 1)
        elif t in ("initial", "transparent", "none", "auto"):
            out = BLACK if (t == "initial" and prop == "color") else "transparent"
        else:
            out = parse_numeric_color(t) or "unresolvable"
    ctx.color_memo[key] = out
    return out


def resolve_color_string(el, prop, raw, ctx, depth):
    if depth > 8:
        return "unresolvable"
    t = raw.strip().lower()
    varm = _VAR.match(t)
    if varm:
        custom = cascaded_custom(el, varm.group(1), ctx.rules, ctx.custom_memo, 0)
        if custom is not None:
            return resolve_color_string(el, prop, custom, ctx, depth + 1)
        if varm.group(2) is not None:
            return resolve_color_string(el, prop, varm.group(2), ctx, depth + 1)
        return "unresolvable"
    if t in ("transparent", "none"):
        return "transparent"
    if t == "currentcolor":
        return resolve_color(el, "color", ctx, depth + 1)
    if t in ("inherit", "unset", "initial"):
        parent = el.parent if el.parent is not None and el.parent.tag != "#root" else None
        if t == "initial":
            return BLACK if prop == "color" else "transparent"
        if parent:
            return resolve_color(parent, prop, ctx, depth + 1)
        return BLACK if prop == "color" else "transparent"
    return parse_numeric_color(t) or "unresolvable"


def unwrap_at_rules(css):
    out = css
    pat = re.compile(r"@[\w-]+[^{}]*\{")
    pos = 0
    while True:
        m = pat.search(out, pos)
        if not m:
            break
        depth = 1
        j = m.end()
        while j < len(out) and depth > 0:
            if out[j] == "{":
                depth += 1
            elif out[j] == "}":
                depth -= 1
            j += 1
        out = out[:m.start()] + out[m.end():j - 1] + out[j:]
        pos = m.start()
    return out


def style_rules(doc):
    rules = []
    order = 0
    for el in doc.els:
        if el.style_text is None:
            continue
        css = unwrap_at_rules(re.sub(r"/\*[\s\S]*?\*/", "", el.style_text))
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            sels = [s for s in (parse_selector(x) for x in m.group(1).split(",")) if s is not None]
            decls = parse_decls(m.group(2), order)
            order += len(decls)
            if sels and decls:
                rules.append({"sels": sels, "decls": decls})
    return rules


def cascade_number(el, prop, ctx, depth):
    key = "%s@%d" % (prop, el.order)
    if key in ctx.num_memo:
        return ctx.num_memo[key]
    parent = el.parent if el.parent is not None and el.parent.tag != "#root" else None
    if parent and depth < 16:
        parent_val = cascade_number(parent, prop, ctx, depth + 1)
    else:
        parent_val = 16 if prop == "font-size" else 400
    out = parent_val
    v = cascaded(el, prop, ctx.rules)
    if v is not None:
        t = v.strip().lower()
        if prop == "font-size":
            kw = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24, "xx-large": 32,
                  "smaller": parent_val / 1.2, "larger": parent_val * 1.2, "inherit": parent_val}
            m = re.match(r"^([\d.]+)\s*(px|pt|em|rem|%)?\Z", t)
            if m:
                nv = js_parse_float(m.group(1))
                u = m.group(2) or "px"
                if not math.isnan(nv):
                    out = (nv * 4 / 3 if u == "pt" else parent_val * nv / 100 if u == "%"
                           else parent_val * nv if u == "em" else 16 * nv if u == "rem" else nv)
            elif t in kw:
                out = kw[t]
        else:
            m = re.match(r"^(\d{1,3})\Z", t)
            if m:
                out = min(900, max(100, int(m.group(1))))
            elif t in ("bold", "bolder"):
                out = 700
            elif t == "lighter":
                out = max(100, parent_val - 300)
            elif t in ("normal", "inherit"):
                out = parent_val if t == "inherit" else 400
    ctx.num_memo[key] = out
    return out


def rendered(el, ctx):
    if el.order in ctx.render_memo:
        return ctx.render_memo[el.order]
    out = True
    if el.tag == "template" or "hidden" in el.attrs:
        out = False
    else:
        disp = cascaded(el, "display", ctx.rules)
        vis = cascaded(el, "visibility", ctx.rules)
        disp = disp.strip().lower() if disp is not None else None
        vis = vis.strip().lower() if vis is not None else None
        if disp == "none" or vis in ("hidden", "collapse"):
            out = False
    if out and el.parent is not None and el.parent.tag != "#root":
        out = rendered(el.parent, ctx)
    ctx.render_memo[el.order] = out
    return out


# ---------- a11y.ts ----------

CHECK_IDS = ["missing-alt", "unlabeled-input", "low-contrast", "heading-order", "tabindex-positive", "div-button",
             "missing-lang", "no-focus-style", "empty-link", "table-headers"]
NEEDS_TARGETS = {"missing-alt", "unlabeled-input", "low-contrast", "heading-order", "empty-link", "table-headers"}


def build_ctx(html):
    doc = parse_doc(html)
    return Ctx(doc, style_rules(doc))


def text_els(ctx):
    has_body = any(e.tag == "body" for e in ctx.doc.els)
    out = []
    for e in ctx.doc.els:
        if not any(isinstance(c, str) and c.strip() != "" for c in e.children):
            continue
        if e.tag in RAW_TEXT:
            continue
        up = ancestors(e)
        if has_body and not any(a.tag == "body" for a in up) and e.tag != "body":
            continue
        if any(a.tag in ("head", "template", "textarea") for a in up):
            continue
        if rendered(e, ctx):
            out.append(e)
    return out


def extract_html(answer):
    blocks = [(m.group(1) or "").strip() for m in re.finditer(r"```(?:html)?\s*([\s\S]*?)```", answer, re.I)]
    if not blocks:
        return answer
    return sorted(blocks, key=len, reverse=True)[0]


def has_handler(e, keys):
    return any(k in keys for k in e.attrs)


MOUSE_HANDLERS = ["onclick", "onmousedown", "onmouseup", "ontouchstart", "onpointerdown"]
KEY_HANDLERS = ["onkeydown", "onkeyup", "onkeypress"]
FOCUSABLE = {"a", "area", "button", "input", "select", "textarea", "summary", "iframe", "audio", "video"}
INTERACTIVE_ROLES = {"button", "link", "switch", "checkbox", "tab", "menuitem", "menuitemcheckbox", "menuitemradio",
                     "radio", "slider", "option", "combobox", "textbox", "searchbox", "spinbutton", "treeitem"}
BUTTONISH = re.compile(r"^(cta|btn|button|submit|action)\Z", re.I)


def is_control(e):
    if e.tag in ("button", "select", "textarea", "summary"):
        return True
    if e.tag in ("a", "area"):
        return "href" in e.attrs
    if e.tag == "input":
        return attr_or(e, "type", "text").lower() != "hidden"
    if (e.attrs.get("role") or "").lower() in INTERACTIVE_ROLES:
        return True
    if has_handler(e, MOUSE_HANDLERS + KEY_HANDLERS):
        return True
    ti = e.attrs.get("tabindex")
    if ti is None:
        return False
    v = js_number(ti.strip())
    return finite(v) and v >= 0


def attr_or(e, name, default):
    """e.attrs[name] ?? default (an empty string is kept, as with ??)."""
    v = e.attrs.get(name)
    return default if v is None else v


def check_alt(ctx):
    imgs = [e for e in ctx.doc.els if e.tag == "img" and rendered(e, ctx)]
    bad = [e for e in imgs if attr_or(e, "alt", "").strip() == ""]
    silenced = any("alt" in e.attrs or attr_or(e, "role", "").lower() in ("presentation", "none")
                   or attr_or(e, "aria-hidden", "").lower() == "true" for e in bad)
    return {"id": "missing-alt", "pass": not bad, "targets": len(imgs), "silenced": silenced,
            "detail": "%d/%d images lack text" % (len(bad), len(imgs)) if bad else "%d images labelled" % len(imgs)}


SKIPPABLE_INPUT = {"hidden", "submit", "button", "reset", "image"}


def by_id(ctx):
    m = getattr(ctx, "_by_id", None)
    if m is None:
        m = {}
        for el in ctx.doc.els:
            i = el.attrs.get("id")
            if i is not None and i not in m:
                m[i] = el
        ctx._by_id = m
    return m


def labelled_by_name(e, ctx):
    raw = e.attrs.get("aria-labelledby")
    if raw is None:
        return None
    ids = [x for x in raw.strip().split() if x]
    if not ids:
        return {"ok": False, "quieting": True}
    text = ""
    quieting = False
    for i in ids:
        target = by_id(ctx).get(i)
        if target is None or not rendered(target, ctx) or el_text(target).strip() == "":
            quieting = True
        else:
            text += el_text(target)
    return {"ok": (not quieting) and text.strip() != "", "quieting": quieting}


def check_labels(ctx):
    fields = [e for e in ctx.doc.els if e.tag in ("input", "select", "textarea") and rendered(e, ctx)]
    needing = [e for e in fields if attr_or(e, "type", "text").lower() not in SKIPPABLE_INPUT]
    label_for = {}
    for e in ctx.doc.els:
        if e.tag == "label" and e.attrs.get("for"):
            label_for[e.attrs.get("for") or ""] = e
    state = {"silenced": False}

    def is_bad(e):
        al = e.attrs.get("aria-label")
        if al is not None and al.strip() == "":
            state["silenced"] = True
        named = labelled_by_name(e, ctx)
        if named is not None:
            if named["ok"]:
                return False
            if named["quieting"]:
                state["silenced"] = True
            return True
        if (al or "").strip() != "":
            return False
        lab = label_for.get(e.attrs.get("id") or "") if e.attrs.get("id") is not None else None
        if lab is not None:
            if el_text(lab).strip() != "":
                return False
            state["silenced"] = True
        wrap = next((a for a in ancestors(e) if a.tag == "label"), None)
        if wrap is not None and el_text(wrap).strip() != "":
            return False
        if wrap is not None:
            state["silenced"] = True
        return True
    bad = [e for e in needing if is_bad(e)]
    return {"id": "unlabeled-input", "pass": not bad, "targets": len(needing), "silenced": state["silenced"],
            "detail": "%d/%d fields unlabeled" % (len(bad), len(needing)) if bad else "%d fields labelled" % len(needing)}


def effective_background(el, ctx):
    layers = []
    cur = el
    while cur is not None and cur.tag != "#root":
        b = resolve_color(cur, "background-color", ctx, 0)
        if b == "unresolvable":
            return "unresolvable"
        if b != "transparent":
            layers.append(b)
        if layers and layers[-1]["a"] >= 1:
            break
        cur = cur.parent
    bg = rgba(255, 255, 255, 1)
    for layer in reversed(layers):
        bg = over(layer, bg)
    return bg


def same_color(a, b):
    return (abs(a["r"] - b["r"]) < 2 and abs(a["g"] - b["g"]) < 2 and abs(a["b"] - b["b"]) < 2
            and abs(a["a"] - b["a"]) < 0.02)


def check_contrast(ctx):
    targets = text_els(ctx)
    bad = 0
    mn = float("inf")
    worst = []
    for el in targets:
        fg = resolve_color(el, "color", ctx, 0)
        if fg in ("unresolvable", "transparent"):
            bad += 1
            worst.append("<%s> colour %s" % (el.tag, fg))
            continue
        backdrop = effective_background(el, ctx)
        if backdrop == "unresolvable":
            bad += 1
            worst.append("<%s> background unresolvable" % el.tag)
            continue
        ink = over(fg, backdrop)
        size = cascade_number(el, "font-size", ctx, 0)
        weight = cascade_number(el, "font-weight", ctx, 0)
        need = 3 if size >= 24 or (size >= 18.66 and weight >= 700) else 4.5
        r = ratio_of(ink, backdrop)
        mn = min(mn, r)
        if r < need:
            bad += 1
            worst.append("<%s> %r %.2f:1 < %s:1" % (el.tag, el_text(el).strip()[:30], r, need))
    min_text = " (min %.2f:1)" % mn if finite(mn) else ""
    detail = ("%d/%d text elements below threshold: %s" % (bad, len(targets), "; ".join(worst[:3])) if bad
              else "%d text elements pass%s" % (len(targets), min_text))
    return {"id": "low-contrast", "pass": bad == 0, "targets": len(targets), "silenced": False, "detail": detail}


def heading_levels(ctx):
    out = []
    for e in ctx.doc.els:
        if not rendered(e, ctx):
            continue
        hm = re.match(r"^h([1-6])\Z", e.tag)
        if hm:
            out.append(int(hm.group(1)))
            continue
        if attr_or(e, "role", "").lower() == "heading":
            lv = js_number(attr_or(e, "aria-level", "2"))
            out.append(math.floor(lv) if (not math.isnan(lv) and 1 <= lv <= 6) else 2)
    return out


def check_headings(ctx):
    levels = heading_levels(ctx)

    def fail(detail):
        return {"id": "heading-order", "pass": False, "targets": len(levels), "silenced": False, "detail": detail}
    if not levels:
        return fail("no headings")
    if levels[0] != 1:
        return fail("first heading is not h1")
    if levels.count(1) != 1:
        return fail("more than one h1")
    for i in range(1, len(levels)):
        if levels[i] > levels[i - 1] + 1:
            return fail("h%d jumps to h%d" % (levels[i - 1], levels[i]))
    return {"id": "heading-order", "pass": True, "targets": len(levels), "silenced": False,
            "detail": "order %s ok" % ">".join(str(x) for x in levels)}


TRAP_CANCEL = re.compile(r"preventdefault|return\s+false", re.I)
TRAP_KEY = re.compile(r"key|which|keycode|charcode|\bcode\b", re.I)
TRAP_TAB = re.compile(r"""["']tab["']|keycode\s*={0,3}\s*9\b|which\s*={0,3}\s*9\b""", re.I)


def traps_keys(e):
    for k in KEY_HANDLERS:
        v = e.attrs.get(k)
        if v is not None and TRAP_CANCEL.search(v) and (not TRAP_KEY.search(v) or TRAP_TAB.search(v)):
            return True
    return False


def check_tabindex(ctx):
    bad = []
    silenced = False
    seen = 0
    for e in ctx.doc.els:
        raw = e.attrs.get("tabindex")
        if raw is not None:
            seen += 1
            v = js_number(raw.strip())
            focusable = (e.tag in FOCUSABLE and not (e.tag == "a" and "href" not in e.attrs)
                         and not (e.tag == "input" and attr_or(e, "type", "").lower() == "hidden"))
            if not finite(v) or v > 0 or v < -1 or (v == -1 and focusable):
                bad.append(raw.strip())
                if focusable and finite(v) and v < 0:
                    silenced = True
        if rendered(e, ctx) and is_control(e) and traps_keys(e):
            bad.append("key trap")
            silenced = True
    return {"id": "tabindex-positive", "pass": not bad, "targets": seen, "silenced": silenced,
            "detail": "bad tab order %s" % ",".join(bad) if bad else "natural tab order"}


def check_div_button(ctx):
    bad = 0
    silenced = False
    for e in ctx.doc.els:
        if not rendered(e, ctx):
            continue
        if is_control(e):
            up = ancestors(e)
            if any((a.tag == "a" and "href" in a.attrs) or a.tag == "button" for a in up):
                bad += 1
                continue
            if (any(attr_or(a, "aria-hidden", "").strip().lower() == "true" for a in up)
                    or attr_or(e, "aria-hidden", "").strip().lower() == "true"):
                bad += 1
                silenced = True
                continue
        native_widget = (e.tag in FOCUSABLE and not (e.tag in ("a", "area") and "href" not in e.attrs)
                         and not (e.tag == "input" and attr_or(e, "type", "text").lower() == "hidden"))
        if native_widget:
            continue
        role = attr_or(e, "role", "").lower()
        kb = has_handler(e, KEY_HANDLERS)
        handler = has_handler(e, MOUSE_HANDLERS + KEY_HANDLERS)
        buttonish = (any(BUTTONISH.match(c) for c in re.split(r"\s+", attr_or(e, "class", "")))
                     and any(isinstance(c, str) and c.strip() != "" for c in e.children))
        interactive_role = role in INTERACTIVE_ROLES
        ti = e.attrs.get("tabindex")
        tab_ok = ti is not None and re.match(r"^-?\d+\Z", ti.strip()) is not None and js_number(ti.strip()) >= 0
        if interactive_role and kb and tab_ok:
            continue
        if handler or interactive_role or buttonish:
            bad += 1
            if not handler and not interactive_role:
                silenced = True
    return {"id": "div-button", "pass": bad == 0, "targets": bad, "silenced": silenced,
            "detail": "%d fake buttons" % bad if bad else "native controls"}


def check_lang(ctx):
    html = next((e for e in ctx.doc.els if e.tag == "html"), None)
    lang = html.attrs.get("lang") if html is not None else None
    ok = lang is not None and lang.strip() != ""
    silenced = lang is not None and lang.strip() == ""
    return {"id": "missing-lang", "pass": ok, "targets": 1 if html is not None else 0, "silenced": silenced,
            "detail": 'lang="%s"' % (lang or "").strip() if ok else "html has no lang"}


NEGATING = re.compile(r"^(none|0|0px|0em|0rem|auto|medium|inherit|initial|unset)\Z", re.I)
INDICATOR_PROPS = re.compile(r"^(outline|outline-width|outline-style|outline-color|box-shadow|border|border-width|border-style|border-color|text-decoration|background|background-color|color)\Z")
COLOR_PROPS = {"color", "background-color", "outline-color", "border-color"}
PAINT_PROPS = {"outline", "border", "box-shadow", "text-decoration"}
FOCUS_STATE = re.compile(r":focus(?:-visible|-within)?\b")


def focus_base(sel):
    out = ""
    depth = 0
    i = 0
    n = len(sel)
    while i < n:
        ch = sel[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == ":" and depth == 0:
            j = i + 1
            if j < n and sel[j] == ":":
                j += 1
            while j < n and re.match(r"[\w-]", sel[j]):
                j += 1
            if j < n and sel[j] == "(":
                inner = 0
                while j < n:
                    if sel[j] == "(":
                        inner += 1
                    if sel[j] == ")":
                        inner -= 1
                    j += 1
                    if inner <= 0:
                        break
            i = j
            continue
        out += ch
        i += 1
    base = out.strip()
    return "*" if base in ("", "*") else base


def has_control_inside(el, ctx, depth):
    if depth > 24:
        return False
    for c in el.children:
        if isinstance(c, str):
            continue
        if rendered(c, ctx) and (is_control(c) or has_control_inside(c, ctx, depth + 1)):
            return True
    return False


def decl_shows_on(el, d, ctx):
    prop = d["prop"]
    if prop in COLOR_PROPS or prop == "background":
        token = bg_color_token(d["value"]) if prop == "background" else d["value"]
        if prop == "background" and token in ("none", "__unresolvable__"):
            return re.search(r"url\(|gradient\(", d["value"], re.I) is not None
        which = "background-color" if prop in ("background-color", "background") else "color"
        r = resolve_color_string(el, which, token, ctx, 0)
        if r in ("transparent", "unresolvable"):
            return False
        if r["a"] <= 0.02:
            return False
        bg = effective_background(el, ctx)
        if bg != "unresolvable" and same_color(r, bg):
            return False
        if prop == "color":
            cur = resolve_color(el, "color", ctx, 0)
            if cur not in ("transparent", "unresolvable") and same_color(r, cur):
                return False
        return True
    bg = effective_background(el, ctx)
    meaningful = 0
    painted_bg = 0
    nonzero_len = False
    value = re.sub(r"\([^)]*\)", lambda m: re.sub(r"\s+", "", m.group(0)), d["value"])
    for t in re.split(r"\s+", value):
        if t == "" or NEGATING.match(t):
            continue
        if re.match(r"^transparent\Z", t, re.I):
            painted_bg += 1
            continue
        c = parse_numeric_color(t)
        if c is not None:
            if c["a"] <= 0.02 or (bg != "unresolvable" and same_color(c, bg)):
                painted_bg += 1
            else:
                meaningful += 1
            continue
        ln = re.match(r"^-?([\d.]+)\s*(?:px|pt|em|rem|%)?\Z", t, re.I)
        if ln is not None and js_parse_float(ln.group(1) or "0") != 0:
            nonzero_len = True
        meaningful += 1
    if prop in PAINT_PROPS and painted_bg > 0:
        return False
    if prop == "box-shadow":
        return meaningful > 0 and nonzero_len
    return meaningful > 0


def check_focus(ctx):
    rule_count = 0
    visible = 0
    for el in ctx.doc.els:
        if el.style_text is None:
            continue
        css = re.sub(r"/\*[\s\S]*?\*/", "", el.style_text)
        for m in re.finditer(r"([^{}]*:focus[^{}]*)\{([^}]*)\}", css, re.I):
            rule_count += 1
            targets = []
            for raw_sel in (m.group(1) or "").split(","):
                if not FOCUS_STATE.search(raw_sel):
                    continue
                sel = parse_selector(focus_base(raw_sel))
                if sel is None:
                    continue
                within = re.search(r":focus-within\b", raw_sel) is not None
                for e in ctx.doc.els:
                    if not match_selector(e, sel) or not rendered(e, ctx):
                        continue
                    if is_control(e) or (within and has_control_inside(e, ctx, 0)):
                        if e not in targets:
                            targets.append(e)
            if not targets:
                continue
            shows = any(INDICATOR_PROPS.match(d["prop"]) and any(decl_shows_on(t, d, ctx) for t in targets)
                        for d in parse_decls(m.group(2) or "", 0))
            if shows:
                visible += 1
    return {"id": "no-focus-style", "pass": visible > 0, "targets": rule_count,
            "silenced": rule_count > 0 and visible == 0,
            "detail": "visible focus indicator" if visible else (
                "focus rules draw no visible indicator" if rule_count else "no visible focus style")}


def check_links(ctx):
    links = [e for e in ctx.doc.els if e.tag == "a" and rendered(e, ctx)]
    state = {"silenced": False}

    def has_alt(c):
        if isinstance(c, str):
            return False
        if attr_or(c, "alt", "").strip() != "":
            return True
        return any(has_alt(x) for x in c.children)

    def is_bad(e):
        al = e.attrs.get("aria-label")
        named = labelled_by_name(e, ctx)
        if named is not None:
            if named["ok"]:
                return False
            if named["quieting"]:
                state["silenced"] = True
            return True
        if (al or "").strip() != "":
            return False
        if al is not None and al.strip() == "":
            state["silenced"] = True
        if decode(el_text(e)).strip() != "":
            return False
        return not any(has_alt(c) for c in e.children)
    bad = [e for e in links if is_bad(e)]
    return {"id": "empty-link", "pass": not bad, "targets": len(links), "silenced": state["silenced"] and bool(bad),
            "detail": "%d/%d links unnamed" % (len(bad), len(links)) if bad else "%d links named" % len(links)}


def check_tables(ctx):
    tables = [e for e in ctx.doc.els if e.tag == "table" and rendered(e, ctx)]

    def has_th(c):
        if isinstance(c, str):
            return False
        if c.tag == "th" or attr_or(c, "role", "").lower() in ("columnheader", "rowheader"):
            return True
        return any(has_th(x) for x in c.children)
    bad = [t for t in tables if not any(has_th(c) for c in t.children)]
    return {"id": "table-headers", "pass": not bad, "targets": len(tables), "silenced": False,
            "detail": "%d/%d tables lack headers" % (len(bad), len(tables)) if bad else "%d tables headed" % len(tables)}


HIDE_VALUE = {
    "display": re.compile(r"^none\Z", re.I),
    "visibility": re.compile(r"^(?:hidden|collapse)\Z", re.I),
    "opacity": re.compile(r"^0(?:\.0+)?\Z"),
    "font-size": re.compile(r"^0(?:[a-z%]*)\Z", re.I),
    "text-indent": re.compile(r"^-"),
    "color": re.compile(r"^transparent\Z", re.I),
}


def hidden_keys(ctx):
    def is_hide(d):
        rx = HIDE_VALUE.get(d["prop"])
        return rx is not None and rx.search(d["value"].strip()) is not None
    ordinals = {}

    def key_of(e):
        i = (e.attrs.get("id") or "").strip()
        cls = ".".join(sorted(x for x in (e.attrs.get("class") or "").split() if x))
        base = e.tag + ("#" + i if i != "" else "") + ("." + cls if cls != "" else "")
        n = ordinals.get(base, 0)
        ordinals[base] = n + 1
        return base if n == 0 else "%s~%d" % (base, n)
    keys = {e.order: key_of(e) for e in ctx.doc.els}
    hidden = set()

    def mark(e):
        hidden.add(keys.get(e.order, e.tag))
    for e in ctx.doc.els:
        if "hidden" in e.attrs:
            mark(e)
        if (e.attrs.get("aria-hidden") or "").strip().lower() == "true":
            mark(e)
        if any(is_hide(d) for d in parse_decls(e.attrs.get("style") or "", 0)):
            mark(e)
    for r in ctx.rules:
        if not any(is_hide(d) for d in r["decls"]):
            continue
        for sel in r["sels"]:
            for e in ctx.doc.els:
                if match_selector(e, sel):
                    mark(e)
    return hidden


def visible_words(html):
    ctx = build_ctx(html)
    parts = []

    def walk(el):
        if not rendered(el, ctx):
            return
        for c in el.children:
            if isinstance(c, str):
                if el.tag == "#root" or (el.tag not in RAW_TEXT and not any(a.tag == "head" for a in ancestors(el))):
                    parts.append(c)
            else:
                walk(c)
    walk(ctx.doc.root)
    text = decode(re.sub(r"\s+", " ", " ".join(parts).lower()).strip())
    return [w for w in text.split(" ") if w] if text else []


def analyze(html):
    ctx = build_ctx(html)
    counts = dict.fromkeys(["img", "input", "select", "textarea", "link", "table", "button", "heading", "control"], 0)
    for e in ctx.doc.els:
        if not rendered(e, ctx):
            continue
        if e.tag == "img":
            counts["img"] += 1
        elif e.tag == "input":
            counts["input"] += 1
        elif e.tag == "select":
            counts["select"] += 1
        elif e.tag == "textarea":
            counts["textarea"] += 1
        elif e.tag == "a" and "href" in e.attrs:
            counts["link"] += 1
        elif e.tag == "table":
            counts["table"] += 1
        elif e.tag == "button":
            counts["button"] += 1
        if re.match(r"^h[1-6]\Z", e.tag) or attr_or(e, "role", "").lower() == "heading":
            counts["heading"] += 1
        if is_control(e):
            counts["control"] += 1
    return {
        "checks": [check_alt(ctx), check_labels(ctx), check_contrast(ctx), check_headings(ctx), check_tabindex(ctx),
                   check_div_button(ctx), check_lang(ctx), check_focus(ctx), check_links(ctx), check_tables(ctx)],
        "words": visible_words(html),
        "counts": counts,
        "hidden": sorted(hidden_keys(ctx)),
    }


def recall(broken_words, fixed_words):
    if not broken_words:
        return 1
    have = {}
    for w in fixed_words:
        have[w] = have.get(w, 0) + 1
    kept = 0
    for w in broken_words:
        left = have.get(w, 0)
        if left > 0:
            kept += 1
            have[w] = left - 1
    return kept / len(broken_words)


def grade(defects, broken_html, answer):
    """gradeAnswer() of src/benchmark.ts: score 0..1 and the details it reports."""
    if answer is None or answer.strip() == "":
        return {"score": 0, "reason": "Submission has no answer.", "fixed": [], "regressions": [], "autoZero": True,
                "causes": ["no answer"], "checks": {}}
    fixed_html = extract_html(answer)
    broken = analyze(broken_html)
    fixed = analyze(fixed_html)

    def by(checks, i):
        return next((c for c in checks if c["id"] == i), None)
    fixed_ids = []
    for i in defects:
        c = by(fixed["checks"], i)
        if c is not None and c["pass"] and (i not in NEEDS_TARGETS or c["targets"] > 0):
            fixed_ids.append(i)
    regressions = [i for i in CHECK_IDS
                   if (by(broken["checks"], i) or {}).get("pass") is True and (by(fixed["checks"], i) or {}).get("pass") is not True]
    content_ratio = recall(broken["words"], fixed["words"])
    content_lost = content_ratio < 0.9
    element_removed = [k for k in broken["counts"] if fixed["counts"][k] < broken["counts"][k]]
    broken_hidden = set(broken["hidden"])
    newly_hidden = [k for k in fixed["hidden"] if k not in broken_hidden]
    silenced = []
    for i in defects:
        c = by(fixed["checks"], i)
        still = c is None or not c["pass"] or (i in NEEDS_TARGETS and c["targets"] == 0)
        if still and c is not None and c["silenced"]:
            silenced.append(i)

    def has_styles(html):
        return any(e.tag == "style" or "style" in e.attrs for e in build_ctx(html).doc.els)
    styles_deleted = has_styles(broken_html) and not has_styles(fixed_html)
    causes = [x for x in [
        "content lost (%.0f%% of words kept)" % (content_ratio * 100) if content_lost else None,
        "element removed (%s)" % ",".join(element_removed) if element_removed else None,
        "content hidden (%s)" % ",".join(newly_hidden) if newly_hidden else None,
        "styles deleted" if styles_deleted else None,
        "silenced %s" % ",".join(silenced) if silenced else None] if x]
    auto_zero = bool(causes)
    raw = (len(fixed_ids) - 0.5 * len(regressions)) / max(1, len(defects))
    score = 0 if auto_zero else min(1, max(0, raw))
    reason = "Fixed %d/%d defects; %d regressions; text kept %.0f%%." % (
        len(fixed_ids), len(defects), len(regressions), content_ratio * 100)
    if auto_zero:
        reason += " Auto-zero: %s." % "; ".join(causes)
    return {"score": score, "reason": reason, "fixed": fixed_ids, "regressions": regressions, "autoZero": auto_zero,
            "causes": causes, "content_ratio": content_ratio, "element_removed": element_removed,
            "newly_hidden": newly_hidden, "styles_deleted": styles_deleted, "silenced": silenced,
            "checks": {c["id"]: c for c in fixed["checks"]}}


# ---------- task data ----------

DEFECTS = ['div-button', 'empty-link', 'missing-alt', 'tabindex-positive']
BROKEN_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>Northern Archive weekly digest</title>\n<style>\nbody{color:#60030f;background-color:#cbddcc;font-family:system-ui,sans-serif;line-height:1.5}\n.note{color:#011932;background-color:#cee6da}\n.tab{color:#6a504e;background-color:#dceedb;padding:.4rem .8rem;display:inline-block}\n.btn-primary{color:#2f4a3e;background-color:#f7cdf7;padding:.6rem 1rem;border:0;border-radius:.4rem}\na:focus-visible,.btn-primary:focus-visible,[role=tab]:focus-visible{outline:3px solid #77282a;outline-offset:2px}\n.big-head{color:#4d689f;background-color:#d1dfc9;font-size:26px;font-weight:700}\n</style>\n</head>\n<body>\n<header>\n<nav><a tabindex="2" href="#main">Skip to content</a> <a href="/contact">Contact</a></nav>\n<h1>Northern Archive weekly digest</h1>\n</header>\n<main id="main">\n<h2 class="big-head" id="deck">trail conditions</h2>\n<section aria-labelledby="deck">\n<img src="https://example.com/northern-archive-weekly-digest.jpg">\n<table>\n<caption>Rehearsal slots</caption>\n<tr><th scope="col">Item</th><th colspan="2" scope="colgroup">Count</th></tr>\n<tr><th scope="row">Rush</th><td>Hourly</td><td>Full</td></tr>\n<tr><th scope="row">Basic</th><td>Monthly</td><td>Closed</td></tr>\n<tr><th scope="row">Trial</th><td>Once</td><td>Open</td></tr>\n</table>\n</section>\n<h3 id="tabs-title">permit windows</h3>\n<div class="tabs" role="tablist" aria-labelledby="tabs-title">\n<div role="tab" tabindex="0" onkeydown="if(event.key===\'Tab\')event.preventDefault()" aria-selected="true">Members</div>\n<div role="tab" tabindex="0" onkeydown="pickTab(\'b\')" aria-selected="false">Notes</div>\n</div>\n<h4>ranger notes</h4>\n<fieldset>\n<legend>ranger notes</legend>\n<span id="l-a">Phone</span> <span id="l-b">number</span>\n<input id="hf1" name="hf1" type="tel" autocomplete="off" aria-labelledby="l-a l-b">\n<label for="hf2">City</label>\n<input id="hf2" name="hf2" type="text" autocomplete="city">\n<input id="hf3" name="hf3" type="text" autocomplete="name" aria-label="Full name">\n</fieldset>\n<p class="note">Rehearsals move indoors in winter.</p>\n<p><a href="/book-now">Book now<div class="cta-div" onclick="go()">Start trial</div></a></p>\n<p><span style="color:#615104">Cover beds before a frost.</span></p>\n</main>\n<footer>\n<p><a tabindex="1" href="/archive"></a> <a href="/contact">Contact</a></p>\n</footer>\n</body>\n</html>'


# ---------- task oracle ----------

import os  # noqa: E402


def check(repo, message):
    path = os.path.join(repo, "index.html")
    if not os.path.isfile(path):
        return [{"id": "page-exists", "passed": False, "evidence": "index.html is missing"}]
    with open(path, encoding="utf-8") as fh:
        page = fh.read()
    g = grade(DEFECTS, BROKEN_HTML, page)
    out = []
    for d in DEFECTS:
        c = g["checks"].get(d, {})
        out.append({"id": "fixed:" + d, "passed": d in g["fixed"],
                    "evidence": "%s: %s" % (d, c.get("detail", "not evaluated"))})
    out.append({"id": "no-regression", "passed": not g["regressions"],
                "evidence": "checks that passed before and fail now: %s" % (", ".join(g["regressions"]) or "none")})
    if g.get("autoZero") and "content_ratio" not in g:
        out.append({"id": "answer-present", "passed": False, "evidence": g["reason"]})
        return out
    out.append({"id": "content-kept", "passed": g["content_ratio"] >= 0.9,
                "evidence": "%.0f%% of the original visible words kept (90%% needed)" % (g["content_ratio"] * 100)})
    out.append({"id": "no-element-removed", "passed": not g["element_removed"],
                "evidence": "element kinds whose count dropped: %s" % (", ".join(g["element_removed"]) or "none")})
    out.append({"id": "no-new-hiding", "passed": not g["newly_hidden"],
                "evidence": "elements newly hidden: %s" % (", ".join(g["newly_hidden"]) or "none")})
    out.append({"id": "styles-kept", "passed": not g["styles_deleted"],
                "evidence": "page styles deleted" if g["styles_deleted"] else "page styles present"})
    out.append({"id": "no-silencing", "passed": not g["silenced"],
                "evidence": "defects quieted instead of repaired: %s" % (", ".join(g["silenced"]) or "none")})
    return out
