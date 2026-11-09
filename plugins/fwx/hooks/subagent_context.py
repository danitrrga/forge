#!/usr/bin/env python3
"""SubagentStart: hand the phase's base-context file to the agent that starts, by the table of cases, and never write.

referent: forge hooks/ponytail_subagent.py @f8a9efb (the shape: one allowlist-by-type, read from the input's agent_type;
the hook is the one place that decides who gets what, so a matcher in hooks.json would split the decision in two)

The file is written by `fwx context-base build` (lib/fwx/context_base.py); this hook only reads it. What each `agent_type`
gets is the row of data/context-base.tsv (the exact type, else the `*` row): `map` is the text up to `## Decided`,
`map+decided` the whole file, `none` nothing. The hook sees the agent_type, session_id, cwd and agent_id and never the
model or the prompt (measured), so the table is by type.

Silent, exit 0, nothing printed: a `none` row; a cwd that is no git repository; no phase (none open, or several open and
none bound to this session); no base file for the phase. A failure is never silent: exit 1 and one line on stderr,
`context-base: <n> units over the cap` for a text over 9500 UTF-16 units (Claude Code persists an additionalContext over
10,000 into a preview with no warning) or `context-base: <error>` for anything else; Claude Code keeps that line in the
subagent's transcript as `hook_non_blocking_error`, which is what the audit reads.

  subagent_context.py                      the phase of the session (`state.resolve`, which binds nothing), from a worktree too
  subagent_context.py --file F [--source S]  the construction's hand-written file: no phase; delivers only when the git
                                           common dir of the cwd is the one F is in, and with --source, only while F is
                                           sealed and its source has not moved on
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

HARD_CAP = 9500  # units; the plan's 9000 is the builder's, this is the hook's margin under Claude Code's 10,000
DECIDED = "## Decided\n"


class HookError(Exception):
    """A failure that is said on stderr and exits 1."""


def common_dir(path):
    """The absolute git common dir of `path`, or None when it is not inside a git repository."""
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           capture_output=True, text=True)
    except OSError as e:
        raise HookError("cannot run git (%s)" % e)
    out = r.stdout.strip()
    return os.path.realpath(out) if r.returncode == 0 and out else None


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise HookError("%s cannot be read (%s)" % (path, e))


def options(argv):
    """`{--file, --source}` from the arguments; an unknown or valueless option is an error."""
    opts, i = {}, 0
    while i < len(argv):
        if argv[i] in ("--file", "--source") and argv[i] not in opts and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            raise HookError("usage: subagent_context.py [--file F [--source S]] (got %r)" % argv[i])
    if "--source" in opts and "--file" not in opts:
        raise HookError("--source needs --file")
    return opts


def base_text(cwd, session_id, opts, cb, state):
    """The text of the base file this agent's session is to be given, or None when there is none to give."""
    if "--file" in opts:
        target = os.path.realpath(opts["--file"])
        here, there = common_dir(cwd), common_dir(os.path.dirname(target))
        if here is None or here != there:
            return None
        text = read(target)
        if text is None:
            raise HookError("%s is not there" % opts["--file"])
        if "--source" in opts:
            problems = cb.inspect(target, source=opts["--source"])[1]
            if problems:
                raise HookError(problems[0])
        return text
    if common_dir(cwd) is None:
        return None
    where = state.resolve(cwd, session_id)
    if not where["phase_dir"]:
        return None
    return read(cb.base_path(where["phase_dir"]))


def run(stdin_text, argv):
    """What the hook prints (a str, '' for nothing); a HookError for a failure."""
    try:
        event = json.loads(stdin_text)
    except ValueError as e:
        raise HookError("the input is not JSON (%s)" % e)
    agent_type = event.get("agent_type") if isinstance(event, dict) else None
    if not isinstance(agent_type, str) or not agent_type:
        raise HookError("the input has no agent_type")
    from fwx import config, context_base as cb, state
    opts = options(argv)
    try:
        sections = cb.sections_for(agent_type)
        if sections == "none":
            return ""
        cwd = event.get("cwd") or os.getcwd()
        session_id = state.session_id(event.get("session_id") or None)
        text = base_text(cwd, session_id, opts, cb, state)
    except (cb.ContextBaseError, state.StateError, config.ConfigError) as e:
        raise HookError(str(e))
    if text is None:
        return ""
    if sections == "map":
        text = text.split(DECIDED, 1)[0]
    n = cb.units(text)
    if n > HARD_CAP:
        raise HookError("%d units over the cap" % n)
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}}, ensure_ascii=False)


def main(argv):
    try:
        out = run(sys.stdin.read(), argv)
    except HookError as e:
        sys.stderr.write("context-base: %s\n" % " ".join(str(e).split()))
        return 1
    except Exception as e:  # nothing may fail quietly: a bug is a line on stderr and exit 1 too
        sys.stderr.write("context-base: %s: %s\n" % (type(e).__name__, " ".join(str(e).split())))
        return 1
    if out:
        sys.stdout.buffer.write(out.encode("utf-8", "surrogatepass") + b"\n")
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
