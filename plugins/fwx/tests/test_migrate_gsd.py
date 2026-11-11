#!/usr/bin/env python3
"""`fwx migrate-gsd`: what the conversion of a GSD `.planning/` to `.fwx/` would do (unit 1, `plan` and `refs`, read only) and
doing it (unit 2, `apply`, `refs --rewrite|--prefix`, `leftovers`; its cases are the second half of this file, from "Unit 2").

Every case builds a toy repository in a temp dir (with its `origin` beside it), runs bin/fwx on it and reads the text or the
`--json` it prints. The toy `.planning/` is described next to `build()`. HOME, XDG_* and git's global config are isolated, and
every temp dir is removed by helpers.cleanup() also when a check fails.

Cases (the plan's twelve, then what the code added):
  1 plan writes nothing   2 classification   3 milestone of each phase   4 closed or open   5 phases only in the ROADMAP
  6 scopes   7 backlog   8 `.gitignore`   9 refs   10 no `.planning/`   11 an emptied phase keeps its `.gitkeep`   12 ahead
  extras: unmerged branches, the remote without its credentials, a repository nested in `.planning/`, two files for one
  destination, a folder cited as a reference, a flag with no file

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

Unit 2 (the write half). Cases: the refusals of `apply`, each with exit 2, its message and the repository unchanged (every path
with size and mtime, `.git` included, and `git status --porcelain --ignored`); `apply` in a worktree (blob of each kept file,
CRLF, binary and symlink included; each purged file gone; `state.phases`, `state.last_stage`; MILESTONE.md; nothing written in
the main checkout); `refs --rewrite|--prefix` and its refusals; the commit and the proof that every removed file comes back
with `git show <base>:<path>`; `leftovers` (dry run, refusals, `--apply`); a failure in the middle of `apply`, of a rollback,
of `refs` and of `leftovers`; a process killed in the middle; re-entrance after a merge.
Seen red before the write half existed (a copy of this plugin with unit 1's migrate_gsd.py):
  FAIL: apply on the default branch: stderr says 'default branch': fwx migrate-gsd: fwx migrate-gsd apply is not built yet ...
Controls, each a copy of this plugin with one rule of migrate_gsd.py changed (the first FAIL line it printed, 390 checks on the
good code):
  - the collision check removed and `git mv -f`: "FAIL: apply with a destination that exists (.fwx/PROJECT.md): exits 2: got 0,
    want 2" and "FAIL: ... destination existed and was overwritten: got '# Project\n', want 'mine\n'"
  - the default-branch refusal removed: "FAIL: apply on the default branch: exits 2: got 0, want 2"
  - the clean-tree refusal removed: "FAIL: apply with .planning/phases/01-a/01-CONTEXT.md modified: exits 2: got 1, want 2" (the
    rollback then restores the file to the base, which is the owner's edit lost: this is why the refusal is there)
  - the blob check removed (the text-copying mover of the plan): "FAIL: a mover that copies as text (the check after the work):
    exits 1: got 0, want 1"
  - the purged-file check removed: "FAIL: a removal step that removes nothing (the check after the work): says 'purged file still
    there' and that the repository is back"
  - the rollback not run: "FAIL: a failure after 5 moves: every file (names and bytes, folders) is as before: got {...}"
  - the marker not written: "FAIL: apply on a repository an earlier apply left half done: stderr says 'stopped in the middle'"
  - nothing to convert but untracked files, the refusal removed: "FAIL: apply with only untracked files in .planning/: exits 2:
    got 0, want 2"
  - the `.gitignore` twins not written: "FAIL: .gitignore: each line that names .planning/ has its twin right under it, the old line
    stays: got ['node_modules/', '/.planning/phases/01-a/fonts/', '/.planning/workstreams/*/private/'], want [...]"
  - no pin of the phases that already exist under `.fwx/` (re-entrance): "FAIL: ... it converted only those two files: got
    ['A\t.fwx/milestones/v1/MILESTONE.md', 'M\t.gitignore', ..., '.../v1/phases/02.1-b/02.1-02-CONTEXT.md'], want [...v2...]"
  - `--rewrite` that swaps the prefix in every path: "FAIL: --rewrite changes the moved path exactly, leaves the one a purged file
    had ...: got [..., '# the old state lived in .fwx/STATE.md', ...]"
  - `--rewrite` without looking for the new path: "FAIL: ... changes nothing whose new path does not exist: got b'...v3...'"
  - the unstaged-edit refusal of refs removed: "FAIL: --prefix a file with an unstaged edit: exits 2: got 0, want 2"
  - leftovers without its `git check-ignore` refusal: "FAIL: leftovers with the .fwx twin of the .gitignore line missing: exits
    2: got 1, want 2" (its own check after the moves still catches it, and puts the moves back)
  - leftovers copying nothing before it deletes: "FAIL: ... and a copy of it is in the git dir, not lost: []"
  - a nested repository moved file by file: "FAIL: ... and it is still a repository, with its empty folders: <path>/.git"

Review fixes (an independent data-loss review, F1..F15; each scenario is a fixture of the second half of this file). The red each
gave on the code before the fix, then the first FAIL line of a copy of the plugin with that rule removed:
  F1 the rollback restored the whole tree: "FAIL: F1 a tracked file edited while apply ran keeps its edit after a rollback: got
     'ahead\n', want 'ahead\nedited while apply ran\n'"; with `-- .` put back: the same line; with the foreign-change stop removed:
     "FAIL: F1 a file the owner wrote at a path apply removed is not overwritten by the rollback"
  F2 an untracked audit file at a closed phase's destination: "FAIL: F2 apply with an untracked audit file ...: exits 2: got 0,
     want 2"; the rule removed: "... exits 2: got 1, want 2"
  F3 the printed commands deleted the owner's untracked .fwx/mynotes.md: "FAIL: F3 the printed commands leave the owner's untracked
     .fwx/mynotes.md: got None, want "the owner's notes\n""; a blanket `git clean` printed again: "FAIL: F3 after a kill the next
     apply prints commands that name only what apply made (no blanket clean)"
  F4 assume-unchanged / skip-worktree: "FAIL: F4 apply with an assume-unchanged file under .planning/: exits 2: got 0, want 2"
  F5 a stale marker told the owner to restore over a dirty tree: "FAIL: F5 a stale marker and a dirty tree: 'not clean', and no
     advice to restore anything"
  F6 a relative symlink that would dangle: "FAIL: F6 apply with relative symlinks that would dangle: exits 2: got 0, want 2"
     (the plan's appendix keeps every blob byte for byte, so a link is refused, never rewritten); in `leftovers` the same with
     "FAIL: leftovers with a leftover symlink that the move would leave dangling: exits 2: got 0, want 2"
  F7 `--prefix` and `--rewrite` on a path that is not at the root: "FAIL: F7 --prefix changes the path .planning only where it is a
     path of its own: ["'cp .planning.bak backup/' -> 'cp .fwx.bak backup/' ..."; "FAIL: F7 --rewrite does not take docs/.planning/..."
  F8 a file name that is not UTF-8: "FAIL: apply said: ... git mv failed (128): fatal: bad source, source=.planning/phases/01-a/caf?.md"
  F9 the base of each run written down: "FAIL: ... the tag points at the base: got '', want '<sha>'", "FAIL: F9 a re-entrant apply
     appends its base ..." and, with the commit message file empty, "FAIL: ... the message file holds the base, the counts and the
     recovery command"
  F10 a .gitignore line .planning/ whose twin ignores .fwx/: "FAIL: F10 ...: exits 2: got 1, want 2"
  F11 a hook of the repository: "FAIL: ... and the hook did not run (once per `git mv` otherwise)" with the hook switch removed
  F14 apply in a main checkout: "FAIL: F14 apply in the main checkout on a branch that is not the default one: exits 2: got 0,
      want 2"; the default-branch test now cannot be satisfied by that refusal ("FAIL: apply on the default branch: stderr says
      'default branch': ... is not a linked worktree")
  F15 an untracked file moved to an ignored place: "FAIL: F15 leftovers with an untracked file whose destination is ignored ...:
      exits 2: got 0, want 2"
  archive (leftovers): "FAIL: leftovers --apply exits 0 (a name that is not UTF-8 included): got 1, want 0" before it existed; with
      the files not added to the tar: "FAIL: leftovers --apply exits 0: got 1, want 0" (it reads the tar back before it moves
      anything); with no tar: "FAIL: ... and the archive is a file that exists"
  controls the first review found missing: detached HEAD ("exits 2: got 0, want 2"), a submodule in `.planning/` (same), an ignored
  destination ("exits 2: got 1, want 2"), a destination under a file ("exits 2: got 1, want 2"), and a rollback that is not
  run or a marker that is not written (above). The refusals now compare the content hash of every path, not size and mtime: "(the
  size and mtime snapshot of unit 1 cannot tell a same-size edit that keeps the mtime)" and "the snapshot of the refusals ... tells it".
Second pass of the review (red on 525fadc, then the control with the rule removed):
  F6 links to folders: "FAIL: F6 a link to a folder (the reviewer's link-to-dir): refused is False, want True" and "FAIL: F6 apply
     with a symbolic link to a folder that would dangle: exits 2: got 0, want 2"; a link to a folder that moves with it, an
     absolute link and a link that was dangling are not refused (table test of link_problems and one apply)
  N1 a file that changed after it was archived: "FAIL: N1 a file changed after it was archived is not deleted: got None, want
     '{}\nwritten after the archive\n'" (the change is injected by replacing write_archive, no sleep); with the digest check off, the same
  N2 an audit file at another stage: "FAIL: N2 plan says apply would refuse, names the stage and how to go on" and "FAIL: N2 apply
     with an audit file at the stage discuss ...: exits 2: got 1, want 2"; each half has its own control
  an archive folder that cannot be created: a traceback (PermissionError) instead of "FAIL: ... exit 2, one line, no traceback"
  Not controlled: the check in `rollback` that git status shows nothing of apply's afterwards (a second line of defence behind the
  removal of each path), and F13, F16, F17 (see the PR).
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
    s.ok("`%s` with no file exits 2 and says it needs one" % " ".join(args[3:]), r.returncode == 2 and "needs at least one file" in r.stderr, r.stderr)

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

def _lenient_git(cwd, *args):
    """helpers.git, reading git's output with surrogateescape: a toy repository now holds a file name that is not UTF-8."""
    r = subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "init.defaultBranch=master",
                        "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "maintenance.auto=false", "-c", "gc.auto=0"]
                       + list(args), env=helpers.clean_env(), capture_output=True, text=True, errors="surrogateescape")
    if r.returncode:
        raise RuntimeError("git %s failed (%d): %s" % (" ".join(args), r.returncode, r.stderr.strip()))
    return r.stdout


helpers.git = _lenient_git
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
    p = os.path.join(os.fsencode(root), os.fsencode(rel))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def build2(**kw):
    repo, origin = build(**kw)
    wbytes(repo, ".planning/phases/01-a/01-CONTEXT.md", CRLF)               # a CRLF file: a text copy would change it
    wbytes(repo, ".planning/knowledge/blob.bin", BLOB)                      # bytes that are not UTF-8, unknown to GSD: kept
    os.symlink("01-CONTEXT.md", os.path.join(repo, ".planning/phases/01-a/01-context-link"))  # a tracked symlink
    wbytes(repo, b".planning/phases/01-a/caf\xe9.md", b"odd name\n")             # a tracked file whose NAME is not UTF-8
    helpers.git(repo, "add", "--", ".planning/phases/01-a/01-CONTEXT.md", ".planning/knowledge/blob.bin", ".planning/phases/01-a/01-context-link",
                os.fsdecode(b".planning/phases/01-a/caf\xe9.md"))
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


def snap2(root):
    """Every path of root with its size, its modification time and, for a file, a hash of its bytes (for a link, its target)."""
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            st = os.lstat(p)
            if os.path.islink(p):
                h = os.readlink(p)
            elif os.path.isfile(p):
                with open(p, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
            else:
                h = None
            seen[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns, h)
    return seen


def strict(*roots):
    out = {}
    for i, r in enumerate(roots):
        out.update({(i, p): v for p, v in snap2(r).items()})
    return out


def undo_cmds(text):
    """The commands a message prints for the owner: indented by two spaces and starting with `git -C` or `cd`."""
    return [l[2:] for l in text.splitlines() if l.startswith("  ") and l[2:].startswith(("git -C", "cd "))]


def run_cmds(cmds):
    for c in cmds:
        subprocess.run(c, shell=True, check=True, capture_output=True, env=helpers.clean_env(**ENV))


def tryg(cwd, *args):
    """A git command whose failure is a failed check, not a crash: its output, or '' when it fails."""
    try:
        return helpers.git(cwd, *args)
    except RuntimeError:
        return ""


def marker_of(wt_):
    return os.path.join(helpers.git(wt_, "rev-parse", "--absolute-git-dir").strip(), mg.MARKER)


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
if r.returncode != 0:
    s.fails.append("FAIL: apply said: " + r.stderr.strip()[:300])
    s.done()    # nothing after this can be read from a conversion that did not happen
s.ok("apply says what it did and where the base is", base in r.stdout and "nothing committed" in r.stdout, r.stdout[:400] + r.stderr[:300])
s.eq("apply commits nothing: HEAD is still the base", helpers.git(wt, "rev-parse", "HEAD").strip(), base)
keeps = [f for f in D["files"] if f["tracked"] and f["action"] == "keep"]
gone = [f for f in D["files"] if f["tracked"] and f["action"] in ("purge", "backlog")]
s.ok("the toy has kept, purged and backlog files to look at (%d, %d)" % (len(keeps), len(gone)), len(keeps) > 10 and len(gone) > 10)
idx = {}
for line in [l for l in helpers.git(wt, "ls-files", "-s", "-z").split("\0") if l]:   # -z: git quotes a name that is not UTF-8 otherwise
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
    src_lines = fh.read().splitlines()
# control (grep run by hand on a copy with the name in a string): "FAIL: no line of migrate_gsd.py names the audit file: ... got [N]"
s.eq("no line of migrate_gsd.py names the audit file: state.append_audit is its only writer",
     [n for n, line in enumerate(src_lines, 1) if "audit.tsv" in line], [])
s.eq("apply passes the paths of its own checkout: nothing in migrate_gsd.py calls plan_root or resolve (3.2)",
     [n for n, line in enumerate(src_lines, 1) if re.search(r"\b(plan_root|state\.resolve|config\.main_checkout)\(", line)], [])

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
helpers.git(repo, "commit", "-q", "--allow-empty", "-am", "drop the twin lines")
refusal("leftovers with the .fwx twin of the .gitignore line missing", repo, ["leftovers", "--apply"], "would stop being ignored", (repo,))
helpers.write(repo, ".gitignore", gi_now)
helpers.git(repo, "commit", "-q", "--allow-empty", "-am", "twin lines back")
r = run(repo, "leftovers", "--apply")
s.eq("leftovers --apply exits 0", r.returncode, 0)
s.eq("fonts/ ends up in .fwx/milestones/v2/phases/01-a/fonts/", rd(os.path.join(repo, ".fwx/milestones/v2/phases/01-a/fonts/a.woff")), "font")
s.eq("the workstream's private/ ends up in .fwx/subprojects/ws1/private/", rd(os.path.join(repo, ".fwx/subprojects/ws1/private/notes.md")), "# private\n")
s.ok("state.json is deleted", not os.path.exists(os.path.join(repo, ".planning/state.json")))
s.ok("a nested repository goes whole, its .git with it", os.path.isdir(os.path.join(repo, ".fwx/ref/.git")) and os.path.isfile(os.path.join(repo, ".fwx/ref/b/c.txt")))
# control (the nested repository moved file by file, which drops its empty folders: refs/, objects/):
#   "FAIL: ... and it is still a repository, with its empty folders: not a git repository ..."
nr = subprocess.run(["git", "-C", os.path.join(repo, ".fwx/ref"), "rev-parse", "--git-dir"], capture_output=True, text=True, env=helpers.clean_env(**ENV))
s.ok("... and it is still a repository, with its empty folders: %s" % (nr.stdout + nr.stderr).strip(), nr.returncode == 0 and nr.stdout.strip() == ".git")
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
# control: a verify that does not look for the purged files lets this through (exit 0): "FAIL: a removal step that removes nothing: exits 1: got 0, want 1"
midway("a removal step that removes nothing (the check after the work)", [(mg, "step_removes", lambda job: None)], "purged file still there")
midway("a failure in the .gitignore step",[(mg, "step_gitignore", lambda job: (_ for _ in ()).throw(RuntimeError("simulated")))], "simulated")


def text_copy(job, src, dest):
    """The plan's control: a mover that reads text and writes it back (CRLF and the binary file change)."""
    if os.path.islink(os.path.join(job.repo, src)):
        return orig_move(job, src, dest)
    mg.mkdirs(job, os.path.dirname(os.path.join(job.repo, dest)))
    mg.record(job, "created", dest)
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
cmds = undo_cmds(err)
s.ok("... and prints the commands that undo it", len(cmds) >= 3, err[-600:])
r = refusal("apply on a repository an earlier apply left half done", wt, ["apply"], "stopped in the middle", (wt,))
run_cmds(cmds)
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
cmds = undo_cmds(r.stderr)
run_cmds(cmds)
s.eq("... and the commands it printed put everything back", (content(wt), index_of(wt), porcelain(wt)), (c0, i0, s0))

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
s.eq("... it converted only those two files (and added its base to the bases file)", staged, sorted([
    "M\t.fwx/migrate-gsd-bases.md",
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
base = helpers.git(wt, "rev-parse", "HEAD").strip()
rj = run(wt, "apply", "--close", "1", "--json")
dj = json.loads(rj.stdout) if rj.returncode == 0 else {}
s.ok("apply --json: schema 1, the base, the counts, the recovery command and nothing else on stdout",
     dj.get("schema") == 1 and dj.get("base") == base and dj.get("moved", 0) > 10 and dj.get("removed", 0) > 10
     and dj.get("recover") == "git show %s:.planning/<path>" % base, rj.stdout[:300] + rj.stderr[:300])
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

# =====================================================================================================================
# Unit 2, review fixes: the scenarios of an independent data-loss review, each a fixture here (F1..F10 are its numbers).
# =====================================================================================================================
def same_size_edit_meta():
    d = helpers.mkdtemp("fwx-hash-")
    f = os.path.join(d, "f.txt")
    with open(f, "w") as fh:
        fh.write("aaaa")
    st = os.stat(f)
    a = snapshot(d)
    h1 = strict(d)
    with open(f, "w") as fh:
        fh.write("bbbb")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    return a == snapshot(d), h1 != strict(d)


old_blind, new_sees = same_size_edit_meta()
s.ok("(the size and mtime snapshot of unit 1 cannot tell a same-size edit that keeps the mtime)", old_blind)
s.ok("the snapshot of the refusals hashes the content and tells it", new_sees)

# ---- F1: the rollback never discards what the conversion did not do -------------------------------------------------------
repo, wt = world()
orig_rm = mg.step_removes
c0 = content(wt)
readme0 = rd(os.path.join(wt, "README"))


def removals_then_edit_then_fail(job):
    orig_rm(job)
    with open(os.path.join(job.repo, "README"), "a", encoding="utf-8") as fh:
        fh.write("edited while apply ran\n")
    raise OSError("simulated: forced failure after the removals")


rc, out, err = inproc(wt, ["apply"], [(mg, "step_removes", removals_then_edit_then_fail)])
# red on the code of the review: "FAIL: F1 a tracked file edited while apply ran keeps its edit after a rollback: got 'ahead\n', want 'ahead\nedited while apply ran\n'"
s.eq("F1 a tracked file edited while apply ran keeps its edit after a rollback", rd(os.path.join(wt, "README")), readme0 + "edited while apply ran\n")
s.eq("F1 apply exits 1, says the repository is back and that README changed meanwhile and was left", (rc, "back as it was" in err, "README" in err), (1, True, True))
now = content(wt)
now.pop("README")
c0.pop("README")
s.eq("F1 everything else is back as it was", now, c0)
s.eq("F1 the only change left is that edit, unstaged", (porcelain(wt), helpers.git(wt, "diff", "--cached", "--name-only")), (" M README\n", ""))
repo, wt = world()
orig_rm = mg.step_removes


def removals_then_edit(job):
    orig_rm(job)
    with open(os.path.join(job.repo, "README"), "a", encoding="utf-8") as fh:
        fh.write("edited while apply ran\n")


rc, out, err = inproc(wt, ["apply"], [(mg, "step_removes", removals_then_edit)])
s.eq("F1 an unrelated tracked file edited while apply ran does not fail the checks: apply exits 0", rc, 0)
s.eq("... and the edit is neither staged nor lost", (helpers.git(wt, "diff", "--name-only").split(), helpers.git(wt, "diff", "--cached", "--name-only").split().count("README")), (["README"], 0))
repo, wt = world()
orig_rm = mg.step_removes
mine = os.path.join(wt, ".planning/phases/01-a/01-RESEARCH.md")


def removals_then_owner_recreates(job):
    orig_rm(job)
    os.makedirs(os.path.dirname(mine), exist_ok=True)
    with open(mine, "w", encoding="utf-8") as fh:
        fh.write("the owner's new notes\n")
    raise OSError("simulated: forced failure")


rc, out, err = inproc(wt, ["apply"], [(mg, "step_removes", removals_then_owner_recreates)])
s.eq("F1 a file the owner wrote at a path apply removed is not overwritten by the rollback", rd(mine), "the owner's new notes\n")
s.ok("... apply exits 1, stops, names the file and keeps its marker", rc == 1 and "01-RESEARCH.md" in err and os.path.exists(marker_of(wt)), err[-300:])

# ---- F2 and F3: what was already under .fwx/ is never touched, and no printed command can delete it -----------------------
repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.write(wt, ".fwx/milestones/v2/phases/02.1-b/audit.tsv", "date\tkind\tsha\tdetail\trc\n")   # untracked, from an earlier use
r = refusal("F2 apply with an untracked audit file already at a closed phase's destination", wt, ["apply"], ".fwx/milestones/v2/phases/02.1-b/audit.tsv", roots)
repo, wt = world()
helpers.write(wt, ".fwx/mynotes.md", "the owner's notes\n")                                          # untracked, no conflict
c0, i0, s0 = content(wt), index_of(wt), porcelain(wt)
rc, out, err = inproc(wt, ["apply"], [(mg, "step_generate", lambda job: (_ for _ in ()).throw(RuntimeError("simulated")))])
s.eq("F3 a clean rollback with an untracked .fwx/mynotes.md: exits 1", rc, 1)
s.eq("... the file is still there and everything else is as before", (content(wt), index_of(wt), porcelain(wt)), (c0, i0, s0))
s.ok("... and it prints no command to paste (nothing is left to undo): %r" % err[-200:], "git clean" not in err and "git restore" not in err and "undo by hand" not in err)
repo, wt = world()
helpers.write(wt, ".fwx/mynotes.md", "the owner's notes\n")
c0, i0, s0 = content(wt), index_of(wt), porcelain(wt)
prog = ("import os, sys; sys.dont_write_bytecode = True; sys.path.insert(0, %r)\n"
        "import fwx.commands.migrate_gsd as mg\n"
        "mg.step_generate = lambda job: os._exit(137)\n"
        "sys.exit(mg.main(['apply']))\n" % os.path.join(helpers.ROOT, "lib"))
k = subprocess.run([sys.executable, "-c", prog], cwd=wt, env=helpers.clean_env(**ENV), capture_output=True, text=True)
r = run(wt, "apply")
cmds = undo_cmds(r.stderr)
s.ok("F3 after a kill the next apply prints commands that name only what apply made (no blanket clean)", r.returncode == 2 and cmds and not any(c.startswith("git -C") and " clean " in c for c in cmds), r.stderr[-400:])
run_cmds(cmds)
# red on the code of the review: "FAIL: F3 the printed commands leave the owner's untracked .fwx/mynotes.md: got None, want "the owner's notes\n""
s.eq("F3 the printed commands leave the owner's untracked .fwx/mynotes.md", rd(os.path.join(wt, ".fwx/mynotes.md")), "the owner's notes\n")
s.eq("... and put everything else back (files, index, status)", (content(wt), index_of(wt), porcelain(wt)), (c0, i0, s0))
# F5: the commands also remove the marker, so a later dirty tree is not taken for the old accident
helpers.write(wt, "README", "a later edit\n")
r = run(wt, "apply")
s.ok("F5 after the printed commands, a later edit gets 'not clean' and no advice to restore", r.returncode == 2 and "not clean" in r.stderr and "stopped in the middle" not in r.stderr and "restore" not in r.stderr, r.stderr[-300:])

# ---- F4: a tracked file that git hides ------------------------------------------------------------------------------------
repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
with open(os.path.join(wt, ".planning/phases/01-a/01-01-PLAN.md"), "a", encoding="utf-8") as fh:
    fh.write("an edit git does not show\n")
helpers.git(wt, "update-index", "--assume-unchanged", ".planning/phases/01-a/01-01-PLAN.md")
refusal("F4 apply with an assume-unchanged file under .planning/", wt, ["apply"], ".planning/phases/01-a/01-01-PLAN.md", roots)
repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.git(wt, "update-index", "--skip-worktree", ".planning/PROJECT.md")
refusal("F4 apply with a skip-worktree file under .planning/", wt, ["apply"], ".planning/PROJECT.md", roots)

# ---- F6: a relative symlink that the move would leave dangling ----------------------------------------------------------------
repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
os.symlink("../../PROJECT.md", os.path.join(wt, ".planning/phases/01-a/link-to-project"))
os.symlink("../../../README", os.path.join(wt, ".planning/phases/01-a/link-to-readme"))
helpers.git(wt, "add", "-A")
helpers.git(wt, "commit", "-q", "-m", "two links that climb")
r = refusal("F6 apply with relative symlinks that would dangle", wt, ["apply"], "link-to-project", roots)
s.ok("... it names both links and their targets", "link-to-readme" in r.stderr and "../../../README" in r.stderr and "would dangle" in r.stderr, r.stderr[-400:])

# ---- F7: --prefix and --rewrite change only the path component they mean ---------------------------------------------------
repo, wt = world()
run(wt, "apply", "--close", "1")
base = helpers.git(wt, "rev-parse", "HEAD").strip()
helpers.git(wt, "commit", "-q", "-m", "convert")
TABLE = [("cp .planning.bak backup/", "cp .planning.bak backup/"),
         ("rm -rf packages/app/.planning/cache", "rm -rf packages/app/.planning/cache"),
         ("see https://example.test/docs/.planning/phases/x", "see https://example.test/docs/.planning/phases/x"),
         ("cat $HOME/.planning/notes.md", "cat $HOME/.planning/notes.md"),
         ("cat ~/.planning/notes.md", "cat ~/.planning/notes.md"),
         ("echo a-.planning/x", "echo a-.planning/x"),
         ("cd .planning", "cd .fwx"),
         ('"!.planning"', '"!.fwx"'),
         ("ls ./.planning/x", "ls ./.fwx/x"),
         ("X=.planning/phases", "X=.fwx/phases"),
         ("(.planning/x)", "(.fwx/x)"),
         ("/.planning/phases/01-a/fonts/", "/.fwx/phases/01-a/fonts/"),
         ("see .planning.", "see .fwx.")]
helpers.write(wt, "scripts/prefix.sh", "".join(a + "\n" for a, _ in TABLE))
helpers.git(wt, "add", "scripts/prefix.sh")
helpers.git(wt, "commit", "-q", "-m", "a script that names .planning in many ways")
r = run(wt, "refs", "--base", base, "--prefix", "scripts/prefix.sh")
got = (rd(os.path.join(wt, "scripts/prefix.sh")) or "").splitlines()
# red on the code of the review: "FAIL: F7 --prefix table: ... 'cp .planning.bak backup/' -> 'cp .fwx.bak backup/'"
bad = ["%r -> %r (want %r)" % (a, g, w) for (a, w), g in zip(TABLE, got) if g != w]
s.ok("F7 --prefix changes the path .planning only where it is a path of its own: %s" % bad, r.returncode == 0 and not bad and len(got) == len(TABLE), r.stderr[-200:])
helpers.write(wt, "scripts/rw.sh", "cat docs/.planning/phases/01-a/01-01-SUMMARY.md\ncat .planning/phases/01-a/01-01-SUMMARY.md\n")
helpers.git(wt, "add", "scripts/rw.sh")
helpers.git(wt, "commit", "-q", "-m", "a second script")
r = run(wt, "refs", "--base", base, "--rewrite", "scripts/rw.sh")
s.eq("F7 --rewrite does not take docs/.planning/... for the root one",
     (rd(os.path.join(wt, "scripts/rw.sh")) or "").splitlines(),
     ["cat docs/.planning/phases/01-a/01-01-SUMMARY.md", "cat .fwx/milestones/v2/phases/01-a/01-01-SUMMARY.md"])

# ---- F8: a file name that is not UTF-8 ------------------------------------------------------------------------------------------
repo, wt = world()
odd = os.path.join(os.fsencode(wt), b".fwx/milestones/v2/phases/01-a/caf\xe9.md")
rj = run(wt, "plan", "--json")
s.eq("F8 plan --json with a tracked file name that is not UTF-8 exits 0", rj.returncode, 0)
r = run(wt, "apply", "--close", "1")
s.eq("F8 apply with a tracked file name that is not UTF-8 exits 0", r.returncode, 0)
s.ok("... and the file is at its destination, byte for byte", os.path.exists(odd) and open(odd, "rb").read() == b"odd name\n", r.stderr[-300:])

# ---- F9 and the commit message and the tag: the base of every run is written down ------------------------------------------------
repo, wt = world()
base1 = helpers.git(wt, "rev-parse", "HEAD").strip()
r = run(wt, "apply")
tag1 = "fwx-migrate-gsd-base-" + base1[:12]
s.ok("F9 apply prints the tag it made and the commit message file to use", tag1 in r.stdout and "git commit -F" in r.stdout, r.stdout[-500:])
s.eq("... the tag points at the base", tryg(wt, "rev-parse", tag1 + "^{commit}").strip(), base1)
msgfile = next((l.split("-F ", 1)[1].split()[0] for l in r.stdout.splitlines() if "git commit -F" in l), "")
msg = rd(msgfile) or ""
s.ok("... the message file holds the base, the counts and the recovery command", base1 in msg and "git show %s:.planning/<path>" % base1 in msg and "chore(fwx)" in msg, msg)
s.ok("... and .fwx/ records the base in a file that is staged", base1 in (rd(os.path.join(wt, ".fwx/migrate-gsd-bases.md")) or "") and ".fwx/migrate-gsd-bases.md" in helpers.git(wt, "diff", "--cached", "--name-only"))
tryg(wt, "commit", "-q", *(["-F", msgfile] if msgfile else ["-m", "convert"])) or helpers.git(wt, "commit", "-q", "--allow-empty", "-m", "convert")
wx = helpers.add_worktree(repo, "extra")
helpers.write(wx, ".planning/extra/n.md", "# new\n")
helpers.git(wx, "add", "-A")
helpers.git(wx, "commit", "-q", "-m", "adds to .planning/")
helpers.git(wt, "-c", "merge.directoryRenames=false", "merge", "--no-edit", "-q", "extra")
base2 = helpers.git(wt, "rev-parse", "HEAD").strip()
first = rd(os.path.join(wt, ".fwx/migrate-gsd-bases.md")) or ""
r = run(wt, "apply")
both = rd(os.path.join(wt, ".fwx/migrate-gsd-bases.md")) or ""
# red on the code of the review: "FAIL: F9 the second run's base is written in .fwx/: ..."
s.ok("F9 a re-entrant apply appends its base (the first stays, byte for byte, in front)", both.startswith(first) and base2 in both and base1 in both and both != first, both)
s.eq("... and tags its own base too", tryg(wt, "rev-parse", "fwx-migrate-gsd-base-%s^{commit}" % base2[:12]).strip(), base2)

# ---- F10: a .gitignore line that would make the twin ignore the destinations ----------------------------------------------------
repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.write(wt, ".gitignore", "node_modules/\n.planning/\n")
helpers.git(wt, "commit", "-q", "-am", "ignore the whole folder")
r = refusal("F10 apply with a .gitignore line .planning/ whose twin would ignore .fwx/", wt, ["apply"], ".planning/", roots)
s.ok("... it names the twin and says what to do", ".fwx/" in r.stderr and "Edit that .gitignore line" in r.stderr, r.stderr[-300:])

# ---- F14: a linked worktree only ---------------------------------------------------------------------------------------------------
repo, wt = world()
helpers.git(repo, "checkout", "-q", "-b", "other")
refusal("F14 apply in the main checkout on a branch that is not the default one", repo, ["apply"], "not a linked worktree", (repo,))

# ---- the refusals that had no control: detached HEAD, submodule, ignored destination, a destination under a file -----------------
repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
with open(os.path.join(wt, ".fwx"), "w") as fh:
    fh.write("a file where the folder goes\n")
refusal("apply with .fwx a file (a destination under a file)", wt, ["apply"], "is not a folder", roots)

# ---- leftovers: the archive, an untracked file into an ignored place, a link that would dangle, a name that is not UTF-8 --------------
repo, wt = world()
run(wt, "apply", "--close", "1")
helpers.git(wt, "commit", "-q", "-m", "convert")
helpers.git(repo, "merge", "--ff-only", "-q", "fwx-migrate-gsd")
helpers.write(repo, ".planning/untracked.md", "an untracked note\n")
wbytes(repo, ".planning/knowledge/n\xe9.txt".encode("latin-1"), b"odd name, untracked\n")
os.symlink("../../../README", os.path.join(repo, ".planning/phases/01-a/up-link"))                 # a leftover link that climbs
refusal("leftovers with a leftover symlink that the move would leave dangling", repo, ["leftovers", "--apply"], "up-link", (repo,))
if os.path.lexists(os.path.join(repo, ".planning/phases/01-a/up-link")):
    os.remove(os.path.join(repo, ".planning/phases/01-a/up-link"))
gi_ok = rd(os.path.join(repo, ".gitignore")) or ""
helpers.write(repo, ".gitignore", gi_ok + "/.fwx/untracked.md\n")
helpers.git(repo, "commit", "-q", "-am", "ignore where an untracked file would land")
refusal("F15 leftovers with an untracked file whose destination is ignored (it would vanish from git status)", repo, ["leftovers", "--apply"], "untracked.md", (repo,))
helpers.write(repo, ".gitignore", gi_ok)
helpers.git(repo, "commit", "-q", "-am", "back")
before = {}
for dp, dn, fn in os.walk(os.path.join(repo, ".planning")):
    for n in fn:
        p = os.path.join(dp, n)
        if os.path.islink(p):
            before[os.path.relpath(p, repo)] = ("l", os.readlink(p))
        else:
            with open(p, "rb") as fh:
                before[os.path.relpath(p, repo)] = ("f", fh.read())
r = run(repo, "leftovers")
s.ok("leftovers (dry run) says where its archive would go and writes none", "archive" in r.stdout and ".git" in r.stdout, r.stdout[-400:])
r = run(repo, "leftovers", "--apply")
s.eq("leftovers --apply exits 0 (a name that is not UTF-8 included)", r.returncode, 0)
m = [l for l in r.stdout.splitlines() if l.startswith("archive: ")]
s.eq("... and prints the archive it made, once", len(m), 1)
arch = (m[0][len("archive: "):].split() or [""])[0] if m else ""
s.ok("... which is inside the git dir (not in the worktree, not in /tmp)", arch.startswith(os.path.join(helpers.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip(), "")), arch)
s.ok("... with the command to restore from it", "tar -xf" in r.stdout, r.stdout[-400:])
out_dir = helpers.mkdtemp("fwx-restore-")
s.ok("... and the archive is a file that exists", bool(arch) and os.path.isfile(arch), repr(arch))
if arch and os.path.isfile(arch):
    import tarfile  # noqa: E402
    with tarfile.open(arch) as tf:
        try:
            tf.extractall(out_dir, filter="fully_trusted")
        except TypeError:
            tf.extractall(out_dir)
    restored = {}
    for dp, dn, fn in os.walk(os.path.join(out_dir, ".planning")):
        for n in fn:
            p = os.path.join(dp, n)
            if os.path.islink(p):
                restored[os.path.relpath(p, out_dir)] = ("l", os.readlink(p))
            else:
                with open(p, "rb") as fh:
                    restored[os.path.relpath(p, out_dir)] = ("f", fh.read())
    s.eq("restoring from the archive gives back every untracked and ignored file, byte for byte (state.json too)", restored, before)
s.ok("the untracked file with a name that is not UTF-8 moved", os.path.exists(os.path.join(os.fsencode(repo), b".fwx/knowledge/n\xe9.txt")))

# ---- F5 without the commands: a stale marker and a dirty tree ------------------------------------------------------------------
repo, wt = world()
with open(marker_of(wt), "w", encoding="utf-8") as fh:
    fh.write("apply started on %s\nbase %s\n" % (wt, helpers.git(wt, "rev-parse", "HEAD").strip()))   # left behind, nothing half done
helpers.write(wt, "README", "an edit of the owner's, made after an old accident\n")
r = run(wt, "apply")
# control (a refusal that treats any dirty tree as the old accident): "FAIL: F5 a stale marker and a dirty tree: says 'not clean' ..."
s.ok("F5 a stale marker and a dirty tree: 'not clean', and no advice to restore anything", r.returncode == 2 and "not clean" in r.stderr and "stopped in the middle" not in r.stderr, r.stderr[-300:])

# ---- F11: the write half starts no hook of the repository ----------------------------------------------------------------------
repo, wt = world()
flag = os.path.join(helpers.mkdtemp("fwx-hook-"), "ran")
hook = os.path.join(repo, ".git", "hooks", "post-index-change")
with open(hook, "w") as fh:
    fh.write("#!/bin/sh\ntouch %s\n" % flag)
os.chmod(hook, 0o755)
r = run(wt, "apply")
s.eq("F11 apply with a post-index-change hook in the repository exits 0", r.returncode, 0)
s.ok("... and the hook did not run (once per `git mv` otherwise)", not os.path.exists(flag))

# =====================================================================================================================
# Unit 2, second pass of the review: links to folders (F6), a file that changed after it was archived (N1), an audit file at
# another stage (N2), an archive folder that cannot be written.
# =====================================================================================================================
# ---- F6, links to folders and the rest of the table ----------------------------------------------------------------------------
lroot = helpers.mkdtemp("fwx-links-")
lrepo = os.path.join(lroot, "repo")
for rel in (".planning/PROJECT.md", ".planning/knowledge/a.md", ".planning/phases/01-a/x.md", ".planning/phases/02-b/y.md",
            ".planning/phases/03-c/purged.md"):
    wbytes(lrepo, rel, b"x\n")
wbytes(lroot, "outside.txt", b"x\n")
MAPPING = {".planning/PROJECT.md": ".fwx/PROJECT.md", ".planning/knowledge/a.md": ".fwx/knowledge/a.md",
           ".planning/phases/01-a/x.md": ".fwx/milestones/v1/phases/01-a/x.md",
           ".planning/phases/02-b/y.md": ".fwx/milestones/v1/phases/02-b/y.md"}     # 03-c holds only a file the conversion purges
LINK_SRC, LINK_DEST = ".planning/phases/01-a/L", ".fwx/milestones/v1/phases/01-a/L"
for label, target, problem in (("a link to a file that moves elsewhere", "../../PROJECT.md", True),
                               ("a link to a sibling file", "x.md", False),
                               ("a link to a folder (the reviewer's link-to-dir)", "../../knowledge", True),
                               ("a link to a folder that itself moves with it", "../02-b", False),
                               ("an absolute link", "/usr/bin", False),
                               ("a link that points outside the repository", "../../../../outside.txt", True),
                               ("a link that was dangling before", "../../nothing", False),
                               ("a link to a folder the conversion empties", "../03-c", True)):
    got = mg.link_problems(lrepo, [(LINK_SRC, LINK_DEST)], MAPPING, lambda s, t=target: t)
    # control (the folder case `continue`d as before): "FAIL: F6 a link to a folder (the reviewer's link-to-dir): refused is False, want True"
    s.eq("F6 %s: refused is %s, want %s" % (label, bool(got), problem), bool(got), problem)
s.ok("... a refusal names the link and its target", "../../knowledge" in " ".join(mg.link_problems(lrepo, [(LINK_SRC, LINK_DEST)], MAPPING, lambda s_: "../../knowledge")))

repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
os.symlink("../../knowledge", os.path.join(wt, ".planning/phases/01-a/link-to-dir"))
helpers.git(wt, "add", "-A")
helpers.git(wt, "commit", "-q", "-m", "a link to a folder that climbs")
r = refusal("F6 apply with a symbolic link to a folder that would dangle", wt, ["apply"], "link-to-dir", roots)
repo, wt = world()
os.symlink("../02.1-b", os.path.join(wt, ".planning/phases/01-a/to-sibling-phase"))
os.symlink("/usr/bin", os.path.join(wt, ".planning/phases/01-a/to-absolute"))
os.symlink("../../nothing", os.path.join(wt, ".planning/phases/01-a/to-nothing"))
helpers.git(wt, "add", "-A")
helpers.git(wt, "commit", "-q", "-m", "three links that stay right")
r = run(wt, "apply", "--close", "1")
s.eq("F6 apply with a link to a folder that moves, an absolute link and a link that was dangling exits 0", r.returncode, 0)
s.ok("... and the link to the moved folder still resolves", os.path.isdir(os.path.join(wt, ".fwx/milestones/v2/phases/01-a/to-sibling-phase")))


def merged_main():
    repo_, wt_ = world()
    run(wt_, "apply", "--close", "1")
    helpers.git(wt_, "commit", "-q", "-m", "convert")
    helpers.git(repo_, "merge", "--ff-only", "-q", "fwx-migrate-gsd")
    return repo_, wt_


# ---- N1: a machine-state file that changed after it was archived is not deleted -----------------------------------------------------
repo, wt = merged_main()
orig_archive = mg.write_archive
state_json = os.path.join(repo, ".planning/state.json")


def archive_then_late_write(*a, **k):
    path = orig_archive(*a, **k)
    with open(state_json, "a", encoding="utf-8") as fh:
        fh.write("written after the archive\n")
    return path


rc, out, err = inproc(repo, ["leftovers", "--apply"], [(mg, "write_archive", archive_then_late_write)])
# red on the code of the second pass: "FAIL: N1 a file changed after it was archived is still there: got None, want '{}\n...'"
s.eq("N1 a file changed after it was archived is not deleted", rd(state_json), "{}\nwritten after the archive\n")
s.ok("... leftovers says which one, and exits 1 after finishing the rest", rc == 1 and "state.json" in err and "NOT deleted" in err, err[-300:])
s.ok("... the other files were moved all the same", os.path.exists(os.path.join(repo, ".fwx/milestones/v2/phases/01-a/fonts/a.woff")))

# ---- N2: an audit file at another stage is a refusal that says what to do, and plan says it too ------------------------------------
repo, wt = world()
roots = (wt, os.path.join(repo, ".git"))
helpers.write(wt, ".fwx/milestones/v2/phases/02.1-b/audit.tsv", "date\tkind\tsha\tdetail\trc\nearlier\tstage\t\tdiscuss started\t\n")
rp = run(wt, "plan")
# red on the code of the second pass: "FAIL: N2 plan says what apply will refuse: got ... (no note)"
s.ok("N2 plan says apply would refuse, names the stage and how to go on", rp.returncode == 0 and "apply would refuse" in rp.stdout and "discuss" in rp.stdout and "--open" in rp.stdout, rp.stdout[-400:])
r = refusal("N2 apply with an audit file at the stage discuss for a phase GSD left closed", wt, ["apply"], "discuss", roots)
s.ok("... it names the file and the way out (--open)", "02.1-b/audit.tsv" in r.stderr and "--open" in r.stderr, r.stderr[-300:])

# ---- an archive folder that cannot be written: one line, nothing touched ------------------------------------------------------------
repo, wt = merged_main()
gitdir = os.path.join(repo, ".git")
if os.geteuid() == 0:
    print("NOT RUN: the unwritable archive folder needs a user that is not root")
else:
    before = strict(repo)
    os.chmod(gitdir, 0o500)
    try:
        r = run(repo, "leftovers", "--apply")
    finally:
        os.chmod(gitdir, 0o700)
    # red on the code of the second pass: a Traceback ("PermissionError") instead of the line
    s.ok("an archive folder that cannot be created: exit 2, one line, no traceback: %r" % r.stderr[-300:],
         r.returncode == 2 and len(r.stderr.strip().splitlines()) == 1 and "cannot write the archive" in r.stderr and "Traceback" not in r.stderr)
    s.ok("... and nothing was touched (every path, size, mtime and content hash)", strict(repo) == before)

s.done()
