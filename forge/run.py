"""forge run @NAME "PROMPT" [--model M] [--cwd DIR] [--permission-mode MODE] [--json]: one headless session of this project with
session profile NAME, and its final answer on stdout. It is how an agent launches another with a specialised profile: a `claude -p`
started from a session's Bash tool does not inherit that session's profile (measured, 4.3 U0), so the profile is given here.

The child is `claude -p` with the flags `forge start @NAME` gives an interactive session (launch._flags: the same function, so the two
cannot drift), a `--session-id` of ours, `--output-format json` and `--model`, which is always passed: `sonnet` when the caller gave
none (no agent without an explicit model). No permission flag is added: forge sets no mode of its own, a headless session cannot ask,
and the profile's `--settings` permissions are added to the user's, the project's and the local ones, which still apply: the child is
not limited to the profile. `--permission-mode` takes only default, plan, acceptEdits and dontAsk, never bypassPermissions. The prompt
reaches claude on its stdin, from a file: never as an argument of claude (a prompt that starts with `-` is not a flag there, and its
length is no limit of claude's command line) and never through a shell. The caller's own `PROMPT` is one argument of `forge run`, and
the system limits that one (on Linux 128 KiB).

stdout carries only the final answer (with --json, claude's whole output), stderr one line `profile P session ID cost USD`, and the
exit code is claude's, except that a child that exits 0 with `is_error` or with output that is no result document is exit 1: an error
of the child is never a success. The session record (profiles.session_record) names the parent session when CLAUDE_CODE_SESSION_ID is
set, and says the session was started with -p, so `forge switch` refuses it. The reasons for a refusal (exit 2) are `forge start`'s, plus
what the caller asked that is refused: a prompt that is no UTF-8, an empty --model, a --permission-mode outside the four, and a call
from a forge run called from a forge run (FORGE_RUN_DEPTH, MAX_DEPTH: one more level than the caller's own, no deeper; a caller that
unsets the variable defeats it on purpose, not by accident).

The child is bounded: after --timeout seconds (default 1800) it gets TERM, KILL after launch.KILL_AFTER, and forge run exits 124; an
INT, TERM or HUP sent to forge run is passed on to the child's whole group (launch._run, headless); and a forge run that dies, SIGKILL
included, takes claude with it (the parent-death signal of launch._die_with_parent, Linux only)."""
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
import uuid

from forge import launch, lib, profiles

WHO = "forge run"
PERMISSION_MODES = ("default", "plan", "acceptEdits", "dontAsk")  # never bypassPermissions, whoever asks
MAX_DEPTH = 2  # a child of forge run may call forge run once more, and that one's child may not (FORGE_RUN_DEPTH counts the levels)
TIMEOUT = 1800  # seconds a child may run (--timeout)
TIMED_OUT = 124  # the exit code of a child that outlived it, as timeout(1)'s


def _result(text):
    """The result document claude printed (a dict whose type is `result`; the last one when it printed a list of events), or None."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    if isinstance(doc, list):
        doc = next((d for d in reversed(doc) if isinstance(d, dict) and d.get("type") == "result"), None)
    return doc if isinstance(doc, dict) and doc.get("type") == "result" else None


def cmd(a):
    depth = os.environ.get("FORGE_RUN_DEPTH", "0")
    if not (depth.isascii() and depth.isdigit() and len(depth) <= 9):  # 9 digits: int() never meets a string long enough to raise
        return launch._refuse("FORGE_RUN_DEPTH=%r is not a number of levels: `unset FORGE_RUN_DEPTH` and run it again" % depth, WHO)
    depth = int(depth)
    if depth >= MAX_DEPTH:
        return launch._refuse("this is a forge run called from a forge run called from a forge run (FORGE_RUN_DEPTH=%d): "
                              "agents launching agents stop here, so that no loop of them can start by accident; do the work in this session, "
                              "or run `forge run @NAME \"PROMPT\"` from your own terminal, where the depth starts again" % depth, WHO)
    if not a.prompt.strip():
        return launch._refuse('the prompt is empty: forge run @NAME "PROMPT"', WHO)
    try:
        prompt = a.prompt.encode("utf-8")  # an argv that is no UTF-8 reaches us as surrogates; refused before anything is written
    except UnicodeEncodeError:
        return launch._refuse("the prompt is not valid UTF-8 (a file in another encoding? convert it first, e.g. iconv -t UTF-8)", WHO)
    if a.model is not None and not a.model.strip():
        return launch._refuse("--model is empty: name a model (`--model sonnet`), or leave it out for sonnet", WHO)
    if a.permission_mode is not None and a.permission_mode not in PERMISSION_MODES:
        return launch._refuse("--permission-mode %r is not accepted: %s (forge adds no mode of its own); `--permission-mode default` is the usual one" % (
            a.permission_mode, ", ".join(PERMISSION_MODES)), WHO)
    if a.timeout < 1:
        return launch._refuse("--timeout is %d: a number of seconds, 1 or more (`--timeout %d` is the default)" % (a.timeout, TIMEOUT), WHO)
    if a.cwd is not None:
        if not os.path.isdir(a.cwd):
            return launch._refuse("--cwd %s is not a folder: name one that exists (`--cwd .` is the current folder)" % a.cwd, WHO)
        try:
            os.chdir(a.cwd)  # the project is this folder's, and the child runs in it
        except OSError as e:
            return launch._refuse("cannot enter --cwd %s: %s; look at it with `ls -ld %s`" % (a.cwd, e.strerror or e, shlex.quote(a.cwd)), WHO)
    found = launch._target(WHO, a.name)
    if isinstance(found, int):
        return found
    project, prof, profile = found
    if not profile:
        return launch._refuse("name a profile: forge run @NAME \"PROMPT\" (`forge list @` lists them)", WHO)
    try:
        flags, settings, mcp_file, _, settings_path, mcp_path = launch._flags(project, prof, profile)
    except profiles.ProfileError as e:
        return launch._refuse(str(e) + profiles.doctor_hint(project), WHO)
    sid = str(uuid.uuid4())
    env = dict(launch.session_env(profile, project, sid), FORGE_RUN_DEPTH=str(depth + 1))
    claude = shutil.which("claude", path=env.get("PATH", os.defpath))
    if not claude:
        print(profiles.claude_missing(WHO), file=sys.stderr)
        return 127
    model = a.model or "sonnet"
    argv = flags + ["--session-id", sid, "--model", model]
    if a.permission_mode is not None:
        argv += ["--permission-mode", a.permission_mode]
    argv += ["--output-format", "json", "-p"]
    record = profiles.session_record(profile, project, os.getpid(), parent=os.environ.get("CLAUDE_CODE_SESSION_ID"), print_mode=True)
    try:
        launch._write_files(settings, mcp_file, settings_path, mcp_path)
        profiles.write_session(sid, record)
    except OSError as e:
        return launch._refuse("cannot write the session's files under %s: %s%s" % (lib.STATE, e.strerror or e, profiles.state_hint()), WHO)
    with tempfile.TemporaryFile() as fin, tempfile.TemporaryFile() as fout:  # files, not pipes: nothing to deadlock on, however long
        fin.write(prompt)
        fin.seek(0)
        began, late = time.monotonic(), []

        def watch():
            if time.monotonic() - began > a.timeout:
                late.append(True)
                return True
            return False
        try:
            code = launch._run(claude, argv, env, watch=watch, headless=True, stdin=fin, stdout=fout)
        except OSError as e:  # claude passed `which` and still cannot start (a missing interpreter): the record says a session that never was
            os.remove(profiles.session_path(sid))
            print("! forge run: cannot start %s: %s" % (claude, e.strerror or e), file=sys.stderr)
            return 127
        if not late and time.monotonic() - began > a.timeout:  # the child ended between two looks of the watch, after the deadline
            late.append(True)
        if not late:
            fout.seek(0)
            text = fout.read().decode("utf-8", "replace")
    if late:
        print("! forge run: profile %s session %s ran past --timeout %d seconds and was ended" % (profile, sid, a.timeout), file=sys.stderr)
        return TIMED_OUT
    doc = _result(text)
    cost = (doc or {}).get("total_cost_usd", (doc or {}).get("cost_usd"))
    print("profile %s session %s cost %s USD" % (profile, (doc or {}).get("session_id") or sid,
                                                 "%.4f" % cost if isinstance(cost, (int, float)) else "unknown"), file=sys.stderr)
    problem = None  # what makes this run no success, whatever the exit code of the child was
    if doc is None:
        problem = "claude's output is not a result document (%d bytes)" % len(text)
    elif doc.get("is_error"):
        problem = "the session ended with an error (%s)%s" % (doc.get("subtype") or "no subtype", ": " + doc["result"] if isinstance(doc.get("result"), str) and doc["result"] else "")
    elif not isinstance(doc.get("result"), str):
        problem = "the result document has no `result` text (%s)" % (doc.get("subtype") or "no subtype")
    elif code:
        problem = "claude exited %d%s" % (code, ": " + doc["result"] if doc["result"] else "")
    if problem:
        print("! forge run: " + problem, file=sys.stderr)
        code = code or 1
    if a.json and doc is not None:  # output that is no result document is not passed on as if it were one
        sys.stdout.write(text)
    elif not problem:
        answer = doc["result"]
        print(answer)
    return code
