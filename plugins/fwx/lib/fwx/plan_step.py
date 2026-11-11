"""The three steps of the plan block (pre-mortem, planner, post-mortem) as the scripts around the agents see them:
which agent and model run a step, the brief the agent follows, and what a finished step says about itself.

`head(dir, step)` is `{agent, model, round}`, all a skill needs to launch the agent; `brief(dir, step, ...)` is the text the
launched agent runs as its first action, so the brief never passes through the orchestrator's context; `status(dir, step, ...)`
is `{status, reason, phase_dir}` after the agent returned. A critique round is counted from the `stage` rows of the phase's
audit file (`critique_round`), not from lib/fwx/core/rounds.py, which counts implement-verify rounds.

`dir` is a phase folder in any checkout; every path in a brief and in a status is that folder's place in the main checkout
(`state.plan_root`), so a launch from a worktree names the files the agents write to. The paths a brief lists for every agent
of the phase (`_common`) are kept apart from the ones of the step (`_step_files`): the base-context file later takes over the
first group.

Missing what a step needs raises Missing (the command's exit 1); what cannot be read at all (not a folder, no usable
configuration) raises CannotRun (exit 2). Imports the standard library, config, state and plan.
"""
import json
import os
import re

from fwx import config, plan, state

STEPS = ("premortem", "plan", "postmortem")
AGENT = {"premortem": "fwx:pre-mortem", "plan": "fwx:planner", "postmortem": "fwx:post-mortem"}
ROLE = {"premortem": "pre-mortem", "plan": "planner", "postmortem": "post-mortem"}
STAGE = {"premortem": "premortem", "plan": "planning", "postmortem": "postmortem"}  # the stage a step runs in
NEEDS = "Needs from the owner before executing"
REPLAN_UNATTENDED = "Address every blocker in postmortem.md and send every warning to `later` with its why."
PREMORTEM_UNATTENDED = "Address the objections in premortem.md."
_ACCEPTED = re.compile(r"(post|pre)mortem r\d+")
_DIFF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./~^@-]*\.\.\.?[A-Za-z0-9_][A-Za-z0-9_./~^@-]*\Z")


class Missing(Exception):
    """The step cannot start or be judged because something it needs is not there or does not validate."""


class CannotRun(Exception):
    """Nothing can be said about the folder: it is not a folder, or the configuration cannot be used."""


# ---------------------------------------------------------------- the folder and the rounds

def resolve(dir):
    """The phase folder `dir` names, at its place in the main checkout: the part of the path after the last `.fwx` folder is
    laid under `state.plan_root`. A folder with no `.fwx` in its path is returned as it is (made absolute)."""
    d = os.path.realpath(str(dir))
    if not os.path.isdir(d):
        raise CannotRun("%s is not a folder" % dir)
    parts = d.split(os.sep)
    if state.PLAN_DIR not in parts:
        return d
    i = len(parts) - 1 - parts[::-1].index(state.PLAN_DIR)
    try:
        moved = os.path.join(str(state.plan_root(d)), *parts[i + 1:])
    except config.ConfigError as e:
        raise CannotRun(str(e))
    if not os.path.isdir(moved):
        raise CannotRun("%s is not a folder (the place of %s in the main checkout)" % (moved, d))
    return moved


def _destination(row):
    words = row.get("detail", "").split(None, 1)
    return words[0] if words else ""


def critique_round(dir, stage):
    """The `stage` rows of the folder's audit file whose destination is `stage`, since the last one whose destination is
    `discuss` (a return to the discuss starts the counting again). 0 when the phase has not entered that stage."""
    n = 0
    for row in state.read_rows(state.phase_paths(dir)["audit"]):
        if row.get("kind") != "stage":
            continue
        if _destination(row) == "discuss":
            n = 0
        elif _destination(row) == stage:
            n += 1
    return n


def _config(d):
    try:
        return config.load(d)
    except config.ConfigError as e:
        raise CannotRun(str(e))


def _cap(cfg):
    v = cfg["critique_rounds_unattended"]
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise CannotRun("critique_rounds_unattended is %r in the configuration: it must be a positive integer" % (v,))
    return v


# ---------------------------------------------------------------- what a step needs

def _load(loader, path, label):
    try:
        return loader(path, label)
    except plan.PlanError as e:
        raise Missing(str(e))


def _facts(d, step):
    """Everything a head and a brief need, after checking what the step needs: Missing for a context.md that is not there, a
    `plan` with no valid premortem.md (unless the phase never went through the premortem stage: the mini plan of a small
    issue, which has none), a `postmortem` with no valid plan.md, a premortem.md that does not validate where it is read,
    and a phase not yet in the stage of the step."""
    paths = state.phase_paths(d)
    if not paths["context"].is_file():
        raise Missing("%s is missing: the step needs the discuss's context" % paths["context"])
    premortem = None
    if paths["premortem"].exists():
        premortem = _load(plan.load_premortem, paths["premortem"], "premortem.md")
    elif step == "plan" and critique_round(d, "premortem"):
        raise Missing("%s is missing: the phase went through the premortem stage, and the plan needs its result" % paths["premortem"])
    if step == "postmortem" and not paths["plan"].exists():
        raise Missing("%s is missing: nothing to critique" % paths["plan"])
    if step == "postmortem":
        _load(plan.load_plan, paths["plan"], "plan.md")
    stage = STAGE[step]
    n = critique_round(d, stage)
    if n < 1:
        raise Missing("the phase has no `%s` stage row since its last discuss: run `fwx stage %s %s` first" % (stage, d, stage))
    size = "normal" if step == "premortem" else (premortem["size_tag"] if premortem else "small")
    cfg = _config(d)
    try:
        model = config.model(cfg, ROLE[step], size)
    except config.ConfigError as e:
        raise CannotRun(str(e))
    return {"dir": d, "paths": paths, "premortem": premortem, "round": n, "size": size, "model": model, "cfg": cfg}


def head(dir, step):
    """{agent, model, round}: what a skill needs to launch the step's agent."""
    f = _facts(resolve(dir), _step(step))
    return {"agent": AGENT[step], "model": f["model"], "round": f["round"]}


def _step(step):
    if step not in STEPS:
        raise CannotRun("step %r is not one of %s" % (step, ", ".join(STEPS)))
    return step


# ---------------------------------------------------------------- the brief

def _exists(p):
    return os.path.exists(str(p))


def _common(d, paths):
    """What every agent of the phase is pointed at, as absolute paths that exist."""
    root = state.plan_root(d)
    found = [("PROJECT.md", root / "PROJECT.md"), ("durable/", root / "durable"), ("context.md", paths["context"]),
             ("decisions.tsv", paths["decisions"]), ("research/", paths["research"]), ("demo/", paths["demo"]),
             (".claude/fwx.json", os.path.join(config.main_checkout(d), config.FILE))]
    return ["- %s: %s" % (name, p) for name, p in found if _exists(p)]


def _plans(d):
    """The phase's plan.md and the plan.md of each subphase that has one."""
    return [p for p in [state.phase_paths(d)["plan"]] + [state.phase_paths(s)["plan"] for s in state.subphases(d)] if _exists(p)]


def _step_files(d, step, paths):
    """What the step reads besides the common files: the earlier results."""
    out = []
    if step in ("plan", "postmortem") and _exists(paths["premortem"]):
        out.append("- premortem.md: %s" % paths["premortem"])
    if step == "postmortem":
        out += ["- %s: %s" % (os.path.relpath(p, d), p) for p in _plans(d)]
    elif step == "plan" and _exists(paths["postmortem"]):
        out.append("- postmortem.md (the last round): %s" % paths["postmortem"])
    if step == "postmortem" and _exists(paths["postmortem"]):
        out.append("- postmortem.md (the previous round, to be replaced): %s" % paths["postmortem"])
    if step == "plan":  # the planner has no plugin-root variable: the plan format comes with its brief (3.3 U4)
        out.append("- plan.md template: %s" % (state._TEMPLATES / "phase" / "plan.md"))
    return out


def _decisions(paths):
    """The count by support of the decisions in force, and the ids the critiques attack."""
    rows = state.read_rows(paths["decisions"])
    replaced = {r.get("supersedes") for r in rows if r.get("supersedes")}
    rows = [r for r in rows if r.get("id") not in replaced]
    counts = {s: sum(1 for r in rows if r.get("support") == s) for s in state.SUPPORT}
    lines = ["decisions.tsv, %d decisions in force: %s." % (len(rows), ", ".join("%s %d" % (s, counts[s]) for s in state.SUPPORT))]
    for s in ("agent-assumption", "unexamined"):
        ids = [r.get("id", "?") for r in rows if r.get("support") == s]
        if ids:
            lines.append("%s: %s." % (s, ", ".join(ids)))
    return lines, rows


def _check_output(d):
    r = plan.check_phase(d)
    count = "checked %d plan file(s): %d tasks, %d waves, %d parts; %d errors, %d warnings" % (
        r["plans"], r["tasks"], r["waves"], r["parts"], len(r["errors"]), len(r["warnings"]))
    return r, ["error: " + e for e in r["errors"]] + ["warning: " + w for w in r["warnings"]] + [count]


def _variants(f, step, unattended, rows):
    """The lines that depend on how the step is run and on what the earlier rounds left."""
    d, paths, out = f["dir"], f["paths"], []
    if step == "plan" and _exists(paths["postmortem"]):
        if unattended:
            out.append(REPLAN_UNATTENDED)
        else:
            ids = [r["id"] for r in rows if _ACCEPTED.match(r.get("source", "")) and r.get("id")]
            if ids:
                out.append("The owner accepted the objections behind these decisions (source `postmortem r<N>` or `premortem r<N>`): "
                           + ", ".join(ids) + ". The plan answers each of them.")
        if _exists(paths["plan"]):
            out.append("The plan being replaced: " + _check_output(d)[1][-1].replace("checked ", "", 1) + ".")
    elif step == "plan" and unattended and f["premortem"] and f["premortem"]["verdict"] == "objections":
        out.append(PREMORTEM_UNATTENDED)
    return out


def brief(dir, step, unattended=False, diff=None):
    """The brief of a step as text. Missing / CannotRun as `_facts` says; `diff` (`BASE..BRANCH`) belongs to the post-mortem
    of a job that came back."""
    d = resolve(dir)
    step = _step(step)
    if diff is not None and (step != "postmortem" or not _DIFF.match(diff) or diff.startswith("-")):
        raise CannotRun("--diff takes BASE..BRANCH and belongs to the postmortem step")
    f = _facts(d, step)
    paths = f["paths"]
    summary, rows = _decisions(paths)
    target = paths[step]
    out = ["# Brief: %s, round %d, %s" % (ROLE[step], f["round"], "unattended" if unattended else "supervised"),
           "",
           "This is your brief: it is your first action and everything you are asked. The phase folder is %s." % d,
           "Supervised: the owner reads what you return." if not unattended else
           "Unattended: nobody can be asked; decide, and say what you assumed.",
           "", "## Read"] + _common(d, paths) + _step_files(d, step, paths) + [""] + summary
    extra = _variants(f, step, unattended, rows)
    if step == "postmortem":
        r, lines = _check_output(d)
        extra.append("`fwx plan check` already ran; do not repeat what it checked:\n" + "\n".join("    " + l for l in lines))
        if diff:
            extra.append("A job came back: review structurally what is left of the plan against the work. Run `git diff %s` in %s."
                         % (diff, config.main_checkout(d)))
    if extra:
        out += ["", "## This round"] + extra
    out += ["", "## Write", "%s%s" % (target, ", with `\"round\": %d` in its frontmatter" % f["round"] if step != "plan" else "")]
    out += ["", "## Return",
            "The path of `plan.md` and the last line of `fwx plan check`, in under 100 words." if step == "plan" else
            "Your verdict and the path you wrote, in under 100 words."]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- the status

def _needs_none(path):
    text = plan.section(path, NEEDS)
    return text is not None and text.strip().rstrip(".").strip().lower() == "none"


def _why(path):
    """The sentence under `## Verdict` on one line, or "" when the file has none: the reason a critique gave."""
    return " ".join((plan.section(path, "Verdict") or "").split())


def _verdict(d, step, unattended, cfg):
    """(status, reason) of a finished step; Missing means the file is not usable."""
    paths = state.phase_paths(d)
    path = paths[step]
    if not path.exists():
        raise Missing("%s.md is missing" % step)
    if step == "plan":
        r = plan.check_phase(d)
        if r["errors"]:
            more = " (and %d more)" % (len(r["errors"]) - 1) if len(r["errors"]) > 1 else ""
            return "failed", "errors: %s%s" % (r["errors"][0], more)
        return "done", "ok: %d plan file(s), %d tasks, %d warnings" % (r["plans"], r["tasks"], len(r["warnings"]))
    data = _load(plan.load_premortem if step == "premortem" else plan.load_postmortem, path, "%s.md" % step)
    want = critique_round(d, STAGE[step])
    if data["round"] != want:
        raise Missing("%s.md: round: %d in the file, but this is round %d (a dead agent or an old file)" % (step, data["round"], want))
    verdict = data["verdict"]
    if verdict == "back-to-discuss":
        why = _why(path)
        if unattended:
            return "needs-owner", "back-to-discuss: what was decided has to be reopened with the owner" + (" (%s)" % why if why else "")
        return "back-to-discuss", "back-to-discuss: " + why if why else "back-to-discuss"
    if verdict == "ok":
        if step == "postmortem" and unattended and not _needs_none(path):
            return "needs-owner", "ok: but `## %s` does not say None" % NEEDS
        return "done", "ok"
    if step == "premortem":
        return "done", "objections" + ("; the planner addresses them" if unattended else "")
    if unattended and data["round"] >= _cap(cfg):
        return "needs-owner", "objections: round %d of the %d an unattended run allows" % (data["round"], _cap(cfg))
    return "done", "objections"


def status(dir, step, unattended=False):
    """{status, reason, phase_dir} of a finished step (the table is in the plan's Appendix C). The first word of `reason` is
    the verdict. A file that is missing, does not validate or has a `round` other than the one counted is `failed`, never
    'no findings'."""
    d = resolve(dir)
    step = _step(step)
    cfg = _config(d)
    try:
        s, reason = _verdict(d, step, unattended, cfg)
    except Missing as e:
        s, reason = "failed", str(e)
    return {"status": s, "reason": reason, "phase_dir": d}


def status_line(result):
    return json.dumps(result, ensure_ascii=False)
