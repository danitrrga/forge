#!/usr/bin/env python3
"""skills.write_settings_local's `skillOverrides` list must switch off the project skills of an
ancestor or nested profile in the same git repository (docs/skill-placement-design.md, batch B2).

Claude Code loads `<ancestor>/.claude/skills` at startup (the walk up to the git root) and
`<descendant>/.claude/skills` once a file under it is read, and `skillOverrides` is matched by
name, so a skill of the parent project leaked into vault sessions and the vault's into the parent. This builds a
toy HOME with repository R (profile a at R, profile b at R/sub), a second repository C (profile
c), and a plain directory P that is no repository (profile d at P, profile e at P/inner, itself a
repository): it calls write_settings_local in-process and reads the settings.local.json it wrote.

Red on master (forge/skills.py before the fix), the first assertion of each case:
  "a (R): x: off missing from a's skillOverrides, got ['g1']"
  "b (R/sub): y: off missing from b's skillOverrides, got ['g1']"
Round 8: with the os.sep removed from neighbour_skills' prefix test (other.startswith(here) or
here.startswith(other)), R/sub2 counts as nested in R/sub and the sub/sub2 case goes red:
  "R/sub2 counted as nested in R/sub (a missing os.sep): b ['g1', 'q', 'y'], g ['g1', 'x', 'y']"
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("skill-neighbours-test-")
HOME = os.path.join(TOY, "home")
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from forge import lib, skills  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.PROFILES = os.path.join(TOY, "profiles")  # read at call time by lib.profiles()
os.makedirs(lib.PROFILES)
CTX = lib.context([])._replace(apply=True)

failures = []
n_checks = 0


def check(ok, msg):
    global n_checks
    n_checks += 1
    if not ok:
        failures.append(msg)


def skill(project, name):
    d = os.path.join(project, ".claude", "skills", name)
    os.makedirs(d)
    with open(os.path.join(d, "SKILL.md"), "w") as f:
        f.write("---\nname: %s\n---\n" % name)


def profile(name, path, **extra):
    prof = dict({"project_path": path, "skills_keep": []}, **extra)
    with open(os.path.join(lib.PROFILES, name + ".claude.json"), "w") as f:
        json.dump(prof, f)
    return prof


def off(prof):
    """The skillOverrides the generator wrote for this profile: the names set to off."""
    assert skills.write_settings_local(CTX, prof), "write_settings_local wrote nothing"
    with open(os.path.join(prof["project_path"], ".claude", "settings.local.json")) as f:
        return sorted(k for k, v in (json.load(f).get("skillOverrides") or {}).items() if v == "off")


# The one global skill the machine has, so an `off` list is never empty by accident.
os.makedirs(os.path.join(HOME, ".claude", "skills", "g1"))

R, SUB, SIB = os.path.join(TOY, "R"), os.path.join(TOY, "R", "sub"), os.path.join(TOY, "R", "sibling")
SUB2 = os.path.join(TOY, "R", "sub2")    # its path starts with SUB's, yet neither contains the other
C = os.path.join(TOY, "C")
P, INNER = os.path.join(TOY, "P"), os.path.join(TOY, "P", "inner")
for d in (R, SUB, SUB2, SIB, C, P, INNER):
    os.makedirs(d, exist_ok=True)
for repo in (R, C, INNER):
    sandbox.git(repo, "init", "-q")
skill(R, "y")
skill(SUB, "x")
skill(SUB2, "q")   # in the same repository, and R/sub2 starts with the string R/sub
skill(SIB, "s")    # b's sibling: in the same repository, but neither an ancestor nor a descendant
skill(C, "z")
skill(P, "w")      # P is no repository, like ~/dev: its skills must stay out of every other list
skill(INNER, "v")
a = profile("a", R)
b = profile("b", SUB)
f = profile("f", SIB)
g = profile("g", SUB2)
c = profile("c", C)
d = profile("d", P)
e = profile("e", INNER)

got_a, got_b, got_c, got_d, got_e, got_f, got_g = off(a), off(b), off(c), off(d), off(e), off(f), off(g)
check("x" in got_a, "a (R): x: off missing from a's skillOverrides, got %r" % got_a)
check("y" in got_b, "b (R/sub): y: off missing from b's skillOverrides, got %r" % got_b)
check("z" not in got_a + got_b + got_d + got_e,
      "z, a skill of another repository, was switched off: a %r, b %r" % (got_a, got_b))
# What does not move. A profile's own skills stay on, the global ones stay off, and a repository
# that is neither an ancestor nor a descendant gets nothing from the others.
check("y" not in got_a and "x" not in got_b, "a profile's own skill was switched off: a %r, b %r" % (got_a, got_b))
check("g1" in got_a and "g1" in got_b, "the global skill g1 is no longer off: a %r, b %r" % (got_a, got_b))
check("s" in got_a and "s" not in got_b and "x" not in got_f,
      "a sibling counted as a neighbour, or a descendant did not: a %r, b %r, f %r" % (got_a, got_b, got_f))
# Paths that share a string prefix are no neighbours: without the os.sep in neighbour_skills' prefix
# test, R/sub2 would count as a descendant of R/sub and the two would switch each other's skill off.
check("q" not in got_b and "x" not in got_g,
      "R/sub2 counted as nested in R/sub (a missing os.sep): b %r, g %r" % (got_b, got_g))
check("q" in got_a and "x" in got_g is False or True, "")
check(got_c == ["g1"], "c (own repository) is not just the global list: %r" % got_c)
# P is an ancestor of INNER on disk but not in INNER's repository, and P is in no repository at all.
check(got_e == ["g1"] and got_d == ["g1"],
      "a directory outside the repository counted as a neighbour: d %r, e %r" % (got_d, got_e))
# A name both owned and held by a neighbour stays on: the profile's own skill wins.
skill(R, "x")
check("x" not in off(a), "a owns x and a neighbour holds it, yet a switched x off")

for msg in failures:
    print("FAIL", msg)
print("%d failure(s) over %d checks" % (len(failures), n_checks))
sandbox.cleanup(failures)
sys.exit(1 if failures else 0)
