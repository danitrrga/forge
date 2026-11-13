#!/usr/bin/env python3
"""lib/fwx/context_audit.py and `fwx context audit` (2.5 U5): from the subagent transcripts, which agent did not get the base
context its type should get. The transcript is the evidence, never what a model says it received.

Fixtures (tests/fixtures/context_audit/<verdict>/projects/...): transcripts in the shapes measured in 2.5 U1
(research/contexto-base-casos.md): `hook_success` and `hook_additional_context` attachments (content: a list of strings), a
`hook_non_blocking_error` with its `Failed with non-blocking status code:` prefix, a `<persisted-output>` entry, a Workflow
agent under `subagents/workflows/wf_*/`, and `base.md`, the toy base file every case is judged against (`--file`). Cases that need
a real phase and a real base file (today's file from the session's cwd, stale after a rebuild) build their transcripts here.

Not covered here: the real transcripts of a project (the run is in the PR), the hook (U3) and the builder (U2).

Seen red before the code existed (neither lib/fwx/context_audit.py nor the `audit` subcommand):
  FAIL: cannot import fwx.context_audit: cannot import name 'context_audit' from 'fwx' (.../lib/fwx/__init__.py)

Controls, each seen red on a copy of the repo with one thing changed in lib/fwx/context_audit.py (first FAIL line; 60 checks on the
good code; the other hook's mutants and the search ones print more FAIL lines, the count is in the commit message):
  - the audit looks only at transcripts that have an attachment (the named control; 25 FAIL):
      FAIL: missing: the agent with no attachment is reported (missing agent went unreported): audited 1 subagent(s) in 1 session(s): 0 ok, ...
  - the audit does not look under workflows/wf_*/:
      FAIL: missing: summary counts the three as none of ok, stale, not armed: got (2, 1, 0, 0, 0), want (3, 1, 0, 0, 0)
  - a `none` type that got the base is ok:
      FAIL: wrong: Explore handed the base: audited 2 subagent(s) in 1 session(s): 1 ok, 0 stale, 0 not armed
  - a `map` type that got `## Decided` is ok:
      FAIL: wrong: fwx:reviewer handed ## Decided: audited 2 subagent(s) in 1 session(s): 1 ok, 0 stale, 0 not armed
  - `<persisted-output>` is taken for a delivery:
      FAIL: over-cap: the persisted output is not a delivery: audited 1 subagent(s) in 1 session(s): 0 ok, ...
  - two marks in one attachment are taken for one:
      FAIL: double: exit: got 0, want 1
  - a stale mark is a failure / is not noticed:
      FAIL: stale: exit (a warning only): got 1, want 0
      FAIL: stale: summary: got (1, 1, 1, 0, 0), want (1, 1, 0, 1, 0)
  - nothing handed is `missing` whatever the file (no `not armed`):
      FAIL: not armed (no --file, the cwd is not a repository): exit 0: got 1, want 0
  - another hook's `hook_additional_context` counts as the base (no mark needed; 10 FAIL):
      FAIL: armed: summary (ours and Explore ok; ...): got (None, None, None, None, None), want (6, 1, 2, 0, 0)
  - an attachment of another hook event counts:
      FAIL: armed: summary (ours and Explore ok; ...): got (6, 1, 3, 0, 0), want (6, 1, 2, 0, 0)
  - the stderr of the hook's error is not shown:
      FAIL: missing: the hook's stderr is in the line (the hook_non_blocking_error): FAIL amis1gp general-purpose: missing (no hook_additional_context ...
  - a project folder of more than 200 characters (`-<hash>`) is not matched:
      FAIL: a project folder over 200 characters ends in a hash and is still found: got (None, ...), want (1, 1, 1, 0, 0)
  - --last takes the oldest / ignores N / counts a session with no subagent transcript:
      FAIL: --last defaults to 1: the newest session with subagents, not the newer one with none: got (1, 1, 1, 0, 0), want (2, 1, 2, 0, 0)
      FAIL: --last 2: both sessions: got (2, 1, 2, 0, 0), want (3, 2, 3, 0, 0)
  - no transcript is a pass:
      FAIL: no transcript: exit 77: got 0, want 77
  - the session's cwd is not looked at, so a phase's base is never found:
      FAIL: armed by the open phase and its base (no --file): exit 1: got 0, want 1
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx import context_audit as ca  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.context_audit: %s" % e)
    sys.exit(1)
FIX = os.path.join(ROOT, "tests", "fixtures", "context_audit")
BASE = os.path.join(FIX, "base.md")
TOY_PROJECT = "/nonexistent/toy-proj"
SUMMARY = re.compile(r"audited (\d+) subagent\(s\) in (\d+) session\(s\): (\d+) ok, (\d+) stale, (\d+) not armed\Z")
SCRATCH = helpers.mkdtemp("fwx-ca-")


def audit(*args, cwd=None, env=None):
    return helpers.fwx(cwd or ROOT, "context", "audit", *args, env=env)


def case(name, *extra):
    """The audit of fixtures/<name> as `--project`, against the toy base file unless `extra` says otherwise."""
    return audit("--project", TOY_PROJECT, "--projects-dir", os.path.join(FIX, name, "projects"), *extra)


def lines(r):
    return r.stdout.strip().splitlines()


def fails(r):
    return [l for l in lines(r) if l.startswith("FAIL ")]


def summary(r):
    m = SUMMARY.match(lines(r)[0]) if lines(r) else None
    return tuple(int(x) for x in m.groups()) if m else (None,) * 5  # a missing summary line fails the comparison, it does not crash


def fail_for(r, agent):
    got = [l for l in fails(r) if l.startswith("FAIL %s " % agent)]
    return got[0] if got else ""


# ---- one fixture per verdict --------------------------------------------------------------------------------------
r = case("ok", "--file", BASE)
s.eq("ok: exit", r.returncode, 0)
s.eq("ok: summary (a map agent, a map+decided agent and Explore, all fine; another hook's context beside ours is ignored)",
     summary(r), (3, 1, 3, 0, 0))
s.eq("ok: no FAIL line", fails(r), [])

r = case("missing", "--file", BASE)
s.eq("missing: exit", r.returncode, 1)
s.eq("missing: summary counts the three as none of ok, stale, not armed", summary(r), (3, 1, 0, 0, 0))
s.ok("missing: the agent with no attachment is reported (missing agent went unreported)", bool(fail_for(r, "amis2gp")), r.stdout)
s.ok("missing: a silent hook leaves no attachment and the file of today says it was owed", fail_for(r, "amis2gp").endswith("general-purpose: missing (no hook_additional_context carries the base)"),
     fail_for(r, "amis2gp"))
s.ok("missing: the hook's stderr is in the line (the hook_non_blocking_error)",
     "context-base: 9600 units over the cap" in fail_for(r, "amis1gp") and fail_for(r, "amis1gp").startswith("FAIL amis1gp general-purpose: missing"),
     fail_for(r, "amis1gp"))
s.ok("missing: the Workflow agent is audited (subagents/workflows/wf_*/)", fail_for(r, "amis3wf").startswith("FAIL amis3wf fwx:reviewer: missing"),
     "got %d FAIL lines, want 3: %s" % (len(fails(r)), r.stdout))
s.eq("missing: three FAIL lines", len(fails(r)), 3)

r = case("over-cap", "--file", BASE)
s.eq("over-cap: exit", r.returncode, 1)
s.ok("over-cap: the persisted output is not a delivery", fail_for(r, "aovr1gp").startswith("FAIL aovr1gp general-purpose: over-cap"), r.stdout)

r = case("wrong", "--file", BASE)
s.eq("wrong: exit", r.returncode, 1)
s.ok("wrong: Explore handed the base", fail_for(r, "awrg1explore").startswith("FAIL awrg1explore Explore: wrong"), r.stdout)
s.ok("wrong: fwx:reviewer handed ## Decided", fail_for(r, "awrg2reviewer").startswith("FAIL awrg2reviewer fwx:reviewer: wrong")
     and "Decided" in fail_for(r, "awrg2reviewer"), r.stdout)

r = case("double", "--file", BASE)
s.eq("double: exit", r.returncode, 1)
s.ok("double: two marks in one attachment", fail_for(r, "adbl1gp").startswith("FAIL adbl1gp general-purpose: double"), r.stdout)

r = case("stale", "--file", BASE)
s.eq("stale: exit (a warning only)", r.returncode, 0)
s.eq("stale: summary", summary(r), (1, 1, 0, 1, 0))
s.ok("stale: one WARN line naming both marks", [l for l in lines(r) if l.startswith("WARN astl1gp general-purpose: stale")] != []
     and "0badf00d" in r.stdout and "198ae9b4" in r.stdout, r.stdout)
s.eq("stale: no FAIL line", fails(r), [])

r = case("not-armed")
s.eq("not armed (no --file, the cwd is not a repository): exit 0", r.returncode, 0)
s.eq("not armed: the agent with nothing is counted as not armed, Explore (gets nothing) as ok", summary(r), (2, 1, 1, 0, 1))
r = case("not-armed", "--file", BASE)
s.eq("the same transcripts against a base file of today: exit 1", r.returncode, 1)
s.ok("the same transcripts against a base file of today: general-purpose is missing, Explore is not",
     fail_for(r, "anar1gp").startswith("FAIL anar1gp general-purpose: missing") and not fail_for(r, "anar2explore"), r.stdout)

# ---- the ways in: --session by id, CLAUDE_CONFIG_DIR, no transcript, usage -------------------------------------------------
sess = next(d for d in os.listdir(os.path.join(FIX, "missing", "projects", "-nonexistent-toy-proj")))
r = audit("--session", sess, "--projects-dir", os.path.join(FIX, "missing", "projects"), "--file", BASE)
s.ok("--session finds the folder by its id", r.returncode == 1 and len(fails(r)) == 3, "exit %d: %s" % (r.returncode, r.stdout + r.stderr))
r = audit("--session", sess, "--file", BASE, env={"CLAUDE_CONFIG_DIR": os.path.join(FIX, "missing")})
s.ok("--projects-dir defaults to ${CLAUDE_CONFIG_DIR}/projects", r.returncode == 1 and len(fails(r)) == 3, "exit %d: %s" % (r.returncode, r.stdout + r.stderr))
r = audit("--session", "no-such-session", "--projects-dir", os.path.join(FIX, "ok", "projects"), "--file", BASE)
s.eq("no transcript: exit 77", r.returncode, 77)
s.eq("no transcript: says NOT RUN, NOT ARMED", lines(r), ["NOT RUN, NOT ARMED: no subagent transcript found"])
empty = os.path.join(SCRATCH, "empty-projects")
os.makedirs(empty)
r = audit("--project", TOY_PROJECT, "--projects-dir", empty)
s.eq("an empty projects dir: exit 77", r.returncode, 77)
for label, args in (("neither --session nor --project", ()), ("both", ("--session", "x", "--project", "/p")),
                    ("--last 0", ("--project", "/p", "--last", "0")), ("--last abc", ("--project", "/p", "--last", "abc")),
                    ("--last with --session", ("--session", "x", "--last", "2")), ("a path as a session id", ("--session", "../x")),
                    ("a stray argument", ("--project", "/p", "extra")), ("an unknown option", ("--project", "/p", "--nope", "1")),
                    ("a --file that is not there", ("--project", TOY_PROJECT, "--projects-dir", os.path.join(FIX, "ok", "projects"),
                                                    "--file", os.path.join(SCRATCH, "nope.md")))):
    r = audit(*args)
    s.ok("usage: %s: exit 2 and a message on stderr" % label, r.returncode == 2 and r.stderr.strip() != "", "exit %d: %s" % (r.returncode, r.stderr))


# ---- transcripts built here: today's file from the phase, other hooks, other events, bad lines, --last -------------------------
def encoded(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def transcript(pdir, project, sid, agents, main=True, mtime=None, folder=None):
    """A session folder under `pdir`: `agents` is [(id, type, [(hookEvent, [entries])], [stderr])]; the session's own transcript
    carries the cwd."""
    sdir = os.path.join(pdir, folder or encoded(project), sid)
    os.makedirs(os.path.join(sdir, "subagents"), exist_ok=True)
    if main:
        helpers.write(os.path.dirname(sdir), sid + ".jsonl", json.dumps({"type": "user", "cwd": project, "sessionId": sid}) + "\n")
    for aid, typ, atts, errs in agents:
        base = os.path.join(sdir, "subagents", "agent-%s" % aid)
        helpers.write(sdir, "subagents/agent-%s.meta.json" % aid, json.dumps({"agentType": typ, "spawnDepth": 1}))
        rows = [{"type": "user", "agentId": aid, "cwd": project, "message": {"role": "user", "content": "go"}}, "this line is not JSON"]
        for event, entries in atts:
            rows.append({"type": "attachment", "agentId": aid, "attachment": {"type": "hook_additional_context", "hookName": event,
                                                                             "hookEvent": event, "content": entries}})
        for e in errs:
            rows.append({"type": "attachment", "agentId": aid, "attachment": {"type": "hook_non_blocking_error", "hookEvent": "SubagentStart",
                                                                             "stderr": "Failed with non-blocking status code: " + e, "exitCode": 1}})
        helpers.write(sdir, "subagents/agent-%s.jsonl" % aid, "\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n")
    if mtime is not None:
        for p in (sdir, sdir + ".jsonl"):
            if os.path.exists(p):
                os.utime(p, (mtime, mtime))
    return sdir


from fwx import context_base as cb, state  # noqa: E402

repo = helpers.toy_repo()
phase = str(state.new_phase("alpha", cwd=repo))
helpers.write(phase, "context.md", "# Context: 01-alpha\n\n## Intent\nMake the toy work.\n\n## What success means\nIt works.\n\n## Surfaces\nnone\n")
cb.build(phase)
with open(cb.base_path(phase), encoding="utf-8") as f:
    built = f.read()
maponly = built.split("## Decided")[0]  # what the hook hands a type that gets the map
OTHER = "[memory] Related memories found for this error: none"
pdir = os.path.join(SCRATCH, "projects")
SID = "22222222-0000-4000-8000-000000000001"
transcript(pdir, repo, SID, [
    ("gp-nothing", "general-purpose", [], []),
    ("gp-ours", "general-purpose", [("SubagentStart", [maponly])], []),
    ("gp-other-hook", "general-purpose", [("SubagentStart", [OTHER])], []),
    ("gp-other-event", "general-purpose", [("PostToolUse", [maponly])], []),
    ("explore-nothing", "Explore", [], []),
    ("typeless", "?", [], []),
])
r = audit("--project", repo, "--projects-dir", pdir)
s.eq("armed by the open phase and its base (no --file): exit 1", r.returncode, 1)
s.eq("armed: summary (ours and Explore ok; a typeless agent falls on the `*` row and is missing too)", summary(r), (6, 1, 2, 0, 0))
s.ok("armed: nothing handed is missing", fail_for(r, "gp-nothing").startswith("FAIL gp-nothing general-purpose: missing"), r.stdout)
s.ok("another hook's context is not the base: missing, not ok", fail_for(r, "gp-other-hook").startswith("FAIL gp-other-hook general-purpose: missing"), r.stdout)
s.ok("a mark from another event is not a delivery: missing, not ok", fail_for(r, "gp-other-event").startswith("FAIL gp-other-event general-purpose: missing"), r.stdout)
s.ok("a transcript with no meta type is judged by the `*` row, and its type is shown as ?", fail_for(r, "typeless").startswith("FAIL typeless ?: missing"), r.stdout)
s.ok("a line that is not JSON does not stop the audit", summary(r)[0] == 6, r.stdout)
r = audit("--session", SID, "--projects-dir", pdir)
s.eq("--session reads the cwd from the session's own transcript: the same verdicts", (r.returncode, len(fails(r))), (1, 4))

# today's file moves on: a rebuild with a new decision changes the mark, and what was handed turns stale
helpers.write(phase, "context.md", "# Context: 01-alpha\n\n## Intent\nMake the toy work, differently.\n\n## What success means\nIt works.\n\n## Surfaces\nnone\n")
cb.build(phase)
r = audit("--project", repo, "--projects-dir", pdir)
s.eq("the base was rebuilt: what gp-ours got is stale, counted as stale and not as ok", summary(r), (6, 1, 1, 1, 0))
s.ok("the base was rebuilt: a WARN line, and still four FAIL lines (the stale one is not a new failure)",
     any(l.startswith("WARN gp-ours general-purpose: stale") for l in lines(r)) and len(fails(r)) == 4, r.stdout)

# a phase with no base file built: owed nothing, nothing missing
repo2 = helpers.toy_repo()
state.new_phase("beta", cwd=repo2)
transcript(pdir, repo2, "22222222-0000-4000-8000-000000000002", [("gp2", "general-purpose", [], [])])
r = audit("--project", repo2, "--projects-dir", pdir)
s.ok("an open phase with no base file yet is not armed", r.returncode == 0 and summary(r) == (1, 1, 0, 0, 1), r.stdout + r.stderr)

# --last: the newest sessions that have subagent transcripts
repo3 = helpers.toy_repo()
p3 = os.path.join(SCRATCH, "projects3")
one = [("a%d" % i, "Explore", [], []) for i in range(2)]
transcript(p3, repo3, "33333333-0000-4000-8000-00000000000a", one[:1], mtime=1_700_000_000)
transcript(p3, repo3, "33333333-0000-4000-8000-00000000000b", one, mtime=1_700_000_500)
helpers.write(os.path.join(p3, encoded(repo3), "33333333-0000-4000-8000-00000000000c"), "empty-session/notes.txt", "no subagents here\n")
os.utime(os.path.join(p3, encoded(repo3), "33333333-0000-4000-8000-00000000000c"), (1_700_001_000,) * 2)
r = audit("--project", repo3, "--projects-dir", p3)
s.eq("--last defaults to 1: the newest session with subagents, not the newer one with none", summary(r), (2, 1, 2, 0, 0))
r = audit("--project", repo3, "--projects-dir", p3, "--last", "2")
s.eq("--last 2: both sessions", summary(r), (3, 2, 3, 0, 0))
r = audit("--project", repo3, "--projects-dir", p3, "--last", "9")
s.eq("--last 9: only the two that exist", summary(r)[:2], (3, 2))

# a project folder over 200 characters carries `-<6 characters>`: matched by prefix
long_project = "/" + "a" * 210
folder = encoded(long_project)[:200] + "-qbfbem"
transcript(os.path.join(SCRATCH, "projects4"), long_project, "44444444-0000-4000-8000-000000000001", [("e1", "Explore", [], [])], folder=folder)
r = audit("--project", long_project, "--projects-dir", os.path.join(SCRATCH, "projects4"))
s.eq("a project folder over 200 characters ends in a hash and is still found", summary(r), (1, 1, 1, 0, 0))

# ---- the judge, one agent at a time ------------------------------------------------------------------------------------
def judged(agent_type, entries, today):
    try:
        return ca.judge(agent_type, {"entries": entries, "errors": []}, today)[0]
    except Exception as e:  # a judge that crashes is a failed check, not a stopped run
        return "crashed: %r" % e


nothing = []
s.eq("judge: a type that gets nothing and got nothing is ok even with no file", judged("Explore", nothing, None), "ok")
s.eq("judge: a type that is owed the map, no file, nothing handed: not armed", judged("general-purpose", nothing, None), "not armed")
s.eq("judge: owed, file today, nothing handed: missing", judged("general-purpose", nothing, built), "missing")
s.eq("judge: handed with no file today: ok (it was delivered)", judged("general-purpose", [maponly], None), "ok")
s.eq("judge: a persisted entry of a type owed the base is over-cap even if its preview has no mark",
     judged("general-purpose", ["<persisted-output>\nOutput too large"], built), "over-cap")
s.eq("judge: a persisted entry of another hook for a type that gets nothing is not ours",
     judged("Explore", ["<persisted-output>\nOutput too large"], built), "ok")

s.done()
