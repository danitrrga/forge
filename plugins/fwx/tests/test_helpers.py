"""tests/helpers.py: a toy repo is built in its own folder whatever GIT_* the caller exports, and
add_worktree gives a worktree of that repo.

Control seen red (a copy of helpers.py whose git() passes os.environ as it is, GIT_DIR and GIT_INDEX_FILE
included, so the toy repo's commit lands in the other repo):
  FAIL: toy_repo with GIT_DIR set: the other repo's history is unchanged: got '2', want '1'
  FAIL: toy_repo with GIT_DIR set: the toy repo has its own commit: got '2', want '1'
  FAIL: toy_repo is on master: got 'git rev-parse --abbrev-ref HEAD failed (128): fatal: not a git repository ...'
  FAIL: add_worktree makes a worktree: git worktree add -q -b side ... failed (128): fatal: not a git repository ...
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()

other = helpers.toy_repo()


def query(repo, *args):
    """git's answer, or the error text: a broken helper must end as a FAIL line, not a traceback."""
    try:
        return helpers.git(repo, *args).strip()
    except RuntimeError as e:
        return str(e)


def count(repo):
    return query(repo, "rev-list", "--count", "HEAD")


s.eq("the other repo starts with one commit", count(other), "1")

saved = {k: os.environ.get(k) for k in ("GIT_DIR", "GIT_INDEX_FILE")}
os.environ["GIT_DIR"] = os.path.join(other, ".git")
os.environ["GIT_INDEX_FILE"] = os.path.join(other, ".git", "index")
try:
    toy = helpers.toy_repo({"a.txt": "a\n"})
    after_other = count(other)
    after_toy = count(toy)
finally:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
s.eq("toy_repo with GIT_DIR set: the other repo's history is unchanged", after_other, "1")
s.eq("toy_repo with GIT_DIR set: the toy repo has its own commit", after_toy, "1")
s.ok("toy_repo with GIT_DIR set: the files are in the toy folder", os.path.isfile(os.path.join(toy, "a.txt")))
s.eq("toy_repo is on master", query(toy, "rev-parse", "--abbrev-ref", "HEAD"), "master")

env = helpers.clean_env(EXTRA="1")
s.ok("clean_env drops GIT_* and keeps the rest", not any(k.startswith("GIT_") and k not in helpers.GIT_ENV for k in env)
     and env.get("EXTRA") == "1" and env.get("PATH") == os.environ.get("PATH"))

try:
    wt = helpers.add_worktree(toy, "side")
except RuntimeError as e:
    s.ok("add_worktree makes a worktree", False, str(e).splitlines()[0])
    s.done()
common = query(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
s.eq("add_worktree: the worktree shares the repo's git dir", os.path.realpath(common),
     os.path.realpath(os.path.join(toy, ".git")))
s.ok("add_worktree: the worktree has the files", os.path.isfile(os.path.join(wt, "a.txt")))
s.eq("add_worktree: it is on its own branch", query(wt, "rev-parse", "--abbrev-ref", "HEAD"), "side")

s.done()
