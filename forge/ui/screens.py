"""The reference screens, composed from components only: each takes a Context and a plain dict (or list) of data and returns
lines. No rail, colour or glyph is made here; a screen picks components, orders them and says which role a number takes."""
from forge.ui import components as c
from forge.ui import marks
from forge.ui.model import Line, Span


def _count(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def home(ctx, data):
    """`forge` with no arguments. data: product, version, tagline, projects, skills, doctor {passed, warnings, failures},
    sync (a count of changes), plugin (optional: phase, stage, done, total), commands (the key line), bands (attention)."""
    d = data["doctor"]
    total = d["passed"] + d["warnings"] + d["failures"]
    sep = Span("mute", "  " + ctx.glyph("sep") + "  ")
    counts = [Span("mute", "%d passed" % d["passed"]), sep,
              Span("warn" if d["warnings"] else "mute", _count(d["warnings"], "warning")), sep,
              Span("error" if d["failures"] else "mute", _count(d["failures"], "failure"))]
    bar = c.meter(ctx, d["passed"], total)
    doctor = c.fit_first([c.step(ctx, "doctor", bar + [Span("mute", "   ")] + counts, label_width=6)[0],
                          c.step(ctx, "doctor", counts, label_width=6)[0]], ctx.width)
    out = [Line([])] + c.header(ctx, data["product"], data["version"], data["tagline"], marks.mark_lines(ctx)) + [Line([])]
    out += c.rail_start(ctx, [Span("ink", _count(data["projects"], "project"), True), sep, Span("mute", "%d skills installed" % data["skills"])])
    out += c.rail_blank(ctx)
    out.append(doctor)
    out += c.step(ctx, "sync", [Span("mute", "%s would apply" % _count(data["sync"], "change"))], label_width=6)
    plugin = data.get("plugin")
    if plugin:
        row = [Span("mute", "phase "), Span("ink", plugin["phase"], True), sep, Span("mute", plugin["stage"] + "  ")]
        full = c.step(ctx, "fwx", row + c.meter(ctx, plugin["done"], plugin["total"]) + [Span("mute", "  %d/%d" % (plugin["done"], plugin["total"]))], label_width=6)[0]
        short = c.step(ctx, "fwx", row[:3] + [Span("mute", "%d/%d" % (plugin["done"], plugin["total"]))], label_width=6)[0]
        out.append(c.fit_first([full, short], ctx.width))
    out += c.rail_blank(ctx)
    out += c.keys(ctx, [(k, "") for k in data["commands"]])
    return out + c.stack(ctx, data["bands"])


def project_list(ctx, rows, installed=None, more=0):
    """`forge list`. rows: dicts with name, servers, skills and optionally frozen. `installed` is what the meter measures
    skills against (default: the most any row keeps); `more` is how many projects the list does not show."""
    installed = installed or max([r["skills"] for r in rows] + [1])
    name_w = max(8, min(28, ctx.width - 41))
    body = []
    for r in rows:
        frozen = r.get("frozen", False)
        name = c.truncate(ctx, r["name"], name_w)
        if frozen:
            mark = [Span("ink", ctx.glyph("icon_frozen"))]
            label = [Span("faint", name)]
            skills = c.meter(ctx, 0, 1) + [Span("mute", "  %2d" % r["skills"]), Span("ink", "  frozen")]
            servers = [Span("faint", str(r["servers"]))]
        else:
            mark = [Span("accent", ctx.glyph("check_on"))]
            label = [Span("ink", name, True)]
            skills = c.meter(ctx, r["skills"], installed) + [Span("mute", "  %2d" % r["skills"])]
            servers = [Span("mute", str(r["servers"]))]
        body.append([mark, label, servers, skills])
    lines = c.table(ctx, ["", "project", "servers", "skills"], body, [1, name_w, 7, 22])
    out = c.rail_start(ctx, [Span("accent", "forge list "), Span("mute", _count(len(rows) + more, "project"))])
    out += c.rail_blank(ctx)
    out += [c.rail_line(ctx, line.spans)[0] for line in lines]
    if more:
        out += c.rail_line(ctx, [Span("faint", "%s %d more" % (ctx.glyph("more"), more))])
    out += c.rail_blank(ctx)
    out += c.keys(ctx, [("forge list NAME", ctx.glyph("arrow") + " one project in full")])
    return out


def selector(ctx, state):
    """`forge config`. state: project, groups [{name, members, cursor, icon}] (icon: None | refused), servers
    [{name, on, pending}], server_cursor (an index or None), server_icon (None | broken), frozen, bands."""
    frozen = state.get("frozen", False)
    status = "disabled" if frozen else "active"
    out = c.rail_start(ctx, [Span("accent", "forge config "), Span("mute", state["project"])]) + c.rail_blank(ctx)
    out += c.step(ctx, "skills", state="disabled" if frozen else "active")
    for g in state["groups"]:
        icon = {"refused": ("warn", ctx.glyph("icon_refused"))}.get(g.get("icon"))
        out += c.group(ctx, g["name"], g["members"], cursor=g.get("cursor"), icon_on=icon, faint=frozen)
    out += c.rail_blank(ctx)
    out += c.step(ctx, "servers", state=status)
    at = state.get("server_cursor")
    for i, s in enumerate(state["servers"]):
        mode = "pending_off" if s.get("pending") and not s["on"] else "on" if s["on"] else "off"
        if frozen and mode == "on":
            mode = "on_faint"
        right = [Span("error", ctx.glyph("icon_broken"))] if at == i and state.get("server_icon") == "broken" else None
        out += c.check_row(ctx, s["name"], mode, right=right, cursor=at == i)
    out += c.rail_blank(ctx)
    out += c.keys(ctx, [("esc", "close")] if frozen else [("updown", "select"), ("space", "toggle"), ("enter", "apply"), ("esc", "cancel")])
    return out + c.stack(ctx, state["bands"])


def agent_events(ctx, data):
    """fwx's agent lines in a transcript. data: blocks, a list of {title, rows} (rows as agent_block takes them)."""
    out = []
    for i, block in enumerate(data["blocks"]):
        if i:
            out.append(Line([]))
        out += c.agent_block(ctx, block["title"], block["rows"])
    return out
