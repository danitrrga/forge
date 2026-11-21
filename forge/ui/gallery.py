"""The component gallery of forge/ui: one offline HTML page (no external asset) with the token table and its measured contrast, the
three glyph sets, every component in each of its states and the reference screens in both themes and every glyph set.

  python3 -m forge.ui.gallery --out PAGE.html     write the page
  python3 -m forge.ui.gallery --plain             print every component and screen as plain text blocks (deterministic)
  python3 -m forge.ui.gallery --tokens-css PATH   write the custom properties of both themes
"""
import argparse
import html
import sys

from forge.ui import context, marks, render_ansi, render_html, samples, tokens

PLAIN = context.Context("dark", "unicode", "none", 80)
SETS = tokens.GLYPH_SETS
THEMES = tokens.THEMES
GROUPS = {  # plain block name -> the component names whose cases it holds
    "meter": ("meter",), "group": ("step", "rail_start", "rail_blank", "rail_line", "rail_end", "check_row", "group"),
    "keys": ("keys",), "table": ("table",), "header": ("header",), "band": ("band",), "stack": ("stack",),
    "agent_block": ("agent_block",)}


def _scope(theme):
    return '[data-forge-theme="%s"]' % theme


# ---- plain text ------------------------------------------------------------------------------------------------------------
def _text(lines):
    return render_ansi.to_text(lines, PLAIN)


def _cases(names):
    out = []
    for name, state, lines in samples.component_cases(PLAIN):
        if name in names:
            out.append("-- %s%s\n%s" % (name, ": " + state if state else "", _text(lines)))
    return "\n".join(out)


def plain_blocks():
    """[(NAME, text)]: every component and screen at 80 columns, unicode set, dark, no colour."""
    screens_by = {(s, st): lines for s, st, lines in samples.screen_cases(PLAIN)}
    blocks = []
    glyph_lines = "".join("%-14s %s\n" % (k, v) for k, v in tokens.glyphs("unicode").items() if k.startswith("icon_"))
    for name in ("meter", "icons", "mark", "group", "keys", "table", "header", "band", "stack", "status_line", "agent_block"):
        if name == "icons":
            body = glyph_lines
        elif name == "mark":
            body = "".join("".join(s.text for s in line) + "\n" for line in marks.mark_lines(PLAIN))
        elif name == "status_line":
            body = "\n".join("-- %d columns\n%s" % (w, _text(l)) for w, l in samples.status_line_cases(PLAIN))
        else:
            body = _cases(GROUPS[name])
        blocks.append((name, body))
    blocks.append(("home", _text(screens_by[("home", "full")])))
    blocks.append(("project_list", _text(screens_by[("project_list", "")])))
    blocks.append(("selector", _text(screens_by[("selector", "refused")])))
    blocks.append(("selector_frozen", _text(screens_by[("selector", "frozen")])))
    blocks.append(("selector_stack", _text(screens_by[("selector", "several")])))
    blocks.append(("agent_events", _text(screens_by[("agent_events", "")])))
    return blocks


def plain():
    return "".join("=== %s ===\n%s\n" % (name, body.rstrip("\n") + "\n") for name, body in plain_blocks())


# ---- html ------------------------------------------------------------------------------------------------------------------
CSS = """
:root{--page:@band@;--page-ink:@ink@;--page-mute:@mute@;--page-line:@line@;--font-term:"CaskaydiaCove Nerd Font Mono","CaskaydiaCove Nerd Font","DejaVu Sans Mono",monospace}
*{box-sizing:border-box}body{margin:0;padding:40px clamp(16px,4vw,56px) 80px;background:var(--page);color:var(--page-ink);font:15px/1.5 system-ui,sans-serif}
h1{font-size:26px;margin:0 0 6px}h2{font-size:19px;margin:56px 0 6px;border-top:1px solid var(--page-line);padding-top:20px}h3{font-size:14px;margin:26px 0 8px;color:var(--page-mute);font-weight:600}
p{color:var(--page-mute);max-width:80ch;margin:4px 0 12px}code{font-family:var(--font-term);font-size:13px}
table.t{border-collapse:collapse;font:13px/1.4 var(--font-term)}table.t td,table.t th{padding:5px 14px 5px 0;border-bottom:1px solid var(--page-line);text-align:left;font-weight:400}
table.t th{color:var(--page-mute)}.sw{display:inline-block;width:3.2ch;height:1.3em;vertical-align:middle;border:1px solid var(--page-line)}
.pass{color:@ok@}.fail{color:@error@;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,760px),1fr));gap:18px;align-items:start}
.win{background:var(--forge-ground);border:1px solid var(--forge-line);border-radius:8px;overflow:hidden;color:var(--forge-body)}
.bar{display:flex;justify-content:space-between;gap:16px;padding:7px 12px;border-bottom:1px solid var(--forge-line);font:11px/1 var(--font-term);color:var(--forge-dim)}
.win pre{margin:0;padding:12px 14px 14px;font:13px/1.1 var(--font-term);font-variant-ligatures:none;white-space:pre;overflow-x:auto;scrollbar-color:var(--forge-faint) var(--forge-ground);color:var(--forge-body)}
.glyphs td.g{font:18px var(--font-term)}.states .win{max-width:760px}
"""


def window(title, lines, theme, note=""):
    cols = max([l.width for l in lines] + [0])
    return ('<div class="win"><div class="bar"><span>%s</span><span>%s%d cols</span></div>%s</div>'
            % (html.escape(title), html.escape(note), cols, render_html.to_html(lines, theme)))


def themed(theme, inner):
    return '<div class="theme" data-forge-theme="%s">%s</div>' % (theme, inner)


def token_section():
    out = ["<h2>Tokens and measured contrast</h2><p>Every text role against the ground and the cursor band, the ramp tints against both, and ink, mute and the role's own colour on each coloured band. Minimums come from tokens.json (text %.1f, graphic %.1f).</p>"
           % (tokens.data()["contrast"]["text_min"], tokens.data()["contrast"]["graphic_min"])]
    rules = tokens.data()["contrast"]
    for theme in THEMES:
        table = tokens.theme(theme)
        rows = ["<tr><th>%s</th><th>colour</th><th></th><th>on</th><th>ratio</th><th>min</th><th></th></tr>" % theme]
        for role, surface, ratio, minimum in tokens.contrast_rows(table, rules):
            ok = ratio >= minimum
            colour = tokens.role_color(table, role)
            rows.append('<tr><td>%s</td><td>%s</td><td><span class="sw" style="background:%s"></span></td><td>%s</td><td class="%s">%.2f</td><td>%.1f</td><td class="%s">%s</td></tr>'
                        % (role, colour, colour, surface, "pass" if ok else "fail", ratio, minimum, "pass" if ok else "fail", "pass" if ok else "FAIL"))
        decor = "".join('<tr><td>%s</td><td>%s</td><td><span class="sw" style="background:%s"></span></td><td colspan="4">decoration or surface, not text</td></tr>'
                        % (r, table[r], table[r]) for r in ("faint", "line", "ground", "band", "warn_band", "error_band", "ok_band", "neutral_band"))
        out.append("<h3>%s</h3><table class=\"t\">%s%s</table>" % (theme, "".join(rows), decor))
    return "".join(out)


def glyph_section():
    rows = ["<tr><th>token</th><th>nerd</th><th>unicode</th><th>ascii</th><th>cell</th></tr>"]
    cells = set(tokens.cell_glyphs())
    for name in tokens.glyphs("nerd"):
        rows.append("<tr><td>%s</td>%s<td>%s</td></tr>" % (name, "".join('<td class="g">%s</td>' % html.escape(tokens.glyphs(s)[name]) for s in SETS), "1" if name in cells else "text"))
    return ('<h2>Glyph sets</h2><p>The three sets side by side. Cell glyphs are exactly one terminal cell in every set. The nerd set needs a Nerd Font; the page falls back to a monospace font where it has none.</p>'
            '<table class="t glyphs">%s</table>' % "".join(rows))


def component_section():
    out = ["<h2>Components</h2><p>Each component in each of its states, dark theme, unicode set, 80 columns. The state names are below each title.</p><div class=\"grid states\">"]
    ctx = context.Context("dark", "unicode", "truecolor", 80)
    for name, state, lines in samples.component_cases(ctx):
        out.append(themed("dark", window("%s%s" % (name, ": " + state if state else ""), lines, "dark")))
    out.append("</div><h3>Component states in the other glyph sets and in light</h3><div class=\"grid states\">")
    for theme, gs in (("light", "unicode"), ("dark", "nerd"), ("dark", "ascii")):
        ctx = context.Context(theme, gs, "truecolor", 80)
        for name, state, lines in samples.component_cases(ctx):
            if name in ("band", "group", "check_row", "meter") and state in ("cursor member with an icon", "pending_off", "refused", "broken", "frozen", "stale", "done", "ramp, four of ten", "cursor with an icon"):
                out.append(themed(theme, window("%s: %s" % (name, state), lines, theme, "%s / %s  " % (theme, gs))))
    out.append("</div><h3>The status line at each width</h3><div class=\"grid states\">")
    ctx = context.Context("dark", "unicode", "truecolor", 80)
    for w, lines in samples.status_line_cases(ctx):
        out.append(themed("dark", window("status_line at %d columns" % w, lines, "dark")))
    return "".join(out) + "</div>"


def screen_section():
    out = ["<h2>Screens</h2><p>The four reference screens, each in both themes and in the three glyph sets, at 80 columns.</p>"]
    wanted = (("home", "full"), ("project_list", ""), ("selector", "refused"), ("selector", "frozen"), ("selector", "several"), ("agent_events", ""))
    for screen, state in wanted:
        out.append("<h3>%s%s</h3><div class=\"grid\">" % (screen, ": " + state if state else ""))
        for theme in THEMES:
            for gs in SETS:
                ctx = context.Context(theme, gs, "truecolor", 80)
                lines = next(l for s, st, l in samples.screen_cases(ctx) if (s, st) == (screen, state))
                out.append(themed(theme, window("%s / %s" % (theme, gs), lines, theme)))
        out.append("</div>")
    return "".join(out)


def _chrome(css):
    """The page's own colours (outside the terminal windows) are the dark theme's tokens."""
    dark = tokens.theme("dark")
    for role in ("band", "ink", "mute", "line", "ok", "error"):
        css = css.replace("@%s@" % role, dark[role])
    return css


def page():
    css = "".join(render_html.tokens_css(t, _scope(t)) for t in THEMES)
    body = ("<h1>forge/ui gallery</h1><p>Generated from forge/ui/tokens.json: edit a value there, never in this page.</p>"
            + token_section() + glyph_section() + component_section() + screen_section())
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>forge/ui gallery</title><style>%s%s</style><body>%s</body></html>\n' % (_chrome(CSS), css, body)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="write the gallery page here")
    ap.add_argument("--plain", action="store_true", help="print every component and screen as plain text blocks")
    ap.add_argument("--tokens-css", metavar="PATH", help="write the custom properties of both themes here")
    args = ap.parse_args(argv)
    if not (args.out or args.plain or args.tokens_css):
        ap.error("give --out, --plain or --tokens-css")
    if args.plain:
        sys.stdout.write(plain())
    if args.tokens_css:
        with open(args.tokens_css, "w", encoding="utf-8") as f:
            f.write("\n".join(render_html.tokens_css(t, _scope(t)) for t in THEMES) + "\n")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(page())
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
