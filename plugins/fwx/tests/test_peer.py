#!/usr/bin/env python3
"""`fwx peer-review` (lib/fwx/commands/peer.py): an active review of a git range by another model, run as a chat of Orca's Antigravity
agent in a throwaway worktree of HEAD, which writes its result to a JSON file there. The tests put a fake `orca` first on PATH (a script
that answers `status`, `agent installed`, `agent launch` and `agent read` from a scenario file, writes the result file where the prompt
says, and records what it was launched with and where) over a toy repo; no network, no Orca, no model.

referent: none, own text (the command's contract is its docstring and plugins/fwx/README.md).

Controls: every behaviour is also run on a copy of bin/fwx and lib/fwx with one line of peer.py changed (`MUTANTS`), and must go red
with the text given. A mutant that makes the command crash is red on its exit code. First FAIL line of each, seen red (a control run
stops at the first FAIL it waits for):
  empty looked_at accepted:     FAIL: empty looked_at: exit 1, naming looked_at: (0, '', {'looked_at': [], 'findings': [...
  critical not mapped to high:  FAIL: success: findings, critical is high, renumbered, with reproduction and fix: got [{'id': 'G1', ..., 'severity': 'critical', ...
  ids not renumbered:           FAIL: success: findings, critical is high, renumbered, with reproduction and fix: got [{'id': 'F1', ...
  fix dropped:                  FAIL: success: findings, critical is high, renumbered, with reproduction and fix: got [{'id': 'G1', ..., 'proposed_fix': None}, ...
  unreproduced not marked:      FAIL: a finding with no reproduction is passed on, marked unreproduced: ...'reproduced': True...
  malformed line accepted:      FAIL: a finding whose line is no integer: exit 1: (0, '', {'looked_at': ['a.txt'], 'findings': [{'id': 'G1', ..., 'line': 'x', ...
  no result file passes:        FAIL: Gemini done and no result file: exit 1 naming it: (0, ...
  missing orca exits 1:         FAIL: orca not on PATH: exit 77 and NOT RUN, NOT ARMED naming the fix: (1, 'NOT ARMED: orca is not on PATH -- install Orca ...
  unreachable Orca runs:        FAIL: Orca not reachable: exit 77, NOT RUN, NOT ARMED, open Orca: (0, '')
  no timeout:                   FAIL: working for ever: exit 1 naming the timeout, nothing left: (1, 'Traceback (most recent call last): ... (a sleep of a negative time)
  does not wait for done:       FAIL: success: exit 0 and the line: got (...), want (0, 'peer looked_at=1 findings=2 model=gemini-4-neon')
  failed launch ignored:        FAIL: launch refused: exit 1 naming `orca agent launch`, nothing left: (1, 'Traceback ... (no session id)
  worktree at the base:         FAIL: success: the worktree is a detached checkout of HEAD: ...
  worktree left behind:         FAIL: success: the worktree, its folder and the state file are gone, git lists one worktree: ...
  prompt loses reproduce:       FAIL: success: the brief: range, intent files, criteria, reproduce, proposed fix, result path, no push: ...
  resume starts again:          FAIL: resume: the second call goes on with the same chat, one launch in all: ...
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
FAKE = """#!%(py)s
import json, os, re, subprocess, sys
d = os.environ["FAKE_ORCA_DIR"]
sc = json.load(open(os.path.join(d, "scenario.json")))
a = sys.argv[1:]


def out(obj, rc=0):
    print(json.dumps(obj))
    sys.exit(rc)


if a[:1] == ["status"]:
    out(sc.get("status", {"ok": True, "result": {"runtime": {"reachable": True}}}), sc.get("status_rc", 0))
if a[:2] == ["agent", "installed"]:
    out({"ok": True, "result": {"agents": [{"id": x} for x in sc.get("agents", ["claude", "antigravity"])]}})
if a[:2] == ["agent", "launch"]:
    prompt = a[a.index("--prompt") + 1]
    m = re.search(r"(/\\S+/\\.fwx-peer/result\\.json)", prompt)
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    detached = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], capture_output=True, text=True).returncode != 0
    rec = {"argv": a, "cwd": os.path.realpath(os.getcwd()), "head": head, "detached": detached, "result_path": m.group(1) if m else None}
    log = os.path.join(d, "launches.json")
    done = json.load(open(log)) if os.path.exists(log) else []
    json.dump(done + [rec], open(log, "w"))
    out(sc.get("launch", {"ok": True, "result": {"outcome": {"kind": "structured", "sessionId": "sid-1"}}}), sc.get("launch_rc", 0))
if a[:2] == ["agent", "read"]:
    n = len(os.listdir(os.path.join(d, "reads")))
    open(os.path.join(d, "reads", str(n)), "w").close()
    reads = sc["reads"]
    reply = reads[min(n, len(reads) - 1)]
    if reply.get("state") == "done" and "result" in sc:  # the result file is there once the chat is done, not before
        path = json.load(open(os.path.join(d, "launches.json")))[-1]["result_path"]
        with open(path, "w") as f:
            f.write(sc["result"] if isinstance(sc["result"], str) else json.dumps(sc["result"]))
    out({"ok": True, "result": reply})
sys.stderr.write("fake orca: unexpected %%r\\n" %% (a,))
sys.exit(3)
"""


def chat(state="done", text="Done."):
    return {"state": state, "entries": [{"kind": "message", "role": "user", "text": "the prompt"}, {"kind": "tool", "name": "run_command", "state": "completed"},
                                        {"kind": "message", "role": "assistant", "text": text}]}


def finding(i="F1", severity="critical", line=3, **kw):
    d = {"id": i, "file": "a.txt", "line": line, "severity": severity, "claim": "claim " + i, "evidence": "evidence " + i,
         "reproduction": "python -m pytest t.py: 1 failed (" + i + ")",
         "proposed_fix": {"diff": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-x\n+y\n", "rationale": "why " + i, "test": "test_" + i}}
    d.update(kw)
    return d


def result(findings, looked=("a.txt",)):
    return {"looked_at": list(looked), "findings": findings}


DONE = [chat()]
GOOD = {"result": result([finding("F1", "critical"), finding("F2", "low", 5, reproduction="", proposed_fix=None)]), "reads": [chat("working"), chat()]}

repo = helpers.toy_repo({"a.txt": "one\n"})
helpers.write(repo, "a.txt", "one\ntwo\nthree\n")
helpers.git(repo, "add", "-A")
helpers.git(repo, "commit", "-q", "-m", "second")
BASE = helpers.git(repo, "rev-parse", "HEAD~1").strip()
HEAD = helpers.git(repo, "rev-parse", "HEAD").strip()
PLAN = helpers.write(repo, ".fwx/plan.md", "# plan\n")
CRIT = [{"id": "C1", "text": "g is exported", "measure": "python -c 'import a'"}]
PEER_TMP = helpers.mkdtemp("fwx-peer-tmp-")  # the command makes its review folders here (TMPDIR): what a run leaves goes with it
GIT_DIR = helpers.mkdtemp("fwx-peer-git-")  # a PATH with git and no orca
os.symlink(shutil.which("git"), os.path.join(GIT_DIR, "git"))


def scenario_dir(sc):
    d = helpers.mkdtemp("fwx-peer-orca-")
    os.makedirs(os.path.join(d, "reads"))
    with open(os.path.join(d, "scenario.json"), "w") as f:
        json.dump(sc, f)
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    with open(os.path.join(bindir, "orca"), "w") as f:
        f.write(FAKE % {"py": sys.executable})
    os.chmod(os.path.join(bindir, "orca"), 0o755)
    return d


class Run:
    """One `fwx peer-review` over the toy repo: code, stdout, stderr, the launches the fake saw, the --out file's JSON, the fake's folder."""

    def __init__(self, code, so, se, launches, doc, d):
        self.code, self.so, self.se, self.launches, self.doc, self.d = code, so, se, launches, doc, d

    @property
    def launch(self):
        return self.launches[0] if self.launches else {}


def run(bin_fwx, sc, with_orca=True, argv=None, config=None, seconds=20, d=None, extra=()):
    d = d or scenario_dir(sc)
    out = os.path.join(d, "peer.json")
    cfg = os.path.join(repo, ".claude", "fwx.json")
    if config is None:
        if os.path.exists(cfg):
            os.remove(cfg)
    else:
        helpers.write(repo, ".claude/fwx.json", json.dumps(dict({"schema": 1}, **config)))
    path = (os.path.join(d, "bin") + os.pathsep if with_orca else "") + GIT_DIR
    args = argv if argv is not None else ["--base", BASE, "--head", HEAD, "--out", out, "--dir", repo] + list(extra)
    try:
        r = subprocess.run([sys.executable, bin_fwx, "peer-review"] + args, cwd=repo, capture_output=True, text=True, timeout=seconds,
                           env=helpers.clean_env(PATH=path, FAKE_ORCA_DIR=d, TMPDIR=PEER_TMP))
        code, so, se = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        code, so, se = 124, "", "killed after %d s" % seconds
    launches = []
    if os.path.exists(os.path.join(d, "launches.json")):
        with open(os.path.join(d, "launches.json")) as f:
            launches = json.load(f)
    doc = None
    if os.path.exists(out):
        with open(out) as f:
            doc = json.load(f)
    return Run(code, so.strip(), se.strip(), launches, doc, d)


def worktrees():
    return [l for l in helpers.git(repo, "worktree", "list").splitlines() if l.strip()]


def flag(argv, k):
    return argv[argv.index(k) + 1] if k in argv else None


def cases(S, bin_fwx):
    # success: the line, the file, the findings, how the chat was launched, where, with what brief, and what is left afterwards
    r = run(bin_fwx, GOOD, extra=["--intent", PLAN, "--criteria", json.dumps(CRIT)])
    S.eq("success: exit 0 and the line", (r.code, r.so), (0, "peer looked_at=1 findings=2 model=gemini-4-neon"))
    got = (r.doc or {}).get("findings")
    want = [{"id": "G1", "file": "a.txt", "line": 3, "severity": "high", "claim": "claim F1", "evidence": "evidence F1",
             "reproduction": "python -m pytest t.py: 1 failed (F1)", "reproduced": True,
             "proposed_fix": {"diff": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-x\n+y\n", "rationale": "why F1", "test": "test_F1"}},
            {"id": "G2", "file": "a.txt", "line": 5, "severity": "low", "claim": "claim F2", "evidence": "evidence F2",
             "reproduction": "", "reproduced": False, "proposed_fix": None}]
    S.eq("success: findings, critical is high, renumbered, with reproduction and fix", got, want)
    S.eq("success: the file has looked_at, model and a duration", (sorted(r.doc or {}), (r.doc or {}).get("looked_at"), (r.doc or {}).get("model")),
         (["duration_seconds", "findings", "looked_at", "model"], ["a.txt"], "gemini-4-neon"))
    argv = r.launch.get("argv") or []
    S.eq("success: a chat of the antigravity agent with the configured model and effort",
         (flag(argv, "--agent"), flag(argv, "--surface"), flag(argv, "--model"), flag(argv, "--effort")), ("antigravity", "chat", "gemini-4-neon", "high"))
    wt = flag(argv, "--worktree") or ""
    S.ok("success: launched in a worktree of its own, not the checkout, and in it", wt.startswith("path:") and wt[5:] == r.launch.get("cwd") and
         os.path.realpath(wt[5:]) != os.path.realpath(repo), repr((wt, r.launch.get("cwd"))))
    S.ok("success: the worktree is a detached checkout of HEAD", r.launch.get("head") == HEAD and r.launch.get("detached") is True,
         repr((r.launch.get("head"), HEAD, r.launch.get("detached"))))
    prompt = flag(argv, "--prompt") or ""
    S.ok("success: the brief: range, intent files, criteria, reproduce, proposed fix, result path, no push",
         "git diff %s..%s" % (BASE, HEAD) in prompt and os.path.realpath(PLAN) in prompt and '"measure": "python -c \'import a\'"' in prompt
         and "REPRODUCE every defect" in prompt and "proposed_fix" in prompt and "Never push" in prompt and "throwaway git worktree" in prompt
         and (r.launch.get("result_path") or "").startswith(wt[5:]), prompt)
    S.ok("success: the worktree, its folder and the state file are gone, git lists one worktree",
         not os.path.exists(wt[5:]) and not os.path.exists(os.path.join(r.d, "peer.json.state")) and len(worktrees()) == 1,
         repr((os.path.exists(wt[5:]), worktrees())))
    # configuration
    r = run(bin_fwx, GOOD, config={"peer": {"model": "toy-model", "effort": "low"}})
    argv = r.launch.get("argv") or []
    S.eq("peer.model and peer.effort of the configuration are the launch's", [flag(argv, "--model"), flag(argv, "--effort")], ["toy-model", "low"])
    r = run(bin_fwx, GOOD, config={"peer": {"timeout_s": 0}})
    S.ok("a peer.timeout_s that is no positive number: exit 2 naming it", r.code == 2 and "peer.timeout_s" in r.se and not r.launches, repr((r.code, r.se)))
    # a finding with no reproduction is passed on and marked; a bad fix is dropped, not the finding
    r = run(bin_fwx, {"result": result([finding(reproduction="", proposed_fix={"diff": "", "rationale": "r"})]), "reads": DONE})
    f = ((r.doc or {}).get("findings") or [{}])[0]
    S.ok("a finding with no reproduction is passed on, marked unreproduced", r.code == 0 and f.get("reproduced") is False and f.get("reproduction") == "" and f.get("proposed_fix") is None,
         repr((r.code, r.doc)))
    # no findings is valid, one that read nothing is not, nor a malformed one
    r = run(bin_fwx, {"result": result([]), "reads": DONE})
    S.eq("no findings is a valid review", (r.code, (r.doc or {}).get("findings")), (0, []))
    r = run(bin_fwx, {"result": result([finding()], looked=()), "reads": DONE})
    S.ok("empty looked_at: exit 1, naming looked_at", r.code == 1 and "looked_at" in r.se and r.doc is None, repr((r.code, r.se, r.doc)))
    r = run(bin_fwx, {"result": result([finding(line="x")]), "reads": DONE})
    S.ok("a finding whose line is no integer: exit 1", r.code == 1 and "finding 1" in r.se and "line" in r.se and r.doc is None, repr((r.code, r.se, r.doc)))
    r = run(bin_fwx, {"result": result([finding(severity="urgent")]), "reads": DONE})
    S.ok("a finding with an unknown severity: exit 1", r.code == 1 and "severity" in r.se and r.doc is None, repr((r.code, r.se, r.doc)))
    r = run(bin_fwx, {"reads": [chat(text="I could not finish: the tests need a database.")]})
    S.ok("Gemini done and no result file: exit 1 naming it", r.code == 1 and "wrote no .fwx-peer/result.json" in r.se and "need a database" in r.se and r.doc is None, repr((r.code, r.se)))
    S.ok("a review that failed leaves no worktree and no state", len(worktrees()) == 1 and not os.path.exists(os.path.join(r.d, "peer.json.state")), repr(worktrees()))
    r = run(bin_fwx, {"result": "{not json", "reads": DONE})
    S.ok("a result file that is no JSON: exit 1 naming it", r.code == 1 and "is not JSON" in r.se and r.doc is None, repr((r.code, r.se)))
    # Orca
    r = run(bin_fwx, GOOD, with_orca=False)
    S.ok("orca not on PATH: exit 77 and NOT RUN, NOT ARMED naming the fix",
         r.code == 77 and r.se.startswith("NOT RUN, NOT ARMED: orca is not on PATH") and "integrations.peer_review false" in r.se and not r.launches, repr((r.code, r.se)))
    r = run(bin_fwx, dict(GOOD, status={"ok": True, "result": {"runtime": {"reachable": False}}}))
    S.ok("Orca not reachable: exit 77, NOT RUN, NOT ARMED, open Orca", r.code == 77 and "NOT RUN, NOT ARMED" in r.se and "open Orca" in r.se and not r.launches, repr((r.code, r.se)))
    r = run(bin_fwx, dict(GOOD, status={"ok": False}, status_rc=1))
    S.ok("`orca status` failing: exit 77", r.code == 77 and not r.launches, repr((r.code, r.se)))
    r = run(bin_fwx, dict(GOOD, agents=["claude"]))
    S.ok("no antigravity agent in Orca: exit 77 naming it", r.code == 77 and "antigravity" in r.se and not r.launches, repr((r.code, r.se)))
    r = run(bin_fwx, dict(GOOD, launch={"ok": False, "error": {"message": "no such workspace"}}, launch_rc=1))
    S.ok("launch refused: exit 1 naming `orca agent launch`, nothing left", r.code == 1 and "orca agent launch" in r.se and r.doc is None and len(worktrees()) == 1, repr((r.code, r.se, worktrees())))
    r = run(bin_fwx, {"reads": [chat("working")]}, config={"peer": {"timeout_s": 1}})
    S.ok("working for ever: exit 1 naming the timeout, nothing left", r.code == 1 and "not done after 1 s" in r.se and "last state: working" in r.se and r.doc is None and len(worktrees()) == 1,
         repr((r.code, r.se, worktrees())))
    # a review takes longer than a call: --max-wait ends the call, the next goes on with the same chat
    d = scenario_dir(dict(GOOD, reads=[chat("working"), chat("working"), chat("working"), chat()]))
    r1 = run(bin_fwx, None, d=d, extra=["--max-wait", "1"])
    S.ok("resume: a call that ends while it is working: exit 75, `peer running`, the worktree and the state kept",
         r1.code == 75 and re.match(r"^peer running elapsed=\d+ of=2700$", r1.so) and os.path.exists(os.path.join(d, "peer.json.state")) and len(worktrees()) == 2 and r1.doc is None,
         repr((r1.code, r1.so, r1.se, worktrees())))
    r2 = run(bin_fwx, None, d=d, extra=["--max-wait", "30"])
    S.ok("resume: the second call goes on with the same chat, one launch in all",
         r2.code == 0 and r2.so == "peer looked_at=1 findings=2 model=gemini-4-neon" and len(r2.launches) == 1 and len(worktrees()) == 1
         and not os.path.exists(os.path.join(d, "peer.json.state")), repr((r2.code, r2.so, r2.se, len(r2.launches), worktrees())))
    d = scenario_dir(dict(GOOD, reads=[chat("working")]))
    run(bin_fwx, None, d=d, extra=["--max-wait", "1"])
    r = run(bin_fwx, None, d=d, argv=["--base", HEAD, "--head", BASE, "--out", os.path.join(d, "peer.json"), "--dir", repo])
    S.ok("resume: the state of another range is refused, naming it", r.code == 2 and "still running" in r.se and "delete the file" in r.se, repr((r.code, r.se)))
    helpers.git(repo, "worktree", "remove", "--force", [w.split()[0] for w in worktrees() if w.split()[0] != os.path.realpath(repo)][0])
    # the range and the options
    r = run(bin_fwx, GOOD, argv=["--base", HEAD, "--head", HEAD, "--out", "/nonexistent-dir-x/out.json", "--dir", repo])
    S.ok("an empty range: exit 2, nothing launched", r.code == 2 and "empty" in r.se and not r.launches, repr((r.code, r.se)))
    r = run(bin_fwx, GOOD, argv=["--base", "nonesuch", "--head", HEAD, "--out", "/tmp/x.json", "--dir", repo])
    S.ok("a bad revision: exit 2", r.code == 2 and "not a commit" in r.se and not r.launches and len(worktrees()) == 1, repr((r.code, r.se)))
    r = run(bin_fwx, GOOD, argv=["--base", BASE])
    S.ok("missing options: exit 2 with the usage", r.code == 2 and "usage: fwx peer-review" in r.se, repr((r.code, r.se)))
    r = run(bin_fwx, GOOD, extra=["--intent", "/nonexistent/plan.md"])
    S.ok("an --intent that does not exist: exit 2", r.code == 2 and "--intent" in r.se, repr((r.code, r.se)))
    r = run(bin_fwx, GOOD, extra=["--criteria", "{}"])
    S.ok("--criteria that is no JSON list: exit 2", r.code == 2 and "--criteria" in r.se and not r.launches, repr((r.code, r.se)))
    r = run(bin_fwx, GOOD, extra=["--max-wait", "0"])
    S.ok("--max-wait that is no positive number: exit 2", r.code == 2 and "--max-wait" in r.se and not r.launches, repr((r.code, r.se)))


# name, text to replace (once, in peer.py), its replacement, the FAIL text that must appear
MUTANTS = [
    ("empty looked_at accepted", "or not looked or not all(_text(x)", "or not all(_text(x)", "FAIL: empty looked_at"),
    ("critical not mapped to high", '"critical": "high"}', '"critical": "critical"}', "FAIL: success: findings, critical is high"),
    ("ids not renumbered", '"id": "G%d" % n', '"id": f.get("id")', "FAIL: success: findings, critical is high"),
    ("fix dropped", 'and _text(fix.get("rationale")) else None', "and False else None", "FAIL: success: findings, critical is high"),
    ("unreproduced not marked", '"reproduced": bool(repro)', '"reproduced": True', "FAIL: a finding with no reproduction is passed on"),
    ("malformed line accepted", 'if not isinstance(f.get("line"), int) or isinstance(f.get("line"), bool):', "if False:", "FAIL: a finding whose line is no integer"),
    ("no result file passes", '    except OSError:\n        raise Stop(1, "peer review failed: Gemini was done and wrote no', '    except OSError:\n        return ["x"], []\n        raise Stop(1, "peer review failed: Gemini was done and wrote no',
     "FAIL: Gemini done and no result file"),
    ("missing orca exits 1", 'raise Stop(NOT_RUN, "NOT ARMED: orca is not on PATH', 'raise Stop(1, "NOT ARMED: orca is not on PATH', "FAIL: orca not on PATH: exit 77"),
    ("unreachable Orca runs", '.get("reachable") is not True', '.get("reachable") is None', "FAIL: Orca not reachable: exit 77"),
    ("no timeout", "if left <= 0:", "if False:", "FAIL: working for ever: exit 1 naming the timeout"),
    ("does not wait for done", 'if result.get("state") == "done":', "if True:", "FAIL: success: exit 0 and the line"),
    ("failed launch ignored", 'if rc != 0 or launched.get("ok") is not True or not isinstance(sid, str) or not sid:', "if False:", "FAIL: launch refused"),
    ("worktree at the base", 'st["wt"], shas[1]]', 'st["wt"], shas[0]]', "FAIL: success: the worktree is a detached checkout of HEAD"),
    ("worktree left behind", '    subprocess.run(["git", "-C", st["top"], "worktree", "remove", "--force", st["wt"]], capture_output=True, stdin=subprocess.DEVNULL)\n',
     "    return\n", "FAIL: success: the worktree, its folder and the state file are gone"),
    ("prompt loses reproduce", '"REPRODUCE every defect before you report it', '"Skip every defect before you report it', "FAIL: success: the brief"),
    ("resume starts again", "    if os.path.exists(state_path):\n        try:", "    if False:\n        try:", "FAIL: resume: the second call goes on with the same chat"),
]


def mutant(name, old, new, want):
    work = helpers.mkdtemp("fwx-peer-mut-")
    shutil.copytree(os.path.join(ROOT, "lib", "fwx"), os.path.join(work, "lib", "fwx"), ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(work, "bin"))
    shutil.copy(os.path.join(ROOT, "bin", "fwx"), os.path.join(work, "bin", "fwx"))
    p = os.path.join(work, "lib", "fwx", "commands", "peer.py")
    with open(p, encoding="utf-8") as f:
        text = f.read()
    if text.count(old) != 1:
        return "the anchor of %s is in peer.py %d times, not once" % (name, text.count(old))
    with open(p, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))
    ctl = helpers.FirstFail(lambda line: want in line)
    ctl.run(cases, ctl, os.path.join(work, "bin", "fwx"))
    helpers.remove(work)
    # a control that stops at its first FAIL leaves the worktrees of the run it cut short: the next control starts clean
    for w in worktrees()[1:]:
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", w.split()[0]], capture_output=True)
    return None if ctl.seen else "%s: no FAIL with %r; saw %r" % (name, want, ctl.fails[-3:])


if not shutil.which("git"):
    helpers.Suite().not_run("git is not on PATH")
s = helpers.Suite()
cases(s, os.path.join(ROOT, "bin", "fwx"))
for m in MUTANTS:
    why = mutant(*m)
    s.ok("control: %s goes red" % m[0], why is None, why or "")
s.done()
