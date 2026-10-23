"""Oracle for ui-design-tokens-02 (authored). Imports the repo's ui.components and wraps each component function
(alert, button, badge, stat, card) so every call is recorded, then imports pages.billing and renders it for an expired
account (plan_expires 3 Oct 2026, today 23 Oct 2026) and an active one. The expired page must show a notice built by
alert() with the warning or danger tone (a hand-copied copy of the alert's markup is not the component), mentioning the
expiry date in any common format (or "20 days ago"), placed before the first card, and the page must link to
ui.routes.RENEW. The active page must be exactly what it was. No style="" or <style> in the output and no new CSS
declaration that hard-codes a colour, spacing/radius/font size or font weight. The repo's tests must pass.

What it cannot see: how the notice looks in a browser, whether the wording is good, and logic for accounts other than
the two it renders (it does not test an account expiring today). It reads the component calls, so a page that inlines
the component's HTML instead of calling it fails even if the markup is identical, by design.
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


# ---------- design-token adherence helpers ----------

NAMED_COLORS = set("""aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown
burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod
darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue
firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew
hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray
lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid
mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen
paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue
saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen
steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen""".split())
COLOR_FN = re.compile(r"\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.I)
SPACING_PROPS = re.compile(r"^(padding|margin|gap|row-gap|column-gap|border(-[a-z]+)*-radius|border-radius|font-size|"
                           r"letter-spacing|inset|top|right|bottom|left|padding-[a-z-]+|margin-[a-z-]+)$")
LENGTH = re.compile(r"(?<![\w-])(-?\d*\.?\d+)(px|rem|em|pt|ch|ex|vh|vw)\b", re.I)


def _strip_vars(value):
    out, i = "", 0
    while True:
        j = value.find("var(", i)
        if j == -1:
            return out + value[i:]
        out += value[i:j] + " "
        k, depth = j + 4, 1
        while k < len(value) and depth:
            depth += {"(": 1, ")": -1}.get(value[k], 0)
            k += 1
        i = k


def literal_problems(prop, value):
    """Why a declaration hard-codes a colour, a spacing/shape/type size or a font weight (empty when it does not)."""
    if prop.startswith("--"):
        return []
    rest = _strip_vars(value)
    out = []
    if re.search(r"#[0-9a-fA-F]{3,8}\b", rest) or COLOR_FN.search(rest):
        out.append("colour literal")
    elif any(w.lower() in NAMED_COLORS for w in re.findall(r"[A-Za-z]+", rest)):
        out.append("named colour")
    if SPACING_PROPS.match(prop) and any(float(m.group(1)) != 0 for m in LENGTH.finditer(rest)):
        out.append("length literal")
    if prop == "font-weight" and re.search(r"\b[1-9]00\b|\bbold(er)?\b", rest):
        out.append("font-weight literal")
    return out


def _norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def author_decls(sheet):
    """{(selector, prop, value)} of every author declaration, normalised."""
    out = set()
    for sel_text, decls, media, order, source in sheet.rules:
        if source == "ua":
            continue
        for sel in split_top(sel_text, ","):
            for p, v, imp in decls:
                out.add((_norm(sel), p if p.startswith("--") else p.lower(), _norm(v), tuple(_norm(m) for m in media)))
    return out


def inline_decls(dom):
    out = []
    for n in dom.iter():
        if n.attrs.get("style"):
            for p, v, imp in parse_declarations(n.attrs["style"]):
                out.append((n, p.lower(), v))
    return out


def tokens_reached(style, node, value, original, depth=0):
    """Names of original tokens that value resolves through (following custom properties as the node sees them)."""
    found = set()
    if value is None or depth > 10:
        return found
    for name in re.findall(r"var\(\s*(--[\w-]+)", value):
        if name in original:
            seen = style.custom(node, name)
            if seen is not None and _norm(seen) == _norm(original[name]):
                found.add(name)
                continue
        found |= tokens_reached(style, node, style.custom(node, name), original, depth + 1)
    return found


def strip_states(sel):
    """The selector without :hover/:focus... so it can be matched against the resting DOM; None if it has no state."""
    if not re.search(r":(hover|focus|focus-visible|focus-within|active)\b", sel):
        return None
    base = re.sub(r":(?:is|where)\((?:\s*:(?:hover|focus|focus-visible|focus-within|active)\s*,?)+\)", "", sel)
    base = re.sub(r":(hover|focus|focus-visible|focus-within|active)\b", "", base)
    return base.strip() or "*"


# The stylesheets as shipped, and the active account's page as the original code renders it.
ORIGINAL_CSS = {
 "ui/components.css": "body {\n  margin: 0;\n  font-family: system-ui, sans-serif;\n  color: var(--color-neutral-900);\n  background-color: var(--color-neutral-50);\n}\n\n.page {\n  max-width: 56rem;\n  margin: 0 auto;\n  padding: var(--space-8) var(--space-4);\n}\n\n.page__title {\n  display: flex;\n  align-items: center;\n  gap: var(--space-3);\n  margin: 0 0 var(--space-6);\n}\n\n.btn {\n  display: inline-block;\n  padding: var(--space-2) var(--space-4);\n  border: 1px solid transparent;\n  border-radius: var(--radius-md);\n  font-weight: var(--font-weight-medium);\n  text-decoration: none;\n}\n\n.btn--primary {\n  background-color: var(--color-brand-600);\n  color: var(--color-neutral-0);\n}\n\n.btn--secondary {\n  background-color: var(--color-neutral-0);\n  border-color: var(--color-neutral-200);\n  color: var(--color-neutral-900);\n}\n\n.alert {\n  margin-bottom: var(--space-6);\n  padding: var(--space-3) var(--space-4);\n  border: 1px solid;\n  border-radius: var(--radius-md);\n}\n\n.alert__title {\n  margin: 0 0 var(--space-1);\n  font-weight: var(--font-weight-bold);\n}\n\n.alert__body {\n  margin: 0;\n}\n\n.alert__action {\n  display: inline-block;\n  margin-top: var(--space-2);\n  color: inherit;\n  font-weight: var(--font-weight-medium);\n}\n\n.alert--info {\n  background-color: var(--color-info-50);\n  border-color: var(--color-info-700);\n  color: var(--color-info-700);\n}\n\n.alert--success {\n  background-color: var(--color-success-50);\n  border-color: var(--color-success-700);\n  color: var(--color-success-700);\n}\n\n.alert--warning {\n  background-color: var(--color-warning-50);\n  border-color: var(--color-warning-300);\n  color: var(--color-warning-700);\n}\n\n.alert--danger {\n  background-color: var(--color-danger-50);\n  border-color: var(--color-danger-300);\n  color: var(--color-danger-700);\n}\n\n.badge {\n  padding: 0 var(--space-2);\n  border-radius: var(--radius-sm);\n  font-size: var(--font-size-sm);\n}\n\n.badge--success {\n  background-color: var(--color-success-50);\n  color: var(--color-success-700);\n}\n\n.badge--danger {\n  background-color: var(--color-danger-50);\n  color: var(--color-danger-700);\n}\n\n.card {\n  margin-bottom: var(--space-6);\n  padding: var(--space-6);\n  background-color: var(--color-neutral-0);\n  border: 1px solid var(--color-neutral-200);\n  border-radius: var(--radius-lg);\n}\n\n.card__title {\n  margin: 0 0 var(--space-4);\n  font-size: var(--font-size-lg);\n}\n\n.card__actions {\n  margin-top: var(--space-4);\n}\n\n.stat {\n  display: flex;\n  justify-content: space-between;\n  padding: var(--space-2) 0;\n}\n\n.stat__label {\n  color: var(--color-neutral-600);\n}\n\n.stat__value {\n  margin: 0;\n  font-weight: var(--font-weight-medium);\n}\n\n.muted {\n  color: var(--color-neutral-600);\n}\n",
 "ui/tokens.css": ":root {\n  --color-neutral-0: #ffffff;\n  --color-neutral-50: #f7f8fa;\n  --color-neutral-200: #dde1e8;\n  --color-neutral-600: #5b6372;\n  --color-neutral-900: #171a21;\n  --color-brand-600: #3b4bd8;\n  --color-brand-700: #2f3cb0;\n  --color-info-50: #eef4ff;\n  --color-info-700: #23479e;\n  --color-success-50: #ecfdf3;\n  --color-success-700: #17633d;\n  --color-warning-50: #fff8e6;\n  --color-warning-300: #f2c261;\n  --color-warning-700: #7a4800;\n  --color-danger-50: #fdeeee;\n  --color-danger-300: #ee9a9a;\n  --color-danger-700: #a12424;\n\n  --space-1: 0.25rem;\n  --space-2: 0.5rem;\n  --space-3: 0.75rem;\n  --space-4: 1rem;\n  --space-6: 1.5rem;\n  --space-8: 2rem;\n\n  --radius-sm: 0.25rem;\n  --radius-md: 0.5rem;\n  --radius-lg: 0.75rem;\n\n  --font-size-sm: 0.875rem;\n  --font-size-lg: 1.25rem;\n  --font-weight-medium: 500;\n  --font-weight-bold: 650;\n}\n"
}
ACTIVE_HTML = '<main class="page"><h1 class="page__title">Billing <span class="badge badge--success">Active</span></h1><section class="card"><h2 class="card__title">Plan</h2><dl><div class="stat"><dt class="stat__label">Plan</dt><dd class="stat__value">Team</dd></div><div class="stat"><dt class="stat__label">Seats</dt><dd class="stat__value">12</dd></div><div class="stat"><dt class="stat__label">Monthly total</dt><dd class="stat__value">€96.00</dd></div><div class="stat"><dt class="stat__label">Renews on</dt><dd class="stat__value">30 Nov 2026</dd></div></dl><div class="card__actions"><a class="btn btn--secondary" href="/billing/plans">Change plan</a></div></section><section class="card"><h2 class="card__title">Invoices</h2><p class="muted">Invoices are emailed to the account owner on the 1st of each month.</p><div class="card__actions"><a class="btn btn--secondary" href="/billing/invoices">View invoices</a></div></section></main>'


# ---------- task oracle: ui-design-tokens-02 ----------

import datetime  # noqa: E402
import functools  # noqa: E402
import importlib  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

EXPIRED = {"name": "Northwind", "plan": "Team", "seats": 12, "plan_expires": datetime.date(2026, 10, 3),
           "monthly_total": "€96.00"}
ACTIVE = {"name": "Northwind", "plan": "Team", "seats": 12, "plan_expires": datetime.date(2026, 11, 30),
          "monthly_total": "€96.00"}
TODAY = datetime.date(2026, 10, 23)
DATE_RX = re.compile(r"\b0?3(st|rd|th)?\s+(oct|october)\.?,?\s+2026|\b(oct|october)\.?\s+0?3(rd)?,?\s+2026|2026[-]10[-]03|"
                     r"\b03/10/2026|\b10/03/2026|\b3/10/2026|\b10/3/2026|\b20\s+days\b|\btwenty\s+days\b", re.I)
COMPONENTS = ("alert", "button", "badge", "stat", "card")


def _ws(s):
    return re.sub(r"\s+", " ", s).strip()


def check(repo, message):
    out = []

    def add(cid, ok, ev):
        out.append({"id": cid, "passed": bool(ok), "evidence": ev})
    sys.path.insert(0, repo)
    calls = []
    try:
        comp = importlib.import_module("ui.components")
        routes = importlib.import_module("ui.routes")
        for name in COMPONENTS:
            fn = getattr(comp, name, None)
            if fn is None:
                continue

            def wrap(f, nm):
                @functools.wraps(f)
                def inner(*a, **k):
                    res = f(*a, **k)
                    calls.append((nm, a, k, res))
                    return res
                return inner
            setattr(comp, name, wrap(fn, name))
        billing = importlib.import_module("pages.billing")
    except Exception as e:  # noqa: BLE001
        return [{"id": "imports", "passed": False, "evidence": "the billing page does not import: %r" % e}]

    try:
        del calls[:]
        page = billing.render(dict(EXPIRED), TODAY)
        exp_calls = list(calls)
    except Exception as e:  # noqa: BLE001
        return [{"id": "renders-expired", "passed": False, "evidence": "render(expired account) raised %r" % e}]
    alerts = [(a, k, res) for nm, a, k, res in exp_calls if nm == "alert" and res in page]
    tones = [(k.get("tone") if "tone" in k else (a[1] if len(a) > 1 else "info")) for a, k, res in alerts]
    warn = [res for (a, k, res), tone in zip(alerts, tones) if tone in ("warning", "danger")]
    add("notice-is-the-alert-component", bool(warn),
        "alert() calls on the page: %s" % (", ".join("tone=%s" % t for t in tones) or "none (the notice is not built with alert())"))
    text = _ws(html.unescape(re.sub(r"<[^>]+>", " ", " ".join(warn))))
    add("notice-says-when-it-expired", bool(DATE_RX.search(text)),
        "notice text: %r" % text[:160] if warn else "no warning/danger alert to read")
    first_card = page.find('class="card"')
    pos = min((page.find(w) for w in warn), default=-1)
    add("notice-above-the-page-content", warn and pos != -1 and (first_card == -1 or pos < first_card),
        "notice at offset %s, first card at %s" % (pos, first_card))
    renew = getattr(routes, "RENEW", "/billing/renew")
    links = re.findall(r"""<a\b[^>]*href\s*=\s*["']([^"']*)["']""", page)
    add("renew-link", renew in [html.unescape(x) for x in links],
        "links on the expired page: %s" % (", ".join(links) or "none"))

    try:
        active = billing.render(dict(ACTIVE), TODAY)
    except Exception as e:  # noqa: BLE001
        active = "render(active account) raised %r" % e
    add("active-account-page-unchanged", _ws(active) == _ws(ACTIVE_HTML),
        "identical to the original page" if _ws(active) == _ws(ACTIVE_HTML) else "differs: %r" % _ws(active)[:200])

    bad = []
    for m in re.finditer(r"""\bstyle\s*=\s*["']([^"']*)["']""", page + active):
        bad.append('style="%s" in the rendered page' % m.group(1))
    cur, orig = Sheet(), Sheet()
    for rel in sorted(set(ORIGINAL_CSS)):
        orig.add(ORIGINAL_CSS[rel], (), rel)
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "site"]
        for f in files:
            if f.endswith(".css"):
                p = os.path.join(root, f)
                cur.add(open(p, encoding="utf-8").read(), (), os.path.relpath(p, repo))
    new = author_decls(cur) - author_decls(orig)
    for sel, p, v, media in sorted(new):
        for why in literal_problems(p, v):
            bad.append("%s { %s: %s } (%s)" % (sel, p, v, why))
    for m in re.finditer(r"""<style[^>]*>([\s\S]*?)</style>""", page):
        bad.append("a <style> block in the rendered page")
    add("no-hand-written-styling", not bad,
        "; ".join(bad[:4]) or "no inline styles and %d new CSS declarations, none hard-coded" % len(new))

    try:
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-t", "."], cwd=repo, capture_output=True,
                           text=True, timeout=40, env={k: v for k, v in os.environ.items() if not k.startswith("PYTHON")})
        tail = (r.stderr.strip().splitlines() or ["no output"])[-1]
        ran = re.search(r"Ran (\d+) test", r.stderr)
        add("repo-tests-pass", r.returncode == 0 and ran and int(ran.group(1)) > 0,
            "python3 -m unittest: %s (%s)" % (tail, ran.group(0) if ran else "no tests ran"))
    except subprocess.TimeoutExpired:
        add("repo-tests-pass", False, "the test run timed out")
    return out
