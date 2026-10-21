"""hooks/ponytail_subagent.py against a toy Ponytail install: the eight GSD agents that execute, debug
or review get the ruleset, every other agent gets nothing, a broken install is a visible error, and a
manual /ponytail change holds for its own session and no other.

Seen to fail first: before the hook existed every case failed ("can't open file .../ponytail_subagent.py",
17 of 17), and with the allowlist check removed 7 failed, from "gsd-planner: want no output, got the
ruleset" to "(empty agent_type): want no output, got the ruleset".
The per-session cases (SEQUENCES) were added before the UserPromptSubmit half: 7 of 32 failed on the hook
without it ("off: (silent, executor, planner, a new session) = (True, 'full', '-', 'full'), want (True, '-',
'-', 'full')"). Mutated after: the session level ignored, 7 failed; "stop ponytail" ignored, "stop ponytail:
... (True, 'ultra', '-', 'full'), want (True, '-', '-', 'full')"; a bare /ponytail always full, "lite then
bare: ... 'full' ... want ... 'lite'".
"""
import json, os, shutil, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ponytail_subagent.py")
ON = ["gsd-executor", "gsd-debugger", "gsd-code-fixer", "gsd-code-reviewer", "gsd-verifier",
      "gsd-security-auditor", "gsd-nyquist-auditor", "gsd-integration-checker"]
OFF = ["gsd-planner", "gsd-phase-researcher", "general-purpose", "Explore", "gsd-executor-x", "x-gsd-executor", ""]
# The toy plugin's builder answers like Ponytail's: the header, then the level it was asked for.
STUB = "exports.getPonytailInstructions = m => 'PONYTAIL MODE ACTIVE — level: ' + m + '\\n\\nrules';\n"

fails, made = [], []


def toy(with_plugin=True):
    cfg = tempfile.mkdtemp(prefix="ponytail-toy-")
    made.append(cfg)
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
    env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg, HOME=cfg)
    return subprocess.run([sys.executable, HOOK], input=payload, env=env, capture_output=True, text=True, timeout=30)


def start(agent, session=None):
    d = {"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": agent}
    if session is not None:
        d["session_id"] = session
    return json.dumps(d)


def prompt(text, session):
    return json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": text})


def level(cfg, session, agent="gsd-executor"):
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
r = run(toy(with_plugin=False), start("gsd-executor"))
if r.stdout.strip() or r.returncode != 1 or "ponytail@ponytail" not in r.stderr:
    fails.append("no plugin: want exit 1, no stdout, stderr naming ponytail@ponytail; got exit %d, stdout %r, stderr %r"
                 % (r.returncode, r.stdout[:120], r.stderr[-200:]))

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
    got = (quiet, level(cfg, sid), level(cfg, sid, "gsd-planner"), level(cfg, "fresh-%d" % i))
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

for d in made:
    shutil.rmtree(d, ignore_errors=True)
for f in fails:
    print("FAIL", f)
print("%d case(s), %d failed" % (checked, len(fails)))
sys.exit(1 if fails else 0)
