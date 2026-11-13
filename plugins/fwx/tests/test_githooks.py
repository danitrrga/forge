"""githooks/pre-commit, commit-msg and pre-push: each calls forge's personal-data guard with this
repo's root and its own mode, passes forge's refusal on, and refuses itself when forge is not found.

forge is a fake here: a script that records its argv0 and arguments in $FAKE_LOG and exits with $FAKE_RC.
A hook that finds no forge must be run with a PATH that holds no forge (rule: only the fake directory
on PATH), so PATH is a directory of links to the few programs the hooks use.

Controls seen red, each on a copy of one hook changed in one place (39 checks each):
  - a hook whose "forge not found" branch ends `exit 0` instead of `exit 1` (the plan's control, for each of the three):
      FAIL: pre-commit: no FORGE_ROOT, no forge on PATH: exit code: got 0, want 1
      FAIL: pre-commit: FORGE_ROOT without bin/forge: exit code: got 0, want 1
  - a pre-commit that calls forge without --root:
      FAIL: pre-commit: forge gets the repo root and the mode: got [['check-public', '--staged']], want [['check-public', '--root', ...
  - a commit-msg or pre-push that swallows forge's exit 1:
      FAIL: commit-msg: forge says 1: the hook exits 1: got 0, want 1
      FAIL: pre-push: forge says 1: the hook exits 1: got 0, want 1
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()
HOOKS = ("pre-commit", "commit-msg", "pre-push")
MESSAGE = "%s: refused: forge not found; set FORGE_ROOT to the forge checkout or put its bin/forge on PATH"
FAKE = '#!/bin/sh\n{ echo "$0"; for a in "$@"; do echo "$a"; done; } >> "$FAKE_LOG"\nexit "${FAKE_RC:-0}"\n'
A, Z = "a" * 40, "0" * 40

work = helpers.mkdtemp("fwx-hooks-")
for tool in ("git", "tr", "sed"):
    found = shutil.which(tool)
    if not found:
        s.not_run("%s is not installed" % tool)
tools = os.path.join(work, "tools")  # PATH without forge
with_forge = os.path.join(work, "with-forge")  # the same, plus a fake forge
for d in (tools, with_forge):
    os.makedirs(d)
    for tool in ("git", "tr", "sed"):
        os.symlink(shutil.which(tool), os.path.join(d, tool))
path_forge = helpers.write(with_forge, "forge", FAKE, 0o755)
forge_root = os.path.join(work, "checkout")
root_forge = helpers.write(forge_root, "bin/forge", FAKE, 0o755)
empty_root = os.path.join(work, "no-forge-here")
os.makedirs(empty_root)
repo = helpers.toy_repo()
msgfile = helpers.write(work, "msg.txt", "a message\n")


def run(hook, path, forge_root=None, rc=0):
    log = os.path.join(work, "log")
    if os.path.exists(log):
        os.remove(log)
    env = dict(helpers.GIT_ENV, PATH=path, LANG="C", FAKE_LOG=log, FAKE_RC=str(rc))
    if forge_root:
        env["FORGE_ROOT"] = forge_root
    args = [msgfile] if hook == "commit-msg" else []
    stdin = "refs/heads/m %s refs/heads/m %s\nrefs/heads/n %s refs/heads/n %s\n" % (A, "b" * 40, A, Z) \
        if hook == "pre-push" else ""
    r = subprocess.run([os.path.join(helpers.ROOT, "githooks", hook)] + args, cwd=repo, env=env,
                       input=stdin, capture_output=True, text=True)
    calls = []
    if os.path.exists(log):
        lines = open(log).read().splitlines()
        marks = [i for i, l in enumerate(lines) if l.endswith("/forge")]
        calls = [lines[i:j] for i, j in zip(marks, marks[1:] + [len(lines)])]
    return r, calls


def expected(hook):
    """The arguments forge gets from each hook, one list per call."""
    base = ["lint", "--root", repo]
    return {"pre-commit": [base + ["--staged"]], "commit-msg": [base + ["--message", msgfile]],
            "pre-push": [base + ["--range", "b" * 40 + ".." + A], base + ["--range", Z + ".." + A]]}[hook]


for hook in HOOKS:
    s.ok("%s: is executable" % hook, os.access(os.path.join(helpers.ROOT, "githooks", hook), os.X_OK))
    r, calls = run(hook, tools, forge_root=forge_root)
    s.eq("%s: FORGE_ROOT, forge says 0: exit code" % hook, r.returncode, 0)
    s.eq("%s: it runs $FORGE_ROOT/bin/forge" % hook, {c[0] for c in calls}, {root_forge})
    s.eq("%s: forge gets the repo root and the mode" % hook, [c[1:] for c in calls], expected(hook))

    r, calls = run(hook, tools, forge_root=forge_root, rc=1)
    s.eq("%s: forge says 1: the hook exits 1" % hook, r.returncode, 1)
    s.ok("%s: forge says 1: the hook says it refused" % hook, "%s: refused" % hook in r.stderr, r.stderr)

    r, calls = run(hook, with_forge)
    s.eq("%s: no FORGE_ROOT, forge on PATH: exit code" % hook, r.returncode, 0)
    s.eq("%s: no FORGE_ROOT, forge on PATH: that forge runs" % hook, {c[0] for c in calls}, {path_forge})

    r, calls = run(hook, with_forge, forge_root=forge_root)
    s.eq("%s: FORGE_ROOT wins over PATH" % hook, {c[0] for c in calls}, {root_forge})

    r, calls = run(hook, tools)
    s.eq("%s: no FORGE_ROOT, no forge on PATH: exit code" % hook, r.returncode, 1)
    s.eq("%s: no FORGE_ROOT, no forge on PATH: message" % hook, r.stderr.strip(), MESSAGE % hook)

    r, calls = run(hook, with_forge, forge_root=empty_root)
    s.eq("%s: FORGE_ROOT without bin/forge: exit code" % hook, r.returncode, 1)
    s.eq("%s: FORGE_ROOT without bin/forge: message, and no fallback to PATH" % hook,
         (r.stderr.strip(), calls), (MESSAGE % hook, []))

s.done()
