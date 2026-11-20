# forge/ui

forge's terminal component library. One source of truth, `tokens.json`; everything else draws from it.

| file | what it is |
|---|---|
| `tokens.json` | colour roles per theme (dark, light), the three glyph sets (nerd, unicode, ascii), layout numbers, the contrast rules |
| `tokens.py` | loads and checks `tokens.json` (`problems`), the WCAG contrast helper, `theme(name)` and `glyphs(name)` |
| `context.py` | `Context(theme, glyphs, color, width)` and `detect(env, stream)`: NO_COLOR, tty, COLORTERM, TERM, FORGE_ICONS, FORGE_THEME, COLUMNS |
| `model.py` | `Span(role, text, bold)` and `Line(spans, bg)`: what a component returns |
| `components.py` | meter, step, rail, check_row, group, band, stack, keys, table, header, status_line, agent_block: pure functions, no I/O |
| `screens.py` | home, project_list, selector, agent_events: components composed from plain data |
| `render_ansi.py` | `to_text(lines, ctx)`: plain text with colour `none`, SGR at 16, 256 and truecolor |
| `render_html.py` | `to_html(lines, theme)` and `tokens_css(theme)`: the shared output for the web, the Orca panel and the verdict page |
| `marks.py` | the brand mark, a placeholder until a final logo exists |
| `samples.py` | neutral fixture data shared by the tests and the gallery |
| `gallery.py` | `python3 -m forge.ui.gallery`: the offline HTML page, the plain text blocks and the token CSS |

## The one rule

A component never carries a colour or a glyph. It names a role (`Span("accent", ...)`) or a glyph token
(`ctx.glyph("check_on")`) from `tokens.json`. `tests/test_ui.py` fails a component or screen that holds a non-ASCII string or a
`#rrggbb`. The ellipsis of a cut text is the `ellipsis` glyph token (`Context.ellipsis`).

## Add a role or a glyph

Edit `tokens.json` (a role in both themes; a glyph in all three sets, and in `cell_glyphs` if it is one terminal cell), name it
from a component, then run `python3 tests/test_ui.py`. It checks that every theme and set is complete, that contrast holds, and that
every glyph token is used by a component or screen. A new component state goes into `samples.py` so the width, NO_COLOR and ASCII
checks and the gallery see it; a new screen also gets a golden file (`FORGE_UI_UPDATE=1 python3 tests/test_ui.py`, then read the diff).

## See it

```
python3 -m forge.ui.gallery --out /tmp/forge-ui-gallery.html   # the page: tokens, contrast, glyph sets, components, screens
python3 -m forge.ui.gallery --plain                             # every component and screen as plain text blocks (=== NAME === each)
python3 -m forge.ui.gallery --tokens-css tokens.css             # the custom properties of both themes
```

`FORGE_UI_FONT=/path/to/font.ttf python3 tests/test_ui.py` also checks that the font has every glyph of the nerd and unicode sets.
