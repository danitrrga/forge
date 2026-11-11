#!/usr/bin/env python3
"""`fwx migrate-gsd plan` and `refs`: what the conversion of a GSD `.planning/` to `.fwx/` would do, read only.

Every case builds a toy repository in a temp dir (with its `origin` beside it), runs bin/fwx on it and reads the text or the
`--json` it prints. The toy `.planning/` is described next to `build()`. HOME, XDG_* and git's global config are isolated, and
every temp dir is removed by helpers.cleanup() also when a check fails.

Cases (the plan's twelve, then the ones the code added):
  1 plan writes nothing   2 classification   3 milestone of each phase   4 closed or open   5 phases only in the ROADMAP
  6 scopes   7 backlog   8 `.gitignore`   9 refs   10 no `.planning/`   11 an emptied phase keeps its `.gitkeep`   12 ahead
  extras: unmerged branches, the remote without its credentials, two files for one destination, the write half refused

Seen red before the command existed (bin/fwx has no `migrate-gsd`):
  FAIL: plan (text) exits 0: got 2, want 0
  (every later check fails the same way)

Controls, each seen red on a copy of this plugin with one rule of lib/fwx/commands/migrate_gsd.py changed; the FAIL line
the case printed is quoted (filled in below from the run):
CONTROLS
"""
import json
import os
import re
import subprocess
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
        "scripts/check.sh": "#!/bin/sh\ncat .planning/phases/01-a/01-01-SUMMARY.md\n# the old state lived in .planning/STATE.md\n",
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
s.eq("untracked and ignored files are in the list", sorted(f["src"] for f in d["files"] if not f["tracked"]),
     sorted([".planning/phases/01-a/fonts/a.woff", ".planning/state.json", ".planning/workstreams/ws1/private/notes.md"]))


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


WS = ".fwx/subprojects/ws1/milestones/"
for name in ("01-a", "02.1-b", "02.5-c"):
    phase(D2 + name, "milestone (STATE says v2.0)", "milestone", "v2")
for dest, ms in ((WS + "v1/phases/01-one", "v1"), (WS + "v2/phases/03-two", "v2"), (WS + "v2/phases/05-three", "v2 (v2.1 is in v2)"),
                 (WS + "v3/phases/08-four", "v3")):
    s.ok("phase %s milestone: got %s, want %s" % (os.path.basename(dest), (PH.get(dest) or {}).get("milestone"), ms.split()[0]),
         dest in PH and PH[dest]["milestone"] == ms.split()[0])
s.eq("ws1 has four phases, none made up", sorted(k for k in PH if k.startswith(".fwx/subprojects/ws1")), sorted([
    WS + "v1/phases/01-one", WS + "v2/phases/03-two", WS + "v2/phases/05-three", WS + "v3/phases/08-four"]))
s.eq("ws1's ROADMAP goes to its current milestone", F[".planning/workstreams/ws1/ROADMAP.md"]["dest"], WS + "v3/ROADMAP.md")
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
s.eq("02.1-b signals", PH[D2 + "02.1-b"]["signals"], {"checklist": True, "pairing": False})
s.eq("01-a signals", PH[D2 + "01-a"]["signals"], {"checklist": False, "pairing": True})
s.eq("02.5-c signals (no plan is not a paired phase)", PH[D2 + "02.5-c"]["signals"], {"checklist": False, "pairing": False})
phase(WS + "v1/phases/01-one", "closed: no boxes, so the pairing decides", "closed", True)
phase(WS + "v2/phases/05-three", "open: no boxes, a PLAN without SUMMARY", "closed", False)
s.eq("a phase without boxes has checklist null", PH[WS + "v1/phases/01-one"]["signals"]["checklist"], None)
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
for args in (["refs", "--base", base, "--rewrite", "scripts/check.sh"], ["refs", "--base", base, "--prefix", "biome.json"], ["apply"], ["leftovers"]):
    r = run(repo, *args)
    s.ok("the write half `%s` is refused (exit 2, says not built)" % " ".join(args[:1] + args[2:3]), r.returncode == 2 and "not built yet" in r.stderr, r.stderr)

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
s.eq("ahead is null when there is no tracking branch", dn and dn["ahead"], None)
s.eq("ahead is null and remote null without a remote", [(x["ahead"], x["remote"]) for x in [plan_json(helpers.toy_repo({".planning/PROJECT.md": "# p\n"}))[1]]], [(None, None)])
clash = helpers.toy_repo({".planning/PROJECT.md": "# p\n", ".planning/milestones/v1.0-ROADMAP.md": "# a\n",
                          ".planning/milestones/v1/v1.0-ROADMAP.md": "# b\n"})
r = run(clash, "plan")
s.eq("two files for one destination exit 2", r.returncode, 2)
s.ok("... naming the destination", ".fwx/milestones/v1/v1.0-ROADMAP.md" in r.stderr, r.stderr)

s.done()
