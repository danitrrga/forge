"""Oracle for ui-layout-bug-02 (authored). Reads index.html and every stylesheet it links, evaluates the cascade at
every whole viewport width from 320 to 480px and at steps up to 1600px (plus each width either side of the page's
breakpoints), and lays out the plan cards with a width-only model: block widths down to .plans, then the grid
(repeat with auto-fill/auto-fit, minmax, min()/max()/clamp(), fr, auto) or flex algorithm over the cards. Checks: no card
sticks out at any width (320-367px is where the original overflows), and at every width where the original page
already fitted, each card keeps its row, its column and its width (to 1px), so a fix may change only the widths that
were broken. The original page is embedded below and laid out by the same model for that comparison.

What it cannot see: heights, real font metrics (card text is measured at 0.55em per character, far below any card
width), container queries (a stylesheet using @container is reported and fails), floats, absolute positioning and
JavaScript. It does not judge visual taste; any layout that fits and leaves the working widths alone passes.
"""
# ---------- a small static HTML + CSS engine (standard library only) ----------
# DOM from html.parser; author stylesheets from <link rel=stylesheet> (local files), <style> and style=""; @media
# evaluated at a given viewport width; @supports and @layer contents applied (layer order ignored); selectors with
# type/class/id/attribute/:root/:not/:is/:where/:first-child/:last-child/:only-child/:nth-child and all four
# combinators; specificity, source order, !important, inheritance, var(), calc()/min()/max()/clamp().
import html.parser
import math
import os
import re

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
INHERITED = {"white-space", "white-space-collapse", "text-wrap-mode", "overflow-wrap", "word-break", "font-size",
             "font-family", "color", "line-height", "font-weight", "visibility", "text-align", "direction"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []
        self.mcache = {}
        self.inline = None

    @property
    def elements(self):
        return [c for c in self.children if isinstance(c, Node)]

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def iter(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.iter()

    def __repr__(self):
        cls = ".".join(self.classes())
        return "<%s%s>" % (self.tag, "." + cls if cls else "")


class _Builder(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, None)
        self.cur = self.root
        self.raw = None

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k.lower(): (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in VOID_TAGS:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        n = Node(tag, {k.lower(): (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)

    def handle_endtag(self, tag):
        p = self.cur
        while p is not None and p.tag != tag:
            p = p.parent
        if p is not None and p.parent is not None:
            self.cur = p.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse_html(text):
    b = _Builder()
    b.feed(text)
    b.close()
    return b.root


def find_all(root, pred):
    return [n for n in root.iter() if pred(n)]


def by_class(root, cls):
    return find_all(root, lambda n: cls in n.classes())


# ---------- CSS parsing ----------

def strip_comments(css):
    return re.sub(r"/\*[\s\S]*?\*/", "", css)


def split_top(s, sep):
    """Split on sep outside parentheses, brackets and strings."""
    out, depth, cur, q = [], 0, "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def parse_declarations(body):
    decls = []
    for piece in split_top(body, ";"):
        if ":" not in piece:
            continue
        prop, _, value = piece.partition(":")
        prop, value = prop.strip().lower() if not prop.strip().startswith("--") else prop.strip(), value.strip()
        if not prop or not value:
            continue
        important = False
        m = re.search(r"!\s*important\s*$", value, re.I)
        if m:
            important, value = True, value[:m.start()].strip()
        decls.append((prop, value, important))
    return decls


def _block_end(css, i):
    """Index just past the } matching the { at css[i]."""
    depth = 0
    q = None
    while i < len(css):
        ch = css[i]
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(css)


class Sheet:
    def __init__(self):
        self.rules = []   # (selector_text, decls, media_list, order, source)
        self.unsupported = []
        self.n = 0

    def add(self, css, media=(), source="?", base_dir=None, depth=0):
        css = strip_comments(css)
        i = 0
        while i < len(css):
            j = css.find("{", i)
            semi = css.find(";", i)
            if j == -1:
                tail = css[i:].strip()
                if tail.startswith("@import"):
                    self._import(tail, media, source, base_dir, depth)
                break
            if css[i:j].lstrip().startswith("@import") and semi != -1 and semi < j:
                self._import(css[i:semi], media, source, base_dir, depth)
                i = semi + 1
                continue
            prelude = css[i:j].strip()
            end = _block_end(css, j)
            body = css[j + 1:end - 1]
            if prelude.startswith("@"):
                name = re.match(r"@([\w-]+)", prelude).group(1).lower()
                cond = prelude[len(name) + 1:].strip()
                if name == "media":
                    self.add(body, media + (cond,), source, base_dir, depth)
                elif name in ("supports", "layer", "scope", "document"):
                    self.add(body, media, source, base_dir, depth)
                elif name == "container":
                    self.unsupported.append("@container %s (not evaluated)" % cond)
                # @font-face, @keyframes, @page ...: no layout effect here
            elif prelude:
                self.n += 1
                self.rules.append((prelude, parse_declarations(body), media, self.n, source))
            i = end

    def compiled(self):
        if getattr(self, "_compiled", None) is None or self._compiled_n != len(self.rules):
            out = []
            for sel_text, decls, media, order, source in self.rules:
                sels = [(x.strip(), specificity(x.strip())) for x in split_top(sel_text, ",") if x.strip()]
                expanded = [(lp, lv, imp, k) for k, (p, v, imp) in enumerate(decls) for lp, lv in expand(p, v)]
                out.append((sels, expanded, media, order, source))
            self._compiled, self._compiled_n = out, len(self.rules)
        return self._compiled

    def _import(self, stmt, media, source, base_dir, depth):
        m = re.search(r"""@import\s+(?:url\()?\s*["']?([^"')\s]+)["']?\s*\)?\s*([^;]*)""", stmt)
        if not m or base_dir is None or depth > 5:
            return
        p = os.path.normpath(os.path.join(base_dir, m.group(1)))
        if os.path.isfile(p):
            extra = (m.group(2).strip(),) if m.group(2).strip() else ()
            self.add(open(p, encoding="utf-8").read(), media + extra, p, os.path.dirname(p), depth + 1)


def load_page(repo, page="index.html"):
    """(dom, sheet) for repo/page with every local stylesheet it links, in document order."""
    path = os.path.join(repo, page)
    dom = parse_html(open(path, encoding="utf-8").read())
    sheet = Sheet()
    sheet.add(UA_CSS, (), "ua")
    for n in dom.iter():
        if n.tag == "link" and "stylesheet" in (n.attrs.get("rel") or "").lower().split():
            href = (n.attrs.get("href") or "").split("?")[0]
            p = os.path.normpath(os.path.join(os.path.dirname(path), href))
            if href and not re.match(r"^[a-z]+:", href) and os.path.isfile(p):
                media = (n.attrs["media"],) if n.attrs.get("media") else ()
                sheet.add(open(p, encoding="utf-8").read(), media, os.path.relpath(p, repo), os.path.dirname(p))
        elif n.tag == "style":
            media = (n.attrs["media"],) if n.attrs.get("media") else ()
            sheet.add(n.text(), media, "<style>", os.path.dirname(path))
    return dom, sheet


# The few user-agent defaults the layout reasoning needs.
UA_CSS = """
html, body, div, p, ul, ol, li, main, header, footer, nav, section, article, aside, h1, h2, h3, h4, h5, h6, form,
fieldset, figure, blockquote, dl, dt, dd, table, details, summary, address, hr, pre, legend { display: block; }
li { display: list-item; }
head, script, style, title, meta, link, template, [hidden] { display: none; }
body { margin: 8px; }
ul, ol { padding-left: 40px; }
button, input, select, textarea { display: inline-block; }
button { padding: 1px 6px; border: 2px solid; }
img, svg { display: inline; }
table { display: table; }
"""


# ---------- media queries ----------

def _len_px(v, root_fs=16.0):
    m = re.match(r"^\s*(-?[\d.]+)\s*(px|em|rem)?\s*$", v)
    if not m:
        return None
    n = float(m.group(1))
    return n if (m.group(2) or "px") == "px" else n * root_fs


def media_matches(cond, width, height=800):
    cond = cond.strip().lower()
    if not cond:
        return True
    for q in split_top(cond, ","):
        if _query_matches(q.strip(), width, height):
            return True
    return False


def _query_matches(q, w, h):
    neg = False
    if q.startswith("not "):
        neg, q = True, q[4:].strip()
    if q.startswith("only "):
        q = q[5:].strip()
    ok = True
    for part in re.split(r"\s+and\s+", q):
        part = part.strip()
        if not part:
            continue
        if part in ("screen", "all"):
            continue
        if part in ("print", "speech"):
            ok = False
            continue
        m = re.match(r"^\((.*)\)$", part)
        if not m:
            ok = False
            continue
        ok = ok and _feature(m.group(1).strip(), w, h)
    return (not ok) if neg else ok


def _feature(f, w, h):
    m = re.match(r"^(min-|max-)?(width|height)\s*:\s*(.+)$", f)
    if m:
        v = _len_px(m.group(3))
        if v is None:
            return False
        x = w if m.group(2) == "width" else h
        return x >= v if m.group(1) == "min-" else x <= v if m.group(1) == "max-" else x == v
    # range syntax: (width >= 40em), (400px <= width < 800px)
    toks = re.split(r"\s*(<=|>=|<|>|=)\s*", f)
    if len(toks) in (3, 5):
        def val(t):
            if t in ("width", "height"):
                return w if t == "width" else h
            return _len_px(t)
        vals = [val(t) for t in toks[0::2]]
        if any(v is None for v in vals):
            return False
        ops = toks[1::2]
        for a, op, b in zip(vals, ops, vals[1:]):
            if not {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "=": a == b}[op]:
                return False
        return True
    m = re.match(r"^orientation\s*:\s*(portrait|landscape)$", f)
    if m:
        return (h >= w) == (m.group(1) == "portrait")
    return False


# ---------- selectors ----------

def _split_complex(sel):
    """[(combinator, compound_text)] with combinator in ' ', '>', '+', '~' (first is ' ')."""
    parts, cur, comb, depth = [], "", " ", 0
    i = 0
    s = sel.strip()
    while i < len(s):
        ch = s[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and (ch in ">+~" or ch.isspace()):
            if cur:
                parts.append((comb, cur))
                cur = ""
                comb = " "
            j = i
            while j < len(s) and (s[j].isspace() or s[j] in ">+~"):
                if s[j] in ">+~":
                    comb = s[j]
                j += 1
            i = j
            continue
        cur += ch
        i += 1
    if cur:
        parts.append((comb, cur))
    return parts


_SIMPLE = re.compile(r"""\*|[a-zA-Z][\w-]*|\.[\w-]+|\#[\w-]+|\[[^\]]*\]|::?[\w-]+(?:\((?:[^()]|\([^()]*\))*\))?""")


def _simples(compound):
    out, pos = [], 0
    while pos < len(compound):
        m = _SIMPLE.match(compound, pos)
        if not m:
            return None
        out.append(m.group(0))
        pos = m.end()
    return out


def _nth(expr, idx):
    e = expr.replace(" ", "").lower()
    if e == "odd":
        e = "2n+1"
    if e == "even":
        e = "2n"
    m = re.match(r"^([+-]?\d*)n([+-]\d+)?$", e)
    if m:
        a = m.group(1)
        a = 1 if a in ("", "+") else -1 if a == "-" else int(a)
        b = int(m.group(2) or 0)
        if a == 0:
            return idx == b
        return (idx - b) % a == 0 and (idx - b) / a >= 0
    if re.match(r"^[+-]?\d+$", e):
        return idx == int(e)
    return False


STATE_PSEUDOS = {"hover", "focus", "focus-visible", "focus-within", "active", "visited", "target", "checked",
                 "disabled", "enabled", "invalid", "valid", "placeholder-shown", "open", "popover-open"}


def match_compound(n, compound):
    simples = _simples(compound)
    if simples is None:
        return False
    for s in simples:
        if s == "*":
            continue
        if s[0] == ".":
            if s[1:] not in n.classes():
                return False
        elif s[0] == "#":
            if n.attrs.get("id") != s[1:]:
                return False
        elif s[0] == "[":
            m = re.match(r"""^\[\s*([\w-]+)\s*(?:([~|^$*]?=)\s*["']?([^"'\]]*)["']?\s*(i)?)?\s*\]$""", s)
            if not m:
                return False
            name, op, val = m.group(1).lower(), m.group(2), m.group(3)
            if name not in n.attrs:
                return False
            have = n.attrs[name]
            if m.group(4):
                have, val = have.lower(), (val or "").lower()
            if op == "=" and have != val:
                return False
            if op == "~=" and val not in have.split():
                return False
            if op == "^=" and not have.startswith(val):
                return False
            if op == "$=" and not have.endswith(val):
                return False
            if op == "*=" and val not in have:
                return False
            if op == "|=" and not (have == val or have.startswith(val + "-")):
                return False
        elif s.startswith("::"):
            return False          # pseudo-elements generate no element of the DOM
        elif s[0] == ":":
            m = re.match(r"^:([\w-]+)(?:\((.*)\))?$", s)
            name, arg = m.group(1).lower(), m.group(2)
            sibs = n.parent.elements if n.parent is not None else [n]
            if name == "root":
                if n.tag != "html":
                    return False
            elif name in ("not", "is", "where", "matches"):
                hit = any(matches(n, x) for x in split_top(arg or "", ","))
                if (name == "not") == hit:
                    return False
            elif name == "first-child":
                if sibs[0] is not n:
                    return False
            elif name == "last-child":
                if sibs[-1] is not n:
                    return False
            elif name == "only-child":
                if len(sibs) != 1:
                    return False
            elif name == "nth-child":
                if not _nth(arg or "", sibs.index(n) + 1):
                    return False
            elif name == "nth-last-child":
                if not _nth(arg or "", len(sibs) - sibs.index(n)):
                    return False
            elif name in ("first-of-type", "last-of-type"):
                same = [x for x in sibs if x.tag == n.tag]
                if (same[0] if name == "first-of-type" else same[-1]) is not n:
                    return False
            elif name in ("before", "after", "first-line", "first-letter", "marker", "placeholder"):
                return False
            else:
                return False      # state pseudos (:hover, :focus ...) never apply to the resting render
        else:
            if n.tag != s.lower():
                return False
    return True


def matches(n, sel):
    hit = n.mcache.get(sel)
    if hit is None:
        hit = n.mcache[sel] = _matches(n, sel)
    return hit


def _matches(n, sel):
    parts = _split_complex(sel)
    if not parts:
        return False
    return _match_from(n, parts, len(parts) - 1)


def _match_from(n, parts, i):
    comb, compound = parts[i]
    if not match_compound(n, compound):
        return False
    if i == 0:
        return True
    nxt = parts[i][0]
    if nxt == ">":
        p = n.parent
        return p is not None and p.tag != "#document" and _match_from(p, parts, i - 1)
    if nxt == " ":
        p = n.parent
        while p is not None and p.tag != "#document":
            if _match_from(p, parts, i - 1):
                return True
            p = p.parent
        return False
    sibs = n.parent.elements if n.parent is not None else []
    k = sibs.index(n)
    if nxt == "+":
        return k > 0 and _match_from(sibs[k - 1], parts, i - 1)
    return any(_match_from(s, parts, i - 1) for s in sibs[:k])


def specificity(sel):
    a = b = c = 0
    for _, compound in _split_complex(sel):
        for s in _simples(compound) or []:
            if s == "*":
                continue
            if s[0] == "#":
                a += 1
            elif s[0] in ".[":
                b += 1
            elif s.startswith("::"):
                c += 1
            elif s[0] == ":":
                m = re.match(r"^:([\w-]+)(?:\((.*)\))?$", s)
                name, arg = m.group(1).lower(), m.group(2)
                if name == "where":
                    continue
                if name in ("not", "is", "matches"):
                    best = max((specificity(x) for x in split_top(arg or "", ",")), default=(0, 0, 0))
                    a, b, c = a + best[0], b + best[1], c + best[2]
                else:
                    b += 1
            else:
                c += 1
    return (a, b, c)


# ---------- cascade ----------

class Style:
    """Computed-ish values for one viewport width."""

    def __init__(self, sheet, width, height=800):
        self.width, self.height = width, height
        self.index = {}
        for sels, expanded, media, order, source in sheet.compiled():
            if all(media_matches(m, width, height) for m in media):
                for prop, value, imp, k in expanded:
                    for sel, spec in sels:
                        self.index.setdefault(prop, []).append(
                            ((1 if imp else 0, 0 if source == "ua" else 1, 0, spec, order, k), sel, value))
        for lst in self.index.values():
            lst.sort(key=lambda x: x[0], reverse=True)
        self.memo = {}

    def declared(self, n, prop):
        """Winning declared value of prop on n (after shorthand expansion), or None."""
        key = (id(n), prop)
        if key in self.memo:
            return self.memo[key]
        best, rank = None, None
        for r, sel, value in self.index.get(prop, ()):
            if matches(n, sel):
                best, rank = value, r
                break
        if n.inline is None:
            n.inline = [(lp, lv, imp, k) for k, (p, v, imp) in enumerate(parse_declarations(n.attrs.get("style") or ""))
                        for lp, lv in expand(p, v)]
        for lp, lv, imp, k in n.inline:
            if lp == prop:
                r = (1 if imp else 0, 1, 1, (0, 0, 0), 0, k)
                if rank is None or r >= rank:
                    best, rank = lv, r
        self.memo[key] = best
        return best

    def get(self, n, prop, default=None):
        """Specified value with var() substituted and inheritance applied; default when nothing applies."""
        if n is None or n.tag == "#document":
            return INITIAL.get(prop, default)
        v = self.declared(n, prop)
        if v is not None:
            v = self.subst(n, v)
        if v is None or v.strip().lower() in ("inherit",) or (v.strip().lower() in ("unset", "revert") and prop in INHERITED):
            if v is None and prop not in INHERITED:
                return INITIAL.get(prop, default)
            return self.get(n.parent, prop, default)
        if v.strip().lower() in ("initial", "unset", "revert"):
            return INITIAL.get(prop, default)
        return v.strip()

    def custom(self, n, name):
        while n is not None and n.tag != "#document":
            v = self.declared(n, name)
            if v is not None:
                return v
            n = n.parent
        return None

    def subst(self, n, v, depth=0):
        if "var(" not in v or depth > 10:
            return v
        out, i = "", 0
        while True:
            j = v.find("var(", i)
            if j == -1:
                return out + v[i:]
            out += v[i:j]
            k, depth_p = j + 4, 1
            while k < len(v) and depth_p:
                depth_p += {"(": 1, ")": -1}.get(v[k], 0)
                k += 1
            inner = v[j + 4:k - 1]
            name, _, fallback = inner.partition(",")
            val = self.custom(n, name.strip())
            if val is None:
                val = fallback.strip() if fallback else None
            if val is None:
                return None
            out += self.subst(n, val, depth + 1)
            i = k

    # ---- lengths ----
    def root_font(self):
        return 16.0

    def font_size(self, n):
        if n is None or n.tag == "#document":
            return 16.0
        key = (id(n), "#fs")
        if key in self.memo:
            return self.memo[key]
        parent = self.font_size(n.parent) if n.parent is not None else 16.0
        v = self.declared(n, "font-size")
        v = self.subst(n, v) if v is not None else None
        out = parent
        if v is not None:
            t = v.strip().lower()
            kw = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24, "xx-large": 32,
                  "smaller": parent / 1.2, "larger": parent * 1.2}
            if t in kw:
                out = kw[t]
            elif t not in ("inherit", "unset"):
                x = self.length(n, t, basis=parent, em=parent)
                if x is not None:
                    out = x
        self.memo[key] = out
        return out

    def length(self, n, v, basis=None, em=None):
        """px value of a length/percentage/calc expression; None when it is not one (auto, none, keywords)."""
        if v is None:
            return None
        t = v.strip().lower()
        if em is None:
            em = self.font_size(n)
        try:
            return _calc(t, basis, em, self.root_font(), self.width, self.height)
        except (ValueError, ZeroDivisionError):
            return None


INITIAL = {"display": "inline", "overflow-x": "visible", "overflow-y": "visible", "white-space": "normal",
           "overflow-wrap": "normal", "word-break": "normal", "flex-direction": "row", "flex-wrap": "nowrap",
           "flex-grow": "0", "flex-shrink": "1", "flex-basis": "auto", "min-width": "auto", "max-width": "none",
           "width": "auto", "box-sizing": "content-box", "column-gap": "normal", "row-gap": "normal",
           "align-items": "normal", "align-self": "auto", "justify-items": "legacy", "grid-template-columns": "none",
           "grid-auto-columns": "auto", "grid-auto-flow": "row", "grid-column-start": "auto", "grid-column-end": "auto",
           "visibility": "visible", "position": "static", "text-overflow": "clip", "font-family": "serif",
           "padding-left": "0", "padding-right": "0", "margin-left": "0", "margin-right": "0",
           "border-left-width": "0", "border-right-width": "0", "border-left-style": "none", "border-right-style": "none",
           "text-wrap-mode": "wrap", "float": "none", "order": "0", "color": "canvastext", "background-color": "transparent"}

_BORDER_STYLES = {"none", "hidden", "dotted", "dashed", "solid", "double", "groove", "ridge", "inset", "outset"}


def _box4(vals):
    v = split_ws(vals)
    if len(v) == 1:
        return v * 4
    if len(v) == 2:
        return [v[0], v[1], v[0], v[1]]
    if len(v) == 3:
        return [v[0], v[1], v[2], v[1]]
    return v[:4]


def split_ws(v):
    out, cur, depth = [], "", 0
    for ch in v.strip():
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _border_parts(v):
    width, style = None, None
    for t in split_ws(v):
        tl = t.lower()
        if tl in _BORDER_STYLES:
            style = tl
        elif tl in ("thin", "medium", "thick") or re.match(r"^-?[\d.]", tl) or tl.startswith(("calc(", "min(", "max(", "clamp(")):
            width = {"thin": "1px", "medium": "3px", "thick": "5px"}.get(tl, t)
    return width, style


def expand(p, v):
    """Longhands set by one declaration (only the ones the reasoning needs)."""
    p = p if p.startswith("--") else p.lower()
    vl = v.strip()
    if p == "overflow":
        parts = split_ws(vl)
        return [("overflow-x", parts[0]), ("overflow-y", parts[-1])]
    if p == "word-wrap":
        return [("overflow-wrap", vl)]
    if p == "text-wrap":
        t = vl.lower().split()
        return [("text-wrap-mode", "nowrap" if "nowrap" in t else "wrap")] if t and t[0] in ("nowrap", "wrap") else []
    if p == "white-space":
        return [("white-space", vl)]
    if p == "flex":
        t = vl.lower()
        if t == "none":
            return [("flex-grow", "0"), ("flex-shrink", "0"), ("flex-basis", "auto")]
        if t == "auto":
            return [("flex-grow", "1"), ("flex-shrink", "1"), ("flex-basis", "auto")]
        if t in ("initial",):
            return [("flex-grow", "0"), ("flex-shrink", "1"), ("flex-basis", "auto")]
        parts = split_ws(vl)
        nums = [x for x in parts if re.match(r"^[\d.]+$", x)]
        rest = [x for x in parts if not re.match(r"^[\d.]+$", x)]
        grow = nums[0] if nums else "1"
        shrink = nums[1] if len(nums) > 1 else "1"
        basis = rest[0] if rest else ("0%" if nums else "auto")
        return [("flex-grow", grow), ("flex-shrink", shrink), ("flex-basis", basis)]
    if p == "flex-flow":
        out = []
        for x in split_ws(vl.lower()):
            if x in ("row", "row-reverse", "column", "column-reverse"):
                out.append(("flex-direction", x))
            elif x in ("wrap", "nowrap", "wrap-reverse"):
                out.append(("flex-wrap", x))
        return out
    if p in ("gap", "grid-gap"):
        parts = split_ws(vl)
        return [("row-gap", parts[0]), ("column-gap", parts[-1])]
    if p == "grid-column-gap":
        return [("column-gap", vl)]
    if p in ("padding", "margin"):
        b = _box4(vl)
        return [(p + "-top", b[0]), (p + "-right", b[1]), (p + "-bottom", b[2]), (p + "-left", b[3])]
    if p in ("padding-inline", "margin-inline"):
        parts = split_ws(vl)
        base = p.split("-")[0]
        return [(base + "-left", parts[0]), (base + "-right", parts[-1])]
    if p in ("padding-inline-start", "margin-inline-start"):
        return [(p.split("-")[0] + "-left", vl)]
    if p in ("padding-inline-end", "margin-inline-end"):
        return [(p.split("-")[0] + "-right", vl)]
    if p in ("border", "border-left", "border-right"):
        w, s = _border_parts(vl)
        sides = ["left", "right"] if p == "border" else [p.split("-")[1]]
        out = []
        for side in sides:
            out.append(("border-%s-width" % side, w or "3px"))
            out.append(("border-%s-style" % side, s or "none"))
        if p == "border":
            rest = [t for t in split_ws(vl) if t.lower() not in _BORDER_STYLES and _border_parts(t)[0] is None]
            out.append(("border-color", " ".join(rest) or "currentcolor"))
        return out
    if p == "border-width":
        b = _box4(vl)
        return [("border-left-width", b[3]), ("border-right-width", b[1])]
    if p == "border-style":
        b = _box4(vl)
        return [("border-left-style", b[3]), ("border-right-style", b[1])]
    if p == "border-inline":
        w, s = _border_parts(vl)
        return [("border-left-width", w or "3px"), ("border-right-width", w or "3px"),
                ("border-left-style", s or "none"), ("border-right-style", s or "none")]
    if p == "font":
        parts = split_ws(vl)
        for i, x in enumerate(parts):
            m = re.match(r"^([\d.]+(?:px|rem|em|%|pt)|xx-small|x-small|small|medium|large|x-large|xx-large|smaller|larger)(?:/.*)?$", x.lower())
            if m:
                fam = " ".join(parts[i + 1:])
                return [("font-size", m.group(1)), ("font-family", fam)]
        return []
    if p == "place-items":
        parts = split_ws(vl)
        return [("align-items", parts[0]), ("justify-items", parts[-1])]
    if p == "grid-column":
        a, _, b = vl.partition("/")
        return [("grid-column-start", a.strip()), ("grid-column-end", b.strip() or "auto")]
    if p == "background":
        return [("background", vl), ("background-color", vl)]
    if p == "inline-size":
        return [("width", vl)]
    if p == "min-inline-size":
        return [("min-width", vl)]
    if p == "max-inline-size":
        return [("max-width", vl)]
    return [(p, vl)]


# ---------- calc ----------

_TOK = re.compile(r"\s*(?:(-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)(px|rem|em|%|vw|vh|vmin|vmax|ch|ex|pt|svw|lvw|dvw|cqw|cqi)?|([a-z-]+\()|([()+\-*/,])|([a-z-]+))", re.I)


def _calc(t, basis, em, rem, vw, vh):
    toks = []
    pos = 0
    while pos < len(t):
        m = _TOK.match(t, pos)
        if not m or m.end() == pos:
            if t[pos:].strip() == "":
                break
            raise ValueError(t)
        pos = m.end()
        if m.group(1) is not None:
            n = float(m.group(1))
            u = (m.group(2) or "").lower()
            if u == "":
                toks.append(("num", n))
            elif u == "px":
                toks.append(("len", n))
            elif u == "rem":
                toks.append(("len", n * rem))
            elif u == "em":
                toks.append(("len", n * em))
            elif u in ("ch", "ex"):
                toks.append(("len", n * em * 0.5))
            elif u == "pt":
                toks.append(("len", n * 4 / 3))
            elif u in ("vw", "svw", "lvw", "dvw"):
                toks.append(("len", n * vw / 100))
            elif u == "vh":
                toks.append(("len", n * vh / 100))
            elif u == "vmin":
                toks.append(("len", n * min(vw, vh) / 100))
            elif u == "vmax":
                toks.append(("len", n * max(vw, vh) / 100))
            elif u == "%":
                if basis is None:
                    raise ValueError("% without basis")
                toks.append(("len", n * basis / 100))
            else:
                raise ValueError(u)
        elif m.group(3):
            toks.append(("fn", m.group(3)[:-1].lower()))
        elif m.group(4):
            toks.append(("op", m.group(4)))
        else:
            raise ValueError(m.group(5))
    val, i = _expr(toks, 0)
    if i != len(toks):
        raise ValueError("trailing")
    kind, x = val
    if kind == "num":
        if x == 0:
            return 0.0
        raise ValueError("unitless")
    return x


def _expr(toks, i):
    left, i = _term(toks, i)
    while i < len(toks) and toks[i] == ("op", "+") or i < len(toks) and toks[i] == ("op", "-"):
        op = toks[i][1]
        right, i = _term(toks, i + 1)
        left = (left[0] if left[0] == "len" else right[0], left[1] + right[1] if op == "+" else left[1] - right[1])
    return left, i


def _term(toks, i):
    left, i = _factor(toks, i)
    while i < len(toks) and toks[i] in (("op", "*"), ("op", "/")):
        op = toks[i][1]
        right, i = _factor(toks, i + 1)
        if op == "*":
            left = ("len" if "len" in (left[0], right[0]) else "num", left[1] * right[1])
        else:
            left = (left[0], left[1] / right[1])
    return left, i


def _factor(toks, i):
    if i >= len(toks):
        raise ValueError("eof")
    kind, v = toks[i]
    if kind in ("num", "len"):
        return (kind, v), i + 1
    if (kind, v) == ("op", "("):
        val, i = _expr(toks, i + 1)
        if i >= len(toks) or toks[i] != ("op", ")"):
            raise ValueError(")")
        return val, i + 1
    if (kind, v) == ("op", "-"):
        val, i = _factor(toks, i + 1)
        return (val[0], -val[1]), i
    if kind == "fn":
        args = []
        i += 1
        while True:
            val, i = _expr(toks, i)
            args.append(val)
            if i < len(toks) and toks[i] == ("op", ","):
                i += 1
                continue
            if i < len(toks) and toks[i] == ("op", ")"):
                i += 1
                break
            raise ValueError("args")
        k = "len" if any(a[0] == "len" for a in args) else "num"
        xs = [a[1] for a in args]
        if v == "calc":
            return args[0], i
        if v == "min":
            return (k, min(xs)), i
        if v == "max":
            return (k, max(xs)), i
        if v == "clamp" and len(xs) == 3:
            return (k, max(xs[0], min(xs[1], xs[2]))), i
        raise ValueError(v)
    raise ValueError(str(toks[i]))

# ---------- a width-only layout model over the engine above ----------
# Answers one question per element: at viewport width W, does anything stick out of its box? It sizes block
# containers, flex containers (both directions, wrapping, the full grow/shrink loop with min-width:auto) and grid columns
# (fixed, fr, auto, minmax, fit-content, repeat with a count or auto-fill/auto-fit), and measures text as words of
# monospace 0.6em or proportional 0.55em per character, with the CSS rules for where a long word may break
# (white-space, overflow-wrap, word-break). It does not do heights, floats, absolute positioning, transforms or
# tables; an element using one of those is reported as a problem in its own right ("cannot be checked statically").

INF = float("inf")
BLOCKISH = {"block", "list-item", "flow-root", "flex", "grid", "table", "-webkit-box"}
ATOMIC = {"inline-block", "inline-flex", "inline-grid", "inline-table"}


class Layout:
    def __init__(self, style):
        self.s = style
        self.memo = {}

    # ---- basics ----
    def display(self, n):
        d = (self.s.get(n, "display", "inline") or "inline").lower().split()
        d = [x for x in d if x not in ("flow",)]
        if not d:
            return "inline"
        if d == ["block", "flex"] or d == ["flex", "block"]:
            return "flex"
        if d == ["block", "grid"] or d == ["grid", "block"]:
            return "grid"
        if d == ["inline", "flex"]:
            return "inline-flex"
        if d == ["inline", "grid"]:
            return "inline-grid"
        if d == ["inline", "flow-root"]:
            return "inline-block"
        return d[0]

    def rendered(self, n):
        while n is not None and n.tag != "#document":
            if self.display(n) == "none":
                return False
            n = n.parent
        return True

    def visible(self, n):
        return self.rendered(n) and (self.s.get(n, "visibility", "visible") or "visible").lower() == "visible"

    def kids(self, n):
        out = []
        for c in n.children:
            if isinstance(c, str):
                out.append(c)
            elif self.display(c) == "none":
                continue
            elif self.display(c) == "contents":
                out.extend(self.kids(c))
            else:
                out.append(c)
        return out

    def px(self, n, prop, basis=None, default=0.0):
        v = self.s.get(n, prop)
        if v is None:
            return default
        x = self.s.length(n, v, basis=basis)
        return default if x is None else x

    def side(self, n, basis):
        """(padding+border left+right, margin left+right) in px; auto margins count 0."""
        pad = self.px(n, "padding-left", basis) + self.px(n, "padding-right", basis)
        bor = 0.0
        for sd in ("left", "right"):
            st = (self.s.get(n, "border-%s-style" % sd, "none") or "none").lower()
            if st not in ("none", "hidden"):
                bor += self.px(n, "border-%s-width" % sd, None, 3.0)
        mar = 0.0
        for sd in ("left", "right"):
            v = (self.s.get(n, "margin-" + sd, "0") or "0").lower()
            if v != "auto":
                x = self.s.length(n, v, basis=basis)
                mar += x or 0.0
        return pad + bor, mar

    def border_box(self, n, v, basis):
        """A width/min-width/max-width value as a border-box px size, None for auto/none/content keywords."""
        if v is None:
            return None
        t = v.strip().lower()
        if t in ("auto", "none", "fit-content", "min-content", "max-content", "stretch", "-webkit-fill-available"):
            return None
        x = self.s.length(n, t, basis=basis)
        if x is None:
            return None
        if (self.s.get(n, "box-sizing", "content-box") or "").lower() != "border-box":
            x += self.side(n, basis)[0]
        return x

    def width_kw(self, n, prop):
        return (self.s.get(n, prop, "auto") or "auto").strip().lower()

    def clamp(self, n, w, basis):
        mx = self.border_box(n, self.s.get(n, "max-width"), basis)
        mn = self.border_box(n, self.s.get(n, "min-width"), basis)
        if mx is not None:
            w = min(w, mx)
        if mn is not None:
            w = max(w, mn)
        return w

    def overflow_clips(self, n):
        return (self.s.get(n, "overflow-x", "visible") or "visible").lower() in ("hidden", "clip", "auto", "scroll")

    def unsupported(self, n):
        pos = (self.s.get(n, "position", "static") or "static").lower()
        if pos in ("absolute", "fixed"):
            return "position:%s" % pos
        if (self.s.get(n, "float", "none") or "none").lower() in ("left", "right", "inline-start", "inline-end"):
            return "float"
        d = self.display(n)
        if d in ("table", "inline-table", "table-row", "table-cell"):
            return "display:" + d
        return None

    # ---- text ----
    def char_w(self, n):
        fam = (self.s.get(n, "font-family", "") or "").lower()
        mono = any(k in fam for k in ("mono", "courier", "menlo", "consolas"))
        return self.s.font_size(n) * (0.6 if mono else 0.55)

    def text_rules(self, n):
        ws = (self.s.get(n, "white-space", "normal") or "normal").lower()
        mode = (self.s.get(n, "text-wrap-mode", "wrap") or "wrap").lower()
        nowrap = ws in ("nowrap", "pre") or ws.startswith("pre ") or "nowrap" in ws.split() or mode == "nowrap"
        ow = (self.s.get(n, "overflow-wrap", "normal") or "normal").lower()
        wb = (self.s.get(n, "word-break", "normal") or "normal").lower()
        min_break = (not nowrap) and (ow == "anywhere" or wb in ("break-all", "break-word"))
        layout_break = (not nowrap) and (ow in ("anywhere", "break-word") or wb in ("break-all", "break-word"))
        return nowrap, min_break, layout_break

    def text_units(self, text, owner):
        """[(min_unit_px, label)] and max-content px for a text run styled by owner."""
        t = re.sub(r"\s+", " ", text).strip()
        if not t:
            return [], 0.0
        cw = self.char_w(owner)
        nowrap, min_break, _ = self.text_rules(owner)
        if nowrap:
            units = [(len(t) * cw, t)]
        elif min_break:
            units = [(cw, t[:1])]
        else:
            words = []
            for w in t.split(" "):
                words += [x for x in re.split(r"(?<=-)", w) if x]
            units = [(len(w) * cw, w) for w in words]
        return units, len(t) * cw

    # ---- intrinsic sizes (border-box, without margins) ----
    def intrinsic(self, n):
        key = id(n)
        if key in self.memo:
            return self.memo[key]
        self.memo[key] = (0.0, 0.0)  # cycle guard
        pb, _ = self.side(n, None)
        contain = (self.s.get(n, "contain", "none") or "none").lower().split()
        ctype = (self.s.get(n, "container-type", "normal") or "normal").lower()
        if {"size", "inline-size", "strict"} & set(contain) or ctype in ("inline-size", "size"):
            res = (self.clamp(n, pb, None), self.clamp(n, pb, None))   # size containment: contents do not count
            self.memo[key] = res
            return res
        w = self.border_box(n, self.s.get(n, "width"), None)
        if w is not None:
            res = (self.clamp(n, w, None), self.clamp(n, w, None))
            self.memo[key] = res
            return res
        d = self.display(n)
        if d in ("flex", "inline-flex"):
            items = [c for c in self.kids(n) if not isinstance(c, str) or c.strip()]
            items = [c for c in items if not isinstance(c, str)]
            gap = self.gap(n, None)
            contrib = [self.contribution(c) for c in items]
            direction = (self.s.get(n, "flex-direction", "row") or "row").lower()
            wrap = (self.s.get(n, "flex-wrap", "nowrap") or "nowrap").lower() != "nowrap"
            if direction.startswith("column"):
                mc = max([c[0] for c in contrib] or [0])
                mx = max([c[1] for c in contrib] or [0])
            else:
                g = gap * max(0, len(items) - 1)
                mc = (max([c[0] for c in contrib] or [0]) if wrap else sum(c[0] for c in contrib) + g)
                mx = sum(c[1] for c in contrib) + g
        elif d in ("grid", "inline-grid"):
            items = [c for c in self.kids(n) if not isinstance(c, str)]
            tracks = self.grid_tracks(n, None, len(items))
            cols = len(tracks)
            gap = self.gap(n, None)
            mc_cols = [0.0] * cols
            mx_cols = [0.0] * cols
            for i, c in enumerate(items):
                k = i % cols
                cmin, cmax = self.contribution(c)
                mn_f = tracks[k][0]
                if mn_f == "auto":  # an auto minimum takes the item's minimum contribution (honours min-width/overflow)
                    cmin = self.auto_min(c, None) + self.side(c, None)[1]
                mc_cols[k] = max(mc_cols[k], cmin)
                mx_cols[k] = max(mx_cols[k], cmax)
            mc = mx = gap * max(0, cols - 1)
            for k, (mn_f, mx_f) in enumerate(tracks):
                fixed = self._fixed(n, mn_f, None)
                fixed_max = self._fixed(n, mx_f, None)
                lo = fixed if fixed is not None else (0.0 if mn_f in ("0",) else mc_cols[k])
                hi = fixed_max if fixed_max is not None else mx_cols[k]
                mc += lo
                mx += max(lo, hi)
        else:
            mc = mx = 0.0
            line_max = 0.0
            for c in self.kids(n):
                if isinstance(c, str):
                    units, m = self.text_units(c, n)
                    mc = max([mc] + [u[0] for u in units])
                    line_max += m
                    continue
                cd = self.display(c)
                if cd in BLOCKISH:
                    a, b = self.contribution(c)
                    mc, mx = max(mc, a), max(mx, b)
                    mx = max(mx, line_max)
                    line_max = 0.0
                elif cd in ATOMIC or c.tag in ("button", "img", "input", "select", "textarea"):
                    a, b = self.contribution(c)
                    mc = max(mc, a)
                    line_max += b
                else:  # inline: its text joins this line
                    a, b = self.inline_intrinsic(c)
                    mc = max(mc, a)
                    line_max += b
            mx = max(mx, line_max)
        res = (self.clamp(n, mc + pb, None), self.clamp(n, max(mc, mx) + pb, None))
        self.memo[key] = res
        return res

    def inline_intrinsic(self, n):
        mc = mx = 0.0
        for c in self.kids(n):
            if isinstance(c, str):
                units, m = self.text_units(c, n)
                mc = max([mc] + [u[0] for u in units])
                mx += m
            else:
                if self.display(c) in BLOCKISH or self.display(c) in ATOMIC:
                    a, b = self.contribution(c)
                else:
                    a, b = self.inline_intrinsic(c)
                mc, mx = max(mc, a), mx + b
        return mc, mx

    def contribution(self, n):
        """Min- and max-content contributions (outer, with margins). min-width:0 never lowers them."""
        mc, mx = self.intrinsic(n)
        _, mar = self.side(n, None)
        return mc + mar, mx + mar

    def gap(self, n, basis):
        v = (self.s.get(n, "column-gap", "normal") or "normal").lower()
        if v == "normal":
            return 0.0
        return self.s.length(n, v, basis=basis) or 0.0

    # ---- automatic minimum of a flex/grid item ----
    def auto_min(self, n, basis):
        mn = self.s.get(n, "min-width", "auto")
        if (mn or "auto").strip().lower() != "auto":
            return self.border_box(n, mn, basis) or 0.0
        if self.overflow_clips(n):
            return 0.0
        mc, _ = self.intrinsic(n)
        mx = self.border_box(n, self.s.get(n, "max-width"), basis)
        if mx is not None:
            mc = min(mc, mx)
        spec = self.border_box(n, self.s.get(n, "width"), basis)
        if spec is not None:
            mc = min(mc, spec)
        return mc

    # ---- flex ----
    def flex_layout(self, n, cw):
        """[(item, border-box width)] and the total outer width the items need on their widest line."""
        items = [c for c in self.kids(n) if not isinstance(c, str)]
        direction = (self.s.get(n, "flex-direction", "row") or "row").lower()
        gap = self.gap(n, cw)
        if direction.startswith("column"):
            out = []
            need = 0.0
            for c in items:
                _, mar = self.side(c, cw)
                align = (self.s.get(c, "align-self", "auto") or "auto").lower()
                if align == "auto":
                    align = (self.s.get(n, "align-items", "normal") or "normal").lower()
                spec = self.border_box(c, self.s.get(c, "width"), cw)
                if spec is not None:
                    w = self.clamp(c, spec, cw)
                elif align in ("normal", "stretch"):
                    w = self.clamp(c, max(0.0, cw - mar), cw)
                else:
                    mc, mx = self.intrinsic(c)
                    w = self.clamp(c, min(mx, max(mc, cw - mar)), cw)
                out.append((c, w))
                need = max(need, w + mar)
            self.last_placements = [(c, i, 0, w) for i, (c, w) in enumerate(out)]
            self.last_flex_lines = len(out)
            return out, need
        data = []
        for c in items:
            _, mar = self.side(c, cw)
            grow = _num(self.s.get(c, "flex-grow", "0"), 0.0)
            shrink = _num(self.s.get(c, "flex-shrink", "1"), 1.0)
            basis_v = (self.s.get(c, "flex-basis", "auto") or "auto").strip().lower()
            base = None
            if basis_v not in ("auto", "content"):
                base = self.border_box(c, basis_v, cw)
            if base is None and basis_v == "auto":
                base = self.border_box(c, self.s.get(c, "width"), cw)
            if base is None:
                base = self.intrinsic(c)[1]
            mn = self.auto_min(c, cw)
            mxw = self.border_box(c, self.s.get(c, "max-width"), cw)
            mxw = INF if mxw is None else mxw
            hyp = max(mn, min(base, mxw))
            data.append({"n": c, "mar": mar, "grow": grow, "shrink": shrink, "base": base, "min": mn, "max": mxw, "hyp": hyp})
        wrap = (self.s.get(n, "flex-wrap", "nowrap") or "nowrap").lower() != "nowrap"
        lines = [[]]
        used = 0.0
        for d in data:
            outer = d["hyp"] + d["mar"]
            if wrap and lines[-1] and used + gap + outer > cw + 0.01:
                lines.append([])
                used = 0.0
            used += (gap if lines[-1] else 0.0) + outer
            lines[-1].append(d)
        out, need = [], 0.0
        self.last_placements = []
        for li, line in enumerate(lines):
            sizes = _resolve_flex(line, cw - gap * max(0, len(line) - 1))
            self.last_placements += [(d["n"], li, k, sz) for k, (sz, d) in enumerate(zip(sizes, line))]
            total = sum(sz + d["mar"] for sz, d in zip(sizes, line)) + gap * max(0, len(line) - 1)
            need = max(need, total)
            out += [(d["n"], sz) for sz, d in zip(sizes, line)]
        self.last_flex_lines = len([x for x in lines if x])
        return out, need

    # ---- grid ----
    def _fixed(self, n, f, basis):
        if f is None:
            return None
        if re.match(r"^[\d.]+fr$", f) or f in ("auto", "min-content", "max-content") or f.startswith("fit-content"):
            return None
        return self.s.length(n, f, basis=basis)

    def grid_tracks(self, n, cw, n_items):
        """[(min_fn, max_fn)] column tracks; repeat(auto-fill/auto-fit) resolved against cw."""
        tpl = (self.s.get(n, "grid-template-columns", "none") or "none").strip()
        auto = (self.s.get(n, "grid-auto-columns", "auto") or "auto").strip()
        if tpl.lower() in ("none", "subgrid", "masonry"):
            return [_track(auto)]
        toks = [t for t in split_tracks(tpl) if not t.startswith("[")]
        tracks = []
        for t in toks:
            m = re.match(r"^repeat\(\s*([^,]+?)\s*,\s*(.*)\)$", t, re.S)
            if m:
                inner = [_track(x) for x in split_tracks(m.group(2)) if not x.startswith("[")]
                cnt = m.group(1).strip().lower()
                if cnt in ("auto-fill", "auto-fit"):
                    tracks.append(("AUTO", inner, cnt))
                else:
                    tracks += inner * int(float(cnt))
            else:
                tracks.append(_track(t))
        if any(isinstance(t[0], str) and t[0] == "AUTO" for t in tracks):
            fixed_sum = 0.0
            ntr = 0
            for t in tracks:
                if t[0] != "AUTO":
                    fixed_sum += self._fixed(n, t[1], cw) or self._fixed(n, t[0], cw) or 0.0
                    ntr += 1
            gap = self.gap(n, cw)
            out = []
            for t in tracks:
                if t[0] != "AUTO":
                    out.append(t)
                    continue
                inner = t[1]
                per = 0.0
                for mn, mxf in inner:
                    v = self._fixed(n, mxf, cw)
                    if v is None:
                        v = self._fixed(n, mn, cw)
                    if v is None:
                        raise ValueError("auto-fill repeat with no definite size")
                    per += v
                per_gap = gap * len(inner)
                if cw is None:
                    count = 1
                else:
                    avail = cw - fixed_sum - gap * ntr
                    count = max(1, int(math.floor((avail + gap) / (per + per_gap) + 1e-9)))
                if t[2] == "auto-fit":
                    count = max(1, min(count, max(1, n_items - ntr)))
                out += inner * count
            tracks = out
        return tracks

    def grid_layout(self, n, cw):
        items = [c for c in self.kids(n) if not isinstance(c, str)]
        tracks = self.grid_tracks(n, cw, len(items))
        cols = len(tracks)
        gap = self.gap(n, cw)
        place = []  # (item, start, span)
        rows_of = []
        col = 0
        row = 0
        for c in items:
            gs = (self.s.get(c, "grid-column-start", "auto") or "auto").strip().lower()
            ge = (self.s.get(c, "grid-column-end", "auto") or "auto").strip().lower()
            span = 1
            m = re.match(r"^span\s+(\d+)$", gs) or re.match(r"^span\s+(\d+)$", ge)
            if m:
                span = int(m.group(1))
            if gs == "1" and ge == "-1":
                span, col = cols, 0
            span = min(span, cols)
            if col + span > cols:
                col = 0
                row += 1
            place.append((c, col, span))
            rows_of.append(row)
            col += span
            if col >= cols:
                col = 0
                row += 1
        base, limit, flex = [], [], []
        for k, (mn_f, mx_f) in enumerate(tracks):
            singles = [c for c, s0, sp in place if sp == 1 and s0 == k]
            fx = self._fixed(n, mn_f, cw)
            if fx is not None:
                b = fx
            elif mn_f == "max-content":
                b = max([self.contribution(c)[1] for c in singles] or [0.0])
            elif mn_f == "min-content":
                b = max([self.contribution(c)[0] for c in singles] or [0.0])
            else:  # auto: the items' automatic minimum
                b = max([self.auto_min(c, cw) + self.side(c, cw)[1] for c in singles] or [0.0])
            fr = re.match(r"^([\d.]+)fr$", mx_f or "")
            if fr:
                flex.append(float(fr.group(1)))
                lim = INF
            else:
                flex.append(0.0)
                fxm = self._fixed(n, mx_f, cw)
                if fxm is not None:
                    lim = fxm
                elif mx_f == "min-content":
                    lim = max([self.contribution(c)[0] for c in singles] or [0.0])
                elif (mx_f or "").startswith("fit-content"):
                    arg = self.s.length(n, mx_f[len("fit-content("):-1], basis=cw) or 0.0
                    lim = min(max([self.contribution(c)[1] for c in singles] or [0.0]), max(b, arg))
                else:
                    lim = max([self.contribution(c)[1] for c in singles] or [0.0])
            base.append(b)
            limit.append(max(b, lim))
        free = cw - sum(base) - gap * max(0, cols - 1)
        sizes = list(base)
        if free > 0:
            grow_idx = [k for k in range(cols) if flex[k] == 0 and limit[k] > sizes[k]]
            while free > 1e-6 and grow_idx:
                share = free / len(grow_idx)
                nxt = []
                for k in grow_idx:
                    add = min(share, limit[k] - sizes[k])
                    sizes[k] += add
                    free -= add
                    if limit[k] - sizes[k] > 1e-6:
                        nxt.append(k)
                if len(nxt) == len(grow_idx) and all(limit[k] == INF for k in nxt):
                    break
                grow_idx = nxt
            if any(flex):
                fl = [k for k in range(cols) if flex[k] > 0]
                left = cw - gap * max(0, cols - 1) - sum(sizes[k] for k in range(cols) if flex[k] == 0)
                while True:
                    tot = sum(flex[k] for k in fl)
                    unit = left / tot if tot else 0
                    small = [k for k in fl if flex[k] * unit < base[k]]
                    if not small:
                        break
                    for k in small:
                        sizes[k] = base[k]
                        left -= base[k]
                    fl = [k for k in fl if k not in small]
                for k in fl:
                    sizes[k] = flex[k] * unit
            elif free > 1e-6:
                autos = [k for k in range(cols) if tracks[k][1] == "auto"]
                for k in autos:
                    sizes[k] += free / len(autos)
        need = sum(sizes) + gap * max(0, cols - 1)
        out = []
        self.last_placements = []
        for (c, s0, sp), r in zip(place, rows_of):
            area = sum(sizes[s0:s0 + sp]) + gap * (sp - 1)
            _, mar = self.side(c, cw)
            spec = self.border_box(c, self.s.get(c, "width"), area)
            just = (self.s.get(c, "justify-self", "auto") or "auto").lower()
            if just == "auto":
                just = (self.s.get(n, "justify-items", "legacy") or "legacy").lower()
            if spec is not None:
                w = self.clamp(c, spec, area)
            elif just in ("normal", "stretch", "legacy", "auto"):
                w = self.clamp(c, max(0.0, area - mar), area)
            else:
                mc, mx = self.intrinsic(c)
                w = self.clamp(c, min(mx, max(mc, area - mar)), area)
            out.append((c, w, area))
            self.last_placements.append((c, r, s0, w))
        self.last_grid = {"cols": cols, "sizes": sizes, "rows": rows_of[-1] + 1 if place else 0}
        return out, need

    # ---- used widths and overflow ----
    def block_width(self, n, avail):
        _, mar = self.side(n, avail)
        spec = self.border_box(n, self.s.get(n, "width"), avail)
        w = spec if spec is not None else max(0.0, avail - mar)
        return self.clamp(n, w, avail)

    def problems(self, n, w, depth=0):
        """What sticks out of n's box when n is w px wide (border-box)."""
        out = []
        bad = self.unsupported(n)
        if bad:
            return ["%r uses %s, which cannot be checked statically" % (n, bad)]
        pb, _ = self.side(n, w)
        cw = w - pb
        if self.overflow_clips(n):
            return []
        d = self.display(n)
        if d in ("flex", "inline-flex"):
            items, need = self.flex_layout(n, cw)
            if need > cw + 0.5:
                out.append("%r: its flex items need %.0fpx but it has %.0fpx" % (n, need, cw))
            for c, wc in items:
                out += self.problems(c, wc, depth + 1)
            return out
        if d in ("grid", "inline-grid"):
            items, need = self.grid_layout(n, cw)
            if need > cw + 0.5:
                out.append("%r: its grid columns need %.0fpx but it has %.0fpx" % (n, need, cw))
            for c, wc, area in items:
                _, mar = self.side(c, area)
                if wc + mar > area + 0.5:
                    out.append("%r is %.0fpx wide in a %.0fpx grid area" % (c, wc + mar, area))
                # content may spill out of a narrower item into the empty rest of its own grid area
                out += self.problems(c, max(wc, area - mar), depth + 1)
            return out
        out += self.inline_problems(n, n, cw)
        return out

    def inline_problems(self, ctx_el, n, cw):
        out = []
        for c in self.kids(n):
            if isinstance(c, str):
                units, _ = self.text_units(c, n)
                _, _, layout_break = self.text_rules(n)
                for u, label in units:
                    if u > cw + 0.5 and not layout_break:
                        out.append("text %r (%.0fpx) is wider than its %.0fpx box in %r" % (label[:40], u, cw, ctx_el))
                continue
            cd = self.display(c)
            if cd in BLOCKISH:
                wc = self.block_width(c, cw)
                _, mar = self.side(c, cw)
                if wc + mar > cw + 0.5:
                    out.append("%r is %.0fpx wide in a %.0fpx box" % (c, wc + mar, cw))
                out += self.problems(c, wc)
            elif cd in ATOMIC or c.tag in ("button", "img", "input", "select", "textarea"):
                mc, mx = self.intrinsic(c)
                _, mar = self.side(c, cw)
                spec = self.border_box(c, self.s.get(c, "width"), cw)
                wc = spec if spec is not None else min(mx, max(mc, cw - mar))
                if wc + mar > cw + 0.5:
                    out.append("%r is %.0fpx wide in a %.0fpx box" % (c, wc + mar, cw))
                out += self.problems(c, wc)
            else:
                out += self.inline_problems(ctx_el, c, cw)
        return out

    def width_of(self, n, viewport):
        """Border-box width of n, laying out each ancestor (block, flex or grid) from the viewport down.
        (None, reason) when an ancestor uses something the model does not do."""
        chain = []
        p = n
        while p is not None and p.tag != "#document":
            chain.append(p)
            p = p.parent
        chain.reverse()
        avail = float(viewport)
        w = avail
        self.ancestor_problems = []
        for i, el in enumerate(chain):
            if i > 0:
                parent = chain[i - 1]
                bad = self.unsupported(parent)
                if bad:
                    return None, "%r uses %s" % (parent, bad)
                pd = self.display(parent)
                if pd in ("flex", "inline-flex"):
                    items, need = self.flex_layout(parent, avail)
                    w = dict((id(c), wc) for c, wc in items).get(id(el))
                    if need > avail + 0.5:
                        self.ancestor_problems.append("%r: its flex items need %.0fpx but it has %.0fpx" % (parent, need, avail))
                elif pd in ("grid", "inline-grid"):
                    items, need = self.grid_layout(parent, avail)
                    w = dict((id(c), wc) for c, wc, area in items).get(id(el))
                    if need > avail + 0.5:
                        self.ancestor_problems.append("%r: its grid columns need %.0fpx but it has %.0fpx" % (parent, need, avail))
                elif pd in ("block", "list-item", "flow-root"):
                    w = self.block_width(el, avail)
                    _, mar = self.side(el, avail)
                    if w is not None and w + mar > avail + 0.5:
                        self.ancestor_problems.append("%r is %.0fpx wide in a %.0fpx box" % (el, w + mar, avail))
                else:
                    return None, "%r is laid out by its %s parent %r" % (el, pd, parent)
                if w is None:
                    return None, "%r is not laid out by its parent" % el
            else:
                w = self.block_width(el, avail)
            pb, _ = self.side(el, avail)
            avail = w - pb
        return w, None


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _track(t):
    t = t.strip()
    m = re.match(r"^minmax\((.*)\)$", t, re.S)
    if m:
        args = split_top(m.group(1), ",")
        if len(args) == 2:
            return (args[0].strip().lower(), args[1].strip().lower())
    tl = t.lower()
    if re.match(r"^[\d.]+fr$", tl):
        return ("auto", tl)
    if tl.startswith("fit-content("):
        return ("auto", tl)
    return (tl, tl)


def split_tracks(s):
    out, cur, depth = [], "", 0
    for ch in s.strip():
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "[" and depth == 0:
            depth += 100
        if ch == "]" and depth >= 100:
            depth -= 100
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _resolve_flex(line, avail):
    """CSS Flexbox 9.7 resolving flexible lengths for one line: border-box sizes."""
    if not line:
        return []
    outer_hyp = sum(d["hyp"] + d["mar"] for d in line)
    growing = outer_hyp < avail
    target = [d["hyp"] for d in line]
    frozen = [False] * len(line)
    for i, d in enumerate(line):
        if (growing and (d["grow"] == 0 or d["base"] > d["hyp"])) or (not growing and (d["shrink"] == 0 or d["base"] < d["hyp"])):
            frozen[i] = True
    for _ in range(len(line) + 2):
        if all(frozen):
            break
        free = avail - sum((target[i] if frozen[i] else line[i]["base"]) + line[i]["mar"] for i in range(len(line)))
        unf = [i for i in range(len(line)) if not frozen[i]]
        if growing:
            tot = sum(line[i]["grow"] for i in unf)
            if tot < 1:
                free = free * tot if tot else 0.0
            for i in unf:
                target[i] = line[i]["base"] + (free * line[i]["grow"] / tot if tot else 0.0)
        else:
            tot = sum(line[i]["shrink"] for i in unf)
            if tot < 1:
                free = free * tot
            scaled = sum(line[i]["shrink"] * line[i]["base"] for i in unf)
            for i in unf:
                target[i] = line[i]["base"] + (free * line[i]["shrink"] * line[i]["base"] / scaled if scaled else 0.0)
        viol = 0.0
        kind = {}
        for i in unf:
            clamped = max(line[i]["min"], min(target[i], line[i]["max"]))
            if clamped > target[i]:
                kind[i] = "min"
            elif clamped < target[i]:
                kind[i] = "max"
            viol += clamped - target[i]
            target[i] = clamped
        if abs(viol) < 1e-9:
            break
        for i in unf:
            if (viol > 0 and kind.get(i) == "min") or (viol < 0 and kind.get(i) == "max"):
                frozen[i] = True
    return target


# The page as shipped, laid out by the same model for the unchanged-widths comparison.
ORIGINAL = {
 "index.html": "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>Pricing \u00b7 Acme Notes</title>\n<link rel=\"stylesheet\" href=\"css/styles.css\">\n</head>\n<body>\n<main class=\"page\">\n  <header class=\"intro\">\n    <h1>Pick a plan</h1>\n    <p>Every plan includes unlimited notes and a 30-day free trial.</p>\n  </header>\n  <ul class=\"plans\">\n    <li class=\"plan\">\n      <h2 class=\"plan__name\">Starter</h2>\n      <p class=\"plan__price\">\u20ac0 <span>per month</span></p>\n      <ul class=\"plan__features\">\n        <li>3 shared notebooks</li>\n        <li>Search across all notes</li>\n        <li>Email support</li>\n      </ul>\n      <a class=\"button\" href=\"/signup?plan=starter\">Choose Starter</a>\n    </li>\n    <li class=\"plan plan--featured\">\n      <h2 class=\"plan__name\">Team</h2>\n      <p class=\"plan__price\">\u20ac8 <span>per user per month</span></p>\n      <ul class=\"plan__features\">\n        <li>Unlimited shared notebooks</li>\n        <li>Version history for 90 days</li>\n        <li>Priority support</li>\n      </ul>\n      <a class=\"button button--primary\" href=\"/signup?plan=team\">Choose Team</a>\n    </li>\n    <li class=\"plan\">\n      <h2 class=\"plan__name\">Business</h2>\n      <p class=\"plan__price\">\u20ac15 <span>per user per month</span></p>\n      <ul class=\"plan__features\">\n        <li>Single sign-on</li>\n        <li>Unlimited version history</li>\n        <li>Audit log export</li>\n      </ul>\n      <a class=\"button\" href=\"/signup?plan=business\">Choose Business</a>\n    </li>\n  </ul>\n  <p class=\"fineprint\">Prices exclude VAT. Cancel any time from the billing page.</p>\n</main>\n</body>\n</html>\n",
 "css/styles.css": "*,\n*::before,\n*::after {\n  box-sizing: border-box;\n}\n\nbody {\n  margin: 0;\n  font: 16px/1.5 system-ui, sans-serif;\n  color: #1f2933;\n  background: #f5f7fa;\n}\n\n.page {\n  max-width: 75rem;\n  margin: 0 auto;\n  padding: 1.5rem;\n}\n\n.intro {\n  margin-bottom: 2rem;\n  text-align: center;\n}\n\n.intro h1 {\n  margin: 0 0 0.5rem;\n  font-size: 2rem;\n}\n\n/* Cards are never narrower than 20rem; the grid adds a column whenever another one fits. */\n.plans {\n  display: grid;\n  grid-template-columns: repeat(auto-fill, minmax(20rem, 1fr));\n  gap: 1.5rem;\n  margin: 0;\n  padding: 0;\n  list-style: none;\n}\n\n.plan {\n  display: flex;\n  flex-direction: column;\n  gap: 1rem;\n  padding: 1.5rem;\n  background: #ffffff;\n  border: 1px solid #e4e7eb;\n  border-radius: 0.75rem;\n}\n\n.plan--featured {\n  border-color: #3e4c9e;\n  box-shadow: 0 0 0 2px #3e4c9e;\n}\n\n.plan__name {\n  margin: 0;\n  font-size: 1.25rem;\n}\n\n.plan__price {\n  margin: 0;\n  font-size: 2rem;\n  font-weight: 700;\n}\n\n.plan__price span {\n  font-size: 0.875rem;\n  font-weight: 400;\n  color: #616e7c;\n}\n\n.plan__features {\n  margin: 0;\n  padding-left: 1.25rem;\n  flex: 1;\n}\n\n.button {\n  display: block;\n  padding: 0.75rem 1rem;\n  border: 1px solid #3e4c9e;\n  border-radius: 0.5rem;\n  color: #3e4c9e;\n  text-align: center;\n  text-decoration: none;\n  font-weight: 600;\n}\n\n.button--primary {\n  background: #3e4c9e;\n  color: #ffffff;\n}\n\n.fineprint {\n  margin-top: 2rem;\n  color: #616e7c;\n  font-size: 0.875rem;\n  text-align: center;\n}\n\n@media (min-width: 64rem) {\n  .page {\n    padding: 3rem;\n  }\n}\n"
}


# ---------- task oracle: ui-layout-bug-02 ----------

import shutil  # noqa: E402
import tempfile  # noqa: E402

PLAN_NAMES = ["Starter", "Team", "Business"]
WIDTHS = sorted(set(list(range(320, 481)) + list(range(488, 1601, 8)) +
                    [711, 712, 1023, 1024, 1111, 1112, 1199, 1200, 1247, 1248, 1296]))
BROKEN = range(320, 368)


def _cards(repo_dir):
    dom, sheet = load_page(repo_dir)
    return dom, sheet


def _layout_at(dom, sheet, width):
    """(placements [(row, col, width)], problems, shown) for the plan cards at one viewport width."""
    st = Style(sheet, width)
    lay = Layout(st)
    plans = (by_class(dom, "plans") or [None])[0]
    if plans is None:
        return None, ["no .plans list"], False
    cards = [c for c in by_class(plans, "plan")]
    shown = len(cards) == 3 and all(lay.visible(c) for c in cards)
    w, why = lay.width_of(plans, width)
    if w is None:
        return None, [why], shown
    probs = lay.ancestor_problems + lay.problems(plans, w)
    pb, _ = lay.side(plans, w)
    d = lay.display(plans)
    place = {}
    if d in ("grid", "inline-grid"):
        lay.grid_layout(plans, w - pb)
        place = {id(c): (r, k, round(x, 1)) for c, r, k, x in lay.last_placements}
    elif d in ("flex", "inline-flex"):
        lay.flex_layout(plans, w - pb)
        place = {id(c): (r, k, round(x, 1)) for c, r, k, x in lay.last_placements}
    else:
        place = {id(c): (i, 0, round(lay.block_width(c, w - pb), 1)) for i, c in enumerate(cards)}
    return [place.get(id(c)) for c in cards], probs, shown


def check(repo, message):
    try:
        dom, sheet = load_page(repo)
    except (OSError, ValueError) as e:
        return [{"id": "page-loads", "passed": False, "evidence": "index.html could not be read: %s" % e}]
    with tempfile.TemporaryDirectory() as t:
        for rel, text in ORIGINAL.items():
            p = os.path.join(t, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text)
        odom, osheet = load_page(t)
    names = [(by_class(c, "plan__name") or [None])[0] for c in by_class(dom, "plan")]
    names = [n.text().strip() if n is not None else None for n in names]
    out = [{"id": "plans-intact", "passed": names == PLAN_NAMES, "evidence": "plan cards on the page: %r" % names}]
    small, anywhere, changed, hidden = [], [], [], []
    for w in WIDTHS:
        try:
            place, probs, shown = _layout_at(dom, sheet, w)
        except (ValueError, RecursionError, ZeroDivisionError) as e:
            place, probs, shown = None, ["could not evaluate: %s" % e], True
        if not shown:
            hidden.append(w)
        if probs:
            (small if w in BROKEN else anywhere).append("%dpx: %s" % (w, probs[0]))
        if w not in BROKEN:
            oplace, oprobs, _ = _layout_at(odom, osheet, w)
            if not oprobs and place is not None and oplace is not None:
                diff = [(i, a, b) for i, (a, b) in enumerate(zip(oplace, place))
                        if a is None or b is None or a[:2] != b[:2] or abs(a[2] - b[2]) > 1]
                if diff:
                    i, a, b = diff[0]
                    changed.append("%dpx: %s card was row %s col %s %spx wide, now %s" % (
                        w, PLAN_NAMES[i], a[0], a[1], round(a[2]), "row %s col %s %spx wide" % (b[0], b[1], round(b[2])) if b else "not placed"))
            elif place is None:
                changed.append("%dpx: cards could not be placed" % w)
    unsup = sorted(set(sheet.unsupported))
    out.append({"id": "cards-fit-small-phones", "passed": not small and not unsup,
                "evidence": "; ".join((unsup + small)[:4]) or "no card sticks out at any width from 320 to 367px"})
    out.append({"id": "cards-fit-all-widths", "passed": not anywhere,
                "evidence": "; ".join(anywhere[:4]) or "no card sticks out at %d widths from 368 to 1600px" % len([w for w in WIDTHS if w not in BROKEN])})
    out.append({"id": "layout-unchanged-where-it-worked", "passed": not changed,
                "evidence": "%d widths changed, e.g. %s" % (len(changed), "; ".join(changed[:3])) if changed else
                "every width that already fitted keeps each card's row, column and width"})
    out.append({"id": "cards-shown", "passed": not hidden,
                "evidence": "cards hidden at %s" % hidden[:5] if hidden else "all three cards rendered at every width"})
    return out
