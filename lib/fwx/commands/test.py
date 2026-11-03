"""Run every tests/test_*.py of the repo and summarise: PASS, FAIL, or NOT RUN, NOT ARMED.

The repo's checks recipe. Each test is a plain script that runs itself, prints its FAIL lines and
exits 1 on any; one that cannot run (a tool, a key or the network is missing) prints
`NOT RUN, NOT ARMED: <reason>` as its last line and exits 77.

Exit 0 when every file passed. Exit 1 when one failed, or when there was no test file at all
(looking at zero is a failure). Exit 77 when none failed but one did not run: neither green nor red,
because a CI job that skips its tests would otherwise end green. Whoever wants 0 lets them run.
"""
import os
import subprocess
import sys

NOT_RUN = "NOT RUN, NOT ARMED"


def clean_env():
    """The environment without GIT_*: inside a git hook GIT_DIR and GIT_INDEX_FILE point at the
    repo being committed, and a test that builds its own repos must not reach it."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def test_files(root, env):
    """tests/test_*.py that git tracks or would add: a new test counts before its first commit."""
    out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         env=env, capture_output=True, text=True, check=True).stdout
    return sorted(f for f in out.split("\0")
                  if os.path.dirname(f) == "tests" and os.path.basename(f).startswith("test_") and f.endswith(".py"))


def reason(output):
    """What a test says after `NOT RUN, NOT ARMED:` on its last line."""
    lines = [l for l in output.strip().splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    return last.split(NOT_RUN + ":", 1)[1].strip() if (NOT_RUN + ":") in last else "no reason printed"


def main(argv):
    env = clean_env()
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], env=env, capture_output=True, text=True)
    if top.returncode:
        sys.stderr.write("fwx test: not inside a git repository\n")
        return 1
    root = top.stdout.strip()
    passed = failed = not_run = 0
    for rel in test_files(root, env):
        r = subprocess.run([sys.executable, rel], cwd=root, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if r.returncode == 0:
            passed += 1
            print("PASS  " + rel)
        elif r.returncode == 77:
            not_run += 1
            print("%s: %s: %s" % (NOT_RUN, rel, reason(r.stdout)))
        else:
            failed += 1
            print("FAIL  %s (exit %d)" % (rel, r.returncode))
            for line in r.stdout.splitlines():
                print("    " + line)
    total = passed + failed + not_run
    print("%d test file(s): %d passed, %d failed, %d not run" % (total, passed, failed, not_run))
    if failed or total == 0:
        return 1
    return 77 if not_run else 0
