"""hooks/ponytail_subagent.py against a toy Ponytail install: the framework's two reviewers (fwx:reviewer,
fwx:security-reviewer) get the ruleset, every other agent gets nothing (the eight gsd-* agents, fwx:executor,
fwx:review-verifier and workflow-subagent included), a broken install is a visible error, and a
manual /ponytail change holds for its own session and no other.

Seen to fail first for the gsd-* names leaving AGENTS, on the hook as it was: "gsd-executor: want no output, got the
ruleset" (the brief's "got PONYTAIL MODE ACTIVE" is the first words of that ruleset) and the same for the other seven
gsd-* names, 8 of 37 cases failed.
Seen to fail first for the framework's reviewers (3.4 U6), on the hook as it was: "fwx:reviewer: want the full
ruleset, got exit 0, stdout ''" and the same for fwx:security-reviewer, 2 of 40 cases failed; the OFF names
already passed, as they must. Earlier: before the hook existed every case failed ("can't open file .../ponytail_subagent.py",
17 of 17), and with the allowlist check removed 7 failed, from "gsd-planner: want no output, got the
ruleset" to "(empty agent_type): want no output, got the ruleset".
Seen to fail first for the review sentence (09.3 T31), on the hook as it was: "fwx:reviewer is told to run
ponytail:ponytail-review, and to go on without it when it is not available -> not in its context" and the same for
fwx:security-reviewer, 2 of 39 cases failed (Ponytail 5.3.2's own ruleset does not mention its review skill).
Seen to fail first for the review sentence with a ruleset that does not build, on the hook as it was: "fwx:reviewer,
ruleset build fails: want exit 0, the review sentence without the ruleset, the error on stderr; got exit 1, stdout ''"
and the same for fwx:security-reviewer, 2 of 42 cases failed.
The per-session cases (SEQUENCES) were added before the UserPromptSubmit half: 7 of 32 failed on the hook
without it ("off: (silent, executor, planner, a new session) = (True, 'full', '-', 'full'), want (True, '-',
'-', 'full')"). Mutated after: the session level ignored, 7 failed; "stop ponytail" ignored, "stop ponytail:
... (True, 'ultra', '-', 'full'), want (True, '-', '-', 'full')"; a bare /ponytail always full, "lite then
bare: ... 'full' ... want ... 'lite'".
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "tests"))
import sandbox  # noqa: E402

HOOK = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ponytail_subagent.py")
ON = ["fwx:reviewer", "fwx:security-reviewer"]
# The framework's executor and review-verifier never get it (ponytail only when reviewing), and neither does a
# framework agent launched without agentType, which reaches the hook as "workflow-subagent".
OFF = ["gsd-executor", "gsd-debugger", "gsd-code-fixer", "gsd-code-reviewer", "gsd-verifier", "gsd-security-auditor",
       "gsd-nyquist-auditor", "gsd-integration-checker", "gsd-planner", "general-purpose", "Explore", "",
       "fwx:executor", "fwx:review-verifier", "workflow-subagent", "fwx:reviewer-x", "x-fwx:reviewer", "reviewer"]
# The toy plugin's builder answers like Ponytail's: the header, then the level it was asked for.
STUB = "exports.getPonytailInstructions = m => 'PONYTAIL MODE ACTIVE — level: ' + m + '\\n\\nrules';\n"

fails = []


def toy(with_plugin=True):
    cfg = sandbox.mkdtemp("ponytail-toy-")
    plug = os.path.join(cfg, "plugins", "cache", "ponytail", "1.0.0")
    os.makedirs(os.path.join(plug, "hooks"))
    with open(os.path.join(plug, "hooks", "ponytail-instructions.js"), "w") as fh:
        fh.write(STUB)
    rows = {"ponytail@ponytail": [{"scope": "user", "installPath": plug}]} if with_plugin else {}
    with open(os.path.join(cfg, "plugins", "installed_plugins.json"), "w") as fh:
        json.dump({"version": 2, "plugins": rows}, fh)
    return cfg


def run(cfg, payload):
    # HOME is the toy too: the session levels live under it (~/.local/state/forge/ponytail).
    env = dict({k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, CLAUDE_CONFIG_DIR=cfg, HOME=cfg)  # no GIT_DIR of a caller's hook
    return subprocess.run([sys.executable, HOOK], input=payload, env=env, capture_output=True, text=True, timeout=30)


def start(agent, session=None):
    d = {"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": agent}
    if session is not None:
        d["session_id"] = session
    return json.dumps(d)


def prompt(text, session):
    return json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": text})


def level(cfg, session, agent="fwx:reviewer"):
    """The level the session's `agent` gets, "-" for none."""
    r = run(cfg, start(agent, session))
    if not r.stdout.strip():
        return "-"
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"].split("level: ")[1].split()[0]


cfg = toy()
checked = 0
for agent in ON:
    checked += 1
    r = run(cfg, start(agent))
    try:
        out = json.loads(r.stdout)["hookSpecificOutput"]
        ok = out["hookEventName"] == "SubagentStart" and out["additionalContext"].startswith("PONYTAIL MODE ACTIVE — level: full")
    except (ValueError, KeyError, TypeError):
        ok = False
    if r.returncode != 0 or not ok:
        fails.append("%s: want the full ruleset, got exit %d, stdout %r, stderr %r" % (agent, r.returncode, r.stdout[:120], r.stderr[-200:]))
    # Ponytail's own ruleset never says to run its review skill; the reviewers' texts no longer do either.
    checked += 1
    text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if ok else ""
    if "ponytail:ponytail-review" not in text or "the skill is not available" not in text.lower():
        fails.append("%s is told to run ponytail:ponytail-review, and to go on without it when it is not available -> not in its context" % agent)

for agent in OFF:
    checked += 1
    r = run(cfg, start(agent))
    if r.returncode != 0 or r.stdout.strip():
        fails.append("%s: want no output, got %s" % (agent or "(empty agent_type)", "the ruleset" if r.stdout.strip() else "exit %d" % r.returncode))

# Fail closed on a payload it cannot read.
checked += 1
r = run(cfg, "not json")
if r.returncode != 0 or r.stdout.strip():
    fails.append("unreadable payload: want silence and exit 0, got exit %d, stdout %r" % (r.returncode, r.stdout[:120]))

# An allowlisted agent with Ponytail not installed: no output, a non-blocking error that names the fix.
checked += 1
r = run(toy(with_plugin=False), start("fwx:reviewer"))
if r.stdout.strip() or r.returncode != 1 or "ponytail@ponytail" not in r.stderr:
    fails.append("no plugin: want exit 1, no stdout, stderr naming ponytail@ponytail; got exit %d, stdout %r, stderr %r"
                 % (r.returncode, r.stdout[:120], r.stderr[-200:]))

# An install whose ruleset does not build (the builder throws): the reviewers still get the review sentence, nothing
# else, and the error is on stderr; any other agent still gets nothing.
broken = toy()
for root, _, fs in os.walk(os.path.join(broken, "plugins", "cache")):
    for f in fs:
        if f == "ponytail-instructions.js":
            with open(os.path.join(root, f), "w") as fh:
                fh.write("exports.getPonytailInstructions = m => { throw new Error('boom'); };\n")
for agent in ON:
    checked += 1
    r = run(broken, start(agent))
    try:
        text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        text = ""
    if r.returncode != 0 or "ponytail:ponytail-review" not in text or "PONYTAIL MODE ACTIVE" in text or "did not build its ruleset" not in r.stderr:
        fails.append("%s, ruleset build fails: want exit 0, the review sentence without the ruleset, the error on stderr; got exit %d, stdout %r, stderr %r"
                     % (agent, r.returncode, r.stdout[:120], r.stderr[-120:]))
checked += 1
r = run(broken, start("fwx:executor"))
if r.stdout.strip():
    fails.append("fwx:executor, ruleset build fails: want no output, got %r" % r.stdout[:120])

# A manual change holds for its session and no other: a new session starts at the default again.
# (prompts in order, the level the session's executor then gets)
SEQUENCES = [
    ("off", ["/ponytail off"], "-"),
    ("ultra", ["/ponytail ultra"], "ultra"),
    ("lite then bare", ["/ponytail lite", "/ponytail"], "lite"),
    ("off then bare", ["/ponytail off", "/ponytail"], "full"),
    ("off then full", ["/ponytail off", "/PONYTAIL full"], "full"),
    ("plugin-qualified", ["/ponytail:ponytail ultra"], "ultra"),
    ("stop ponytail", ["/ponytail ultra", "stop ponytail"], "-"),
    ("normal mode.", ["Normal mode."], "-"),
    ("the phrase inside a request", ["please add a normal mode toggle", "stop ponytail from failing"], "full"),
    ("default is not a session change", ["/ponytail off", "/ponytail default full"], "-"),
    ("band is not a level", ["/ponytail band off"], "full"),
    ("a one-shot skill is not a level", ["/ponytail-review"], "full"),
    ("an unknown word", ["/ponytail loud"], "full"),
]
for i, (label, texts, want_level) in enumerate(SEQUENCES):
    checked += 1
    sid = "sess-%d" % i
    quiet = True
    for t in texts:
        r = run(cfg, prompt(t, sid))
        quiet = quiet and r.returncode == 0 and not r.stdout.strip()
    got = (quiet, level(cfg, sid), level(cfg, sid, "fwx:executor"), level(cfg, "fresh-%d" % i))
    if got != (True, want_level, "-", "full"):
        fails.append("%s: (silent, executor, planner, a new session) = %r, want %r" % (label, got, (True, want_level, "-", "full")))

checked += 1
if level(cfg, None) != "full":
    fails.append("a SubagentStart with no session_id: want full, got %s" % level(cfg, None))

# A session id that is not a plain name writes nothing anywhere.
checked += 1
run(cfg, prompt("/ponytail off", "../../escape"))
stray = [os.path.join(dp, f) for dp, _, fs in os.walk(cfg) for f in fs if "escape" in f or f == "ponytail"]
if stray or level(cfg, "../../escape") != "full":
    fails.append("session id ../../escape: want nothing written and full, got %s and %s" % (stray, level(cfg, "../../escape")))

# SessionStart: a worker (a top-level session, so no SubagentStart) whose worktree's git dir holds fwx-worker.json with the
# role reviewer or security-reviewer gets what those agents get, under hookEventName SessionStart; any other role, no marker or
# a marker that cannot be read gets nothing.
# A git hook that runs this suite exports GIT_DIR and GIT_WORK_TREE, and `cwd=` does not override them: with them inherited the fixture's
# `commit --allow-empty` landed in the caller's repository (15 commits there, seen on a repo set up with GIT_DIR before this change).
# The fixture's git sees no repository-location variable.
def fixture_env(cwd):
    return dict({k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, HOME=cwd, GIT_CONFIG_NOSYSTEM="1")


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *args], cwd=cwd, check=True,
                   capture_output=True, env=fixture_env(cwd))


def worker_tree(marker, linked=True):
    """A worktree (a linked one, as `fwx wave run` makes, or a main checkout) whose git dir holds `marker` as fwx-worker.json
    (a str is written as it is, a dict as JSON, None writes nothing); returns the worktree."""
    main = sandbox.mkdtemp("ponytail-worker-")
    git("init", "-q", cwd=main)
    git("commit", "-q", "--allow-empty", "-m", "x", cwd=main)
    tree = main
    if linked:
        tree = os.path.join(main, "wt")
        git("worktree", "add", "-q", "--detach", tree, cwd=main)
    gitdir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=tree, capture_output=True, text=True, check=True, env=fixture_env(tree)).stdout.strip()
    if marker is not None:
        with open(os.path.join(gitdir, "fwx-worker.json"), "w") as fh:
            fh.write(marker if isinstance(marker, str) else json.dumps(marker))
    return tree


def session_start(cwd, session="w1"):
    d = {"hook_event_name": "SessionStart", "session_id": session, "source": "startup"}
    if cwd is not None:
        d["cwd"] = cwd
    return json.dumps(d)


def worker_text(cfg, tree, session="w1"):
    """What a SessionStart in `tree` puts in the worker's context ("" for nothing), the hook event name and the exit code."""
    r = run(cfg, session_start(tree, session))
    if not r.stdout.strip():
        return "", None, r.returncode
    out = json.loads(r.stdout)["hookSpecificOutput"]
    return out["additionalContext"], out["hookEventName"], r.returncode


for role in ("reviewer", "security-reviewer"):
    for linked in (True, False):
        checked += 1
        text, event, rc = worker_text(cfg, worker_tree({"role": role, "run": "r", "unit": "T1"}, linked))
        if rc != 0 or event != "SessionStart" or not text.startswith("PONYTAIL MODE ACTIVE — level: full") or "ponytail:ponytail-review" not in text:
            fails.append("a %s worker gets the ruleset at SessionStart (%s worktree) -> %r, event %r, exit %d"
                         % (role, "linked" if linked else "main", text[:60] or "nothing", event, rc))

tree = worker_tree({"role": "reviewer", "run": "r", "unit": "T1"})
checked += 1
run(cfg, prompt("/ponytail ultra", "w2"))
if "level: ultra" not in worker_text(cfg, tree, "w2")[0]:
    fails.append("a reviewer worker gets the level its own session holds (/ponytail ultra) -> %r" % worker_text(cfg, tree, "w2")[0][:60])
checked += 1
run(cfg, prompt("/ponytail off", "w3"))
if worker_text(cfg, tree, "w3")[0]:
    fails.append("a reviewer worker whose session is off gets nothing -> the ruleset")

for label, marker in (("role executor", {"role": "executor"}), ("role review-verifier", {"role": "review-verifier"}),
                      ("role fixer", {"role": "fixer"}), ("no role", {"run": "r"}), ("role a list", {"role": ["reviewer"]}),
                      ("role in another case", {"role": "Reviewer"}), ("no marker", None), ("a marker that is not JSON", "{oops"),
                      ("a marker that is a list", '["reviewer"]'), ("an empty marker", "")):
    checked += 1
    text, _, rc = worker_text(cfg, worker_tree(marker))
    if rc != 0 or text:
        fails.append("%s gets nothing at SessionStart -> exit %d, %r" % (label, rc, text[:60]))

# A SessionStart with no cwd, a cwd that is not a directory or one that is no repository is the same silence.
for label, cwd in (("no cwd", None), ("a cwd that does not exist", os.path.join(cfg, "nowhere")), ("a cwd that is no repository", cfg),
                   ("a cwd that is not a string", 5)):
    checked += 1
    r = run(cfg, session_start(cwd))
    if r.returncode != 0 or r.stdout.strip():
        fails.append("SessionStart with %s: want silence and exit 0, got exit %d, stdout %r" % (label, r.returncode, r.stdout[:80]))

# The same two failures as SubagentStart: a ruleset that does not build leaves the review sentence, a missing install exits 1.
checked += 1
text, event, rc = worker_text(broken, tree)
if rc != 0 or event != "SessionStart" or "ponytail:ponytail-review" not in text or "PONYTAIL MODE ACTIVE" in text:
    fails.append("a reviewer worker, ruleset build fails: want exit 0 and the review sentence alone, got exit %d, %r" % (rc, text[:80]))
checked += 1
r = run(toy(with_plugin=False), session_start(tree))
if r.stdout.strip() or r.returncode != 1 or "ponytail@ponytail" not in r.stderr:
    fails.append("a reviewer worker, no plugin: want exit 1, no stdout, stderr naming it; got exit %d, stdout %r" % (r.returncode, r.stdout[:80]))

# A SubagentStart is still answered under its own event name.
checked += 1
if json.loads(run(cfg, start("fwx:reviewer")).stdout)["hookSpecificOutput"]["hookEventName"] != "SubagentStart":
    fails.append("fwx:reviewer at SubagentStart is answered under SubagentStart")

sandbox.cleanup(fails)
for f in fails:
    print("FAIL", f)
print("%d case(s), %d failed" % (checked, len(fails)))
sys.exit(1 if fails else 0)
