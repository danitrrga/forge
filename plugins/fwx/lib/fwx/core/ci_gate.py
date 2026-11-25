"""GitHub CI as the gate of the end of a part (D26), and as the check of a base (D22).

`run(root, sha, cfg, say, timeout, protected)` is the gate `verify.verify(ci=True)` takes before it runs the project's checks. With a
GitHub origin, the CI workflow `CI_WORKFLOW` at `sha` and a `gh` that answers, it pushes the checkout's branch (`git push origin
refs/heads/<b>:refs/heads/<b>`: never forced, never a branch of `protected`, the default and production branches), finds the open pull
request of that branch or opens a draft one (once), and polls the `pull_request` runs of that workflow on `sha` until all are completed.
It returns the evidence dict, `{sha, clean, source: "ci", commands, rc}`: green (rc 0, one command `ci:<workflow>:run-<ids>` with rc 0)
only when at least one run ended and all ended `success`; red (rc 1, one command per failed job, `ci:<workflow>:run-<id>:<job>`, the run's
URL said) when one ended `failure`. It returns None, after one `say` line, for every other case, and the caller runs the local gate: no
branch or a protected one, no GitHub origin, no CI file at `sha`, `gh` missing or not answering, a push that was rejected or failed, a
pull request that conflicts (CI does not run on it: it stops the wait at once), a run that ended any other way (cancelled, skipped), no
run within `NO_RUN_S`, no result within `timeout`. Fail closed, as the base check does: not being able to ask is never green.

The only `git push` of lib/fwx is here, and it is not forced (tests/test_single_writer.py reads the code to check it): the gate runs
inside `fwx wave run`, where no session step can come between the final merge and the review, and a push writes the remote, not the branch.
`FWX_CI_POLL_S` and `FWX_CI_NO_RUN_S` shorten the two waits, for the tests.

`base_green(top, base, say, cfg)` is D22's check of a base that came from the default branch: a green push run of `CI_WORKFLOW` on `base`.

Imports the standard library, core.evidence and core.gh.
"""
import os
import re
import subprocess
import time
from urllib.parse import quote

from fwx.core import evidence, gh

CI_WORKFLOW = ".github/workflows/ci.yml"  # the workflow whose last job is `All checks`; on a push to the default branch it runs every suite
CI_TIMEOUT_S = 20  # one `gh api` of the base check
GIT_TIMEOUT_S = 30
PUSH_TIMEOUT_S = 120
POLL_S = 15.0
NO_RUN_S = 300.0  # how long a pushed sha may have no run before CI is taken for not running it
_GITHUB = re.compile(r"(?:https?://(?:[^/@]+@)?|ssh://git@|git@)github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?\Z")


def _git(root, *args, timeout=GIT_TIMEOUT_S):
    """git in `root`, never asking for a password: the CompletedProcess, or one with exit 124 (out of time) or 127 (no git)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(args), 124, "", "git %s did not finish in %d s" % (args[0], timeout))
    except OSError as e:
        return subprocess.CompletedProcess(list(args), 127, "", "cannot run git (%s)" % e)


def _first_line(text, limit=160):
    return ((text or "").strip().splitlines() or [""])[0][:limit]


def _seconds(name, default):
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _repo(root):
    """((owner, repo), why not): the GitHub repository of `origin`."""
    r = _git(root, "remote", "get-url", "origin")
    url = r.stdout.strip() if r.returncode == 0 else ""
    found = _GITHUB.match(url)
    if not found:
        return None, "the origin is not a GitHub repository" if url else "no origin remote"
    return found.groups(), None


def base_green(top, base, say, cfg):
    """True only when GitHub has run `CI_WORKFLOW` on a push of the sha `base` to `project.default_branch` (that one name), at least once, and
    every such run is completed with the conclusion success. A pull request run of the same sha does not count: it may skip suites, and the
    sha of a merged pull request head has only that. Anything else, including not being able to ask, is False with one stderr line saying
    why: the caller then runs the checks here. No row is written for a CI answer: no check ran here."""
    def no(why):
        say("base checks: CI not used (%s); running the checks here" % why)
        return False

    branch = ((cfg or {}).get("project") or {}).get("default_branch")
    if not isinstance(branch, str) or not branch:
        return no("project.default_branch is not set")
    found, why = _repo(top)
    if not found:
        return no(why)
    api = "repos/%s/%s/actions/runs?head_sha=%s&event=push&branch=%s&per_page=100" % (found[0], found[1], base, quote(branch, safe=""))
    try:
        r = subprocess.run(["gh", "api", api, "--jq", '.workflow_runs[] | [.path, .status, (.conclusion // "")] | @tsv'], cwd=top,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=CI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return no("gh did not answer in %d s" % CI_TIMEOUT_S)
    except OSError as e:
        return no("cannot run gh: %s" % e)
    if r.returncode != 0:
        return no("gh failed: %s" % ((r.stderr.strip().splitlines() or ["exit %d" % r.returncode])[0][:120]))
    rows = [line.split("\t") + ["", ""] for line in r.stdout.splitlines()]
    got = [(x[1], x[2]) for x in rows if x[0] == CI_WORKFLOW]
    if not got:
        return no("no push run of %s for %s on %s" % (CI_WORKFLOW, base[:7], branch))
    bad = sorted({" ".join(x).strip() for x in got if x != ("completed", "success")})
    if bad:
        return no("%s on %s is %s" % (CI_WORKFLOW, branch, ", ".join(bad)))
    say("base checks: CI passed %s (%s on %s, success)" % (base[:7], CI_WORKFLOW, branch))
    return True


def _pull(root, owner, repo, branch, cfg, say):
    """The number of the open pull request from `branch`: the one that exists, else a draft opened now (to the default branch)."""
    base = "repos/%s/%s" % (owner, repo)
    open_ = gh.api("%s/pulls?state=open&head=%s" % (base, quote("%s:%s" % (owner, branch), safe=":/")), cwd=root)
    if isinstance(open_, list) and open_ and isinstance(open_[0], dict) and isinstance(open_[0].get("number"), int):
        return open_[0]["number"]
    target = ((cfg.get("project") or {}).get("default_branch")) or (gh.api(base, cwd=root) or {}).get("default_branch")
    if not isinstance(target, str) or not target:
        raise gh.GhError("the default branch of %s/%s is not known: set project.default_branch" % (owner, repo))
    made = gh.api("%s/pulls" % base, "POST", {"title": "fwx: %s" % branch, "head": branch, "base": target, "draft": True,
                                              "body": "Opened by the fwx gate so that CI runs on the phase branch. The session marks it ready at the close."}, cwd=root)
    if not isinstance(made, dict) or not isinstance(made.get("number"), int):
        raise gh.GhError("GitHub did not answer with the number of the draft pull request")
    say("opened draft pull request #%d for %s" % (made["number"], branch))
    return made["number"]


def _runs(root, owner, repo, sha):
    """The `pull_request` runs of `CI_WORKFLOW` on `sha`: [{id, status, conclusion, html_url}]."""
    got = gh.api("repos/%s/%s/actions/runs?head_sha=%s&event=pull_request&per_page=100" % (owner, repo, sha), cwd=root) or {}
    runs = got.get("workflow_runs") if isinstance(got, dict) else None
    if not isinstance(runs, list):
        raise gh.GhError("GitHub answered the runs of %s with no workflow_runs" % sha[:7])
    return [r for r in runs if isinstance(r, dict) and str(r.get("path") or "").split("@")[0] == CI_WORKFLOW]


def _evidence(sha, commands, rc):
    return {"sha": sha, "clean": True, "source": evidence.CI_SOURCE, "commands": commands, "rc": rc}


def _verdict(root, owner, repo, sha, runs, say):
    """(evidence, None) for finished runs that decide the gate, (None, why) when they do not (the local gate then runs)."""
    failed = [r for r in runs if r.get("conclusion") == "failure"]
    if failed:
        commands, urls = [], []
        for r in failed:
            jobs = []
            try:
                if not isinstance(r.get("id"), int):
                    raise gh.GhError("the run has no numeric id")
                got = gh.api("repos/%s/%s/actions/runs/%s/jobs?per_page=100" % (owner, repo, r.get("id")), cwd=root) or {}
                jobs = [j.get("name") for j in got.get("jobs") or [] if isinstance(j, dict) and j.get("conclusion") == "failure" and j.get("name")]
            except gh.GhError:
                pass  # the names are for the fixer; the run itself is red either way
            url = r.get("html_url") if isinstance(r.get("html_url"), str) and r.get("html_url") else ""
            if url and url not in urls:
                urls.append(url)
            say("CI failed at %s: run %s, failed jobs: %s, %s" % (sha[:7], r.get("id"), ", ".join(jobs) or "none named", url or "no URL"))
            commands += [{"cmd": "ci:%s:run-%s:%s" % (CI_WORKFLOW, r.get("id"), j), "rc": 1} for j in jobs] or [{"cmd": "ci:%s:run-%s" % (CI_WORKFLOW, r.get("id")), "rc": 1}]
        ev = _evidence(sha, commands, 1)
        if urls:
            ev["urls"] = urls
        return ev, None
    odd = sorted({"run %s ended %s" % (r.get("id"), r.get("conclusion") or "with no conclusion") for r in runs if r.get("conclusion") != "success"})
    if odd:
        return None, "; ".join(odd)
    ids = ",".join(str(r.get("id")) for r in runs)
    return _evidence(sha, [{"cmd": "ci:%s:run-%s" % (CI_WORKFLOW, ids), "rc": 0}], 0), None


def run(root, sha, cfg, say, timeout, protected):
    """The evidence of the CI run of `sha`, or None when the local gate must run (module docstring). `say` receives the progress lines."""
    def no(why):
        say("CI gate not used (%s); running the checks here" % why)
        return None

    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
    if not branch:
        return no("the checkout is on no branch")
    if branch in protected:
        return no("%s is a default or a production branch: the gate never pushes it" % branch)
    found, why = _repo(root)
    if not found:
        return no(why)
    owner, repo = found
    if _git(root, "cat-file", "-e", "%s:%s" % (sha, CI_WORKFLOW)).returncode:
        return no("%s is not at %s" % (CI_WORKFLOW, sha[:7]))
    pushed = _git(root, "push", "origin", "refs/heads/%s:refs/heads/%s" % (branch, branch), timeout=PUSH_TIMEOUT_S)
    if pushed.returncode:
        return no("the push of %s failed: %s" % (branch, _first_line(pushed.stderr or pushed.stdout)))
    say("pushed %s at %s" % (branch, sha[:7]))
    poll, patience, started = _seconds("FWX_CI_POLL_S", POLL_S), _seconds("FWX_CI_NO_RUN_S", NO_RUN_S), time.monotonic()
    try:
        number = _pull(root, owner, repo, branch, cfg, say)
        say("waiting for CI on pull request #%d" % number)
        while True:
            if (gh.api("repos/%s/%s/pulls/%d" % (owner, repo, number), cwd=root) or {}).get("mergeable") is False:
                return no("pull request #%d conflicts with its base, and CI does not run on a conflicting pull request" % number)
            runs = _runs(root, owner, repo, sha)
            waited = time.monotonic() - started
            if runs and all(r.get("status") == "completed" for r in runs):
                ev, why = _verdict(root, owner, repo, sha, runs, say)
                return ev if ev else no(why)
            if not runs and waited >= patience:
                return no("no run of %s for %s in %d s" % (CI_WORKFLOW, sha[:7], patience))
            if waited >= timeout:
                return no("no result from CI in %d s (project.check_timeout_s)" % timeout)
            time.sleep(poll)
    except gh.GhError as e:
        return no(_first_line(str(e)))
