#!/usr/bin/env python3
"""NOTICE against the files that say where their text came from (I12), and every text file against the header that says
whether it came from anywhere (I15).

A `copied-from: <source> <path> @<commit>` header in the first 10 lines of any file needs that source and that commit in
one entry of NOTICE (an entry is a block with no blank line inside; a full hash matches its short form). Anything
that follows the commit is free. A `<source> <path>` with no space (`repo-kit/files/x.yml`) names the source by its first
folder. `copied-from: none ...` says the file copies nothing. Every agents/*.md, skills/*/SKILL.md,
skills/*/references/*.md, workflows/*.js and playbooks/*.md carries in its first 10 lines one of the three headers:
the copied one, `referent: <project> <path> @<rev>` or `referent: none, <reason>`. A header is a line that starts with
the key (after a comment marker); the commit may sit on the next two lines. The test prints how many files it looked at;
none marked, or none of the five kinds, is a FAIL (skills/ and workflows/ do not exist yet, so only the sum is held).

Seen red before this change: NOTICE held only marshal's entry, and on the real repo the first lines were
  FAIL: .github/PULL_REQUEST_TEMPLATE.md:1: copied-from source `repo-kit` @582258b has no entry in NOTICE
  FAIL: .github/dependabot.yml:1: copied-from source `repo-kit` @582258b has no entry in NOTICE

Controls: each toy is the good one with one change, and must fail with the message given; the good toy passes first.
Seen red again, each on a copy of this file with that one check switched off (`if <check>:` made `if False:`), first FAIL line:
  the NOTICE lookup:        FAIL: control: a source with no entry in NOTICE: got [], want a problem with 'has no entry in NOTICE'
  the commit in the entry:  FAIL: control: the source is in NOTICE under another commit: got [], want a problem with 'has no entry in NOTICE'
  the referent line:        FAIL: control: an agent with none of the three headers: got [], want a problem with 'agents/x.md: no referent line'
  zero files marked:        FAIL: control: none marked: got []
  zero files of five kinds: FAIL: control: files marked, none of the five kinds: got []
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()
ROOT = helpers.ROOT
HEAD_LINES = 10
SKIP_DIRS = {".git", ".claude", "__pycache__", "node_modules"}
COPIED = re.compile(r"^\s*(?:#|//|\*|/\*|<!--)*\s*copied-from:\s*(.*)$")
REFERENT = re.compile(r"^\s*(?:#|//|\*|/\*|<!--)*\s*referent:\s*(.*)$")
COMMIT = re.compile(r"@([0-9a-f]{7,40})\b")
REFERENT_OK = re.compile(r"none,\s*\S|\S+\s+\S+\s+@\S+")
KINDS = [("agents/*.md", re.compile(r"agents/[^/]+\.md\Z")),
         ("skills/*/SKILL.md", re.compile(r"skills/[^/]+/SKILL\.md\Z")),
         ("skills/*/references/*.md", re.compile(r"skills/[^/]+/references/[^/]+\.md\Z")),
         ("workflows/*.js", re.compile(r"workflows/[^/]+\.js\Z")),
         ("playbooks/*.md", re.compile(r"playbooks/[^/]+\.md\Z"))]


def strip_marker(line):
    return re.sub(r"^\s*(?:#|//|\*|/\*|<!--)*\s*", "", line).replace("-->", "").strip()


def entries(text):
    return [b for b in re.split(r"\n\s*\n", text) if b.strip()]


def in_entry(block, source, commit):
    named = re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(source), block)
    hashes = re.findall(r"\b[0-9a-f]{7,40}\b", block)
    return bool(named) and any(h.startswith(commit) or commit.startswith(h) for h in hashes)


def read_head(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [next(fh, "").rstrip("\n") for _ in range(HEAD_LINES)]
    except (OSError, UnicodeDecodeError):
        return None


def header_of(lines, i):
    """The text of the header on line i with the next two lines, until a commit shows up."""
    text = COPIED.match(lines[i]).group(1)
    for extra in lines[i + 1:i + 3]:
        if COMMIT.search(text):
            break
        text += " " + strip_marker(extra)
    return text


def scan(root):
    """(problems, counts): problems are strings; counts has `marked` (files with a copied-from header that names a source),
    `none` (copied-from: none), and one entry per kind of text file."""
    problems = []
    counts = {"marked": 0, "none": 0}
    counts.update((name, 0) for name, _ in KINDS)
    try:
        with open(os.path.join(root, "NOTICE"), encoding="utf-8") as fh:
            blocks = entries(fh.read())
    except OSError:
        blocks = []
        problems.append("NOTICE: missing")
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            lines = read_head(full)
            if lines is None:
                continue
            headers = 0
            marked = False
            for i, line in enumerate(lines):
                m = COPIED.match(line)
                if m and m.group(1).strip().startswith("none"):
                    headers += 1
                    counts["none"] += 1
                elif m:
                    headers += 1
                    text = header_of(lines, i)
                    c = COMMIT.search(text)
                    toks = text[:c.start()].split() if c else []
                    if not c or not toks:
                        problems.append("%s:%d: copied-from is not `<source> <path> @<commit>`" % (rel, i + 1))
                        continue
                    source = toks[0].rstrip(",")
                    if len(toks) == 1:
                        source = source.split("/")[0]
                    marked = True
                    if not any(in_entry(b, source, c.group(1)) for b in blocks):
                        problems.append("%s:%d: copied-from source `%s` @%s has no entry in NOTICE" % (rel, i + 1, source, c.group(1)))
                else:
                    r = REFERENT.match(line)
                    if r and REFERENT_OK.match(r.group(1).strip()):
                        headers += 1
            counts["marked"] += marked
            for name, pat in KINDS:
                if pat.match(rel):
                    counts[name] += 1
                    if not headers:
                        problems.append("%s: no referent line (a copied-from or referent header in the first %d lines)" % (rel, HEAD_LINES))
    if counts["marked"] == 0:
        problems.append("looked at no file with a copied-from header")
    if sum(counts[name] for name, _ in KINDS) == 0:
        problems.append("looked at no agent, skill, workflow or playbook file")
    return problems, counts


# ---- controls on toy repos ------------------------------------------------------------------------------------------

NOTICE = "Sources.\n\ntoysrc, https://example.org/toysrc, commit abc1234def5678 (MIT).\n  a.py from x/y.py\n\nother, commit 9999999.\n"
GOOD = {"NOTICE": NOTICE,
        "a.py": "# copied-from: toysrc x/y.py @abc1234, adapted\nprint(1)\n",
        "b.py": "# copied-from: toysrc x/z.py\n# @abc1234def5678, ported\n",
        "c.yml": "# copied-from: toysrc/files/c.yml @abc1234\n",
        "d.py": "# copied-from: none (written here)\n",
        "agents/x.md": "---\nname: x\n---\n<!-- referent: toysrc skills/x.md @abc1234 (the shape) -->\ntext\n",
        "playbooks/p.md": "<!-- referent: none, own text: nothing like it -->\n# P\n",
        "skills/k/SKILL.md": "<!-- copied-from: toysrc skills/k/SKILL.md @abc1234def5678 -->\n",
        "skills/k/references/r.md": "<!-- referent: none, own text -->\n",
        "workflows/w.js": "// referent: toysrc w.js @abc1234\n"}


def toy(**change):
    """The good toy with `change` laid over it (a value None removes the file)."""
    files = dict(GOOD)
    for k, v in change.items():
        k = k.replace("__", "/").replace("_dot_", ".")
        if v is None:
            files.pop(k, None)
        else:
            files[k] = v
    return files


def run(files):
    root = helpers.mkdtemp("fwx-notice-")
    for rel, text in files.items():
        helpers.write(root, rel, text)
    return scan(root)


problems, counts = run(GOOD)
s.eq("the good toy has no problem", problems, [])
s.eq("the good toy: files marked", counts["marked"], 4)
s.eq("the good toy: one of each of the five kinds", [counts[n] for n, _ in KINDS], [1, 1, 1, 1, 1])
s.eq("the good toy: copied-from none counted apart", counts["none"], 1)

CASES = [
    ("a source with no entry in NOTICE", dict(a_dot_py="# copied-from: nosuch x/y.py @abc1234\n"), "has no entry in NOTICE"),
    ("the source is in NOTICE under another commit", dict(a_dot_py="# copied-from: toysrc x/y.py @9999999\n"), "has no entry in NOTICE"),
    ("the commit is in NOTICE under another source", dict(a_dot_py="# copied-from: other x/y.py @abc1234\n"), "has no entry in NOTICE"),
    ("a commit that only shares its start with the entry's", dict(a_dot_py="# copied-from: toysrc x/y.py @abc1235\n"), "has no entry in NOTICE"),
    ("a copied-from with no commit", dict(a_dot_py="# copied-from: toysrc x/y.py\n"), "copied-from is not"),
    ("an agent with none of the three headers", dict(agents__x_dot_md="---\nname: x\n---\ntext\n"), "agents/x.md: no referent line"),
    ("a playbook with a referent that has no reason", dict(playbooks__p_dot_md="<!-- referent: none -->\n"), "playbooks/p.md: no referent line"),
    ("a skill reference with the header past line 10",
     dict(skills__k__references__r_dot_md="\n" * 10 + "<!-- referent: none, own text -->\n"), "skills/k/references/r.md: no referent line"),
    ("a workflow with none", dict(workflows__w_dot_js="export default 1;\n"), "workflows/w.js: no referent line"),
    ("a SKILL.md with none", dict(skills__k__SKILL_dot_md="# k\n"), "skills/k/SKILL.md: no referent line"),
    ("no NOTICE file", dict(NOTICE=None), "NOTICE: missing"),
]
for label, change, want in CASES:
    got, _ = run(toy(**change))
    s.ok("control: %s" % label, any(want in p for p in got), "got %r, want a problem with %r" % (got, want))

# nothing looked at is a failure of its own
got, _ = run({"NOTICE": NOTICE, "README": "toy\n"})
s.ok("control: nothing looked at", any("looked at no file" in p for p in got), "got %r, want a problem with 'looked at no file'" % got)
got, _ = run({k: v for k, v in GOOD.items() if k.split("/")[0] not in ("agents", "playbooks", "skills", "workflows")})
s.ok("control: files marked, none of the five kinds", any("looked at no agent" in p for p in got), "got %r" % got)
got, _ = run(toy(a_dot_py=None, b_dot_py=None, c_dot_yml=None, skills__k__SKILL_dot_md=None))
s.ok("control: none marked", any("looked at no file with a copied-from" in p for p in got), "got %r" % got)
# a header the walk must not read: past line 10, in a skipped folder, in a file that is not text
late = toy(late_dot_py="\n" * 10 + "# copied-from: nosuch x @abc1234\n")
late[".git/hooks/h"] = "# copied-from: nosuch x @abc1234\n"
late[".claude/h.md"] = "# copied-from: nosuch x @abc1234\n"
got, _ = run(late)
s.eq("a header past line 10, under .git or under .claude is not read", got, [])

# ---- the repo itself ------------------------------------------------------------------------------------------------

problems, counts = scan(ROOT)
for p in problems:
    s.ok(p, False)
s.ok("the repo: files with a copied-from header looked at: %d (more than zero)" % counts["marked"], counts["marked"] > 0)
kinds = ", ".join("%s %d" % (n, counts[n]) for n, _ in KINDS)
s.ok("the repo: files of the five kinds looked at: %s (more than zero)" % kinds, sum(counts[n] for n, _ in KINDS) > 0)
print("looked at %d files with a copied-from header (and %d with `copied-from: none`); text files by kind: %s"
      % (counts["marked"], counts["none"], kinds))
s.done()
