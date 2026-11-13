#!/usr/bin/env python3
"""`fwx verify` and the `gh` adapter: core.verify, core.gh, commands/verify.py, on real repos and worktrees, with a fake `gh`.

Ports the CLI cases of marshal's evidence-regressions.ts:175-293 (passing, failing and dirty runs at the exact HEAD, every
check run, a secret in the output redacted) onto `fwx verify`, and adds the worktree, `--dir`, `.fwx/`-only, HEAD-moved and
`--pr` cases. Every program a test fakes lives alone on PATH (order 10): a directory holding symlinks to python3, git and
bash, and a fake `npm`; with `gh`, a second one that also holds the fake `gh`, which keeps its state and its calls in a JSON
file. No network, no real `gh`. The check-state table is 5.2's, row by row, not marshal's `PASSING` set.

Seen red before the code existed (core/gh.py and core/verify.py absent; the test stops at the import):
  FAIL: cannot import fwx.core.verify and fwx.core.gh: cannot import name 'gh' from 'fwx.core' (<worktree>/lib/fwx/core/__init__.py)

Controls, each seen red on a copy of the repo with one thing changed (first FAIL line shown; 152 checks on the good code):
  - the dirty-tree check is off:
      FAIL: a modified tracked file: exit 2: got 0, want 2
      FAIL: a dirty tree writes no row: got [{'date': ..., 'kind': 'evidence', ...}], want []
  - a red check exits 0:
      FAIL: a red check exits 1: got 0, want 1
  - the run stops at the first red check:
      FAIL: every check ran even after the red one: got [{'cmd': 'exit 1', 'rc': 1}], want [{'cmd': 'exit 1', 'rc': 1}, {'cmd': 'echo second; exit 0', 'rc': 0}]
  - the phase is looked for under `git rev-parse --show-toplevel` (the worktree) and not in the main checkout (the plan's control):
      FAIL: from a worktree the row lands in the main checkout's phase, with the worktree's HEAD: got [], want ['41857de1...']
      FAIL: a dirty worktree: exit 2, no new row: got (2, 0), want (2, 1)
  - `.fwx/` counts when asking whether the tree is clean:
      FAIL: a green run exits 0: got 2, want 0   (45 FAIL: the phase folder itself makes every run dirty)
  - an empty recipe is green:
      FAIL: no recipe and no package.json: exit 2: got 0, want 2
  - HEAD is not compared after the checks:
      FAIL: HEAD moving while the checks run: exit 2: got 0, want 2
      FAIL: it writes a row for the sha it started from, clean false, rc 1: got ('b968d1d6...', True, '0'), want ('b968d1d6...', False, '1')
  - the tail is not redacted, or not by variable name, or not by token shape (three copies):
      FAIL: the value of a variable named like a credential is not shown: fwx verify: running 1 check from the profile at 684e4fb ...
      FAIL: redact: a variable named like a credential: got 'k=abcd1234efgh!', want 'k=[redacted]!'
      FAIL: a token-shaped value is not shown: fwx verify: running 1 check from the profile at a4e5a49 ...
  - the tail keeps 400 lines:
      FAIL: and keeps 40 lines, not more: ...
      FAIL: tail: 40 lines: got 'l0', want 'l60'
  - a check killed by its limit keeps the signal as its exit status:
      FAIL: a check past its limit has no exit status: got -9, want None
  - the comment is always created, never edited (the plan's control):
      FAIL: the second verify --pr 7 edits the comment and creates no other: got (['POST', 'POST', 'POST'], 3), want (['POST', 'PATCH'], 1)
  - lists read one page (comments and files):
      FAIL: the marked comment on the second page is edited: got 'created', want 'updated'
  - a list still full at the last page is returned instead of an error:
      FAIL: a list still full at the last page is an error: no error
  - neutral and skipped count green (marshal's PASSING):
      FAIL: check_state: neutral: got ('success', None), want ('pending', 'neutral')
      FAIL: check_state: skipped: got ('success', None), want ('pending', 'skipped')
  - cancelled is not a failure:
      FAIL: check_state: cancelled: got ('pending', "unknown conclusion 'cancelled'"), want ('failure', None)
  - the skip text of a success is ignored:
      FAIL: check_state: a success whose text says the review was skipped: got ('success', None), want ('pending', 'success, but its text says it was skipped')
  - the oldest run of a check wins:
      FAIL: the newest run of a check is the one that counts (old red, new green): got [{'name': 'ci', 'state': 'failure'}], want [{'name': 'ci', 'state': 'success'}]
  - a head with no check reported is not pending:
      FAIL: no check reported at all is pending, never success: got [], want ['pending']
  - Bugbot's run is not left out:
      FAIL: Bugbot's run is left out: got [{'name': 'Cursor Bugbot', 'state': 'failure'}, {'name': 'ci', 'state': 'success'}], want [{'name': 'ci', 'state': 'success'}]
  - a rename loses `previous_path`, the patch is dropped, `mergeable: null` is not `running`:
      FAIL: a rename carries previous_path: got None, want 'hooks/old.py'
      FAIL: a file carries its patch, which U3a reads for package.json: got '', want '@@ -1 +1 @@ ...'
      FAIL: mergeable null while GitHub computes: running, and mergeable true for the schema: got (True, False), want (True, True)
  - `--dir` ignored, `--json` printing the line, `--pr` not validated:
      FAIL: --dir writes the row in that folder, not in the phase: got (0, 1), want (1, 0)
      FAIL: --json prints JSON on stdout: evidence 118f4c27... true=0
      FAIL: a bad option --pr abc: exit 2, no row: got (1, 0), want (2, 0)
  - gh failing keeps the checks' exit code instead of 2:
      FAIL: gh failing: exit 2: got 0, want 2
      FAIL: no gh on PATH: exit 2: got 0, want 2
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
s = helpers.Suite()
try:
    from fwx import state  # noqa: E402
    from fwx.core import evidence, gh  # noqa: E402
    from fwx.core import verify as core_verify  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.core.verify and fwx.core.gh: %s" % e)
    sys.exit(1)

# ---- a PATH that holds only what a test puts there (order 10): python3, git, bash, and fakes of gh and npm ------------

NO_GH = helpers.mkdtemp("fwx-bin-")
WITH_GH = helpers.mkdtemp("fwx-bin-gh-")
for d in (NO_GH, WITH_GH):
    for prog, target in (("python3", sys.executable), ("git", shutil.which("git")), ("bash", shutil.which("bash"))):
        if target:
            os.symlink(target, os.path.join(d, prog))
    helpers.write(d, "npm", "#!/bin/sh\nexit 0\n", 0o755)
GH_STATE = os.path.join(helpers.mkdtemp("fwx-ghstate-"), "state.json")
FAKE_GH = r'''#!%s
import json, os, re, sys
path_state = os.environ["FAKE_GH_STATE"]
with open(path_state) as f:
    st = json.load(f)
args = sys.argv[1:]
method, body, target = "GET", None, None
i = 1
while i < len(args):
    if args[i] == "--method":
        method = args[i + 1]; i += 2
    elif args[i] == "--input":
        body = json.loads(sys.stdin.read()); i += 2
    else:
        target = args[i]; i += 1
st["log"].append({"cwd": os.getcwd(), "method": method, "path": target})
def finish(code, text="", err=""):
    with open(path_state, "w") as f:
        json.dump(st, f)
    sys.stdout.write(text); sys.stderr.write(err); sys.exit(code)
if st.get("fail"):
    finish(1, err=st["fail"])
m = re.fullmatch(r"repos/\{owner\}/\{repo\}/issues/(\d+)/comments(\?per_page=(\d+)&page=(\d+))?", target)
if m and method == "GET":
    mine = [c for c in st["comments"] if c["pr"] == int(m.group(1))]
    per, page = int(m.group(3)), int(m.group(4))
    finish(0, json.dumps(mine[(page - 1) * per:page * per]))
if m and method == "POST":
    c = {"id": len(st["comments"]) + 1, "pr": int(m.group(1)), "body": body["body"]}
    st["comments"].append(c)
    finish(0, json.dumps(c))
m = re.fullmatch(r"repos/\{owner\}/\{repo\}/issues/comments/(\d+)", target)
if m and method == "PATCH":
    for c in st["comments"]:
        if c["id"] == int(m.group(1)):
            c["body"] = body["body"]
            finish(0, json.dumps(c))
    finish(1, err="no such comment")
if target in st["routes"]:
    finish(0, json.dumps(st["routes"][target]))
finish(1, err="fake gh: no route for " + target)
''' % sys.executable
helpers.write(WITH_GH, "gh", FAKE_GH, 0o755)


def gh_reset(**fields):
    st = {"log": [], "comments": [], "routes": {}, "fail": None}
    st.update(fields)
    helpers.write(os.path.dirname(GH_STATE), "state.json", json.dumps(st))


def gh_state():
    with open(GH_STATE, encoding="utf-8") as f:
        return json.load(f)


def writes(st):
    return [c for c in st["log"] if c["method"] != "GET"]


gh_reset()
ENV = {"PATH": NO_GH, "CLAUDE_CODE_SESSION_ID": "", "FAKE_GH_STATE": GH_STATE}
GH_ENV = dict(ENV, PATH=WITH_GH)


def make(recipe, files=None):
    """A toy repo whose committed `.claude/fwx.json` has `recipe` as its checks, and the phase folder `.fwx` holds."""
    f = {"README": "toy\n", "sub/x.txt": "x\n",
         ".claude/fwx.json": json.dumps({"schema": 1, "project": {"checks": recipe}})}
    f.update(files or {})
    repo = helpers.toy_repo(f)
    return repo, str(state.new_phase("work", cwd=repo))


def rows(phase):
    return state.read_rows(state.phase_paths(phase)["audit"])


def run(cwd, *args, env=None):
    return helpers.fwx(cwd, "verify", *args, env=dict(ENV, **(env or {})))


def head(cwd):
    return helpers.git(cwd, "rev-parse", "HEAD").strip()


# ---- the three exit codes, each with the row it leaves ----------------------------------------------------------------

repo, phase = make(["true", "echo hello"])
sha = head(repo)
r = run(repo)
s.eq("a green run exits 0", r.returncode, 0)
got = rows(phase)
s.eq("a green run writes one evidence row", [x["kind"] for x in got], ["evidence"])
detail = json.loads(got[0]["detail"]) if got else {}
s.eq("the row carries the sha of HEAD and rc 0", (got[0]["sha"], got[0]["rc"]) if got else None, (sha, "0"))
s.eq("the detail is the evidence: sha, clean, source, commands, rc", detail,
     {"sha": sha, "clean": True, "source": "profile",
      "commands": [{"cmd": "true", "rc": 0}, {"cmd": "echo hello", "rc": 0}], "rc": 0})
s.eq("stdout is the line for the phase report", r.stdout.strip(), "evidence %s true=0 echo hello=0" % sha)
s.eq("the row proves the recipe at that sha (core.evidence)",
     evidence.evidence_state(detail, sha, ["true", "echo hello"])["state"], "verified")
s.ok("progress goes to stderr, with the short sha", "at %s" % sha[:7] in r.stderr, r.stderr)
s.eq("a second run on the same phase is not dirty because of `.fwx/` (the row it wrote)", run(repo).returncode, 0)
s.eq("and writes a second row", len(rows(phase)), 2)

repo, phase = make(["exit 1", "echo second; exit 0"])
r = run(repo)
s.eq("a red check exits 1", r.returncode, 1)
got = rows(phase)
s.eq("a red check writes a row with the sha and rc 1", [(x["sha"], x["rc"]) for x in got], [(head(repo), "1")])
s.eq("every check ran even after the red one",
     json.loads(got[0]["detail"])["commands"] if got else None,
     [{"cmd": "exit 1", "rc": 1}, {"cmd": "echo second; exit 0", "rc": 0}])
s.ok("the red check's command and its exit are named on stderr", "failed exit 1" in r.stderr and "exit 1" in r.stderr, r.stderr)

repo, phase = make([": > ran.marker"])
helpers.write(repo, "README", "changed\n")
r = run(repo)
s.eq("a modified tracked file: exit 2", r.returncode, 2)
s.eq("a dirty tree writes no row", rows(phase), [])
s.ok("a dirty tree runs no check", not os.path.exists(os.path.join(repo, "ran.marker")))
s.ok("a dirty tree says why", "uncommitted" in r.stderr, r.stderr)
helpers.git(repo, "checkout", "--", "README")
helpers.write(repo, "new-file.txt", "untracked\n")
s.eq("an untracked file: exit 2", run(repo).returncode, 2)
os.remove(os.path.join(repo, "new-file.txt"))

repo, phase = make(["true"])
helpers.write(repo, ".fwx/notes.md", "only documents changed\n")
s.eq("a change only under `.fwx/` is not dirty", run(repo).returncode, 0)
helpers.write(repo, ".fwx/notes.md", "again\n")
helpers.write(repo, "sub/y.txt", "y\n")
s.eq("a change under `.fwx/` and another elsewhere is dirty", run(repo).returncode, 2)

repo, phase = make([])
r = run(repo)
s.eq("no recipe and no package.json: exit 2", r.returncode, 2)
s.eq("no recipe writes no row", rows(phase), [])
s.ok("no recipe says so", "no checks defined" in r.stderr, r.stderr)

repo, phase = make([], {"package.json": json.dumps({"scripts": {"test": "x", "lint": "y", "dev": "z"}})})
r = run(repo)
s.eq("no recipe, a package.json with test and lint: exit 0 through npm (a fake one)", r.returncode, 0)
got = rows(phase)
d = json.loads(got[0]["detail"]) if got else {}
s.eq("the package.json scripts are the commands, and the source says so",
     (d.get("source"), [c["cmd"] for c in d.get("commands", [])]), ("package", ["npm run test", "npm run lint"]))

repo, phase = make(["git -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit --allow-empty -q -m moved"])
before = head(repo)
r = run(repo)
s.eq("HEAD moving while the checks run: exit 2", r.returncode, 2)
got = rows(phase)
d = json.loads(got[0]["detail"]) if got else {}
s.eq("it writes a row for the sha it started from, clean false, rc 1",
     (got[0]["sha"], d.get("clean"), got[0]["rc"]) if got else None, (before, False, "1"))
s.eq("such a row proves nothing (core.evidence: dirty)",
     evidence.evidence_state(d, before, ["git -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit "
                                          "--allow-empty -q -m moved"])["state"], "dirty")
s.ok("the move is said on stderr", "HEAD moved" in r.stderr, r.stderr)

# ---- worktrees, folders and the destination of the row ----------------------------------------------------------------

repo, phase = make(["true"])
wt = helpers.add_worktree(repo, "feature")
helpers.git(wt, "commit", "--allow-empty", "-q", "-m", "work in the worktree")
r = run(wt)
s.eq("from a worktree: exit 0", r.returncode, 0)
got = rows(phase)
s.eq("from a worktree the row lands in the main checkout's phase, with the worktree's HEAD",
     [x["sha"] for x in got], [head(wt)])
s.ok("the worktree's HEAD is not the main checkout's", head(wt) != head(repo))
s.ok("the worktree gets no `.fwx` of its own", not os.path.exists(os.path.join(wt, ".fwx")))
helpers.write(wt, "README", "dirty in the worktree\n")
s.eq("a dirty worktree: exit 2, no new row", (run(wt).returncode, len(rows(phase))), (2, 1))
helpers.git(wt, "checkout", "--", "README")
s.eq("from a subfolder of the worktree: the same checkout", run(os.path.join(wt, "sub")).returncode, 0)
wt_red, phase_red = make(["exit 1"])
wt_red = helpers.add_worktree(wt_red, "red")
s.eq("a red check from a worktree: exit 1", run(wt_red).returncode, 1)
s.eq("and its row is in the main checkout's phase", [x["rc"] for x in rows(phase_red)], ["1"])

repo, phase = make(["true"])
job = os.path.join(repo, ".fwx", "factory", "KEY-1")
os.makedirs(job)
r = run(repo, "--dir", job)
s.eq("--dir: exit 0", r.returncode, 0)
s.eq("--dir writes the row in that folder, not in the phase", (len(rows(job)), len(rows(phase))), (1, 0))
r = run(repo, "--dir", os.path.join(repo, "nowhere"))
s.eq("--dir with no such folder: exit 2", r.returncode, 2)
s.ok("--dir with no such folder creates nothing", not os.path.exists(os.path.join(repo, "nowhere")))
s.eq("and runs no check, writes no row", (len(rows(job)), len(rows(phase))), (1, 0))

repo = helpers.toy_repo({"README": "toy\n", ".claude/fwx.json": json.dumps({"schema": 1, "project": {"checks": ["true"]}})})
r = run(repo)
s.eq("no phase for the session and no --dir: the exit is the checks' (0)", r.returncode, 0)
s.ok("it says no row was written", "no evidence row was written" in r.stderr, r.stderr)
s.ok("and it makes no `.fwx`", not os.path.exists(os.path.join(repo, ".fwx")))

r = run(helpers.mkdtemp("fwx-nogit-"))
s.eq("outside a git repository: exit 2", r.returncode, 2)
s.ok("outside a git repository says so", "not inside a git repository" in r.stderr, r.stderr)

repo, phase = make(["true"])
for bad in (["--bogus"], ["--pr"], ["--pr", "abc"], ["--pr", "0"], ["--dir"], ["--pr", "--json"]):
    s.eq("a bad option %s: exit 2, no row" % " ".join(bad), (run(repo, *bad).returncode, len(rows(phase))), (2, 0))

r = run(repo, "--json")
s.eq("--json: exit 0", r.returncode, 0)
try:
    parsed = json.loads(r.stdout)
except ValueError:
    parsed = None
s.ok("--json prints JSON on stdout", isinstance(parsed, dict), r.stdout)
if isinstance(parsed, dict):
    s.eq("--json has the facts.evidence shape, plus source and rc", sorted(parsed), ["clean", "commands", "rc", "sha", "source"])
    s.eq("--json is what the row's detail holds", parsed, json.loads(rows(phase)[-1]["detail"]))
    s.eq("--json is the evidence of HEAD", evidence.evidence_state(parsed, head(repo), ["true"])["state"], "verified")

# ---- output: the tail, and no secrets in it ---------------------------------------------------------------------------

loop = "i=0; while [ $i -lt 200 ]; do echo line$i; i=$((i+1)); done; exit 1"
repo, phase = make([loop])
r = run(repo)
s.ok("the tail of a red check holds its last line", "line199" in r.stderr, r.stderr[-300:])
s.ok("and keeps 40 lines, not more", "line160" in r.stderr and "line159" not in r.stderr, r.stderr[-900:])
s.eq("tail: 40 lines", core_verify.tail("\n".join("l%d" % n for n in range(100))).split("\n")[0], "l60")
t = core_verify.tail("ab " * 5000)
s.ok("tail: 4000 characters at most", 0 < len(t) <= 4000, str(len(t)))

repo, phase = make(['echo "name rule: $FWX_TEST_SECRET_TOKEN"; echo "shape rule: $FWX_TEST_PLAIN"; exit 1'])
r = run(repo, env={"FWX_TEST_SECRET_TOKEN": "hunter2hunter2", "FWX_TEST_PLAIN": "ghp_abcdefghijklmnopqrst"})
s.eq("the secret test run is red", r.returncode, 1)
s.ok("the output of the red check is shown", "name rule:" in r.stderr and "shape rule:" in r.stderr, r.stderr)
s.ok("the value of a variable named like a credential is not shown", "hunter2hunter2" not in r.stderr, r.stderr)
s.ok("a token-shaped value is not shown", "ghp_abcdefghij" not in r.stderr, r.stderr)
s.ok("the row holds neither", "hunter2" not in "".join(x["detail"] for x in rows(phase)))

env = {"MY_API_KEY": "abcd1234efgh"}
s.eq("redact: a variable named like a credential", core_verify.redact("k=abcd1234efgh!", env), "k=[redacted]!")
s.eq("redact: a variable not named like one is left", core_verify.redact("k=abcd1234efgh!", {"MY_NAME": "abcd1234efgh"}),
     "k=abcd1234efgh!")
s.eq("redact: a short value is left", core_verify.redact("k=abc", {"MY_API_KEY": "abc"}), "k=abc")
s.eq("redact: a bearer token", core_verify.redact("Authorization: Bearer abcdefghijkl", {}), "Authorization: Bearer [redacted]")
s.eq("redact: the userinfo of a URL", core_verify.redact("clone https://user:pw@example.com/x", {}),
     "clone https://[redacted]@example.com/x")
s.eq("redact: a long run of token characters", core_verify.redact("key " + "A1" * 25, {}), "key [redacted]")
s.eq("redact: ordinary text is left", core_verify.redact("3 passed in 0.1s", {}), "3 passed in 0.1s")

# ---- the limit of a check ---------------------------------------------------------------------------------------------

res = core_verify.run_check("%s -c 'import time; time.sleep(30)'" % sys.executable, ROOT, timeout=1)
s.eq("a check past its limit has no exit status", res["rc"], None)
s.ok("it is killed at the limit, not waited for", res["seconds"] < 10, str(res["seconds"]))
s.ok("and says it timed out", "timed out" in res["output"], res["output"])
res = core_verify.run_check("echo out; echo err >&2; exit 3", ROOT)
s.eq("a check's exit status and both streams", (res["rc"], "out" in res["output"], "err" in res["output"]), (3, True, True))
s.eq("the line for a report names a missing exit", core_verify.evidence_line("a" * 40, [{"cmd": "x", "rc": None}]),
     "evidence %s x=none" % ("a" * 40))

# ---- the comment on the PR, through a fake gh ------------------------------------------------------------------------

repo, phase = make(["true"])
gh_reset()
r = run(repo, "--pr", "7", env=GH_ENV)
st = gh_state()
s.eq("--pr 7 on a green run: exit 0", r.returncode, 0)
s.eq("--pr 7 created one comment, on PR 7", [(c["pr"], c["body"].split("\n")[0]) for c in st["comments"]],
     [(7, "<!-- fwx:evidence -->")])
s.ok("the comment carries the evidence line", "evidence %s true=0" % head(repo) in st["comments"][0]["body"] if st["comments"] else False)
s.eq("gh ran in the repository's checkout", {c["cwd"] for c in st["log"]}, {repo})
s.eq("gh was asked for the comments first, then to create", [(c["method"], c["path"]) for c in st["log"]],
     [("GET", "repos/{owner}/{repo}/issues/7/comments?per_page=100&page=1"),
      ("POST", "repos/{owner}/{repo}/issues/7/comments")])
r = run(repo, "--pr", "7", env=GH_ENV)
s.eq("the same commit again: exit 0", r.returncode, 0)
s.eq("the same commit again writes nothing to GitHub", len(writes(gh_state())), 1)
helpers.git(repo, "commit", "--allow-empty", "-q", "-m", "two")
r = run(repo, "--pr", "7", env=GH_ENV)
st = gh_state()
s.eq("the second verify --pr 7 edits the comment and creates no other",
     ([c["method"] for c in writes(st)], len(st["comments"])), (["POST", "PATCH"], 1))
body = (st["comments"] or [{"body": ""}])[0]["body"]
s.ok("the comment now names the new commit", head(repo) in body, body)
s.eq("it edited the comment it had created", [c["path"] for c in writes(st)[1:2]], ["repos/{owner}/{repo}/issues/comments/1"])

repo, phase = make(["exit 1"])
gh_reset()
r = run(repo, "--pr", "7", env=GH_ENV)
s.eq("a red run with --pr: exit 1, the comment is still posted", (r.returncode, len(gh_state()["comments"])), (1, 1))
s.ok("the comment says cmd=rc", "exit 1=1" in gh_state()["comments"][0]["body"] if gh_state()["comments"] else False)

repo, phase = make(["true"])
helpers.write(repo, "README", "dirty\n")
gh_reset()
r = run(repo, "--pr", "7", env=GH_ENV)
s.eq("a dirty tree with --pr: exit 2 and gh is never called", (r.returncode, gh_state()["log"]), (2, []))

repo, phase = make(["true"])
gh_reset(fail="HTTP 401: Bad credentials")
r = run(repo, "--pr", "7", env=GH_ENV)
s.eq("gh failing: exit 2", r.returncode, 2)
s.eq("gh failing: the evidence row is written", [x["rc"] for x in rows(phase)], ["0"])
s.ok("gh failing: gh's own error is on stderr", "HTTP 401: Bad credentials" in r.stderr, r.stderr)
r = run(repo, "--pr", "7")
s.eq("no gh on PATH: exit 2", r.returncode, 2)
s.eq("no gh on PATH: the row is written too", len(rows(phase)), 2)
s.ok("no gh on PATH: the error names gh", "gh is not installed" in r.stderr, r.stderr)
gh_reset()

# ---- the adapter itself: pages, marker, the check-state table ---------------------------------------------------------

saved = {k: os.environ.get(k) for k in ("PATH", "FAKE_GH_STATE")}
os.environ["PATH"], os.environ["FAKE_GH_STATE"] = WITH_GH, GH_STATE
try:
    marker = "<!-- fwx:evidence -->"
    fillers = [{"id": n, "pr": 9, "body": "chatter %d" % n} for n in range(1, 101)]
    gh_reset(comments=fillers + [{"id": 101, "pr": 9, "body": marker + "\nold"}])
    s.eq("the marked comment on the second page is edited", gh.upsert_comment(9, marker, marker + "\nnew", cwd=ROOT), "updated")
    st = gh_state()
    s.eq("and no second one is created", ([c["method"] for c in writes(st)], len(st["comments"])), (["PATCH"], 101))
    s.eq("the edit went to comment 101", [c["path"] for c in writes(st)[:1]], ["repos/{owner}/{repo}/issues/comments/101"])
    s.eq("a comment without the marker is created", gh.upsert_comment(10, marker, marker + "\nx", cwd=ROOT), "created")
    s.eq("a body that already is the one asked for is unchanged", gh.upsert_comment(9, marker, marker + "\nnew", cwd=ROOT),
         "unchanged")
    for bad in ((0, marker, marker), (True, marker, marker), (7, marker, "no marker here"), (7, "", "x")):
        try:
            gh.upsert_comment(*bad, cwd=ROOT)
            s.ok("upsert_comment refuses %r" % (bad,), False, "no error")
        except ValueError:
            s.ok("upsert_comment refuses %r" % (bad,), True)

    # check_state: one row per row of the 5.2 table
    table = [
        (("success", "completed", ""), ("success", None), "a plain success"),
        (("success", "completed", "Tests passed"), ("success", None), "a success with ordinary text"),
        (("success", "completed", "Review skipped"), ("pending", "success, but its text says it was skipped"),
         "a success whose text says the review was skipped"),
        (("success", "completed", "REVIEW SKIPPED"), ("pending", "success, but its text says it was skipped"),
         "the skip text in any case"),
        (("neutral", "completed", ""), ("pending", "neutral"), "neutral"),
        (("skipped", "completed", ""), ("pending", "skipped"), "skipped"),
        (("failure", "completed", ""), ("failure", None), "failure"),
        (("cancelled", "completed", ""), ("failure", None), "cancelled"),
        (("timed_out", "completed", ""), ("failure", None), "timed_out"),
        (("action_required", "completed", ""), ("failure", None), "action_required"),
        (("startup_failure", "completed", ""), ("failure", None), "startup_failure"),
        (("stale", "completed", ""), ("failure", None), "stale"),
        ((None, "in_progress", ""), ("pending", None), "in progress"),
        ((None, "queued", ""), ("pending", None), "queued"),
        (("success", "in_progress", ""), ("pending", None), "a conclusion on a run that is not completed"),
        (("surprise", "completed", ""), ("pending", "unknown conclusion 'surprise'"), "a conclusion nobody knows"),
    ]
    for args, want, label in table:
        s.eq("check_state: %s" % label, gh.check_state(*args), want)
    s.eq("status_state: success", gh.status_state("success", "ok"), ("success", None))
    s.eq("status_state: success that says skipped", gh.status_state("success", "Review skipped")[0], "pending")
    s.eq("status_state: pending", gh.status_state("pending", ""), ("pending", None))
    s.eq("status_state: failure", gh.status_state("failure", ""), ("failure", None))
    s.eq("status_state: error", gh.status_state("error", ""), ("failure", None))

    def run_of(name, conclusion, started, id_, status="completed", title="", summary=""):
        return {"name": name, "status": status, "conclusion": conclusion, "started_at": started, "id": id_,
                "output": {"title": title, "summary": summary}}

    checks, not_green = gh.checks_of([run_of("ci", "failure", "t00", 1),
                                      run_of("ci", "success", "t01", 2)], [])
    s.eq("the newest run of a check is the one that counts (old red, new green)", checks, [{"name": "ci", "state": "success"}])
    checks, _ = gh.checks_of([run_of("ci", "success", "t01", 2),
                              run_of("ci", "failure", "t00", 1)], [])
    s.eq("whatever the order they come in (old red listed last)", checks, [{"name": "ci", "state": "success"}])
    checks, _ = gh.checks_of([run_of("ci", "success", "t00", 1),
                              run_of("ci", "failure", "t01", 2)], [])
    s.eq("old green and new red is red", checks, [{"name": "ci", "state": "failure"}])
    checks, not_green = gh.checks_of([run_of("CodeRabbit", "success", "t00", 1, summary="Review skipped")], [])
    s.eq("a success whose summary says Review skipped is pending", checks, [{"name": "CodeRabbit", "state": "pending"}])
    s.eq("and is listed as not green, with its conclusion",
         [(n["name"], n["conclusion"]) for n in not_green], [("CodeRabbit", "success")])
    checks, _ = gh.checks_of([run_of("review", "success", "t00", 1, title="Skipped: draft")], [])
    s.eq("the title counts as well as the summary", checks, [{"name": "review", "state": "pending"}])
    checks, _ = gh.checks_of([run_of("Cursor Bugbot", "failure", "t00", 1),
                              run_of("ci", "success", "t00", 2)], [])
    s.eq("Bugbot's run is left out", checks, [{"name": "ci", "state": "success"}])
    checks, not_green = gh.checks_of([], [])
    s.eq("no check reported at all is pending, never success", [c["state"] for c in checks], ["pending"])
    s.eq("and is listed as not green", len(not_green), 1)
    checks, _ = gh.checks_of([], [{"context": "ci/x", "state": "success", "description": "ok"},
                                  {"context": "ci/y", "state": "error", "description": ""}])
    s.eq("commit statuses count as checks", checks, [{"name": "ci/x", "state": "success"}, {"name": "ci/y", "state": "failure"}])
    checks, _ = gh.checks_of([run_of("a", None, "t00", 1, status="in_progress")],
                             [{"context": "b", "state": "success", "description": "ok"}])
    s.eq("one running check keeps the head pending next to a green status", [c["state"] for c in checks], ["pending", "success"])

    # pr_facts over pages
    head_sha = "f" * 40
    files = [{"filename": "f%d.py" % n, "additions": 1, "deletions": 0, "patch": "@@ +%d" % n} for n in range(100)]
    files[5] = {"filename": "new/name.py", "previous_filename": "hooks/old.py", "additions": 0, "deletions": 0, "status": "renamed"}
    last = [{"filename": "package.json", "additions": 1, "deletions": 1, "patch": '@@ -1 +1 @@\n-"test": "a"\n+"test": "true"'}]
    base = "repos/{owner}/{repo}"
    routes = {
        base + "/pulls/7": {"head": {"sha": head_sha}, "base": {"ref": "factory"}, "mergeable": True},
        base + "/pulls/7/files?per_page=100&page=1": files,
        base + "/pulls/7/files?per_page=100&page=2": last,
        base + "/commits/%s/check-runs?per_page=100&page=1" % head_sha:
            {"total_count": 1, "check_runs": [run_of("ci", "success", "t00", 1)]},
        base + "/commits/%s/status?per_page=100&page=1" % head_sha: {"state": "success", "statuses": []},
    }
    gh_reset(routes=routes)
    facts = gh.pr_facts(7, cwd=ROOT)
    paths = [f["path"] for f in facts["changed_files"]]
    s.eq("101 changed files over two pages are all there", len(paths), 101)
    s.ok("the file of the second page is there", "package.json" in paths, str(paths[-3:]))
    pj = facts["changed_files"][-1] if facts["changed_files"] else {}
    s.eq("a file carries its patch, which U3a reads for package.json", pj.get("patch"), last[0]["patch"])
    s.eq("a file with no patch has an empty one", [f["patch"] for f in facts["changed_files"][5:6]], [""])
    s.eq("a rename carries previous_path", facts["changed_files"][5].get("previous_path"), "hooks/old.py")
    s.ok("a file that was not renamed has no previous_path", "previous_path" not in facts["changed_files"][0])
    s.eq("the other fields of a changed file", sorted(pj), ["additions", "deletions", "patch", "path"])
    s.eq("the PR's own fields", (facts["number"], facts["head_sha"], facts["base"], facts["mergeable"], facts["running"]),
         (7, head_sha, "factory", True, False))
    s.eq("the checks of the head", facts["checks"], [{"name": "ci", "state": "success"}])
    routes[base + "/pulls/7"]["mergeable"] = None
    gh_reset(routes=routes)
    facts = gh.pr_facts(7, cwd=ROOT)
    s.eq("mergeable null while GitHub computes: running, and mergeable true for the schema", (facts["mergeable"], facts["running"]), (True, True))

    saved_max = gh.MAX_PAGES
    gh.MAX_PAGES = 2
    full = {base + "/pulls/7/files?per_page=100&page=%d" % p: [dict(f) for f in files] for p in (1, 2)}
    gh_reset(routes=dict(routes, **full))
    try:
        gh.pr_facts(7, cwd=ROOT)
        s.ok("a list still full at the last page is an error", False, "no error")
    except gh.GhError as e:
        s.ok("a list still full at the last page is an error that says truncated", "truncated" in str(e), str(e))
    finally:
        gh.MAX_PAGES = saved_max
    gh_reset(fail="boom")
    try:
        gh.pr_facts(7, cwd=ROOT)
        s.ok("a gh failure is a GhError", False, "no error")
    except gh.GhError as e:
        s.ok("a gh failure is a GhError with gh's message", "boom" in str(e), str(e))
finally:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

r = helpers.fwx(ROOT, "help")
s.ok("`fwx help` lists verify", any(line.split()[:2] == ["fwx", "verify"] for line in r.stdout.splitlines()), r.stdout)

s.done()
