"""Say what moving a project's GSD `.planning/` to `.fwx/` would keep, purge and move: fwx migrate-gsd plan|refs [...]

  plan [--json] [--milestone-map FILE] [--close IDS] [--open IDS]
      Reads the `.planning/` of the repository you stand in (tracked, untracked and ignored files) and prints what the
      conversion would do with each file, phase, backlog item, `.gitignore` line, reference and unmerged branch.
  refs --base SHA [--json] [--milestone-map FILE]
      The same reference list, for a branch the conversion has already run on: the files of `.planning/` at SHA are
      classified again and every tracked line outside `.planning/` and `.fwx/` that names `.planning` is listed.

Both only read. They write nothing in the repository, no cache and no log: git runs with `--no-optional-locks`, so not even
the index is refreshed. `apply`, `leftovers` and `refs --rewrite|--prefix` are the write half and are not built here: they
exit 2 with a line saying so.

The classification is data (ROWS, PHASE_KEEP, PHASE_PURGE, ...): one tuple per row of the table the plan documents, each with
its `rule`, which is also the `rule` of every file it decided. A file no row names is kept at its own path (rule
`unknown`), because the project wrote it on purpose. Ignored and untracked files are never purged: only the machine-state
names are marked for deletion, the rest for moving. A PLAN is purged only when its SUMMARY is tracked.

`--milestone-map FILE` is JSON `{"<phase>": "vN"}` or lines `<phase> vN` / `<phase>=vN`, `#` comments allowed; a key is a
phase number (`7`, `02.1`) or a folder name, with an optional `<workstream>/` in front. `--close` and `--open` take
comma-separated keys of the same kind. A key no scope has, in any of the three flags, is exit 2.

`--json` is schema 1 and nothing else on stdout; notes (a ROADMAP with no phase headings in the expected format, a phase with
every file purged) go to stderr then, and to a `notes:` section in the text. Exit 0 done, 2 it cannot run or refuses: not a
git repository, 0 files looked at, a phase no milestone range covers, a key that matches no phase, two files for one
destination, a bad option.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys
import unicodedata

SCHEMA = 1
SCOPE_SRC = ".planning"
SCOPE_DEST = ".fwx"
USAGE = ("usage: fwx migrate-gsd plan [--json] [--milestone-map FILE] [--close IDS] [--open IDS]\n"
         "       fwx migrate-gsd refs --base SHA [--json] [--milestone-map FILE]\n")
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

def _git(repo, *args, ok=(0,)):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", repo] + list(args), capture_output=True, env=env)
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
                try:
                    size = os.lstat(os.path.join(self.repo, p)).st_size
                except OSError:
                    size = 0
                out.setdefault(p[len(SCOPE_SRC) + 1:], (kind, size))
        return [(rel, t, n) for rel, (t, n) in sorted(out.items())]

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
        """Whether a key of --milestone-map, --close or --open names this phase: its folder or its number, with or
        without the workstream in front."""
        ws, _, ident = k.rpartition("/")
        if ws and ws != sc.ws:
            return False
        return ident == name or (bool(RE_NUM.fullmatch(ident)) and tuple(int(n) for n in ident.split(".")) == num)

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
        if len(parts) >= 2 and parts[0] == "phases":
            known = [p for p in (sc.phases if sc else []) if p["key"] == "phases/" + parts[1]]
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
            for m in RE_TOKEN.finditer(line):
                token = m.group(0).rstrip(".:!?")
                kind, new = mapper.cite(token)
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


# ---- the command ---------------------------------------------------------------------------------------------------------

def parse(argv, flags, valued):
    args, got, rest, i = {}, {}, [], 0
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


def repo_of(cwd):
    r = _git(cwd, "rev-parse", "--show-toplevel", ok=(0, 128))
    if r.returncode:
        raise Refuse("not in a git repository: %s" % cwd)
    return os.path.realpath(r.stdout.decode().strip())


def options(got):
    return {"map": read_map(got["--milestone-map"]) if "--milestone-map" in got else {},
            "close": parse_ids(got.get("--close")), "open": parse_ids(got.get("--open"))}


def run(argv):
    if not argv or argv[0] not in ("plan", "refs"):
        if argv and argv[0] in ("apply", "leftovers"):
            raise Refuse("fwx migrate-gsd %s is not built yet (the write half of the converter)" % argv[0])
        raise Refuse(USAGE.rstrip())
    sub, rest = argv[0], argv[1:]
    if sub == "refs":
        if any(a in ("--rewrite", "--prefix") or a.startswith(("--rewrite=", "--prefix=")) for a in rest):
            raise Refuse("fwx migrate-gsd refs --rewrite and --prefix are not built yet (the write half of the converter)")
        got = parse(rest, ("--json",), ("--base", "--milestone-map"))
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
    refs = scan_refs(repo, mapper)
    url, ahead, branches = git_facts(repo)
    if sub == "refs":
        branches = []
    doc = {"schema": SCHEMA, "repo": repo, "base": base, "remote": url, "ahead": ahead,
           "gsd_state": {"milestone": getattr(root, "state_milestone", None)}, "totals": totals(files),
           "scopes": [{"src": sc.src, "dest": sc.dest} for sc in scopes], "phases": phases, "files": files,
           "backlog": backlog_items(scopes, src, files), "gitignore": gitignore, "refs": refs, "branches": branches}
    if "--json" in got:
        sys.stdout.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        for n in notes:
            sys.stderr.write("fwx migrate-gsd: note: %s\n" % n)
    else:
        sys.stdout.write(render(doc, notes, files, refs_only=(sub == "refs")))
    return 0


def main(argv):
    try:
        return run(list(argv))
    except Refuse as e:
        sys.stderr.write("fwx migrate-gsd: %s\n" % e)
        return 2
