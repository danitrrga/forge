#!/usr/bin/env python3
"""Which of the two long suites of .github/workflows/checks.yml a pull request needs, from the paths it changes.

`fwx` (`forge test fwx`, about 8 minutes) and `suite` (`forge test`, about 12) are most of a CI run. Each runs only when a
changed path can change what it checks. `engine` (lint, the fresh install and the tests that read the documentation) and
every job of ci.yml run always. Four rules keep a skipped suite from hiding a break:

1. Only a pull request is ever narrowed: a push to the default branch, a manual run or any other event selects both suites.
2. Skipping a suite is an allowlist, never a guess. A path that matches no row of SKIP or ROWS is unknown and selects BOTH,
   so a new folder costs minutes and never a missed check.
3. Nothing to look at (no changed path) or a diff git cannot compute selects both: a real pull request never has an empty list.
4. A path the CI itself is made of (.github/, githooks/ci-local) selects both, so a change to the rules is checked by all of it.

Usage (what the `changes` job runs):
    select_suites.py --event E --base SHA --head SHA [--github-output FILE]
It prints one line per changed path, then `fwx=true|false` and `suite=true|false`, and appends the last two to FILE (GITHUB_OUTPUT).
`--paths-from-stdin` takes the paths from stdin instead of git (tests/test_select_suites.py drives it that way).
"""
import argparse
import fnmatch
import subprocess
import sys

# SKIP: files no test reads for their content except the ones DOC_READERS runs, and that run no code. Checked by
# grepping every tests/, hooks/ and scripts/ file for each name, and by running both suites with the copy of the tree
# the suite is allowed to see (see the PR body). AGENTS.md is a link to CLAUDE.md.
SKIP = ("README.md", "CLAUDE.md", "AGENTS.md", "docs/assets/*")

# The tests that read those documents (README.md and CLAUDE.md by content, every tracked file for an old registry name).
# checks.yml runs them in the job that always runs; tests/test_select_suites.py checks the two lists agree.
DOC_READERS = ("tests/test_readme.py", "tests/test_registry_names.py", "tests/test_measure_login.py")

# ROWS: (pattern, fwx, suite, why). First match wins; `*` crosses `/` (fnmatch).
# What the fwx suite reads outside plugins/fwx: nothing but the runner (a copy of plugins/fwx alone passes every file):
#   bin/forge, forge/cli.py, forge/lib.py, forge/testgroup.py, forge/tmpscope.py   the runner (`forge test fwx`), its group runner and temp-dir scope
# The forge/publish.py and publish/engine.gitignore rows are what the fwx suite read before it stopped running `bin/forge lint`
# (the rows stay: one that over-selects costs CI minutes only).
ROWS = (
    (".github/*", True, True, "CI itself"),
    ("githooks/ci-local", True, True, "CI itself"),
    ("bin/forge", True, True, "read by the fwx suite"),
    ("forge/cli.py", True, True, "read by the fwx suite"),
    ("forge/lib.py", True, True, "read by the fwx suite"),
    ("forge/testgroup.py", True, True, "read by the fwx suite"),
    ("forge/tmpscope.py", True, True, "read by the fwx suite"),
    ("forge/publish.py", True, True, "read by the fwx suite"),
    ("publish/engine.gitignore", True, True, "read by the fwx suite"),
    # The engine suite reads one folder of the plugin: README.md shows plugins/fwx/docs/workflow-tree.svg, which tests/test_publish.py pins by
    # hash and tests/test_readme.py looks for (a copy of the tree without plugins/fwx fails exactly those two, measured). Every other test
    # builds a toy plugin (tests/test_test_group.py).
    ("plugins/fwx/docs/*", True, True, "an image of the README, pinned by the engine suite"),
    ("plugins/fwx/*", True, False, "the fwx plugin"),
    ("forge/*", False, True, "engine code the fwx suite does not read"),
    ("tests/*", False, True, "engine tests"),
    ("hooks/*", False, True, "engine hooks"),
    ("scripts/*", False, True, "engine scripts"),
    ("githooks/*", False, True, "engine git hooks"),
    ("examples/*", False, True, "engine examples"),
    ("benchmarks/*", False, True, "engine benchmarks"),
    ("skills/*", False, True, "engine skills"),
    ("config/*", False, True, "engine config"),
)


def classify_path(path):
    """(fwx, suite, why) for one changed path."""
    for pattern in SKIP:
        if fnmatch.fnmatchcase(path, pattern):
            return False, False, "documentation no suite reads"
    for pattern, fwx, suite, why in ROWS:
        if fnmatch.fnmatchcase(path, pattern):
            return fwx, suite, why
    return True, True, "unknown path"


def classify(event, paths):
    """(fwx, suite, lines): which suites run, and a line saying why for each path (or for the event)."""
    if event != "pull_request":
        return True, True, ["event %s: both suites" % event]
    if not paths:
        return True, True, ["no changed path to look at: both suites"]
    fwx = suite = False
    lines = []
    for p in paths:
        f, s, why = classify_path(p)
        fwx, suite = fwx or f, suite or s
        lines.append("%s -> fwx=%s suite=%s (%s)" % (p, str(f).lower(), str(s).lower(), why))
    return fwx, suite, lines


def changed_paths(base, head):
    """The paths the pull request changes since the merge base (three dots), or None when git cannot say."""
    # --no-renames: git names a rename by its destination alone, so a file moved out of plugins/fwx/ would not select fwx.
    r = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", "%s...%s" % (base, head)], capture_output=True, text=True)
    if r.returncode:
        print("git diff %s...%s failed (exit %d): %s" % (base, head, r.returncode, r.stderr.strip()), file=sys.stderr)
        return None
    return [p for p in r.stdout.split("\0") if p]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--event", required=True)
    ap.add_argument("--base")
    ap.add_argument("--head")
    ap.add_argument("--github-output")
    ap.add_argument("--paths-from-stdin", action="store_true")
    a = ap.parse_args(argv)
    if a.event != "pull_request":
        paths = []
    elif a.paths_from_stdin:
        paths = [l for l in sys.stdin.read().split("\n") if l]
    elif a.base and a.head:
        paths = changed_paths(a.base, a.head)
    else:
        print("a pull_request needs --base and --head", file=sys.stderr)
        paths = None
    if paths is None:
        fwx, suite, lines = True, True, ["the changed paths could not be listed: both suites"]
    else:
        fwx, suite, lines = classify(a.event, paths)
    for l in lines:
        print(l)
    out = "fwx=%s\nsuite=%s\n" % (str(fwx).lower(), str(suite).lower())
    print(out, end="")
    if a.github_output:
        with open(a.github_output, "a", encoding="utf-8") as fh:
            fh.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
