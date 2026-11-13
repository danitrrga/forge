"""`fwx wave new`: validate a part and give `execute` its `args` (3.4 U2; the shape is C.3 of the plan).

`prepare(cwd, ...)` works on the integration checkout `cwd` is in (the session's worktree, on the phase branch) and returns
the args dict; it raises WaveError (exit 2) for anything that must stop the run before it starts, and RedBase (exit 1) when
the base fails its own checks. It writes no audit row; the only files are the briefs (below), written last.

The part is `part_dir`: a phase folder, a subphase folder (it uses the `context.md` and `decisions.tsv` of the phase that
holds it) or a job folder. Its `plan.md` and `postmortem.md` must load (`plan.load_plan`, `plan.load_postmortem`). Refused with
exit 2, in this order of cost: a plan that does not load; a task file that git ignores (the executor could not commit it); the
requested branch is a default branch, or is not the one the checkout is on; the checkout holds uncommitted work; the effective
`worktree.baseRef` is not `head`; the project has no checks. Why the baseRef: without it a workflow agent's worktree is made from
`origin/<default branch>`, not from the phase branch, and nothing says so (research/execute-measures.md, measured).
The effective value is the last one set of: the user's settings (`$CLAUDE_CONFIG_DIR` or `~/.claude`), the main checkout's
`.claude/settings.json` and `.claude/settings.local.json` (read from a linked worktree too: Claude Code does), and the
checkout's own two.

Then, in a linked worktree, `project.worktree_setup` runs (execute/worktree_setup.py; a no-op when it already ran against the same
dependency files): the phase worktree comes from a plain `git worktree add` and has none of the project's installed dependencies,
so the base and every later check would be red for a reason that has nothing to do with the work. A setup that fails stops the run
with exit 2 before the base is run.

Then the base is run: the effective recipe (`evidence.plan_checks`) in the checkout, unless the part's audit rows already
holds a green `evidence` row for the base sha. A red check is RedBase: needs-owner, no round spent.

What else it works out: the run id `<part>-<sha7>-<n>` (n counts the runs of that base already made in the git common
dir); the tasks already done (a commit reachable from the phase branch whose trailer says `Fwx-Task: <part>/<task>`); each
wave's `serial` and `plan_failures` for tasks of one wave that write the same path or one inside the other (plan._clashes,
which `load_plan` leaves to its caller); and a model for every role, from the configuration.

`--from gate` (3.4 align) is the way back into the checks once every task is on the phase branch: the tree's n_C7F, where the
owner fixed what kept the gate from running, loops to n_C7 and then to the review. Refused (exit 2) unless every task is done,
and with `--fix` or `--revert`. It launches nothing, so it writes no brief and does not run the base (the gate judges the head,
red or not), and `base` is where the part's first run started (the oldest `Fwx-Run: <part>-<sha7>-<n>` of the phase branch), not
the head: the review and the trusted-edit report diff from it. The run id continues that numbering. The result has `from: "gate"`.

The briefs (3.4 U9, execute/brief.py): one file per task in `<git-common-dir>/fwx/runs/<run>/briefs/<task>.md`, its path in
`waves[].tasks[].brief`. They hold no base sha (a later wave starts from a later head: the workflow names it in the prompt) and
no path for a report: an agent writes in the folder `fwx scratch new` makes in its own worktree. They are built, and checked, before the base is run: a field that
is empty stops the run with exit 2, naming task and field, before any file exists; the files are written once the base is green,
so a refusal and a red base leave nothing behind. With `--fix` the one brief is the fixer's (`fix.brief`) and the tasks of the
plan get none; with `--revert` nothing is launched, so there is none. `--fix` and `--control-findings` are lists of findings in the
shape of plan C.5 (execute/brief.py `finding_problems`), or the rows of a walk's fix.json (`normalize`), `--revert` a list of finding ids; anything else is refused.

Imports the standard library, fwx.plan, plan_step, state, config, core.evidence, core.rounds, core.verify and execute.base, execute.brief and execute.worktree_setup.
"""
import json
import os
import re
import shlex

from fwx import config, plan, plan_step, state
from fwx.core import evidence, rounds, verify
from fwx.execute import brief, worktree_setup
from fwx.execute.base import WaveError, git, linked, out, toplevel

PLANES = ("session", "factory")
STARTS = ("gate",)
_PHASE_NAME = re.compile(r"\d+(\.\d+)*-.+\Z")


class RedBase(Exception):
    """The base fails its own checks. `.status` is what the command prints: {status, reason, phase_dir, rounds}."""

    def __init__(self, status, shown):
        super().__init__(status["reason"])
        self.status, self.shown = status, shown


def _is_subphase(part):
    parent = os.path.dirname(part)
    return bool(_PHASE_NAME.match(os.path.basename(parent))) and part in [str(p) for p in state.subphases(parent)]


def _config(top):
    return config.load(top)


def _setup(top, cfg, say):
    """`project.worktree_setup` in the phase worktree, before any check runs there: a worktree made by `git worktree add` has none
    of the project's installed dependencies, so the base would be red for a reason that has nothing to do with the work. The main
    checkout is the owner's own, with its dependencies, and is left alone. A failure stops the run (exit 2), before the base."""
    commands = cfg["project"]["worktree_setup"]
    if not commands or not linked(top):
        return
    try:
        say(worktree_setup.summary(worktree_setup.run(top, commands)))
    except worktree_setup.SetupFailed as e:
        raise WaveError(str(e))


def _load(loader, path, label):
    try:
        return loader(path, label)
    except plan.PlanError as e:
        raise WaveError(str(e))


def _ignored(top, tasks):
    """The task files git ignores in `top` (a tracked file is not ignored: it can be committed)."""
    files = sorted({plan._norm(f) for t in tasks for f in t["files"]})
    r = git(top, "check-ignore", "-z", "--stdin", input="\0".join(files))
    if r.returncode not in (0, 1):
        raise WaveError("git check-ignore failed in %s: %s" % (top, r.stderr.strip()))
    return [f for f in r.stdout.split("\0") if f]


def _defaults(top, cfg):
    """The names of the default branch: the configuration's, the remote's, else main and master."""
    names = set()
    if cfg["project"].get("default_branch"):
        names.add(cfg["project"]["default_branch"])
    ref = out(top, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    if ref:
        names.add(ref.split("/", 1)[-1])
    return names or {"main", "master"}


def _settings(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise WaveError("%s cannot be read as settings (%s): it decides where the agents' worktrees start" % (path, e))
    return data if isinstance(data, dict) else {}


def _base_ref(top, main, environ):
    """The effective `worktree.baseRef`, or None when no layer sets it."""
    conf = environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    layers = [os.path.join(conf, "settings.json"),
              os.path.join(main, ".claude", "settings.json"), os.path.join(main, ".claude", "settings.local.json")]
    if os.path.realpath(top) != os.path.realpath(main):
        layers += [os.path.join(top, ".claude", "settings.json"), os.path.join(top, ".claude", "settings.local.json")]
    value = None
    for path in layers:
        tree = _settings(path).get("worktree")
        if isinstance(tree, dict) and "baseRef" in tree:
            value = tree["baseRef"]
    return value


def _done(top, branch, part_name, tasks):
    r = git(top, "log", "refs/heads/" + branch, "--format=%(trailers:key=Fwx-Task,valueonly)")
    if r.returncode:
        raise WaveError("git log %s failed: %s" % (branch, r.stderr.strip()))
    found = {line.strip() for line in r.stdout.splitlines()}
    return [t["id"] for t in tasks if "%s/%s" % (part_name, t["id"]) in found]


def _part_base(top, branch, part_name):
    """Where the part's first run started: the oldest base among the `Fwx-Run: <part>-<sha7>-<n>` trailers of `branch`."""
    ref = "refs/heads/" + branch
    r = git(top, "log", ref, "--format=%(trailers:key=Fwx-Run,valueonly,unfold)")
    if r.returncode:
        raise WaveError("git log %s failed: %s" % (branch, r.stderr.strip()))
    mine = re.compile(re.escape(part_name) + r"-([0-9a-f]{7})-\d+\Z")
    bases = {}
    for line in r.stdout.splitlines():
        m = mine.match(line.strip())
        sha = m and out(top, "rev-parse", "--verify", "--quiet", m.group(1) + "^{commit}")
        if sha and git(top, "merge-base", "--is-ancestor", sha, ref).returncode == 0:
            bases[sha] = int(out(top, "rev-list", "--count", sha) or 0)
    if not bases:
        raise WaveError("--from gate: no commit of %s carries `Fwx-Run: %s-<sha>-<n>`, so there is no telling where the part's work started"
                        % (branch, part_name))
    return min(bases, key=bases.get)


def _run_id(top, part_name, base):
    common = out(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    prefix = "%s-%s-" % (part_name, base[:7])
    runs = os.path.join(common or "", "fwx", "runs")
    made = [d for d in os.listdir(runs) if d.startswith(prefix)] if os.path.isdir(runs) else []
    return "%s%d" % (prefix, len(made) + 1)


def _findings(path, flag):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise WaveError("%s %s cannot be read as a JSON list of findings (%s)" % (flag, path, e))
    if not isinstance(data, list):
        raise WaveError("%s %s is not a JSON list of findings" % (flag, path))
    problems = brief.finding_problems(data)
    if problems:
        raise WaveError("%s %s: %s" % (flag, path, "; ".join(problems)))
    return brief.normalize(data)


def _revert_ids(ids):
    """The finding ids `--revert` names, or None; an empty list or an id that cannot be a trailer value is refused."""
    if ids is None:
        return None
    bad = [i for i in ids if not brief.ID.match(i)]
    if not ids or bad:
        raise WaveError("--revert %s: %s" % (",".join(ids), "no finding named" if not ids else "%s cannot be a finding id" % ", ".join(map(repr, bad))))
    return ids


def _briefs(data, ctx, fix, size, quick, launching):
    """{task id or brief.FIX: (facts, text)} for what the run launches, or {} when it launches no executor (`--revert`). Every
    task of the part is checked, so one with an empty field stops the run before any file is written (WaveError, exit 2)."""
    found, problems = {}, []
    if not launching:
        return found
    if fix:
        facts = brief.fix_facts(fix["findings"], fix["source"], data["tasks"], quick, size, ctx)
        found[brief.FIX] = facts
    else:
        for t in data["tasks"]:
            if not brief.ID.match(t["id"]):
                problems.append("task %s: the id cannot name a file (letters, digits, `.`, `_` and `-`, starting with a letter or digit)" % t["id"])
                continue
            found[t["id"]] = brief.task_facts(t, [x for x in data["tasks"] if x["wave"] == t["wave"]], ctx)
    for facts in found.values():
        problems += brief.missing(facts)
    if problems:
        raise WaveError("a brief with an empty field is not launched:\n  " + "\n  ".join(problems))
    return {k: (facts, brief.render(facts)) for k, facts in found.items()}


def _model(cfg, role, size):
    try:
        return config.model(cfg, role, size)
    except config.ConfigError as e:
        raise WaveError(str(e))


def _base_is_green(top, base, recipe, folders, say):
    """None when the base passes (or a green evidence row of the part says so), else the red results."""
    for d in folders:
        for row in state.read_rows(state.phase_paths(d)["audit"]):
            if row.get("kind") == "evidence" and row.get("sha") == base and row.get("rc", "").strip() == "0":
                say("base %s: a green evidence row stands in for a run" % base[:7])
                return None
    results = [verify.run_check(c, top) for c in recipe]
    return [r for r in results if r["rc"] != 0] or None


def _write(made, folder, claim):
    """The briefs of a run: what `prepare` writes, once everything else has passed. With `claim` the run's folder is made even
    with no brief (a `--from gate` run launches none), so that the next run of the base gets the next number."""
    if not made and not claim:
        return
    try:
        os.makedirs(folder, exist_ok=True)
        for facts, text in made.values():
            brief.put(facts["brief"], text)
    except OSError as e:
        raise WaveError("cannot write the briefs of the run in %s: %s" % (folder, e))


def prepare(cwd, part_dir, plane, branch, unattended=False, security=False, fix=None, revert=None, control_findings=None,
            start=None, environ=None, say=lambda line: None):
    environ = os.environ if environ is None else environ
    if plane not in PLANES:
        raise WaveError("--plane is %r, not one of %s" % (plane, ", ".join(PLANES)))
    if start is not None and start not in STARTS:
        raise WaveError("--from is %r, not one of %s" % (start, ", ".join(STARTS)))
    if start and (fix or revert is not None):
        raise WaveError("--from %s runs no fixer and reverts nothing: it cannot go with --fix or --revert" % start)
    top = toplevel(cwd)
    if top is None:
        raise WaveError("not inside a git repository: %s" % cwd)
    main = config.main_checkout(top)
    cfg = _config(top)
    try:
        part = plan_step.resolve(part_dir)
    except plan_step.CannotRun as e:
        raise WaveError(str(e))
    phase = os.path.dirname(part) if _is_subphase(part) else part
    paths = state.phase_paths(part)
    data = _load(plan.load_plan, paths["plan"], "plan.md")
    owner = state.phase_paths(phase)  # context, decisions and the critique are the phase's; a subphase has its own plan and audit only
    post = _load(plan.load_postmortem, owner["postmortem"], "postmortem.md")
    tasks = data["tasks"]
    ignored = _ignored(top, tasks)
    if ignored:
        raise WaveError("a task writes a file git ignores, so its commit would not hold it: %s" % ", ".join(ignored))
    if branch in _defaults(top, cfg):
        raise WaveError("%s is the default branch: execute works on a phase branch, never on it" % branch)
    on = out(top, "symbolic-ref", "--short", "-q", "HEAD")
    if on != branch:
        raise WaveError("the checkout %s is on %s, not on %s" % (top, on or "no branch (detached HEAD)", branch))
    try:
        dirty = verify.is_dirty(top)
    except state.StateError as e:
        raise WaveError(str(e))
    if dirty:
        raise WaveError("the integration checkout %s has uncommitted changes: commit or stash them first" % top)
    revert = _revert_ids(revert)
    fixing = {"source": fix, "findings": _findings(fix, "--fix")} if fix else None
    controls = _findings(control_findings, "--control-findings") if control_findings else []
    value = _base_ref(top, main, environ)
    if value != "head":
        raise WaveError("worktree.baseRef is %s, not head: without it an agent's worktree starts from origin/<default branch>, "
                        "not from %s, and nothing says so; set it to \"head\" in .claude/settings.local.json"
                        % ("absent" if value is None else value, branch))
    recipe = evidence.plan_checks(cfg["project"]["checks"], top)
    if not recipe:
        raise WaveError("no checks defined: `project.checks` in %s is empty and package.json has no test, lint, typecheck or build "
                        "script, so the base cannot be shown green" % os.path.join(main, config.FILE))
    name = os.path.basename(part)
    gating = start == "gate"
    if gating:
        todo = [t["id"] for t in tasks if t["id"] not in _done(top, branch, name, tasks)]
        if todo:
            raise WaveError("--from gate needs every task on %s, and %s is not: run the waves first" % (branch, ", ".join(todo)))
        base = _part_base(top, branch, name)
    else:
        base = verify.head(top)
    run = _run_id(top, name, base)
    size = data["size"]["tag"]
    common = out(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    folder = brief.folder_of(common, run)
    ctx = {"run": run, "part": name, "folder": folder,
           "paths": {"context": str(owner["context"]), "decisions": str(owner["decisions"]),
                     "plan": str(paths["plan"])}}
    quick = evidence.plan_checks(cfg["project"]["checks_quick"], os.devnull)
    made = _briefs(data, ctx, fixing, size, quick, revert is None and not gating)
    _setup(top, cfg, say)
    red = None if gating else _base_is_green(top, base, recipe, {part, phase}, say)
    if red:
        used, cap = rounds.count(state.read_rows(paths["audit"])), rounds.cap(top)
        reason = "base %s is red: %s" % (base[:8], ", ".join("%s=%s" % (r["cmd"], "none" if r["rc"] is None else r["rc"]) for r in red))
        raise RedBase({"status": "needs-owner", "reason": reason, "phase_dir": phase, "rounds": "%d/%d" % (used, cap)},
                      "\n".join("--- %s\n%s" % (r["cmd"], verify.tail(r["output"])) for r in red))
    _write(made, folder, gating)
    if not gating and not revert and not fixing and tasks and len(_done(top, branch, name, tasks)) == len(tasks):
        say("every task is already on %s: `execute` has nothing to run; to run the gate and the review on it: "
            "fwx wave new --part-dir %s --plane %s --branch %s --from gate" % (branch, shlex.quote(part_dir), plane, shlex.quote(branch)))
    clashes = plan._clashes("plan.md", data)
    waves = []
    for n in sorted({t["wave"] for t in tasks}):
        serial = any(c["wave"] == n for c in clashes)
        waves.append({"n": n, "serial": serial,
                      "tasks": [{"id": t["id"], "type": t["type"], "size": t["size"], "ui": t["ui"],
                                 "brief": made[t["id"]][0]["brief"] if t["id"] in made else None,
                                 "trailer": "%s/%s" % (name, t["id"])} for t in tasks if t["wave"] == n]})
    why = [w for w, on_ in (("postmortem.md security_review is true", post["security_review"]), ("--security", security)) if on_]
    return {
        "run": run, "plane": plane, "unattended": plane == "factory" or unattended,
        "part_dir": part, "phase_dir": phase, "checkout": top, "branch": branch, "base": base, "isolation": "native",
        "paths": {"context": str(owner["context"]), "decisions": str(owner["decisions"]),
                  "plan": str(paths["plan"]), "postmortem": str(owner["postmortem"]), "config": os.path.join(main, config.FILE)},
        "models": {"runner": _model(cfg, "executor", "small"),
                   "executor": {t["id"]: _model(cfg, "executor", t["size"]) for t in tasks},
                   "fixer": _model(cfg, "executor", size), "reviewer": _model(cfg, "reviewer", size),
                   "review_verifier": _model(cfg, "review-verifier", "small"),
                   "security_reviewer": _model(cfg, "security-reviewer", size)},
        "waves": waves, "done": _done(top, branch, name, tasks), "plan_failures": [
            {"wave": c["wave"], "tasks": c["tasks"], "files": [c["file"]]} for c in clashes],
        "security": {"needed": bool(why), "why": " and ".join(why) or "not asked for"},
        "criteria": data["criteria"],
        "fix": dict(fixing, brief=made[brief.FIX][0]["brief"] if brief.FIX in made else None) if fixing else None,
        "revert": revert or [],
        "from": start,
        "control_findings": controls,
    }
