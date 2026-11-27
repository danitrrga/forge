"""`fwx wave new`: validate a part and give `execute` its `args` (3.4 U2; the shape is C.3 of the plan).

`prepare(cwd, ...)` works on the integration checkout `cwd` is in (the session's worktree, on the phase branch) and returns
the args dict; it raises WaveError (exit 2) for anything that must stop the run before it starts, RedBase (exit 1) when
the base fails its own checks, and NotRun (exit 77) when a base check ran out of time. The only files are the briefs (below),
written last, and the evidence row of a base that ran green (below).

The part is `part_dir`: a phase folder, a subphase folder (it uses the `context.md` and `decisions.tsv` of the phase that
holds it) or a job folder. Its `plan.md` and `postmortem.md` must load (`plan.load_plan`, `plan.load_postmortem`); a missing
`postmortem.md` is accepted only for a `small` plan that says `security_review` (_security_why: the planner's answer and a task on a
default protected path or a `project.protected_paths` glob stand in for the post-mortem's). Refused with
exit 2, in this order of cost: no `orca` on PATH on the session plane (`need_orca`, before anything is read); a plan that does not load; a checkout that is not a worktree of the repository the part works in (the plan's `repo`,
else the workspace: nested repos, `project.repos`); a task file that git ignores (the executor could not commit it); the
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

Then the base is run: the effective recipe (`evidence.plan_checks`) in the checkout, unless the audit rows of the part or its phase
already hold a green `evidence` row for the base sha whose commands are exactly the recipe (`base checks: reused the passing record
of <sha7>`), or GitHub CI already passed the base: the workflow `.github/workflows/ci.yml` ran on a push of that exact sha to `project.default_branch`
and every such run is completed with the conclusion success (`gh api .../actions/runs`, asked for at most `ci_gate.CI_TIMEOUT_S`; `base checks: CI passed
<sha7> (.github/workflows/ci.yml on <branch>, success)`); no row is written for it, so the next `wave new` asks again. Any other answer,
or none (no gh, not signed in, no GitHub origin, no `default_branch`, network down, timeout, only a pull request run, no run, in progress, red or
skipped), is not green: one stderr line says why and the recipe runs here as before. A base that ran green leaves such a row in the part's audit, so the next `wave new` on that base (a relaunch, a part that
starts where the last stopped) runs nothing: the checks of a large project take longer than the rest of the command together. A red
check is RedBase: needs-owner, no round spent, no row. A check killed by its time limit (`project.check_timeout_s`, default `verify.CHECK_TIMEOUT_S`) proved nothing, red
or green: it is NotRun, a machine condition with its own exit and no row, unless another check of the recipe is red, which is RedBase.

What else it works out: the run id `<part>-<sha7>-<n>` (n is the first number of that base whose folder is free in the git common
dir: the folder is made at once, so two runs never share one, and a refused run removes it); the tasks already done (a commit reachable from the phase branch whose trailer says `Fwx-Task: <part>/<task>`); each
wave's `serial` and `plan_failures` for tasks of one wave that write the same path or one inside the other (plan._clashes,
which `load_plan` leaves to its caller); and a model for every role, from the configuration.

`--from gate` (3.4 align) is the way back into the checks once every task is on the phase branch: the tree's n_C7F, where the
owner fixed what kept the gate from running, loops to n_C7 and then to the review. Refused (exit 2) unless every task is done,
and with `--fix` or `--revert`. It launches nothing, so it writes no brief and does not run the base (the gate judges the head,
red or not), and `base` is where the part's first run started (the oldest `Fwx-Run: <part>-<sha7>-<n>` of the phase branch), not
the head: the review and the trusted-edit report diff from it. The run id continues that numbering. The result has `from: "gate"`.

The briefs (3.4 U9, execute/brief.py): one file per task in `<fwx folder>/runs/<run>/briefs/<task>.md`, its path in
`waves[].tasks[].brief`. They hold no base sha (a later wave starts from a later head: the workflow names it in the prompt) and
no path for a report: an agent writes in the folder `fwx scratch new` makes in its own worktree. They are built, and checked, before the base is run: a field that
is empty stops the run with exit 2, naming task and field, before any file exists; the files are written once the base is green,
so a refusal and a red base leave nothing behind. With `--fix` the one brief is the fixer's (`fix.brief`) and the tasks of the
plan get none; with `--revert` nothing is launched, so there is none. `--fix` and `--control-findings` are lists of findings in the
shape of plan C.5 (execute/brief.py `finding_problems`), or the rows of a walk's fix.json (`normalize`), `--revert` a list of finding ids; anything else is refused.

Imports the standard library (shutil: `need_orca` looks for `orca` on PATH), fwx.plan, plan_form, plan_step, state, config, core.ci_gate, core.evidence, core.rounds, core.verify and execute.base, execute.brief and execute.worktree_setup.
"""
import itertools
import json
import os
import re
import shlex
import shutil

from fwx import config, plan, plan_form, plan_step, state
from fwx.core import ci_gate, evidence, rounds, verify
from fwx.execute import brief, worktree_setup
from fwx.execute.base import WaveError, git, linked, out, toplevel

PLANES = ("session", "factory")
STARTS = ("gate",)
_PHASE_NAME = re.compile(r"\d+(\.\d+)*-.+\Z")


def need_orca(plane, environ=None):
    """The session plane drives every agent as an Orca worker (execute/orca.py), so without `orca` on PATH a run would fail late and leave a failed run
    behind: refuse first, naming what to install. The factory plane has its own seam."""
    environ = os.environ if environ is None else environ
    if plane == "session" and shutil.which("orca", path=environ.get("PATH", os.defpath)) is None:
        raise WaveError("orca is not on PATH: `wave run` drives each agent as an Orca worker, so install Orca (the desktop app) and its CLI "
                        "(Settings in Orca) first; discuss, plan and the mortems do not need it")


class NotRun(Exception):
    """A base check ran out of time, so the base is neither green nor red: nothing is recorded and no round is spent."""


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


def _security_why(data, post_path, cfg):
    """The reasons the security review is needed, from the post-mortem, or from the plan when a small plan skips it (a missing
    postmortem.md is accepted only then, and the plan must say `security_review`: a default would let an unasked-for review through).
    A task on a default protected path (decide's table) or a `project.protected_paths` glob forces the review in a plan with no post-mortem, whatever the planner wrote."""
    if os.path.exists(post_path):
        post = _load(plan.load_postmortem, post_path, "postmortem.md")
        return ["postmortem.md security_review is true"] if post["security_review"] else []
    if data["size"]["tag"] != "small":
        raise WaveError("%s is missing: only a small plan may skip the post-mortem, and this one is %s" % (post_path, data["size"]["tag"]))
    if "security_review" not in data:
        raise WaveError("plan.md: security_review: missing: a small plan that skips the post-mortem says whether it needs the security review "
                        "(true or false), because nothing else would ask")
    why = ["plan.md security_review is true"] if data["security_review"] else []
    protected = plan_form.protected_paths(cfg)
    for t in data["tasks"]:
        hit = next(((f, g) for f in t["files"] for g in [plan_form.protected_glob(protected, f)] if g), None)
        if hit:
            why.append("task %s writes %s, a protected path (%s)" % (t["id"], hit[0], hit[1]))
            break
    return why


def _repo_checked(top, main, part, cfg):
    """WaveError unless `top` is a worktree of the repository the part works in: the repo its plan names (`plan_form.part_repo`), else
    the workspace itself. The tasks name that repo's files, its checks and branch are the ones that run here, and a worktree of any
    other repo holds none of the code."""
    named = plan_form.part_repo(part, cfg)
    repos = cfg["project"]["repos"]
    if named is not None and named not in repos:
        raise WaveError("%s: repo %s names no repo of project.repos (%s)" % (os.path.join(part, "plan.md"), named, ", ".join(repos) or "none declared"))
    want = os.path.realpath(os.path.join(main, repos[named]["path"]) if named else main)
    have = os.path.realpath(config.repo_checkout(top))
    if have != want:
        raise WaveError("the part works in %s (%s) and the checkout %s is a worktree of %s: run `fwx wave new` from a worktree of %s"
                        % ("repo " + named if named else "the workspace", want, top, have, "repo " + named if named else "the workspace"))


def _ignored(top, tasks):
    """The task files git ignores in `top` (a tracked file is not ignored: it can be committed)."""
    files = sorted({plan._norm(f) for t in tasks for f in t["files"]})
    r = git(top, "check-ignore", "-z", "--stdin", input="\0".join(files))
    if r.returncode not in (0, 1):
        raise WaveError("git check-ignore failed in %s: %s" % (top, r.stderr.strip()))
    return [f for f in r.stdout.split("\0") if f]


def _defaults(top, cfg):
    """The names of the default branch (core.verify has the one copy)."""
    return verify.default_names(top, cfg)


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
    """The part's next run id at `base`, with its folder made: `os.mkdir` creates or fails, so two runs of one part at one base never share a number,
    and a number another run took, or one whose folder is left, is skipped. A folder with no `state.json` is no run to `wave list`."""
    prefix = "%s-%s-" % (part_name, base[:7])
    runs = os.path.join(config.fwx_dir(top), "runs")
    try:
        os.makedirs(runs, exist_ok=True)
        for n in itertools.count(1):
            try:
                os.mkdir(os.path.join(runs, "%s%d" % (prefix, n)))
                return "%s%d" % (prefix, n)
            except FileExistsError:
                continue
    except OSError as e:
        raise WaveError("cannot make the run folder in %s: %s" % (runs, e))


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


def _cap(cfg, unattended):
    """The most executors at once, from the configuration (`limits.per_project.executor`, else `limits.default_cap`): the workflow reads
    it from the args and asks no command. A value that is no positive whole number refuses the run before anything is written."""
    try:
        return config.cap(cfg, "executor", unattended)
    except config.ConfigError as e:
        raise WaveError(str(e))


def _record(base, recipe, folders):
    """The green `evidence` row in the audit of one of `folders`, or of a part folder inside one (a phase's sibling parts share its base),
    that stands in for a run of `recipe` at `base`: the same sha, rc 0, and the commands of its evidence exactly the recipe, each with
    exit 0 (a row of other checks proves nothing about these), or evidence of GitHub CI (`source: ci`, the gate of a part that ended on
    this sha: CI ran the recipe, as the pull request's suite selection chose it) with every command at exit 0. None if none."""
    own = sorted(folders)
    siblings = [s for s in dict.fromkeys(str(s) for f in own for s in state.subphases(f)) if s not in own]
    for d in own + siblings:
        try:
            rows = state.read_rows(state.phase_paths(d)["audit"])
        except (OSError, UnicodeDecodeError):
            if d in own:
                raise
            continue  # another part's unreadable file is not this part's to fail on
        for row in rows:
            if row.get("kind") != "evidence" or row.get("sha") != base or row.get("rc", "").strip() != "0":
                continue
            try:
                detail = json.loads(row.get("detail", ""))
                got = [(c["cmd"], c["rc"]) for c in detail["commands"]]
            except (ValueError, KeyError, TypeError):
                continue
            if got == [(c, 0) for c in recipe] or (detail.get("source") == evidence.CI_SOURCE and got and all(rc == 0 for _, rc in got)):
                return row
    return None


def _base_is_green(top, base, recipe, folders, say, timeout, part=None, cfg=None):
    """None when the base passes (a check ran here, or a green evidence row says so), `[]` when a green CI run of the sha says so, else the red
    results. NotRun when no check is red and one ran out of time (`timeout` seconds each: the project's `check_timeout_s`). `[]` is falsy, like
    None, but the caller writes a row only for None: a CI answer leaves no row, since no check ran here and a row says one did (`integrate` and
    the part report read it as verify evidence); the next `wave new` on the same base asks GitHub again."""
    if _record(base, recipe, folders):
        say("base checks: reused the passing record of %s" % base[:7])
        return None
    if ci_gate.base_green(top, base, say, cfg):
        return []
    with verify.gate_lock(top):  # one recipe at a time per project, as `fwx verify` does: two at once fail each other on load; `prepare` refuses an empty recipe
        results = [verify.run_check(c, top, timeout) for c in recipe]
    red = [r for r in results if r["rc"] != 0 and not r["timed_out"]]
    late = [r for r in results if r["timed_out"]]
    if not red and late:
        raise NotRun("NOT RUN: the base checks at %s did not finish: %s timed out after %d s. That is the machine, not the code: the base is "
                     "neither red nor green, no round was spent and nothing was recorded. Run it again when the machine is less loaded, or raise `project.check_timeout_s` if the check needs longer. "
                     "A base that passes is recorded, and the next `fwx wave new` on it reuses the record"
                     % (base[:8], ", ".join(r["cmd"] for r in late), late[0]["limit"]))
    return red or None


def _unmoved(top, base):
    """WaveError if HEAD is no longer `base` after the base checks: a check that commits or checks out proves nothing about `base`, and a
    green row of `base` written then would be reused by the next run. This is what `fwx verify` calls not clean (`clean` is `HEAD == sha`)."""
    try:
        now = verify.head(top)
    except state.StateError as e:
        raise WaveError(str(e))
    if now != base:
        raise WaveError("HEAD moved from %s to %s while the base checks ran, so they prove neither commit: nothing was recorded"
                        % (base[:8], now[:8]))


def _remember(part, base, recipe, folders, cfg):
    """The evidence row of a base that ran green (shaped as `fwx verify` writes it), unless a record already stands in for the run.
    `clean` is True because `_unmoved` has just measured it, as `fwx verify` does."""
    if _record(base, recipe, folders):
        return
    source = ("profile" if evidence.plan_checks(cfg["project"]["checks"], os.devnull) else "package")
    ev = {"sha": base, "clean": True, "source": source, "commands": [{"cmd": c, "rc": 0} for c in recipe], "rc": 0}
    state.append_audit(part, "evidence", detail=json.dumps(ev), rc=0, sha=base)


def _write(made, folder):
    """The briefs of a run, written once everything else has passed, into the folder `_run_id` made."""
    try:
        for facts, text in made.values():
            brief.put(facts["brief"], text)
    except OSError as e:
        raise WaveError("cannot write the briefs of the run in %s: %s" % (folder, e))


def prepare(*args, **kw):
    """`_prepare`, and a run it refuses (a red base, a bad flag) gives back the folder `_run_id` claimed: an empty folder would take a number
    the next run then skips. `rmdir` leaves a folder that holds briefs."""
    claimed = []
    try:
        return _prepare(*args, claimed=claimed, **kw)
    except BaseException:
        for folder in claimed:
            try:
                os.rmdir(folder)
            except OSError:
                pass
        raise


def _prepare(cwd, part_dir, plane, branch, unattended=False, security=False, fix=None, revert=None, control_findings=None,
             start=None, environ=None, say=lambda line: None, claimed=None):
    environ = os.environ if environ is None else environ
    if plane not in PLANES:
        raise WaveError("--plane is %r, not one of %s" % (plane, ", ".join(PLANES)))
    need_orca(plane, environ)
    if start is not None and start not in STARTS:
        raise WaveError("--from is %r, not one of %s" % (start, ", ".join(STARTS)))
    if start and (fix or revert is not None):
        raise WaveError("--from %s runs no fixer and reverts nothing: it cannot go with --fix or --revert" % start)
    top = toplevel(cwd)
    if top is None:
        raise WaveError("not inside a git repository: %s" % cwd)
    main = config.main_checkout(top)
    cfg = _config(top)
    cap = _cap(cfg, plane == "factory" or unattended)
    try:
        part = plan_step.resolve(part_dir)
    except plan_step.CannotRun as e:
        raise WaveError(str(e))
    _repo_checked(top, main, part, cfg)
    phase = os.path.dirname(part) if _is_subphase(part) else part
    paths = state.phase_paths(part)
    data = _load(plan.load_plan, paths["plan"], "plan.md")
    owner = state.phase_paths(phase)  # context, decisions and the critique are the phase's; a subphase has its own plan and audit only
    tasks = data["tasks"]
    why = _security_why(data, owner["postmortem"], cfg)
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
    folder = brief.folder_of(config.fwx_dir(top), run)
    claimed.append(folder)
    ctx = {"run": run, "part": name, "folder": folder,
           "paths": {"context": str(owner["context"]), "decisions": str(owner["decisions"]),
                     "plan": str(paths["plan"])}}
    quick = evidence.plan_checks(cfg["project"]["checks_quick"], os.devnull)
    made = _briefs(data, ctx, fixing, size, quick, revert is None and not gating)
    _setup(top, cfg, say)
    red = None if gating else _base_is_green(top, base, recipe, {part, phase}, say, cfg["project"]["check_timeout_s"], part, cfg)
    if red:
        used, cap = rounds.count(state.read_rows(paths["audit"])), rounds.cap(top)
        reason = "base %s is red: %s" % (base[:8], ", ".join("%s=%s" % (r["cmd"], "none" if r["rc"] is None else r["rc"]) for r in red))
        raise RedBase({"status": "needs-owner", "reason": reason, "phase_dir": phase, "rounds": "%d/%d" % (used, cap)},
                      "\n".join("--- %s\n%s" % (r["cmd"], verify.tail(r["output"])) for r in red))
    if not gating and red is None:
        _unmoved(top, base)
        _remember(part, base, recipe, {part, phase}, cfg)
    _write(made, folder)
    if not gating and not revert and not fixing and tasks and len(_done(top, branch, name, tasks)) == len(tasks):
        say("every task is already on %s: `execute` has nothing to run; to run the gate and the review on it: "
            "fwx wave new --part-dir %s --plane %s --branch %s --from gate" % (branch, shlex.quote(part_dir), plane, shlex.quote(branch)))
    clashes = plan._clashes("plan.md", data)
    waves = []
    for n in sorted({t["wave"] for t in tasks}):
        serial = any(c["wave"] == n for c in clashes)
        waves.append({"n": n, "serial": serial,
                      "tasks": [{"id": t["id"], "type": t["type"], "size": t["size"], "ui": t["ui"], "files": [plan._norm(f) for f in t["files"]],
                                 "brief": made[t["id"]][0]["brief"] if t["id"] in made else None,
                                 "trailer": "%s/%s" % (name, t["id"])} for t in tasks if t["wave"] == n]})
    why = why + ["--security"] * bool(security)
    return {
        "run": run, "plane": plane, "unattended": plane == "factory" or unattended, "cap": cap,
        "linear": bool(cfg["project"].get("linear_project")),  # an unfixed `outside` item needs its issue key only where there is a Linear project
        "part_dir": part, "phase_dir": phase, "checkout": top, "branch": branch, "base": base, "isolation": "native",
        "paths": {"context": str(owner["context"]), "decisions": str(owner["decisions"]),
                  "plan": str(paths["plan"]), "postmortem": str(owner["postmortem"]), "config": os.path.join(main, config.FILE)},
        "models": {"runner": _model(cfg, "runner", "small"),
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
