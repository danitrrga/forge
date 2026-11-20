"""Lines to terminal text. With colour `none` the output is plain text without a single escape byte; otherwise each span is
one SGR sequence closed by a reset. `ink` and `body` are the terminal's own foreground (ink is bold when asked): they take no
colour, so a light or dark terminal theme keeps its own text colour. The exception is a line with a background: there they are
painted with the theme's own ink and body (truecolor and 256), so the text never sits on a band in the terminal's opposite tone.
At 16 colours the cursor band is reverse video, which keeps the pair together."""
from forge.ui import tokens

TERMINAL_OWN = ("ink", "body")
CUBE = (0, 95, 135, 175, 215, 255)


def xterm256(hex_color):
    """The nearest xterm-256 index of "#rrggbb", looking at the colour cube (16-231) and the grey ramp (232-255)."""
    r, g, b = tokens.rgb(hex_color)
    best, best_d = 16, None
    for i in range(16, 256):
        if i < 232:
            n = i - 16
            cr, cg, cb = CUBE[n // 36], CUBE[(n // 6) % 6], CUBE[n % 6]
        else:
            cr = cg = cb = 8 + (i - 232) * 10
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def _codes(span, bg, ctx):
    codes = []
    if span.bold:
        codes.append("1")
    if span.rgb and ctx.color in ("truecolor", "256"):  # the logo's own colour (the nearest entry at 256); 16 colours draw the role
        codes.append("38;2;%d;%d;%d" % tokens.rgb(span.rgb) if ctx.color == "truecolor" else "38;5;%d" % xterm256(span.rgb))
        return codes
    if ctx.color == "16":
        if span.role not in TERMINAL_OWN:
            codes.extend(tokens.ansi16()[span.role])
        if bg == "band":
            codes.append("7")
        return codes
    table = ctx.colors
    if span.role not in TERMINAL_OWN or bg:  # on a painted background the text colour is the theme's, never the terminal's
        c = tokens.role_color(table, span.role)
        codes.append("38;2;%d;%d;%d" % tokens.rgb(c) if ctx.color == "truecolor" else "38;5;%d" % xterm256(c))
    if bg:
        c = table[bg]
        codes.append("48;2;%d;%d;%d" % tokens.rgb(c) if ctx.color == "truecolor" else "48;5;%d" % xterm256(c))
    return codes


def to_text(lines, ctx):
    """The screen as one string, a newline after each line. Plain text drops the trailing spaces that only fill a band."""
    out = []
    for line in lines:
        if ctx.color == "none":
            out.append(line.text.rstrip())
            continue
        parts = []
        for span in line.spans:
            if not span.text:
                continue
            codes = _codes(span, line.bg, ctx)
            parts.append("\033[%sm%s\033[0m" % (";".join(codes), span.text) if codes else span.text)
        out.append("".join(parts))
    return "".join(l + "\n" for l in out)
