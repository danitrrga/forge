#!/usr/bin/env python3
"""SubagentStart: give Ponytail's ruleset to the GSD agents that execute, debug or review code, and to no other.

Ponytail (the `ponytail@ponytail` Claude Code plugin) writes the smallest change, which is what a dense
plan, a bug or a review wants, and what a discussion, a plan or a design from scratch does not. Its own
SubagentStart hook injects only while the session's mode is on, so the main thread and the subagents
are always on together. This hook breaks that tie: a project that wires it starts its sessions with
`PONYTAIL_DEFAULT_MODE=off` and still gets the ruleset in the agents of AGENTS, whatever the mode.

The list is an allowlist checked here, not a hook matcher, so a missing or unknown agent_type gets
nothing. The text is Ponytail's own, built by the installed plugin's hooks/ponytail-instructions.js:
forge copies none of it. A broken install exits 1, which Claude Code shows and does not block on.
"""
import json, os, subprocess, sys

PLUGIN = "ponytail@ponytail"
LEVEL = "full"
AGENTS = {"gsd-executor", "gsd-debugger", "gsd-code-fixer", "gsd-code-reviewer", "gsd-verifier",
          "gsd-security-auditor", "gsd-nyquist-auditor", "gsd-integration-checker"}
BUILD = "process.stdout.write(require(process.argv[1]).getPonytailInstructions(process.argv[2]))"


def ruleset():
    """Ponytail's ruleset at LEVEL, from the install Claude Code records (its cache path carries the version)."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    with open(os.path.join(cfg, "plugins", "installed_plugins.json"), encoding="utf-8") as fh:
        rows = json.load(fh).get("plugins", {}).get(PLUGIN) or []
    if not rows:
        raise LookupError("%s is not installed (claude plugin install %s)" % (PLUGIN, PLUGIN))
    root = next((r for r in rows if r.get("scope") == "user"), rows[0])["installPath"]
    r = subprocess.run(["node", "-e", BUILD, os.path.join(root, "hooks", "ponytail-instructions.js"), LEVEL],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0 or not r.stdout.startswith("PONYTAIL MODE ACTIVE"):
        raise RuntimeError("%s under %s did not build its ruleset: %s" % (PLUGIN, root, (r.stderr.strip().splitlines() or ["no output"])[-1]))
    return r.stdout


def main():
    try:
        agent = json.loads(sys.stdin.read()).get("agent_type")
    except (ValueError, AttributeError):
        return 0
    if agent not in AGENTS:
        return 0
    try:
        text = ruleset()
    except Exception as e:  # never block a subagent: say why on stderr and let it run without
        print("ponytail_subagent: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
