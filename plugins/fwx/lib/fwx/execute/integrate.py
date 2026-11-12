"""The only path that writes the phase branch, and the one place that spends a round (3.4 U3; shapes in C.2 of the plan).

Only this module runs `git merge` and `git revert`; nothing in lib/fwx/ runs `git rebase`, `git push` or `git reset --hard`
(tests/test_single_writer.py reads the code to check it). No function here writes a `stage` row, and only `fix_round` writes a
round.

`integrate(cwd, ...)` merges the branches of a wave into the branch the checkout `cwd` is on, with `--no-ff`, in the order
given. It refuses (exit 2, nothing merged) a checkout with uncommitted changes, a branch whose worktree holds a live agent
(`cleanup.lock_state`: the pid lives and its start time is the lock's; a dead agent's lock does not stop it), and, with
`findings`, a set of branches whose commits are not exactly one `Fwx-Finding: <id>` commit per finding. At the first conflict
it aborts that merge and stops (the earlier ones stay). Then it runs the project's `worktree_setup` again in the checkout (a no-op unless a merge changed a dependency file; a failure
stops here with `setup` in the result and exit 1) and then `project.checks_quick`, removes the
worktrees of the branches it merged (only unlocked, clean ones: a stale lock is `cleanup`'s), and, with `final` and everything
green, runs the gate (`core.verify`) and reports the trusted edits (with a `worktree_setup`, also the files it installs from: core.trusted) and the protected paths of
`<base>..HEAD`, `base` being the sha in the run id. It reports; it spends no round. With `final` and no branch nothing is merged: it is the gate on the head as it
is (the re-entry of `prepare --from gate`).

`fix_round(cwd, part_dir, why)` decides whether a failure may be fixed and spends the round for it. If the last audit row is
the red evidence of the checkout's HEAD, `verify` already made that failure a round and nothing more is spent. A failure is
allowed only when fewer than `rounds` were spent before it: the third round is fixed, only the failure after it ends the job.

`revert(cwd, part_dir, finding_ids)` reverts the commit of each finding, the newest first, and then runs the setup again like `integrate`
(`setup` in the result on a failure). `summary(...)` says whether the gate
of the run passes. Imports the standard library, fwx.state, fwx.config, fwx.core and execute.base, cleanup and worktree_setup.
"""
import json
import os

from fwx import config, state
from fwx.core import decide, evidence, globs, rounds, trusted, verify
from fwx.execute import cleanup, worktree_setup
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


def _quick(top, cfg):
    """{ran, cmds, rc}: project.checks_quick, run in the checkout; rc is 0 or the first exit that is not."""
    cmds = evidence.plan_checks(cfg["project"]["checks_quick"], os.devnull)
    rc = 0
    for c in cmds:
        got = verify.run_check(c, top)["rc"]
        if got != 0 and rc == 0:
            rc = 1 if got is None else got
    return {"ran": bool(cmds), "cmds": cmds, "rc": rc}


def _changed(top, base):
    r = git(top, "diff", "--name-only", "%s..HEAD" % base)
    if r.returncode:
        raise WaveError("git diff %s..HEAD failed: %s" % (base, r.stderr.strip()))
    return [p for p in r.stdout.splitlines() if p]


def integrate(cwd, part_dir, run, branches, findings=(), final=False, say=lambda line: None):
    """(exit code, result). The result is C.2's: {ok, head, merged, conflict, locked, findings_check, quick, verify, trusted,
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
    result = {"ok": False, "head": verify.head(top), "merged": [], "conflict": None, "locked": [],
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
    result["quick"] = _quick(top, cfg)
    result["ok"] = result["quick"]["rc"] == 0
    if final and result["ok"]:
        code, ev = verify.verify(top, part_dir, say)
        result["verify"] = {"ran": True, "rc": code, "line": verify.evidence_line(ev["sha"], ev["commands"]) if ev else ""}
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


def summary(cwd, part_dir, run=None, steps=()):
    """(exit code, result): {gate, head, evidence_line, rounds, why}. `pass` when the last evidence row of the part is green and is
    HEAD's, and the run `run` (whose calls are `steps`) passed its own gate (`_own_gate`); `fail` when it is red or another
    commit's, or the run did not pass its gate (exit 1, `why` says it); `none` with no evidence row or no part (exit 2)."""
    top = _top(cwd)
    head = verify.head(top)
    if not part_dir:
        return 2, {"gate": "none", "head": head, "evidence_line": "", "rounds": None, "why": ""}
    rows = state.read_rows(state.phase_paths(part_dir)["audit"])
    cap = rounds.cap(part_dir)
    used = "%d/%d" % (rounds.count(rows), cap)
    seen = [r for r in rows if r.get("kind") == "evidence"]
    if not seen:
        return 2, {"gate": "none", "head": head, "evidence_line": "", "rounds": used, "why": ""}
    last = seen[-1]
    rc, sha = last.get("rc", "").strip(), last.get("sha", "")
    why = _own_gate(run, steps) if run else None
    gate = "pass" if rc == "0" and sha == head and not why else "fail"
    try:
        commands = json.loads(last.get("detail", ""))["commands"]
        line = verify.evidence_line(sha, commands)
    except (ValueError, KeyError, TypeError):
        line = "evidence %s rc=%s" % (sha, rc)
    return (0 if gate == "pass" else 1), {"gate": gate, "head": head, "evidence_line": line, "rounds": used, "why": why or ""}
