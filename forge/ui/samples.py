"""Neutral sample data for the component library: what tests/test_ui.py renders and the gallery shows. Names are fixtures
(projects alpha, beta, ...; sets CORE_SET, STYLE_SET); nothing here is a real project or number of this machine."""
from forge.ui import components as c
from forge.ui import marks, screens
from forge.ui.model import Line, Span

TAGLINE = "One source of truth for the agent setup of every project on your machine."
BANDS = {
    "refused": ("refused", "review is in CORE_SET: cannot go off alone", "a whole set  b keep two"),
    "broken": ("broken", "neon cannot be switched on: its secret is missing", "enter show how"),
    "frozen": ("frozen", "alpha is frozen: it writes nothing for this project", "esc close"),
    "stale": ("stale", "config/forge.json changed; nothing was written", "r reload"),
    "done": ("done", "sync applied: 14 changes written", ""),
}
LONG_BAND = ("refused", "this message is much longer than any terminal this library draws for, so it must be cut", "an action")
STATUS = dict(profile="@design", skills=16, servers=3, phase="10 design", done=4, total=10)
STATUS_WIDTHS = (30, 36, 40, 60, 64, 80, 120)


def wave_start(ctx):
    """The agent lines of a wave that has just started (state text is built from the context's glyphs)."""
    return {"title": "wave 2 of 3  %s  4 agents starting" % ctx.glyph("sep"), "rows": [
        ("executor", "task 3", "add the stage table", ("starting", "starting")),
        ("planner", "task 4", "render the home screen", ("starting", "starting")),
        ("reviewer", "part 1", "diff base..head", ("starting", "starting")),
        ("researcher", "", "how other tools print a header", ("starting", "starting"))]}


def wave_end(ctx):
    """The same wave a few minutes later: two done, one with findings, one running."""
    done, warn = ctx.glyph("icon_done"), ctx.glyph("icon_refused")
    return {"title": "wave 2 of 3  %s  3 of 4 done" % ctx.glyph("sep"), "rows": [
        ("executor", "task 3", "add the stage table", ("done", done + " 4m 12s  3 files")),
        ("planner", "task 4", "render the home screen", ("done", done + " 6m 02s  5 files")),
        ("reviewer", "part 1", "diff base..head", ("findings", warn + " 2 findings")),
        ("researcher", "", "how other tools print a header", ("running", "running 3m 40s"))]}


PROJECTS_HIDDEN = 8  # projects the list does not show (its "more" row); the home screen counts them
SKILLS_INSTALLED = 50  # what the list's meters measure against; the home screen says it
HOME = {"product": "forge", "version": "v0.1.0", "tagline": TAGLINE, "projects": 0, "skills": SKILLS_INSTALLED,
        "doctor": {"passed": 41, "warnings": 3, "failures": 1}, "sync": 14,
        "plugin": {"phase": "10 design", "stage": "review", "done": 4, "total": 10},
        "commands": ["forge list", "forge doctor", "forge sync"],
        "bands": [("broken", "hindsight: 2 checks failed", "forge doctor"), ("refused", "sync: 14 changes would apply", "forge sync --apply")]}
PROJECTS = [{"name": "alpha", "servers": 10, "skills": 31}, {"name": "beta", "servers": 5, "skills": 20},
            {"name": "gamma", "servers": 4, "skills": 18}, {"name": "delta", "servers": 3, "skills": 16},
            {"name": "epsilon", "servers": 4, "skills": 15}, {"name": "zeta", "servers": 4, "skills": 14},
            {"name": "eta", "servers": 0, "skills": 5, "frozen": True}]
HOME["projects"] = len(PROJECTS) + PROJECTS_HIDDEN  # the same data feeds the home screen and the list
SELECT_BASE = {"project": "alpha", "frozen": False, "server_cursor": None, "server_icon": None, "bands": [],
               "groups": [{"name": "CORE_SET", "members": ["lint", "review", "docs-style"], "cursor": None, "icon": None},
                          {"name": "STYLE_SET", "members": ["format", "naming"], "cursor": None, "icon": None}],
               "servers": [{"name": "search", "on": True}, {"name": "docs", "on": True}, {"name": "neon", "on": False}]}


def select(**kw):
    state = dict(SELECT_BASE, groups=[dict(g) for g in SELECT_BASE["groups"]])
    state.update(kw)
    return state


def _refused():
    s = select(bands=[BANDS["refused"]])
    s["groups"][0].update(cursor=1, icon="refused")
    return s


SELECTORS = {
    "refused": _refused(),
    "broken": select(server_cursor=2, server_icon="broken", bands=[BANDS["broken"]]),
    "frozen": select(frozen=True, bands=[BANDS["frozen"]]),
    "stale": select(bands=[BANDS["stale"]]),
    "pending": select(servers=[{"name": "search", "on": True}, {"name": "docs", "on": False, "pending": True}, {"name": "neon", "on": False}]),
    "several": dict(_refused(), bands=[BANDS["stale"], BANDS["refused"], BANDS["broken"]]),
}


def _line(spans):
    return [Line(spans)]


def component_cases(ctx):
    """(component, state, lines) for each component in each of its states, drawn with `ctx`."""
    out = []
    for done, total, label in ((0, 10, "empty"), (1, 20, "one cell at least"), (4, 10, "four of ten"), (10, 10, "full")):
        out.append(("meter", "ramp, " + label, _line(c.meter(ctx, done, total))))
    out.append(("meter", "flat, 3 of 4 cells", _line(c.meter(ctx, 3, 4, cells=4, mode="flat"))))
    out.append(("step", "active", c.step(ctx, "skills", "3 of 3")))
    out.append(("step", "disabled", c.step(ctx, "skills", state="disabled")))
    body = [Span("body", "text on the rail")]
    out.append(("rail_start", "", c.rail_start(ctx, body)))
    out.append(("rail_blank", "", c.rail_blank(ctx)))
    out.append(("rail_line", "plain", c.rail_line(ctx, body)))
    out.append(("rail_line", "with a right part", c.rail_line(ctx, body, right=[Span("mute", "right")])))
    out.append(("rail_line", "cursor", c.rail_line(ctx, body, right=[Span("mute", "right")], cursor=True)))
    out.append(("rail_end", "", c.rail_end(ctx, body)))
    for state in ("on", "off", "pending_off", "on_faint"):
        out.append(("check_row", state, c.check_row(ctx, "search", state)))
    out.append(("check_row", "cursor with an icon", c.check_row(ctx, "neon", "off", right=[Span("error", ctx.glyph("icon_broken"))], cursor=True)))
    members = ["lint", "review", "docs-style"]
    out.append(("group", "no cursor", c.group(ctx, "CORE_SET", members)))
    out.append(("group", "cursor member with an icon", c.group(ctx, "CORE_SET", members, cursor=1, icon_on=("warn", ctx.glyph("icon_refused")))))
    out.append(("group", "faint (frozen)", c.group(ctx, "CORE_SET", members, faint=True)))
    for kind, msg, action in BANDS.values():
        out.append(("band", kind, c.band(ctx, kind, msg, action)))
    out.append(("band", "too long: the message is cut", c.band(ctx, *LONG_BAND)))
    out.append(("stack", "two bands", c.stack(ctx, [BANDS["refused"], BANDS["broken"]])))
    out.append(("keys", "", c.keys(ctx, [("updown", "select"), ("space", "toggle"), ("enter", "apply"), ("esc", "cancel")])))
    rows = [[[Span("ink", "alpha", True)], [Span("mute", "10")]], [[Span("faint", "beta")], [Span("mute", "5")]]]
    out.append(("table", "left and right aligned", c.table(ctx, ["project", "servers"], rows, [10, 7], ["l", "r"])))
    out.append(("header", "", c.header(ctx, "forge", "v0.1.0", TAGLINE, marks.mark_lines(ctx))))
    out.append(("status_line", "at the context width", c.status_line(ctx, **STATUS)))
    out.append(("status_line", "no phase", c.status_line(ctx, "@design", 16, 3)))
    out.append(("agent_block", "starting", c.agent_block(ctx, wave_start(ctx)["title"], wave_start(ctx)["rows"])))
    out.append(("agent_block", "finishing", c.agent_block(ctx, wave_end(ctx)["title"], wave_end(ctx)["rows"])))
    kinds = [(a, "", "", ("running", "running")) for a in ("executor", "planner", "reviewer", "researcher")]
    out.append(("agent_block", "the four kinds", c.agent_block(ctx, "one dot shape per kind", kinds)))
    return out


def screen_cases(ctx):
    """(screen, state, lines) for the reference screens."""
    out = [("home", "full", screens.home(ctx, HOME)),
           ("home", "minimal", screens.home(ctx, dict(HOME, plugin=None, bands=[])))]
    out.append(("project_list", "", screens.project_list(ctx, PROJECTS, installed=SKILLS_INSTALLED, more=PROJECTS_HIDDEN)))
    for name, state in SELECTORS.items():
        out.append(("selector", name, screens.selector(ctx, state)))
    out.append(("agent_events", "", screens.agent_events(ctx, {"blocks": [wave_start(ctx), wave_end(ctx)]})))
    return out


def status_line_cases(ctx):
    """(width, lines): the status line drawn at each of STATUS_WIDTHS, where it drops its parts in order."""
    return [(w, c.status_line(ctx, width=w, **STATUS)) for w in STATUS_WIDTHS]
