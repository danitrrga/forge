#!/usr/bin/env python3
"""`fwx migrate-gsd plan` and `refs`: what the conversion of a GSD `.planning/` to `.fwx/` would do, read only.

Every case builds a toy repository in a temp dir (with its `origin` beside it), runs bin/fwx on it and reads the text or the
`--json` it prints. The toy `.planning/` is described next to `build()`. HOME, XDG_* and git's global config are isolated, and
every temp dir is removed by helpers.cleanup() also when a check fails.

Cases (the plan's twelve, then what the code added):
  1 plan writes nothing   2 classification   3 milestone of each phase   4 closed or open   5 phases only in the ROADMAP
  6 scopes   7 backlog   8 `.gitignore`   9 refs   10 no `.planning/`   11 an emptied phase keeps its `.gitkeep`   12 ahead
  extras: unmerged branches, the remote without its credentials, a repository nested in `.planning/`, two files for one
  destination, a folder cited as a reference, the write half refused (`apply`, `leftovers`, `refs --rewrite|--prefix`: exit 2)

Seen red before the command existed (a copy of this plugin without migrate_gsd.py):
  FAIL: plan (text) exits 0: got 2, want 0

Controls: each is a copy of this plugin with one rule of lib/fwx/commands/migrate_gsd.py changed (154 checks on the good code);
the first FAIL line it printed:
  - plan creates `.fwx/` (case 1):
      FAIL: plan wrote .fwx: a .fwx/ exists in the repo
  - a PLAN is purged without its SUMMARY being looked for (case 2):
      FAIL: 02.1-01-PLAN.md (no SUMMARY) classified purge, want keep
  - the milestone list of the ROADMAP ignored (case 3; ws1 falls to its STATE's v3.0 and the ranges are not read):
      FAIL: ws1 has four phases, none made up: got ['.fwx/subprojects/ws1/milestones/v3/phases/01-one', ...
  - closed read from the pairing only (case 4):
      FAIL: phase 02.1-b closed: the box [x] wins over an incomplete pairing: got False, want True
  - the slug of a ROADMAP-only phase without its 60-character limit (case 5):
      FAIL: slug of phase 3 is 138 characters, over 60
  - a workstream sent to `.fwx/workstreams/` (case 6):
      FAIL: .planning/workstreams/ws1/private/notes.md destination: got '.fwx/workstreams/ws1/private/notes.md', want '.fwx/subprojects/ws1/private/notes.md'
  - a quick task without SUMMARY counted as done (case 7):
      FAIL: 260101-PLAN.md classified purge, want backlog
  - `.gitignore` lines copied unchanged (case 8):
      FAIL: the .gitignore lines that name .planning/: got [{'old': '/.planning/phases/01-a/fonts/', 'new': '/.planning/phases/01-a/fonts/'}, ...
  - a reference to a purged file called moved (case 9):
      FAIL: refs classify moved, purged and prefix in a script, a comment and a biome.json: missing [('scripts/check.sh', 3, '.planning/STATE.md', 'purged', None)]
  - the zero-files refusal removed (case 10):
      FAIL: a repo without .planning/ exits 2: got 0, want 2
  - every `.gitkeep` purged (case 11):
      FAIL: phase 02.5-c missing from destination
  - the `ahead` key dropped from `--json` (case 12):
      FAIL: ahead missing
  - the extras: credentials left in the remote ("FAIL: a remote with credentials in its URL is printed without them: got
    'https://user:s3cret@example.com/x.git', ..."), the collision check off ("FAIL: two files for one destination exit 2: got 0,
    want 2"), the branch list emptied ("FAIL: unmerged branches that touch .planning/: got [], want [('eden/x', ...)]"), a
    nested repository not expanded ("FAIL: a repository nested in .planning/ is listed file by file, its .git too, and never as
    a folder"), a cited `.planning/phases/` sent to `.fwx/phases/` ("FAIL: refs classify ... missing [('scripts/check.sh', 4,
    '.planning/phases/', 'moved', '.fwx/milestones/v2/phases/')]"), sizes not summed ("FAIL: totals.keep files and bytes: got
    {'files': 14, 'bytes': 0}, ...").
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()
HOME = helpers.mkdtemp("fwx-home-")
ENV = {"HOME": HOME, "XDG_CONFIG_HOME": HOME, "XDG_DATA_HOME": HOME, "GIT_CONFIG_GLOBAL": os.devnull,
       "PYTHONDONTWRITEBYTECODE": "1"}
LONG = ("Café au lait: the extraordinarily long title of the third phase, which goes on and on well past the "
        "sixty characters a folder name may carry")
OLD = "/.planning/workstreams/*/private/"
PLAN_BODY = "# Plan\n"


def run(repo, *args):
    return helpers.fwx(repo, "migrate-gsd", *args, env=ENV)


def plan_json(repo, *args):
    r = run(repo, "plan", "--json", *args)
    return r, (json.loads(r.stdout) if r.returncode == 0 else None)


def build(outside=False, ws=True, roadmap=None):
    """A toy repo on master with this `.planning/` (every file tracked unless said otherwise):

      PROJECT.md, STATE.md (`milestone: v2.0`), config.json, codebase/STACK.md
      ROADMAP.md      phases 1, 2.1, 2.5 and 3 with a box each ([ ] [x] [ ] [ ]) and a heading each
      phases/01-a     01-01 and 01-02 (PLAN + SUMMARY), CONTEXT, RESEARCH, shots/a.png, 01-BASELINE.md, .gitkeep;
                      fonts/ is ignored (a.woff exists on disk only)
      phases/02.1-b   02.1-01-PLAN.md and no SUMMARY
      phases/02.5-c   .gitkeep only
      phases/999.1-x  CONTEXT with a heading
      quick/          260101-open (a PLAN) and 260102-done (PLAN + SUMMARY)
      state.json      on disk, not tracked
      workstreams/ws1 PROJECT.md, STATE.md, a ROADMAP with milestone ranges (v1.0 1-2, v2.0 3-4, v2.1 5-6, v3.0 7-8, three
                      different dashes) and no boxes; phases 01-one (paired), 03-two (paired), 05-three (PLAN only), 08-four
                      (paired); private/ is ignored. `outside` adds 09-five, which no range covers.
    and a `scripts/check.sh` and a `biome.json` that name `.planning`, an `eden/x` branch that touches the ROADMAP, a bare
    `origin` with every ref fetched, and one commit on master that origin does not have."""
    repo = helpers.mkdtemp("fwx-migrate-")
    helpers.git(repo, "init", "-q", "-b", "master")
    road = roadmap if roadmap is not None else (
        "# Roadmap\n\n## Phases\n\n- [ ] **Phase 1: Alpha** - first\n- [x] **Phase 2.1: Beta** - second\n"
        "- [ ] **Phase 2.5: Gamma** - inserted\n- [ ] **Phase 3: %s** - later\n\n## Phase Details\n\n"
        "### Phase 1: Alpha\nGoal.\n\n### Phase 2.1: Beta\nGoal.\n\n### Phase 2.5: Gamma\nGoal.\n\n### Phase 3: %s\nGoal.\n" % (LONG, LONG))
    files = {
        "README": "toy\n",
        ".gitignore": "node_modules/\n/.planning/phases/01-a/fonts/\n%s\n" % OLD,
        "scripts/check.sh": "#!/bin/sh\ncat .planning/phases/01-a/01-01-SUMMARY.md\n# the old state lived in .planning/STATE.md\nls .planning/phases/\n",
        "biome.json": '{"files": {"ignore": ["!.planning"]}}\n',
        ".planning/PROJECT.md": "# Project\n",
        ".planning/STATE.md": "---\nmilestone: v2.0\n---\n# State\n",
        ".planning/config.json": "{}\n",
        ".planning/ROADMAP.md": road,
        ".planning/codebase/STACK.md": "# Stack\n",
        ".planning/quick/260101-open/260101-PLAN.md": "# Fix the thing\n",
        ".planning/quick/260102-done/260102-PLAN.md": PLAN_BODY,
        ".planning/quick/260102-done/260102-SUMMARY.md": "# Done\n",
        ".planning/phases/999.1-x/999.1-CONTEXT.md": "# Someday idea\n",
        ".planning/phases/01-a/.gitkeep": "",
        ".planning/phases/01-a/01-01-PLAN.md": PLAN_BODY, ".planning/phases/01-a/01-01-SUMMARY.md": "# s\n",
        ".planning/phases/01-a/01-02-PLAN.md": PLAN_BODY, ".planning/phases/01-a/01-02-SUMMARY.md": "# s\n",
        ".planning/phases/01-a/01-CONTEXT.md": "# c\n", ".planning/phases/01-a/01-RESEARCH.md": "# r\n",
        ".planning/phases/01-a/shots/a.png": "png",
        ".planning/phases/01-a/01-BASELINE.md": "# baseline kept: GSD does not know it\n",
        ".planning/phases/02.1-b/02.1-01-PLAN.md": PLAN_BODY,
        ".planning/phases/02.5-c/.gitkeep": "",
    }
    if ws:
        base = ".planning/workstreams/ws1/"
        files.update({
            base + "PROJECT.md": "# Workstream\n", base + "STATE.md": "---\nmilestone: v3.0\n---\n",
            base + "ROADMAP.md": ("# Roadmap\n\n- ✅ **v1.0 First** - Phases 1-2 (shipped)\n"
                                  "- ✅ **v2.0 Second** – Phases 3-4\n- \U0001F6A7 **v2.1 Third** — Phases 5-6\n"
                                  "- \U0001F4CB **v3.0 Fourth** - Phases 7-8\n"),
            base + "phases/01-one/01-01-PLAN.md": PLAN_BODY, base + "phases/01-one/01-01-SUMMARY.md": "# s\n",
            base + "phases/03-two/03-01-PLAN.md": PLAN_BODY, base + "phases/03-two/03-01-SUMMARY.md": "# s\n",
            base + "phases/05-three/05-01-PLAN.md": PLAN_BODY,
            base + "phases/08-four/08-01-PLAN.md": PLAN_BODY, base + "phases/08-four/08-01-SUMMARY.md": "# s\n",
        })
        if outside:
            files[base + "phases/09-five/09-01-PLAN.md"] = PLAN_BODY
    for rel, text in files.items():
        helpers.write(repo, rel, text)
    helpers.git(repo, "add", "-A")
    helpers.git(repo, "commit", "-q", "-m", "toy")
    helpers.git(repo, "checkout", "-q", "-b", "eden/x")
    helpers.write(repo, ".planning/ROADMAP.md", road + "\nedited on a branch\n")
    helpers.git(repo, "commit", "-q", "-am", "eden")
    helpers.git(repo, "checkout", "-q", "master")
    origin = os.path.join(helpers.mkdtemp("fwx-origin-"), "origin.git")
    helpers.git(repo, "clone", "-q", "--bare", repo, origin)
    helpers.git(repo, "remote", "add", "origin", origin)
    helpers.git(repo, "fetch", "-q", "origin")
    helpers.write(repo, "README", "ahead\n")
    helpers.git(repo, "commit", "-q", "-am", "local only")
    helpers.write(repo, ".planning/phases/01-a/fonts/a.woff", "font")          # ignored
    if ws:
        helpers.write(repo, ".planning/workstreams/ws1/private/notes.md", "# private\n")  # ignored
    helpers.write(repo, ".planning/state.json", "{}\n")                          # untracked
    nested = os.path.join(repo, ".planning", "ref")                              # an untracked repository inside the folder
    os.makedirs(nested)
    helpers.git(nested, "init", "-q")
    helpers.write(nested, "a.txt", "a\n")
    helpers.write(nested, "b/c.txt", "c\n")
    return repo, origin


def snapshot(repo):
    """Every path of the repo, .git included, with its size and modification time. No `git status` in here: git refreshes its
    own index when that runs, and that is its write, not the command's."""
    seen = {}
    for dirpath, dirnames, filenames in os.walk(repo):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            st = os.lstat(p)
            seen[os.path.relpath(p, repo)] = (st.st_size, st.st_mtime_ns)
    return seen


def by_src(d):
    return {f["src"]: f for f in d["files"]}


# ---- 1: plan writes nothing -----------------------------------------------------------------------------------------
repo, origin = build()
before_status = helpers.git(repo, "status", "--porcelain", "--ignored")
before_tree = snapshot(repo)
rt = run(repo, "plan")
rj, d = plan_json(repo)
rr = run(repo, "refs", "--base", d["base"] if d else "HEAD")
after_tree = snapshot(repo)
after_status = helpers.git(repo, "status", "--porcelain", "--ignored")
s.eq("plan (text) exits 0", rt.returncode, 0)
s.eq("plan --json exits 0", rj.returncode, 0)
s.eq("refs exits 0", rr.returncode, 0)
s.ok("plan wrote .fwx", not os.path.exists(os.path.join(repo, ".fwx")), "a .fwx/ exists in the repo")
s.eq("git status --porcelain --ignored is the same after plan and refs", after_status, before_status)
changed = sorted(p for p in set(before_tree) | set(after_tree) if before_tree.get(p) != after_tree.get(p))
s.ok("plan wrote nothing: the list of paths (size, mtime) is the same before and after", not changed, "changed: %s" % changed[:5])
if d is None:
    s.done()
F = by_src(d)
s.eq("schema", d["schema"], 1)
s.ok("text output counts the files it looked at", re.search(r"^\d+ files looked at in 2 scope\(s\)", rt.stdout, re.M), rt.stdout[:300])
s.eq("untracked and ignored files are in the list (a nested repository's .git apart)",
     sorted(f["src"] for f in d["files"] if not f["tracked"] and "/.git/" not in f["src"]),
     sorted([".planning/phases/01-a/fonts/a.woff", ".planning/ref/a.txt", ".planning/ref/b/c.txt", ".planning/state.json",
             ".planning/workstreams/ws1/private/notes.md"]))
s.ok("a repository nested in .planning/ is listed file by file, its .git too, and never as a folder",
     not any(f["src"].endswith("/") for f in d["files"]) and any(f["src"].startswith(".planning/ref/.git/") for f in d["files"]))
s.eq("... and each file of it moves to the same path under .fwx", F.get(".planning/ref/b/c.txt", {}).get("dest"), ".fwx/ref/b/c.txt")


def act(src, action, rule=None, dest=None, note=""):
    f = F.get(src)
    got = f["action"] if f else "missing"
    s.ok("%s%s classified %s, want %s" % (os.path.basename(src), note, got, action), got == action)
    if f and rule:
        s.eq("%s rule" % src, f["rule"], rule)
    if f and dest:
        s.eq("%s destination" % src, f["dest"], dest)


# ---- 2: classification ----------------------------------------------------------------------------------------------
P = ".planning/phases/"
D2 = ".fwx/milestones/v2/phases/"
act(P + "01-a/01-01-PLAN.md", "purge", "plan-done")
act(P + "01-a/01-02-PLAN.md", "purge", "plan-done")
act(P + "02.1-b/02.1-01-PLAN.md", "keep", "plan-open", D2 + "02.1-b/02.1-01-PLAN.md", " (no SUMMARY)")
act(P + "01-a/01-01-SUMMARY.md", "keep", "phase-doc", D2 + "01-a/01-01-SUMMARY.md")
act(P + "01-a/01-CONTEXT.md", "keep", "phase-doc")
act(P + "01-a/01-BASELINE.md", "keep", "unknown", D2 + "01-a/01-BASELINE.md", " (unknown)")
act(P + "01-a/01-RESEARCH.md", "purge", "phase-scratch")
act(P + "01-a/shots/a.png", "purge", "phase-media")
act(P + "01-a/.gitkeep", "purge", "phase-gitkeep")
act(P + "01-a/fonts/a.woff", "leftover_move", "leftover", D2 + "01-a/fonts/a.woff", " (ignored)")
act(".planning/state.json", "leftover_delete", "machine-state", None, " (untracked)")
act(".planning/workstreams/ws1/private/notes.md", "leftover_move", "leftover", ".fwx/subprojects/ws1/private/notes.md")
act(".planning/STATE.md", "purge", "machine-state")
act(".planning/config.json", "purge", "machine-state")
act(".planning/codebase/STACK.md", "purge", "generated")
act(".planning/ROADMAP.md", "keep", "milestone-docs", ".fwx/milestones/v2/ROADMAP.md")
act(".planning/quick/260102-done/260102-SUMMARY.md", "purge", "quick-done")
act(".planning/quick/260102-done/260102-PLAN.md", "purge", "quick-done")
act(".planning/quick/260101-open/260101-PLAN.md", "backlog", "quick-open")
act(P + "999.1-x/999.1-CONTEXT.md", "backlog", "backlog")
tot = d["totals"]
for k in ("keep", "purge", "backlog", "leftover_move", "leftover_delete"):
    want = [f for f in d["files"] if f["action"] == k]
    s.eq("totals.%s files and bytes" % k, tot[k], {"files": len(want), "bytes": sum(f["bytes"] for f in want)})
want = [f for f in d["files"] if f["action"] == "keep" and f["rule"] == "unknown"]
s.eq("totals.unknown counts the kept unknown files, a subset of keep", tot["unknown"], {"files": len(want), "bytes": sum(f["bytes"] for f in want)})
s.eq("the unknown file is the baseline one", [f["src"] for f in want], [P + "01-a/01-BASELINE.md"])
s.eq("gsd_state.milestone", d["gsd_state"]["milestone"], "v2.0")

# ---- 3: milestone of each phase -------------------------------------------------------------------------------------
PH = {p["dest"]: p for p in d["phases"]}


def phase(dest, what, field, want):
    p = PH.get(dest)
    s.ok("phase %s %s: %s" % (os.path.basename(dest), what, "got %r, want %r" % (p and p[field], want)), p is not None and p[field] == want)


def sig(dest):
    return (PH.get(dest) or {}).get("signals", {})


WS = ".fwx/subprojects/ws1/milestones/"
for name in ("01-a", "02.1-b", "02.5-c"):
    phase(D2 + name, "milestone (STATE says v2.0)", "milestone", "v2")
for dest, ms in ((WS + "v1/phases/01-one", "v1"), (WS + "v2/phases/03-two", "v2"), (WS + "v2/phases/05-three", "v2 (v2.1 is in v2)"),
                 (WS + "v3/phases/08-four", "v3")):
    s.ok("phase %s milestone: got %s, want %s" % (os.path.basename(dest), (PH.get(dest) or {}).get("milestone"), ms.split()[0]),
         dest in PH and PH[dest]["milestone"] == ms.split()[0])
s.eq("ws1 has four phases, none made up", sorted(k for k in PH if k.startswith(".fwx/subprojects/ws1")), sorted([
    WS + "v1/phases/01-one", WS + "v2/phases/03-two", WS + "v2/phases/05-three", WS + "v3/phases/08-four"]))
s.eq("ws1's ROADMAP goes to its current milestone", F.get(".planning/workstreams/ws1/ROADMAP.md", {}).get("dest"), WS + "v3/ROADMAP.md")
rep, _ = build(outside=True)  # one phase outside every range: exit 2, naming it
r = run(rep, "plan")
s.eq("a phase outside the ROADMAP's ranges exits 2", r.returncode, 2)
s.ok("... and names the phase", "09-five" in r.stderr, r.stderr)
mapfile = os.path.join(HOME, "map.txt")
with open(mapfile, "w") as fh:
    fh.write("# the phase no range covers\nws1/9 v3\n")
r, d3 = plan_json(rep, "--milestone-map", mapfile)
s.eq("--milestone-map resolves it (exit)", r.returncode, 0)
s.ok("--milestone-map puts 09-five in v3", d3 is not None and any(p["dest"] == WS + "v3/phases/09-five" for p in d3["phases"]),
     "phases: %s" % (d3 and [p["dest"] for p in d3["phases"] if "09" in p["dest"]]))
mapjson = os.path.join(HOME, "map.json")
with open(mapjson, "w") as fh:
    fh.write('{"09-five": "v2.1"}')
r, d3 = plan_json(rep, "--milestone-map", mapjson)
s.ok("a JSON map by folder name, with v2.1 read as v2", d3 is not None and any(p["dest"] == WS + "v2/phases/09-five" for p in d3["phases"]))
with open(mapfile, "w") as fh:
    fh.write("42=v1\n")
r = run(repo, "plan", "--milestone-map", mapfile)
s.ok("a key of the map no phase has is a note, not an error", r.returncode == 0 and "matched no phase: 42" in r.stdout, r.stdout[-200:])

# ---- 4: closed or open ----------------------------------------------------------------------------------------------
phase(D2 + "02.1-b", "closed: the box [x] wins over an incomplete pairing", "closed", True)
phase(D2 + "01-a", "open: the box [ ] wins over a complete pairing", "closed", False)
s.eq("02.1-b signals", sig(D2 + "02.1-b"), {"checklist": True, "pairing": False})
s.eq("01-a signals", sig(D2 + "01-a"), {"checklist": False, "pairing": True})
s.eq("02.5-c signals (no plan is not a paired phase)", sig(D2 + "02.5-c"), {"checklist": False, "pairing": False})
phase(WS + "v1/phases/01-one", "closed: no boxes, so the pairing decides", "closed", True)
phase(WS + "v2/phases/05-three", "open: no boxes, a PLAN without SUMMARY", "closed", False)
s.eq("a phase without boxes has checklist null", sig(WS + "v1/phases/01-one").get("checklist", "phase missing"), None)
s.ok("the text marks the two signals that disagree", re.search(r"02\.1-b .*DISAGREE", rt.stdout) and not re.search(r"02\.5-c .*DISAGREE", rt.stdout), rt.stdout)
r, d4 = plan_json(repo, "--close", "1", "--open", "2.1")
P4 = {p["dest"]: p for p in d4["phases"]} if d4 else {}
s.ok("--close 1 closes 01-a against its box", P4.get(D2 + "01-a", {}).get("closed") is True)
s.ok("--open 2.1 opens 02.1-b against its box", P4.get(D2 + "02.1-b", {}).get("closed") is False)
r = run(repo, "plan", "--close", "7")
s.eq("--close 7 (no such phase) exits 2", r.returncode, 2)
s.ok("... and names 7", "7" in r.stderr, r.stderr)
s.eq("--close and --open on one phase exit 2", run(repo, "plan", "--close", "1", "--open", "1").returncode, 2)

# ---- 5: phases only in the ROADMAP ----------------------------------------------------------------------------------
road = [p for p in d["phases"] if p["from_roadmap"]]
s.eq("one phase comes from the ROADMAP alone (phase 3)", len(road), 1)
if road:
    m = re.match(r"\.fwx/milestones/v2/phases/03-([a-z0-9-]+)\Z", road[0]["dest"])
    s.ok("its destination is 03-<slug>", m, road[0]["dest"])
    slug = m.group(1) if m else ""
    s.ok("slug of phase 3 is %d characters, over 60" % len(slug), 0 < len(slug) <= 60)
    s.ok("the slug is ASCII (the accent of the title is gone) and starts with the title", slug.startswith("cafe-au-lait-the-extraordinarily"), slug)
    s.ok("the slug does not end with a dash", not slug.endswith("-"), slug)
    s.eq("a ROADMAP-only phase has no source folder and is open", (road[0]["src"], road[0]["closed"]), (None, False))
s.ok("phases with a folder are not made up from their headings", not any(p["from_roadmap"] and "01-a" in p["dest"] for p in d["phases"]))
other, _ = build(ws=False, roadmap="# Hoja de ruta\n\n### Fase 0 — Cimientos\nTexto.\n")
ro = run(other, "plan")
s.eq("a ROADMAP with `### Fase 0` plans (exit)", ro.returncode, 0)
s.ok("... creates no phase from it", "from_roadmap" not in ro.stdout and "(ROADMAP only)" not in ro.stdout, ro.stdout)
s.ok("... and says so", "no phase is created from it" in ro.stdout, ro.stdout)
rj2, dj2 = plan_json(other)
s.ok("... the note goes to stderr with --json", "no phase is created from it" in rj2.stderr, rj2.stderr)
s.ok("... and no phase is from_roadmap", dj2 is not None and not any(p["from_roadmap"] for p in dj2["phases"]))

# ---- 6: scopes ------------------------------------------------------------------------------------------------------
s.eq("scopes", d["scopes"], [{"src": ".planning", "dest": ".fwx"}, {"src": ".planning/workstreams/ws1", "dest": ".fwx/subprojects/ws1"}])
act(".planning/workstreams/ws1/PROJECT.md", "keep", "project", ".fwx/subprojects/ws1/PROJECT.md")
act(".planning/PROJECT.md", "keep", "project", ".fwx/PROJECT.md")
act(".planning/workstreams/ws1/STATE.md", "purge", "machine-state")

# ---- 7: backlog -----------------------------------------------------------------------------------------------------
s.eq("backlog items with their titles", d["backlog"], [{"src": ".planning/phases/999.1-x", "title": "Someday idea"},
                                                        {"src": ".planning/quick/260101-open", "title": "Fix the thing"}])
s.ok("02.5-c is a phase, not backlog", not any("02.5-c" in b["src"] for b in d["backlog"]))
s.ok("a quick task with a SUMMARY is not backlog", not any("260102-done" in b["src"] for b in d["backlog"]))

# ---- 8: .gitignore --------------------------------------------------------------------------------------------------
s.eq("the .gitignore lines that name .planning/", d["gitignore"], [
    {"old": "/.planning/phases/01-a/fonts/", "new": "/.fwx/milestones/v2/phases/01-a/fonts/"},
    {"old": OLD, "new": "/.fwx/subprojects/*/private/"}])

# ---- 9: refs --------------------------------------------------------------------------------------------------------
want = {("scripts/check.sh", 2, ".planning/phases/01-a/01-01-SUMMARY.md", "moved", D2 + "01-a/01-01-SUMMARY.md"),
        ("scripts/check.sh", 3, ".planning/STATE.md", "purged", None),
        ("scripts/check.sh", 4, ".planning/phases/", "moved", ".fwx/milestones/v2/phases/"),
        ("biome.json", 1, ".planning", "prefix", ".fwx"),
        (".gitignore", 2, ".planning/phases/01-a/fonts/", "moved", ".fwx/milestones/v2/phases/01-a/fonts/"),
        (".gitignore", 3, OLD[1:], "moved", ".fwx/subprojects/*/private/")}
got = {(r["file"], r["line"], r["old"], r["kind"], r["new"]) for r in d["refs"]}
s.ok("refs classify moved, purged and prefix in a script, a comment and a biome.json: missing %s" % sorted(want - got, key=str), want <= got)
s.eq("refs names only files outside .planning/ and .fwx/", sorted({r["file"] for r in d["refs"]}), [".gitignore", "biome.json", "scripts/check.sh"])
# the real use: the branch has no .planning/ any more, and refs reads the base commit
base = d["base"]
helpers.git(repo, "checkout", "-q", "-b", "converted")
helpers.git(repo, "rm", "-rq", ".planning")
helpers.git(repo, "commit", "-q", "-m", "converted")
rr, dr = (lambda r: (r, json.loads(r.stdout) if r.returncode == 0 else None))(run(repo, "refs", "--base", base, "--json"))
s.eq("refs --base on a branch without .planning/ exits 0", rr.returncode, 0)
same = lambda x: sorted(str(r) for r in x if r["file"] != ".gitignore")  # an ignored folder is unknown to a commit
s.ok("... and lists the same references as plan did", same((dr or {}).get("refs", [])) == same(d["refs"]), str((dr or {}).get("refs")))
none = {"files": 0, "bytes": 0}
s.eq("... and reads the files of the base (tracked ones only)", (dr or {}).get("totals"), {**d["totals"], "leftover_move": none, "leftover_delete": none})
s.eq("refs without --base exits 2", run(repo, "refs").returncode, 2)
s.eq("refs --base of a non-commit exits 2", run(repo, "refs", "--base", "nonsense").returncode, 2)
s.eq("an unknown subcommand exits 2", run(repo, "nonsense").returncode, 2)
for args in (["refs", "--base", base, "--rewrite"], ["refs", "--base", base, "--prefix"]):
    r = run(repo, *args)  # unit 2 built the write half: what is left of "not built yet" is a flag with no file
    s.ok("`%s` with no file exits 2 and says it needs one" % " ".join(args[2:]), r.returncode == 2 and "needs at least one file" in r.stderr, r.stderr)

# ---- 10: no .planning/ ----------------------------------------------------------------------------------------------
bare = helpers.toy_repo()
r = run(bare, "plan")
s.eq("a repo without .planning/ exits 2", r.returncode, 2)
s.ok("... saying 0 files looked at", "0 files looked at" in r.stderr, r.stderr)
s.eq("a folder that is not a repo exits 2", run(HOME, "plan").returncode, 2)

# ---- 11: an emptied phase keeps its .gitkeep ------------------------------------------------------------------------
act(P + "02.5-c/.gitkeep", "keep", "phase-gitkeep-last", D2 + "02.5-c/.gitkeep")
for p in d["phases"]:
    if p["src"]:
        s.ok("phase %s missing from destination" % os.path.basename(p["dest"]),
             any(f["dest"] and f["dest"].startswith(p["dest"] + "/") for f in d["files"]))

# ---- 12: ahead ------------------------------------------------------------------------------------------------------
s.ok("ahead missing", "ahead" in d)
s.eq("ahead: the local commit origin does not have", d.get("ahead"), 1)
s.eq("remote", d["remote"], origin)
s.eq("base is HEAD", d["base"], helpers.git(repo, "rev-parse", "master").strip())

# ---- extras ---------------------------------------------------------------------------------------------------------
s.eq("unmerged branches that touch .planning/", [(b["name"], b["files"]) for b in d["branches"]], [("eden/x", [".planning/ROADMAP.md"])])
noremote = helpers.toy_repo({".planning/PROJECT.md": "# p\n"})
helpers.git(noremote, "remote", "add", "origin", "https://user:s3cret@example.com/x.git")
r, dn = plan_json(noremote)
s.eq("a remote with credentials in its URL is printed without them", dn and dn["remote"], "https://example.com/x.git")
s.ok("remote credentials removed from the text too", "s3cret" not in run(noremote, "plan").stdout)
s.eq("ahead is null when there is no tracking branch", dn and dn.get("ahead", "ahead missing"), None)
s.eq("ahead is null and remote null without a remote", [(x.get("ahead", "ahead missing"), x.get("remote")) for x in [plan_json(helpers.toy_repo({".planning/PROJECT.md": "# p\n"}))[1]]], [(None, None)])
clash = helpers.toy_repo({".planning/PROJECT.md": "# p\n", ".planning/milestones/v1.0-ROADMAP.md": "# a\n",
                          ".planning/milestones/v1/v1.0-ROADMAP.md": "# b\n"})
r = run(clash, "plan")
s.eq("two files for one destination exit 2", r.returncode, 2)
s.ok("... naming the destination", ".fwx/milestones/v1/v1.0-ROADMAP.md" in r.stderr, r.stderr)


# =====================================================================================================================
# Unit 2: the write half. Every case builds its own toy repository (build2: build() plus a CRLF file, a binary file and a
# symlink, all tracked), a linked worktree `fwx-migrate-gsd` of it, and runs the command in the worktree. A refusal is seen
# with its exit 2 AND with the repository unchanged: every path with size and modification time, `.git` of the repository
# included, plus `git status --porcelain --ignored`, before and after. The steps that can fail in the middle are failed on
# purpose, in process, by replacing one function of the module.
# =====================================================================================================================
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

from fwx import state  # noqa: E402
import fwx.commands.migrate_gsd as mg  # noqa: E402

CRLF = b"# c\r\nsecond line\r\n"
BLOB = b"\xff\xfe\x00binary\r\n\x80"
MAIN_PRESENT = "the main checkout"


def rd(path, mode="r"):
    """The content of a file, or None (a missing file is a failed check, not a crash of the test)."""
    try:
        with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
            return fh.read()
    except OSError:
        return None


def wbytes(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def build2(**kw):
    repo, origin = build(**kw)
    wbytes(repo, ".planning/phases/01-a/01-CONTEXT.md", CRLF)               # a CRLF file: a text copy would change it
    wbytes(repo, ".planning/knowledge/blob.bin", BLOB)                      # bytes that are not UTF-8, unknown to GSD: kept
    os.symlink("01-CONTEXT.md", os.path.join(repo, ".planning/phases/01-a/01-context-link"))  # a tracked symlink
    helpers.git(repo, "add", "--", ".planning/phases/01-a/01-CONTEXT.md", ".planning/knowledge/blob.bin", ".planning/phases/01-a/01-context-link")
    helpers.git(repo, "commit", "-q", "-m", "u2 extras")
    return repo, origin


def world(**kw):
    """(main checkout, linked worktree on its own branch)."""
    repo, _origin = build2(**kw)
    return repo, helpers.add_worktree(repo, "fwx-migrate-gsd")


def content(root):
    """Every path outside .git with its kind and, for a file, a hash of its bytes: what a person would call 'the same files'."""
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != ".git"]
        for n in dn + fn:
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                out[rel] = ("l", os.readlink(p))
            elif os.path.isdir(p):
                out[rel] = ("d",)
            else:
                with open(p, "rb") as f:
                    out[rel] = ("f", hashlib.sha256(f.read()).hexdigest())
    return out


def strict(*roots):
    out = {}
    for i, r in enumerate(roots):
        out.update({(i, p): v for p, v in snapshot(r).items()})
    return out


def porcelain(cwd):
    return helpers.git(cwd, "status", "--porcelain", "--ignored")


def index_of(cwd):
    return helpers.git(cwd, "ls-files", "-s")


def inproc(cwd, argv, patches=()):
    """bin/fwx's main() in this process, in cwd, with the toy world's environment; `patches` is [(object, name, value)]."""
    old_env, old_cwd = dict(os.environ), os.getcwd()
    saved = [(o, n, getattr(o, n)) for o, n, _ in patches]
    out, err = io.StringIO(), io.StringIO()
    try:
        os.environ.clear()
        os.environ.update(helpers.clean_env(**ENV))
        os.chdir(cwd)
        for o, n, v in patches:
            setattr(o, n, v)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mg.main(list(argv))
    finally:
        for o, n, v in reversed(saved):
            setattr(o, n, v)
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)
    return rc, out.getvalue(), err.getvalue()


def show_bytes(cwd, sha, path):
    r = subprocess.run(["git", "-C", cwd, "show", "%s:%s" % (sha, path)], capture_output=True, env=helpers.clean_env(**ENV))
    return r.stdout if r.returncode == 0 else None


def refusal(label, cwd, argv, want, roots):
    """exit 2, a stderr that says `want`, and nothing in `roots` different afterwards (paths, sizes, mtimes, git status)."""
    st0, sn0 = porcelain(cwd), strict(*roots)
    r = run(cwd, *argv)
    sn1, st1 = strict(*roots), porcelain(cwd)
    s.eq("%s: exits 2" % label, r.returncode, 2)
    s.ok("%s: stderr says %r" % (label, want), want in r.stderr, r.stderr[-300:])
    changed = sorted(str(k) for k in set(sn0) | set(sn1) if sn0.get(k) != sn1.get(k))
    s.ok("%s: the repository is unchanged afterwards (every path with size and mtime, .git included)" % label, not changed, "changed: %s" % changed[:5])
    s.eq("%s: git status --porcelain --ignored is the same" % label, st1, st0)
    return r


# ---- U2 1: the refusals ------------------------------------------------------------------------------------------------
repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
refusal("apply on the default branch", repo, ["apply"], "default branch", (repo,))
refusal("apply with 0 files looked at", helpers.add_worktree(helpers.toy_repo(), "fwx-migrate-gsd"), ["apply"], "0 files looked at", ())

repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.git(wt, "checkout", "-q", "--detach")
refusal("apply on a detached HEAD", wt, ["apply"], "detached", roots)

repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
with open(os.path.join(wt, ".planning/phases/01-a/01-CONTEXT.md"), "ab") as fh:   # a tracked file of .planning/ modified
    fh.write(b"edited\n")
refusal("apply with .planning/phases/01-a/01-CONTEXT.md modified", wt, ["apply"], "not clean", roots)

repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.write(wt, "README", "edited\n")
helpers.git(wt, "add", "README")                                                  # staged, outside .planning/: the commit would sweep it in
refusal("apply with a staged change outside .planning/", wt, ["apply"], "not clean", roots)

repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.write(wt, ".fwx/PROJECT.md", "mine\n")
helpers.git(wt, "add", ".fwx/PROJECT.md")
helpers.git(wt, "commit", "-q", "-m", "a .fwx/PROJECT.md of its own")
r = refusal("apply with a destination that exists (.fwx/PROJECT.md)", wt, ["apply"], ".fwx/PROJECT.md exists", roots)
with open(os.path.join(wt, ".fwx/PROJECT.md"), encoding="utf-8") as fh:
    s.eq("... destination existed and was overwritten", fh.read(), "mine\n")

repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.write(wt, ".gitignore", "node_modules/\n/.fwx/\n")
helpers.git(wt, "commit", "-q", "-am", "ignore .fwx")
refusal("apply with a destination that .gitignore ignores", wt, ["apply"], "ignored by .gitignore", roots)

repo, wt = world(outside=True)
roots = (wt, os.path.join(repo, ".git"))
refusal("apply with a phase no milestone range covers", wt, ["apply"], "09-five", roots)

repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
refusal("apply --close 7 (no such phase)", wt, ["apply", "--close", "7"], "--close/--open name no phase: 7", roots)
refusal("apply --open 99 (no such phase)", wt, ["apply", "--open", "99"], "--close/--open name no phase: 99", roots)

repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.git(wt, "update-index", "--add", "--cacheinfo", "160000,%s,.planning/sub" % ("a" * 40))
os.makedirs(os.path.join(wt, ".planning/sub"), exist_ok=True)   # the empty folder of a submodule that is not checked out
helpers.git(wt, "commit", "-q", "-m", "a gitlink inside .planning/")
refusal("apply with a submodule inside .planning/", wt, ["apply"], "submodule", roots)

lone = helpers.toy_repo()
lwt = helpers.add_worktree(lone, "fwx-migrate-gsd")
helpers.write(lwt, ".planning/note.md", "untracked\n")
refusal("apply with only untracked files in .planning/", lwt, ["apply"], "0 tracked files to convert", (lwt, os.path.join(lone, ".git")))

# ---- U2 2: apply, the success path (and refs, the commit, the merge, leftovers: the real use, in order) ----------------------
repo, wt = world()
main0, st_main0, head_main0 = content(repo), porcelain(repo), helpers.git(repo, "rev-parse", "HEAD")
rp, D = plan_json(wt)
base = D["base"]
FD = by_src(D)
tracked_files = [p for p in helpers.git(wt, "ls-files", "-z", "--", ".planning").split("\0") if p]
before_bytes = {}
for p in tracked_files:
    with open(os.path.join(wt, p), "rb") as fh:
        before_bytes[p] = fh.read() if not os.path.islink(os.path.join(wt, p)) else None
r = run(wt, "apply", "--close", "1")
s.eq("apply in a worktree exits 0", r.returncode, 0)
s.ok("apply says what it did and where the base is", base in r.stdout and "nothing committed" in r.stdout, r.stdout[:400] + r.stderr[:300])
s.eq("apply commits nothing: HEAD is still the base", helpers.git(wt, "rev-parse", "HEAD").strip(), base)
keeps = [f for f in D["files"] if f["tracked"] and f["action"] == "keep"]
gone = [f for f in D["files"] if f["tracked"] and f["action"] in ("purge", "backlog")]
s.ok("the toy has kept, purged and backlog files to look at (%d, %d)" % (len(keeps), len(gone)), len(keeps) > 10 and len(gone) > 10)
idx = {}
for line in helpers.git(wt, "ls-files", "-s").splitlines():
    meta, _, path = line.partition("\t")
    idx[path] = tuple(meta.split()[:2])
for f in keeps:
    b = helpers.git(wt, "ls-tree", base, "--", f["src"]).split("\t")[0].split()
    s.ok("blob changed: %s -> %s" % (f["src"], f["dest"]), idx.get(f["dest"]) == (b[0], b[2]), "now %s, base %s" % (idx.get(f["dest"]), (b[0], b[2])))
for f in gone:
    s.ok("purged file still there: %s" % f["src"], f["src"] not in idx and not os.path.lexists(os.path.join(wt, f["src"])))
with open(os.path.join(wt, ".fwx/milestones/v2/phases/01-a/01-CONTEXT.md"), "rb") as fh:
    s.eq("the CRLF file is byte for byte the same at its destination", fh.read(), CRLF)
s.eq("the binary file is kept at its own path, byte for byte", open(os.path.join(wt, ".fwx/knowledge/blob.bin"), "rb").read(), BLOB)
s.eq("the symlink is still a symlink with the same target (mode 120000)",
     (idx[".fwx/milestones/v2/phases/01-a/01-context-link"][0], os.readlink(os.path.join(wt, ".fwx/milestones/v2/phases/01-a/01-context-link"))),
     ("120000", "01-CONTEXT.md"))
s.eq("nothing of .planning/ is tracked any more", [p for p in idx if p.startswith(".planning/")], [])
road_dest = [p["dest"] for p in D["phases"] if p["from_roadmap"]][0]
root_phases = [p.name for p in state.phases(Path(wt) / ".fwx", "v2")]
s.eq("state.phases lists the four phases of the root scope", root_phases, ["01-a", "02.1-b", "02.5-c", os.path.basename(road_dest)])
last = {n: state.last_stage(Path(wt) / ".fwx/milestones/v2/phases" / n) for n in root_phases}
s.eq("state.last_stage: 01-a closed (--close 1 against its box), 02.1-b closed (its box), the other two not",
     last, {"01-a": "closed", "02.1-b": "closed", "02.5-c": None, os.path.basename(road_dest): None})
ws = Path(wt) / ".fwx/subprojects/ws1"
s.eq("the workstream's phases are in v1, v2 and v3 and closed where their pairing says so",
     [(m, p.name, state.last_stage(p)) for m in state.milestones(ws) for p in state.phases(ws, m)],
     [("v1", "01-one", "closed"), ("v2", "03-two", "closed"), ("v2", "05-three", None), ("v3", "08-four", "closed")])
rows = state.read_rows(Path(wt) / ".fwx/milestones/v2/phases/01-a/audit.tsv")
s.eq("the stage row of a closed phase: kind, sha, detail", [(x["kind"], x["sha"], x["detail"]) for x in rows], [("stage", base, "closed migrated-from-gsd " + base)])
ms_text = open(os.path.join(wt, ".fwx/milestones/v2/MILESTONE.md"), encoding="utf-8").read()
s.ok("MILESTONE.md carries the base SHA, the date, the counts and the recovery command",
     base in ms_text and re.search(r"Date: \d{4}-\d{2}-\d{2}", ms_text) and "kept" in ms_text and "git show %s:.planning/<path>" % base in ms_text, ms_text)
s.ok("MILESTONE.md is the framework's template (a Goal and a Scope section, no placeholder left)",
     "## Goal" in ms_text and "## Scope" in ms_text and "<vN>" not in ms_text and "<What is true" not in ms_text and "<what the" not in ms_text, ms_text)
s.ok("the ROADMAP-only phase got its section as gsd-roadmap-entry.md",
     open(os.path.join(wt, road_dest, "gsd-roadmap-entry.md"), encoding="utf-8").read().startswith("### Phase 3: "), road_dest)
s.ok("the 02.5-c phase kept its .gitkeep (nothing generated for it)", ".fwx/milestones/v2/phases/02.5-c/.gitkeep" in idx)
s.eq(".gitignore: each line that names .planning/ has its twin right under it, the old line stays",
     open(os.path.join(wt, ".gitignore"), encoding="utf-8").read().splitlines(),
     ["node_modules/", "/.planning/phases/01-a/fonts/", "/.fwx/milestones/v2/phases/01-a/fonts/", OLD, "/.fwx/subprojects/*/private/"])
s.ok("the backlog is listed in what apply prints (it is removed, not migrated)", "Someday idea" in r.stdout and "Fix the thing" in r.stdout, r.stdout)
s.eq("nothing was written in the main checkout (same files, same status, same HEAD, no .fwx/)",
     (content(repo), porcelain(repo), helpers.git(repo, "rev-parse", "HEAD")), (main0, st_main0, head_main0))
s.ok("... and its branch is still master", helpers.git(repo, "symbolic-ref", "--short", "HEAD").strip() == "master")
with open(os.path.join(helpers.ROOT, "lib/fwx/commands/migrate_gsd.py"), encoding="utf-8") as fh:
    s.eq("no line of migrate_gsd.py names the audit file: state.append_audit is its only writer",
         [n for n, line in enumerate(fh, 1) if "audit.tsv" in line], [])

# refs --rewrite and --prefix, as the common procedure runs them: after apply, before the commit
check_before = open(os.path.join(wt, "scripts/check.sh"), encoding="utf-8").read()
r = run(wt, "refs", "--base", base, "--rewrite", "scripts/check.sh", "--prefix", "biome.json")
s.eq("refs --rewrite --prefix exits 0", r.returncode, 0)
with open(os.path.join(wt, "scripts/check.sh"), encoding="utf-8") as fh:
    # control (a --rewrite that swapped the prefix everywhere): "FAIL: the citation of a purged file is still .planning/STATE.md: ..."
    s.eq("--rewrite changes the moved path exactly, leaves the one a purged file had and the folder moves with its milestone",
         fh.read().splitlines(), ["#!/bin/sh", "cat .fwx/milestones/v2/phases/01-a/01-01-SUMMARY.md",
                                  "# the old state lived in .planning/STATE.md", "ls .fwx/milestones/v2/phases/"])
s.eq("--prefix changes !.planning in biome.json", open(os.path.join(wt, "biome.json"), encoding="utf-8").read(), '{"files": {"ignore": ["!.fwx"]}}\n')
s.eq("the rewritten files are staged", sorted(helpers.git(wt, "diff", "--name-only", "--cached", "--", "scripts", "biome.json").split()),
     ["biome.json", "scripts/check.sh"])
s.eq("nothing else is unstaged", helpers.git(wt, "diff", "--name-only").split(), [])
s.ok("what is left is listed (the purged citation)", ".planning/STATE.md" in r.stdout and "left alone" in r.stdout, r.stdout[-400:])

# the commit, and the proof that everything the conversion removed comes back from the commit before it
helpers.git(wt, "commit", "-q", "-m", "chore(fwx): migrate GSD .planning/ to .fwx/ (base %s)" % base)
lost, wrong = [], []
for f in gone:
    got = show_bytes(wt, base, f["src"])
    if got is None:
        lost.append(f["src"])
    elif not os.path.islink(os.path.join(repo, f["src"])) and got != before_bytes[f["src"]]:
        wrong.append(f["src"])
s.ok("%d purged or backlog files, each recoverable with `git show %s:<path>`: missing %s" % (len(gone), base[:12], lost[:3]), gone and not lost)
s.ok("... with the same bytes it had before apply: differing %s" % wrong[:3], not wrong)

# leftovers: dry run before the merge refuses; after the merge it moves the ignored files and deletes the machine state
refusal("leftovers before the conversion is merged", repo, ["leftovers"], "still tracked", (repo,))
s.eq("merging the conversion into the main checkout", helpers.git(repo, "merge", "--ff-only", "-q", "fwx-migrate-gsd"), "")
st0, sn0 = porcelain(repo), strict(repo)
r = run(repo, "leftovers")
s.eq("leftovers (dry run) exits 0", r.returncode, 0)
s.ok("... lists what it would do", ".fwx/milestones/v2/phases/01-a/fonts/a.woff" in r.stdout and "delete .planning/state.json" in r.stdout, r.stdout)
s.ok("... and writes nothing (paths, sizes, mtimes, git status)", strict(repo) == sn0 and porcelain(repo) == st0)
before_lines = porcelain(repo).splitlines()
ign0 = [l for l in before_lines if l.startswith("!!")]


def mess(label, make, argv, want):
    """Make a mess in the main checkout, see leftovers refuse with nothing changed (the caller cleans up)."""
    make()
    refusal(label, repo, argv, want, (repo,))


mess("leftovers with a destination in the way", lambda: helpers.write(repo, ".fwx/ref/a.txt", "in the way\n"), ["leftovers", "--apply"], ".fwx/ref/a.txt exists")
shutil.rmtree(os.path.join(repo, ".fwx/ref"))
mess("leftovers for a phase with no folder under .fwx/", lambda: helpers.write(repo, ".planning/phases/09-zzz/x.txt", "x\n"), ["leftovers", "--apply"], "09-zzz")
mfile = os.path.join(HOME, "map9.txt")
with open(mfile, "w") as fh:
    fh.write("9 v2\n")
r = run(repo, "leftovers", "--milestone-map", mfile)
s.ok("... --milestone-map places it (dry run)", r.returncode == 0 and ".fwx/milestones/v2/phases/09-zzz/x.txt" in r.stdout, r.stdout + r.stderr)
os.remove(os.path.join(repo, ".planning/phases/09-zzz/x.txt"))
os.rmdir(os.path.join(repo, ".planning/phases/09-zzz"))
gi_now = open(os.path.join(repo, ".gitignore"), encoding="utf-8").read()
# control: leftovers without its git check-ignore moves an ignored folder to where git shows it as untracked:
#   "FAIL: leftovers with the .fwx twin of the .gitignore line missing: exits 2: got 0, want 2"
helpers.write(repo, ".gitignore", "node_modules/\n/.planning/phases/01-a/fonts/\n%s\n" % OLD)
helpers.git(repo, "commit", "-q", "-am", "drop the twin lines")
refusal("leftovers with the .fwx twin of the .gitignore line missing", repo, ["leftovers", "--apply"], "would stop being ignored", (repo,))
helpers.write(repo, ".gitignore", gi_now)
helpers.git(repo, "commit", "-q", "-am", "twin lines back")
r = run(repo, "leftovers", "--apply")
s.eq("leftovers --apply exits 0", r.returncode, 0)
s.eq("fonts/ ends up in .fwx/milestones/v2/phases/01-a/fonts/", rd(os.path.join(repo, ".fwx/milestones/v2/phases/01-a/fonts/a.woff")), "font")
s.eq("the workstream's private/ ends up in .fwx/subprojects/ws1/private/", rd(os.path.join(repo, ".fwx/subprojects/ws1/private/notes.md")), "# private\n")
s.ok("state.json is deleted", not os.path.exists(os.path.join(repo, ".planning/state.json")))
trash = [p for p in Path(helpers.git(repo, "rev-parse", "--absolute-git-dir").strip(), "fwx", "migrate-gsd", "deleted").rglob("state.json")]
s.ok("... and a copy of it is in the git dir, not lost: %s" % trash, len(trash) == 1 and trash[0].read_text() == "{}\n")
s.ok("a nested repository goes whole, its .git with it", os.path.isdir(os.path.join(repo, ".fwx/ref/.git")) and os.path.isfile(os.path.join(repo, ".fwx/ref/b/c.txt")))
s.ok(".planning/ is gone", not os.path.lexists(os.path.join(repo, ".planning")))
after_lines = porcelain(repo).splitlines()
s.eq("the number of ignored entries is the same", len([l for l in after_lines if l.startswith("!!")]), len(ign0))
s.eq("git status --porcelain shows nothing new: only the nested repository, moved", [l for l in after_lines if not l.startswith("!!")], ["?? .fwx/ref/"])
r = run(repo, "leftovers", "--apply")
s.ok("a second leftovers has nothing to do and exits 0", r.returncode == 0 and "nothing to do" in r.stdout, r.stdout + r.stderr)

# ---- U2 3: a failure in the middle -------------------------------------------------------------------------------------------
orig_move = mg.move_file


def failing_after(n, exc=OSError("simulated: no space left on device")):
    calls = []

    def move(job, src, dest):
        calls.append(src)
        if len(calls) > n:
            raise exc
        return orig_move(job, src, dest)
    return move


def midway(label, patches, want):
    """Fail apply in the middle and see the repository back as it was (files, index, status), the marker gone, exit 1."""
    repo_, wt_ = world()
    c0, i0, s0, h0 = content(wt_), index_of(wt_), porcelain(wt_), helpers.git(wt_, "rev-parse", "HEAD")
    rc, out, err = inproc(wt_, ["apply"], patches)
    s.eq("%s: exits 1" % label, rc, 1)
    s.ok("%s: says %r and that the repository is back" % (label, want), want in err and "back as it was" in err, err[-400:])
    s.eq("%s: every file (names and bytes, folders) is as before" % label, content(wt_), c0)
    s.eq("%s: the index is as before" % label, index_of(wt_), i0)
    s.eq("%s: git status --porcelain --ignored is as before" % label, porcelain(wt_), s0)
    s.eq("%s: HEAD did not move" % label, helpers.git(wt_, "rev-parse", "HEAD"), h0)
    s.ok("%s: no marker left in the git dir" % label, not os.path.exists(os.path.join(helpers.git(wt_, "rev-parse", "--absolute-git-dir").strip(), mg.MARKER)))
    rc2, out2, err2 = inproc(wt_, ["apply"])
    s.ok("%s: and a plain apply afterwards works (exit %d)" % (label, rc2), rc2 == 0, err2[-300:])


midway("a failure after 5 moves", [(mg, "move_file", failing_after(5))], "simulated: no space left")
midway("a failure writing the generated files (after every move and removal)",
       [(mg, "step_generate", lambda job: (_ for _ in ()).throw(OSError("simulated: cannot write")))], "simulated: cannot write")
midway("a failure in the .gitignore step", [(mg, "step_gitignore", lambda job: (_ for _ in ()).throw(RuntimeError("simulated")))], "simulated")


def text_copy(job, src, dest):
    """The plan's control: a mover that reads text and writes it back (CRLF and the binary file change)."""
    if os.path.islink(os.path.join(job.repo, src)):
        return orig_move(job, src, dest)
    mg.mkdirs(job, os.path.dirname(os.path.join(job.repo, dest)))
    with open(os.path.join(job.repo, src), encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    with open(os.path.join(job.repo, dest), "w", encoding="utf-8") as fh:
        fh.write(text)
    mg._git(job.repo, "--literal-pathspecs", "rm", "-q", "--cached", "--", src)
    mg._git(job.repo, "--literal-pathspecs", "add", "--", dest)
    os.remove(os.path.join(job.repo, src))


# control: a check that does not compare the blob lets this through (apply exits 0): "FAIL: a mover that copies as text: exits 1: got 0, want 1"
midway("a mover that copies as text (the check after the work)", [(mg, "move_file", text_copy)], "blob changed: .planning/phases/01-a/01-CONTEXT.md")

# a real error of the file system, in the middle: a folder the second scope's files go into cannot be written
repo, wt = world()
os.makedirs(os.path.join(wt, ".fwx/subprojects"))
os.chmod(os.path.join(wt, ".fwx/subprojects"), 0o500)
c0, i0, s0 = content(wt), index_of(wt), porcelain(wt)
if os.geteuid() == 0:
    print("NOT RUN: the unwritable-folder case needs a user that is not root (the monkeypatched cases above cover the same path)")
else:
    rc, out, err = inproc(wt, ["apply"])
    s.eq("an unwritable destination folder in the middle: exits 1", rc, 1)
    s.ok("... says the repository is back as it was", "back as it was" in err and "Permission" in err, err[-300:])
    os.chmod(os.path.join(wt, ".fwx/subprojects"), 0o700)
    s.eq("... files, index and status are as before", (content(wt), index_of(wt), porcelain(wt)), (c0, i0, s0))
os.chmod(os.path.join(wt, ".fwx/subprojects"), 0o700)

# a rollback that itself fails, and a process killed in the middle: a state the next run detects, and the printed commands undo it
repo, wt = world()
c0, i0, s0 = content(wt), index_of(wt), porcelain(wt)
rc, out, err = inproc(wt, ["apply"], [(mg, "step_generate", lambda job: (_ for _ in ()).throw(RuntimeError("simulated"))),
                                     (mg, "rollback", lambda job: ["simulated: rollback failed"])])
s.eq("a rollback that fails: exits 1", rc, 1)
s.ok("... says it could NOT put the repository back, and names the marker", "could NOT be put back" in err and mg.MARKER in err, err[-400:])
cmds = [l.strip() for l in err.splitlines() if l.strip().startswith("git -C")]
s.eq("... and prints the two commands that undo it", len(cmds), 2)
r = refusal("apply on a repository an earlier apply left half done", wt, ["apply"], "stopped in the middle", (wt,))
for c in cmds:
    subprocess.run(c, shell=True, check=True, capture_output=True, env=helpers.clean_env(**ENV))
s.eq("the printed commands put the files, the index and the status back", (content(wt), index_of(wt), porcelain(wt)), (c0, i0, s0))
rc, out, err = inproc(wt, ["apply"])
s.ok("... and apply runs again (the old marker does not block a repository that is clean)", rc == 0, err[-300:])

repo, wt = world()
c0, i0, s0 = content(wt), index_of(wt), porcelain(wt)
prog = ("import os, sys; sys.dont_write_bytecode = True; sys.path.insert(0, %r)\n"
        "import fwx.commands.migrate_gsd as mg\n"
        "mg.step_generate = lambda job: os._exit(137)\n"
        "sys.exit(mg.main(['apply']))\n" % os.path.join(helpers.ROOT, "lib"))
k = subprocess.run([sys.executable, "-c", prog], cwd=wt, env=helpers.clean_env(**ENV), capture_output=True, text=True)
s.eq("a process killed after the moves and removals: exit 137", k.returncode, 137)
s.ok("... leaves the repository half converted (this is what the marker is for)", content(wt) != c0 and os.path.exists(os.path.join(helpers.git(wt, "rev-parse", "--absolute-git-dir").strip(), mg.MARKER)))
r = refusal("apply on the repository a killed apply left", wt, ["apply"], "stopped in the middle", (wt,))
cmds = [l.strip() for l in r.stderr.splitlines() if l.strip().startswith("git -C")]
for c in cmds:
    subprocess.run(c, shell=True, check=True, capture_output=True, env=helpers.clean_env(**ENV))
s.eq("... and the two commands it printed put everything back", (content(wt), index_of(wt), porcelain(wt)), (c0, i0, s0))

# leftovers: a failure in the middle puts the moves back
repo, wt = world()
run(wt, "apply", "--close", "1")
helpers.git(wt, "commit", "-q", "-m", "convert")
helpers.git(repo, "merge", "--ff-only", "-q", "fwx-migrate-gsd")
c0, s0 = content(repo), porcelain(repo)
orig_rename, calls = mg.Journal2.rename, []


def rename_fails_third(self, s_, d_):
    calls.append(s_)
    if len(calls) == 3:
        raise OSError("simulated: cannot move")
    return orig_rename(self, s_, d_)


rc, out, err = inproc(repo, ["leftovers", "--apply"], [(mg.Journal2, "rename", rename_fails_third)])
s.eq("leftovers failing on its third move: exits 1", rc, 1)
s.ok("... says everything moved was put back", "put back" in err and "simulated: cannot move" in err, err[-300:])
s.eq("... every file, ignored ones included, is where it was", content(repo), c0)
s.eq("... and git status is the same", porcelain(repo), s0)

# ---- U2 4: re-entrance ---------------------------------------------------------------------------------------------------------
repo, wt = world()
run(wt, "apply")
helpers.git(wt, "commit", "-q", "-m", "convert")
mil0 = open(os.path.join(wt, ".fwx/milestones/v2/MILESTONE.md"), "rb").read()
aud0 = open(os.path.join(wt, ".fwx/milestones/v2/phases/02.1-b/audit.tsv"), "rb").read()
wx = helpers.add_worktree(repo, "extra")
helpers.write(wx, ".planning/extra/n.md", "# new\n")
helpers.write(wx, ".planning/phases/02.1-b/02.1-02-CONTEXT.md", "# context\n")
helpers.git(wx, "add", "-A")
helpers.git(wx, "commit", "-q", "-m", "a branch that adds to .planning/")
helpers.git(wt, "-c", "merge.directoryRenames=false", "merge", "--no-edit", "-q", "extra")
r = run(wt, "apply")
s.eq("apply after a merge that brought new files exits 0", r.returncode, 0)
staged = sorted(helpers.git(wt, "diff", "--cached", "--name-status").splitlines())
s.eq("... it converted only those two files", staged, sorted([
    "R100\t.planning/extra/n.md\t.fwx/extra/n.md",
    "R100\t.planning/phases/02.1-b/02.1-02-CONTEXT.md\t.fwx/milestones/v2/phases/02.1-b/02.1-02-CONTEXT.md"]))
s.eq("... MILESTONE.md is as it was", open(os.path.join(wt, ".fwx/milestones/v2/MILESTONE.md"), "rb").read(), mil0)
s.eq("... and the stage rows are as they were", open(os.path.join(wt, ".fwx/milestones/v2/phases/02.1-b/audit.tsv"), "rb").read(), aud0)
helpers.git(wt, "commit", "-q", "-m", "convert the rest")
helpers.write(wt, ".planning/extra/n.md", "# the same destination again\n")
helpers.git(wt, "add", ".planning/extra/n.md")
helpers.git(wt, "commit", "-q", "-m", "a file for a destination that exists")
refusal("a collision after a re-entrant apply", wt, ["apply"], ".fwx/extra/n.md exists", (wt, os.path.join(repo, ".git")))

# ---- U2 5: refs --rewrite and --prefix, the refusals and the failure in the middle -----------------------------------------------
repo, wt = world()
run(wt, "apply", "--close", "1")
base = helpers.git(wt, "rev-parse", "HEAD").strip()
helpers.git(wt, "commit", "-q", "-m", "convert")
sh0 = open(os.path.join(wt, "scripts/check.sh"), "rb").read()


def refs_refusal(label, args, want, mutate=None):
    if mutate:
        mutate()
    c0, i0, s0 = content(wt), index_of(wt), porcelain(wt)
    r = run(wt, "refs", "--base", base, *args)
    s.eq("%s: exits 2" % label, r.returncode, 2)
    s.ok("%s: says %r" % (label, want), want in r.stderr, r.stderr[-300:])
    s.eq("%s: nothing was written (files, index, status)" % label, (content(wt), index_of(wt), porcelain(wt)), (c0, i0, s0))


refs_refusal("--rewrite a file that does not exist", ["--rewrite", "scripts/check.sh", "scripts/nope.sh"], "not a tracked file")
refs_refusal("--rewrite a file named for --prefix too", ["--rewrite", "biome.json", "--prefix", "biome.json"], "both --rewrite and --prefix")
refs_refusal("--rewrite a file outside the repository", ["--rewrite", "../outside.txt"], "outside the repository")
refs_refusal("--rewrite a file inside .fwx/", ["--rewrite", ".fwx/PROJECT.md"], "inside .planning/ or .fwx/")
wbytes(wt, "binary.dat", b"\xff\xfe.planning/x\n")
helpers.git(wt, "add", "binary.dat")
helpers.git(wt, "commit", "-q", "-m", "a file that is not UTF-8")
refs_refusal("--rewrite a file that is not UTF-8", ["--rewrite", "binary.dat"], "not UTF-8")
refs_refusal("--prefix a file with an unstaged edit", ["--prefix", "biome.json"], "not staged", lambda: helpers.write(wt, "biome.json", '{"files": {"ignore": ["!.planning", "x"]}}\n'))
helpers.git(wt, "checkout", "-q", "--", "biome.json")

mp = os.path.join(HOME, "wrong-map.txt")
with open(mp, "w") as fh:
    fh.write("1 v3\n")   # apply put 01-a in v2: a destination that is not there
r = run(wt, "refs", "--base", base, "--milestone-map", mp, "--rewrite", "scripts/check.sh")
s.eq("--rewrite with a map that puts a phase where apply did not: exits 0", r.returncode, 0)
s.eq("... changes nothing whose new path does not exist", open(os.path.join(wt, "scripts/check.sh"), "rb").read(), sh0)
s.ok("... and says why", "does not exist" in r.stdout, r.stdout[-400:])

helpers.write(wt, "other.sh", "cat .planning/phases/01-a/01-01-SUMMARY.md\n")
helpers.git(wt, "add", "other.sh")
helpers.git(wt, "commit", "-q", "-m", "a second script")
o0 = open(os.path.join(wt, "other.sh"), "rb").read()
orig_write, wcalls = mg._write_bytes, []


def write_fails_second(path, data):
    wcalls.append(path)
    if len(wcalls) == 2:
        raise OSError("simulated: read-only file")
    return orig_write(path, data)


c0, i0, s0 = content(wt), index_of(wt), porcelain(wt)
rc, out, err = inproc(wt, ["refs", "--base", base, "--rewrite", "other.sh", "scripts/check.sh"], [(mg, "_write_bytes", write_fails_second)])
s.eq("refs --rewrite failing on its second file: exits 1", rc, 1)
s.ok("... says the files already rewritten were put back", "put back" in err, err[-300:])
s.eq("... both files have their old bytes, nothing is staged", (content(wt), index_of(wt), porcelain(wt)), (c0, i0, s0))

s.done()
