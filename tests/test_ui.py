#!/usr/bin/env python3
"""forge/ui: the terminal component library (tokens.json, Context, the components, the screens, the two renderers).

Each check is a function that takes the thing under test and returns its failures. The plain script runs it on the real code, and
then on a deliberately broken variant (an in-file "control", printed with FORGE_UI_SHOW_CONTROLS=1) and fails if the variant is NOT
caught. Run against a tree without forge/ui the file stops at its first import: "ModuleNotFoundError: No module named 'forge.ui'".

Negative controls on the finished code: one source mutation per behaviour, made in a throwaway copy of the tree and never in this
one; the first message the mutated copy printed is beside it (the commit message repeats them):
  tokens        dark dim #8d888a -> #3a3436     "1 tokens.json problems = ['dark: dim on ground is 1.63, want >= 4.5', ..."
  dead tokens   BAND done uses icon_refused     "2 glyph tokens the components and screens do not name = ['glyph token never used: icon_done']"
                (dot_check -> dot_plan:         "glyph token never used: dot_check", and the dot-shape check fails too)
  width         truncate() cuts nothing         "3 widths 60, 80 and 120 in every glyph set = ['nerd/60 band refused: 70 columns, width is 60', ..."
  NO_COLOR      to_text ignores colour none     "4 colour none writes no ESC byte = ['none: escape byte in meter ramp, empty', ..."
  meter         round() -> int()                "5 meter = ['meter(1,1000): 0 filled cells, want at least 1']"
  status line   skills and servers swapped      "5 status line drop order at 30, 36, 40, 60, 64, 80, 120 columns = [\"status line at 60 columns: '  \u2b22 @design  \u00b7  3 mcp ..."
                MARGIN 2 -> 3                   "status line at 30 columns: '  \u2b22 @design      phase 4/10\\n', want '  \u2b22 @design       phase 4/10\\n'"
  stack         alert_gap_lines loop -> 0       "6 stack spacing = [\"stack: line 0 is not blank, or a band follows it badly: [' \u25b2  review is in CORE_SET ..."
  golden        MARGIN 2 -> 3                   "7 golden screens ... home_full.txt differs from its golden file:" and a unified diff (--- golden/ / +++ rendered/)
  render.py     YELLOW "33" -> "31"             "9 forge/render.py returns what it returned = [\"card_lines(color=True) title = '\\x1b[1malpha\\x1b[0m  /tmp/alpha  \\x1b[31m[frozen]..."
plus in-file controls (no source edit): a tokens dict with a lowered colour, a lost glyph key, a two-character cell glyph or a lost role;
a component source with a glyph or a colour written in; a renderer that ignores colour none; unicode glyphs where ascii is meant; a
layout with alert_gap_lines 0; a font that lacks one glyph.

Round 2 (the enter glyph, the ellipsis token, the gallery as forge/ui/gallery.py), each check written and run BEFORE the change:
  1b  "FAIL 1b the ellipsis token and the enter glyph = [\"nerd: Context.ellipsis is '\u2026', the token is None\", ..."
  8   FORGE_UI_FONT=<the Nerd Font Mono regular file>: "FAIL 8 glyph coverage: nerd enter U+21B5: not in the font" (and unicode)
  10b "FAIL 10b forge.ui.gallery cannot be imported: cannot import name 'gallery' from 'forge.ui'"
After the change all three pass, and each has a control that is caught: a Context.ellipsis that ignores the token ("ascii:
Context.ellipsis is '\u2026', the token is '~'"), a font that lacks one glyph, a gallery whose plain output changes between runs
("gallery --plain is not deterministic: two runs differ"), one with an empty block ("gallery block mark is empty"), a page without
a role ("gallery page has no custom property for role warn_band") or a glyph name, and a command line that differs from plain().

Round 3 (the adversarial review's fixes), each check written and run red first; the failures it printed:
  meter        "FAIL 5 meter = ['meter(99,100): 10 filled cells, want 9', ..., 'meter(19,20) is a full bar below the total', ..."
  widths       "FAIL 4 detect: width is at least 60 = 40, want 60"; "FAIL 11 a group of 100 members: every line at most 80 columns = [119]"
  plural       "FAIL 11 home: 1 project and 1 skill installed = ['\u250c  1 project  \u00b7  1 skills installed']"
  agents       "FAIL 11 agent_block: an unknown agent gets the read dot raised KeyError: 'made-up'"
  band colour  "FAIL 11 truecolor: ink and body on a band are painted ... = (0, 2), want (2, 2)"
  default theme "FAIL 4 detect: the default theme is auto: COLORFGBG 0;15 is light with no FORGE_THEME = 'dark', want 'light'"
  band control "FAIL 11 a band with 'a\\nb' in its text is one line of one row = (1, True, False, False, 80), want (1, False, ..."
  ansi16       "FAIL control not caught: an ansi16 table without a role" and the table was not in tokens.json
  validation   "FAIL 11 status_line total without done raised TypeError, want ValueError", "FAIL 11 stack of a string was accepted",
               "FAIL 11 step with an unknown state was accepted"
  literal scan "FAIL 10 gallery.py carries no glyph or colour of its own = ['gallery.py: string with a colour: ..."
After the fixes each one was mutated back in a throwaway copy (the cap, the group cells, the plural, the .get fallbacks, the
background foreground, _printable, the done/total and step checks, MIN_WIDTH, the auto theme, the ansi16 validation, the stack
type check) and the file failed each time.
The tautological "the control font covers every glyph" line is deleted: it compared a set with itself.

The glyph-coverage check (8) needs FORGE_UI_FONT (a path to a font file): without it, or without fontTools and fc-query, it prints
NOT RUN, NOT ARMED and counts as neither pass nor fail. FORGE_UI_UPDATE=1 rewrites tests/fixtures/ui/*.txt from the current code:
read the diff before committing it."""
import ast
import contextlib
import copy
import difflib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from forge import render  # noqa: E402
from forge.ui import components, context, marks, model, render_ansi, render_html, samples, screens, tokens  # noqa: E402
from forge.ui.model import Line, Span  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "ui")
SHOW = bool(os.environ.get("FORGE_UI_SHOW_CONTROLS"))
SETS = tokens.GLYPH_SETS
WIDTHS = (60, 80, 120)
failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def caught(label, problems):
    """A control: the broken variant must produce at least one failure; the first one is the message recorded in the docstring."""
    if not problems:
        failures.append("control not caught: %s" % label)
    elif SHOW:
        print("CONTROL %-34s -> %s" % (label, problems[0]))


def all_cases(ctx):
    return samples.component_cases(ctx) + samples.screen_cases(ctx)


@contextlib.contextmanager
def patched(obj, name, value):
    saved = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, saved)


# ---- 1. tokens ---------------------------------------------------------------------------------------------------------------
def token_problems(data):
    out = list(tokens.problems(data))
    if out:
        return out
    rules = data["contrast"]
    for name in tokens.THEMES:
        for role, surface, ratio, minimum in tokens.contrast_rows(data["themes"][name], rules):
            if ratio < minimum:
                out.append("%s: %s on %s is %.2f, want >= %.1f" % (name, role, surface, ratio, minimum))
    return out


want("1 tokens.json problems", token_problems(tokens.data()), [])
want("1 contrast rows looked at (looking at zero is a failure)", len(tokens.contrast_rows(tokens.theme("dark"), tokens.data()["contrast"])) > 30, True)
want("1 contrast of black on white", round(tokens.contrast("#000000", "#ffffff"), 2), 21.0)
want("1 contrast of a colour on itself", round(tokens.contrast("#808080", "#808080"), 2), 1.0)
dim = copy.deepcopy(tokens.data())
dim["themes"]["dark"]["dim"] = "#3a3436"
caught("dark dim lowered", token_problems(dim))
lost = copy.deepcopy(tokens.data())
del lost["glyphs"]["ascii"]["mark"]
caught("glyph set lost a key", token_problems(lost))
wide = copy.deepcopy(tokens.data())
wide["glyphs"]["unicode"]["mark"] = "##"
caught("cell glyph of two characters", token_problems(wide))
partial = copy.deepcopy(tokens.data())
del partial["themes"]["light"]["warn"]
caught("a theme lost a role", token_problems(partial))
want("1 every glyph set has the same keys", len({frozenset(tokens.glyphs(s)) for s in SETS}), 1)
want("1 every cell glyph is one character in every set",
     [(s, g) for s in SETS for g in tokens.cell_glyphs() if len(tokens.glyphs(s)[g]) != 1], [])
want("1 the nerd stale icon is one character (a surrogate pair in the JSON)", len(tokens.glyphs("nerd")["icon_stale"]), 1)


# ---- 1b. the enter glyph and the ellipsis token (round 2) -----------------------------------------------------------------------
def glyph_problems(ctx_cls):
    out = []
    for gs in SETS:
        got = ctx_cls("dark", gs, "none", 80).ellipsis
        want_ = tokens.glyphs(gs).get("ellipsis")
        if got != want_:
            out.append("%s: Context.ellipsis is %r, the token is %r" % (gs, got, want_))
    for gs, value in (("nerd", "\u2026"), ("unicode", "\u2026"), ("ascii", "~")):
        if tokens.glyphs(gs).get("ellipsis") != value:
            out.append("%s: ellipsis token is %r, want %r" % (gs, tokens.glyphs(gs).get("ellipsis"), value))
    if "ellipsis" not in tokens.cell_glyphs():
        out.append("ellipsis is not in cell_glyphs")
    for gs, value in (("nerd", "\u23ce"), ("unicode", "\u23ce"), ("ascii", "enter")):
        if tokens.glyphs(gs)["enter"] != value:
            out.append("%s: enter is %r, want %r" % (gs, tokens.glyphs(gs)["enter"], value))
    return out


class HardEllipsis(context.Context):
    ellipsis = "\u2026"


want("1b the ellipsis token and the enter glyph", glyph_problems(context.Context), [])
caught("a Context.ellipsis that ignores the token", glyph_problems(HardEllipsis))


# ---- 2. no dead tokens, and no colour or glyph written into a component -------------------------------------------------------
UI_DIR = os.path.join(ROOT, "forge", "ui")


def source(name):
    with open(os.path.join(UI_DIR, name), encoding="utf-8") as f:
        return f.read()


def string_constants(text):
    return [n.value for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def unused_glyphs(texts):
    used = {s for t in texts for s in string_constants(t)}
    return ["glyph token never used: %s" % g for g in tokens.glyphs("nerd") if g not in used]


want("2 glyph tokens the components and screens do not name", unused_glyphs([source("components.py"), source("screens.py"), source("context.py")]), [])
want("2 the source scan looked at glyph tokens", len(tokens.glyphs("nerd")) > 20, True)
caught("components.py without icon_done", unused_glyphs([source("components.py").replace('"icon_done"', '"x"'), source("screens.py"), source("context.py")]))


# marks.py draws the placeholder anvil with half blocks: those three strings are the drawing, not a glyph token (a final logo replaces them)
ALLOWED_LITERALS = {"marks.py": {marks.UPPER, marks.LOWER, marks.FULL}}


def literal_problems(name, text, allowed=()):
    out = []
    for s in string_constants(text):
        if s in allowed:
            continue
        if not s.isascii():
            out.append("%s: string with a non-ASCII character: %r" % (name, s))
        if re.search(r"#[0-9a-fA-F]{6}\b", s):
            out.append("%s: string with a colour: %r" % (name, s))
    return out


UI_FILES = sorted(f for f in os.listdir(UI_DIR) if f.endswith(".py"))
want("10 the scan looked at every file of forge/ui", UI_FILES, sorted(["__init__.py", "components.py", "context.py", "gallery.py", "marks.py", "model.py", "render_ansi.py", "render_html.py", "samples.py", "screens.py", "tokens.py"]))
for n in UI_FILES:
    want("10 %s carries no glyph or colour of its own" % n, literal_problems(n, source(n), ALLOWED_LITERALS.get(n, ())), [])
caught("a glyph written into a component", literal_problems("components.py", source("components.py") + '\nX = "\\u25c6"\n'))
caught("a colour written into a component", literal_problems("components.py", source("components.py") + '\nX = "#ff00ff"\n'))
caught("a colour written into the gallery", literal_problems("gallery.py", source("gallery.py") + '\nX = "#ff00ff"\n'))
caught("marks.py without its explicit allowance", literal_problems("marks.py", source("marks.py")))


# ---- 3. width ----------------------------------------------------------------------------------------------------------------
def width_problems():
    out = []
    for gs in SETS:
        for w in WIDTHS:
            ctx = context.Context("dark", gs, "none", w)
            for name, state, lines in all_cases(ctx):
                for i, line in enumerate(lines):
                    if line.width > w:
                        out.append("%s/%d %s %s: %d columns, width is %d" % (gs, w, name, state, line.width, w))
                    if name == "band" and (len(lines) != 1 or line.width != w):
                        out.append("%s/%d band %s: %d lines of width %d, want one of %d" % (gs, w, state, len(lines), line.width, w))
                text = render_ansi.to_text(lines, ctx)
                for t in text.split("\n"):
                    if len(t) > w:
                        out.append("%s/%d %s %s: rendered line of %d columns" % (gs, w, name, state, len(t)))
            for sw in samples.STATUS_WIDTHS:
                for line in components.status_line(ctx, width=sw, **samples.STATUS):
                    if line.width > sw:
                        out.append("%s status_line at %d is %d columns" % (gs, sw, line.width))
                    if "@design" not in line.text:
                        out.append("%s status_line at %d dropped the profile" % (gs, sw))
    return out


want("3 widths 60, 80 and 120 in every glyph set", width_problems(), [])
want("3 the loop looked at components and screens", len(all_cases(context.Context("dark", "unicode", "none", 80))) > 40, True)
with patched(components, "truncate", lambda ctx, text, n: text):
    caught("a truncate that cuts nothing", width_problems())
long_band = components.band(context.Context("dark", "unicode", "none", 60), *samples.LONG_BAND)
want("3 a too long band is one line and ends with the ellipsis", (len(long_band), "\u2026" in long_band[0].text), (1, True))
long_ascii = components.band(context.Context("dark", "ascii", "none", 60), *samples.LONG_BAND)
want("3 the ascii band cuts with ~", "~" in long_ascii[0].text and "\u2026" not in long_ascii[0].text, True)
no_room = components.band(context.Context("dark", "unicode", "none", 40), "refused", "a message", "an action that is far too long to fit")
want("3 a band whose action cannot fit drops the action, keeps one line", (len(no_room), no_room[0].width, "far too long" in no_room[0].text), (1, 40, False))


# ---- 4. NO_COLOR and ASCII ---------------------------------------------------------------------------------------------------
def esc_problems(render_fn):
    out = []
    for gs in SETS:
        ctx = context.Context("dark", gs, "none", 80)
        for name, state, lines in all_cases(ctx):
            if "\033" in render_fn(lines, ctx):
                out.append("none: escape byte in %s %s" % (name, state))
    return out


def ascii_problems(glyph_set):
    out = []
    for color in ("none", "16", "256", "truecolor"):
        ctx = context.Context("dark", glyph_set, color, 80)
        for name, state, lines in all_cases(ctx):
            if not render_ansi.to_text(lines, ctx).isascii():
                out.append("%s set: non-ASCII output in %s %s" % (glyph_set, name, state))
    return out


want("4 colour none writes no ESC byte", esc_problems(render_ansi.to_text), [])
caught("a renderer that ignores colour none", esc_problems(lambda lines, ctx: render_ansi.to_text(lines, ctx.replace(color="truecolor"))))
want("4 the ascii set writes only ASCII, at every colour depth", ascii_problems("ascii"), [])
caught("unicode glyphs where ascii is meant", ascii_problems("unicode"))


class Tty(io.StringIO):
    def isatty(self):
        return True


FULL = {"TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "en_US.UTF-8", "COLUMNS": "100"}
want("4 detect: a pipe is colour none", context.detect(FULL, io.StringIO()).color, "none")
want("4 detect: no stream is colour none", context.detect(FULL, None).color, "none")
want("4 detect: NO_COLOR set is none even on a tty", context.detect(dict(FULL, NO_COLOR="1"), Tty()).color, "none")
want("4 detect: NO_COLOR set to 0 is still none", context.detect(dict(FULL, NO_COLOR="0"), Tty()).color, "none")
want("4 detect: NO_COLOR empty does not switch colour off", context.detect(dict(FULL, NO_COLOR=""), Tty()).color, "truecolor")
want("4 detect: COLORTERM truecolor", context.detect(FULL, Tty()).color, "truecolor")
want("4 detect: COLORTERM 24bit", context.detect(dict(FULL, COLORTERM="24bit"), Tty()).color, "truecolor")
want("4 detect: TERM 256color", context.detect(dict(FULL, COLORTERM=""), Tty()).color, "256")
want("4 detect: plain xterm is 16", context.detect(dict(FULL, COLORTERM="", TERM="xterm"), Tty()).color, "16")
want("4 detect: TERM dumb is none", context.detect(dict(FULL, TERM="dumb"), Tty()).color, "none")
want("4 detect: TERM unset is none", context.detect({"LANG": "en_US.UTF-8"}, Tty()).color, "none")
want("4 detect: default glyph set is unicode", context.detect(FULL, Tty()).glyphs, "unicode")
want("4 detect: FORGE_ICONS nerd", context.detect(dict(FULL, FORGE_ICONS="nerd"), Tty()).glyphs, "nerd")
want("4 detect: FORGE_ICONS ascii", context.detect(dict(FULL, FORGE_ICONS="ascii"), Tty()).glyphs, "ascii")
want("4 detect: an unknown FORGE_ICONS is unicode", context.detect(dict(FULL, FORGE_ICONS="emoji"), Tty()).glyphs, "unicode")
want("4 detect: a non-UTF-8 locale is ascii", context.detect(dict(FULL, LANG="C"), Tty()).glyphs, "ascii")
want("4 detect: a non-UTF-8 locale beats FORGE_ICONS nerd", context.detect(dict(FULL, LANG="C", FORGE_ICONS="nerd"), Tty()).glyphs, "ascii")
want("4 detect: LC_ALL wins over LANG", context.detect(dict(FULL, LC_ALL="C", LANG="en_US.UTF-8"), Tty()).glyphs, "ascii")
want("4 detect: no locale at all is ascii", context.detect({"TERM": "xterm"}, Tty()).glyphs, "ascii")
want("4 detect: default theme is dark when COLORFGBG is not set", context.detect(FULL, Tty()).theme, "dark")
want("4 detect: the default theme is auto: COLORFGBG 0;15 is light with no FORGE_THEME", context.detect(dict(FULL, COLORFGBG="0;15"), Tty()).theme, "light")
want("4 detect: FORGE_THEME dark beats COLORFGBG", context.detect(dict(FULL, COLORFGBG="0;15", FORGE_THEME="dark"), Tty()).theme, "dark")
want("4 detect: FORGE_THEME light", context.detect(dict(FULL, FORGE_THEME="light"), Tty()).theme, "light")
for bg, theme in (("0", "dark"), ("6", "dark"), ("8", "dark"), ("7", "light"), ("15", "light")):
    want("4 detect: auto with COLORFGBG 15;%s" % bg, context.detect(dict(FULL, FORGE_THEME="auto", COLORFGBG="15;%s" % bg), Tty()).theme, theme)
want("4 detect: auto reads the last field of COLORFGBG", context.detect(dict(FULL, FORGE_THEME="auto", COLORFGBG="0;default;15"), Tty()).theme, "light")
want("4 detect: auto without COLORFGBG is dark", context.detect(dict(FULL, FORGE_THEME="auto"), Tty()).theme, "dark")
want("4 detect: COLUMNS gives the width", context.detect(FULL, Tty()).width, 100)
want("4 detect: width is at least 60", context.detect(dict(FULL, COLUMNS="12"), Tty()).width, 60)
want("4 detect: a COLUMNS that is no number falls back to the terminal size and stays at least 60", context.detect(dict(FULL, COLUMNS="x"), Tty()).width >= 60, True)

# colour output: what each depth writes
ESC = "\033["
one = [Line([Span("accent", "a"), Span("ink", "b", True), Span("body", "c"), Span("faint", "d"), Span("mute", "e")])]
tc = render_ansi.to_text(one, context.Context("dark", "unicode", "truecolor", 80))
want("4 truecolor: accent is 38;2 and reset after each span, ink is bold only, body is bare",
     tc, ESC + "38;2;242;114;176ma" + ESC + "0m" + ESC + "1mb" + ESC + "0m" + "c" + ESC + "38;2;92;84;87md" + ESC + "0m" + ESC + "38;2;165;155;159me" + ESC + "0m\n")
c256 = render_ansi.to_text(one, context.Context("dark", "unicode", "256", 80))
want("4 256: accent is the nearest xterm index", ESC + "38;5;%dma" % render_ansi.xterm256("#f272b0") in c256, True)
want("4 xterm256 of black and white", (render_ansi.xterm256("#000000"), render_ansi.xterm256("#ffffff"), render_ansi.xterm256("#808080")), (16, 231, 244))
c16 = render_ansi.to_text(one, context.Context("dark", "unicode", "16", 80))
want("4 16 colours: accent magenta, faint bright black plus dim, mute bright black",
     c16, ESC + "35ma" + ESC + "0m" + ESC + "1mb" + ESC + "0m" + "c" + ESC + "90;2md" + ESC + "0m" + ESC + "90me" + ESC + "0m\n")
band_line = [Line([Span("body", "x")], bg="warn_band"), Line([Span("body", "y")], bg="band")]
want("4 truecolor: a band is a 48;2 background and its body text the theme's own foreground", ESC + "38;2;217;210;214;48;2;42;35;16mx" + ESC + "0m", render_ansi.to_text(band_line[:1], context.Context("dark", "unicode", "truecolor", 80)).strip())
want("4 16 colours: only the cursor band is reverse video",
     render_ansi.to_text(band_line, context.Context("dark", "unicode", "16", 80)), "x\n" + ESC + "7my" + ESC + "0m\n")
want("4 the colour is the theme's: light accent", ESC + "38;2;176;52;111ma" in render_ansi.to_text(one, context.Context("light", "unicode", "truecolor", 80)), True)

# html and css
css = render_html.tokens_css("dark")
want("4 css starts with :root and carries every role", [r for r in ("ground", "ink", "body", "mute", "dim", "faint", "line", "band", "accent", "ramp-0", "ramp-3", "warn", "ok", "error",
                                                                 "warn-band", "error-band", "ok-band", "neutral-band") if "--forge-%s:" % r not in css], [])
want("4 css opens with :root{", css.startswith(":root{"), True)
want("4 css takes the value from tokens.json", "--forge-accent:%s" % tokens.theme("dark")["accent"] in css, True)
html_out = render_html.to_html(components.band(context.Context("dark", "unicode", "none", 60), "refused", "m", "a"), "dark")
want("4 html: a pre block, spans name custom properties and never a colour", (html_out.startswith("<pre"), "var(--forge-warn-band)" in html_out, "var(--forge-ink)" in html_out, re.search(r"#[0-9a-f]{6}", html_out)),
     (True, True, True, None))
want("4 html escapes text", "&lt;b&gt;" in render_html.to_html([Line([Span("ink", "<b>")])], "dark"), True)
try:
    Span("pink", "x")
    failures.append("a span with an unknown role was accepted")
except ValueError:
    pass


# ---- 5. meter and status line --------------------------------------------------------------------------------------------------
def meter_problems(fn):
    out = []
    ctx = context.Context("dark", "unicode", "none", 80)
    full, empty = ctx.glyph("meter_full"), ctx.glyph("meter_empty")
    for done, total, cells, filled in ((0, 10, 10, 0), (4, 10, 10, 4), (1, 1000, 10, 1), (10, 10, 10, 10), (15, 10, 10, 10), (5, 0, 10, 0), (3, 4, 4, 3), (1, 2, 6, 3),
                                       (99, 100, 10, 9), (9, 10, 10, 9), (999, 1000, 10, 9), (95, 100, 10, 9)):
        spans = fn(ctx, done, total, cells=cells)
        text = "".join(s.text for s in spans)
        got = text.count(full)
        if len(text) != cells:
            out.append("meter(%d,%d): %d cells, want %d" % (done, total, len(text), cells))
        if got != filled:
            out.append("meter(%d,%d): %d filled cells, want %s" % (done, total, got, filled if done > 0 and total > 0 else 0) if (done, total) != (1, 1000) else "meter(1,1000): %d filled cells, want at least 1" % got)
        if text != full * got + empty * (cells - got):
            out.append("meter(%d,%d): filled cells are not first: %r" % (done, total, text))
    roles = [s.role for s in fn(ctx, 4, 10, cells=10) if s.text.startswith(full)]
    if roles != ["ramp0", "ramp1", "ramp2", "ramp3"]:
        out.append("ramp of 4 filled cells is %r" % roles)
    ten = [s.role for s in fn(ctx, 10, 10, cells=10) if s.text.startswith(full)]
    order = [int(r[4:]) for r in ten]
    if order != sorted(order) or order[0] != 0 or order[-1] != 3 or len(ten) != 10:
        out.append("ramp of 10 filled cells goes %r" % ten)
    if [s.role for s in fn(ctx, 4, 10, cells=10) if s.text.startswith(empty)] != ["faint"]:
        out.append("empty cells are not faint")
    flat = fn(ctx, 3, 5, cells=5, mode="flat")
    if {s.role for s in flat if s.text.startswith(full)} != {"accent"}:
        out.append("flat meter has roles other than accent: %r" % [s.role for s in flat])
    # a full bar means complete: below the total it never fills every cell, and above zero it fills at least one
    for total in range(1, 61):
        for done in range(0, total):
            n = "".join(x.text for x in fn(ctx, done, total, cells=10)).count(full)
            if n >= 10:
                out.append("meter(%d,%d) is a full bar below the total" % (done, total))
                break
            if done > 0 and n < 1:
                out.append("meter(%d,%d) has no filled cell" % (done, total))
                break
    return out


want("5 meter", meter_problems(components.meter), [])


def meter_rounds_down(ctx, done, total, cells=None, mode="ramp"):
    spans = components.meter(ctx, 0 if 0 < done / max(total, 1) * cells < 1 else done, total, cells, mode)
    return spans


caught("a meter that rounds down to zero", meter_problems(meter_rounds_down))


def meter_full_when_nearly(ctx, done, total, cells=None, mode="ramp"):
    return components.meter(ctx, total if total > 0 and done / total >= 0.95 else done, total, cells, mode)


caught("a meter that shows a full bar for 99 of 100", meter_problems(meter_full_when_nearly))
try:
    components.meter(context.Context(), 1, 2, mode="stripes")
    failures.append("an unknown meter mode was accepted")
except ValueError:
    pass

STATUS_GOLDEN = {
    30: '  \u2b22 @design       phase 4/10\n',
    36: '  \u2b22 @design             phase 4/10\n',
    40: '  \u2b22 @design     phase \u25b0\u25b0\u25b0\u25b0\u25b1\u25b1\u25b1\u25b1\u25b1\u25b1  4/10\n',
    60: '  \u2b22 @design               phase 10 design \u25b0\u25b0\u25b0\u25b0\u25b1\u25b1\u25b1\u25b1\u25b1\u25b1  4/10\n',
    64: '  \u2b22 @design  \u00b7  16 skills     phase 10 design \u25b0\u25b0\u25b0\u25b0\u25b1\u25b1\u25b1\u25b1\u25b1\u25b1  4/10\n',
    80: '  \u2b22 @design  \u00b7  16 skills  \u00b7  3 mcp           phase 10 design \u25b0\u25b0\u25b0\u25b0\u25b1\u25b1\u25b1\u25b1\u25b1\u25b1  4/10\n',
    120: '  \u2b22 @design  \u00b7  16 skills  \u00b7  3 mcp' + ' ' * 51 + 'phase 10 design \u25b0\u25b0\u25b0\u25b0\u25b1\u25b1\u25b1\u25b1\u25b1\u25b1  4/10\n',
}


def status_problems():
    out = []
    ctx = context.Context("dark", "unicode", "none", 80)
    for w, lines in samples.status_line_cases(ctx):
        got = render_ansi.to_text(lines, ctx)
        # the golden keeps the padding the renderer strips only at the end of a line, so compare without it
        if got != STATUS_GOLDEN[w]:
            out.append("status line at %d columns: %r, want %r" % (w, got, STATUS_GOLDEN[w]))
        if "@design" not in got:
            out.append("status line at %d columns dropped the profile" % w)
    no_phase = components.status_line(ctx, "@design", 16, 3)
    if render_ansi.to_text(no_phase, ctx) != "  \u2b22 @design  \u00b7  16 skills  \u00b7  3 mcp\n":
        out.append("status line without a phase: %r" % render_ansi.to_text(no_phase, ctx))
    tight = components.status_line(ctx, "@design", 16, 3, width=14)
    if "@design" not in tight[0].text or "skills" in tight[0].text:
        out.append("status line at 14 columns: %r" % tight[0].text)
    return out


want("5 status line drop order at 30, 36, 40, 60, 64, 80, 120 columns", status_problems(), [])
want("5 status line: one line", all(len(l) == 1 for _, l in samples.status_line_cases(context.Context())), True)
with patched(components, "MARGIN", 0):
    caught("status line with MARGIN 0", status_problems())


# ---- 6. stack spacing ----------------------------------------------------------------------------------------------------------
def stack_problems(ctx):
    out = []
    one_band = components.stack(ctx, [samples.BANDS["refused"]])
    two = components.stack(ctx, [samples.BANDS["refused"], samples.BANDS["broken"]])
    if len(one_band) != 2 or one_band[0].text != "" or not one_band[1].text.strip():
        out.append("stack: line 0 is not blank, or a band follows it badly: %r" % [l.text for l in one_band])
    if len(two) != 4 or [bool(l.text.strip()) for l in two] != [False, True, False, True]:
        out.append("stack: blank, band, blank, band expected, got %r" % [bool(l.text.strip()) for l in two])
    if components.stack(ctx, []) != []:
        out.append("stack of nothing is not empty")
    return out


class NoGap(context.Context):
    @property
    def layout(self):
        return dict(tokens.layout(), alert_gap_lines=0)


want("6 stack spacing", stack_problems(context.Context("dark", "unicode", "none", 80)), [])
caught("a layout with alert_gap_lines 0", stack_problems(NoGap("dark", "unicode", "none", 80)))
want("6 alert_gap_lines 2 gives two blank lines", len(components.stack(type("Two", (context.Context,), {"layout": property(lambda s: dict(tokens.layout(), alert_gap_lines=2))})(), [samples.BANDS["stale"]])), 3)

# ---- the rest of the components, named behaviours -------------------------------------------------------------------------------
ctx = context.Context("dark", "unicode", "none", 80)
want("components: the band kinds draw their own surface and icon role",
     [(k, components.band(ctx, k, "m")[0].bg, components.band(ctx, k, "m")[0].spans[1].role) for k in components.BAND],
     [("refused", "warn_band", "warn"), ("broken", "error_band", "error"), ("frozen", "neutral_band", "ink"), ("stale", "neutral_band", "ink"), ("done", "ok_band", "ok")])
want("components: a band with no action ends in padding to the width", components.band(ctx, "done", "m")[0].width, 80)
want("components: every agent has a family", sorted(components.FAMILY), sorted(["executor", "planner", "pre-mortem", "post-mortem", "reviewer", "security-reviewer", "review-verifier", "ui-walker", "ui-verifier", "researcher", "state", "decisions", "demo", "skill-proposer"]))
want("components: the dot is always mute and its shape follows the family",
     [(components.agent_block(ctx, "t", [(a, "", "", ("running", "r"))])[1].spans[3].role, components.agent_block(ctx, "t", [(a, "", "", ("running", "r"))])[1].spans[3].text) for a in ("executor", "planner", "reviewer", "researcher")],
     [("mute", "\u25c6"), ("mute", "\u25c7"), ("mute", "\u25cf"), ("mute", "\u25cb")])
want("components: agent states colour the text", [components.agent_block(ctx, "t", [("executor", "", "", (k, "x"))])[1].spans[-1].role for k in ("starting", "running", "done", "findings", "failed")],
     ["mute", "mute", "ok", "warn", "error"])
want("components: the last agent row uses tree_last", [l.spans[1].text for l in components.agent_block(ctx, "t", [("executor", "", "", ("done", "x")), ("planner", "", "", ("done", "x"))])[1:]], ["\u251c", "\u2514"])
want("components: a long agent name widens the name column", components.agent_block(ctx, "t", [("security-reviewer", "u", "w", ("done", "x"))])[1].text.split()[2:4], ["security-reviewer", "u"])
want("components: check_row pending_off carries its own right text in warn",
     (components.check_row(ctx, "x", "pending_off")[0].spans[-1].text, components.check_row(ctx, "x", "pending_off")[0].spans[-1].role), ("off, not applied yet", "warn"))
want("components: a cursor row is filled to the width with the band", (components.check_row(ctx, "x", "on", cursor=True)[0].bg, components.check_row(ctx, "x", "on", cursor=True)[0].width), ("band", 80))
want("components: the group meter is flat", {s.role for s in components.group(ctx, "S", ["a", "b"])[0].spans if s.text.startswith("\u25b0")}, {"accent"})
want("components: the group tree glyphs", [l.spans[2].text for l in components.group(ctx, "S", ["a", "b", "c"])[1:]], ["\u2502 ", "\u2502 ", "\u2514 "])
want("components: the cursor member has an accent nest and an icon", ([(s.role, s.text) for s in components.group(ctx, "S", ["a", "b"], cursor=0, icon_on=("warn", "!"))[1].spans if s.role in ("accent", "warn")]), [("accent", "\u25b8 "), ("warn", "!")])
want("components: a table has no borders and a lowercase header", [l.text for l in components.table(ctx, ["a", "bb"], [[[Span("body", "x")], [Span("body", "y")]]], [3, 2])], ["a    bb", "x    y"])
want("components: header wraps the tagline at the measure", max(l.width for l in components.header(context.Context("dark", "unicode", "none", 200), "p", "v", "word " * 40, marks.mark_lines(ctx))) <= 2 + 18 + 4 + 66, True)
want("components: keys with two spaces around the separator", components.keys(ctx, [("updown", "select"), ("esc", "cancel")])[0].text, "\u2514  \u2191\u2193 select  \u00b7  esc cancel")
want("components: keys close the gaps in the ascii set at 60 columns", components.keys(context.Context("dark", "ascii", "none", 60), [("updown", "select"), ("space", "toggle"), ("enter", "apply"), ("esc", "cancel")])[0].width <= 60, True)
want("marks: the placeholder is four lines of 18 cells", (len(marks.MARK_PLACEHOLDER), {len(l) for l in marks.MARK_PLACEHOLDER}), (4, {18}))
want("marks: the first line accent and the rest mute", [l[0].role for l in marks.mark_lines(ctx)], ["accent", "mute", "mute", "mute"])
want("marks: the first text line is the upper half of the first two rows", marks.MARK_PLACEHOLDER[0], "\u2580\u2580" + "\u2588" * 16)
want("marks: the ascii mark is ASCII", all(s.text.isascii() for l in marks.mark_lines(context.Context("dark", "ascii", "none", 80)) for s in l), True)
want("model: a line's width is its text", Line([Span("ink", "ab"), Span("mute", "cde")]).width, 5)
try:
    Line([], bg="pink")
    failures.append("a line with an unknown surface was accepted")
except ValueError:
    pass
def screens_text(ctx, data):
    return render_ansi.to_text(screens.home(ctx, data), ctx)


frozen_lines = screens.selector(ctx, samples.SELECTORS["frozen"])
want("screens: the frozen selector replaces the keys by esc close", [l.text for l in frozen_lines if l.text.startswith("\u2514")], ["\u2514  esc close"])
want("screens: the frozen selector dims every row (only faint text between the title and the keys)",
     {s.role for l in frozen_lines[2:-4] for s in l.spans if s.text.strip() and s.role not in ("faint", "ink")} - {"faint"}, set())
want("screens: the frozen selector has no accent mark on a row", [s.text for l in frozen_lines[3:-4] for s in l.spans if s.role == "accent"], [])

want("screens: home with the plugin row", "fwx" in screens_text(ctx, samples.HOME), True)
want("screens: home without the plugin row", "fwx " in screens_text(ctx, dict(samples.HOME, plugin=None)), False)
want("screens: the doctor meter measures passed over the total", screens_text(ctx, samples.HOME).count("\u25b0"), 9 + 4)
want("screens: a frozen project shows the frozen icon in ink and a blank meter",
     [(s.role, s.text) for l in screens.project_list(ctx, samples.PROJECTS)[2:] for s in l.spans if s.text == ctx.glyph("icon_frozen")], [("ink", "*")])
want("screens: the project table header is lowercase", [l.text for l in screens.project_list(ctx, samples.PROJECTS)][2].split(), ["\u2502", "project", "servers", "skills"])

# ---- 7. golden screens ---------------------------------------------------------------------------------------------------------
golden_ctx = context.Context("dark", "unicode", "none", 80)


def slug(screen, state):
    return (screen + "_" + state if state else screen).replace(" ", "_").replace(",", "")


def golden_problems(update=False):
    out = []
    seen = set()
    for screen, state, lines in samples.screen_cases(golden_ctx):
        name = slug(screen, state) + ".txt"
        seen.add(name)
        path = os.path.join(FIXTURES, name)
        got = render_ansi.to_text(lines, golden_ctx)
        if update:
            with open(path, "w", encoding="utf-8") as f:
                f.write(got)
            continue
        if not os.path.exists(path):
            out.append("%s: no golden file (FORGE_UI_UPDATE=1 writes it)" % name)
            continue
        with open(path, encoding="utf-8") as f:
            wanted = f.read()
        if got != wanted:
            diff = "".join(difflib.unified_diff(wanted.splitlines(True), got.splitlines(True), "golden/" + name, "rendered/" + name))
            out.append("%s differs from its golden file:\n%s" % (name, diff))
    extra = sorted(set(os.listdir(FIXTURES)) - seen) if os.path.isdir(FIXTURES) and not update else []
    out.extend("%s: a golden file no screen produces" % n for n in extra)
    return out


if os.environ.get("FORGE_UI_UPDATE"):
    os.makedirs(FIXTURES, exist_ok=True)
    golden_problems(update=True)
want("7 golden screens at 80 columns, unicode", golden_problems(), [])
want("7 the golden files looked at are 10", len([n for n in os.listdir(FIXTURES) if n.endswith(".txt")]) if os.path.isdir(FIXTURES) else 0, 10)
with patched(components, "MARGIN", 3):
    problems = golden_problems()
    caught("components.MARGIN raised to 3", problems)
    want("7 the failure carries a unified diff", bool(problems) and "--- golden/" in problems[0] and "+++ rendered/" in problems[0], True)


# ---- 8. glyph coverage in a font ------------------------------------------------------------------------------------------------
def font_codepoints(path):
    """The code points a font file covers, by fontTools when importable, else by fc-query; None when neither can say."""
    try:
        from fontTools.ttLib import TTFont
        with contextlib.closing(TTFont(path, fontNumber=0)) as f:
            return set(f.getBestCmap())
    except ImportError:
        pass
    if shutil.which("fc-query"):
        r = subprocess.run(["fc-query", "--format", "%{charset}\n", path], capture_output=True, text=True, timeout=60)
        if r.returncode:
            return None
        points = set()
        for part in r.stdout.split():
            lo, _, hi = part.partition("-")
            points.update(range(int(lo, 16), int(hi or lo, 16) + 1))
        return points
    return None


def coverage_problems(points):
    out = []
    for gs in ("nerd", "unicode"):
        for name, value in tokens.glyphs(gs).items():
            missing = [ch for ch in value if ord(ch) not in points]
            if missing:
                out.append("%s %s %s: not in the font" % (gs, name, " ".join("U+%04X" % ord(m) for m in missing)))
    return out


font = os.environ.get("FORGE_UI_FONT")
if not font:
    print("NOT RUN, NOT ARMED: FORGE_UI_FONT is unset, so no font was asked whether it has the glyphs of the nerd and unicode sets")
else:
    pts = font_codepoints(font) if os.path.isfile(font) else None
    if pts is None:
        print("NOT RUN, NOT ARMED: %s is not a font file that fontTools or fc-query can read" % font)
    else:
        for msg in coverage_problems(pts):
            failures.append("8 glyph coverage: " + msg)
every = {ord(ch) for gs in ("nerd", "unicode") for v in tokens.glyphs(gs).values() for ch in v}
caught("a font that lacks one glyph", coverage_problems(every - {ord("\u25b0")}))
want("8 the coverage check looked at glyphs", len(every) > 25, True)

# ---- 10b. the gallery: python3 -m forge.ui.gallery --------------------------------------------------------------------------------
BLOCKS = ["meter", "icons", "mark", "group", "keys", "table", "header", "band", "stack", "status_line", "agent_block", "home",
          "project_list", "selector", "selector_frozen", "selector_stack"]


def gallery_problems(gallery, expected_cli=None):
    """`gallery` is the module (or anything with plain() and page()): plain output deterministic and every block non-empty and
    present; the page names every theme role and every glyph token."""
    out = []
    first, second = gallery.plain(), gallery.plain()
    if first != second:
        out.append("gallery --plain is not deterministic: two runs differ")
    found = re.findall(r"^=== (\w+) ===$", first, re.M)
    if found != BLOCKS:
        out.append("gallery --plain blocks are %r, want %r" % (found, BLOCKS))
    parts = re.split(r"^=== \w+ ===$", first, flags=re.M)[1:]
    for name, body in zip(found, parts):
        if not body.strip():
            out.append("gallery block %s is empty" % name)
    page = gallery.page()
    roles = [r for r in tokens.theme("dark") if r != "ramp"] + ["ramp-%d" % i for i in range(4)]
    for r in roles:
        if "--forge-%s:" % r.replace("_", "-") not in page:
            out.append("gallery page has no custom property for role %s" % r)
    for g in tokens.glyphs("nerd"):
        if ">%s<" % g not in page:
            out.append("gallery page does not name glyph %s" % g)
    return out


try:
    from forge.ui import gallery
except ImportError as e:  # the check below then fails loudly rather than the whole file stopping
    gallery = None
    failures.append("10b forge.ui.gallery cannot be imported: %s" % e)
if gallery is not None:
    want("10b the gallery: deterministic, every block non-empty, every role and glyph named", gallery_problems(gallery), [])
    nondeterministic = types.SimpleNamespace(plain=iter(["=== a ===\nx\n", "=== a ===\ny\n"] * 3).__next__, page=gallery.page)
    caught("a gallery whose plain output changes between runs", gallery_problems(nondeterministic))
    def empty_mark():
        head, rest = gallery.plain().split("=== mark ===\n", 1)
        return head + "=== mark ===\n\n=== group ===" + rest.split("=== group ===", 1)[1]

    empty = types.SimpleNamespace(plain=empty_mark, page=gallery.page)
    caught("a gallery with an empty block", gallery_problems(empty))
    no_role = types.SimpleNamespace(plain=gallery.plain, page=lambda: gallery.page().replace("--forge-warn-band:", "--x:"))
    caught("a gallery page without a role", gallery_problems(no_role))
    no_glyph = types.SimpleNamespace(plain=gallery.plain, page=lambda: gallery.page().replace(">icon_stale<", ">x<"))
    caught("a gallery page without a glyph name", gallery_problems(no_glyph))

    def cli_problems(expected_plain):
        out = []
        env = dict(os.environ, PYTHONPATH=ROOT)
        r = subprocess.run([sys.executable, "-m", "forge.ui.gallery", "--plain"], capture_output=True, text=True, cwd=tempfile.gettempdir(), env=env, timeout=120)
        if r.returncode or r.stdout != expected_plain:
            out.append("python3 -m forge.ui.gallery --plain: exit %d and %d characters, want exit 0 and %d" % (r.returncode, len(r.stdout), len(expected_plain)))
        with tempfile.TemporaryDirectory() as d:
            css, page = os.path.join(d, "t.css"), os.path.join(d, "g.html")
            r = subprocess.run([sys.executable, "-m", "forge.ui.gallery", "--out", page, "--tokens-css", css], capture_output=True, text=True, cwd=d, env=env, timeout=120)
            if r.returncode or not os.path.exists(css) or not os.path.exists(page):
                out.append("python3 -m forge.ui.gallery --out --tokens-css: exit %d, %s" % (r.returncode, r.stderr.strip()[-200:]))
            else:
                with open(css, encoding="utf-8") as f, open(page, encoding="utf-8") as g:
                    if "--forge-accent:" not in f.read() or "<!doctype html>" not in g.read():
                        out.append("gallery files lack the custom properties or the page")
        return out

    want("10b python3 -m forge.ui.gallery runs with each flag", cli_problems(gallery.plain()), [])
    caught("a command line whose plain output differs from plain()", cli_problems(gallery.plain() + "x"))


# ---- 11. the adversarial review's fixes ------------------------------------------------------------------------------------------
ctx = context.Context("dark", "unicode", "none", 80)
# 2 a group's meter is at most meter_cells wide and a big set fits
big = components.group(ctx, "S", ["m%d" % i for i in range(100)])
want("11 a group of 100 members: every line at most 80 columns", [l.width for l in big if l.width > 80], [])
want("11 a group's meter is at most 10 cells", sum(len(sp.text) for sp in big[0].spans if sp.text and sp.text[0] in "\u25b0\u25b1"), 10)
want("11 a group of 100 members says N of N and not the cells", "100 of 100" in big[0].text, True)
want("11 a group of 3 keeps a 3 cell meter", sum(len(sp.text) for sp in components.group(ctx, "S", ["a", "b", "c"])[0].spans if sp.text and sp.text[0] in "\u25b0\u25b1"), 3)
# 3 plural
want("11 status line: 1 skill", "1 skill " in components.status_line(ctx, "@x", 1, 1)[0].text + " ", True)
want("11 status line: 1 skill is not 1 skills", "1 skills" in components.status_line(ctx, "@x", 1, 1)[0].text, False)
want("11 status line: 0 skills and 2 skills", ("0 skills" in components.status_line(ctx, "@x", 0, 1)[0].text, "2 skills" in components.status_line(ctx, "@x", 2, 1)[0].text), (True, True))
one_skill = screens.home(ctx, dict(samples.HOME, skills=1, projects=1))
want("11 home: 1 project and 1 skill installed", [l.text for l in one_skill if "installed" in l.text], ["\u250c  1 project  \u00b7  1 skill installed"])
# 4 an agent type or a state kind nobody listed
def attempt(label, fn, expected):
    """`want` for a call that may raise: the raise is the failure, not the end of the file."""
    try:
        want(label, fn(), expected)
    except Exception as e:  # noqa: BLE001
        failures.append("%s raised %s: %s" % (label, type(e).__name__, e))


attempt("11 agent_block: an unknown agent gets the read dot", lambda: components.agent_block(ctx, "t", [("made-up", "u", "w", ("done", "x"))])[1].spans[3].text, ctx.glyph("dot_read"))
attempt("11 agent_block: an unknown state kind is mute", lambda: components.agent_block(ctx, "t", [("executor", "u", "w", ("made-up", "x"))])[1].spans[-1].role, "mute")
# 5 a band paints its own foreground for ink and body
for depth in ("truecolor", "256"):
    cx = context.Context("dark", "unicode", depth, 80)
    on_band = render_ansi.to_text([Line([Span("ink", "a", True), Span("body", "b")], bg="band")], cx)
    bare = render_ansi.to_text([Line([Span("ink", "a", True), Span("body", "b")])], cx)
    want("11 %s: ink and body on a band are painted (a foreground code before each)" % depth, (on_band.count("38;"), on_band.count("48;")), (2, 2))
    want("11 %s: ink and body without a background stay the terminal's own" % depth, "38;" in bare, False)
want("11 truecolor: the ink on a band is the theme's ink", "38;2;242;237;239" in render_ansi.to_text([Line([Span("ink", "a")], bg="band")], context.Context("dark", "unicode", "truecolor", 80)), True)
want("11 16 colours: ink on a band is not painted, the cursor band is reverse", render_ansi.to_text([Line([Span("ink", "a")], bg="band")], context.Context("dark", "unicode", "16", 80)), "\033[7ma\033[0m\n")
# 6 control characters cannot split a band
for evil in ("a\nb", "a\rb", "a\x1b[2Jb", "a\tb", "a\u2028b"):
    got = components.band(ctx, "broken", evil, evil)
    want("11 a band with %r in its text is one line of one row" % evil, (len(got), "\n" in got[0].text, "\r" in got[0].text, "\x1b" in got[0].text, got[0].width), (1, False, False, False, 80))
want("11 a band keeps the nerd icon (private use) in its text", "\uf00d" in components.band(context.Context("dark", "nerd", "none", 80), "broken", "x", "")[0].text, True)
# 8 validation
for label, call, exc in (("status_line total without done", lambda: components.status_line(ctx, "@x", 1, 1, "p", None, 5), ValueError),
                         ("status_line done without total", lambda: components.status_line(ctx, "@x", 1, 1, "p", 4, None), ValueError),
                         ("stack of a string", lambda: components.stack(ctx, ["broken"]), TypeError),
                         ("stack of a number", lambda: components.stack(ctx, [3]), TypeError),
                         ("stack of a list of non-lines", lambda: components.stack(ctx, [["broken", "m", "a"]]), TypeError),
                         ("stack of a tuple of two", lambda: components.stack(ctx, [("broken", "m")]), TypeError),
                         ("step with an unknown state", lambda: components.step(ctx, "x", state="actve"), ValueError)):
    try:
        call()
        failures.append("11 %s was accepted" % label)
    except exc as e:
        if not str(e):
            failures.append("11 %s raised without a message" % label)
    except Exception as e:  # noqa: BLE001
        failures.append("11 %s raised %s, want %s" % (label, type(e).__name__, exc.__name__))
want("11 stack accepts a list of lines", len(components.stack(ctx, [components.band(ctx, "done", "m")])), 2)
# 7 the 16-colour table is in tokens.json
want("11 tokens.json has an ansi16 table for every colour role", sorted(tokens.data().get("ansi16", {})), sorted(["accent", "mute", "dim", "faint", "warn", "ok", "error", "ramp0", "ramp1", "ramp2", "ramp3"]))
no16 = copy.deepcopy(tokens.data())
no16.setdefault("ansi16", {}).pop("warn", None)
caught("an ansi16 table without a role", token_problems(no16))
bad16 = copy.deepcopy(tokens.data())
bad16.setdefault("ansi16", {})["warn"] = "yellow"
caught("an ansi16 value that is no SGR code", token_problems(bad16))
want("11 render_ansi reads its 16-colour codes from tokens.json", render_ansi.to_text([Line([Span("warn", "a")])], context.Context("dark", "unicode", "16", 80)), "\033[%sma\033[0m\n" % tokens.data()["ansi16"]["warn"] if "ansi16" in tokens.data() else "")


# ---- 9. forge/render.py is untouched ---------------------------------------------------------------------------------------------
CARD = {"project": "alpha", "path": "/tmp/alpha", "frozen": True, "skills": 3, "servers": ["a", "b"], "plugins": ["*"],
        "profiles": {"default": "x", "offered": ["y"]}, "options": {"k": True, "j": None}, "opted_out": ["z"]}


def render_problems():
    out = []
    got = render.lines([("header", "Skills"), ("row", "a", True, True), ("row", "b", False, False)])
    if got != ["Skills", "> [x] a", "  [ ] b"]:
        out.append("lines() = %r" % got)
    if render.hint() != "up/down move, space toggles, enter confirms, esc cancels":
        out.append("hint() = %r" % render.hint())
    if render.paint("x", "1", True) != "\033[1mx\033[0m" or render.paint("x", "1", False) != "x":
        out.append("paint() changed")
    plain = ["alpha  /tmp/alpha  [frozen]", "  skills     3", "  servers    a, b", "  plugins    * (every plugin)",
             "  profiles   x (default), y", "  options    k on, j unset", "  opted-out  z"]
    if render.card_lines(CARD) != plain:
        out.append("card_lines() = %r" % render.card_lines(CARD))
    painted = ["\033[1malpha\033[0m  /tmp/alpha  \033[33m[frozen]\033[0m", "  \033[2mskills\033[0m     3", "  \033[2mservers\033[0m    a, b",
               "  \033[2mplugins\033[0m    * (every plugin)", "  \033[2mprofiles\033[0m   x (default), y", "  \033[2moptions\033[0m    k on, j unset", "  \033[2mopted-out\033[0m  z"]
    if render.card_lines(CARD, True)[0] != painted[0] or render.card_lines(CARD, True) != painted:
        out.append("card_lines(color=True) title = %r" % render.card_lines(CARD, True)[0])
    full = {"project": "beta", "path": "/tmp/beta", "frozen": False, "skills": ["s1", "*"], "origins": {"s1": ["CORE_SET"]}}
    if render.card_lines(full) != ["beta  /tmp/beta", "  skills     s1 (CORE_SET), * (every global skill)"]:
        out.append("card_lines(full) = %r" % render.card_lines(full))
    return out


want("9 forge/render.py returns what it returned", render_problems(), [])
with patched(render, "YELLOW", "31"):
    caught("a card title painted in the wrong code", render_problems())

for msg in failures:
    print("FAIL", msg)
print("%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
