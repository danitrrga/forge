#!/usr/bin/env python3
"""forge doctor row `project roots`: a project that lives inside another profile's git repository and has skills of its
own is a FAIL. Why: forge switches an enclosing project's neighbours' skills off in its settings (skills.neighbour_skills),
Claude Code applies those settings inside the nested directory too, and an inner "on" does not override an outer "off"
(tested with claude -p on a toy tree: parent off + child on, in settings.local.json and in settings.json, the
child's skill stayed hidden). A vault nested inside another project's repository lost six of its skills that way. The standard is one
git repository per project: `git init` in the nested directory, ignored by the outer repository.

Toy projects under /tmp with real `git init`s. The row is the function cli.nested_project_roots(only, profs).
Controls: with the nested-without-own-skills case turned into a FAIL, or the own-repository case into a FAIL, the matching
case below fails; an outer repository that no profile owns is not a problem (nothing hides the inner skills); reading zero
projects is a FAIL, never a PASS.
Seen failing before the row existed: "AttributeError: module 'forge.cli' has no attribute 'nested_project_roots'"."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import sandbox  # noqa: E402
from forge import cli  # noqa: E402

failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def mk(path, skill=None, repo=False):
    os.makedirs(path, exist_ok=True)
    if repo:
        subprocess.run(["git", "init", "-q", path], check=True)
    if skill:
        d = os.path.join(path, ".claude", "skills", skill)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as fh:
            fh.write("---\nname: %s\ndescription: x\n---\n" % skill)


def main():
    tmp = sandbox.mkdtemp("nested-roots-")
    outer = os.path.join(tmp, "outer")
    mk(outer, skill="o1", repo=True)
    nested = os.path.join(outer, "inner")
    mk(nested, skill="teach")                       # inside outer's repository, own skill
    own = os.path.join(tmp, "own-outer")
    mk(own, repo=True)
    mk(os.path.join(own, "inner"), skill="teach", repo=True)   # its own repository
    plain = os.path.join(tmp, "plain-outer")
    mk(plain, repo=True)
    mk(os.path.join(plain, "inner"))                # nested, no skills of its own
    orphan = os.path.join(tmp, "orphan")
    mk(orphan, repo=True)
    mk(os.path.join(orphan, "inner"), skill="teach")  # nested in a repo no profile owns

    far = os.path.join(tmp, "far-outer")            # an ancestor profile by path, but a repository of its own in between
    mk(far, repo=True)
    mk(os.path.join(far, "mid"), repo=True)
    mk(os.path.join(far, "mid", "inner"), skill="teach")

    def row(profs, only=None):
        r = cli.nested_project_roots(only, profs)
        return r.level, r.detail

    p = {"outer": {"project_path": outer}, "inner": {"project_path": nested}}
    st, det = row(p)
    want("nested with own skills in a profile's repository: FAIL naming both", (st, "inner" in det and "outer" in det), ("FAIL", True))
    want("the row is registered with a fix that names git init",
         [f for n, _, f in cli.CHECKS if n == "project roots"] != [] and "git init" in [f for n, _, f in cli.CHECKS if n == "project roots"][0], True)
    st, det = row({"outer": {"project_path": own}, "inner": {"project_path": os.path.join(own, "inner")}})
    want("inner with its own repository: PASS", st, "PASS")
    st, det = row({"outer": {"project_path": plain}, "inner": {"project_path": os.path.join(plain, "inner")}})
    want("nested without skills of its own: PASS", st, "PASS")
    want("an ancestor profile in a different repository does not hide it: PASS",
         row({"outer": {"project_path": far}, "inner": {"project_path": os.path.join(far, "mid", "inner")}})[0], "PASS")
    st, det = row({"inner": {"project_path": os.path.join(orphan, "inner")}})
    want("nested in a repository no profile owns: PASS", st, "PASS")
    want("frozen profile is not read (only one left, none read: FAIL, never a silent PASS)",
         row({"inner": {"project_path": nested, "frozen": True}})[0], "FAIL")
    want("only= scopes to one project", row(p, only="outer")[0], "PASS")
    want("only= on the nested one reports it", row(p, only="inner")[0], "FAIL")
    want("no projects at all: FAIL", row({})[0], "FAIL")
    want("a profile whose directory is gone is named, not a crash", row({"gone": {"project_path": os.path.join(tmp, "nope")}, **p})[0], "FAIL")

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
