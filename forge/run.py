"""forge run @NAME "PROMPT" [--model M] [--cwd DIR] [--permission-mode MODE] [--json]: one headless session of this project with
session profile NAME, and its final answer on stdout. It is how an agent launches another with a specialised profile: a `claude -p`
started from a session's Bash tool does not inherit that session's profile (measured, 4.3 U0), so the profile is given here.

The child is `claude -p` with the flags `forge start @NAME` gives an interactive session (launch._flags: the same function, so the two
cannot drift), a `--session-id` of ours, `--output-format json` and `--model`, which is always passed: `sonnet` when the caller gave
none (no agent without an explicit model). No permission flag is added: a headless session cannot ask, so it has what the profile's
`--settings` allows and nothing wider, unless the caller names `--permission-mode`. The prompt reaches claude on its stdin, from a
file: never as an argument (a prompt that starts with `-` is not a flag and a long one cannot overflow the command line) and never
through a shell.

stdout carries only the final answer (with --json, claude's whole output), stderr one line `profile P session ID cost USD`, and the
exit code is claude's, except that a child that exits 0 with `is_error` or with output that is no result document is exit 1: an error
of the child is never a success. The session record (profiles.session_record) names the parent session when CLAUDE_CODE_SESSION_ID is
set, and says the session was started with -p, so `forge switch` refuses it. The reasons for a refusal (exit 2) are `forge start`'s."""
import json
import os
import shutil
import sys
import tempfile
import uuid

from forge import launch, lib, profiles

WHO = "forge run"


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
    if not a.prompt.strip():
        return launch._refuse('the prompt is empty: forge run @NAME "PROMPT"', WHO)
    if a.cwd is not None:
        if not os.path.isdir(a.cwd):
            return launch._refuse("--cwd %s is not a folder" % a.cwd, WHO)
        os.chdir(a.cwd)  # the project is this folder's, and the child runs in it
    found = launch._target(WHO, a.name)
    if isinstance(found, int):
        return found
    project, prof, profile = found
    if not profile:
        return launch._refuse("name a profile: forge run @NAME \"PROMPT\" (`forge list @` lists them)", WHO)
    try:
        flags, settings, mcp_file, _, settings_path, mcp_path = launch._flags(project, prof, profile)
    except profiles.ProfileError as e:
        return launch._refuse(str(e), WHO)
    sid = str(uuid.uuid4())
    env = launch.session_env(profile, project, sid)
    claude = shutil.which("claude", path=env.get("PATH", os.defpath))
    if not claude:
        print("! forge run: claude is not on PATH", file=sys.stderr)
        return 127
    model = a.model or "sonnet"
    argv = flags + ["--session-id", sid, "--model", model]
    if a.permission_mode:
        argv += ["--permission-mode", a.permission_mode]
    argv += ["--output-format", "json", "-p"]
    record = profiles.session_record(profile, project, os.getpid(), parent=os.environ.get("CLAUDE_CODE_SESSION_ID"), print_mode=True)
    try:
        launch._write_files(settings, mcp_file, settings_path, mcp_path)
        profiles.write_session(sid, record)
    except OSError as e:
        return launch._refuse("cannot write the session's files under %s: %s" % (lib.STATE, e.strerror or e), WHO)
    with tempfile.TemporaryFile() as fin, tempfile.TemporaryFile() as fout:  # files, not pipes: nothing to deadlock on, however long
        fin.write(a.prompt.encode("utf-8"))
        fin.seek(0)
        code = launch._run(claude, argv, env, stdin=fin, stdout=fout)
        fout.seek(0)
        text = fout.read().decode("utf-8", "replace")
    doc = _result(text)
    cost = (doc or {}).get("total_cost_usd", (doc or {}).get("cost_usd"))
    print("profile %s session %s cost %s USD" % (profile, (doc or {}).get("session_id") or sid,
                                                 "%.4f" % cost if isinstance(cost, (int, float)) else "unknown"), file=sys.stderr)
    problem = None  # what makes this run no success, whatever the exit code of the child was
    if doc is None:
        problem = "claude's output is not a result document (%d bytes)" % len(text)
    elif doc.get("is_error"):
        problem = "the session ended with an error (%s)%s" % (doc.get("subtype") or "no subtype", ": " + doc["result"] if doc.get("result") else "")
    elif not isinstance(doc.get("result"), str):
        problem = "the result document has no `result` text"
    elif code:
        problem = "claude exited %d%s" % (code, ": " + doc["result"] if doc["result"] else "")
    if problem:
        print("! forge run: " + problem, file=sys.stderr)
        code = code or 1
    if a.json:
        sys.stdout.write(text)
    elif not problem:
        answer = doc["result"]
        print(answer)
    return code
