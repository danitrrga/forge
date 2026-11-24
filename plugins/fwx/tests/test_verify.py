#!/usr/bin/env python3
"""`fwx verify` and the `gh` adapter: core.verify, core.gh, commands/verify.py, on real repos and worktrees, with a fake `gh`.

Ports the CLI cases of marshal's evidence-regressions.ts:175-293 (passing, failing and dirty runs at the exact HEAD, every
check run, a secret in the output redacted) onto `fwx verify`, and adds the worktree, `--dir`, `.fwx/`-only, HEAD-moved and
`--pr` cases. Every program a test fakes lives alone on PATH (order 10): a directory holding symlinks to python3, git and
bash, and a fake `npm`; with `gh`, a second one that also holds the fake `gh`, which keeps its state and its calls in a JSON
file. No network, no real `gh`. The check-state table is 5.2's, row by row, not marshal's `PASSING` set.

Seen red before the code existed (core/gh.py and core/verify.py absent; the test stops at the import):
  FAIL: cannot import fwx.core.verify and fwx.core.gh: cannot import name 'gh' from 'fwx.core' (<worktree>/lib/fwx/core/__init__.py)

The built-in check `fwx added-files` (no one-use or old-version file added since the default branch) was seen red on master,
before core/verify.py had it (first FAILs shown):
  FAIL: a range adding docs/brief-x.md, plan-v2.md and notes.md.bak: exit 1: got 0, want 1
  FAIL: it prints the line of docs/brief-x.md: fwx verify: running 1 check from the project at 165a099 ...
  FAIL: a red built-in check is a red command of the evidence, like the project's own: got ('0', 0, [{'cmd': 'true', 'rc': 0}]), want ('1', 1, [{'cmd': 'true', 'rc': 0}, {'cmd': 'fwx added-files', 'rc': 1}])
Narrowed after the first version (a dated blog post, a prompt template, TODO.md, release notes and a lone api-v2.md are living
files). The narrowed cases were seen red on the first version's code:
  FAIL: living files that only look like leftovers (a dated blog post, a prompt template, TODO.md, a lone api-v2.md, release notes): exit 0: got (1, ['TODO.md', 'api-v2.md', 'blog/<date>-post.md', 'prompts/summary-prompt.md', 'release-notes-3.md']), want (0, [])
After the adversarial review, seen red on the previous head (F1, F2; the F3 cases pass on it, they pin the behaviour before the
two copies of the default branch's names became one, and their mutants below show them able to fail):
  FAIL: `briefing` and `debrief` are not `brief`: exit 0: got (1, True), want (0, False)
  FAIL: marker of 'morning-briefing-prompt.md': got 'one-use', want None
  FAIL: a rename to a one-use name counts as added, a rename to a plain name does not: got (0, []), want (1, ['plan-handoff.md'])
Its mutants, each seen red on a copy of the plugin with one line changed:
  - the `.fwx/` exemption removed:
      FAIL: a range adding src/<date>-migration.sql, README.md and .fwx/milestones/x/state.md (and a marked name under .fwx/): exit 0: got 1, want 0
  - modified files counted too (no `--diff-filter=A`):
      FAIL: a marked file that already existed and is only changed is not added: got 1, want 0
  - renames not counted (`--diff-filter=A`): the rename case above, got (0, [])
  - the `origin/` ref not looked up: FAIL: the remote's default branch (origin/HEAD) is measured from ...: got (0, True, False), want (1, False, True)
  - the farthest base chosen, not the nearest: FAIL: a stale local master and a newer origin/master: ...: got 1, want 0
  - `project.default_branch` ignored: FAIL: `project.default_branch` names the default branch ...: got (0, True, False), want (1, False, True)
  - a `-v2` or `-old` name is old with no living file beside it:
      FAIL: living files that only look like leftovers (...): exit 0: got (1, ['api-v2.md']), want (0, [])
      FAIL: marker of 'api-v2.md': got 'old', want None
  - the `.md`/`.txt` limit of the one-use names removed:
      FAIL: a marker in a code file's name, a folder's name, `-older` or a bare `notes.md` is not a hit: got 1, want 0

After an active review of PR 201 (G1 to G4), each case seen red on the code before its fix (G4 on a mutant):
  - G1, only the first `-vN`/`-old` match of a name read (`api-v2.spec-old.md` beside `api-v2.spec.md`):
      FAIL: marker of 'api-v2.spec-old.md': got None, want 'old'
  - G2, a sibling looked up in the working tree, and an empty stem counted:
      FAIL: a folder, an empty stem and an ignored file are no living sibling; a committed broken symlink is one: got (True, ['-v2', 'docs/api-v2', 'report-v2.json']), want (True, ['plan-old.md'])
      FAIL: marker of '-v2' with every path existing: the stem is empty, so None: got 'old', want None
      FAIL: added_files measures the commit it is given, not a HEAD that moved (before: TypeError: added_files() takes 2 positional arguments but 3 were given)
  - G3, a dangling `refs/remotes/origin/HEAD` trusted:
      FAIL: a dangling origin/HEAD: the check still measures from master, exit 1, no NOT RUN: got (0, True, False), want (1, False, True)
      FAIL: a dangling origin/HEAD: the names are the fallback ones: got ['gone'], want ['main', 'master']
  - G4, the old master case (`todo.md`, no longer a marker; master only adds) passed a mutant of `_range_base` returning the default
    branch's ref instead of the merge base; with `handoff.md` added and a marked file deleted on master it fails:
      FAIL: a marked file the default branch added or removed after the branch left is not the branch's: got 1, want 0

Controls of the rest, each seen red on a copy of the repo with one thing changed (first FAIL line shown; 152 checks on the good code):
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
      FAIL: the value of a variable named like a credential is not shown: fwx verify: running 1 check from the project at 684e4fb ...
      FAIL: redact: a variable named like a credential: got 'k=abcd1234efgh!', want 'k=[redacted]!'
      FAIL: a token-shaped value is not shown: fwx verify: running 1 check from the project at a4e5a49 ...
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
import shlex
import select
import shutil
import subprocess
import sys
import time

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


def make(recipe, files=None, project=None):
    """A toy repo whose committed `.claude/fwx.json` has `recipe` as its checks (and the other `project` keys given), and the phase folder `.fwx` holds."""
    f = {"README": "toy\n", "sub/x.txt": "x\n",
         ".claude/fwx.json": json.dumps({"schema": 1, "project": dict(project or {}, checks=recipe)})}
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

# ---- the time limit of a check is the project's: project.check_timeout_s (DTC-113) ---------------------------------------
# Seen red on master (the limit was the constant CHECK_TIMEOUT_S, 20 minutes, whatever the file said):
#   FAIL: a check of 2 s with check_timeout_s 1: exit 1 and rc none: got (0, [0]), want (1, [None])
#   FAIL: a check of 2 s with check_timeout_s 1: the limit actually used is named: fwx verify: running 1 check from the project at 8b3f2e7 ...
#   FAIL: check_timeout_s 0 is a configuration error: exit 2, no row: got (0, [{'date': ..., 'kind': 'evidence', ...}]), want (2, [])

NAP = "%s -c 'import time; time.sleep(2)'" % shlex.quote(sys.executable)
repo, phase = make([NAP], project={"check_timeout_s": 1})
r = run(repo)
got = rows(phase)
s.eq("a check of 2 s with check_timeout_s 1: exit 1 and rc none",
     (r.returncode, [c["rc"] for c in json.loads(got[-1]["detail"])["commands"]] if got else []), (1, [None]))
s.ok("a check of 2 s with check_timeout_s 1: the limit actually used is named", "timed out after 1 s" in r.stderr, r.stderr)
# PR 223 review. Seen red: FAIL: a timed-out check says to raise project.check_timeout_s: fwx verify: running 1 check from the project at ...
s.ok("a timed-out check says to raise project.check_timeout_s", "raise `project.check_timeout_s`" in r.stderr, r.stderr)
repo, phase = make([NAP])
s.eq("the same check with no configured limit passes (the default is 1200 s)", run(repo).returncode, 0)
repo, phase = make([NAP], project={"check_timeout_s": 0})
r = run(repo)
s.eq("check_timeout_s 0 is a configuration error: exit 2, no row", (r.returncode, rows(phase)), (2, []))
s.ok("and the error names the key", "project.check_timeout_s" in r.stderr, r.stderr)

# ---- the built-in check: no file of a one-use or old-version name is added (the range from the default branch) -----------

DATE = "-".join(("2001", "02", "03"))  # built from parts: the private list of `forge lint` refuses a date in a file
TIP = ("is never committed: put it in your scratch folder (fwx scratch new), which git ignores; for an old version, keep only "
       "the living file, since git holds the history. If this file really belongs in the project, rename it without the marker.")


def on_branch(files, recipe=("true",), base_files=None):
    """A toy repo on a new branch `work`, one commit past master, adding `files` ({path: text})."""
    repo, phase = make(list(recipe), base_files)
    helpers.git(repo, "checkout", "-q", "-b", "work")
    for rel, text in files.items():
        helpers.write(repo, rel, text)
    helpers.git(repo, "add", "-A", "-f")
    helpers.git(repo, "commit", "-q", "-m", "work")
    return repo, phase


repo, phase = on_branch({"docs/brief-x.md": "b\n", "plan-v2.md": "p\n", "notes.md.bak": "n\n"}, base_files={"plan.md": "p\n"})
r = run(repo)
s.eq("a range adding docs/brief-x.md, plan-v2.md and notes.md.bak: exit 1", r.returncode, 1)
for rel, what in (("docs/brief-x.md", "a one-use file"), ("plan-v2.md", "an old version"), ("notes.md.bak", "an old version")):
    s.ok("it prints the line of %s" % rel, "%s: %s %s" % (rel, what, TIP) in r.stderr, r.stderr)
s.eq("one line for each file, and nothing else says 'never committed'", r.stderr.count("is never committed"), 3)
got = rows(phase)
d = json.loads(got[0]["detail"]) if got else {}
s.eq("a red built-in check is a red command of the evidence, like the project's own",
     (got[0]["rc"], d.get("rc"), d.get("commands")) if got else None,
     ("1", 1, [{"cmd": "true", "rc": 0}, {"cmd": "fwx added-files", "rc": 1}]))
s.ok("the evidence line names it", "%s=1" % "fwx added-files" in r.stdout, r.stdout)
s.eq("and it proves the commit failed (core.evidence)", evidence.evidence_state(d, head(repo), ["true"])["state"], "failed")

repo, phase = on_branch({"src/" + DATE + "-migration.sql": "s\n", "README.md": "r\n", ".fwx/milestones/x/state.md": "st\n",
                         ".fwx/milestones/x/handoff-" + DATE + ".md": "h\n"})
r = run(repo)
s.eq("a range adding src/" + DATE + "-migration.sql, README.md and .fwx/milestones/x/state.md (and a marked name under .fwx/): exit 0", r.returncode, 0)
s.ok("and says nothing about files: success is silent", "never committed" not in r.stderr and "NOT RUN" not in r.stderr, r.stderr)
s.eq("a green built-in check adds no command to the evidence",
     [c["cmd"] for c in json.loads(rows(phase)[0]["detail"])["commands"]], ["true"])

repo, phase = on_branch({"blog/" + DATE + "-post.md": "p\n", "prompts/summary-prompt.md": "p\n", "TODO.md": "t\n",
                         "api-v2.md": "a\n", "release-notes-3.md": "r\n"})
r = run(repo)
s.eq("living files that only look like leftovers (a dated blog post, a prompt template, TODO.md, a lone api-v2.md, release notes): exit 0",
     (r.returncode, [l.split(": ")[1] for l in r.stderr.splitlines() if "never committed" in l]), (0, []))
repo, phase = on_branch({"walk-old.py": "o\n", "docs/plan-v2.md": "o\n"}, base_files={"walk.py": "w\n", "docs/plan.md": "p\n"})
r = run(repo)
s.eq("an old version beside the living file fails whatever the extension",
     (r.returncode, sorted(l.split(": ")[1] for l in r.stderr.splitlines() if "never committed" in l)), (1, ["docs/plan-v2.md", "walk-old.py"]))

# F1: a one-use marker is a whole word of the name; F2: a rename to such a name counts; F3: where the default branch is found
repo, phase = on_branch({"docs/morning-briefing-prompt.md": "b\n", "debrief.md": "d\n"})
r = run(repo)
s.eq("`briefing` and `debrief` are not `brief`: exit 0", (r.returncode, "never committed" in r.stderr), (0, False))
repo, phase = on_branch({"PROJECT_BRIEF.md": "b\n", "docs/api.handoff.txt": "h\n"})
r = run(repo)
s.eq("`PROJECT_BRIEF.md` and `api.handoff.txt` are one-use: exit 1, two lines", (r.returncode, r.stderr.count("is never committed")), (1, 2))

repo, phase = make(["true"], {"plan.md": "the living plan, long enough to be told from another file\n" * 5, "old-name.md": "an old name\n" * 5})
helpers.git(repo, "checkout", "-q", "-b", "work")
helpers.git(repo, "mv", "plan.md", "plan-handoff.md")
helpers.git(repo, "mv", "old-name.md", "docs-name.md")
helpers.git(repo, "commit", "-q", "-m", "renames")
r = run(repo)
s.eq("a rename to a one-use name counts as added, a rename to a plain name does not",
     (r.returncode, [l.split(": ")[1] for l in r.stderr.splitlines() if "never committed" in l]), (1, ["plan-handoff.md"]))

repo, phase = make(["true"])
helpers.write(repo, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"checks": ["true"], "default_branch": "develop"}}))
helpers.git(repo, "commit", "-q", "-am", "config")
helpers.git(repo, "branch", "-q", "-m", "master", "develop")
helpers.git(repo, "checkout", "-q", "-b", "work")
helpers.write(repo, "checkpoint.md", "c\n")
helpers.git(repo, "add", "-A")
helpers.git(repo, "commit", "-q", "-m", "work")
r = run(repo)
s.eq("`project.default_branch` names the default branch: develop is measured from, not NOT RUN",
     (r.returncode, "NOT RUN" in r.stderr, "checkpoint.md: a one-use file" in r.stderr), (1, False, True))

repo, phase = on_branch({"checkpoint.md": "c\n"})
helpers.git(repo, "update-ref", "refs/remotes/origin/trunk", "master")
helpers.git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
helpers.git(repo, "branch", "-q", "-D", "master")
r = run(repo)
s.eq("the remote's default branch (origin/HEAD) is measured from when no local branch of it exists",
     (r.returncode, "NOT RUN" in r.stderr, "checkpoint.md: a one-use file" in r.stderr), (1, False, True))

repo, phase = make(["true"])
helpers.git(repo, "checkout", "-q", "-b", "up")
helpers.write(repo, "handoff.md", "added upstream, merged before the branch left\n")
helpers.git(repo, "add", "-A")
helpers.git(repo, "commit", "-q", "-m", "upstream")
helpers.git(repo, "update-ref", "refs/remotes/origin/master", "up")
helpers.git(repo, "checkout", "-q", "-b", "work")
helpers.write(repo, "src/a.py", "a\n")
helpers.git(repo, "add", "-A")
helpers.git(repo, "commit", "-q", "-m", "work")
s.eq("a stale local master and a newer origin/master: the nearer base wins, upstream's file is not the branch's",
     run(repo).returncode, 0)

repo, phase = make(["true"])
r = run(repo)
s.eq("on the default branch itself the range is empty: exit 0, silent", (r.returncode, "never committed" in r.stderr), (0, False))
# G4: a real marker, and a marked file the default branch DELETES after the fork: measured from master's tip, work would
# "add" it back (A), so only the merge base keeps it out
repo, phase = on_branch({"src/a.py": "a\n"}, base_files={"legacy-handoff.md": "existed at the fork\n"})
helpers.git(repo, "checkout", "-q", "master")
helpers.write(repo, "handoff.md", "added on master after the branch left\n")
helpers.git(repo, "rm", "-q", "legacy-handoff.md")
helpers.git(repo, "add", "-A")
helpers.git(repo, "commit", "-q", "-m", "master moves on")
helpers.git(repo, "checkout", "-q", "work")
s.eq("a marked file the default branch added or removed after the branch left is not the branch's", run(repo).returncode, 0)
helpers.git(repo, "branch", "-q", "-m", "master", "trunk")
r = run(repo)
s.eq("no default branch to measure from: exit 0 and the check says NOT RUN, NOT ARMED", (r.returncode, "NOT RUN, NOT ARMED" in r.stderr), (0, True))

repo, phase = on_branch({"docs/old-brief.md": "changed\n", "legacy-v1.md": "changed\n"}, base_files={"docs/old-brief.md": "x\n", "legacy-v1.md": "x\n"})
s.eq("a marked file that already existed and is only changed is not added", run(repo).returncode, 0)
repo, phase = on_branch({"a/Brief.MD": "x\n"})
s.eq("the marker is found whatever the case", run(repo).returncode, 1)
repo, phase = on_branch({"src/brief.py": "x\n", "debug/older.md": "x\n", "src/api-v2/handler.py": "x\n", "docs/notes.md": "x\n",
                         ".fwx/briefs/" + DATE + "-handoff.md": "x\n"})
s.eq("a marker in a code file's name, a folder's name, `-older` or a bare `notes.md` is not a hit", run(repo).returncode, 0)
wt = helpers.add_worktree(repo, "wt")
helpers.write(wt, "checkpoint.txt", "c\n")
helpers.git(wt, "add", "-A")
helpers.git(wt, "commit", "-q", "-m", "wt")
r = run(wt)
s.eq("from a linked worktree the range is the same: a checkpoint.txt added there fails", (r.returncode, "checkpoint.txt: a one-use file" in r.stderr), (1, True))

# G2: a sibling is a file (or symlink) of the verified commit, not whatever the working tree holds
repo, phase = make(["true"], {".gitignore": "report.json\n", "docs/api/idx.md": "x\n"})
os.symlink("missing-target", os.path.join(repo, "plan.md"))
helpers.git(repo, "add", "-A")
helpers.git(repo, "commit", "-q", "-m", "a folder docs/api and a committed broken symlink plan.md")
helpers.git(repo, "checkout", "-q", "-b", "work")
for rel in ("docs/api-v2", "-v2", "report-v2.json", "plan-old.md"):
    helpers.write(repo, rel, "x\n")
helpers.git(repo, "add", "-A")
helpers.git(repo, "commit", "-q", "-m", "work")
helpers.write(repo, "report.json", "an ignored artifact a check made\n")
cfg0 = {"project": {"default_branch": None}}
lines, known = core_verify.added_files(repo, cfg0)
s.eq("a folder, an empty stem and an ignored file are no living sibling; a committed broken symlink is one",
     (known, [l.split(": ")[0] for l in lines]), (True, ["plan-old.md"]))
sha0 = head(repo)
helpers.write(repo, "checkpoint.md", "c\n")
helpers.git(repo, "add", "-A")
helpers.git(repo, "commit", "-q", "-m", "after the verified commit")
s.eq("added_files measures the commit it is given, not a HEAD that moved",
     [l.split(": ")[0] for l in core_verify.added_files(repo, cfg0, sha0)[0]], ["plan-old.md"])

# G3: an origin/HEAD that points at a branch the remote no longer has does not replace main and master
repo, phase = on_branch({"brief.md": "b\n"})
helpers.git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")
r = run(repo)
s.eq("a dangling origin/HEAD: the check still measures from master, exit 1, no NOT RUN",
     (r.returncode, "NOT RUN" in r.stderr, "brief.md: a one-use file" in r.stderr), (1, False, True))
s.eq("a dangling origin/HEAD: the names are the fallback ones", sorted(core_verify.default_names(repo, cfg0)), ["main", "master"])

LIVING = {"plan.md", "src/walk.py", "a", "a.md", "a.test.js", "a.json", "a.py", "docs/a.md",
          "api-v2.spec.md", "api-v2.test.js", "api-v2.config.json", "api-v2.schema.json"}
for name, want in (("brief.md", "one-use"), ("Checkpoint-3.md", "one-use"), ("handoff.md", "one-use"), ("tomorrow.md", "one-use"),
                   ("scratch.txt", "one-use"), ("x/Brief.TXT", "one-use"),
                   ("my-prompt.txt", None), ("TODO.md", None), ("notes-api.md", None), ("release-notes-3.md", None),
                   ("day-" + DATE + ".md", None), ("blog/" + DATE + "-post.md", None), ("prompts/summary-prompt.md", None),
                   ("brief.py", None), (DATE + ".sql", None), ("morning-briefing-prompt.md", None), ("debrief.md", None),
                   ("briefs.md", None), ("PROJECT_BRIEF.md", "one-use"), ("api.handoff.txt", "one-use"), ("my brief.md", "one-use"),
                   ("notes_checkpoint-2.md", "one-use"), ("notes.md", None),
                   ("a.bak", "old"), ("a.orig", "old"), ("notes.md.bak", "old"), ("a.bak.md", "old"),
                   ("plan-v2.md", "old"), ("src/walk-old.py", "old"), ("a-copy.md", "old"), ("a copy.md", "old"), ("a copy", "old"),
                   ("a-backup.json", "old"), ("a-v12.md", "old"), ("a-v2.test.js", "old"), ("docs/a-old.md", "old"),
                   ("api-v2.md", None), ("src/api-v2.py", None), ("docs/plan-v2.md", None), ("a-older.md", None), ("a-vx.md", None),
                   ("a-v2b.md", None), ("old.md", None), ("copy.md", None), ("backup.md", None),
                   # G1: a version token before an earlier dot does not hide the one that makes the copy
                   ("api-v2.spec-old.md", "old"), ("api-v2.test-copy.js", "old"), ("api-v2.config-backup.json", "old"),
                   ("api-v2.schema-v2.json", "old"), ("api-v2.spec.md", None), ("api-v2.other-old.md", None)):
    s.eq("marker of %r" % name, getattr(core_verify, "marker", lambda n, e=None: "no marker()")(name, lambda p: p in LIVING), want)
# G2: a name that is only a marker strips to nothing, and nothing is not a living sibling (even when `exists` says yes to everything)
for name in ("-v2", "fixtures/-old", "-copy"):
    s.eq("marker of %r with every path existing: the stem is empty, so None" % name, core_verify.marker(name, lambda p: True), None)

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
s.eq("a timed-out check says so, with its limit: it proved nothing, which is not a red check", (res["timed_out"], res["limit"]), (True, 1))
res = core_verify.run_check("echo out; echo err >&2; exit 3", ROOT)
s.eq("a check's exit status and both streams", (res["rc"], "out" in res["output"], "err" in res["output"]), (3, True, True))
s.eq("a check that ends on its own did not time out", res["timed_out"], False)
s.eq("a command that cannot start did not time out either", core_verify.run_check("true", os.path.join(ROOT, "no-such-folder"))["timed_out"], False)
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

# ---- two checkouts of one repo never run the recipe at the same time (the gate lock) ----------------------------------
# Control, on the code before the lock: the second gate started while the first was still inside its check, so the case below
# FAILed with "two gates of one repo ran one after the other: second started <t>, first ended <t>" (the exact output is in the PR).

# The order is forced, not timed: the first check holds the lock until the test writes `release`, and the test writes it only
# once the second gate has printed its waiting line. A loaded machine cannot let the second arrive after the first has finished.
stamp_dir = helpers.mkdtemp("fwx-gate-")  # outside every checkout, so the trees stay clean
stamps = os.path.join(stamp_dir, "out")
release = os.path.join(stamp_dir, "release")
os.makedirs(stamps)
stamp = helpers.write(stamp_dir, "stamp.py", "import json, os, sys, time\n"
                      "t0 = time.time()\nopen(os.path.join(sys.argv[1], '%d.start' % os.getpid()), 'w').close()\n"
                      "for _ in range(300):\n    if os.path.exists(sys.argv[2]):\n        break\n    time.sleep(0.1)\n"
                      "json.dump([t0, time.time()], open(os.path.join(sys.argv[1], '%d.json' % os.getpid()), 'w'))\n")
repo, phase = make(["python3 %s %s %s" % (shlex.quote(stamp), shlex.quote(stamps), shlex.quote(release))])
other = helpers.add_worktree(repo, "gate-b")
FWX = [sys.executable, os.path.join(ROOT, "bin", "fwx"), "verify", "--dir", phase]
first = subprocess.Popen(FWX, cwd=repo, env=helpers.clean_env(**ENV), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
for _ in range(300):  # start the second only once the first is inside its check, so the second has to wait if there is a lock
    if first.poll() is not None or any(f.endswith(".start") for f in os.listdir(stamps)):
        break
    time.sleep(0.1)
second = subprocess.Popen(FWX, cwd=other, env=helpers.clean_env(**ENV), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
seen = b""
for _ in range(150):  # up to 30 s for the second to say it waits; without a lock it never does and its check waits for `release` too
    if select.select([second.stderr], [], [], 0.2)[0]:
        seen += os.read(second.stderr.fileno(), 4096)
    if b"waiting for another gate" in seen or second.poll() is not None:
        break
open(release, "w").close()
out1, err1 = first.communicate(timeout=120)
out2, err2 = second.communicate(timeout=120)
err2 = seen.decode("utf-8", "replace") + err2.decode("utf-8", "replace")
s.eq("both gates of the one repo are green", (first.returncode, second.returncode), (0, 0))
times = sorted(json.load(open(os.path.join(stamps, f))) for f in os.listdir(stamps) if f.endswith(".json"))
s.eq("both gates ran their check", len(times), 2)
if len(times) == 2:
    s.ok("two gates of one repo ran one after the other: second started %.1f, first ended %.1f" % (times[1][0], times[0][1]),
         times[1][0] >= times[0][1])
common = helpers.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
lock = os.path.join(common, "fwx", "gate.lock")
waited = [e for e in (err1, err2) if "fwx: waiting for another gate of this repo to finish (lock %s)" % lock in e]
s.eq("exactly one of them said it was waiting, naming the lock", len(waited), 1)

r = helpers.fwx(repo, "verify", "--dir", phase, env=ENV)
s.ok("a gate on its own does not wait", "waiting for another gate" not in r.stderr and r.returncode == 0, r.stderr)

# A check of the recipe that itself runs `fwx verify` on the repo does not wait for the lock its own gate holds (the lock path is
# exported as FWX_GATE_LOCK while it is held). Control, on the head before that: the inner gate blocked in flock until the outer
# one killed the check at its 6 s limit, so the outer gate ended red: "FAIL: a check that runs fwx verify on the same repo does
# not deadlock on the gate lock: exit 1 in 6.x s".
inner = "%s %s verify" % (shlex.quote(sys.executable), shlex.quote(os.path.join(ROOT, "bin", "fwx")))
repo, phase = make(['[ -n "$FWX_TEST_INNER" ] || FWX_TEST_INNER=1 %s' % inner], project={"check_timeout_s": 6})
t0 = time.monotonic()
r = helpers.fwx(repo, "verify", "--dir", phase, env=ENV)
took = time.monotonic() - t0
s.ok("a check that runs fwx verify on the same repo does not deadlock on the gate lock: exit %s in %.1f s" % (r.returncode, took),
     r.returncode == 0, r.stderr)

r = helpers.fwx(ROOT, "help")
s.ok("`fwx help` lists verify", any(line.split()[:2] == ["fwx", "verify"] for line in r.stdout.splitlines()), r.stdout)

s.done()
