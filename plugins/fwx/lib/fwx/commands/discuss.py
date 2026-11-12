"""What the discuss opens with, as one JSON: fwx discuss start [--json] [--phase PHASE_DIR]

Read-only: it binds no session and creates nothing. It gives the orchestrator, before its first word to the owner, the
configuration (`config.load`, no other way in), the subprojects, the phase the session is bound to (or `--phase`) with its
last stage and whether this is a re-entry, the open phases, the model of each role the discuss launches (`config.model`),
and what waits for the owner in Linear. The shape is Appendix C of plan/3.1-conversacion-discuss.md.

`bound.reentry` is true only when the phase has a `stage` row and the last one is `discuss`: a new phase has no rows, so
only the return from the session (3.2) makes it true. `waiting` is grouped by `updatedAt` into `today` (under 24 hours),
`week` (under 7 days) and `older`, at most MAX_ITEMS `items` per group and the whole `count`, because the rest must not
pass through the orchestrator's context. Linear is asked for WAIT_S seconds at most; no key, no network, an error or a
timeout is `{"status": "NOT RUN", "reason": ...}`, never a count of 0.

Exit 0 with the framework on, 1 with it off (one line, nothing more), 2 when it cannot run (outside a git repository, an
unusable configuration, a `--phase` that is not a phase of this project, a flag it does not know).
"""
import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone

from fwx import config, linear, state

WAIT_S = 5
MAX_ITEMS = 5
KEY = "LINEAR_API_KEY"
USAGE = "usage: fwx discuss start [--json] [--phase PHASE_DIR]\n"
GROUPS = (("today", timedelta(hours=24)), ("week", timedelta(days=7)), ("older", None))
FRACTION = re.compile(r"\.\d+")


class Refused(Exception):
    """The command cannot run; the message is one line for stderr (exit 2)."""


def _age_group(updated, now):
    """today, week or older for an ISO-8601 `updatedAt`, with or without a fraction of a second."""
    at = datetime.fromisoformat(FRACTION.sub("", updated).replace("Z", "+00:00"))
    age = now - at
    for name, limit in GROUPS:
        if limit is None or age < limit:
            return name


def _waiting_label(issue):
    return next((l for l in linear.WAITING if l in issue["labels"]), "")


def group_waiting(issues, now):
    """The issues grouped by `updatedAt` age: the non-empty groups, most recent first, `count` whole and `items` capped."""
    by = {name: [] for name, _ in GROUPS}
    for i in issues:
        by[_age_group(i["updatedAt"], now)].append(i)
    out = []
    for name, _ in GROUPS:
        found = sorted(by[name], key=lambda i: i["updatedAt"], reverse=True)
        if found:
            out.append({"age": name, "count": len(found),
                        "items": [{"id": i["identifier"], "label": _waiting_label(i), "title": i["title"], "url": i["url"]}
                                  for i in found[:MAX_ITEMS]]})
    return out


def waiting(cfg, now):
    """`{status: ok, count, groups}`, or `{status: NOT RUN, reason}` for anything that kept Linear from answering in WAIT_S."""
    def not_run(why):
        return {"status": "NOT RUN", "reason": why}
    project, key = cfg["project"].get("linear_project"), os.environ.get(KEY)
    if not key:
        return not_run("%s is not set (forge puts it in the environment of a project with the framework)" % KEY)
    if not project:
        return not_run("project.linear_project is not set in .claude/fwx.json")
    box = {}

    def ask():
        try:
            box["issues"] = linear.Client(key, project, cfg, timeout=WAIT_S).waiting()
        except linear.LinearError as e:
            box["error"] = "Linear: %s" % e
        except Exception as e:  # whatever it was, the owner must see NOT RUN, not a count
            box["error"] = "Linear: %s: %s" % (type(e).__name__, e)

    t = threading.Thread(target=ask, daemon=True)
    t.start()
    t.join(WAIT_S)
    if t.is_alive():
        return not_run("Linear did not answer in %s s" % WAIT_S)
    if "error" in box:
        return not_run(box["error"])
    try:
        groups = group_waiting(box["issues"], now)
    except (KeyError, ValueError, TypeError) as e:
        return not_run("Linear answered something this command cannot read (%s: %s)" % (type(e).__name__, e))
    return {"status": "ok", "count": sum(g["count"] for g in groups), "groups": groups}


def _subproject_of(root, phase_dir):
    m = re.match(r"subprojects/([^/]+)/", os.path.relpath(phase_dir, str(root)).replace(os.sep, "/"))
    return m.group(1) if m else None


def _bound(cwd, session, phase):
    """`{subproject, phase_dir, stage, reentry}` of `--phase`, else of the session's bound phase; all empty for neither."""
    root = state.plan_root(cwd)
    subproject = None
    if phase is not None:
        phase = os.path.abspath(phase)
        inside = phase.startswith(str(root) + os.sep) and state.phase_paths(phase)["audit"].is_file()
        if not inside:
            raise Refused("%s is not a phase folder of %s (no phase folder there)" % (phase, root))
        subproject = _subproject_of(root, phase)
    else:
        b = state.read_session(cwd, session)
        if b and b["phase_dir"]:
            full = os.path.join(str(root.parent), b["phase_dir"])
            if os.path.isdir(full):
                phase, subproject = full, b["subproject"]
    if phase is None:
        return {"subproject": None, "phase_dir": None, "stage": None, "reentry": False}
    stage = state.last_stage(phase)
    return {"subproject": subproject, "phase_dir": phase, "stage": stage, "reentry": stage == "discuss"}


def _open_phases(root, cwd=None):
    """The open phases of `root`; in a protected project (documents live on the phase branches) a phase folder with no audit file is what
    is left of one that moved, so it does not count, and with none left those of the worktrees are listed."""
    wts = state.phase_worktrees(cwd)

    def of(r):
        return [{"dir": str(p), "subproject": sub, "stage": state.last_stage(p)}
                for sub in [None] + state.subprojects(r) for p in state.open_phases(state.scope_root(r, sub))
                if not wts or state.phase_paths(p)["audit"].is_file()]
    return of(root) or [x for w in wts for x in of(w)]


def build(cfg, cwd=None, session=None, phase=None, now=None):
    """The JSON of Appendix C as a dict. `now` is there for tests."""
    now = now or datetime.now(timezone.utc)
    root = state.plan_root(cwd)
    proj, m = cfg["project"], lambda role, size: config.model(cfg, role, size)
    return {"framework": True, "config": cfg["_source"], "project": proj["name"], "main_checkout": proj["main_checkout"],
            "ui": bool(proj.get("ui")), "verdict_command": proj.get("verdict_command"),
            "verdict_tool": (cfg.get("paths") or {}).get("verdict"), "factory_ui_bugs": bool(cfg["factory"]["ui_bugs"]),
            "subprojects": state.subprojects(root), "bound": _bound(cwd, session, phase), "open_phases": _open_phases(root, cwd),
            "models": {"researcher": {"small": m("researcher", "small"), "normal": m("researcher", "normal")},
                       "demo": {"normal": m("demo", "normal")}, "decisions": {"small": m("decisions", "small")}},
            "waiting": waiting(cfg, now)}


def text(d):
    b, w = d["bound"], d["waiting"]
    lines = ["project: %s (%s)" % (d["project"], d["main_checkout"]),
             "config: %s" % (d["config"] or "none, defaults"),
             "ui: %s, verdict_command: %s, verdict_tool: %s, factory_ui_bugs: %s"
             % (d["ui"], d["verdict_command"], d["verdict_tool"], d["factory_ui_bugs"]),
             "subprojects: %s" % (", ".join(d["subprojects"]) or "none"),
             "bound: %s (stage %s, subproject %s, reentry %s)" % (b["phase_dir"] or "no phase", b["stage"], b["subproject"], b["reentry"]),
             "open phases: %s" % (", ".join("%s [%s]" % (p["dir"], p["stage"]) for p in d["open_phases"]) or "none"),
             "models: %s" % ", ".join("%s.%s=%s" % (r, z, n) for r, sizes in d["models"].items() for z, n in sizes.items())]
    if w["status"] != "ok":
        lines.append("waiting: NOT RUN (%s)" % w["reason"])
    else:
        lines.append("waiting: %d" % w["count"])
        for g in w["groups"]:
            lines.append("  %s: %d" % (g["age"], g["count"]))
            lines.extend("    %s  [%s]  %s  %s" % (i["id"], i["label"], i["title"], i["url"]) for i in g["items"])
    return "\n".join(lines) + "\n"


def main(argv):
    args = list(argv)
    as_json, phase = False, None
    if not args or args.pop(0) != "start":
        sys.stderr.write(USAGE)
        return 2
    while args:
        a = args.pop(0)
        if a == "--json":
            as_json = True
        elif a == "--phase" and args:
            phase = args.pop(0)
        elif a.startswith("--phase="):
            phase = a[len("--phase="):]
        else:
            sys.stderr.write("fwx discuss: unknown argument %r\n%s" % (a, USAGE))
            return 2
    try:
        cfg = config.load()
        if not cfg["framework"]:
            sys.stdout.write("fwx discuss: the framework is off for this project (framework: false in .claude/fwx.json)\n")
            return 1
        d = build(cfg, session=state.session_id(), phase=phase)
    except (config.ConfigError, state.StateError, Refused) as e:
        sys.stderr.write("fwx discuss: %s\n" % e)
        return 2
    sys.stdout.write(json.dumps(d, indent=2) + "\n" if as_json else text(d))
    return 0
