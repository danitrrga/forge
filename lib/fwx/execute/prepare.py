"""`fwx wave prepare`: validate a part and give `execute` its `args` (3.4 U2; the shape is C.3 of the plan).

`prepare(cwd, ...)` works on the integration checkout `cwd` is in (the session's worktree, on the phase branch) and returns
the args dict; it raises WaveError (exit 2) for anything that must stop the run before it starts, and RedBase (exit 1) when
the base fails its own checks. It writes nothing: no audit row, no folder.

The part is `part_dir`: a phase folder, a subphase folder (it uses the `context.md` and `decisions.tsv` of the phase that
holds it) or a job folder. Its `plan.md` and `postmortem.md` must load (`plan.load_plan`, `plan.load_postmortem`). Refused with
exit 2, in this order of cost: a plan that does not load; a task file that git ignores (the executor could not commit it); the
requested branch is a default branch, or is not the one the checkout is on; the checkout holds uncommitted work; the effective
`worktree.baseRef` is not `head`; the project has no checks. Why the baseRef: without it a workflow agent's worktree is made from
`origin/<default branch>`, not from the phase branch, and nothing says so (research/execute-measures.md, measured).
The effective value is the last one set of: the user's settings (`$CLAUDE_CONFIG_DIR` or `~/.claude`), the main checkout's
`.claude/settings.json` and `.claude/settings.local.json` (read from a linked worktree too: Claude Code does), and the
checkout's own two.

Then the base is run: the effective recipe (`evidence.plan_checks`) in the checkout, unless the part's audit rows already
holds a green `evidence` row for the base sha. A red check is RedBase: needs-owner, no round spent.

What else it works out: the run id `<part>-<sha7>-<n>` (n counts the runs of that base already made in the git common
dir); the tasks already done (a commit reachable from the phase branch whose trailer says `Fwx-Task: <part>/<task>`); each
wave's `serial` and `plan_failures` for tasks of one wave that write the same path or one inside the other (plan._clashes,
which `load_plan` leaves to its caller); and a model for every role, from the configuration. The brief of each task is `None`
until 3.4 U9 writes it.

Imports the standard library, fwx.plan, plan_step, state, config, core.evidence, core.rounds, core.verify and execute.base.
"""
import json
import os
import re

from fwx import config, plan, plan_step, state
from fwx.core import evidence, rounds, verify
from fwx.execute.base import WaveError, git, out, toplevel

PLANES = ("session", "factory")
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
    return data


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


def prepare(cwd, part_dir, plane, branch, unattended=False, security=False, fix=None, revert=None, control_findings=None,
            environ=None, say=lambda line: None):
    environ = os.environ if environ is None else environ
    if plane not in PLANES:
        raise WaveError("--plane is %r, not one of %s" % (plane, ", ".join(PLANES)))
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
    post = _load(plan.load_postmortem, paths["postmortem"], "postmortem.md")
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
    value = _base_ref(top, main, environ)
    if value != "head":
        raise WaveError("worktree.baseRef is %s, not head: without it an agent's worktree starts from origin/<default branch>, "
                        "not from %s, and nothing says so; set it to \"head\" in .claude/settings.local.json"
                        % ("absent" if value is None else value, branch))
    recipe = evidence.plan_checks(cfg["project"]["checks"], top)
    if not recipe:
        raise WaveError("no checks defined: `project.checks` in %s is empty and package.json has no test, lint, typecheck or build "
                        "script, so the base cannot be shown green" % os.path.join(main, config.FILE))
    base = verify.head(top)
    red = _base_is_green(top, base, recipe, {part, phase}, say)
    if red:
        used, cap = rounds.count(state.read_rows(paths["audit"])), rounds.cap(top)
        reason = "base %s is red: %s" % (base[:8], ", ".join("%s=%s" % (r["cmd"], "none" if r["rc"] is None else r["rc"]) for r in red))
        raise RedBase({"status": "needs-owner", "reason": reason, "phase_dir": phase, "rounds": "%d/%d" % (used, cap)},
                      "\n".join("--- %s\n%s" % (r["cmd"], verify.tail(r["output"])) for r in red))
    name = os.path.basename(part)
    clashes = plan._clashes("plan.md", data)
    waves = []
    for n in sorted({t["wave"] for t in tasks}):
        serial = any(c["wave"] == n for c in clashes)
        waves.append({"n": n, "serial": serial,
                      "tasks": [{"id": t["id"], "type": t["type"], "size": t["size"], "ui": t["ui"], "brief": None,
                                 "trailer": "%s/%s" % (name, t["id"])} for t in tasks if t["wave"] == n]})
    size = data["size"]["tag"]
    why = [w for w, on_ in (("postmortem.md security_review is true", post["security_review"]), ("--security", security)) if on_]
    return {
        "run": _run_id(top, name, base), "plane": plane, "unattended": plane == "factory" or unattended,
        "part_dir": part, "phase_dir": phase, "checkout": top, "branch": branch, "base": base, "isolation": "native",
        "paths": {"context": str(state.phase_paths(phase)["context"]), "decisions": str(state.phase_paths(phase)["decisions"]),
                  "plan": str(paths["plan"]), "postmortem": str(paths["postmortem"]), "config": os.path.join(main, config.FILE)},
        "models": {"runner": _model(cfg, "executor", "small"),
                   "executor": {t["id"]: _model(cfg, "executor", t["size"]) for t in tasks},
                   "fixer": _model(cfg, "executor", size), "reviewer": _model(cfg, "reviewer", size),
                   "review_verifier": _model(cfg, "review-verifier", "small"),
                   "security_reviewer": _model(cfg, "security-reviewer", size)},
        "waves": waves, "done": _done(top, branch, name, tasks), "plan_failures": [
            {"wave": c["wave"], "tasks": c["tasks"], "files": [c["file"]]} for c in clashes],
        "security": {"needed": bool(why), "why": " and ".join(why) or "not asked for"},
        "criteria": data["criteria"],
        "fix": {"source": fix, "findings": _findings(fix, "--fix")} if fix else None,
        "revert": revert or [],
        "control_findings": _findings(control_findings, "--control-findings") if control_findings else [],
    }
