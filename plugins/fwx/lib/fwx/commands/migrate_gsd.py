"""Convert a project's GSD `.planning/` to `.fwx/`: fwx migrate-gsd plan|refs|apply|leftovers [...]

  plan [--json] [--milestone-map FILE] [--close IDS] [--open IDS]
      Reads the `.planning/` of the repository you stand in (tracked, untracked and ignored files) and prints what the
      conversion would do with each file, phase, backlog item, `.gitignore` line, reference and unmerged branch. Writes nothing.
  apply [--json] [--milestone-map FILE] [--close IDS] [--open IDS]
      In a worktree, on a branch that is not the default one: `git mv` of what is kept, `git rm` of what is purged and of the
      backlog (not migrated), the generated files (`milestones/<vN>/MILESTONE.md` with the base SHA and the recovery command, a
      `gsd-roadmap-entry.md` per open phase only the ROADMAP had, a stage row per closed phase through `state.append_audit`),
      the `.fwx/` twin under each `.gitignore` line that names `.planning/`; everything staged, nothing committed. Then the
      checks: the blob of each kept file identical at its destination, each purged file gone, `state.phases` sees every phase
      folder, `state.last_stage` says closed for each closed phase. Re-entrant: after a merge that brings new files into
      `.planning/`, it converts only those.
  refs --base SHA [--json] [--milestone-map FILE] [--rewrite FILE...] [--prefix FILE...]
      The reference list, for a branch the conversion has already run on: the files of `.planning/` at SHA are classified again
      and every tracked line outside `.planning/` and `.fwx/` that names `.planning` is listed. `--rewrite` changes, in the
      named files only, the paths that moved (when their new path exists); `--prefix` changes `.planning` for `.fwx` in every
      path of the named files. What a purged file was cited by is never touched. The changed files are staged.
  leftovers [--apply] [--milestone-map FILE]
      In the main checkout, after the conversion is merged: the ignored and untracked files still under `.planning/` move to
      their destination with `os.rename` (an ignored file only if git would still ignore it there, else nothing moves), the
      machine-state names of GSD are deleted (a copy goes to `<git dir>/fwx/migrate-gsd/deleted/` first), and `.planning/` is
      removed when it is empty. A dry run unless `--apply`.

`plan` and `refs` without a write flag only read: no cache, no log, git runs with `--no-optional-locks`, so not even the
index is refreshed.

What makes the write half safe is in the code, not in this text. `apply` refuses (exit 2, nothing written) on the default
branch or a detached HEAD, with any tracked file not clean (so what it removes is in HEAD, the base it names), with a
submodule in `.planning/`, with a destination that exists or that `.gitignore` ignores, with a phase no milestone range
covers, with a `--close`/`--open` key that names no phase, and when a previous apply stopped in the middle. It changes the
repository in a fixed order; a step that raises or a check that fails puts the repository back to the base (`git restore`,
then the files it created are removed) and compares git status and the index with what they were, and exits 1. A process
killed in the middle cannot clean up: it leaves a marker in the git dir, and the next run refuses and prints the two commands
that undo it. The same two commands are printed whenever apply exits 1. `leftovers` puts its renames back on a failure.

The classification is data (ROWS, PHASE_KEEP, PHASE_PURGE, ...): one tuple per row of the table the plan documents, each with
its `rule`, which is also the `rule` of every file it decided. A file no row names is kept at its own path (rule
`unknown`), because the project wrote it on purpose. Ignored and untracked files are never purged: only the machine-state
names are marked for deletion, the rest for moving. A PLAN is purged only when its SUMMARY is tracked.

`--milestone-map FILE` is JSON `{"<phase>": "vN"}` or lines `<phase> vN` / `<phase>=vN`, `#` comments allowed; a key is a
phase number (`7`, `02.1`) or a folder name, with an optional `<workstream>/` in front. `--close` and `--open` take
comma-separated keys of the same kind. A key no scope has, in any of the three flags, is exit 2.

`--json` is schema 1 and nothing else on stdout; notes (a ROADMAP with no phase headings in the expected format, a phase with
every file purged) go to stderr then, and to a `notes:` section in the text. Exit 0 done, 1 a step or a check after the work
failed (the repository is put back and the message says so), 2 it cannot run or refuses: not a git repository, 0 files looked
at, a phase no milestone range covers, a key that matches no phase, two files for one destination, a bad option.
"""
import fnmatch
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from fwx import state

SCHEMA = 1
SCOPE_SRC = ".planning"
SCOPE_DEST = ".fwx"
USAGE = ("usage: fwx migrate-gsd plan [--json] [--milestone-map FILE] [--close IDS] [--open IDS]\n"
         "       fwx migrate-gsd apply [--json] [--milestone-map FILE] [--close IDS] [--open IDS]\n"
         "       fwx migrate-gsd refs --base SHA [--json] [--milestone-map FILE] [--rewrite FILE...] [--prefix FILE...]\n"
         "       fwx migrate-gsd leftovers [--apply] [--milestone-map FILE]\n")
MAX_SLUG = 60
MAX_SCAN = 2 * 1024 * 1024  # a tracked file over this is not read for references

# ---- the classification, as data --------------------------------------------------------------------------------------
# One row of the plan's table per tuple: (rule, action, how it matches, patterns, where it goes). Paths are relative to a
# scope (the root of `.planning/` or one workstream). The first row that matches wins; none matching is `unknown`.
STATE_NAMES = ("STATE.md", "STATE-ARCHIVE.md", "config.json", "state.json", "milestone.lock", "STATE.md.lock", "WAITING.json",
               "HANDOFF.json", ".continue-here.md", ".verification-ledger.json", "skill-manifest.json", "active-workstream",
               "CLAUDE.md", "INGEST-CONFLICTS.md", "ingest-manifest.yaml")
MILESTONE_DOCS = ("ROADMAP.md", "REQUIREMENTS.md", "MILESTONES.md", "LEARNINGS.md", "RETROSPECTIVE.md", "PATTERNS.md", "WINDOWS.md",
                  "THREADS.md")
RE_MS_PHASES = re.compile(r"milestones/v(\d+)\.\d+-phases/(\d+(?:\.\d+)*-[^/]+)/(.+)\Z")
RE_MS_ANY = re.compile(r"milestones/v(\d+)\.\d+-.*\Z")
RE_AUDIT = re.compile(r"v(\d+)\.\d+-MILESTONE-AUDIT\.md\Z")
# match kinds: name (a file at the scope root), tree (anything below the folder), glob (fnmatch on the path),
#             regex (re.match on the path, group 1 is the milestone's major)
# dest kinds: scope (<dest>/<same name>), actual (<dest>/milestones/<current>/<name>), major (<dest>/milestones/v<group 1>/<rest>),
#             none (the file goes nowhere)
ROWS = (
    ("project", "keep", "name", ("PROJECT.md",), "scope"),
    ("milestone-docs", "keep", "name", MILESTONE_DOCS, "actual"),
    ("milestone-file", "keep", "regex", (RE_MS_ANY,), "major"),
    ("milestone-audit", "keep", "regex", (RE_AUDIT,), "major"),
    ("machine-state", "purge", "name", STATE_NAMES, "none"),
    ("generated", "purge", "tree", ("codebase", "intel", "debug", "ui-reviews", "todos/done", "todos/completed"), "none"),
    ("research-summary", "purge", "glob", tuple("research/%s.md" % n for n in ("STACK", "FEATURES", "ARCHITECTURE", "PITFALLS", "SUMMARY")), "none"),
    ("backlog", "backlog", "tree", ("todos/pending",), "none"),
    ("backlog", "backlog", "name", ("BACKLOG.md",), "none"),
)
# inside a phase folder (first row that matches wins)
PHASE_KEEP = ("*-CONTEXT.md", "*-SUMMARY.md", "*-VERIFICATION.md", "*-UAT.md", "*-HUMAN-UAT.md", "*-LEARNINGS.md", "*-SECURITY.md",
              "*-UI-SPEC.md", "*-AI-SPEC.md", "deferred-items.md")
PHASE_PURGE = ("*-RESEARCH.md", "*-VALIDATION.md", "*-PATTERNS.md", "*-REVIEWS.md", "*-REVIEW*.md", "*-UI-REVIEW.md",
               "*-DISCUSSION-LOG.md", "*-DEBUG.md", "*-DISCUSS-CHECKPOINT.json")
IMAGE_EXT = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".mp4", ".webm")
RE_PLAN = re.compile(r"(\d+(?:\.\d+)*-\d+)-PLAN\.md\Z")
RE_PHASE_DIR = re.compile(r"\d+(?:\.\d+)*-.+\Z")
RE_NUM = re.compile(r"\d+(?:\.\d+)*")

# ---- reading the roadmap and the state --------------------------------------------------------------------------------
DASH = "-–—"
RE_RANGE = re.compile(r"^\s*[-*]\s*(?:\S+\s+)?\*\*v(\d+)(?:\.\d+)?[^*]*\*\*\s*[%s]\s*Phases?\s+(\d+)(?:\s*[%s]\s*(\d+))?" % (DASH, DASH),
                      re.M)
RE_BOX = re.compile(r"^\s*[-*]\s*\[(.)\]\s*\**Phase\s+(\d+(?:\.\d+)*)\b", re.M)
RE_HEADING = re.compile(r"^#{2,4} Phase (\d+(?:\.\d+)*): (.+)$", re.M)
RE_STATE_MS = re.compile(r"^milestone:\s*[\"']?v?(\d+)", re.M)
RE_STATE_MS_RAW = re.compile(r"^milestone:\s*[\"']?([^\s\"']+)", re.M)


class Refuse(Exception):
    """The command cannot run or refuses; the message is the whole of what it says on stderr."""


# ---- git, read only ----------------------------------------------------------------------------------------------------

def _git(repo, *args, ok=(0,), input=None):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        # no optional lock: git refreshes no index; no fsmonitor: a repository's own hook program is not started
        r = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", repo] + list(args),
                           capture_output=True, env=env, input=input)
    except OSError as e:
        raise Refuse("cannot run git (%s)" % e)
    if r.returncode not in ok:
        raise Refuse("git %s failed (%d): %s" % (" ".join(args[:2]), r.returncode, r.stderr.decode("utf-8", "replace").strip()))
    return r


def _lines(repo, *args):
    return [p for p in _git(repo, *args).stdout.decode("utf-8", "replace").split("\0") if p]


def _text(repo, *args):
    return _git(repo, *args).stdout.decode("utf-8", "replace").strip()


class WorkTree:
    """The `.planning/` on disk: what git tracks, what it does not track yet, what it ignores."""

    def __init__(self, repo):
        self.repo = repo

    def entries(self):
        out = {}
        for kind, args in ((True, ("ls-files", "-z", "--", SCOPE_SRC)),
                           (False, ("ls-files", "-z", "--others", "--exclude-standard", "--", SCOPE_SRC)),
                           (False, ("ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", SCOPE_SRC))):
            for p in _lines(self.repo, *args):
                for path in self.expand(p):
                    try:
                        size = os.lstat(os.path.join(self.repo, path)).st_size
                    except OSError:
                        size = 0
                    out.setdefault(path[len(SCOPE_SRC) + 1:], (kind, size))
        return [(rel, t, n) for rel, (t, n) in sorted(out.items())]

    def expand(self, p):
        """git lists a repository nested in the folder as one `dir/` entry and does not look inside it: list its files
        (its own `.git` too) from the disk, so none is left out of the count and the sizes."""
        if not p.endswith("/"):
            return [p]
        found = []
        for dirpath, dirnames, filenames in os.walk(os.path.join(self.repo, p)):
            for n in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
                found.append(os.path.relpath(os.path.join(dirpath, n), self.repo))
        return sorted(found)

    def read(self, rel):
        try:
            with open(os.path.join(self.repo, SCOPE_SRC, rel), "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None


class Commit:
    """The `.planning/` of one commit: only tracked files exist there."""

    def __init__(self, repo, sha):
        self.repo, self.sha = repo, sha

    def entries(self):
        out = []
        for rec in _lines(self.repo, "ls-tree", "-r", "-l", "-z", self.sha, "--", SCOPE_SRC):
            meta, _, path = rec.partition("\t")
            size = meta.split()[-1]
            out.append((path[len(SCOPE_SRC) + 1:], True, int(size) if size.isdigit() else 0))
        return sorted(out)

    def read(self, rel):
        r = _git(self.repo, "cat-file", "blob", "%s:%s/%s" % (self.sha, SCOPE_SRC, rel), ok=(0, 128))
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


# ---- small helpers -----------------------------------------------------------------------------------------------------

def num_key(name):
    """`02.1-b` -> (2, 1): the phase number as a tuple, so 2.1 and 02.1 are one phase and 12.2 < 12.10."""
    return tuple(int(n) for n in RE_NUM.match(name).group(0).split("."))


def slugify(title):
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:MAX_SLUG].rstrip("-") or "phase"


def phase_folder(number, title):
    """`<NN>-<slug>` for a phase that only the ROADMAP has: the integer part has two digits, a decimal part stays."""
    head, _, rest = number.partition(".")
    return "%02d%s-%s" % (int(head), ("." + rest) if rest else "", slugify(title))


def clean_url(url):
    """A remote URL without the credentials it may carry (`https://user:token@host/...`)."""
    return re.sub(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/@]*@", r"\1", url)


def first_title(text, fallback):
    if text:
        m = re.search(r"^---\s*\n(.*?)\n---", text, re.S)
        if m:
            t = re.search(r"^(?:title|name):\s*[\"']?(.+?)[\"']?\s*$", m.group(1), re.M)
            if t:
                return t.group(1)
        h = re.search(r"^#{1,6}\s+(.+?)\s*$", text, re.M)
        if h:
            return h.group(1)
    return fallback


def match_row(row, rel):
    """The destination kind and the group-1 text of the first matching row of `rel`, or None."""
    rule, action, how, patterns, dest = row
    for p in patterns:
        if how == "name":
            hit = rel == p
        elif how == "tree":
            hit = rel.startswith(p + "/")
        elif how == "glob":
            hit = fnmatch.fnmatchcase(rel, p)
        else:
            m = p.match(rel)
            if m:
                return m.group(1)
            hit = False
        if hit:
            return ""
    return None


def parse_ids(value):
    return [v for v in re.split(r"[,\s]+", value or "") if v]


def read_map(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise Refuse("cannot read --milestone-map %s: %s" % (path, e))
    out = {}
    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except ValueError as e:
            raise Refuse("--milestone-map %s is not JSON: %s" % (path, e))
        if not isinstance(data, dict):
            raise Refuse("--milestone-map %s: expected an object {phase: vN}" % path)
        items = [(str(k), str(v)) for k, v in data.items()]
    else:
        items = []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                m = re.match(r"(\S+?)\s*(?:=|\s)\s*(\S+)\Z", line)
                if not m:
                    raise Refuse("--milestone-map %s: cannot read the line %r (want `<phase> vN`)" % (path, line))
                items.append((m.group(1), m.group(2)))
    for k, v in items:
        m = re.match(r"v?(\d+)", v)
        if not m:
            raise Refuse("--milestone-map %s: %r is not a milestone (want vN)" % (path, v))
        out[k] = "v" + m.group(1)
    return out


def key_hits(k, scope_ws, name, num):
    """Whether a key of --milestone-map, --close or --open names this phase: its folder or its number, with or without the
    workstream in front."""
    ws, _, ident = k.rpartition("/")
    if ws and ws != scope_ws:
        return False
    return ident == name or (bool(RE_NUM.fullmatch(ident)) and tuple(int(n) for n in ident.split(".")) == num)


# ---- a scope: the root of `.planning/` or one workstream ---------------------------------------------------------------

class Scope:
    def __init__(self, ws):
        self.ws = ws
        self.prefix = "" if ws is None else "workstreams/%s/" % ws          # inside `.planning/`
        self.src = SCOPE_SRC if ws is None else "%s/workstreams/%s" % (SCOPE_SRC, ws)
        self.dest = SCOPE_DEST if ws is None else "%s/subprojects/%s" % (SCOPE_DEST, ws)
        self.files = []     # (inner path, tracked, bytes)
        self.phases = []    # dicts, see build_phases
        self.by_dir = {}    # inner folder path ("phases/01-a") -> phase
        self.actual = "v1"
        self.notes = []

    def label(self):
        return "" if self.ws is None else " (workstream %s)" % self.ws


def split_scopes(entries):
    scopes = {None: Scope(None)}
    for rel, tracked, size in entries:
        parts = rel.split("/")
        if parts[0] == "workstreams" and len(parts) >= 3:
            sc = scopes.setdefault(parts[1], Scope(parts[1]))
            sc.files.append(("/".join(parts[2:]), tracked, size))
        else:
            scopes[None].files.append((rel, tracked, size))
    return [scopes[k] for k in sorted(scopes, key=lambda k: (k is not None, k or ""))]


def roadmap_ranges(text):
    """[(low, high, major)] of the ROADMAP's milestone list (`- ✅ **v1.0 ...** - Phases 1-4`)."""
    out = []
    for m in RE_RANGE.finditer(text or ""):
        lo = int(m.group(2))
        out.append((lo, int(m.group(3)) if m.group(3) else lo, int(m.group(1))))
    return out


def build_phases(sc, src, ctx):
    """Find the phase folders of a scope, read their signals and give each a milestone and a verdict (open or closed)."""
    roadmap, state = src.read(sc.prefix + "ROADMAP.md"), src.read(sc.prefix + "STATE.md")
    ranges = roadmap_ranges(roadmap)
    boxes = {}
    for m in RE_BOX.finditer(roadmap or ""):
        boxes.setdefault(tuple(int(n) for n in m.group(2).split(".")), {" ": False, "x": True, "X": True}.get(m.group(1)))
    heads = [(m.group(1), m.group(2).strip()) for m in RE_HEADING.finditer(roadmap or "")]
    st = RE_STATE_MS.search(state or "")
    state_ms = "v" + st.group(1) if st else None
    sc.state_milestone = RE_STATE_MS_RAW.search(state or "").group(1) if RE_STATE_MS_RAW.search(state or "") else None
    folders = {}
    for inner, tracked, size in sc.files:
        m = RE_MS_PHASES.match(inner)
        if m:
            key = inner[:len(inner) - len(m.group(3)) - 1]
            folders.setdefault(key, {"name": m.group(2), "ms": "v" + m.group(1), "files": []})["files"].append((m.group(3), tracked))
            continue
        parts = inner.split("/")
        if len(parts) >= 3 and parts[0] == "phases" and RE_PHASE_DIR.match(parts[1]) and not parts[1].startswith("999."):
            key = "phases/" + parts[1]
            folders.setdefault(key, {"name": parts[1], "ms": None, "files": []})["files"].append(("/".join(parts[2:]), tracked))
    problems = []

    def hit(k, name, num):
        return key_hits(k, sc.ws, name, num)

    def milestone(name, num):
        for k, v in ctx["map"].items():
            if hit(k, name, num):
                ctx["used"].add(k)
                return v
        if ranges:
            for lo, hi, major in ranges:
                if lo <= num[0] <= hi:
                    return "v%d" % major
            problems.append("phase %s%s is outside every milestone range of ROADMAP.md (%s); give it with --milestone-map"
                            % (name, sc.label(), ", ".join("v%d: %d-%d" % (m, a, b) for a, b, m in ranges)))
            return None
        return state_ms or "v1"

    def verdict(name, num, pairing):
        for flag, value in (("close", True), ("open", False)):
            for k in ctx[flag]:
                if hit(k, name, num):
                    ctx["used"].add(k)
                    return value
        if boxes.get(num) is not None:
            return boxes[num]
        return pairing

    for key in sorted(folders, key=lambda k: (num_key(folders[k]["name"]), k)):
        f = folders[key]
        plans, summaries = set(), set()
        for inner, tracked in f["files"]:
            if "/" in inner or not tracked:
                continue
            m = RE_PLAN.match(inner)
            if m:
                plans.add(m.group(1))
            elif inner.endswith("-SUMMARY.md"):
                summaries.add(inner[:-len("-SUMMARY.md")])
        pairing = bool(plans) and plans <= summaries
        f["pairing"], f["checklist"], f["num"] = pairing, boxes.get(num_key(f["name"])), num_key(f["name"])
        f["milestone"] = f["ms"] or milestone(f["name"], f["num"])
        f["closed"] = verdict(f["name"], f["num"], pairing)
        f["from_roadmap"], f["key"] = False, key
        sc.phases.append(f)
    have = {p["num"] for p in sc.phases}
    for number, title in heads:
        num = tuple(int(n) for n in number.split("."))
        if num in have or num[0] == 999:
            continue
        have.add(num)
        name = phase_folder(number, title)
        closed = verdict(name, num, False)
        if closed:
            continue
        ms = milestone(name, num)
        sc.phases.append({"name": name, "ms": None, "files": [], "pairing": False, "checklist": boxes.get(num), "num": num,
                          "milestone": ms, "closed": False, "from_roadmap": True, "key": None, "title": title})
    if roadmap is not None and not heads:
        sc.notes.append("ROADMAP.md%s has no `### Phase N: title` headings: no phase is created from it, and it is kept whole" % sc.label())
    for p in sc.phases:
        ms = p["milestone"]
        p["dest_rel"] = "milestones/%s/phases/%s" % (ms, p["name"]) if ms else None
        if p["key"]:
            sc.by_dir[p["key"]] = p
    nums = [p for p in sc.phases if p["milestone"]]
    top = max(nums, key=lambda p: p["num"], default=None)
    sc.actual = top["milestone"] if top else (state_ms or "v1")
    return problems


# ---- classifying a file ------------------------------------------------------------------------------------------------

def classify(sc, inner, tracked):
    """(action, destination inside the scope or None, rule) of one file of a scope. A tracked file follows the table; an
    untracked or ignored one is never purged: a machine-state name is deleted, anything else moves."""
    action, dest, rule = classify_tracked(sc, inner)
    if tracked:
        return action, dest, rule
    if rule == "machine-state":
        return "leftover_delete", None, rule
    return "leftover_move", dest or place(sc, inner), "leftover"


def place(sc, inner):
    """Where a file the table would not keep goes if it has to move anyway: with its phase, else at its own path."""
    for key, p in sc.by_dir.items():
        if inner.startswith(key + "/") and p["dest_rel"]:
            return p["dest_rel"] + inner[len(key):]
    return inner


def classify_tracked(sc, inner):
    m = RE_MS_PHASES.match(inner)
    if m:
        key = inner[:len(inner) - len(m.group(3)) - 1]
        return phase_file(sc, key, m.group(3))
    parts = inner.split("/")
    if len(parts) >= 3 and parts[0] == "phases" and parts[1].startswith("999."):
        return "backlog", None, "backlog"
    if len(parts) >= 3 and parts[0] == "phases" and RE_PHASE_DIR.match(parts[1]):
        return phase_file(sc, "phases/" + parts[1], "/".join(parts[2:]))
    if len(parts) >= 3 and parts[0] == "quick":
        done = any(n.endswith("SUMMARY.md") for n, t, _ in sc.files if t and n.startswith("quick/%s/" % parts[1]) and n.count("/") == 2)
        return ("purge", None, "quick-done") if done else ("backlog", None, "quick-open")
    for row in ROWS:
        g = match_row(row, inner)
        if g is None:
            continue
        rule, action, how, patterns, dest = row
        base = inner.rsplit("/", 1)[-1]
        if dest == "scope":
            return action, inner, rule
        if dest == "actual":
            return action, "milestones/%s/%s" % (sc.actual, base), rule
        if dest == "major":
            return action, "milestones/v%s/%s" % (g, inner[len("milestones/"):] if inner.startswith("milestones/") else inner), rule
        return action, None, rule
    return "keep", inner, "unknown"


def phase_file(sc, key, inner):
    p = sc.by_dir.get(key)
    base = inner.rsplit("/", 1)[-1]
    dest = (p["dest_rel"] + "/" + inner) if p and p["dest_rel"] else None
    if inner.lower().endswith(IMAGE_EXT):
        return "purge", None, "phase-media"
    if base == ".gitkeep":
        return "purge", None, "phase-gitkeep"   # analyze() turns it back into keep when its folder would be left empty
    if "/" in inner:
        return "keep", dest, "unknown"
    for pat in PHASE_KEEP:
        if fnmatch.fnmatchcase(base, pat):
            return "keep", dest, "phase-doc"
    m = RE_PLAN.match(base)
    if m:
        paired = (m.group(1) + "-SUMMARY.md") in sc.tracked_names.get(key, ())
        return ("purge", None, "plan-done") if paired else ("keep", dest, "plan-open")
    for pat in PHASE_PURGE:
        if fnmatch.fnmatchcase(base, pat):
            return "purge", None, "phase-scratch"
    return "keep", dest, "unknown"


# ---- the plan ----------------------------------------------------------------------------------------------------------

def analyze(src, opts):
    entries = src.entries()
    if not entries:
        raise Refuse("0 files looked at: no %s/ in %s" % (SCOPE_SRC, src.repo if hasattr(src, "repo") else "the tree"))
    ctx = {"map": opts.get("map", {}), "close": set(opts.get("close", ())), "open": set(opts.get("open", ())), "used": set()}
    both = ctx["close"] & ctx["open"]
    if both:
        raise Refuse("--close and --open both name %s" % ", ".join(sorted(both)))
    scopes = split_scopes(entries)
    problems, notes, files = [], [], []
    for sc in scopes:
        sc.tracked_names = {}
        for inner, tracked, size in sc.files:
            m = RE_MS_PHASES.match(inner)
            if m:
                key = inner[:len(inner) - len(m.group(3)) - 1]
                rest = m.group(3)
            else:
                parts = inner.split("/")
                key, rest = ("phases/" + parts[1], "/".join(parts[2:])) if len(parts) >= 3 and parts[0] == "phases" else (None, None)
            if key and tracked and "/" not in rest:
                sc.tracked_names.setdefault(key, set()).add(rest)
        problems += build_phases(sc, src, ctx)
    unknown_keys = sorted((ctx["close"] | ctx["open"] | set(ctx["map"])) - ctx["used"])
    asked = ctx["close"] | ctx["open"]
    missing = [k for k in unknown_keys if k in asked]
    if missing:
        raise Refuse("--close/--open name no phase: %s" % ", ".join(missing))
    unused_map = [k for k in unknown_keys if k not in asked]
    if problems:
        raise Refuse("\n".join(problems))
    for sc in scopes:
        results = []
        for inner, tracked, size in sc.files:
            action, dest, rule = classify(sc, inner, tracked)
            results.append([inner, tracked, size, action, dest, rule])
        # a `.gitkeep` is purged unless its folder would be left with no file
        kept = [r[0] for r in results if r[3] == "keep" and r[5] != "phase-gitkeep"]
        for r in results:
            if r[5] == "phase-gitkeep" and r[1] and not any(k.startswith(os.path.dirname(r[0]) + "/") for k in kept):
                r[3], r[4], r[5] = "keep", place(sc, r[0]), "phase-gitkeep-last"
        for inner, tracked, size, action, dest, rule in results:
            files.append({"src": "%s/%s%s" % (SCOPE_SRC, sc.prefix, inner), "action": action,
                          "dest": "%s/%s" % (sc.dest, dest) if dest else None, "tracked": tracked, "bytes": size, "rule": rule})
        for p in sc.phases:
            if p["from_roadmap"] or not p["key"]:
                continue
            where = "%s/%s" % (sc.dest, p["dest_rel"])
            if not any(f["dest"] and f["dest"].startswith(where + "/") for f in files):
                notes.append("phase %s%s: every file is purged, so the folder will not exist at the destination %s" % (p["name"], sc.label(), where))
        notes += sc.notes
    if unused_map:
        notes.append("--milestone-map keys that matched no phase: %s" % ", ".join(unused_map))
    return scopes, sorted(files, key=lambda f: f["src"]), notes


def totals(files):
    t = {k: {"files": 0, "bytes": 0} for k in ("keep", "purge", "backlog", "unknown", "leftover_move", "leftover_delete")}
    for f in files:
        for k in (f["action"],) + (("unknown",) if f["rule"] == "unknown" and f["action"] == "keep" else ()):
            t[k]["files"] += 1
            t[k]["bytes"] += f["bytes"]
    return t


def backlog_items(scopes, src, files):
    out, seen = [], set()
    by = {f["src"]: f for f in files if f["action"] == "backlog"}
    for sc in scopes:
        for inner, tracked, size in sc.files:
            path = "%s/%s%s" % (SCOPE_SRC, sc.prefix, inner)
            if path not in by:
                continue
            parts = inner.split("/")
            if parts[0] in ("quick", "phases") and len(parts) >= 3:
                item = "/".join(parts[:2])
            else:
                item = inner
            full = "%s/%s%s" % (SCOPE_SRC, sc.prefix, item)
            if full in seen:
                continue
            seen.add(full)
            members = sorted(n for n, t, _ in sc.files if n == item or n.startswith(item + "/"))
            texts = [src.read(sc.prefix + n) for n in members if n.endswith(".md")]
            title = first_title(next((t for t in texts if t), None), parts[1] if len(parts) >= 3 else item)
            out.append({"src": full, "title": title})
    return sorted(out, key=lambda b: b["src"])


# ---- the map of a cited path, for `.gitignore` lines and for references ------------------------------------------------

class Mapper:
    def __init__(self, scopes, files):
        self.scopes = {sc.ws: sc for sc in scopes}
        self.files = {f["src"][len(SCOPE_SRC) + 1:]: f for f in files}

    def structure(self, rest):
        """Where `.planning/<rest>` goes by its shape alone (a folder, a glob, or a path the plan has no file for). A
        milestone it cannot know is `*`."""
        parts = [p for p in rest.split("/") if p]
        sc, head = self.scopes[None], SCOPE_DEST
        if len(parts) >= 2 and parts[0] == "workstreams":
            sc, head, parts = self.scopes.get(parts[1]), "%s/subprojects/%s" % (SCOPE_DEST, parts[1]), parts[2:]
        tail = parts
        if parts and parts[0] == "phases":
            known = [p for p in (sc.phases if sc else []) if len(parts) >= 2 and p["key"] == "phases/" + parts[1]]
            others = {p["milestone"] for p in (sc.phases if sc else []) if p["milestone"]}
            ms = known[0]["milestone"] if known else (others.pop() if len(others) == 1 else "*")
            tail = ["milestones", ms, "phases"] + parts[1:]
        elif len(parts) >= 2 and parts[0] == "milestones":
            g = re.match(r"v(\d+)\.\d+-phases\Z", parts[1])
            if g:
                tail = ["milestones", "v" + g.group(1), "phases"] + parts[2:]
            elif re.match(r"v\d+\.\d+-", parts[1]):
                tail = ["milestones", "v" + re.match(r"v(\d+)", parts[1]).group(1)] + parts[1:]
        elif len(parts) == 1 and sc and parts[0] in MILESTONE_DOCS:
            tail = ["milestones", sc.actual, parts[0]]
        return "/".join([head] + tail) + ("/" if rest.endswith("/") and tail else "")

    def cite(self, token):
        """(kind, new) of a token that starts with `.planning`: moved, purged or prefix."""
        rest = token[len(SCOPE_SRC):].lstrip("/")
        stem = rest.rstrip("/")
        if not stem or re.fullmatch(r"[*/]*", rest):
            return "prefix", SCOPE_DEST + token[len(SCOPE_SRC):]
        if not any(c in stem for c in "*?[") and stem in self.files:
            f = self.files[stem]
            if f["action"] in ("keep", "leftover_move"):
                return "moved", f["dest"]
            return "purged", None
        if any(c in stem for c in "*?["):
            hits = [f for n, f in self.files.items() if fnmatch.fnmatchcase(n, stem) or fnmatch.fnmatchcase(n, stem + "/*")]
        else:
            hits = [f for n, f in self.files.items() if n.startswith(stem + "/")]
        if hits and all(f["action"] in ("purge", "backlog", "leftover_delete") for f in hits):
            return "purged", None
        if hits:
            return "moved", self.structure(rest)
        return "prefix", SCOPE_DEST + token[len(SCOPE_SRC):]

    def gitignore(self, line):
        """The `.fwx` twin of a `.gitignore` line that names `.planning/`."""
        m = re.match(r"(!?/?)(\.planning)(/.*)?\Z", line.rstrip())
        if not m:
            return line.replace(SCOPE_SRC, SCOPE_DEST)
        rest = (m.group(3) or "/")[1:]
        stem = rest.rstrip("/")
        if stem and not any(c in stem for c in "*?[") and stem in self.files and self.files[stem]["dest"]:
            return m.group(1) + self.files[stem]["dest"] + ("/" if rest.endswith("/") else "")
        return m.group(1) + self.structure(rest) if rest else m.group(1) + SCOPE_DEST + "/"


RE_TOKEN = re.compile(r"(?<![A-Za-z0-9_])\.planning(?![A-Za-z0-9_-])(/[^\s\"'`<>()\[\]{},;|&$#]*)?")


def tokens(line, mapper):
    """(column, token, kind, new) of each `.planning` path of a line: the one reading of a line, so that what `refs` lists is
    what --rewrite and --prefix change."""
    for m in RE_TOKEN.finditer(line):
        token = m.group(0).rstrip(".:!?")
        kind, new = mapper.cite(token)
        yield m.start(), token, kind, new


def scan_refs(repo, mapper):
    out = []
    for p in _lines(repo, "ls-files", "-z"):
        if p.startswith(SCOPE_SRC + "/") or p.startswith(SCOPE_DEST + "/"):
            continue
        full = os.path.join(repo, p)
        try:
            if not os.path.isfile(full) or os.path.islink(full) or os.path.getsize(full) > MAX_SCAN:
                continue
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if SCOPE_SRC.encode() not in data or b"\0" in data[:8192]:
            continue
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            if SCOPE_SRC not in line:
                continue
            for _, token, kind, new in tokens(line, mapper):
                out.append({"file": p, "line": n, "old": token, "kind": kind, "new": new})
    return out


def git_facts(repo):
    """remote (credentials removed), ahead, the default branch and the unmerged branches that touch `.planning/`."""
    cur = _text(repo, "symbolic-ref", "--short", "-q", "HEAD") if _git(repo, "symbolic-ref", "-q", "HEAD", ok=(0, 1)).returncode == 0 else None
    remotes = _text(repo, "remote").split()
    remote = None
    if cur:
        r = _git(repo, "config", "--get", "branch.%s.remote" % cur, ok=(0, 1))
        remote = r.stdout.decode().strip() or None
    if remote not in remotes:
        remote = "origin" if "origin" in remotes else (remotes[0] if len(remotes) == 1 else None)
    url = None
    if remote:
        url = clean_url(_git(repo, "config", "--get", "remote.%s.url" % remote, ok=(0, 1)).stdout.decode().strip()) or None
    default, ahead = None, None
    if remote:
        r = _git(repo, "symbolic-ref", "-q", "refs/remotes/%s/HEAD" % remote, ok=(0, 1))
        cands = ([r.stdout.decode().strip()[len("refs/remotes/%s/" % remote):]] if r.returncode == 0 else []) + [c for c in (cur, "main", "master") if c]
        for c in cands:
            if (_git(repo, "rev-parse", "-q", "--verify", "refs/remotes/%s/%s" % (remote, c), ok=(0, 1)).returncode == 0
                    and _git(repo, "rev-parse", "-q", "--verify", "refs/heads/" + c, ok=(0, 1)).returncode == 0):
                default = c
                ahead = int(_text(repo, "rev-list", "--count", "%s/%s..%s" % (remote, c, c)))
                break
    base = default or cur or "HEAD"
    branches = []
    for b in _text(repo, "branch", "--no-merged", base, "--format=%(refname:short)").splitlines():
        b = b.strip()
        if not b:
            continue
        files = sorted(_lines(repo, "diff", "-z", "--name-only", "%s...%s" % (base, b), "--", SCOPE_SRC))
        if files:
            branches.append({"name": b, "files": files})
    return url, ahead, sorted(branches, key=lambda b: b["name"])


def build(repo, src, opts):
    scopes, files, notes = analyze(src, opts)
    mapper = Mapper(scopes, files)
    root = next(sc for sc in scopes if sc.ws is None)
    phases = []
    for sc in scopes:
        for p in sc.phases:
            if p["dest_rel"] is None:
                continue
            phases.append({"src": ("%s/%s" % (SCOPE_SRC, sc.prefix + p["key"])) if p["key"] else None,
                           "dest": "%s/%s" % (sc.dest, p["dest_rel"]), "milestone": p["milestone"], "closed": bool(p["closed"]),
                           "signals": {"checklist": p["checklist"], "pairing": p["pairing"]}, "from_roadmap": p["from_roadmap"]})
    gitignore = []
    path = os.path.join(repo, ".gitignore")
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f.read().splitlines():
                if SCOPE_SRC in line and not line.lstrip().startswith("#"):
                    gitignore.append({"old": line, "new": mapper.gitignore(line)})
    dests = {}
    for f in files:
        if f["dest"] and f["action"] in ("keep", "leftover_move"):
            dests.setdefault(f["dest"], []).append(f["src"])
    clash = ["%s <- %s" % (d, ", ".join(s)) for d, s in sorted(dests.items()) if len(s) > 1]
    if clash:
        raise Refuse("two files for one destination:\n  " + "\n  ".join(clash))
    return scopes, files, mapper, phases, gitignore, notes, root


# ---- output ------------------------------------------------------------------------------------------------------------

def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def render(doc, notes, files, refs_only=False):
    out = ["fwx migrate-gsd %s: %s" % ("refs" if refs_only else "plan", doc["repo"]),
           "base %s  remote %s  ahead %s  gsd milestone %s" % (doc["base"], doc["remote"] or "none",
                                                                 "n/a" if doc["ahead"] is None else doc["ahead"],
                                                                 doc["gsd_state"]["milestone"] or "none"),
           "%d files looked at in %d scope(s)" % (len(files), len(doc["scopes"]))]
    if not refs_only:
        out.append("scopes:")
        out += ["  %s -> %s" % (s["src"], s["dest"]) for s in doc["scopes"]]
        out.append("totals:")
        for k, v in doc["totals"].items():
            out.append("  %-15s %6d files  %10s%s" % (k, v["files"], human(v["bytes"]), "  (a subset of keep)" if k == "unknown" else ""))
        out.append("phases: %d" % len(doc["phases"]))
        for p in doc["phases"]:
            sg = p["signals"]
            flag = "  DISAGREE" if sg["checklist"] is not None and sg["checklist"] != sg["pairing"] else ""
            out.append("  %s -> %s  %s %s  checklist=%s pairing=%s%s%s" % (
                p["src"] or "(ROADMAP only)", p["dest"], p["milestone"], "closed" if p["closed"] else "open",
                {True: "x", False: "-", None: "none"}[sg["checklist"]], "yes" if sg["pairing"] else "no", flag,
                "  from_roadmap" if p["from_roadmap"] else ""))
        by_rule = {}
        for f in files:
            if f["action"] == "purge":
                by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
        out.append("purge by rule: " + (", ".join("%s %d" % kv for kv in sorted(by_rule.items())) or "none"))
        for title, pick in (("unknown (kept at their own path)", lambda f: f["action"] == "keep" and f["rule"] == "unknown"),
                            ("leftovers to move", lambda f: f["action"] == "leftover_move"),
                            ("leftovers to delete", lambda f: f["action"] == "leftover_delete")):
            rows = [f for f in files if pick(f)]
            out.append("%s: %d" % (title, len(rows)))
            out += ["  %s%s" % (f["src"], (" -> " + f["dest"]) if f["dest"] else "") for f in rows[:50]]
            if len(rows) > 50:
                out.append("  ... %d more (see --json)" % (len(rows) - 50))
        out.append("backlog (not migrated): %d" % len(doc["backlog"]))
        out += ["  %s  %s" % (b["src"], b["title"]) for b in doc["backlog"]]
        out.append(".gitignore lines: %d" % len(doc["gitignore"]))
        out += ["  %s  =>  %s" % (g["old"], g["new"]) for g in doc["gitignore"]]
    kinds = {}
    for r in doc["refs"]:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    out.append("refs: %d in %d file(s) (%s)" % (len(doc["refs"]), len({r["file"] for r in doc["refs"]}),
                                                  ", ".join("%s %d" % kv for kv in sorted(kinds.items())) or "none"))
    out += ["  %s:%d  %s  %s  %s" % (r["file"], r["line"], r["kind"], r["old"], r["new"] or "-") for r in doc["refs"][:100]]
    if len(doc["refs"]) > 100:
        out.append("  ... %d more (see --json)" % (len(doc["refs"]) - 100))
    if not refs_only:
        out.append("unmerged branches that touch .planning/: %d" % len(doc["branches"]))
        out += ["  %s  %d file(s)" % (b["name"], len(b["files"])) for b in doc["branches"]]
    if notes:
        out.append("notes:")
        out += ["  " + n for n in notes]
    return "\n".join(out) + "\n"


# ---- the write half: what every step shares --------------------------------------------------------------------------
# apply stages everything and commits nothing, so the commit it was started on (`base`) holds every file it removes or
# moves. It changes the repository in a fixed order (moves, removals, generated files, the `.gitignore` twins, staging, the
# checks); a step that raises, or a check that fails, puts the repository back to `base` and says so. A process killed in the
# middle cannot do that: it leaves MARKER in the git dir, and the next run refuses, naming the two commands that undo it.
MARKER = "fwx-migrate-gsd-apply"
RE_MS_DEST = re.compile(r"(\.fwx(?:/subprojects/[^/]+)?)/milestones/(v\d+)/")
RE_SECTION = re.compile(r"(#{2,4}) Phase (\d+(?:\.\d+)*): (.+)$")


class Failed(Exception):
    """A step or a check of the write half failed; the message says what, and whether the repository is back as it was."""


def _abs(repo, rel):
    return os.path.join(repo, *rel.split("/"))


def undo_commands(repo, base):
    """The two commands that put a repository back to `base` by hand: tracked files first, then the files apply made that git
    does not track (a folder of its own: `.fwx/`)."""
    return ["git -C %s restore --source=%s --staged --worktree -- ." % (shlex.quote(repo), base),
            "git -C %s clean -fd -- %s" % (shlex.quote(repo), SCOPE_DEST)]


def default_branches(repo):
    """The names that stand for the default branch: main and master, what each remote's HEAD points at, init.defaultBranch."""
    names = {"main", "master"}
    for remote in _text(repo, "remote").split():
        r = _git(repo, "symbolic-ref", "-q", "--short", "refs/remotes/%s/HEAD" % remote, ok=(0, 1))
        if r.returncode == 0 and r.stdout.strip():
            names.add(r.stdout.decode().strip().split("/", 1)[-1])
    r = _git(repo, "config", "--get", "init.defaultBranch", ok=(0, 1))
    if r.stdout.strip():
        names.add(r.stdout.decode().strip())
    return names


def status_tracked(repo):
    """Entries of `git status` for tracked files only (staged or not); empty when the tracked tree is clean."""
    out = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=no").stdout.decode("utf-8", "replace")
    return [e for e in out.split("\0") if e]


def status_all(repo):
    return _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout


def tree_entries(repo, sha=None):
    """{path: (mode, blob)} of the tracked files, from the index or, with `sha`, from that commit (`.planning/` only)."""
    out = {}
    if sha:
        for rec in _lines(repo, "ls-tree", "-r", "-z", sha, "--", SCOPE_SRC):
            meta, _, path = rec.partition("\t")
            mode, _, blob = meta.split()
            out[path] = (mode, blob)
    else:
        for rec in _lines(repo, "ls-files", "-s", "-z"):
            meta, _, path = rec.partition("\t")
            mode, blob, _stage = meta.split()
            out[path] = (mode, blob)
    return out


def pin_existing(repo, entries):
    """{key: vN} for every phase folder of `.planning/` whose folder already exists at the destination, in one milestone: the
    new files of a merge, or the ignored ones of `leftovers`, go where the phase already is, because the ROADMAP and STATE
    that decided its milestone are gone by then. A name that two scopes share is not pinned (a key without a workstream
    would name both)."""
    names = {}
    for rel, tracked, size in entries:
        parts = rel.split("/")
        ws = None
        if parts[0] == "workstreams" and len(parts) >= 3:
            ws, parts = parts[1], parts[2:]
        if len(parts) >= 3 and parts[0] == "phases" and RE_PHASE_DIR.match(parts[1]) and not parts[1].startswith("999."):
            names.setdefault(parts[1], set()).add(ws)
    pins = {}
    for name, wss in names.items():
        if len(wss) != 1:
            continue
        ws = next(iter(wss))
        dest = SCOPE_DEST if ws is None else "%s/subprojects/%s" % (SCOPE_DEST, ws)
        found = {os.path.basename(os.path.dirname(os.path.dirname(p))) for p in
                 glob.glob(os.path.join(glob.escape(repo), glob.escape(dest), "milestones", "v[0-9]*", "phases", glob.escape(name)))
                 if os.path.isdir(p)}
        if len(found) == 1:
            pins[name if ws is None else "%s/%s" % (ws, name)] = found.pop()
    return pins


def with_pins(opts, pins):
    """The options with the pins behind the owner's own --milestone-map keys: the first key that names a phase wins."""
    out = dict(opts)
    out["map"] = dict(opts["map"])
    for k, v in pins.items():
        out["map"].setdefault(k, v)
    return out


def collisions(repo, dests):
    """The destinations that cannot be written: one that exists, one under a path that is a file or a link."""
    bad = []
    for d in sorted(set(dests)):
        a = _abs(repo, d)
        if os.path.lexists(a):
            bad.append("%s exists" % d)
            continue
        parent = os.path.dirname(a)
        while len(parent) > len(repo):
            if os.path.lexists(parent):
                if os.path.islink(parent) or not os.path.isdir(parent):
                    bad.append("%s: %s is not a folder" % (d, os.path.relpath(parent, repo)))
                break
            parent = os.path.dirname(parent)
    return bad


def ignored_among(repo, paths):
    """The paths of the list that git would ignore (`git check-ignore`; one that is already tracked is never ignored)."""
    if not paths:
        return set()
    r = _git(repo, "check-ignore", "-z", "--stdin", ok=(0, 1), input="\0".join(paths).encode("utf-8") + b"\0")
    return {p for p in r.stdout.decode("utf-8", "replace").split("\0") if p}


def roadmap_section(text, number):
    """The text of a ROADMAP's `### Phase N: title` section, up to the next heading of its own level or a higher one."""
    lines = (text or "").splitlines(keepends=True)
    want = tuple(int(n) for n in number.split("."))
    for i, line in enumerate(lines):
        m = RE_SECTION.match(line.rstrip("\r\n"))
        if m and tuple(int(n) for n in m.group(2).split(".")) == want:
            stop = re.compile(r"#{1,%d} " % len(m.group(1)))
            j = i + 1
            while j < len(lines) and not stop.match(lines[j]):
                j += 1
            return "".join(lines[i:j])
    return None


def milestone_text(ms, base, totals_, state_ms):
    """MILESTONE.md of the framework's template (2.3), with the milestone's name as its goal and the block that says where the
    files came from and how to get a removed one back."""
    t = state._read_template("MILESTONE.md")
    t = t.replace("<vN>", ms).replace("<name>", ms)
    t = t.replace("<What is true when this milestone is done, in a paragraph.>",
                  "%s, as GSD left it%s: its phases and documents keep their GSD names." % (ms, " (STATE said %s)" % state_ms if state_ms else ""))
    t = t.replace("In: <what the milestone covers.>", "In: everything GSD tracked for it.")
    t = t.replace("Out: <what it leaves for later, each with the reason.>", "Out: nothing on purpose; what was removed is listed below.")
    n = lambda k: totals_[k]["files"]
    block = ("\n## Migrated from GSD\n\n"
             "- Base commit: %s (the last commit that holds the old `.planning/`)\n"
             "- Date: %s\n"
             "- Whole conversion: %d files kept (%d unknown to GSD, kept at their own path), %d purged, %d of backlog not migrated, "
             "%d ignored or untracked files left for `fwx migrate-gsd leftovers`\n"
             "- Get a removed file back: `git show %s:.planning/<path>` (inside a workstream: `.planning/workstreams/<name>/<path>`)\n"
             % (base, datetime.now(timezone.utc).strftime("%Y-%m-%d"), n("keep"), n("unknown"), n("purge"), n("backlog"),
                n("leftover_move") + n("leftover_delete"), base))
    return (t.rstrip("\n") + "\n" + block).encode("utf-8")


# ---- apply ------------------------------------------------------------------------------------------------------------

class Job:
    """What apply is going to do, and what it has done so far (the rollback needs the second)."""

    def __init__(self, repo, base):
        self.repo, self.base = repo, base
        self.moves, self.removes, self.gens, self.audit_rows, self.twins = [], [], [], [], []
        self.stage = []              # paths to `git add` after the files are written
        self.created, self.dirs = [], []   # files and folders apply made (the rollback removes them)
        self.phases = []             # (scope dest, milestone, folder dest, closed, from_roadmap)
        self.base_entries, self.before = {}, None
        self.marker = None
        self.closed = []


def plan_apply(repo, opts):
    """Every refusal of apply, in order, and then the Job. Reads only."""
    r = _git(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}", ok=(0, 1))
    if r.returncode:
        raise Refuse("%s has no commit yet" % repo)
    base = r.stdout.decode().strip()
    r = _git(repo, "symbolic-ref", "-q", "--short", "HEAD", ok=(0, 1))
    if r.returncode:
        raise Refuse("HEAD is detached: apply runs on a branch of its own, not on the default branch")
    branch = r.stdout.decode().strip()
    if branch in default_branches(repo):
        raise Refuse("%s is the default branch: apply runs on a branch of its own, in a worktree "
                     "(git worktree add .claude/worktrees/fwx-migrate-gsd -b fwx-migrate-gsd %s)" % (branch, branch))
    gitdir = _text(repo, "rev-parse", "--absolute-git-dir")
    marker = os.path.join(gitdir, MARKER)
    dirty = status_tracked(repo)
    # the marker of an apply that stopped in the middle blocks only while the repository still shows it: once the two
    # commands it names have run, the files are clean and a stale marker is just overwritten
    if os.path.exists(marker) and (dirty or _lines(repo, "ls-files", "-z", "--others", "--exclude-standard", "--", SCOPE_DEST)):
        raise Refuse("a previous apply stopped in the middle (%s exists) and left %s half converted. Undo it with:\n  %s"
                     % (marker, repo, "\n  ".join(undo_commands(repo, base))))
    if dirty:
        raise Refuse("the tracked files are not clean, so what apply removes might not be recoverable from %s (%d entries, "
                     "first: %s). Commit or discard them first." % (base[:12], len(dirty), "; ".join(dirty[:5])))
    for rec in _lines(repo, "ls-files", "-s", "-z", "--", SCOPE_SRC):
        if rec.startswith("160000 "):
            raise Refuse("%s is a submodule inside .planning/: apply does not move those, move it by hand first"
                         % rec.partition("\t")[2])
    src = WorkTree(repo)
    scopes, files, mapper, phases, gitignore, notes, root = build(repo, src, with_pins(opts, pin_existing(repo, src.entries())))
    job = Job(repo, base)
    job.before = status_all(repo)
    job.base_entries = tree_entries(repo, base)
    job.moves = [(f["src"], f["dest"]) for f in files if f["tracked"] and f["action"] == "keep"]
    job.removes = [f["src"] for f in files if f["tracked"] and f["action"] in ("purge", "backlog")]
    if not job.moves and not job.removes:
        raise Refuse("0 tracked files to convert: .planning/ holds only ignored or untracked files, which `leftovers` moves "
                     "after the merge")
    job.files, job.scopes, job.mapper, job.notes, job.phase_docs, job.totals = files, scopes, mapper, notes, phases, totals(files)
    job.root_state = getattr(root, "state_milestone", None)
    job.backlog = backlog_items(scopes, src, files)
    job.leftover = [f for f in files if not f["tracked"]]
    roadmaps = {sc.ws: src.read(sc.prefix + "ROADMAP.md") for sc in scopes}
    milestones, dests = set(), [d for _, d in job.moves]
    for sc in scopes:
        for p in sc.phases:
            if p["dest_rel"] is None:
                continue
            dest = "%s/%s" % (sc.dest, p["dest_rel"])
            milestones.add((sc.dest, p["milestone"]))
            job.phases.append((sc.dest, p["milestone"], dest, bool(p["closed"]), p["from_roadmap"]))
            if p["from_roadmap"]:
                section = roadmap_section(roadmaps[sc.ws], ".".join(str(n) for n in p["num"])) or ("### Phase %s\n" % p["title"])
                job.gens.append((dest + "/gsd-roadmap-entry.md", section.encode("utf-8")))
            elif p["closed"]:
                if not state.last_stage(_abs(repo, dest)):
                    job.audit_rows.append((dest, "closed migrated-from-gsd %s" % base))
                job.closed.append(dest)
            elif not any(d.startswith(dest + "/") for d in dests) and not os.path.isdir(_abs(repo, dest)):
                job.gens.append((dest + "/.gitkeep", b""))
    for d in dests:
        m = RE_MS_DEST.match(d)
        if m:
            milestones.add((m.group(1), m.group(2)))
    taken = set(dests)
    for scope_dest, ms in sorted(milestones):
        rel = "%s/milestones/%s/MILESTONE.md" % (scope_dest, ms)
        if rel not in taken and not os.path.lexists(_abs(repo, rel)):
            job.gens.append((rel, milestone_text(ms, base, job.totals, job.root_state)))
    job.twins = [g for g in gitignore if g["new"] != g["old"]] if os.path.isfile(os.path.join(repo, ".gitignore")) \
        and _lines(repo, "ls-files", "-z", "--", ".gitignore") else []
    bad = collisions(repo, dests + [g for g, _ in job.gens])
    if bad:
        raise Refuse("a destination is in the way, nothing was written:\n  " + "\n  ".join(bad[:30])
                     + ("\n  ... %d more" % (len(bad) - 30) if len(bad) > 30 else ""))
    hidden = sorted(ignored_among(repo, dests + [g for g, _ in job.gens]))
    if hidden:
        raise Refuse("a destination is ignored by .gitignore, so git would not keep it:\n  " + "\n  ".join(hidden[:30]))
    return job, branch


def mkdirs(job, path):
    missing, p = [], path
    while not os.path.isdir(p):
        missing.append(p)
        p = os.path.dirname(p)
    for d in reversed(missing):
        os.mkdir(d)
        job.dirs.append(d)


def move_file(job, src, dest):
    mkdirs(job, os.path.dirname(_abs(job.repo, dest)))
    _git(job.repo, "--literal-pathspecs", "mv", "--", src, dest)


def step_moves(job):
    for src, dest in job.moves:
        move_file(job, src, dest)


def step_removes(job):
    if job.removes:
        _git(job.repo, "--literal-pathspecs", "rm", "-q", "--pathspec-from-file=-", "--pathspec-file-nul",
             input=b"".join(p.encode("utf-8") + b"\0" for p in job.removes))


def step_generate(job):
    for rel, data in job.gens:
        a = _abs(job.repo, rel)
        mkdirs(job, os.path.dirname(a))
        with open(a, "xb") as f:
            f.write(data)
        job.created.append(a)
        job.stage.append(rel)
    for dest, detail in job.audit_rows:
        a = _abs(job.repo, dest)
        mkdirs(job, a)
        audit = str(state.phase_paths(a)["audit"])
        if not os.path.exists(audit):
            job.created.append(audit)
        state.append_audit(a, "stage", detail, sha=job.base)
        job.stage.append(os.path.relpath(audit, job.repo))


def step_gitignore(job):
    """Under each `.gitignore` line that names `.planning/`, its `.fwx/` twin; the old line stays. Line endings are kept."""
    if not job.twins:
        return
    path = os.path.join(job.repo, ".gitignore")
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", "surrogateescape")
    lines = text.splitlines(keepends=True)
    have = {l.rstrip("\r\n") for l in lines}
    pending = {g["old"]: g["new"] for g in job.twins}
    out = []
    for line in lines:
        bare = line.rstrip("\r\n")
        out.append(line)
        new = pending.get(bare)
        if new is not None and new not in have:
            eol = line[len(bare):] or "\n"
            if not line[len(bare):]:
                out[-1] = line + "\n"
            out.append(new + eol)
            have.add(new)
    if out != lines:
        with open(path, "wb") as f:
            f.write("".join(out).encode("utf-8", "surrogateescape"))
        job.stage.append(".gitignore")


def step_stage(job):
    if job.stage:
        _git(job.repo, "--literal-pathspecs", "add", "--pathspec-from-file=-", "--pathspec-file-nul",
             input=b"".join(p.encode("utf-8") + b"\0" for p in job.stage))


def verify(job):
    """The checks after the work, each against what git says and not against what the steps meant: the blob of every kept file
    is the same at its destination, every purged or backlog file is gone, `state.phases` sees each phase folder and
    `state.last_stage` says closed for each closed one."""
    repo, problems = job.repo, []
    now = tree_entries(repo)
    for src, dest in job.moves:
        if now.get(dest) != job.base_entries.get(src):
            problems.append("blob changed: %s -> %s (base %s, now %s)" % (src, dest, job.base_entries.get(src), now.get(dest)))
    changed = [p for p in _lines(repo, "diff", "--name-only", "-z") if not p.startswith(SCOPE_SRC + "/")]
    if changed:
        problems.append("a file differs on disk from what was staged: %s" % ", ".join(changed[:5]))
    for src in job.removes:
        if src in now or os.path.lexists(_abs(repo, src)):
            problems.append("purged file still there: %s" % src)
    left = sorted(p for p in now if p.startswith(SCOPE_SRC + "/"))
    if left:
        problems.append("%d tracked file(s) still under .planning/, first %s" % (len(left), left[0]))
    for rel, _data in job.gens:
        if rel not in now:
            problems.append("generated file not staged: %s" % rel)
    for scope_dest, ms, dest, closed, from_roadmap in job.phases:
        try:
            names = [p.name for p in state.phases(Path(repo) / scope_dest, ms)]
        except state.StateError as e:
            names = []
            problems.append("state.phases(%s, %s): %s" % (scope_dest, ms, e))
        if os.path.basename(dest) not in names:
            problems.append("state.phases does not see %s" % dest)
    for dest in job.closed:
        if state.last_stage(_abs(repo, dest)) != "closed":
            problems.append("state.last_stage of %s is not closed" % dest)
    if problems:
        raise Failed("a check after the work failed:\n  " + "\n  ".join(problems[:20])
                     + ("\n  ... %d more" % (len(problems) - 20) if len(problems) > 20 else ""))


def rollback(job):
    """Put the repository back to `base`; the list of what could not be checked or done (empty: it is back, and the status
    equals the one before)."""
    repo, errs = job.repo, []
    try:
        _git(repo, "restore", "--source=" + job.base, "--staged", "--worktree", "--", ".")
    except Refuse as e:
        errs.append(str(e))
    for a in job.created:
        try:
            if os.path.lexists(a):
                os.remove(a)
        except OSError as e:
            errs.append("cannot remove %s: %s" % (a, e))
    for d in reversed(job.dirs):
        try:
            os.rmdir(d)
        except OSError:
            pass
    try:
        if status_all(repo) != job.before:
            errs.append("git status is not what it was before apply")
        if _git(repo, "diff", "--cached", "--quiet", ok=(0, 1)).returncode:
            errs.append("the index is not what it was before apply")
    except Refuse as e:
        errs.append(str(e))
    return errs


def execute(job):
    """Run the steps; on any failure, roll back. A Failed says whether the repository is back."""
    gitdir = _text(job.repo, "rev-parse", "--absolute-git-dir")
    job.marker = os.path.join(gitdir, MARKER)
    try:
        with open(job.marker, "w", encoding="utf-8") as f:
            f.write("apply started on %s\nbase %s\nundo:\n  %s\n" % (job.repo, job.base, "\n  ".join(undo_commands(job.repo, job.base))))
    except OSError as e:
        raise Refuse("cannot write %s (%s): nothing was changed" % (job.marker, e))
    try:
        step_moves(job)
        step_removes(job)
        step_generate(job)
        step_gitignore(job)
        step_stage(job)
        verify(job)
    except BaseException as e:
        try:
            errs = rollback(job)
        except Exception as e2:   # a rollback that crashes is a rollback that did not finish: keep the marker
            errs = ["the rollback itself failed: %s: %s" % (type(e2).__name__, e2)]
        if not errs:
            os.remove(job.marker)
        if not isinstance(e, Exception):
            raise
        what = str(e) if isinstance(e, Failed) else "%s: %s" % (type(e).__name__, e)
        raise Failed("%s\n%s\nto undo by hand:\n  %s" % (
            what, "the repository is back as it was before apply (status and index compared)" if not errs
            else "the repository could NOT be put back (%s); %s stays, and apply refuses to run until it is undone"
            % ("; ".join(errs), job.marker), "\n  ".join(undo_commands(job.repo, job.base))))
    os.remove(job.marker)


def cmd_apply(repo, got):
    job, branch = plan_apply(repo, options(got))
    execute(job)
    n_left = len(job.leftover)
    doc = {"schema": SCHEMA, "repo": repo, "base": job.base, "branch": branch, "moved": len(job.moves), "removed": len(job.removes),
           "generated": [g for g, _ in job.gens], "closed": [{"dest": d, "row": r} for d, r in job.audit_rows],
           "gitignore": job.twins, "backlog": job.backlog, "leftover": n_left, "totals": job.totals,
           "recover": "git show %s:.planning/<path>" % job.base,
           "next": ["fwx migrate-gsd refs --base %s [--rewrite FILE...] [--prefix FILE...]" % job.base, "git commit"]}
    if "--json" in got:
        sys.stdout.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        for n in job.notes:
            sys.stderr.write("fwx migrate-gsd: note: %s\n" % n)
        return 0
    out = ["fwx migrate-gsd apply: %s (branch %s)" % (repo, branch),
           "base %s: every removed or moved file is there; get one back with `git show %s:.planning/<path>`" % (job.base, job.base),
           "moved %d, removed %d (purge %d, backlog %d), generated %d, stage rows %d, .gitignore twins %d; all staged, nothing committed"
           % (len(job.moves), len(job.removes), job.totals["purge"]["files"], job.totals["backlog"]["files"], len(job.gens),
              len(job.audit_rows), len(job.twins)),
           "checks passed: the blob of each of the %d kept files is the same at its destination, each of the %d removed files is gone, "
           "state.phases sees %d phase folder(s), state.last_stage says closed for %d" % (len(job.moves), len(job.removes),
                                                                                       len(job.phases), len(job.closed)),
           "ignored or untracked files left where they are for `fwx migrate-gsd leftovers`: %d" % n_left,
           "backlog (not migrated, recover with the base): %d" % len(job.backlog)]
    out += ["  %s  %s" % (b["src"], b["title"]) for b in job.backlog]
    if job.notes:
        out.append("notes:")
        out += ["  " + n for n in job.notes]
    out.append("next: fwx migrate-gsd refs --base %s, then commit" % job.base)
    sys.stdout.write("\n".join(out) + "\n")
    return 0


# ---- refs --rewrite and --prefix --------------------------------------------------------------------------------------

def dest_exists(repo, new):
    if any(c in new for c in "*?["):
        return bool(glob.glob(os.path.join(glob.escape(repo), new)))
    return os.path.lexists(_abs(repo, new.rstrip("/")))


def rewrite_line(line, mapper, repo, mode):
    """(new line, [(old, new, kind)] changed, [(old, kind, why)] left). `rewrite` changes the paths that moved and whose new
    place exists; `prefix` changes `.planning` for `.fwx` in every path. One pass over the tokens, so a longer path is never
    cut by a shorter one and nothing is changed twice."""
    out, last, changed, left = [], 0, [], []
    for col, token, kind, new in tokens(line, mapper):
        if mode == "prefix":
            repl = SCOPE_DEST + token[len(SCOPE_SRC):]
        elif kind != "moved":
            left.append((token, kind, "it names a file the conversion removed" if kind == "purged"
                         else "it is a path of tool configuration: --prefix"))
            continue
        elif new is None or ("milestones/*/" in new and "milestones/*/" not in token):
            left.append((token, kind, "its milestone is not one"))
            continue
        elif not dest_exists(repo, new):
            left.append((token, kind, "%s does not exist (run it with the --milestone-map of apply)" % new))
            continue
        else:
            repl = new
        out.append(line[last:col])
        out.append(repl)
        last = col + len(token)
        changed.append((token, repl, kind))
    out.append(line[last:])
    return "".join(out), changed, left


def named_files(repo, names):
    """The repo-relative path of each named file, each checked: inside the repo, tracked, outside `.planning/` and `.fwx/`, a
    regular text file that reads as UTF-8, with no edit of its own waiting."""
    tracked = set(_lines(repo, "ls-files", "-z"))
    out = {}
    for n in names:
        full = os.path.abspath(n)
        full = os.path.join(os.path.realpath(os.path.dirname(full)), os.path.basename(full))
        rel = os.path.relpath(full, repo).replace(os.sep, "/")
        if rel.startswith("../") or rel == "..":
            raise Refuse("%s is outside the repository %s" % (n, repo))
        if rel.startswith((SCOPE_SRC + "/", SCOPE_DEST + "/")):
            raise Refuse("%s is inside %s/ or %s/: refs changes the files that cite them, not those" % (n, SCOPE_SRC, SCOPE_DEST))
        if rel not in tracked:
            raise Refuse("%s is not a tracked file of %s" % (n, repo))
        if os.path.islink(full) or not os.path.isfile(full):
            raise Refuse("%s is not a regular file" % n)
        if os.path.getsize(full) > MAX_SCAN:
            raise Refuse("%s is over %d bytes: not rewritten" % (n, MAX_SCAN))
        if _lines(repo, "--literal-pathspecs", "diff", "--name-only", "-z", "--", rel):
            raise Refuse("%s has changes that are not staged: commit or stage them first, refs would stage them with its own" % n)
        out[rel] = full
    return out


def _write_bytes(path, data):
    with open(path, "wb") as f:
        f.write(data)


def apply_rewrites(repo, mapper, rewrite, prefix):
    """Rewrite and stage the named files. Everything is read and checked first; if a write fails, the files already written go
    back to their bytes. Returns ([(file, line, old, new, kind)], [(file, line, old, kind, why)])."""
    both = set(rewrite) & set(prefix)
    if both:
        raise Refuse("named for both --rewrite and --prefix: %s" % ", ".join(sorted(both)))
    todo = [("rewrite", rewrite), ("prefix", prefix)]
    plan, originals = [], {}
    for mode, names in todo:
        for rel, full in named_files(repo, names).items():
            with open(full, "rb") as f:
                raw = f.read()
            if b"\0" in raw:
                raise Refuse("%s is binary: not rewritten" % rel)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise Refuse("%s is not UTF-8: not rewritten" % rel)
            originals[rel] = (full, raw)
            plan.append((mode, rel, full, text))
    changed, left, writes = [], [], []
    for mode, rel, full, text in plan:
        new_lines = []
        for n, line in enumerate(text.splitlines(keepends=True), 1):
            if SCOPE_SRC in line:
                body = line.rstrip("\r\n")
                nl, ch, lf = rewrite_line(body, mapper, repo, mode)
                line = nl + line[len(body):]
                changed += [(rel, n, o, w, k) for o, w, k in ch]
                left += [(rel, n, o, k, why) for o, k, why in lf]
            new_lines.append(line)
        new = "".join(new_lines)
        if new != text:
            writes.append((rel, full, new.encode("utf-8")))
    done = []
    try:
        for rel, full, data in writes:
            _write_bytes(full, data)
            done.append(rel)
        if writes:
            _git(repo, "--literal-pathspecs", "add", "--pathspec-from-file=-", "--pathspec-file-nul",
                 input=b"".join(rel.encode("utf-8") + b"\0" for rel, _, _ in writes))
    except BaseException as e:
        for rel in done:
            full, raw = originals[rel]
            _write_bytes(full, raw)
        if not isinstance(e, Exception):
            raise
        raise Failed("%s: %s; the files already rewritten were put back" % (type(e).__name__, e))
    return changed, left


# ---- leftovers ----------------------------------------------------------------------------------------------------------

def nested_root(src):
    """The folder of a nested repository a path belongs to (the part before its `.git`), or None."""
    i = src.find("/.git/")
    if i < 0 and src.endswith("/.git"):
        i = len(src) - len("/.git")
    return src[:i] if i > len(SCOPE_SRC) else None


def group_of(src, groups):
    """The outermost nested repository of `groups` that holds the path, or None."""
    hits = [r for r in groups if src.startswith(r + "/")]
    return min(hits, key=len) if hits else None


def plan_leftovers(repo, opts):
    """(moves [(src, dest, ignored)], deletes [src], nested {root: dest}), after every refusal. Reads only."""
    tracked = _lines(repo, "ls-files", "-z", "--", SCOPE_SRC)
    if tracked:
        raise Refuse("%d file(s) under .planning/ are still tracked, first %s: apply and merge the conversion first"
                     % (len(tracked), tracked[0]))
    src = WorkTree(repo)
    entries = src.entries()
    pins = pin_existing(repo, entries)
    scopes, files, mapper, phases, gitignore, notes, root = build(repo, src, with_pins(opts, pins))
    unplaced = []
    for sc in scopes:
        for p in sc.phases:
            if p["key"] and p["ms"] is None and not any(key_hits(k, sc.ws, p["name"], p["num"]) for k in with_pins(opts, pins)["map"]):
                unplaced.append("%s%s" % (p["name"], sc.label()))
    if unplaced:
        raise Refuse("no folder of these phases exists under %s/, so where their files go is a guess: %s. Give --milestone-map "
                     "or run apply for them first" % (SCOPE_DEST, ", ".join(unplaced)))
    ignored = set()
    for p in _lines(repo, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", SCOPE_SRC):
        ignored.update(src.expand(p))
    moves = [(f["src"], f["dest"], f["src"] in ignored) for f in files if f["action"] == "leftover_move"]
    deletes = [f["src"] for f in files if f["action"] == "leftover_delete"]
    bad = collisions(repo, [d for _, d, _ in moves])
    if bad:
        raise Refuse("a destination is in the way, nothing was moved:\n  " + "\n  ".join(bad[:30]))
    visible = ignored_among(repo, [d for _, d, ig in moves if ig])
    exposed = [d for _, d, ig in moves if ig and d not in visible]
    if exposed:
        raise Refuse("%d ignored file(s) would stop being ignored at their destination (no .gitignore line names it, apply adds "
                     "those): nothing was moved. First %s" % (len(exposed), exposed[0]))
    groups = {}
    for r in sorted({r for r in (nested_root(s) for s, _, _ in moves) if r}):
        members = [(s, d) for s, d, _ in moves if s.startswith(r + "/")]
        dests = {d[:len(d) - (len(s) - len(r))] for s, d in members if d.endswith(s[len(r):])}
        if len(dests) == 1 and all(d.endswith(s[len(r):]) for s, d in members):
            groups[r] = dests.pop()
    return moves, deletes, groups, notes


def prune_empty(repo):
    """Remove the folders of `.planning/` that hold no file, `.planning/` itself last. Never a folder with anything in it."""
    top = os.path.join(repo, SCOPE_SRC)
    for dirpath, dirnames, filenames in os.walk(top, topdown=False):
        if not os.listdir(dirpath):
            os.rmdir(dirpath)
    return not os.path.lexists(top)


def cmd_leftovers(repo, got):
    do = "--apply" in got
    top = os.path.join(repo, SCOPE_SRC)
    if not os.path.lexists(top):
        if os.path.isdir(os.path.join(repo, SCOPE_DEST)):
            sys.stdout.write("fwx migrate-gsd leftovers: nothing to do, there is no .planning/ in %s (0 files looked at)\n" % repo)
            return 0
        raise Refuse("0 files looked at: neither .planning/ nor .fwx/ in %s" % repo)
    if not WorkTree(repo).entries() and not _lines(repo, "ls-files", "-z", "--", SCOPE_SRC):
        left = [p for _, _, fs in os.walk(top) for p in fs]
        if not left:
            if do:
                prune_empty(repo)
            sys.stdout.write("fwx migrate-gsd leftovers%s: .planning/ holds only empty folders: %s\n"
                             % ("" if do else " (dry run)", "removed" if do else "would be removed"))
            return 0
    moves, deletes, groups, notes = plan_leftovers(repo, options(got))
    out = ["fwx migrate-gsd leftovers%s: %s" % ("" if do else " (dry run)", repo),
           "%d file(s) to move (%d ignored: each stays ignored at its destination, checked with git check-ignore), %d machine-state "
           "file(s) to delete (a copy of each goes to the git dir first), %d nested repositor%s moved whole"
           % (len(moves), sum(1 for m in moves if m[2]), len(deletes), len(groups), "y" if len(groups) == 1 else "ies")]
    out += ["  move %s -> %s%s" % (s, d, "" if ig else "  (untracked)") for s, d, ig in moves[:50]]
    if len(moves) > 50:
        out.append("  ... %d more" % (len(moves) - 50))
    out += ["  delete %s" % s for s in deletes]
    out += ["note: " + n for n in notes]
    if not do:
        out.append("nothing was changed: --apply does it")
        sys.stdout.write("\n".join(out) + "\n")
        return 0
    journal = Journal2(repo)
    try:
        journal.save_deleted(deletes)
        done_groups = set()
        for s, d, ig in moves:
            r = group_of(s, groups)
            if r:
                if r not in done_groups:
                    done_groups.add(r)
                    journal.rename(r, groups[r])
                continue
            journal.rename(s, d)
        for s in deletes:
            journal.delete(s)
        problems = [d for s, d, ig in moves if not os.path.lexists(_abs(repo, d))]
        problems += [s for s, d, ig in moves if os.path.lexists(_abs(repo, s))]
        stayed = ignored_among(repo, [d for s, d, ig in moves if ig])
        problems += [d for s, d, ig in moves if ig and d not in stayed]
        if problems:
            raise Failed("a check after the moves failed: %s" % ", ".join(problems[:5]))
    except BaseException as e:
        errs = journal.undo()
        if not isinstance(e, Exception):
            raise
        what = str(e) if isinstance(e, Failed) else "%s: %s" % (type(e).__name__, e)
        raise Failed("%s\n%s" % (what, "everything moved was put back" if not errs else "NOT everything could be put back: " + "; ".join(errs)))
    gone = prune_empty(repo)
    out.append("done: %d moved, %d deleted (copies in %s)%s" % (len(moves), len(deletes), journal.trash if deletes else "-",
                                                              "; .planning/ is gone" if gone else "; .planning/ still holds files"))
    sys.stdout.write("\n".join(out) + "\n")
    return 0


class Journal2:
    """The moves and deletes of `leftovers`, so that a failure can put them back. A deleted file is copied to the git dir
    first, not recoverable from git (it was never tracked) but not lost either."""

    def __init__(self, repo):
        self.repo, self.renames, self.dirs, self.deleted = repo, [], [], []
        common = _text(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        self.trash = os.path.join(common, "fwx", "migrate-gsd", "deleted", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    def save_deleted(self, deletes):
        for s in deletes:
            t = os.path.join(self.trash, *s.split("/"))
            os.makedirs(os.path.dirname(t), exist_ok=True)
            shutil.copy2(_abs(self.repo, s), t, follow_symlinks=False)

    def rename(self, s, d):
        a, b = _abs(self.repo, s), _abs(self.repo, d)
        missing, p = [], os.path.dirname(b)
        while not os.path.isdir(p):
            missing.append(p)
            p = os.path.dirname(p)
        for m in reversed(missing):
            os.mkdir(m)
            self.dirs.append(m)
        os.rename(a, b)
        self.renames.append((a, b))

    def delete(self, s):
        os.remove(_abs(self.repo, s))
        self.deleted.append(s)

    def undo(self):
        errs = []
        for a, b in reversed(self.renames):
            try:
                os.makedirs(os.path.dirname(a), exist_ok=True)
                os.rename(b, a)
            except OSError as e:
                errs.append("cannot move %s back: %s" % (b, e))
        for s in self.deleted:
            try:
                a = _abs(self.repo, s)
                os.makedirs(os.path.dirname(a), exist_ok=True)
                shutil.copy2(os.path.join(self.trash, *s.split("/")), a, follow_symlinks=False)
            except OSError as e:
                errs.append("cannot restore %s: %s" % (s, e))
        for d in reversed(self.dirs):
            try:
                os.rmdir(d)
            except OSError:
                pass
        return errs


# ---- the command ---------------------------------------------------------------------------------------------------------

def parse(argv, flags, valued):
    got, i = {}, 0
    while i < len(argv):
        a = argv[i]
        name, eq, val = a.partition("=")
        if name in valued:
            if not eq:
                i += 1
                if i >= len(argv):
                    raise Refuse("%s needs a value\n%s" % (name, USAGE.rstrip()))
                val = argv[i]
            got[name] = val
        elif a in flags:
            got[a] = True
        else:
            raise Refuse("unexpected argument %s\n%s" % (a, USAGE.rstrip()))
        i += 1
    return got


def parse_refs(argv):
    """`refs` takes `--rewrite` and `--prefix` with one or more files each (`--rewrite A B --prefix C`, or `--rewrite=A`)."""
    got, i = {"--rewrite": [], "--prefix": []}, 0
    while i < len(argv):
        a = argv[i]
        name, eq, val = a.partition("=")
        if name in ("--rewrite", "--prefix"):
            if eq:
                got[name].append(val)
                i += 1
                continue
            i += 1
            n = 0
            while i < len(argv) and not argv[i].startswith("--"):
                got[name].append(argv[i])
                i += 1
                n += 1
            if not n:
                raise Refuse("%s needs at least one file\n%s" % (name, USAGE.rstrip()))
            continue
        if name in ("--base", "--milestone-map"):
            if not eq:
                i += 1
                if i >= len(argv):
                    raise Refuse("%s needs a value\n%s" % (name, USAGE.rstrip()))
                val = argv[i]
            got[name] = val
        elif a == "--json":
            got[a] = True
        else:
            raise Refuse("unexpected argument %s\n%s" % (a, USAGE.rstrip()))
        i += 1
    return got


def repo_of(cwd):
    r = _git(cwd, "rev-parse", "--show-toplevel", ok=(0, 128))
    if r.returncode:
        raise Refuse("not in a git repository: %s" % cwd)
    return os.path.realpath(r.stdout.decode().strip())


def options(got):
    return {"map": read_map(got["--milestone-map"]) if "--milestone-map" in got else {},
            "close": parse_ids(got.get("--close")), "open": parse_ids(got.get("--open"))}


def run(argv):
    if not argv or argv[0] not in ("plan", "refs", "apply", "leftovers"):
        raise Refuse(USAGE.rstrip())
    sub, rest = argv[0], argv[1:]
    if sub == "apply":
        return cmd_apply(repo_of(os.getcwd()), parse(rest, ("--json",), ("--milestone-map", "--close", "--open")))
    if sub == "leftovers":
        return cmd_leftovers(repo_of(os.getcwd()), parse(rest, ("--apply",), ("--milestone-map",)))
    if sub == "refs":
        got = parse_refs(rest)
        if "--base" not in got:
            raise Refuse("refs needs --base SHA\n" + USAGE.rstrip())
    else:
        got = parse(rest, ("--json",), ("--milestone-map", "--close", "--open"))
    repo = repo_of(os.getcwd())
    if sub == "refs":
        r = _git(repo, "rev-parse", "--verify", "-q", got["--base"] + "^{commit}", ok=(0, 1))
        if r.returncode:
            raise Refuse("--base %s is not a commit of %s" % (got["--base"], repo))
        base = r.stdout.decode().strip()
        src = Commit(repo, base)
    else:
        r = _git(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}", ok=(0, 1))
        if r.returncode:
            raise Refuse("%s has no commit yet" % repo)
        base, src = r.stdout.decode().strip(), WorkTree(repo)
    scopes, files, mapper, phases, gitignore, notes, root = build(repo, src, options(got))
    rewritten = left = None
    if sub == "refs" and (got["--rewrite"] or got["--prefix"]):
        rewritten, left = apply_rewrites(repo, mapper, got["--rewrite"], got["--prefix"])
    refs = scan_refs(repo, mapper)
    url, ahead, branches = git_facts(repo)
    if sub == "refs":
        branches = []
    doc = {"schema": SCHEMA, "repo": repo, "base": base, "remote": url, "ahead": ahead,
           "gsd_state": {"milestone": getattr(root, "state_milestone", None)}, "totals": totals(files),
           "scopes": [{"src": sc.src, "dest": sc.dest} for sc in scopes], "phases": phases, "files": files,
           "backlog": backlog_items(scopes, src, files), "gitignore": gitignore, "refs": refs, "branches": branches}
    if rewritten is not None:
        doc["rewritten"] = [{"file": f, "line": n, "old": o, "new": w, "kind": k} for f, n, o, w, k in rewritten]
        doc["left"] = [{"file": f, "line": n, "old": o, "kind": k, "why": why} for f, n, o, k, why in left]
    if "--json" in got:
        sys.stdout.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        for n in notes:
            sys.stderr.write("fwx migrate-gsd: note: %s\n" % n)
    else:
        text = render(doc, notes, files, refs_only=(sub == "refs"))
        if rewritten is not None:
            text += "rewritten: %d reference(s) in %d file(s), staged\n" % (len(rewritten), len({r[0] for r in rewritten}))
            text += "".join("  %s:%d  %s -> %s\n" % (f, n, o, w) for f, n, o, w, k in rewritten[:100])
            text += "left alone: %d\n" % len(left)
            text += "".join("  %s:%d  %s  (%s)\n" % (f, n, o, why) for f, n, o, k, why in left[:100])
        sys.stdout.write(text)
    return 0


def main(argv):
    try:
        return run(list(argv))
    except Refuse as e:
        sys.stderr.write("fwx migrate-gsd: %s\n" % e)
        return 2
    except Failed as e:
        sys.stderr.write("fwx migrate-gsd: %s\n" % e)
        return 1
