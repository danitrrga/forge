#!/usr/bin/env python3
"""lib/fwx/context_base.py and `fwx context new|seal|check` (2.5 U2): the one writer of the base-context file a hook
hands to every agent, and its check.

Not covered here: the hook that reads the file (U3), the wiring in `new-phase` and `stage` (U4), the audit (U5).

Seen red before the code existed (neither lib/fwx/context_base.py nor commands/context_base.py; the test stops at the import):
  FAIL: cannot import fwx.context_base: cannot import name 'context_base' from 'fwx' (.../lib/fwx/__init__.py)

Controls, each seen red on a copy of the repo with one thing changed (first FAIL lines; 102 checks on the good code):
  - the cap counts bytes:
      FAIL: units of 10 é: got 20, want 10
  - the cap counts code points:
      FAIL: 4600 emoji (4600 code points, 9200 units) are over the cap: exit 1: got 0, want 1
  - `build` has no cap:
      FAIL: a 9500-unit map: exit 1: got 0, want 1
  - `build` writes the file before it refuses:
      FAIL: a refused build leaves the previous file: got '# Base context · b41b620c\nxxxx...
  - the Intent is not cut:
      FAIL: a 5000-character Intent is cut to 1000 + the pointer: ## Goal ...
      FAIL: an emoji Intent is cut by units: at most 1000 units of text, no broken character: 700
  - `## Decided` takes every row:
      FAIL: an agent-assumption row is not in Decided: ## Decided ...
  - 40 long rows are listed one by one:
      FAIL: 40 long decisions become one count line: ## Decided ...
  - a decision is not cut to 160:
      FAIL: a decision over 160 is cut to 160: ['- zzzz...
  - `check` only looks that the file exists (returns before comparing anything; 16 FAIL):
      FAIL: decisions.tsv edited after the build: check exit 1: got 0, want 1
  - `check` does not compare decisions.tsv / context.md / the map / the stage:
      FAIL: decisions.tsv edited after the build: check exit 1: got 0, want 1
      FAIL: context.md edited after the build: stale
      FAIL: the map edited after the build: stale
      FAIL: a stage row after the build: check exit 1: got 0, want 1
  - `check` does not compare the mark with the rest:
      FAIL: a sealed file edited by hand: exit 1 `edited since sealed`
  - `check` does not compare the source:
      FAIL: the source changed after seal: check exit 1: got 0, want 1
  - the map's `fwx <command>` is not looked up:
      FAIL: a map naming `fwx frobnicate`: check exit 1: got 0, want 1
  - the path comes from the git dir of the folder, not the common dir:
      FAIL: build from a linked worktree writes the same path: got '.../.git/worktrees/phase-branch/fwx/context-base/...
  - `check --project` with no open phase exits 0:
      FAIL: check --project with no open phase: exit 77: got 0, want 77
  - `check --hook-command` accepts a silent hook / a hook that answers Explore:
      FAIL: a silent hook: exit 1: got 0, want 1
      FAIL: a hook that answers Explore: exit 1: got 0, want 1
  - `build` rewrites a file that did not change:
      FAIL: a second build says `unchanged`: wrote ...
      FAIL: a second build changes nothing: modification time kept: got ..., want ...

The base file's name does not start with a dot (2.5 U4; seen red on the old `_phase_name`, 104 checks):
  FAIL: the file name does not start with a dot (a hidden file is easy to miss): .fwx__milestones__v1__phases__01-alpha.md
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx import context_base as cb  # noqa: E402
    from fwx import state  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.context_base: %s" % e)
    sys.exit(1)

WROTE = re.compile(r"(wrote|unchanged) (\S+) (\d+) units \(map (\d+), goal (\d+), decided (\d+)\)\Z")
CONTEXT = "# Context: 01-alpha\n\n## Intent\n%s\n\n## What success means\n%s\n\n## Surfaces\nnone\n"
SCRATCH = helpers.mkdtemp("fwx-cb-")


def cli(cwd, *args, **kw):
    return helpers.fwx(cwd, "context", *args, **kw)


def phase(intent="Make the toy work.", success="The toy works.", context=True, repo=None):
    """A toy repo with one phase folder; returns (repo, folder)."""
    repo = repo or helpers.toy_repo()
    d = str(state.new_phase("alpha", cwd=repo))
    if context:
        helpers.write(d, "context.md", CONTEXT % (intent, success))
    return repo, d


def write_map(name, text):
    return helpers.write(SCRATCH, name, text)


def decide(d, text, support="chosen"):
    state.append_decision(os.path.join(d, "decisions.tsv"), decision=text, why="because", support=support)


def base_of(d):
    return cb.base_path(d)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


GOOD_MAP = "fwx is a framework.\nUse `fwx state` and `fwx stage` to move.\n"
good_map = write_map("good-map.md", GOOD_MAP)

# ---- units: UTF-16, not bytes, not code points --------------------------------------------------------------------
s.eq("units of 10 é", cb.units("é" * 10), 10)
s.eq("units of one emoji", cb.units("\U0001F600"), 2)
s.eq("units of ascii", cb.units("abc"), 3)

# ---- build: the file, its parts, its output -----------------------------------------------------------------------
repo, d = phase()
decide(d, "Use a plain TSV for the decisions.")
decide(d, "Ship on Friday.", support="approved")
decide(d, "Maybe cache it.", support="agent-assumption")
decide(d, "Unchecked guess.", support="unexamined")
os.makedirs(os.path.join(d, "research"))
r = cli(repo, "new", d, "--map", good_map)
m = WROTE.match(r.stdout.strip())
s.ok("build prints `wrote <path> <n> units (map <m>, goal <g>, decided <d>)`", r.returncode == 0 and m, repr(r.stdout + r.stderr))
base = base_of(d)
s.ok("the file is the one path() names", bool(m) and m.group(2) == base, "%s vs %s" % (m and m.group(2), base))
text = read(base) if os.path.exists(base) else ""
common = helpers.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
s.eq("the file lives in <git-common-dir>/fwx/context-base/<phase path, its leading dot dropped, / as __>.md", base,
     os.path.join(common, "fwx", "context-base", os.path.relpath(d, repo).lstrip(".").replace(os.sep, "__") + ".md"))
s.ok("the file name does not start with a dot (a hidden file is easy to miss)", not os.path.basename(base).startswith("."),
     os.path.basename(base))
s.ok("the name still tells the folder apart: a sibling phase gets another file", base_of(phase(repo=repo)[1]) != base)
s.ok("it is inside the git dir, so `git status` stays clean", base.startswith(common + os.sep) and not helpers.git(repo, "status", "--porcelain").count("context-base"))
first = text.split("\n", 1)[0]
rest = text.split("\n", 1)[1] if "\n" in text else ""
s.eq("the first line is the mark with the sha8 of the rest", first, "# Base context · " + cb.sha8(rest))
s.ok("the map comes whole, right after the mark", rest.startswith(GOOD_MAP), repr(rest[:80]))
s.ok("## Goal carries Intent and What success means", "## Goal" in text and "Make the toy work." in text and "The toy works." in text)
s.ok("## Files names the existing files as absolute paths",
     all(("- " + p) in text for p in (os.path.join(d, "context.md"), os.path.join(d, "decisions.tsv"), os.path.join(d, "research"),
                                       os.path.join(repo, ".fwx", "PROJECT.md"))), text[text.find("## Files"):text.find("## Decided")])
s.ok("## Files leaves out what does not exist (no demo/, no fwx.json)",
     os.path.join(d, "demo") not in text and "fwx.json" not in text)
dec = text[text.find("## Decided"):] if "## Decided" in text else ""
s.ok("## Decided has the chosen and the approved rows", "- Use a plain TSV for the decisions." in dec and "- Ship on Friday." in dec, dec)
s.ok("an agent-assumption row is not in Decided", "Maybe cache it." not in text, dec)
s.ok("an unexamined row is not in Decided", "Unchecked guess." not in text, dec)
s.ok("no ids in Decided", not re.search(r"\bD\d+\b", dec), dec)
s.ok("## Goal, ## Files and ## Decided come in that order", text.find("## Goal") < text.find("## Files") < text.find("## Decided"))
built = re.search(r"<!-- built stage=(\S+) context=([0-9a-f]{8}) decisions=([0-9a-f]{8}) map=([0-9a-f]{8}) -->\n\Z", text)
s.ok("the last line is the built marker with stage, context, decisions and map", bool(built), repr(text[-120:]))
s.eq("a new phase is built at stage discuss", built and built.group(1), "discuss")
s.eq("units in the output are those of the file", m and int(m.group(3)), cb.units(text))

# a second build changes nothing and does not touch the file
before = os.stat(base).st_mtime_ns
r2 = cli(repo, "new", d, "--map", good_map)
m2 = WROTE.match(r2.stdout.strip())
s.ok("a second build says `unchanged`", bool(m2) and m2.group(1) == "unchanged", r2.stdout)
s.eq("a second build changes nothing: modification time kept", os.stat(base).st_mtime_ns, before)

# ---- the cap: 9000 UTF-16 units; a refusal leaves the previous file ------------------------------------------------
big = write_map("big.md", "x" * 9500)
r = cli(repo, "new", d, "--map", big)
s.eq("a 9500-unit map: exit 1", r.returncode, 1)
s.ok("the refusal names the count, the cap and the fix",
     re.search(r"context-base: \d+ over the cap of 9000: shorten data/context-map\.md or the Intent section", r.stderr), r.stderr)
s.eq("a refused build leaves the previous file", read(base), text)
s.ok("a refused build prints no `wrote`", "wrote" not in r.stdout, r.stdout)
accents = write_map("accents.md", "é" * 6000 + "\n")
r = cli(repo, "new", d, "--map", accents)
s.eq("6000 é (12000 bytes, 6000 units) are under the cap: exit 0", r.returncode, 0)
emoji = write_map("emoji.md", "\U0001F600" * 4600 + "\n")
r = cli(repo, "new", d, "--map", emoji)
s.eq("4600 emoji (4600 code points, 9200 units) are over the cap: exit 1", r.returncode, 1)
warn = write_map("warn.md", "y" * 6500 + "\n")
r = cli(repo, "new", d, "--map", warn)
s.ok("from 6000 units a warning, not a refusal", r.returncode == 0 and "warning" in r.stderr, "%d %r" % (r.returncode, r.stderr))
r = cli(repo, "new", d, "--map", good_map)
s.eq("a small map: no warning", (r.returncode, r.stderr), (0, ""))

# ---- the Intent is cut with a pointer ------------------------------------------------------------------------------
repo5, d5 = phase(intent="i" * 5000)
r = cli(repo5, "new", d5, "--map", good_map)
t5 = read(base_of(d5))
goal = t5[t5.find("## Goal"):t5.find("## Files")]
s.ok("a 5000-character Intent is cut to 1000 + the pointer", goal.count("i") >= 1000 and "i" * 1001 not in goal
     and os.path.join(d5, "context.md") in goal and "i" * 5000 not in goal, goal[:200])
s.eq("a cut Intent builds without complaint", (r.returncode, r.stderr), (0, ""))
repo5b, d5b = phase(intent="\U0001F600" * 700)
cli(repo5b, "new", d5b, "--map", good_map)
t5b = read(base_of(d5b))
g5b = t5b[t5b.find("### Intent"):t5b.find("### What success means")]
s.ok("an emoji Intent is cut by units: at most 1000 units of text, no broken character", g5b.count("\U0001F600") == 500, str(g5b.count("\U0001F600")))

# no context.md: no Goal section, and the file is still built
repo6, d6 = phase(context=False)
os.remove(os.path.join(d6, "context.md"))
r = cli(repo6, "new", d6, "--map", good_map)
t6 = read(base_of(d6))
s.ok("with no context.md the build works and has no ## Goal", r.returncode == 0 and "## Goal" not in t6 and "## Decided" in t6, r.stderr)
r = cli(repo6, "lint", d6, "--map", good_map)
s.eq("no context.md and a base: check passes", r.returncode, 0)
# a job folder of the factory is a folder like any other
job = os.path.join(repo6, ".fwx", "factory", "KEY-1")
helpers.write(job, "context.md", CONTEXT % ("Job intent.", "Job done."))
r = cli(repo6, "new", job, "--map", good_map)
s.ok("a factory job folder builds", r.returncode == 0 and "factory__KEY-1.md" in r.stdout, r.stdout + r.stderr)

# ---- Decided: too many rows become one count line ------------------------------------------------------------------
repo7, d7 = phase()
for i in range(40):
    decide(d7, "Decision number %d: %s" % (i, "w" * 150))
cli(repo7, "new", d7, "--map", good_map)
t7 = read(base_of(d7))
dec7 = t7[t7.find("## Decided"):t7.find("<!-- built")]
s.ok("40 long decisions become one count line", "40" in dec7 and os.path.join(d7, "decisions.tsv") in dec7 and "Decision number 3" not in dec7, dec7)
s.ok("the count line is the only content of Decided", len([l for l in dec7.splitlines() if l.strip() and l != "## Decided"]) == 1, dec7)
repo7b, d7b = phase()
decide(d7b, "z" * 400)
cli(repo7b, "new", d7b, "--map", good_map)
t7b = read(base_of(d7b))
line = [l for l in t7b.splitlines() if l.startswith("- z")]
s.ok("a decision over 160 is cut to 160", len(line) == 1 and len(line[0]) - 2 <= 160 and line[0].count("z") >= 150, repr(line))

# ---- check: current, stale, edited, over the cap, missing ----------------------------------------------------------
CHECKED = re.compile(r"checked 1 file, (\d+) units, sources current\Z")
repo8, d8 = phase()
decide(d8, "Ship it.")
r = cli(repo8, "lint", d8, "--map", good_map)
s.eq("a context.md and no base: check exit 1", r.returncode, 1)
s.ok("the missing base is named", "missing" in r.stderr, r.stderr)
cli(repo8, "new", d8, "--map", good_map)
r = cli(repo8, "lint", d8, "--map", good_map)
s.ok("a fresh base: exit 0 and says how much it looked at", r.returncode == 0 and CHECKED.match(r.stdout.strip()), r.stdout + r.stderr)
s.eq("the units it reports are the file's", int(CHECKED.match(r.stdout.strip()).group(1)), cb.units(read(base_of(d8))))

decide(d8, "Another one.")
r = cli(repo8, "lint", d8, "--map", good_map)
s.eq("decisions.tsv edited after the build: check exit 1", r.returncode, 1)
s.ok("the message names the file", "stale: decisions.tsv changed since the build" in r.stderr, r.stderr)
cli(repo8, "new", d8, "--map", good_map)
helpers.write(d8, "context.md", CONTEXT % ("Another intent.", "Another."))
r = cli(repo8, "lint", d8, "--map", good_map)
s.ok("context.md edited after the build: stale", r.returncode == 1 and "stale: context.md changed since the build" in r.stderr, r.stderr)
cli(repo8, "new", d8, "--map", good_map)
other_map = write_map("other-map.md", GOOD_MAP + "More.\n")
r = cli(repo8, "lint", d8, "--map", other_map)
s.ok("the map edited after the build: stale", r.returncode == 1 and "stale: data/context-map.md changed since the build" in r.stderr, r.stderr)
r = cli(repo8, "lint", d8, "--map", good_map)
s.eq("the map back as it was: current again", r.returncode, 0)
state.append_audit(d8, "stage", detail="premortem", cwd=repo8)
r = cli(repo8, "lint", d8, "--map", good_map)
s.eq("a stage row after the build: check exit 1", r.returncode, 1)
s.ok("the stage message names both stages", "stale: stage is premortem, the base was built at discuss" in r.stderr, r.stderr)
cli(repo8, "new", d8, "--map", good_map)
s.ok("a rebuild takes the new stage", "stage=premortem " in read(base_of(d8)))
r = cli(repo8, "lint", d8, "--map", good_map)
s.eq("after the rebuild: current", r.returncode, 0)

# edited by hand
b8 = base_of(d8)
with open(b8, "a", encoding="utf-8") as f:
    f.write("one more line\n")
r = cli(repo8, "lint", d8, "--map", good_map)
s.ok("a hand edit: check exit 1", r.returncode == 1 and "edited since sealed" in r.stderr, "%d %r" % (r.returncode, r.stderr))
# over the cap: a file written over 9000 with a valid mark
over = "# Base context · %s\n" + "q" * 9100 + "\n"
helpers.write(os.path.dirname(b8), os.path.basename(b8), over % cb.sha8("q" * 9100 + "\n"))
r = cli(repo8, "lint", d8, "--map", good_map)
s.ok("a base over the cap: check exit 1", r.returncode == 1 and "over the cap of 9000" in r.stderr, "%d %r" % (r.returncode, r.stderr))

# ---- the map's `fwx <command>` must exist -------------------------------------------------------------------------
repo9, d9 = phase()
bad_map = write_map("bad-map.md", "Run `fwx frobnicate` first, then `fwx session`.\n")
cli(repo9, "new", d9, "--map", bad_map)
r = cli(repo9, "lint", d9, "--map", bad_map)
s.eq("a map naming `fwx frobnicate`: check exit 1", r.returncode, 1)
s.ok("the message names the command", "unknown command: fwx frobnicate" in r.stderr and "fwx state" not in r.stderr.replace("fwx frobnicate", ""), r.stderr)
cli(repo9, "new", d9, "--map", good_map)
r = cli(repo9, "lint", d9, "--map", good_map)
s.eq("the map with real commands only: exit 0", r.returncode, 0)
# The commands are the objects of lib/fwx/routes.py, not the files of lib/fwx/commands/ (`phase` and `session` are no file).
# Seen red with the commands read from the files: FAIL: a map naming objects of the table (`fwx phase new`, `fwx session`, `fwx review read`): exit 0: got 1, want 0
named_map = write_map("named-map.md", "Run `fwx phase new`, `fwx session`, `fwx decision list`, `fwx review read` and `fwx walk start`.\n")
cli(repo9, "new", d9, "--map", named_map)
r = cli(repo9, "lint", d9, "--map", named_map)
s.eq("a map naming objects of the table (`fwx phase new`, `fwx session`, `fwx review read`): exit 0", r.returncode, 0)
# The lint checks object and verb: an old or unknown `fwx <object> <verb>` fails and names itself (an old one, its new name too).
# Seen red with only the object word looked at (the base was sealed and linted clean):
#   FAIL: a base naming `fwx state decisions`: exit 1: got 0, want 1  (and the same for `fwx wave prepare`, `fwx linear create`)
for old_name, new_name in (("state decisions", "fwx decision list"), ("wave prepare", "fwx wave new"), ("linear create", "fwx linear new")):
    old_map = write_map("old-map.md", "Run `fwx %s` first.\n" % old_name)
    cli(repo9, "new", d9, "--map", old_map)
    r = cli(repo9, "lint", d9, "--map", old_map)
    s.ok("a base naming `fwx %s`: exit 1, naming it and `%s`" % (old_name, new_name),
         r.returncode == 1 and "fwx %s" % old_name in r.stderr and new_name in r.stderr, "%d %r" % (r.returncode, r.stderr))
unknown_map = write_map("unknown-verb-map.md", "Run `fwx phase nwe` first.\n")
cli(repo9, "new", d9, "--map", unknown_map)
r = cli(repo9, "lint", d9, "--map", unknown_map)
s.ok("a base naming `fwx phase nwe`: exit 1, naming it", r.returncode == 1 and "fwx phase nwe" in r.stderr, "%d %r" % (r.returncode, r.stderr))
cur_map = write_map("current-map.md", "Run `fwx wave merge`, `fwx linear list`, `fwx context DIR`, `fwx model executor small` and `fwx walk stop`.\n")
cli(repo9, "new", d9, "--map", cur_map)
r = cli(repo9, "lint", d9, "--map", cur_map)
s.eq("a base with only current names (a default verb, a positional word): exit 0", r.returncode, 0)
oldhand = helpers.write(SCRATCH, "oldhand.md", "Map. Use `fwx state decisions`.\n")
cli(repo9, "seal", oldhand)
r = cli(repo9, "lint", "--file", oldhand)
s.ok("a sealed hand-written file naming `fwx state decisions`: exit 1 and its new name", r.returncode == 1 and "fwx decision list" in r.stderr, "%d %r" % (r.returncode, r.stderr))
real = cli(repo9, "new", d9)
s.ok("the shipped data/context-map.md builds", real.returncode == 0, real.stderr)
s.eq("the shipped data/context-map.md checks", cli(repo9, "lint", d9).returncode, 0)
s.ok("the shipped map is about five lines", 3 <= len(read(os.path.join(ROOT, "data", "context-map.md")).strip().splitlines()) <= 8)

# ---- seal: the hand-written file ---------------------------------------------------------------------------------
src = helpers.write(SCRATCH, "plan/LONG.md", "the long document\n")
hand = helpers.write(SCRATCH, "hand.md", "Short map. Use `fwx state`.\n")
r = cli(repo, "seal", hand, "--source", src)
s.eq("seal: exit 0", r.returncode, 0)
sealed = read(hand)
s.ok("seal puts the mark on the first line", re.match(r"# Base context · [0-9a-f]{8}\nShort map", sealed), repr(sealed[:60]))
s.ok("seal with --source writes the source marker", re.search(r"<!-- source: \S*plan/LONG\.md @[0-9a-f]{8} -->", sealed), repr(sealed[-100:]))
r = cli(repo, "lint", "--file", hand, "--source", src)
s.ok("a sealed file with its source unchanged: exit 0", r.returncode == 0 and CHECKED.match(r.stdout.strip()), r.stdout + r.stderr)
r = cli(repo, "seal", hand, "--source", src)
s.eq("sealing twice gives the same file", read(hand), sealed)
helpers.write(SCRATCH, "plan/LONG.md", "the long document, changed\n")
r = cli(repo, "lint", "--file", hand, "--source", src)
s.eq("the source changed after seal: check exit 1", r.returncode, 1)
s.ok("the message names the source", re.search(r"stale: \S*plan/LONG\.md changed since the file was sealed", r.stderr), r.stderr)
r = cli(repo, "seal", hand, "--source", src)
s.eq("sealed again after the source changed: check passes", cli(repo, "lint", "--file", hand, "--source", src).returncode, 0)
with open(hand, "a", encoding="utf-8") as f:
    f.write("edited\n")
r = cli(repo, "lint", "--file", hand)
s.ok("a sealed file edited by hand: exit 1 `edited since sealed`", r.returncode == 1 and "edited since sealed" in r.stderr, r.stderr)
nomark = helpers.write(SCRATCH, "nomark.md", "no mark here\n")
r = cli(repo, "lint", "--file", nomark)
s.ok("a file with no mark: exit 1", r.returncode == 1 and "mark" in r.stderr, r.stderr)
helpers.write(SCRATCH, "plan/LONG.md", "the long document\n")
r = cli(repo, "lint", "--file", os.path.join(SCRATCH, "does-not-exist.md"))
s.eq("--file of a file that is not there: exit 2", r.returncode, 2)

# ---- the same path from a linked worktree ------------------------------------------------------------------------
# the protected variant: `.fwx/` is tracked and the worktree holds the live copy, so the phase folder is in the worktree
PHASE = ".fwx/milestones/v1/phases/01-alpha"
pmain = helpers.toy_repo({"README": "toy\n", ".fwx/PROJECT.md": "# toy\n", PHASE + "/context.md": CONTEXT % ("Intent.", "Success."),
                          PHASE + "/decisions.tsv": "\t".join(state.DECISION_COLUMNS) + "\n",
                          PHASE + "/audit.tsv": "\t".join(state.AUDIT_COLUMNS) + "\n"})
pwt = helpers.add_worktree(pmain, "phase-branch")
helpers.write(pmain, ".claude/fwx.json", json.dumps({"schema": 1, "project": {"default_branch_protected": True}}))
r_main = cli(pmain, "new", os.path.join(pmain, PHASE), "--map", good_map)
r_wt = cli(pwt, "new", os.path.join(pwt, PHASE), "--map", good_map)
mm, mw = WROTE.match(r_main.stdout.strip()), WROTE.match(r_wt.stdout.strip())
s.ok("both builds work", r_main.returncode == 0 and r_wt.returncode == 0 and mm and mw, r_main.stderr + r_wt.stderr)
s.eq("build from a linked worktree writes the same path", mw and mw.group(2), mm and mm.group(2))
s.ok("that path is in the common dir", bool(mm) and mm.group(2).startswith(os.path.realpath(os.path.join(pmain, ".git")) + os.sep), mm and mm.group(2))

# ---- --project: no open phase is NOT RUN, not a pass -----------------------------------------------------------
empty = helpers.toy_repo()
r = cli(empty, "lint", "--project", empty)
s.eq("check --project with no open phase: exit 77", r.returncode, 77)
s.ok("it says NOT RUN, NOT ARMED: no open phase", "NOT RUN, NOT ARMED: no open phase" in r.stdout + r.stderr, r.stdout + r.stderr)
repo8b, d8b = phase()
cli(repo8b, "new", d8b, "--map", good_map)
r = cli(repo8b, "lint", "--project", repo8b, "--map", good_map)
s.ok("check --project with an open phase looks at it", r.returncode == 0 and CHECKED.match(r.stdout.strip()), r.stdout + r.stderr)

# ---- --hook-command: the hook gets the file through the real input ---------------------------------------------
HOOK = """import json, sys
inp = json.load(sys.stdin)
mode = sys.argv[1]
if mode == "silent" or (mode == "good" and inp["agent_type"] == "Explore"):
    sys.exit(0)
first = open(sys.argv[2], encoding="utf-8").readline().rstrip("\\n")
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": first + "\\nbody"}}))
"""
hook = helpers.write(SCRATCH, "hook.py", HOOK)
repo10, d10 = phase()
cli(repo10, "new", d10, "--map", good_map)
b10 = base_of(d10)


def hook_cmd(mode):
    return "%s %s %s %s" % (sys.executable, hook, mode, b10)


r = cli(repo10, "lint", d10, "--map", good_map, "--hook-command", hook_cmd("good"))
s.ok("a hook that gives general-purpose the base and Explore nothing: exit 0", r.returncode == 0, r.stdout + r.stderr)
r = cli(repo10, "lint", d10, "--map", good_map, "--hook-command", hook_cmd("silent"))
s.eq("a silent hook: exit 1", r.returncode, 1)
s.ok("it names the agent that got nothing", "general-purpose" in r.stderr, r.stderr)
r = cli(repo10, "lint", d10, "--map", good_map, "--hook-command", hook_cmd("all"))
s.eq("a hook that answers Explore: exit 1", r.returncode, 1)
s.ok("it names Explore", "Explore" in r.stderr, r.stderr)
r = cli(repo10, "lint", d10, "--map", good_map, "--hook-command", "%s/no/such/hook" % SCRATCH)
s.eq("a hook that cannot run: exit 1", r.returncode, 1)

# ---- refresh: build when missing or stale, leave it when current ---------------------------------------------
repo11, d11 = phase()
b11 = base_of(d11)
s.ok("no base yet", not os.path.exists(b11))
s.eq("refresh builds a missing base", cb.refresh(d11, map_path=good_map)["written"], True)
s.eq("refresh leaves a current base", cb.refresh(d11, map_path=good_map)["written"], False)
decide(d11, "New decision.")
s.eq("refresh rebuilds a stale base", cb.refresh(d11, map_path=good_map)["written"], True)
s.ok("and the new decision is in it", "- New decision." in read(b11))

# ---- the table of cases: sections_for(agent_type) ----------------------------------------------------------------
table = write_map("table.tsv", "agent_type\tsections\twhy\nfwx:planner\tmap+decided\tbuilds on what is decided\n"
                               "Explore\tnone\tsearches\n*\tmap\tdefault\n")
s.eq("sections_for: exact row", cb.sections_for("fwx:planner", table), "map+decided")
s.eq("sections_for: none", cb.sections_for("Explore", table), "none")
s.eq("sections_for: unknown type falls to *", cb.sections_for("whatever", table), "map")
nodefault = write_map("nodefault.tsv", "agent_type\tsections\twhy\nExplore\tnone\tsearches\n")
try:
    cb.sections_for("x", nodefault)
    s.ok("a table with no * row is refused", False, "returned")
except cb.ContextBaseError as e:
    s.ok("a table with no * row is refused: `no default row`", "no default row" in str(e), str(e))
try:
    cb.sections_for("x", os.path.join(SCRATCH, "nope.tsv"))
    s.ok("a missing table is refused", False, "returned")
except cb.ContextBaseError as e:
    s.ok("a missing table is refused and names the file", "nope.tsv" in str(e), str(e))

# ---- usage ------------------------------------------------------------------------------------------------------
for args in ((), ("new",), ("new", "a", "b"), ("seal",), ("lint",), ("lint", "x", "--file", "y")):
    r = cli(repo, *args)
    s.eq("fwx context %s: exit 2" % " ".join(args), r.returncode, 2)
r = cli(repo, "new", os.path.join(repo, "not-a-folder"))
s.eq("build of a folder that is not there: exit 2", r.returncode, 2)
r = cli(repo, "new", repo)
s.ok("build of a folder outside .fwx: exit 2 and says so", r.returncode == 2 and ".fwx" in r.stderr, "%d %r" % (r.returncode, r.stderr))

s.done()
