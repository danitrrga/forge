#!/usr/bin/env python3
"""lib/fwx/layout.py: the naming rule of a `.fwx/` folder and the check that reports a path outside it.

A toy `.fwx/` holds a closed phase (with a subphase that has no stage row of its own), an open phase (with an open subphase), a
subproject and a factory job. Each bad path is reported as `<path>: <reason>; belongs in <where>`; each good one passes; the
count of paths looked at is returned, and a run over zero paths fails.

Seen red with `check` accepting every path (a stub returning no problem), the five bad paths each print:
  FAIL: bad path 'Notes.md' is reported: got [], want a line naming it
  (likewise 'milestones/v2/phases/02-open/state.md', 'milestones/v2/phases/02-open/02.1-sub/state.md', 'research/Chart.PNG'
  and 'milestones/v2/phases/01-x/notes.md')
Controls on the finished module, each seen red in one edit:
  - a subphase read only by its own stage (the closed phase's stage ignored):
      FAIL: good path 'milestones/v2/phases/01-x/01.1-sub/state.md' passes: got ['milestones/v2/phases/01-x/01.1-sub/state.md: state.md is kept only in a closed or cancelled phase; belongs in the phase, once it is closed or cancelled']
  - the factory key not exempt from the lower-case rule:
      FAIL: good path 'factory/K-1/plan.md' passes: got ['factory/K-1/plan.md: upper-case letter or space in a name; belongs in factory/k-1/plan.md']
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

LIB = os.path.join(helpers.ROOT, "lib")
sys.path.insert(0, LIB)
from fwx import layout  # noqa: E402

s = helpers.Suite()

root = helpers.mkdtemp("fwx-layout-")


def touch(rel, text=""):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def stage_row(phase, stage):
    touch("milestones/v2/phases/%s/audit.tsv" % phase,
          "date\tkind\tsha\tdetail\trc\nt0\tstage\tabc\t%s why\t\n" % stage)


# 01-x is closed; its subphase 01.1-sub has no stage row of its own (closing.md writes `closed` on the phase folder only).
# 02-open is open; its subphase 02.1-sub is open.
stage_row("01-x", "closed")
touch("milestones/v2/phases/01-x/01.1-sub/plan.md")
stage_row("02-open", "plan")
touch("milestones/v2/phases/02-open/02.1-sub/plan.md")

GOOD = [
    "project.md", "adr.tsv", "tree.excalidraw", "milestones/v2/milestone.md",
    "research/chart.png", "milestones/v2/phases/01-x/demo/3/index.html",
    "durable/x.md", "subprojects/a/project.md", "subprojects/a/milestones/v1/milestone.md",
    "factory/K-1/plan.md", "subprojects/a/factory/K-1/plan.md",
    "milestones/v2/phases/01-x/context.md", "milestones/v2/phases/01-x/decisions.tsv",
    "milestones/v2/phases/01-x/state.md", "milestones/v2/phases/01-x/report-1.md",
    "milestones/v2/phases/01-x/research/notes.md",
    "milestones/v2/phases/01-x/01.1-sub/state.md", "milestones/v2/phases/01-x/01.1-sub/report-2.md",
    "milestones/v2/phases/02-open/plan.md", "milestones/v2/phases/02-open/02.1-sub/postmortem.md",
]
BAD = {
    "Notes.md": "research/notes.md",
    "milestones/v2/phases/02-open/state.md": "closed or cancelled",
    "milestones/v2/phases/02-open/02.1-sub/state.md": "closed or cancelled",
    "research/Chart.PNG": "research/chart.png",
    "milestones/v2/phases/01-x/notes.md": "research",
    "research/subprojects/a/factory/UPPER.md": "research/subprojects/a/factory/upper.md",   # only `factory/<KEY>` at a scope root is exempt
    "factory/K 1/plan.md": "factory/K-1/plan.md",                                           # a space is refused in a key too
    "research": "research/research",                                                        # a bare file named like a folder
    "durable": "research/durable",
    "milestones/v2/phases/01-x/demo": "research/demo",
    "milestones/v2/phases/01-x/research": "research/research",
}

for p in GOOD:
    lines, looked = layout.check(root, [p])
    s.ok("good path %r passes" % p, lines == [], "got %r" % (lines,))
    s.eq("good path %r is counted" % p, looked, 1)
for p, where in BAD.items():
    lines, looked = layout.check(root, [p])
    s.ok("bad path %r is reported" % p, len(lines) == 1 and lines[0].startswith(p + ": ") and "; belongs in " in lines[0],
         "got %r, want a line naming it" % (lines,))
    s.ok("bad path %r says where it belongs" % p, lines != [] and where in lines[0].split("; belongs in ", 1)[-1],
         "got %r, want %r after 'belongs in'" % (lines, where))
    s.eq("bad path %r is counted" % p, looked, 1)

lines, looked = layout.check(root, GOOD + list(BAD))
s.eq("one call over all paths: one line per bad path", sorted(l.split(": ", 1)[0] for l in lines), sorted(BAD))
s.eq("one call over all paths: the count", looked, len(GOOD) + len(BAD))

# an absolute path under the root is the same path
lines, _ = layout.check(root, [os.path.join(root, "Notes.md")])
s.ok("an absolute path is read against the root", len(lines) == 1 and lines[0].startswith("Notes.md: "), "got %r" % (lines,))

# the root's own spelling: a path outside the root is refused, not silently passed
try:
    layout.check(root, ["../elsewhere.md"])
    s.ok("a path outside the root raises", False, "returned")
except ValueError:
    s.ok("a path outside the root raises", True)

# the module run: over every file under a root; says how many it looked at; zero is a failure
env = helpers.clean_env(PYTHONPATH=LIB)


def run_main(r):
    p = subprocess.run([sys.executable, "-m", "fwx.layout", r], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout


touch("Notes.md")
rc, out = run_main(root)
files = sum(len(fs) for _, _, fs in os.walk(root))
s.eq("module run over a root holding a bad file exits 1", rc, 1)
s.ok("module run prints the bad file's line", "Notes.md: " in out, "got %r" % out)
s.ok("module run says how many paths it looked at", ("%d paths looked at" % files) in out, "got %r" % out)

clean = helpers.mkdtemp("fwx-layout-clean-")
with open(os.path.join(clean, "project.md"), "w", encoding="utf-8") as f:
    f.write("x")
rc, out = run_main(clean)
s.eq("module run over a clean root exits 0", rc, 0)
s.ok("module run over a clean root counts 1 path", "1 paths looked at" in out, "got %r" % out)

empty = helpers.mkdtemp("fwx-layout-empty-")
rc, out = run_main(empty)
s.eq("module run over an empty root exits 1", rc, 1)
s.ok("module run over an empty root says it looked at none", "0 paths looked at" in out, "got %r" % out)

s.done()
