#!/usr/bin/env python3
"""`fwx project state`: open PRs, default-branch CI and open Linear issues, with a fake `gh` first on PATH and a fake Linear
on 127.0.0.1 (port 0, no network). Every case runs bin/fwx as a subprocess in a toy repo whose .claude/fwx.json names the Linear
project. A control is the same case run against a copy of bin, lib and data with one line changed, and it must fail; the last
block of main() does that (each `old` must be in the file, so a control that no longer matches the code is an error).

Seen red with the route of `project state` taken out of lib/fwx/routes.py (39 checks, 35 failed, the first lines):
  FAIL: all armed: the JSON: Expecting value: line 1 column 1 (char 0); stdout '' stderr "fwx: unknown command: project ...
  FAIL: all armed: exit 0: got 2, want 0
  FAIL: all armed: the PRs: got [], want [(7, 'fix/red'), (8, 'feat/green')]

Controls, each seen red on one changed line (the first FAIL it raised):
  - a gh with no login answers an empty list instead of not_run:
      FAIL: no gh login: open_prs is not_run, not a list: got []
  - a gh with no login is not told from a failing gh (4 failed):
      FAIL: no gh login: open_prs is not_run, not a list: got {'error': 'gh api repos/{owner}/{repo}/pulls?state=open&per_page=100&page=1 failed (4): To get started with GitHub CLI, ...
  - any gh message that names a login or a token is read as a missing login (the first version of the check; 4 failed):
      FAIL: gh badtoken: an error, not a not_run: got {'not_run': 'gh has no login: gh: Bad credentials (HTTP 401): install the GitHub CLI and log in with ...
      FAIL: gh badtoken: exit 1: got 77, want 1
  - the default branch's CI always says success:
      FAIL: all armed: default_branch_ci: got ('master', 'success', '.../commit/ccc/checks'), want ('master', 'failure', '.../commit/ccc/checks')
  - Linear's closed states are not filtered out:
      FAIL: all armed: the open issues: got ['TOY-1', 'TOY-2', 'TOY-3', 'TOY-4'], want ['TOY-1', 'TOY-2']
  - only the first page of issues is read:
      FAIL: 101 open issues: all of them: got 100, want 101
  - a missing LINEAR_API_KEY is not a not_run:
      FAIL: no key: open_issues is not_run: got {'error': 'a Linear client needs an API key and a project name'}
  - a section that did not run exits 0:
      FAIL: no key: exit 77: got 0, want 77
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import http.server

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
CFG = {"schema": 1, "project": {"linear_project": "toy-project"}}
GH = """#!%s
import json, os, sys
if os.environ.get("FAKE_GH_MODE") == "nologin":
    sys.stderr.write("To get started with GitHub CLI, please run:  gh auth login\\nAlternatively, populate the GH_TOKEN environment variable.\\n")
    sys.exit(4)
if os.environ.get("FAKE_GH_MODE") == "badtoken":
    sys.stderr.write("gh: Bad credentials (HTTP 401)\\nset GH_TOKEN to a valid token\\n")
    sys.exit(1)
if os.environ.get("FAKE_GH_MODE") == "nonhub":
    sys.stderr.write("unable to expand placeholder in path: none of the git remotes point to a known GitHub host. To tell gh about a new GitHub host, please use `gh auth login`\\n")
    sys.exit(1)
if os.environ.get("FAKE_GH_MODE") == "down":
    sys.stderr.write("gh: HTTP 500 server error\\n")
    sys.exit(1)
path = sys.argv[sys.argv.index("GET") + 1].split("?")[0]
table = json.load(open(os.environ["FAKE_GH_TABLE"]))
if path not in table:
    sys.stderr.write("fake gh: no answer for " + path + "\\n")
    sys.exit(1)
print(json.dumps(table[path]))
""" % sys.executable
R = "repos/{owner}/{repo}"


def run(name, conclusion="success", status="completed"):
    return {"name": name, "status": status, "conclusion": conclusion, "id": 1, "started_at": "t0"}


def gh_table(main_runs):
    return {
        R + "/pulls": [{"number": 7, "title": "red one", "head": {"ref": "fix/red", "sha": "aaa"}},
                       {"number": 8, "title": "green one", "head": {"ref": "feat/green", "sha": "bbb"}}],
        R + "/commits/aaa/check-runs": {"check_runs": [run("tests", "failure"), run("lint")]},
        R + "/commits/bbb/check-runs": {"check_runs": [run("tests"), run("lint")]},
        R: {"default_branch": "master"},
        R + "/commits/master": {"sha": "ccc", "html_url": "https://github.example.test/o/r/commit/ccc"},
        R + "/commits/ccc/check-runs": {"check_runs": main_runs},
        **{R + "/commits/%s/status" % s: {"statuses": []} for s in ("aaa", "bbb", "ccc")},
    }


class Linear:
    """An in-memory Linear: `issues(` pages by cursor (an offset) and honours the closed state types it is sent."""

    def __init__(self, issues):
        self.issues, self.requests = issues, []
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["content-length"])))
                fake.requests.append(req)
                v = req["variables"]
                hits = [i for i in fake.issues if i["project"] == v["project"] and i["state"][1] not in v["done"]]
                start = int(v["after"] or 0)
                page = hits[start:start + 100]
                more = start + 100 < len(hits)
                nodes = [{"identifier": i["id"], "title": i["title"], "description": "", "updatedAt": "t0",
                          "state": {"name": i["state"][0], "type": i["state"][1]}, "labels": {"nodes": []},
                          "project": {"name": i["project"]}, "assignee": None, "url": "https://linear.example.test/" + i["id"]}
                         for i in page]
                body = json.dumps({"data": {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": more,
                                                                                    "endCursor": str(start + 100) if more else None}}}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = "http://127.0.0.1:%d/graphql" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def issue(ident, state=("Todo", "unstarted"), project="toy-project"):
    return {"id": ident, "title": "title of " + ident, "state": state, "project": project}


def tree(changes):
    dest = helpers.mkdtemp("fwx-project-state-")
    for d in ("bin", "lib", "data"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(dest, d), ignore=shutil.ignore_patterns("__pycache__"))
    for rel, pairs in changes.items():
        p = os.path.join(dest, rel)
        text = open(p, encoding="utf-8").read()
        for old, new in pairs:
            assert old in text, "control: %r is not in %s" % (old, rel)
            text = text.replace(old, new, 1)
        open(p, "w", encoding="utf-8").write(text)
    return dest


class World:
    """The fake gh (a script on PATH, its answers in a file), a PATH without gh, and the toy repos."""

    def __init__(self):
        self.dir = helpers.mkdtemp("fwx-project-state-world-")
        self.bin = os.path.join(self.dir, "bin")
        self.nogh = os.path.join(self.dir, "nogh")
        os.makedirs(self.bin)
        os.makedirs(self.nogh)
        with open(os.path.join(self.bin, "gh"), "w") as f:
            f.write(GH)
        os.chmod(os.path.join(self.bin, "gh"), 0o755)
        os.symlink(shutil.which("git"), os.path.join(self.nogh, "git"))
        self.table = os.path.join(self.dir, "table.json")
        self.repo = helpers.toy_repo({".claude/fwx.json": json.dumps(CFG), "README": "toy\n"})
        self.unpinned = helpers.toy_repo({".claude/fwx.json": json.dumps({"schema": 1}), "README": "toy\n"})

    def go(self, root, fake, table=None, mode=None, key="key-1", gh_on_path=True, repo=None, args=("--json",)):
        json.dump(table if table is not None else gh_table([run("ci")]), open(self.table, "w"))
        e = helpers.clean_env()
        for k in list(e):
            if k.lower().endswith("_proxy") or k in ("LINEAR_API_KEY", "FWX_LINEAR_ENDPOINT", "FAKE_GH_MODE"):
                del e[k]
        e["no_proxy"] = "*"
        e["PATH"] = self.bin + os.pathsep + os.environ["PATH"] if gh_on_path else self.nogh
        e["FAKE_GH_TABLE"] = self.table
        if mode:
            e["FAKE_GH_MODE"] = mode
        if key:
            e["LINEAR_API_KEY"] = key
        if fake is not None:
            e["FWX_LINEAR_ENDPOINT"] = fake.url
        return subprocess.run([sys.executable, os.path.join(root, "bin", "fwx"), "project", "state"] + list(args),
                              cwd=repo or self.repo, env=e, capture_output=True, text=True, timeout=60)


def parse(s, label, r):
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        s.ok("%s: the JSON" % label, False, "%s; stdout %r stderr %r" % (e, r.stdout, r.stderr))
        return {}


def case_armed(s, root, w):
    f = Linear([issue("TOY-1"), issue("TOY-2", ("In Progress", "started")), issue("TOY-3", ("Done", "completed")),
                issue("TOY-4", ("Canceled", "canceled")), issue("OTH-1", project="other-project")])
    r = w.go(root, f, gh_table([run("ci", "failure"), run("docs")]))
    got = parse(s, "all armed", r)
    s.eq("all armed: exit 0", r.returncode, 0)
    s.eq("all armed: the PRs", [(p.get("number"), p.get("head")) for p in got.get("open_prs", [])], [(7, "fix/red"), (8, "feat/green")])
    s.eq("all armed: a PR's checks", (got.get("open_prs", []) + [{}])[0].get("checks"),
         [{"name": "tests", "state": "failure"}, {"name": "lint", "state": "success"}])
    ci = got.get("default_branch_ci", {})
    s.eq("all armed: default_branch_ci", (ci.get("branch"), ci.get("conclusion"), ci.get("url")),
         ("master", "failure", "https://github.example.test/o/r/commit/ccc/checks"))
    s.eq("all armed: the open issues", [i.get("id") for i in got.get("open_issues", [])], ["TOY-1", "TOY-2"])
    s.eq("all armed: an issue's shape", (got.get("open_issues", []) + [{}, {}])[1], {"id": "TOY-2", "title": "title of TOY-2", "status": "In Progress"})
    s.eq("all armed: nothing says NOT RUN", "NOT RUN" in r.stderr, False)
    f.close()
    r = w.go(root, None, gh_table([run("ci"), run("slow", "success", "in_progress")]), key=None)
    got = parse(s, "pending ci", r)
    s.eq("a running check: the default branch is pending", got.get("default_branch_ci", {}).get("conclusion"), "pending")


def case_text(s, root, w):
    f = Linear([issue("TOY-1")])
    r = w.go(root, f, args=())
    s.eq("text: exit 0", r.returncode, 0)
    s.ok("text: lines for the three sections", all(x in r.stdout for x in ("open_prs: 2", "#7", "default_branch_ci: success on master", "TOY-1")),
         r.stdout)
    r = w.go(root, f, args=("--nope",))
    s.eq("usage: an unknown argument is exit 2", r.returncode, 2)
    f.close()


def case_empty(s, root, w):
    f = Linear([])
    t = gh_table([run("ci")])
    t[R + "/pulls"] = []
    r = w.go(root, f, t)
    got = parse(s, "empty", r)
    s.eq("armed with nothing open: empty lists, not not_run", (got.get("open_prs"), got.get("open_issues"), r.returncode), ([], [], 0))
    f.close()


def case_pages(s, root, w):
    f = Linear([issue("TOY-%d" % n) for n in range(1, 102)])
    r = w.go(root, f)
    got = parse(s, "101 open issues", r)
    s.eq("101 open issues: all of them", len(got.get("open_issues", [])), 101)
    s.eq("101 open issues: two requests", len(f.requests), 2)
    f.close()


def case_nologin(s, root, w):
    f = Linear([issue("TOY-1")])
    r = w.go(root, f, mode="nologin")
    got = parse(s, "no gh login", r)
    for sec in ("open_prs", "default_branch_ci"):
        v = got.get(sec)
        s.ok("no gh login: %s is not_run, not a list" % sec, isinstance(v, dict) and "gh auth login" in v.get("not_run", ""), "got %r" % (v,))
    s.eq("no gh login: Linear is still answered", [i.get("id") for i in got.get("open_issues", [])], ["TOY-1"])
    s.eq("no gh login: exit 77", r.returncode, 77)
    s.ok("no gh login: stderr says NOT RUN, NOT ARMED per section",
         "NOT RUN, NOT ARMED: open_prs" in r.stderr and "NOT RUN, NOT ARMED: default_branch_ci" in r.stderr, r.stderr)
    f.close()


def case_nogh(s, root, w):
    f = Linear([issue("TOY-1")])
    r = w.go(root, f, gh_on_path=False)
    got = parse(s, "no gh installed", r)
    s.ok("no gh installed: open_prs is not_run", isinstance(got.get("open_prs"), dict) and "not_run" in got["open_prs"], "got %r" % got.get("open_prs"))
    s.eq("no gh installed: exit 77", r.returncode, 77)
    f.close()


def case_gh_down(s, root, w):
    f = Linear([issue("TOY-1")])
    r = w.go(root, f, mode="down")
    got = parse(s, "gh down", r)
    s.ok("gh down: an error, not a not_run", "error" in got.get("open_prs", {}) and "not_run" not in got.get("open_prs", {}), "got %r" % got.get("open_prs"))
    s.eq("gh down: exit 1", r.returncode, 1)
    f.close()


def case_gh_armed_failing(s, root, w):
    f = Linear([issue("TOY-1")])
    for mode in ("badtoken", "nonhub"):
        r = w.go(root, f, mode=mode)
        got = parse(s, "gh " + mode, r)
        v = got.get("open_prs", {})
        s.ok("gh %s: an error, not a not_run" % mode, "error" in v and "not_run" not in v, "got %r" % (v,))
        s.eq("gh %s: exit 1" % mode, r.returncode, 1)
    f.close()


def case_nokey(s, root, w):
    f = Linear([issue("TOY-1")])
    r = w.go(root, f, key=None)
    got = parse(s, "no key", r)
    v = got.get("open_issues")
    s.ok("no key: open_issues is not_run", isinstance(v, dict) and "LINEAR_API_KEY" in v.get("not_run", ""), "got %r" % (v,))
    s.eq("no key: no request reached Linear", len(f.requests), 0)
    s.eq("no key: gh is still answered", len(got.get("open_prs", [])), 2)
    s.eq("no key: exit 77", r.returncode, 77)
    s.ok("no key: stderr says NOT RUN, NOT ARMED", "NOT RUN, NOT ARMED: open_issues" in r.stderr, r.stderr)
    r = w.go(root, f, repo=w.unpinned)
    v = parse(s, "no project", r).get("open_issues")
    s.ok("no linear_project: open_issues is not_run", isinstance(v, dict) and "linear_project" in v.get("not_run", ""), "got %r" % (v,))
    s.eq("no linear_project: no request reached Linear", len(f.requests), 0)
    f.close()


CASES = [case_armed, case_text, case_empty, case_pages, case_nologin, case_nogh, case_gh_down, case_gh_armed_failing, case_nokey]
GH_PY, LIN_PY, CMD_PY = "lib/fwx/core/gh.py", "lib/fwx/linear.py", "lib/fwx/commands/project_state.py"
CONTROLS = [
    ("a gh with no login answers an empty list", case_nologin, "open_prs is not_run, not a list",
     {CMD_PY: [('return {"not_run": "%s: %s" % (e, GH_FIX)}', "return []")]}),
    ("a gh with no login is a failing gh", case_nologin, "exit 77",
     {GH_PY: [('if r.returncode == NO_LOGIN_EXIT and (r.stderr or "").startswith(_NO_LOGIN):', "if False:")]}),
    ("any gh message that names a login or token is a missing login", case_gh_armed_failing, "an error, not a not_run",
     {GH_PY: [('if r.returncode == NO_LOGIN_EXIT and (r.stderr or "").startswith(_NO_LOGIN):',
               'if re.search(r"gh auth login|GH_TOKEN|HTTP 401", r.stderr or ""):')]}),
    ("the default branch's CI always success", case_armed, "default_branch_ci",
     {GH_PY: [("states = [c[\"state\"] for c in head_checks(sha, cwd)[0]]", "states = []")]}),
    ("closed Linear states are not filtered", case_armed, "the open issues",
     {LIN_PY: [('DONE_TYPES = ("completed", "canceled")', "DONE_TYPES = ()")]}),
    ("only the first page of issues", case_pages, "all of them",
     {LIN_PY: [('if not page.get("hasNextPage"):', "if True:")]}),
    ("a missing key is not a not_run", case_nokey, "open_issues is not_run",
     {CMD_PY: [("if not key:", "if False:")]}),
    ("a section that did not run exits 0", case_nokey, "exit 77",
     {CMD_PY: [('return 77 if any("not_run" in v for v in sections) else 0', "return 0")]}),
]


def main():
    s = helpers.Suite()
    if shutil.which("git") is None:
        s.not_run("git is not installed")
    w = World()
    for case in CASES:
        case(s, ROOT, w)
    print("%d checks on the command" % s.checks)
    for name, case, needle, changes in CONTROLS:
        root = tree(changes)
        c = helpers.Suite()
        case(c, root, w)
        hit = [l for l in c.fails if needle in l]
        s.ok("control %s: fails with %r" % (name, needle), hit, "its failures: %r" % c.fails[:3])
        shutil.rmtree(root, ignore_errors=True)
    s.done()


if __name__ == "__main__":
    main()
