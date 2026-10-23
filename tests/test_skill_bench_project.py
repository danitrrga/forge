#!/usr/bin/env python3
"""skill_bench.py project tasks: a task captured from a project's own history. It is not a repo/ copy; it names a base
commit in the git repository that holds the bench (<project>/.bench), a list of setup commands, and a list of checks, each a
shell command whose exit status is the verdict ("before": "fail" for a fail-to-pass check, "pass" for a pass-to-pass one).
The ideal answer is the merged diff. alt and naive are optional (a real task has the merged diff and maybe one rejected
attempt). `validate` proves: the base commit exists; at base each check gives its "before" verdict and at least one fails;
the ideal diff makes every check pass; the naive diff, when there is one, fails at least one; setup succeeds; verdicts are the
same on three runs; there is at least one check. The agent's working tree is a `git archive` of the base commit in a fresh
repository: no history, so the merged fix cannot be read from `git log`.

A toy project (a git repo under /tmp with a base commit and a fix commit) holds the clean bench; each case below breaks one
thing and must exit 1 naming it. Seen failing before project tasks existed: "task.json lacks ..." / "repo is missing" for the
clean bench, and "materialize" absent for the history case."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "scripts", "bench"))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

SCRIPT = os.path.join(sandbox.FORGE, "scripts", "bench", "skill_bench.py")
failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def git(root, *a):
    r = subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t", "-c", "diff.noprefix=false", "-c", "diff.srcPrefix=a/", "-c", "diff.dstPrefix=b/"] + list(a),
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


ADDS = "python3 -c \"import calc; assert calc.add(2, 3) == 5\""
ZERO = "python3 -c \"import calc; assert calc.add(-1, 1) == 0\""
STABLE = "python3 -c \"import calc; assert calc.sub(5, 3) == 2\""


def project(tmp, name="proj"):
    """A git project: base commit (add is broken), fix commit. Returns (root, base sha, fix sha)."""
    r = os.path.join(tmp, name)
    os.makedirs(r)
    subprocess.run(["git", "init", "-q", r], check=True)
    put(os.path.join(r, "calc.py"), "def add(a, b):\n    return a - b\n\ndef sub(a, b):\n    return a - b\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    base = git(r, "rev-parse", "HEAD")
    put(os.path.join(r, "calc.py"), "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    git(r, "commit", "-qam", "fix add")
    return r, base, git(r, "rev-parse", "HEAD")


def task(root, base, fix, tid="proj-add-01", checks=None, setup=None, naive=True, ideal=True, meta=None):
    d = os.path.join(root, ".bench", "tasks", tid)
    m = {"id": tid, "field": "logic", "concept": "logic.boundaries", "difficulty": 2, "prompt": "add() is wrong, fix it.",
         "source": {"kind": "project", "project": "toy", "ref": "git:" + fix}, "message_required": False,
         "base": {"commit": base}, "setup": setup if setup is not None else [],
         "checks": checks if checks is not None else [{"id": "adds", "cmd": ADDS, "before": "fail"},
                                                      {"id": "zero", "cmd": ZERO, "before": "fail"},
                                                      {"id": "sub", "cmd": STABLE, "before": "pass"}]}
    m.update(meta or {})
    put(os.path.join(d, "task.json"), json.dumps(m))
    if ideal:
        put(os.path.join(d, "ideal", "solution.patch"), git(root, "diff", base, fix) + "\n")
    if naive:
        put(os.path.join(d, "naive", "solution.patch"),
            "--- a/calc.py\n+++ b/calc.py\n@@ -1,5 +1,5 @@\n def add(a, b):\n-    return a - b\n+    return 5\n \n def sub(a, b):\n     return a - b\n")
    return d


def run(bench, *flags):
    r = subprocess.run([sys.executable, SCRIPT, "validate", "--bench", bench, "--min-per-concept", "0"] + list(flags),
                       capture_output=True, text=True, timeout=240)
    return r.returncode, r.stdout + r.stderr


def snap(b):
    return {os.path.join(r, f): open(os.path.join(r, f), "rb").read() for r, _, fs in os.walk(b) for f in fs}


def main():
    import skill_bench as sb
    tmp = sandbox.mkdtemp("skillbench-proj-")
    root, base, fix = project(tmp)
    task(root, base, fix)
    bench = os.path.join(root, ".bench")
    before = snap(bench)
    code, out = run(bench)
    want("clean project task: exit 0 and ok line", (code, "proj-add-01: ok" in out), (0, True))
    want("clean bench is left byte-identical", snap(bench), before)

    r = subprocess.run([sys.executable, SCRIPT, "validate", "--bench", bench], capture_output=True, text=True, timeout=240)
    want("project bench with the default coverage rule: no coverage failure (it shares forge's concepts, owns no coverage)",
         (r.returncode, "coverage" in r.stdout.lower()), (0, False))

    # the agent's tree: a snapshot of the base commit, one commit, no trace of the fix
    d, err = sb.fresh(os.path.join(bench, "tasks", "proj-add-01"), None)
    tree = os.path.join(d, "repo")
    want("materialize: no error", err, None)
    want("materialize: the tree is the base state", open(os.path.join(tree, "calc.py")).read().count("a - b"), 2)
    want("materialize: one commit and the fix is not in history",
         (git(tree, "rev-list", "--count", "HEAD"), fix in subprocess.run(["git", "-C", tree, "log", "--all", "--format=%H"], capture_output=True, text=True).stdout), ("1", False))

    # a base commit that already holds an earlier capture (.bench with another task's ideal diff) must not show it to the agent
    rl = os.path.join(tmp, "leaky")
    os.makedirs(rl)
    subprocess.run(["git", "init", "-q", rl], check=True)
    put(os.path.join(rl, "calc.py"), "def add(a, b):\n    return a - b\n")
    put(os.path.join(rl, ".bench", "tasks", "old", "ideal", "solution.patch"), "the earlier answer\n")
    git(rl, "add", "-A")
    git(rl, "commit", "-qm", "base with an earlier capture")
    lbase = git(rl, "rev-parse", "HEAD")
    put(os.path.join(rl, "calc.py"), "def add(a, b):\n    return a + b\n")
    git(rl, "commit", "-qam", "fix")
    task(rl, lbase, git(rl, "rev-parse", "HEAD"), checks=[{"id": "adds", "cmd": ADDS, "before": "fail"}])
    d2, err2 = sb.fresh(os.path.join(rl, ".bench", "tasks", "proj-add-01"), None)
    want("materialize: an earlier capture in the base commit is not in the agent's tree",
         (err2, os.path.exists(os.path.join(d2, "repo", ".bench"))), (None, False))

    cases = [
        ("base commit that does not exist", dict(meta={"base": {"commit": "0" * 40}}), "base"),
        ("a fail-to-pass check that passes at base", dict(checks=[{"id": "adds", "cmd": "true", "before": "fail"}, {"id": "zero", "cmd": ZERO, "before": "fail"}]), "adds"),
        ("a pass-to-pass check that fails at base", dict(checks=[{"id": "adds", "cmd": ADDS, "before": "fail"}, {"id": "sub", "cmd": "false", "before": "pass"}]), "sub"),
        ("no check fails at base", dict(checks=[{"id": "sub", "cmd": STABLE, "before": "pass"}]), "fails at base"),
        ("ideal diff that does not satisfy a check", dict(checks=[{"id": "adds", "cmd": ADDS, "before": "fail"}, {"id": "never", "cmd": "false", "before": "fail"}]), "ideal"),
        ("naive diff that passes every check", dict(naive=False), None),
        ("setup that fails", dict(setup=["exit 3"]), "setup"),
        ("zero checks", dict(checks=[]), "check"),
        ("missing ideal diff", dict(ideal=False), "ideal"),
    ]
    for i, (label, kw, needle) in enumerate(cases):
        r2, b2, f2 = project(tmp, "case%d" % i)
        kw = dict(kw)
        naive_passes = label.startswith("naive diff that passes")
        if naive_passes:
            kw["naive"] = False
        task(r2, b2, f2, **kw)
        if naive_passes:
            put(os.path.join(r2, ".bench", "tasks", "proj-add-01", "naive", "solution.patch"), git(r2, "diff", b2, f2) + "\n")
            needle = "naive"
        if label == "base commit that does not exist":
            kw_meta = None
        code, out = run(os.path.join(r2, ".bench"))
        want("%s: exit 1" % label, code, 1)
        want("%s: names %r" % (label, needle), needle in out.lower(), True)
        want("%s: no traceback" % label, "Traceback" in out, False)

    # a relative --bench path works (it crashed: the oracle path was relative to the task, run from inside the repo copy)
    r = subprocess.run([sys.executable, SCRIPT, "validate", "--bench", ".bench", "--min-per-concept", "0"], cwd=root,
                       capture_output=True, text=True, timeout=240)
    want("relative --bench path: exit 0, no traceback", (r.returncode, "Traceback" in r.stdout + r.stderr), (0, False))

    # a check whose verdict flips between runs is named
    r3, b3, f3 = project(tmp, "flaky")
    flip = "python3 -c \"import os,sys; p='%s'; n=int(open(p).read())+1 if os.path.exists(p) else 1; open(p,'w').write(str(n)); sys.exit(n%%2)\"" % os.path.join(tmp, "flip")
    task(r3, b3, f3, checks=[{"id": "adds", "cmd": ADDS, "before": "fail"}, {"id": "flip", "cmd": flip, "before": "fail"}])
    code, out = run(os.path.join(r3, ".bench"))
    want("flaky check: exit 1 and named", (code, "nondeterministic" in out.lower()), (1, True))

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
