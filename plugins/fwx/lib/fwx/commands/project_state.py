"""What a project's GitHub and Linear say right now: fwx project state [--json]

Three sections, each answered on its own:
  open_prs           [{number, title, head, checks}]   the open PRs of the repository of the current directory (gh)
  default_branch_ci  {branch, conclusion, url}         the default branch's head: success, failure or pending (gh)
  open_issues        [{id, title, status}]             every issue of `project.linear_project` not completed or canceled

A section whose tool is missing is `{"not_run": "<why and the fix>"}`, never an empty list, and the command says
`NOT RUN, NOT ARMED: <section>: <why>` on stderr: no `gh` or no `gh` login, no `LINEAR_API_KEY`, no
`project.linear_project` in .claude/fwx.json. A section that is armed but failed (GitHub or Linear unreachable, a refused key)
is `{"error": "<message>"}`. The JSON is printed whole either way; without --json the same facts are lines of text.

Exit 0 every section answered, 77 a section did not run (and none failed), 1 a section failed, 2 usage or no configuration.
`FWX_LINEAR_ENDPOINT` points the Linear client at a fake server on 127.0.0.1, as for `fwx linear`.
"""
import json
import os
import sys

from fwx import config, linear
from fwx.core import gh

USAGE = "usage: fwx project state [--json]\n"
GH_FIX = "install the GitHub CLI and log in with `gh auth login` (or export GH_TOKEN) in this checkout"
KEY = "LINEAR_API_KEY"


def _gh(fn):
    try:
        return fn()
    except gh.GhNotArmed as e:
        return {"not_run": "%s: %s" % (e, GH_FIX)}
    except gh.GhError as e:
        return {"error": str(e)}


def _issues(cfg):
    project = cfg["project"].get("linear_project")
    if not project:
        return {"not_run": "no Linear project: set project.linear_project in .claude/fwx.json"}
    key = os.environ.get(KEY)
    if not key:
        return {"not_run": "%s is not set: run `forge sync` (it puts the key in a framework project's environment) or export "
                           "your own Linear personal API key as %s" % (KEY, KEY)}
    try:
        client = linear.Client(key, project, cfg, endpoint=os.environ.get("FWX_LINEAR_ENDPOINT") or linear.ENDPOINT)
        return [{"id": i["identifier"], "title": i["title"], "status": i["state"]["name"]} for i in client.open_issues()]
    except linear.LinearError as e:
        return {"error": str(e)}


def gather(cfg, cwd=None):
    return {"open_prs": _gh(lambda: gh.open_prs(cwd)),
            "default_branch_ci": _gh(lambda: gh.default_branch_ci(cwd)),
            "open_issues": _issues(cfg)}


def _rollup(checks):
    states = [c["state"] for c in checks]
    return "failure" if "failure" in states else "pending" if "pending" in states else "success"


def text(state):
    out = []
    for name, got in state.items():
        if isinstance(got, dict) and "not_run" in got:
            out.append("%s: NOT RUN, NOT ARMED: %s" % (name, got["not_run"]))
        elif isinstance(got, dict) and "error" in got:
            out.append("%s: ERROR: %s" % (name, got["error"]))
        elif name == "default_branch_ci":
            out.append("%s: %s on %s %s" % (name, got["conclusion"], got["branch"], got["url"]))
        elif name == "open_prs":
            out.append("%s: %d" % (name, len(got)))
            out += ["  #%s  %s  [%s]  %s" % (p["number"], p["head"], _rollup(p["checks"]), p["title"]) for p in got]
        else:
            out.append("%s: %d" % (name, len(got)))
            out += ["  %s  %s  %s" % (i["id"], i["status"], i["title"]) for i in got]
    return "\n".join(out) + "\n"


def main(argv):
    args = list(argv)
    if args in (["-h"], ["--help"], ["help"]):
        sys.stdout.write(USAGE)
        return 0
    as_json = "--json" in args
    if [a for a in args if a != "--json"]:
        sys.stderr.write("fwx project state: takes only --json\n" + USAGE)
        return 2
    try:
        cfg = config.load()
    except config.ConfigError as e:
        sys.stderr.write("fwx project state: %s\n" % e)
        return 2
    state = gather(cfg)
    sys.stdout.write(json.dumps(state, indent=2) + "\n" if as_json else text(state))
    sections = [v for v in state.values() if isinstance(v, dict)]
    for name, got in state.items():
        if isinstance(got, dict) and "not_run" in got:
            sys.stderr.write("NOT RUN, NOT ARMED: %s: %s\n" % (name, got["not_run"]))
    if any("error" in v for v in sections):
        return 1
    return 77 if any("not_run" in v for v in sections) else 0
