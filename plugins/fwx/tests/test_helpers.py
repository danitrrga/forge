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

# FirstFail, the Suite of a control run: the case stops at the first FAIL the control is waiting for, and at nothing else.
# Seen red on the base helpers.py (no FirstFail yet): AttributeError: module 'helpers' has no attribute 'FirstFail'
# Controls, each on a copy of helpers.py changed in one place:
#   raising at every FAIL (`if self.want(self.fails[-1]):` -> `if True:`):  FAIL: FirstFail: a FAIL the control is not waiting for does not stop the case: got ['one', 'two'], want ['one', 'two', 'three']
#   never raising (the `raise Found()` line removed):  FAIL: FirstFail: the case stops at the FAIL it waits for: got ['one', 'two', 'three'], want ['one', 'two']
#   Found an Exception, so the case's own `except Exception` swallows it:  FAIL: FirstFail: a case's `except Exception` does not swallow the stop: got ['one', 'two', 'swallowed'], want ['one', 'two']
def case(S, trail, swallow=False):
    try:
        trail.append("one")
        S.ok("one", True)
        trail.append("two")
        S.ok("two", False, "wanted")
        trail.append("three")
        S.ok("three", False, "not wanted")
    except Exception:  # a case that catches its own errors must not catch the stop
        if not swallow:
            raise
        trail.append("swallowed")


f = helpers.FirstFail(lambda line: "two" in line)
trail = []
seen = f.run(case, f, trail)
s.eq("FirstFail: the case stops at the FAIL it waits for", trail, ["one", "two"])
s.ok("FirstFail: run says the FAIL was seen, and `fails` holds it last", seen is True and f.fails == ["FAIL: two: wanted"], repr(f.fails))
s.eq("FirstFail: what ran is counted", f.checks, 2)
f = helpers.FirstFail(lambda line: "nothing like this" in line)
trail = []
seen = f.run(case, f, trail)
s.eq("FirstFail: a FAIL the control is not waiting for does not stop the case", trail, ["one", "two", "three"])
s.ok("FirstFail: run says the FAIL was not seen, `fails` has both", seen is False and len(f.fails) == 2, repr(f.fails))
f = helpers.FirstFail(lambda line: "two" in line)
trail = []
f.run(case, f, trail, True)
s.eq("FirstFail: a case's `except Exception` does not swallow the stop", trail, ["one", "two"])
f = helpers.FirstFail(lambda line: True)
trail = []
s.ok("FirstFail: a case with no FAIL runs to its end and is not seen", f.run(lambda: f.ok("fine", True)) is False and f.fails == [])

# free_port: two test files running at once must never be handed the same port, nor a port the kernel hands to an outgoing
# connection or to a `bind(0)` of its own. The naive version (bind to port 0, read the number, close) lets either happen in the
# window between the close and the caller's own bind. Seen red on that naive version:
#   FAIL: free_port: 300 calls, 300 different ports: got 299, want 300
#   FAIL: free_port: below the ephemeral range, where the kernel gives nobody a port: got 60499, want below 32768
#   FAIL: free_port: a port one process holds is never handed to another: got [46793, 48935, 51221, 52913], want []
# Control, on a copy of helpers.py with the claim removed (`claim.bind(...)` replaced by `pass`, the range kept), red 3 runs in 3:
#   FAIL: free_port: 300 calls, 300 different ports: got 297, want 300
#   FAIL: free_port: a port one process holds is never handed to another: got [13410, 27189, 28208, 31146], want []
import subprocess
import socket
mine = [helpers.free_port() for _ in range(300)]
s.eq("free_port: 300 calls, 300 different ports", len(set(mine)), 300)
s.ok("free_port: below the ephemeral range, where the kernel gives nobody a port", max(mine) < 32768, "got %d, want below 32768" % max(mine))
child = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import helpers; print(' '.join(str(helpers.free_port()) for _ in range(300)))"
                        % os.path.dirname(os.path.realpath(__file__))], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       env=helpers.clean_env(), timeout=120)
theirs = set(int(x) for x in child.stdout.split())
s.eq("free_port: another process got its own 300", len(theirs), 300)
s.eq("free_port: a port one process holds is never handed to another", sorted(set(mine) & theirs), [])
probe = socket.socket()
try:
    probe.bind(("127.0.0.1", mine[0]))
    bound = True
except OSError:
    bound = False
finally:
    probe.close()
s.ok("free_port: the caller can bind what it was given", bound)

s.done()
