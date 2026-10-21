#!/usr/bin/env python3
"""SubagentStart: give Ponytail's ruleset to the GSD agents that execute, debug or review code, and to no other.
UserPromptSubmit: remember a manual `/ponytail` change for the rest of that session, and only that session.

Ponytail (the `ponytail@ponytail` Claude Code plugin) writes the smallest change, which is what a dense
plan, a bug or a review wants, and what a discussion, a plan or a design from scratch does not. Its own
SubagentStart hook injects only while the session's mode is on, so the main thread and the subagents
are always on together. This hook breaks that tie: a project that wires it starts its sessions with
`PONYTAIL_DEFAULT_MODE=off` and still gets the ruleset in the agents of AGENTS, whatever the mode.

The list is an allowlist checked here, not a hook matcher, so a missing or unknown agent_type gets
nothing. The text is Ponytail's own, built by the installed plugin's hooks/ponytail-instructions.js:
forge copies none of it. A broken install exits 1, which Claude Code shows and does not block on.

A `/ponytail lite|full|ultra|off`, a bare `/ponytail`, "stop ponytail" or "normal mode" changes the level
these agents get for the rest of the session: the plugin keeps its mode per project, shared by every
session there and cleared by each new one, so the level is kept here per session_id instead, and a new
session starts at LEVEL again. The grammar mirrors ponytail-mode-tracker.js (5.3.2); `/ponytail default`
and `/ponytail band` change no session. The plugin's own subagent injection is off where this is wired
(PONYTAIL_SUBAGENT_MATCHER that matches nothing), so an agent gets one copy.
"""
import json, os, re, subprocess, sys, time

PLUGIN = "ponytail@ponytail"
LEVEL = "full"
AGENTS = {"gsd-executor", "gsd-debugger", "gsd-code-fixer", "gsd-code-reviewer", "gsd-verifier",
          "gsd-security-auditor", "gsd-nyquist-auditor", "gsd-integration-checker"}
BUILD = "process.stdout.write(require(process.argv[1]).getPonytailInstructions(process.argv[2]))"
LEVELS = ("off", "lite", "full", "ultra")
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
KEEP_DAYS = 7  # a session's level file older than this is a finished session's


def state_path(session):
    """The file that holds `session`'s level, None for an id that is not a plain name."""
    if not isinstance(session, str) or not SESSION_ID.match(session):
        return None
    return os.path.join(os.path.expanduser("~"), ".local", "state", "forge", "ponytail", session)


def session_level(session):
    p = state_path(session)
    try:
        with open(p, encoding="utf-8") as fh:
            got = fh.read().strip()
        return got if got in LEVELS else LEVEL
    except (OSError, TypeError):
        return LEVEL


def asked_level(text, current):
    """The level a prompt sets, as ponytail-mode-tracker.js reads it, or None when it sets none."""
    t = text.strip().lower()
    if re.match(r"^[/@$]ponytail", t):
        parts = t.split()
        if re.sub(r"^[@$]", "/", parts[0]) not in ("/ponytail", "/ponytail:ponytail"):
            return None
        arg = parts[1] if len(parts) > 1 else ""
        if arg in LEVELS:
            return arg
        if arg == "":  # bare: keep a level that is on, else on at full
            return current if current != "off" else "full"
        return None
    return "off" if re.sub(r"[.!?\s]+$", "", t) in ("stop ponytail", "normal mode") else None


def remember(session, text):
    p = state_path(session)
    if p is None or not isinstance(text, str):
        return
    new = asked_level(text, session_level(session))
    if new is None:
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(new)
    old = time.time() - KEEP_DAYS * 86400
    for f in os.listdir(os.path.dirname(p)):
        q = os.path.join(os.path.dirname(p), f)
        if os.path.getmtime(q) < old:
            os.remove(q)


def ruleset(level):
    """Ponytail's ruleset at `level`, from the install Claude Code records (its cache path carries the version)."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    with open(os.path.join(cfg, "plugins", "installed_plugins.json"), encoding="utf-8") as fh:
        rows = json.load(fh).get("plugins", {}).get(PLUGIN) or []
    if not rows:
        raise LookupError("%s is not installed (claude plugin install %s)" % (PLUGIN, PLUGIN))
    root = next((r for r in rows if r.get("scope") == "user"), rows[0])["installPath"]
    r = subprocess.run(["node", "-e", BUILD, os.path.join(root, "hooks", "ponytail-instructions.js"), level],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0 or not r.stdout.startswith("PONYTAIL MODE ACTIVE"):
        raise RuntimeError("%s under %s did not build its ruleset: %s" % (PLUGIN, root, (r.stderr.strip().splitlines() or ["no output"])[-1]))
    return r.stdout


def main():
    try:
        data = json.loads(sys.stdin.read())
        event, agent, session = data.get("hook_event_name"), data.get("agent_type"), data.get("session_id")
    except (ValueError, AttributeError):
        return 0
    if event == "UserPromptSubmit":
        try:
            remember(session, data.get("prompt"))
        except OSError as e:  # never block a prompt
            print("ponytail_subagent: %s" % e, file=sys.stderr)
        return 0
    if agent not in AGENTS:
        return 0
    level = session_level(session)
    if level == "off":
        return 0
    try:
        text = ruleset(level)
    except Exception as e:  # never block a subagent: say why on stderr and let it run without
        print("ponytail_subagent: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
