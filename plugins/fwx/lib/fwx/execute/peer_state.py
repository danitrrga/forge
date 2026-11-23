"""The state file of a running `fwx peer-review` (`<out>.state`) and what may be done to what it names.

The file says where the review's throwaway worktree is, so the command can go on with it and `fwx wave remove` can clear it after an
aborted run. A file is only data: before anything it names is deleted, `check` shows that the folder is one that `fwx peer-review`
itself made (a `fwx-peer-*` folder directly in the temp folder, its worktree `wt` inside), so a hand-edited or foreign file removes
nothing. Imports the standard library only (execute.cleanup and commands.peer both use it).
"""
import json
import os
import shutil
import subprocess
import tempfile

PREFIX = "fwx-peer-"
FIELDS = ("top", "work", "wt", "result", "base", "head")


def read(path):
    """The state a file holds, as it is (None for an empty file); ValueError when it is no JSON object."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        return None
    st = json.loads(text)
    if not isinstance(st, dict):
        raise ValueError("not a JSON object")
    return st


def check(st):
    """None when `st` can be trusted, else what is wrong, naming the field."""
    if not isinstance(st, dict):
        return "it is not a JSON object"
    for k in FIELDS:
        if not isinstance(st.get(k), str) or not st[k]:
            return "field `%s` is missing or not a path or sha" % k
    if st.get("session") is not None and not isinstance(st["session"], str):
        return "field `session` is not a string"
    if not isinstance(st.get("started"), (int, float)) or isinstance(st.get("started"), bool):
        return "field `started` is missing or not a number"
    work = os.path.realpath(st["work"])
    if not os.path.basename(work).startswith(PREFIX) or os.path.dirname(work) != os.path.realpath(tempfile.gettempdir()):
        return "field `work` is not a %s* folder of the temp folder, so nothing it names is touched" % PREFIX
    if os.path.realpath(st["wt"]) != os.path.join(work, "wt") or not os.path.realpath(st["result"]).startswith(os.path.join(work, "wt") + os.sep):
        return "fields `wt` and `result` are not inside `work`, so nothing it names is touched"
    return None


def drop(st, state_path, top=None):
    """The worktree, its folder and the state file of a review that has ended or was given up; `st` has passed `check`. Nothing here may
    fail the caller. `top` is the repository to ask (default the state's)."""
    top = top or st["top"]
    for args in (("worktree", "remove", "--force", st["wt"]), ("worktree", "prune")):
        try:
            subprocess.run(["git", "-C", top] + list(args), capture_output=True, stdin=subprocess.DEVNULL)
        except OSError:
            pass
    shutil.rmtree(st["work"], ignore_errors=True)
    try:
        os.remove(state_path)
    except OSError:
        pass
