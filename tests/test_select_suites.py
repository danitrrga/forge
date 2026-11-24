#!/usr/bin/env python3
"""Which long suites a pull request runs (.github/scripts/select_suites.py, called by the `changes` job of
.github/workflows/checks.yml): the path rules, the fail-safe cases, the git diff it runs, and that the documentation
readers it counts on run in the job that always runs.

`check(classify)` returns every case a classifier gets wrong. `main` runs it on the real `classify` (must find nothing)
and on naive variants (each must be caught, naming its case): that is the negative control. Seen failing:
  everything answers "neither suite":  FAIL a change in the fwx plugin's lib selects fwx: fwx=False suite=False, want fwx=True suite=False
                                       FAIL a change in forge/new.py selects the engine suite only: fwx=False suite=False, want fwx=False suite=True
  everything answers "both":           FAIL README.md alone selects neither: fwx=True suite=True, want fwx=False suite=False
  an unlisted path is skipped:         FAIL a path nobody listed (a new top-level folder): fwx=False suite=False, want fwx=True suite=True
  a push is narrowed like a PR:        FAIL a push to the default branch selects both, even for a README: fwx=False suite=False, want fwx=True suite=True
The command line, the git diff and checks.yml have the same kind of control: `check_cli_git` and `check_workflow` run on the real
script and file (must find nothing) and on copies with one thing broken, each caught naming its case:
  the diff without --no-renames:       FAIL git: a file renamed from plugins/fwx/ to forge/ selects fwx: got 'fwx=false\\nsuite=true\\n', want 'fwx=true\\nsuite=true\\n'
  the diff with two dots:              FAIL git: a base that moved on is not counted as the branch's change (three dots): got 'fwx=false\\nsuite=true\\n', want ...
  no output file written:              FAIL cli: README.md alone: output file: got '', want 'fwx=false\\nsuite=false\\n'
  a reader step removed from `engine`, or moved into `suite`:
                                       FAIL the `engine` job does not run the documentation reader(s) ['tests/test_readme.py']
Seen failing first, before the script existed: "FileNotFoundError ... select_suites.py"; before --no-renames was added, the rename case alone."""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "select_suites.py")
CHECKS = os.path.join(ROOT, ".github", "workflows", "checks.yml")


def load():
    spec = importlib.util.spec_from_file_location("select_suites", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# (label, event, paths, fwx, suite)
CASES = [
    ("a change in the fwx plugin's lib selects fwx", "pull_request", ["plugins/fwx/lib/fwx/state.py"], True, False),
    ("a document of the fwx plugin selects fwx: it is a skill or a playbook, read by its tests", "pull_request",
     ["plugins/fwx/playbooks/principles.md"], True, False),
    ("the README's image under plugins/fwx/docs, pinned by the engine suite, selects both", "pull_request",
     ["plugins/fwx/docs/workflow-tree.svg"], True, True),
    ("bin/forge, which the fwx suite starts, selects both", "pull_request", ["bin/forge"], True, True),
    ("forge/publish.py, whose lint the fwx suite runs on its own tree, selects both", "pull_request", ["forge/publish.py"], True, True),
    ("forge/testgroup.py, the fwx runner, selects both", "pull_request", ["forge/testgroup.py"], True, True),
    ("README.md alone selects neither", "pull_request", ["README.md"], False, False),
    ("CLAUDE.md alone selects neither", "pull_request", ["CLAUDE.md"], False, False),
    ("a README image selects neither", "pull_request", ["docs/assets/banner.png"], False, False),
    ("README.md and an image select neither", "pull_request", ["README.md", "docs/assets/fig-sync.png"], False, False),
    ("a change in forge/new.py selects the engine suite only", "pull_request", ["forge/new.py"], False, True),
    ("a test selects the engine suite only", "pull_request", ["tests/test_new.py"], False, True),
    ("README.md with an engine file selects the engine suite", "pull_request", ["README.md", "forge/new.py"], False, True),
    ("README.md with an fwx file selects fwx only", "pull_request", ["README.md", "plugins/fwx/lib/fwx/state.py"], True, False),
    ("an engine file and an fwx file select both", "pull_request", ["forge/new.py", "plugins/fwx/lib/fwx/state.py"], True, True),
    ("the workflow itself selects both", "pull_request", [".github/workflows/checks.yml"], True, True),
    ("this script selects both", "pull_request", [".github/scripts/select_suites.py"], True, True),
    ("githooks/ci-local selects both", "pull_request", ["githooks/ci-local"], True, True),
    ("a path nobody listed (a new top-level folder)", "pull_request", ["newthing/x.py"], True, True),
    ("an unlisted document selects both: only README.md, CLAUDE.md and the images are listed", "pull_request", ["docs/guide.md"], True, True),
    ("LICENSE is not listed", "pull_request", ["LICENSE"], True, True),
    ("one unknown path among documents selects both", "pull_request", ["README.md", "weird.cfg"], True, True),
    ("a README of the fwx plugin is the plugin's, not the root one", "pull_request", ["plugins/fwx/README.md"], True, False),
    ("a push to the default branch selects both, even for a README", "push", ["README.md"], True, True),
    ("a manual run selects both", "workflow_dispatch", ["README.md"], True, True),
    ("a pull request with no changed path selects both", "pull_request", [], True, True),
]


def check(classify):
    out = []
    for label, event, paths, want_fwx, want_suite in CASES:
        fwx, suite, lines = classify(event, paths)
        if (fwx, suite) != (want_fwx, want_suite):
            out.append("%s: fwx=%s suite=%s, want fwx=%s suite=%s" % (label, fwx, suite, want_fwx, want_suite))
        if not lines:
            out.append("%s: no line saying why" % label)
    return out


def naive_none(event, paths):
    return False, False, ["none"]


def naive_both(event, paths):
    return True, True, ["both"]


def naive_unknown_skips(event, paths):
    """The real rules, but a path nobody listed selects neither."""
    real = load().classify
    if event == "pull_request" and paths and all(p.startswith("newthing/") for p in paths):
        return False, False, ["unknown"]
    return real(event, paths)


def naive_push_narrowed(event, paths):
    return load().classify("pull_request", paths)


def run_cli(args, stdin=None, cwd=None, script=SCRIPT):
    out = tempfile.NamedTemporaryFile("w+", suffix=".out", delete=False)
    out.close()
    try:
        r = subprocess.run([sys.executable, script] + args + ["--github-output", out.name], input=stdin, capture_output=True, text=True, cwd=cwd)
        with open(out.name, encoding="utf-8") as fh:
            return r, fh.read()
    finally:
        os.unlink(out.name)


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@example.com"] + list(args),
                          capture_output=True, text=True, check=True).stdout.strip()




def check_cli_git(script):
    """Every case the command line and the git diff behind it get wrong, as a list of strings; `script` is the file to run."""
    out = []

    def want(label, got, expected):
        if got != expected:
            out.append("%s: got %r, want %r" % (label, got, expected))

    r, outfile = run_cli(["--event", "pull_request", "--paths-from-stdin"], stdin="README.md\n", script=script)
    want("cli: README.md alone: output file", outfile, "fwx=false\nsuite=false\n")
    want("cli: README.md alone: exit code", r.returncode, 0)
    want("cli: README.md alone: it says why", "README.md -> fwx=false suite=false (documentation no suite reads)" in r.stdout, True)
    r, outfile = run_cli(["--event", "pull_request", "--paths-from-stdin"], stdin="forge/new.py\n", script=script)
    want("cli: forge/new.py: output file", outfile, "fwx=false\nsuite=true\n")
    r, outfile = run_cli(["--event", "push"], stdin="", script=script)
    want("cli: a push: output file", outfile, "fwx=true\nsuite=true\n")
    r, outfile = run_cli(["--event", "pull_request"], script=script)
    want("cli: a pull request with no base and no head selects both and exits 0", (outfile, r.returncode), ("fwx=true\nsuite=true\n", 0))

    # git: the three-dot diff of a toy repository, a base git does not know, and a file moved out of the plugin.
    with tempfile.TemporaryDirectory() as d:
        git(d, "init", "-q", "-b", "master")
        for rel, text in (("README.md", "a\n"), ("forge/new.py", "a\n"),
                          ("plugins/fwx/lib/fwx/state.py", "".join("line %d of the plugin's state module\n" % i for i in range(30)))):
            os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
            with open(os.path.join(d, rel), "w") as fh:
                fh.write(text)
        git(d, "add", "-A")
        git(d, "commit", "-qm", "base")
        base = git(d, "rev-parse", "HEAD")
        git(d, "checkout", "-qb", "pr")
        with open(os.path.join(d, "README.md"), "w") as fh:
            fh.write("b\n")
        git(d, "commit", "-qam", "docs")
        docs_head = git(d, "rev-parse", "HEAD")
        r, outfile = run_cli(["--event", "pull_request", "--base", base, "--head", docs_head], cwd=d, script=script)
        want("git: a README-only branch selects neither", outfile, "fwx=false\nsuite=false\n")
        git(d, "checkout", "-q", "master")
        with open(os.path.join(d, "forge", "new.py"), "w") as fh:
            fh.write("moved on\n")
        git(d, "commit", "-qam", "master moves on")
        moved = git(d, "rev-parse", "HEAD")
        r, outfile = run_cli(["--event", "pull_request", "--base", moved, "--head", docs_head], cwd=d, script=script)
        want("git: a base that moved on is not counted as the branch's change (three dots)", outfile, "fwx=false\nsuite=false\n")
        r, outfile = run_cli(["--event", "pull_request", "--base", "0" * 40, "--head", docs_head], cwd=d, script=script)
        want("git: a base git does not know selects both", outfile, "fwx=true\nsuite=true\n")
        want("git: a base git does not know says so", "could not be listed" in r.stdout, True)
        r, outfile = run_cli(["--event", "pull_request", "--base", base, "--head", base], cwd=d, script=script)
        want("git: nothing changed selects both", outfile, "fwx=true\nsuite=true\n")
        # git names a rename by its destination alone unless told not to: a file moved out of the plugin must still select fwx.
        git(d, "checkout", "-q", "-b", "moved-out", base)
        git(d, "mv", "plugins/fwx/lib/fwx/state.py", "forge/state.py")
        git(d, "commit", "-qm", "move a file out of the plugin")
        r, outfile = run_cli(["--event", "pull_request", "--base", base, "--head", git(d, "rev-parse", "HEAD")], cwd=d, script=script)
        want("git: a file renamed from plugins/fwx/ to forge/ selects fwx", outfile, "fwx=true\nsuite=true\n")
    return out


def readers_of_engine_job(checks):
    """The DOC_READERS that the `engine` job of a checks.yml text runs, as a set of paths: a step of another job does not count."""
    m = re.search(r"^  engine:\n(.*?)(?=^  [A-Za-z_-]+:\n|\Z)", checks, re.S | re.M)
    body = m.group(1) if m else ""
    return {t for t in load().DOC_READERS if "run: python3 %s\n" % t in body}


def check_workflow(checks):
    """Every way a checks.yml text skips a suite or leaves a documentation reader out when it should not, as a list of strings."""
    out = []
    missing = set(load().DOC_READERS) - readers_of_engine_job(checks)
    if missing:
        out.append("the `engine` job does not run the documentation reader(s) %s" % sorted(missing))
    for name in ("fwx", "suite"):
        if "needs.changes.outputs.%s != 'false'" % name not in checks:
            out.append("the %s job is not skipped only on `false`" % name)
    if "== 'true'" in checks:
        out.append("a job runs only on `true`: an empty output would skip it")
    return out


def mutate(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)


def main():
    failures, looked = [], [0]

    def want(label, got, expected):
        looked[0] += 1
        if got != expected:
            failures.append("%s: got %r, want %r" % (label, got, expected))

    def control(name, caught, must_name):
        """A broken variant must be caught by a case naming `must_name`, or the cases that look at the real one prove nothing."""
        looked[0] += 1
        if not any(must_name in c for c in caught):
            failures.append("control %s: not caught by a case naming %r (caught: %s)" % (name, must_name, caught))

    mod = load()
    for f in check(mod.classify):
        failures.append("real classifier, " + f)
    looked[0] += len(CASES)
    for name, variant, must_name in (("everything skipped", naive_none, "forge/new.py"),
                                     ("everything selected (never narrows)", naive_both, "README.md alone"),
                                     ("an unknown path skipped", naive_unknown_skips, "a path nobody listed"),
                                     ("a push narrowed like a pull request", naive_push_narrowed, "a push to the default branch")):
        control(name, check(variant), must_name)

    # The command line and the git diff, on the real script; then the same cases on copies of it with one thing broken.
    for f in check_cli_git(SCRIPT):
        failures.append("real script, " + f)
    looked[0] += 14
    with open(SCRIPT, encoding="utf-8") as fh:
        script_text = fh.read()
    with tempfile.TemporaryDirectory() as td:
        broken = os.path.join(td, "broken_select_suites.py")
        for name, old, new, must_name in (
                ("the diff without --no-renames", '"--no-renames", ', "", "renamed from plugins/fwx/"),
                ("the diff with two dots", '"%s...%s" % (base, head)', '"%s..%s" % (base, head)', "base that moved on"),
                ("an unknown base skipped", 'True, True, ["the changed paths could not be listed: both suites"]',
                 'False, False, ["the changed paths could not be listed: both suites"]', "base git does not know selects both"),
                ("no output file written", "fh.write(out)", "pass", "output file"),
                ("an empty diff skipped", 'return True, True, ["no changed path to look at: both suites"]',
                 'return False, False, ["no changed path to look at: both suites"]', "nothing changed selects both")):
            with open(broken, "w", encoding="utf-8") as fh:
                fh.write(mutate(script_text, old, new))
            control(name, check_cli_git(broken), must_name)

    # The workflow: the documentation readers run in the job that always runs, and a suite is skipped only on `false`.
    with open(CHECKS, encoding="utf-8") as fh:
        checks = fh.read()
    for f in check_workflow(checks):
        failures.append("checks.yml, " + f)
    looked[0] += 3
    for t in mod.DOC_READERS:
        want("doc reader %s exists" % t, os.path.isfile(os.path.join(ROOT, t)), True)
    step = "      - name: documentation reader, README and CLAUDE.md claims\n        if: ${{ !cancelled() }}\n        run: python3 tests/test_readme.py\n"
    removed = mutate(checks, step, "")
    suite_job = "      - run: python3 bin/forge test --jobs 4"
    moved = mutate(removed, suite_job, step + suite_job)
    want("the moved copy holds the step in the suite job", "run: python3 tests/test_readme.py" in moved.split("\n  suite:\n")[1], True)
    control("a reader step removed from the engine job", check_workflow(removed), "tests/test_readme.py")
    control("a reader step moved into the suite job", check_workflow(moved), "tests/test_readme.py")
    control("fwx skipped unless `true`", check_workflow(mutate(checks, "needs.changes.outputs.fwx != 'false'", "needs.changes.outputs.fwx == 'true'")),
            "fwx job")
    control("suite skipped unless `true`", check_workflow(mutate(checks, "needs.changes.outputs.suite != 'false'", "needs.changes.outputs.suite == 'true'")),
            "suite job")

    # The paths the fwx suite reads outside the plugin, that are in this tree, exist (a rename must move the row with it).
    for pattern, _, _, why in mod.ROWS:
        if why == "read by the fwx suite" and not pattern.startswith("publish/"):
            want("row %s names a file" % pattern, os.path.isfile(os.path.join(ROOT, pattern)), True)
    # Every skipped path is a file or folder of this tree, so a rename cannot leave a row that skips nothing.
    for pattern in mod.SKIP:
        base = pattern.rstrip("*").rstrip("/")
        want("skip row %s names something" % pattern, os.path.exists(os.path.join(ROOT, base)), True)
    # Looking at zero is a failure.
    want("the checks above looked at something", looked[0] > 30, True)

    for f in failures:
        print("FAIL " + f)
    print("%d check(s), %d failure(s)" % (looked[0], len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
