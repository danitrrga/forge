# copied-from: marshal-factory lib/github/pulls.ts (`upsertComment`) @999ad209598517a4c826073b5a0edc2a4097a4fa, ported to
# `gh api`; the check-state table is not marshal's (its PASSING set counts `neutral` and `skipped` green) but the 5.2 decision.
"""The thin adapter over `gh api`: the one marked comment on a PR, and the PR's facts.

Every call is `gh api <path>` run in the repository's checkout (`{owner}` and `{repo}` in a path are gh's placeholders for
the checkout's remote), with the caller's environment (`gh` reads its own token). A failure of `gh` is `GhError` with gh's
own message; a list that is still full after MAX_PAGES pages is `GhError` too, because a truncated list is a wrong answer.

`upsert_comment(pr, marker, body)` edits in place the comment of the PR that carries `marker`, or creates one: it returns
`"created"`, `"updated"` or `"unchanged"` (the body already is the one asked for). The comments are read page by page.

`pr_facts(pr)` is the `pr` object of the merge decision's facts: `{number, head_sha, base, mergeable, running,
changed_files, checks, not_green}`. `mergeable` is null while GitHub computes it: then `running` is true and `mergeable`
true (the schema has a boolean; `running` holds the decision back). A changed file carries `path`, `additions`,
`deletions`, `patch` (empty when GitHub sends none) and, for a rename, `previous_path`: U3a reads package.json from the
patch. `checks` is `[{name, state}]` with state `success`, `failure` or `pending`, from the check runs of the head (only
the newest run of each name counts, Bugbot's apart) and the commit statuses; `not_green` lists what is pending without
anything running, `[{name, conclusion, why}]`.

What a check run says, table of `check_state`:
  - not completed                                                        -> pending
  - success, and its text does not say it was skipped                    -> success
  - success whose title, summary or description says `skip` (a reviewer
    that skipped its review reports success)                             -> pending, not green
  - neutral, skipped                                                     -> pending, not green
  - failure, cancelled, timed_out, action_required, startup_failure, stale -> failure
  - anything else                                                        -> pending, not green
A head with no check reported at all is pending, never success.

Imports only the standard library.
"""
import json
import re
import subprocess

PER_PAGE = 100
MAX_PAGES = 30
TIMEOUT_S = 60
FAILURES = ("failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale")
NOT_GREEN = ("neutral", "skipped")
_SKIP = re.compile(r"skip", re.I)
_BUGBOT = re.compile(r"bugbot", re.I)


class GhError(Exception):
    """`gh` failed, is missing, or answered something that is not what was asked for."""


def api(path, method="GET", body=None, cwd=None):
    """The JSON `gh api` answers for `path` (None for an empty answer). `body` (a dict) is sent as the JSON request."""
    cmd = ["gh", "api", "--method", method, path] + (["--input", "-"] if body is not None else [])
    try:
        r = subprocess.run(cmd, cwd=cwd, input=None if body is None else json.dumps(body), capture_output=True,
                           text=True, timeout=TIMEOUT_S)
    except FileNotFoundError:
        raise GhError("gh is not installed or not on PATH (the PR comment needs it)")
    except subprocess.TimeoutExpired:
        raise GhError("gh api %s did not answer within %d s" % (path, TIMEOUT_S))
    except OSError as e:
        raise GhError("cannot run gh (%s)" % e)
    if r.returncode:
        raise GhError("gh api %s failed (%d): %s" % (path, r.returncode, r.stderr.strip() or r.stdout.strip() or "no output"))
    if not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise GhError("gh api %s answered something that is not JSON: %.200s" % (path, r.stdout.strip()))


def pages(path, key=None, cwd=None):
    """Every item of a paginated list, page after page until one is not full. `key` names the list inside an object
    answer (`check_runs`); without it the answer is the list. GhError when the last allowed page is still full."""
    items = []
    for page in range(1, MAX_PAGES + 1):
        sep = "&" if "?" in path else "?"
        got = api("%s%sper_page=%d&page=%d" % (path, sep, PER_PAGE, page), cwd=cwd)
        batch = (got or {}).get(key) if key else got
        if not isinstance(batch, list):
            raise GhError("gh api %s answered %s, not a list%s" % (path, type(got).__name__, " under " + key if key else ""))
        items += batch
        if len(batch) < PER_PAGE:
            return items
    raise GhError("gh api %s still had a full page after %d pages: the list is truncated" % (path, MAX_PAGES))


def _pr_number(pr):
    if isinstance(pr, bool) or not isinstance(pr, int) or pr < 1:
        raise ValueError("a PR is a positive number, got %r" % (pr,))
    return pr


def upsert_comment(pr, marker, body, cwd=None):
    """Edit in place the comment of `pr` that carries `marker`, or create one. `body` must carry the marker too, or the
    next call would not find it. Returns `created`, `updated` or `unchanged`."""
    pr = _pr_number(pr)
    if not marker or marker not in body:
        raise ValueError("the body must carry the marker %r, or the next run could not find the comment" % (marker,))
    base = "repos/{owner}/{repo}/issues"
    for c in pages("%s/%d/comments" % (base, pr), cwd=cwd):
        if marker in (c.get("body") or ""):
            if c["body"] == body:
                return "unchanged"
            api("%s/comments/%d" % (base, c["id"]), "PATCH", {"body": body}, cwd)
            return "updated"
    api("%s/%d/comments" % (base, pr), "POST", {"body": body}, cwd)
    return "created"


def check_state(conclusion, status="completed", text=""):
    """`(state, why)` of one check run: state `success`, `failure` or `pending`, and `why` (None when the check is
    plainly green, red or still running) saying why it is pending with nothing running. `text` is the run's title and
    summary: a reviewer that skipped its review reports success there."""
    if status != "completed":
        return "pending", None
    if conclusion == "success":
        return ("pending", "success, but its text says it was skipped") if _SKIP.search(text or "") else ("success", None)
    if conclusion in FAILURES:
        return "failure", None
    if conclusion in NOT_GREEN:
        return "pending", conclusion
    return "pending", "unknown conclusion %r" % (conclusion,)


def status_state(state, description=""):
    """`(state, why)` of one commit status (`success`, `pending`, `failure`, `error`), with the same text rule."""
    if state == "success":
        return ("pending", "success, but its text says it was skipped") if _SKIP.search(description or "") else ("success", None)
    if state in ("failure", "error"):
        return "failure", None
    return "pending", None


def checks_of(runs, statuses):
    """`(checks, not_green)` from check runs (the API's objects) and commit statuses. Only the newest run of a name
    counts (`started_at`, then `id`), Bugbot's runs are left out, and no check at all is one pending entry."""
    newest = {}
    for run in runs:
        name = run.get("name", "")
        if _BUGBOT.search(name):
            continue
        key = (run.get("started_at") or "", run.get("id") or 0)
        if name not in newest or key >= newest[name][0]:
            newest[name] = (key, run)
    checks, not_green = [], []
    for name, (_, run) in newest.items():
        out = run.get("output") or {}
        text = "%s\n%s" % (out.get("title") or "", out.get("summary") or "")
        state, why = check_state(run.get("conclusion"), run.get("status"), text)
        checks.append({"name": name, "state": state})
        if why:
            not_green.append({"name": name, "conclusion": run.get("conclusion"), "why": why})
    for st in statuses:
        state, why = status_state(st.get("state"), st.get("description"))
        checks.append({"name": st.get("context", ""), "state": state})
        if why:
            not_green.append({"name": st.get("context", ""), "conclusion": st.get("state"), "why": why})
    if not checks:
        checks.append({"name": "no check reported yet", "state": "pending"})
        not_green.append({"name": "no check reported yet", "conclusion": None, "why": "nothing has reported on the head"})
    return checks, not_green


def _file(f):
    out = {"path": f.get("filename", "")}
    if f.get("previous_filename"):
        out["previous_path"] = f["previous_filename"]
    out.update(additions=f.get("additions", 0), deletions=f.get("deletions", 0), patch=f.get("patch") or "")
    return out


def pr_facts(pr, cwd=None):
    """The `pr` facts of PR number `pr` (module docstring)."""
    pr = _pr_number(pr)
    base = "repos/{owner}/{repo}"
    info = api("%s/pulls/%d" % (base, pr), cwd=cwd)
    head = ((info or {}).get("head") or {}).get("sha")
    if not isinstance(head, str) or not head:
        raise GhError("the PR %d has no head sha in gh's answer" % pr)
    files = pages("%s/pulls/%d/files" % (base, pr), cwd=cwd)
    runs = pages("%s/commits/%s/check-runs" % (base, head), "check_runs", cwd)
    statuses = []
    for page in range(1, MAX_PAGES + 1):
        got = api("%s/commits/%s/status?per_page=%d&page=%d" % (base, head, PER_PAGE, page), cwd=cwd) or {}
        batch = got.get("statuses") or []
        statuses += batch
        if len(batch) < PER_PAGE:
            break
    else:
        raise GhError("the commit statuses of %s are truncated after %d pages" % (head, MAX_PAGES))
    checks, not_green = checks_of(runs, statuses)
    mergeable = info.get("mergeable")
    return {"number": pr, "head_sha": head, "base": (info.get("base") or {}).get("ref", ""),
            "mergeable": True if mergeable is None else bool(mergeable), "running": mergeable is None,
            "changed_files": [_file(f) for f in files], "checks": checks, "not_green": not_green}
