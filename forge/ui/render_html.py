"""Lines to HTML, and the token table as CSS custom properties: the shared output for the web, the Orca panel and the verdict
page. Spans name a custom property (`var(--forge-accent)`), never a colour, so one stylesheet themes every block."""
import html

from forge.ui import tokens

PREFIX = "--forge-"


def var(role):
    """`ramp2` is `--forge-ramp-2`, `warn_band` is `--forge-warn-band`."""
    if role.startswith("ramp") and role[4:].isdigit():
        return "%sramp-%s" % (PREFIX, role[4:])
    return PREFIX + role.replace("_", "-")


def tokens_css(theme, selector=":root"):
    """`:root{--forge-ground:...;...}` for one theme: every role, the ramp as --forge-ramp-0..3."""
    table = tokens.theme(theme)
    items = []
    for role, value in table.items():
        if role == "ramp":
            items.extend("%sramp-%d:%s" % (PREFIX, i, c) for i, c in enumerate(value))
        else:
            items.append("%s:%s" % (var(role), value))
    return "%s{%s}" % (selector, ";".join(items))


def _span(span):
    style = "color:var(%s)" % var(span.role)
    if span.bold:
        style += ";font-weight:700"
    return '<span style="%s">%s</span>' % (style, html.escape(span.text))


def to_html(lines, ctx_theme):
    """A <pre> block of the lines; `ctx_theme` (dark|light) is written as data-forge-theme so a page can scope the tokens."""
    rows = []
    for line in lines:
        body = "".join(_span(s) for s in line.spans if s.text)
        if line.bg:
            body = '<span style="background:var(%s)">%s</span>' % (var(line.bg), body)
        rows.append(body)
    return '<pre class="forge-term" data-forge-theme="%s">%s</pre>' % (html.escape(ctx_theme), "\n".join(rows))
