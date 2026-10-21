"""hooks/ponytail_subagent.py against a toy Ponytail install: the eight GSD agents that execute, debug
or review get the ruleset, every other agent gets nothing, and a broken install is a visible error.

Seen to fail first: before the hook existed every case failed ("can't open file .../ponytail_subagent.py",
17 of 17), and with the allowlist check removed 7 failed, from "gsd-planner: want no output, got the
ruleset" to "(empty agent_type): want no output, got the ruleset".
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
    env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg)
    return subprocess.run([sys.executable, HOOK], input=payload, env=env, capture_output=True, text=True, timeout=30)


def start(agent):
    return json.dumps({"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": agent})


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

for d in made:
    shutil.rmtree(d, ignore_errors=True)
for f in fails:
    print("FAIL", f)
print("%d case(s), %d failed" % (checked, len(fails)))
sys.exit(1 if fails else 0)
