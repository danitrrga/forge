"""Run every tests/test_*.py of the working folder and summarise: PASS, FAIL, or NOT RUN, NOT ARMED.

The repo's checks recipe. Each test is a plain script that runs itself, prints its FAIL lines and
exits 1 on any; one that cannot run (a tool, a key or the network is missing) prints
`NOT RUN, NOT ARMED: <reason>` as its last line and exits 77.

Exit 0 when every file passed. Exit 1 when one failed, or when there was no test file at all
(looking at zero is a failure). Exit 77 when none failed but one did not run: neither green nor red,
because a CI job that skips its tests would otherwise end green. Whoever wants 0 lets them run.

`--expect-not-run PATH[,PATH...]` (repeatable, also `--expect-not-run=PATH`) declares tests that cannot run
where this is called from (CI has no key, no private tree). A declared test that exits 77 prints
`EXPECTED NOT RUN: PATH: reason` and no longer turns the exit to 77; an undeclared 77 still does. A declared test that
runs counts as any other, so a failing one is still 1. The declaration widens nothing else: a run in which no
test passed is 1 (everything declared away proves nothing), and so is a declared path that is no test file (a typo
would silently un-declare it). Why a flag and not a list file: the reason sits beside the command in the workflow,
and there is no second file to forget. Exit 2 on a usage error.
"""
import os
import subprocess
import sys

NOT_RUN = "NOT RUN, NOT ARMED"
EXPECTED = "EXPECTED NOT RUN"
USAGE = "usage: fwx test [--expect-not-run PATH[,PATH...]]\n"


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


def declared(argv):
    """The set of declared paths, or None on a usage error."""
    out = set()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--expect-not-run":
            i += 1
            if i >= len(argv):
                return None
            value = argv[i]
        elif a.startswith("--expect-not-run="):
            value = a.split("=", 1)[1]
        else:
            return None
        names = [n.strip() for n in value.split(",")]
        if not all(names):
            return None
        out.update(names)
        i += 1
    return out


def main(argv):
    expect = declared(argv)
    if expect is None:
        sys.stderr.write(USAGE)
        return 2
    env = clean_env()
    # The folder it is run from, not the repository's top level: this plugin is a folder of a bigger repository
    # (forge's plugins/fwx), and the top level's tests are not its own. `git ls-files` run there lists only that folder.
    root = os.getcwd()
    if subprocess.run(["git", "-C", root, "rev-parse", "--git-dir"], env=env, capture_output=True).returncode:
        sys.stderr.write("fwx test: not inside a git repository\n")
        return 1
    passed = failed = not_run = expected = 0
    files = test_files(root, env)
    unknown = sorted(expect - set(files))
    for rel in unknown:
        sys.stderr.write("fwx test: --expect-not-run names %s, which is no tests/test_*.py file\n" % rel)
    for rel in files:
        r = subprocess.run([sys.executable, rel], cwd=root, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if r.returncode == 0:
            passed += 1
            print("PASS  " + rel)
        elif r.returncode == 77 and rel in expect:
            expected += 1
            print("%s: %s: %s" % (EXPECTED, rel, reason(r.stdout)))
        elif r.returncode == 77:
            not_run += 1
            print("%s: %s: %s" % (NOT_RUN, rel, reason(r.stdout)))
        else:
            failed += 1
            print("FAIL  %s (exit %d)" % (rel, r.returncode))
            for line in r.stdout.splitlines():
                print("    " + line)
    total = passed + failed + not_run + expected
    print("%d test file(s): %d passed, %d failed, %d not run%s"
          % (total, passed, failed, not_run, ", %d expected not run" % expected if expected else ""))
    if failed or total == 0 or unknown or (expect and passed == 0):
        return 1
    return 77 if not_run else 0
