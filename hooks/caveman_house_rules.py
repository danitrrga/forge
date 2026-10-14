#!/usr/bin/env python3
"""SessionStart hook: emit the user's house rules as an overlay on the caveman plugin.

WHY THIS EXISTS
  The caveman plugin (caveman@caveman, JuliusBrussee/caveman) builds its ruleset by reading
  its own skills/caveman/SKILL.md at runtime, and offers no supported extension point -- its
  user config takes `defaultMode` and nothing else. Editing SKILL.md inside
  ~/.claude/plugins/cache/ would work until the next `/plugin update caveman` silently
  reverted it, so the additions live HERE instead, in git, and are injected as a second
  SessionStart context block right after caveman's own.

  Rules text is in the sibling caveman_house_rules.md so the user can edit the rules without
  touching code. This script only reads and prints it.

WIRING
  User scope ~/.claude/settings.json -> hooks.SessionStart, emitted by
  its row in forge/hooks.py::USER_HOOKS so it survives SessionStart
  regeneration and reproduces on a fresh machine. User scope (not per-project) because hook
  arrays concatenate across scopes, so one entry covers every project -- same reasoning as
  the adapter's row for another user hook in the same table.

  Deliberately NOT gated on caveman being active: these rules are about bureaucracy and
  plain speech, which hold whether or not replies are compressed. Silent no-op if the
  markdown is missing -- a missing rules file must never break session startup.
"""
import os
import sys

RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caveman_house_rules.md")


def main():
    # Claude Code pipes the hook payload on stdin; nothing here needs it, but draining it
    # avoids an EPIPE on the writer side if it ever blocks on a full buffer.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    try:
        with open(RULES, encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError:
        return 0  # absent/unreadable -> emit nothing, never fail the session

    if text:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
