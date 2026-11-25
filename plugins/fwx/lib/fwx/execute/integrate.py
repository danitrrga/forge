"""The only path that writes the phase branch, and the one place that spends a round (3.4 U3; shapes in C.2 of the plan).

Only this module runs `git merge` and `git revert`; nothing in lib/fwx/ runs `git rebase` or `git reset --hard`, and the only `git push`
(never forced) is core/ci_gate.py's (tests/test_single_writer.py reads the code to check it). No function here writes a `stage` row, and only `fix_round` writes a
round.

`integrate(cwd, ...)` merges the branches of a wave into the branch the checkout `cwd` is on, with `--no-ff`, in the order
given. It refuses (exit 2, nothing merged) a checkout with uncommitted changes, a branch whose worktree holds a live agent
(`cleanup.lock_state`: the pid lives and its start time is the lock's; a dead agent's lock does not stop it), and, with
`findings`, a set of branches whose commits are not exactly one `Fwx-Finding: <id>` commit per finding. At the first conflict
it aborts that merge and stops (the earlier ones stay). Then it runs the project's `worktree_setup` again in the checkout (a no-op unless a merge changed a dependency file; a failure
stops here with `setup` in the result and exit 1) and then `project.checks_quick`, removes the
worktrees of the branches it merged (only unlocked, clean ones: a stale lock is `cleanup`'s), and, with `final` and everything
green, runs the gate (`core.verify` with `ci=True`: GitHub CI when it can answer, else the project's checks here) and reports the trusted edits (with a `worktree_setup`, also the files it installs from: core.trusted) and the protected paths of
`<base>..HEAD`, `base` being the sha in the run id. It reports; it spends no round. With `final` and no branch nothing is merged: it is the gate on the head as it
is (the re-entry of `prepare --from gate`).

The result also says what follows (`next_step`): `next` is wave, review, resolve, fix or
owner, `why` the text for `fwx wave fix --why`, and `brief` for resolve and fix the path of the brief written for that agent
(execute/brief.py `resolver_facts`, `fixer_facts`), whose BASE is the head the merge left. A brief that cannot be written (no plan, a missing
context file) makes the next step `owner` and says why. The session spends the round with `fix_round` before it launches either agent.

`fix_round(cwd, part_dir, why)` decides whether a failure may be fixed and spends the round for it. If the last audit row is
the red evidence of the checkout's HEAD, `verify` already made that failure a round and nothing more is spent. A failure is
allowed only when fewer than `rounds` were spent before it: the third round is fixed, only the failure after it ends the job.

`revert(cwd, part_dir, finding_ids)` reverts the commit of each finding, the newest first, and then runs the setup again like `integrate`
(`setup` in the result on a failure). `summary(...)` says whether the gate
of the run passes, and carries what the part report reads, from the run's own recorded calls (`_kept`; 09.5 T54): `findings` ({reported, fix, consider, note, dismissed, fixed: [{id, commit, severity}], outside}: the passes `wave findings` ended,
and the commits of the `Fwx-Finding` trailers of the findings a `wave merge --findings` merged), `criteria`, `outside` (the items of the reports
that were merged and have no issue), `tried` (one line per round spent), `gaps` and `protected`. Imports the standard library, fwx.state, fwx.config, fwx.plan, fwx.plan_step, fwx.core and execute.base, brief, cleanup and worktree_setup.
"""
import json
import os
import re

from fwx import config, plan, plan_step, state
from fwx.core import decide, evidence, globs, rounds, trusted, verify
from fwx.execute import brief, cleanup, worktree_setup
from fwx.execute.base import WaveError, git, linked, out


def _top(cwd):
    top = out(cwd, "rev-parse", "--show-toplevel")
    if top is None:
        raise WaveError("not inside a git repository: %s" % cwd)
    return os.path.realpath(top)


def _branch(top):
    on = out(top, "symbolic-ref", "--short", "-q", "HEAD")
    if on is None:
        raise WaveError("the checkout %s is on no branch (detached HEAD): the integration checkout is on the phase branch" % top)
    return on


def _clean(top):
    try:
        if verify.is_dirty(top):
            raise WaveError("the integration checkout %s has uncommitted changes: commit or stash them first" % top)
    except state.StateError as e:
        raise WaveError(str(e))


def _commits(top, *rev):
    """[(sha, [finding ids])] of the non-merge commits of a git revision range, newest first."""
    r = git(top, "log", *rev, "--no-merges", "--format=%H%x1f%(trailers:key=Fwx-Finding,valueonly,unfold)%x1e")
    if r.returncode:
        raise WaveError("git log %s failed: %s" % (" ".join(rev), r.stderr.strip()))
    rows = []
    for rec in r.stdout.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, _, ids = rec.partition("\x1f")
        rows.append((sha.strip(), [i.strip() for i in ids.splitlines() if i.strip()]))
    return rows


def _findings_check(top, phase, branches, wanted):
    """{ok, problems}: each finding in exactly one commit of the branches, and no commit for two findings."""
    seen = {}
    for b in branches:
        for sha, found in _commits(top, "refs/heads/" + b, "--not", phase):
            seen[sha] = found
    problems = []
    for sha, found in seen.items():
        ids = sorted(set(found))
        if len(ids) > 1:
            problems.append("commit %s carries %s: one commit per finding" % (sha[:8], " and ".join(ids)))
    for i in wanted:
        n = sum(1 for found in seen.values() if i in found)
        if n == 0:
            problems.append("%s: no commit carries Fwx-Finding: %s" % (i, i))
        elif n > 1:
            problems.append("%s: %d commits carry Fwx-Finding: %s, want one" % (i, n, i))
    return {"ok": not problems, "problems": problems}


def _setup_again(top, commands, result, say):
    """The setup of the worktree after the branch changed under it (a merge, a revert): installed again when a dependency file moved
    (a no-op otherwise). True when it failed: `setup` of the result then holds the line, which starts `worktree setup failed:`. The
    main checkout is the owner's own and is left alone."""
    if not commands or not linked(top):
        return False
    try:
        worktree_setup.run(top, commands)
    except (worktree_setup.SetupFailed, WaveError) as e:
        result["setup"] = str(e) if isinstance(e, worktree_setup.SetupFailed) else "worktree setup failed: %s" % e
        say(result["setup"])
        return True
    return False


def _show(top, rev, path):
    """The text of `path` at `rev`; None when there is none."""
    r = git(top, "show", "%s:%s" % (rev, path))
    return r.stdout if r.returncode == 0 else None


def _quick(top, cfg, say=lambda line: None):
    """{ran, cmds, rc}: project.checks_quick, run in the checkout; rc is 0 or the first exit that is not. A check stopped by
    `project.check_timeout_s` is rc 1 as before, and the result also has `timed_out` (those commands) and `limit` (the seconds each
    had), so that it is not taken for a failing check; `say` says so with what to do (only then: the shape is unchanged otherwise)."""
    cmds = evidence.plan_checks(cfg["project"]["checks_quick"], os.devnull)
    limit = cfg["project"]["check_timeout_s"]
    rc, late = 0, []
    for c in cmds:
        r = verify.run_check(c, top, limit)
        if r["timed_out"]:
            late.append(c)
            say("quick check %s timed out after %d s: raise `project.check_timeout_s` if the check needs longer" % (c, limit))
        if r["rc"] != 0 and rc == 0:
            rc = 1 if r["rc"] is None else r["rc"]
    out = {"ran": bool(cmds), "cmds": cmds, "rc": rc}
    if late:
        out.update(timed_out=late, limit=limit)
    return out


def _changed(top, base):
    r = git(top, "diff", "--name-only", "%s..HEAD" % base)
    if r.returncode:
        raise WaveError("git diff %s..HEAD failed: %s" % (base, r.stderr.strip()))
    return [p for p in r.stdout.splitlines() if p]


def _oneline(text, limit=600):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def next_step(result, final):
    """(next, why) for a merge result. `next` is `wave` (merged: launch the next wave, or
    merge the last with --final), `review` (the gate is green: review the diff), `resolve` (a conflict: a resolver), `fix` (a red check, a red
    gate, commits that are not one per finding: a fixer) or `owner` (nothing an agent can fix: a verify that could not run, trusted edits, a
    failed setup, a live lock, or a result that names no cause). For `resolve` and `fix`, `why` is the text for `fwx wave fix --why`."""
    if result["ok"]:
        if not final:
            return "wave", "merged %s on %s: launch the next wave, or merge the last one with --final" % (", ".join(result["merged"]) or "nothing", result["head"])
        if result["trusted"]:
            return "owner", "the diff edits what the checks take as good, so the owner decides: %s" % ", ".join(result["trusted"])
        return "review", "the gate is green on %s: review the diff since the run's base" % result["head"]
    if result["locked"]:
        return "owner", "a live agent holds %s: nothing was merged" % ", ".join(x["branch"] for x in result["locked"])
    if isinstance(result.get("setup"), str) and result["setup"].strip():
        return "owner", _oneline(result["setup"])
    if result["findings_check"]["ok"] is False:
        return "fix", "the commits were not one per finding: %s" % "; ".join(result["findings_check"]["problems"])
    if result["conflict"]:
        return "resolve", "the branch %s conflicts in %s" % (result["conflict"]["branch"], ", ".join(result["conflict"]["files"]))
    q, v = result["quick"], result["verify"]
    if q["ran"] and q["rc"] != 0:
        why = "checks_quick failed with exit %s on %s: %s" % (q["rc"], result["head"], " ; ".join(q["cmds"]))
        if q.get("timed_out"):
            why += " (stopped after %s s: %s; raise project.check_timeout_s if the check needs longer)" % (q["limit"], " ; ".join(q["timed_out"]))
        return "fix", why
    if v["ran"] and v["rc"] != 0:
        if v["rc"] != 1:
            return "owner", "verify could not run (exit %s): %s" % (v["rc"], v["line"] or "no line")
        return "fix", "the gate failed on %s: %s" % (result["head"], v["line"])
    return "owner", "integrate was not ok and its result says why in no field"


def _owner_dir(part):
    """The folder of the phase a part belongs to: its context, decisions and critique are the phase's; a subphase has its own plan and audit."""
    parent = os.path.dirname(part)
    return parent if part in [str(p) for p in state.subphases(parent)] else part


def _trailer_of(top, branch, phase):
    """The `Fwx-Task` value of the newest commit of `branch` that has one, or None."""
    r = git(top, "log", "refs/heads/" + branch, "--not", phase, "--no-merges", "--format=%(trailers:key=Fwx-Task,valueonly,unfold)%x1e")
    for rec in r.stdout.split("\x1e") if r.returncode == 0 else []:
        if rec.strip():
            return rec.strip().splitlines()[0].strip()
    return None


def _findings_brief(folder, findings):
    """The brief of the fixer that holds the text of the findings: the oldest `_fix-<n>.md` of the run (`_fix.md`, `wave new --fix`, counts as the
    first) that names every id of `findings`, or None. The oldest, because a fixer sent after a refused attempt lists the ids too and points back to
    it; the fixer of a red check or gate names no finding, so it is never the one."""
    briefs = os.path.join(folder, "briefs")
    found = [(int(m.group(1) or 0), f) for f, m in ((f, re.fullmatch(r"%s(?:-(\d+))?\.md" % brief.FIX, f)) for f in (os.listdir(briefs) if os.path.isdir(briefs) else [])) if m]
    for _n, name in sorted(found):
        try:
            with open(os.path.join(briefs, name), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        if all(re.search(r"(?<![\w.-])%s(?![\w.-])" % re.escape(i), text) for i in findings):
            return os.path.join(briefs, name)
    return None


def _write_brief(top, part_dir, run, cfg, result, why, branches, findings):
    """(unit, path) of the brief written for the resolver or the fixer this result calls for, or raise WaveError saying why none could be."""
    part = _resolve_part(part_dir)
    try:
        data = plan.load_plan(state.phase_paths(part)["plan"])
    except (plan.PlanError, OSError) as e:
        raise WaveError("the plan of the part cannot be read: %s" % e)
    owner = state.phase_paths(_owner_dir(part))
    paths = {"context": str(owner["context"]), "decisions": str(owner["decisions"]), "plan": str(state.phase_paths(part)["plan"]),
             "config": os.path.join(config.main_checkout(top), config.FILE)}
    common = out(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    folder = brief.folder_of(common, run)
    ctx = {"run": run, "part": os.path.basename(part), "folder": folder, "paths": paths,
           "quick": evidence.plan_checks(cfg["project"]["checks_quick"], os.devnull)}
    kind = "resolve" if result["next"] == "resolve" else "fix"
    unit, path = brief.next_unit(folder, kind)
    if kind == "resolve":
        c = result["conflict"]
        facts = brief.resolver_facts(c, result["head"], _trailer_of(top, c["branch"], _branch(top)), unit, ctx,
                                     ("git merge --no-commit %s" % c["branch"], "git merge --abort"))
    else:
        findings_failed = result["findings_check"]["ok"] is False
        earlier = _findings_brief(folder, findings) if findings_failed else None
        facts = brief.fixer_facts(why, result["head"], data["tasks"], unit, ctx, findings=list(findings) if findings_failed else (),
                                  refused=list(branches) if findings_failed else (), fix_brief=earlier)
    missing = brief.agent_missing(facts)
    if missing:
        raise WaveError("; ".join(missing))
    brief.put(path, brief.render_agent(facts))
    return unit, path


def _resolve_part(part_dir):
    try:
        return plan_step.resolve(part_dir)
    except plan_step.CannotRun as e:
        raise WaveError(str(e))


def integrate(cwd, part_dir, run, branches, findings=(), final=False, say=lambda line: None):
    """(exit code, result): `_merge`'s result, with `next` and `why` (`next_step`) and `brief` and `unit`: for `resolve` and `fix`, the path
    of the brief written for that agent (execute/brief.py), whose BASE is the head the merge left, and the agent's unit (`resolve-1`, `fix-2`: the folder
    `fwx scratch new <run> <unit>` makes, so what `wave report --unit` takes); else None. When the brief cannot be written
    (the plan or a context file is missing) `next` is `owner` and `why` says so, followed by the failure."""
    code, result = _merge(cwd, part_dir, run, branches, findings, final, say)
    result["next"], result["why"] = next_step(result, final)
    result["brief"] = result["unit"] = None
    if result["next"] in ("resolve", "fix"):
        try:
            top = _top(cwd)
            result["unit"], result["brief"] = _write_brief(top, part_dir, run, config.load(top), result, result["why"], branches, findings)
        except (WaveError, config.ConfigError, state.StateError, OSError) as e:
            result["next"], result["why"] = "owner", "no brief could be written for the %s (%s): %s" % (
                "resolver" if result["next"] == "resolve" else "fixer", e, result["why"])
    return code, result


def _merge(cwd, part_dir, run, branches, findings=(), final=False, say=lambda line: None):
    """(exit code, result). The result is C.2's: {ok, head, merged, conflict, remaining (the branches after the one that conflicted,
    not merged yet: the caller merges them after the resolver), locked, findings_check, quick, verify, trusted,
    protected}, and `setup` (the line `worktree setup failed: ...`) only when the setup after the merges failed. Raises WaveError for what stops it before it merges anything and cleanup.NoProc without /proc."""
    top = _top(cwd)
    phase = _branch(top)
    if not os.path.isdir(part_dir):
        raise WaveError("--part-dir %s is not a folder" % part_dir)
    _clean(top)
    cfg = config.load(top)
    base = cleanup.base_of(top, run) if final else None
    for b in branches:
        if b == phase:
            raise WaveError("%s is the phase branch: it cannot be merged into itself" % b)
        if git(top, "rev-parse", "--verify", "--quiet", "refs/heads/" + b).returncode:
            raise WaveError("no branch %s" % b)
    result = {"ok": False, "head": verify.head(top), "merged": [], "conflict": None, "remaining": [], "locked": [],
              "findings_check": {"ok": True, "problems": []}, "quick": {"ran": False, "cmds": [], "rc": 0},
              "verify": {"ran": False, "rc": None, "line": ""}, "trusted": [], "protected": []}
    by_branch = {w["branch"]: w for w in cleanup.worktrees(top)[1:] if w["branch"]}
    for b in branches:
        w = by_branch.get(b)
        if w and cleanup.lock_state(w) in ("live", "unknown"):
            result["locked"].append({"branch": b, "worktree": w["path"], "pid": cleanup.pid_of(w), "lock": w["locked"]})
    if result["locked"]:
        say("a live agent holds %s: nothing merged" % ", ".join(x["branch"] for x in result["locked"]))
        return 2, result
    if findings:
        result["findings_check"] = _findings_check(top, phase, branches, findings)
        if not result["findings_check"]["ok"]:
            say("the commits are not one per finding: nothing merged")
            return 2, result
    for b in branches:
        r = git(top, "merge", "--no-ff", "--no-edit", "-m", "Merge branch '%s'" % b, "-m", "Fwx-Run: %s" % run, "refs/heads/" + b)
        if r.returncode:
            files = [p for p in (out(top, "diff", "--name-only", "--diff-filter=U") or "").splitlines() if p]
            git(top, "merge", "--abort")
            if not files:
                raise WaveError("git merge %s failed, not for a conflict (merged before it: %s): %s"
                                % (b, ", ".join(result["merged"]) or "none", r.stderr.strip() or r.stdout.strip()))
            result["conflict"] = {"branch": b, "files": files}
            result["remaining"] = branches[len(result["merged"]) + 1:]  # not merged yet, after the one that conflicted: the run merges them after the resolver
            break
        result["merged"].append(b)
    for b in result["merged"]:
        w = by_branch.get(b)
        if w and cleanup.lock_state(w) == "none":
            why = cleanup.remove(top, w)
            if why:
                say("worktree of %s stays: %s" % (b, why))
    result["head"] = verify.head(top)
    if result["conflict"]:
        return 1, result
    # A merged lockfile changes what the checks need: the dependencies of this checkout are installed again before any check runs
    # (the marker makes it a no-op when no dependency file changed).
    if _setup_again(top, cfg["project"]["worktree_setup"], result, say):
        return 1, result
    result["quick"] = _quick(top, cfg, say)
    result["ok"] = result["quick"]["rc"] == 0
    if final and result["ok"]:
        code, ev = verify.verify(top, part_dir, say, ci=True)
        line = verify.evidence_line(ev["sha"], ev["commands"]) if ev else ""
        urls = [u for u in (ev or {}).get("urls") or [] if isinstance(u, str) and u]
        result["verify"] = {"ran": True, "rc": code, "line": line + (" (%s)" % ", ".join(urls) if urls else "")}
        result["ok"] = code == 0
        if result["ok"]:
            changed = _changed(top, base)
            setup = cfg["project"]["worktree_setup"]
            manifest = (_show(top, base, "package.json"), _show(top, "HEAD", "package.json")) if setup else None
            result["trusted"] = trusted.trusted_edits(changed, cfg["project"]["checks"], setup=setup, manifest=manifest)
            protected = list(decide.load_table()["default_protected_paths"]) + list(cfg["project"]["protected_paths"])
            result["protected"] = [p for p in changed if globs.matches_any(p, protected)]
    return (0 if result["ok"] else 1), result


def fix_round(cwd, part_dir, why):
    """(exit code, result): {ok, spent, rounds, why}. Exit 0 when the failure may be fixed, 1 when the rounds were spent."""
    top = _top(cwd)
    if not os.path.isdir(part_dir):
        raise WaveError("--part-dir %s is not a folder" % part_dir)
    if not why.strip():
        raise WaveError("--why needs a reason")
    cap = rounds.cap(part_dir)
    rows = state.read_rows(state.phase_paths(part_dir)["audit"])
    head = verify.head(top)
    last = rows[-1] if rows else {}
    counted = last.get("kind") == "evidence" and last.get("rc", "").strip() != "0" and last.get("sha") == head
    before = rounds.count(rows[:-1]) if counted else rounds.count(rows)
    spent = False
    if before >= cap:
        return 1, {"ok": False, "spent": False, "rounds": "%d/%d" % (rounds.count(rows), cap), "why": why}
    if not counted:
        rounds.record(part_dir, "use", why)
        spent = True
    used = rounds.count(state.read_rows(state.phase_paths(part_dir)["audit"]))
    return 0, {"ok": True, "spent": spent, "rounds": "%d/%d" % (used, cap), "why": why}


def revert(cwd, part_dir, ids, say=lambda line: None):
    """(exit code, result): {ok, head, reverted: [{id, commit, revert}], failed}. The commit of each finding is reverted,
    newest first, with no round spent; a revert that conflicts is aborted (the earlier ones stay) and exits 1. As after a merge, the
    worktree's setup runs again when a dependency file moved; a failure is exit 1 with `setup` in the result."""
    top = _top(cwd)
    _branch(top)
    if not os.path.isdir(part_dir):
        raise WaveError("--part-dir %s is not a folder" % part_dir)
    _clean(top)
    history = _commits(top, "HEAD")
    order = [sha for sha, _ in history]
    carried = dict(history)
    where = {}
    for sha, found in history:
        for i in found:
            where.setdefault(i, []).append(sha)
    chosen = []
    for i in ids:
        shas = where.get(i, [])
        if len(shas) != 1:
            raise WaveError("%s: %s" % (i, "no commit of this branch carries Fwx-Finding: %s" % i if not shas
                                       else "%d commits carry Fwx-Finding: %s, want one" % (len(shas), i)))
        mixed = sorted(set(carried[shas[0]]))
        if len(mixed) > 1:
            raise WaveError("%s: its commit %s also carries %s, so it cannot be reverted alone"
                            % (i, shas[0][:8], ", ".join(m for m in mixed if m != i)))
        chosen.append((order.index(shas[0]), i, shas[0]))
    result = {"ok": True, "head": verify.head(top), "reverted": [], "failed": None}
    for _pos, i, sha in sorted(set(chosen)):
        r = git(top, "revert", "--no-edit", sha)
        if r.returncode:
            files = [p for p in (out(top, "diff", "--name-only", "--diff-filter=U") or "").splitlines() if p]
            git(top, "revert", "--abort")
            result.update(ok=False, failed={"id": i, "commit": sha, "files": files})
            break
        result["reverted"].append({"id": i, "commit": sha, "revert": verify.head(top)})
    result["head"] = verify.head(top)
    if result["ok"] and result["reverted"] and _setup_again(top, config.setup_commands(top), result, say):
        result["ok"] = False
    return (0 if result["ok"] else 1), result


def _own_gate(run, steps):
    """None when the run's own calls allow a pass, else why not. A run that merged branches passes only through its own gate: its
    last `integrate --final` is green. The evidence row of the part is shared by every run, so without this an earlier run that
    stopped short (a wave failed, the rounds ran out) reported `pass` as soon as a later run, or a hand fix, made the head green.
    A run with no `integrate` (a `--revert` run, whose gate is `fwx verify` on the head) is left to the evidence row."""
    merges = [r for r in steps if r.get("step") == "integrate"]
    if not merges:
        return None
    finals = [r for r in merges if r.get("args", {}).get("final")]
    if not finals:
        return "run %s merged branches and never ran the gate: no `integrate --final` among its calls" % run
    last = finals[-1]
    if last.get("exit") != 0 or (last.get("result", {}).get("verify") or {}).get("rc") != 0:
        return "the last gate of run %s was red or did not run (`integrate --final` exit %s)" % (run, last.get("exit"))
    return None


def _kept(top, steps):
    """What the part report reads from the run's recorded calls, {findings, criteria, outside, tried, gaps, protected}.
    Only what a call that stands leaves counts: the unfiled `outside` items of a report that was merged (not a retry's), a pass `wave findings`
    ended (`fix`, `owner` or `done`: the `verify` call before it carries the same items), a round that was spent, and the findings of a
    `wave merge --findings` that was ok."""
    found = {"reported": 0, "fix": 0, "consider": [], "note": [], "dismissed": [], "fixed": [], "outside": []}
    criteria, outside, tried, gaps, protected, severity, merged = {}, [], [], [], [], {}, []
    for rec in steps:
        res, args, step = rec.get("result"), rec.get("args"), rec.get("step")
        res, args = res if isinstance(res, dict) else {}, args if isinstance(args, dict) else {}
        if isinstance(res.get("gap"), str) and res["gap"] not in gaps:
            gaps.append(res["gap"])
        if step == "report" and res.get("next") == "merge":
            outside += [o for o in res.get("outside") or [] if isinstance(o, dict) and o.get("issue") is None]
        elif step == "findings":
            for c in res.get("criteria") or []:
                if isinstance(c, dict) and "id" in c:
                    criteria[c["id"]] = c
            if res.get("next") in ("fix", "owner", "done"):
                found["reported"] += res.get("reported") or 0
                found["fix"] += len(res.get("fix") or [])
                for f in res.get("fix") or []:
                    severity[f.get("id")] = f.get("severity")
                for group in ("consider", "note", "dismissed"):
                    found[group] += res.get(group) or []
                found["outside"] += res.get("file") or []
        elif step == "fix-round" and res.get("ok") is True:
            text = _oneline(res.get("why", ""), 400)
            tried.append("%s: %s" % (res["rounds"], text) if res.get("rounds") else text)
        elif step == "integrate":
            if args.get("findings") and res.get("ok") is True:
                merged += [i for i in args["findings"] if i not in merged]
            if args.get("final"):
                protected = list(res.get("protected") or [])
    commit = {}
    if merged:
        for sha, ids in _commits(top, "HEAD"):
            for i in ids:
                commit.setdefault(i, sha)
    found["fixed"] = [{"id": i, "commit": commit.get(i), "severity": severity.get(i)} for i in merged]
    return {"findings": found, "criteria": list(criteria.values()), "outside": outside, "tried": tried, "gaps": gaps, "protected": protected}


def summary(cwd, part_dir, run=None, steps=()):
    """(exit code, result): {gate, head, evidence_line, rounds, why} and what `_kept` reads from the run's calls. `pass` when the last evidence row of the part is green and is
    HEAD's, and the run `run` (whose calls are `steps`) passed its own gate (`_own_gate`); `fail` when it is red or another
    commit's, or the run did not pass its gate (exit 1, `why` says it); `none` with no evidence row or no part (exit 2)."""
    top = _top(cwd)
    head = verify.head(top)
    kept = _kept(top, steps)
    if not part_dir:
        return 2, dict({"gate": "none", "head": head, "evidence_line": "", "rounds": None, "why": ""}, **kept)
    rows = state.read_rows(state.phase_paths(part_dir)["audit"])
    cap = rounds.cap(part_dir)
    used = "%d/%d" % (rounds.count(rows), cap)
    seen = [r for r in rows if r.get("kind") == "evidence"]
    if not seen:
        return 2, dict({"gate": "none", "head": head, "evidence_line": "", "rounds": used, "why": ""}, **kept)
    last = seen[-1]
    rc, sha = last.get("rc", "").strip(), last.get("sha", "")
    why = _own_gate(run, steps) if run else None
    gate = "pass" if rc == "0" and sha == head and not why else "fail"
    try:
        commands = json.loads(last.get("detail", ""))["commands"]
        line = verify.evidence_line(sha, commands)
    except (ValueError, KeyError, TypeError):
        line = "evidence %s rc=%s" % (sha, rc)
    return (0 if gate == "pass" else 1), dict({"gate": gate, "head": head, "evidence_line": line, "rounds": used, "why": why or ""}, **kept)
