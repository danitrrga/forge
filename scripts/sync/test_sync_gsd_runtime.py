#!/usr/bin/env python3
"""sync_gsd_runtime.py's copy-and-patch step on toy staging and destination trees, in-process.

The script is loaded as a module with HOME set to a toy dir before the import, so every constant
derived from HOME (the agents dir, the engine, the skills mirror, the staging tree, the npm
stamp) lands inside the toy root; FORGE_SKILLS and BLOCKS, which derive from the checkout, are
repointed there too, and every one is checked before a case runs. main(), stage(),
package_root() and npm_latest() are never called, and npm_nag() only with npm_latest stubbed and
the module's subprocess replaced by one that raises: nothing here runs the GSD installer, and
npm and node run only in defaults_gsd_reads (`npm root -g`, then node on the installed config.cjs
with HOME on the toy dir). Apply is on by assigning CTX, not by passing --apply, because
lib.may_write() refuses in a linked worktree and a "not written" assertion would then pass for the
wrong reason; each case's positive control proves the write path is live.

- A patch whose anchor no longer matches upstream is an error, and the file it belongs to is not
  written: replacing a working patched runtime file with unpatched upstream text undoes the fix
  the anchor check exists to protect. The file does not count as changed. Seen failing on 7ce50ff:
  "tree: a.md was rewritten with unpatched text: 'upstream drifted text\\n'" and
  "skills: gsd-x was rewritten with unpatched text, changed=1, output lists it True". With the
  held-back `continue` removed from sync_tree (the regression control) the four tree failures
  come back, "tree: a.md was rewritten with unpatched text" first; removed from sync_skills, the
  skills one does. The held-back line itself is asserted too: until attack round 4 the suite passed
  with `held.append` deleted and the `continue` kept, so a held-back file vanished from the output
  unnoticed. With that mutation "tree: output does not name the held-back a.md and
  c.md: []" in sync_tree and "skills: output does not name the held-back gsd-x: []" in sync_skills.
- A patch whose target file is gone (not staged, excluded by `only`, or a skill forge no longer
  ships) applies to nothing: an error, once per cause. Seen failing on 5ffcc88:
  "tree: patches with no target file: raised None, errors name [], want ['gsd-gone.md',
  'other.md']: []" and "skills: ... errors per skill {'gsd-x': 0, 'gsd-gone': 0,
  'gsd-unshipped': 0, 'gsd-orphan': 1}". Controls: with the tree check emptied the tree line
  comes back; without the `- set(missing)` the skills one does, gsd-orphan counted 2.
- check_skill_refs on a fresh HOME counts a missing skills mirror or agents dir as empty. Seen
  failing on 9f4998f: "refs: no ~/.claude at all: raised FileNotFoundError: [Errno
  2] No such file or directory: '<toy>/refs-none/home/.claude/skills'" and the same for
  '.../refs-mirror-only/home/.claude/agents'. Controls: with the agents guard back to
  os.listdir both cases fail on '.claude/agents'; with the mirror guard back, refs-none fails on
  '.claude/skills'. refs-mirror-only also proves an existing mirror is still read.
- A destination file is compared byte for byte (lib.holds). Seen failing on 8f6b6f0,
  which read it with universal newlines: "crlf: raised None, errors [], count 1 (want 2), want
  '1 in sync': == toy == |    2 in sync |    wrote 1 new: gone.md" (the CRLF file read as in
  sync), "not-utf8: raised UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9 in position
  3: invalid continuation byte" and "skills: a CRLF SKILL.md: raised None, errors [], changed 0".
  Controls: with sync_tree's lib.holds replaced by False, "crlf: ... count 3 (want 2) ... 0 in
  sync"; with added and changed swapped, "crlf: want crlf.md changed and gone.md new: ... wrote
  1 new: crlf.md | wrote 1 changed: gone.md" and not-utf8 reads "wrote 1 new: latin.md".
- npm_nag's once-a-day throttle: no stamp checks and writes one, a fresh stamp does not check
  again, a stale one does. Nothing ran it since the fixture seeds its stamp (4c3725c). It passed
  on first run, so each assertion was shown red by a mutation of npm_nag (restored
  from a backup copy each time): with the throttle's `return` made `pass`, and again with the
  stamp read forced to 0.0, "npm: a stamp a minute old: raised None, npm_latest calls [8] (want
  none), stamp rewritten True, said 'GSD 9.9.9 is published ...'"; with the lib.write_text call
  removed, "npm: no stamp: ... stamp None" and "npm: a stamp two days old: ... stamp
  '<t> 1.0.0\\n'"; with the throttle widened to 30 days, only "npm: a stamp two days old: raised
  None, npm_latest calls [] (want [8])"; with `timeout=8` dropped, "calls [60] (want [8])" in the
  no-stamp and stale cases; with the print's condition made False, "npm: no stamp: ... said ''".
- ~/.gsd/defaults.json is a copy of config/gsd/defaults.json (defaults_copy), and GSD reads it
  (defaults_gsd_reads). Seen failing against master's sync_gsd_runtime.py, which has no
  GSD_DEFAULTS: "AttributeError: module 'sync_gsd_runtime' has no attribute 'GSD_DEFAULTS'" out of
  guard() on the first case. A differing real file is the user's, not a fault (changed later):
  against the first version, which put it in errors, "defaults: a real file that differs,
  apply=False: raised None, errors ['<toy>/.../defaults.json is a real file that differs from ...
  -- left alone; delete it to let forge copy it'], changes 0 ..." (and apply=True). Mutations of
  sync_defaults (restored from a backup copy each time): that branch returning 1, "... errors [],
  changes 1" in both cases; its line prefixed with "!", a failure in both cases; and, from the
  first version, the link removal
  before write_text deleted, "defaults: a link to forge's file, apply: ... still a link True" and
  "a link to another file, apply: ... the target's bytes kept False" (write_text writes through
  the link into the file it points at); the copy made a link again, 5 failures from "defaults: a
  second apply" on; in-sync decided
  without comparing bytes, "defaults: a real file that differs ... said ... in sync". With
  config/gsd/defaults.json changed to {"workflow": {"ui_phase": true}}, "gsd reads: with the copy,
  (ui_phase, ui_safety_gate) = (True, True), want (False, False)". guard() sees GSD_DEFAULTS:
  pointed outside the toy root it exits "FAIL harness: outside the toy root: ['GSD_DEFAULTS'] ...".
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
FORGE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(FORGE, "tests"))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("gsd-runtime-test-")
os.environ["HOME"] = os.path.join(TOY, "home")
os.makedirs(os.environ["HOME"])
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG"):
    os.environ.pop(var, None)
sys.argv = [sys.argv[0]]
_spec = importlib.util.spec_from_file_location(
    "sync_gsd_runtime", os.path.join(FORGE, "scripts", "sync", "sync_gsd_runtime.py"))
gsd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gsd)
gsd.FORGE_SKILLS = os.path.join(TOY, "forge-skills")
gsd.BLOCKS = os.path.join(TOY, "blocks")
gsd.CTX = gsd.lib.Ctx(True, None, True)

REAL_AUTHORED = set(gsd.FORGE_AUTHORED)
REAL_PATCHES = {k: list(v) for k, v in gsd.SKILL_PATCHES.items()}  # the cases below replace gsd.SKILL_PATCHES

PATHS = ("AGENTS_DIR", "GSD_DIR", "SCRIPTS_DIR", "HOOKS_DIR", "SKILLS_MIRROR", "FORGE_SKILLS", "BLOCKS", "STAGE_ROOT", "STAGE",
         "STAMP", "NPM_STAMP", "GSD_DEFAULTS")


LAST_CHANGES = [None]  # run_defaults' sync_defaults return value (the change count)
DRY_OK = False  # set by run_defaults for a dry-run case, whose positive control is the apply case beside it


def guard():
    """Exit before a case runs if any path the script writes or reads is outside the toy root."""
    out = [n for n in PATHS if not os.path.realpath(getattr(gsd, n)).startswith(TOY + os.sep)]
    if out or not gsd.lib.HOME.startswith(TOY + os.sep) or not (gsd.CTX.apply or DRY_OK):
        sys.exit("FAIL harness: outside the toy root: %s, lib.HOME %s, apply %s"
                 % (out, gsd.lib.HOME, gsd.CTX.apply))


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


def call(fn, *args, **kw):
    """(fn's return, what it printed, the exception it raised or None)."""
    guard()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return fn(*args, **kw), buf.getvalue(), None
    except Exception as e:  # a crash is a failure to report, not a traceback that ends the run
        return None, buf.getvalue(), "%s: %s" % (type(e).__name__, e)


def case_dir(name):
    d = os.path.join(TOY, name)
    os.makedirs(d)
    return d


TREE_PATCHES = {
    "a.md": [("p-replace", "replace", "OLD ANCHOR", "NEW PAYLOAD")],
    "c.md": [("p-append", "append", "APPEND ANCHOR", "APPENDED BLOCK\n")],
}


def tree_failed_anchor(failures):
    """Both patched files had their patch applied by an earlier run; upstream then rewrote both
    anchors. Neither may be rewritten; the unpatched b.md beside them still is."""
    d = case_dir("tree-failed")
    src, dst = os.path.join(d, "stage"), os.path.join(d, "runtime")
    write(os.path.join(src, "a.md"), "upstream drifted text\n")
    write(os.path.join(src, "b.md"), "plain\n")
    write(os.path.join(src, "c.md"), "anchor rewritten upstream\n")
    write(os.path.join(dst, "a.md"), "upstream NEW PAYLOAD text\n")
    write(os.path.join(dst, "c.md"), "APPEND ANCHOR\n\nAPPENDED BLOCK\n")
    errors = []
    n, out, exc = call(gsd.sync_tree, src, dst, TREE_PATCHES, "toy", errors)
    if exc:
        failures.append("tree: sync_tree raised %s" % exc)
        return
    if read(os.path.join(dst, "a.md")) != "upstream NEW PAYLOAD text\n":
        failures.append("tree: a.md was rewritten with unpatched text: %r" % read(os.path.join(dst, "a.md")))
    if read(os.path.join(dst, "c.md")) != "APPEND ANCHOR\n\nAPPENDED BLOCK\n":
        failures.append("tree: c.md was rewritten with unpatched text: %r" % read(os.path.join(dst, "c.md")))
    if read(os.path.join(dst, "b.md")) != "plain\n":
        failures.append("tree: the unpatched b.md beside them was not written: %r" % read(os.path.join(dst, "b.md")))
    if n != 1:
        failures.append("tree: %s file(s) counted as changed, want 1 (b.md): %s" % (n, sandbox.tail(out, 4)))
    named = sorted(x for x in ("a.md", "c.md") if any(x in e for e in errors))
    if named != ["a.md", "c.md"]:
        failures.append("tree: errors name %s, want both a.md and c.md: %s" % (named, errors))
    wrote = [ln for ln in out.splitlines() if "wrote" in ln]
    if any("a.md" in ln or "c.md" in ln for ln in wrote):
        failures.append("tree: output says a held-back file was written: %s" % wrote)
    held = [ln for ln in out.splitlines() if "held back" in ln]
    if len(held) != 1 or "held back 2 " not in held[0] or "a.md" not in held[0] or "c.md" not in held[0]:
        failures.append("tree: output does not name the held-back a.md and c.md: %s" % held)


def tree_control(failures):
    """Control: the same patches with their anchors intact, over a stale runtime, are written."""
    d = case_dir("tree-control")
    src, dst = os.path.join(d, "stage"), os.path.join(d, "runtime")
    write(os.path.join(src, "a.md"), "upstream OLD ANCHOR text\n")
    write(os.path.join(src, "b.md"), "plain\n")
    write(os.path.join(src, "c.md"), "APPEND ANCHOR\n")
    write(os.path.join(dst, "a.md"), "stale\n")
    write(os.path.join(dst, "c.md"), "stale\n")
    errors = []
    n, out, exc = call(gsd.sync_tree, src, dst, TREE_PATCHES, "toy", errors)
    got = (read(os.path.join(dst, "a.md")), read(os.path.join(dst, "c.md")), read(os.path.join(dst, "b.md")))
    want = ("upstream NEW PAYLOAD text\n", "APPEND ANCHOR\n\nAPPENDED BLOCK\n", "plain\n")
    if exc or errors or n != 3 or got != want:
        failures.append("control: tree with intact anchors: raised %s, errors %s, count %s, files %r"
                        % (exc, errors, n, got))


def skills_setup(name, staged_text, forge_text):
    d = case_dir(name)
    gsd.STAGE = os.path.join(d, "stage", "cfg")
    gsd.FORGE_SKILLS = os.path.join(d, "forge-skills")
    write(os.path.join(gsd.STAGE, "skills", "gsd-x", "SKILL.md"), staged_text)
    write(os.path.join(gsd.FORGE_SKILLS, "gsd-x", "SKILL.md"), forge_text)
    gsd.SKILL_PATCHES = {"gsd-x": [("p-skill", "replace", "OLD ANCHOR", "NEW PAYLOAD")]}
    return os.path.join(gsd.FORGE_SKILLS, "gsd-x", "SKILL.md")


def skills_failed_anchor(failures):
    p = skills_setup("skills-failed", "upstream drifted text\n", "upstream NEW PAYLOAD text\n")
    errors = []
    n, out, exc = call(gsd.sync_skills, errors)
    if exc:
        failures.append("skills: sync_skills raised %s" % exc)
        return
    listed = any("gsd-x" in ln for ln in out.splitlines() if "rewrote" in ln)
    if read(p) != "upstream NEW PAYLOAD text\n" or n != 0 or listed:
        failures.append("skills: gsd-x was rewritten with unpatched text, changed=%s, output lists it %s"
                        % (n, listed))
    if not any("gsd-x" in e and "p-skill" in e for e in errors):
        failures.append("skills: no error names the failed patch: %s" % errors)
    held = [ln for ln in out.splitlines() if "held back" in ln]
    if len(held) != 1 or "held back 1 " not in held[0] or "gsd-x" not in held[0]:
        failures.append("skills: output does not name the held-back gsd-x: %s" % held)


def skills_control(failures):
    p = skills_setup("skills-control", "upstream OLD ANCHOR text\n", "stale\n")
    errors = []
    n, out, exc = call(gsd.sync_skills, errors)
    if exc or errors or n != 1 or read(p) != "upstream NEW PAYLOAD text\n":
        failures.append("control: skills with an intact anchor: raised %s, errors %s, changed %s, file %r"
                        % (exc, errors, n, read(p)))


def tree_missing_target(failures):
    """A patch keyed to a file the package no longer stages, and one to a staged file the `only`
    filter excludes, each apply to nothing: both are errors. The intact patch beside them is not."""
    d = case_dir("tree-missing")
    src, dst = os.path.join(d, "stage"), os.path.join(d, "runtime")
    write(os.path.join(src, "gsd-a.md"), "upstream OLD ANCHOR text\n")
    write(os.path.join(src, "other.md"), "OLD ANCHOR\n")
    patches = {k: [("p-%s" % k, "replace", "OLD ANCHOR", "NEW PAYLOAD")]
               for k in ("gsd-a.md", "gsd-gone.md", "other.md")}
    errors = []
    n, out, exc = call(gsd.sync_tree, src, dst, patches, "toy", errors, only=lambda rel: rel.startswith("gsd-"))
    named = sorted(k for k in patches if any(k in e for e in errors))
    if exc or named != ["gsd-gone.md", "other.md"]:
        failures.append("tree: patches with no target file: raised %s, errors name %s, want "
                        "['gsd-gone.md', 'other.md']: %s" % (exc, named, errors))
    if read(os.path.join(dst, "gsd-a.md")) != "upstream NEW PAYLOAD text\n":
        failures.append("tree: the patch with a target was not applied: %r" % read(os.path.join(dst, "gsd-a.md")))


def skills_missing_target(failures):
    """gsd-gone: in SKILL_PATCHES, neither staged nor shipped. gsd-unshipped: staged, not in forge yet: shipped
    all the same (every upstream skill is), so its patch has a target and no error names it. gsd-orphan: shipped,
    not staged -- already reported as a skill without upstream counterpart, so exactly one error names it."""
    skills_setup("skills-missing", "upstream OLD ANCHOR text\n", "stale\n")
    write(os.path.join(gsd.STAGE, "skills", "gsd-unshipped", "SKILL.md"), "OLD ANCHOR\n")
    write(os.path.join(gsd.FORGE_SKILLS, "gsd-orphan", "SKILL.md"), "OLD ANCHOR\n")
    for k in ("gsd-gone", "gsd-unshipped", "gsd-orphan"):
        gsd.SKILL_PATCHES[k] = [("p-%s" % k, "replace", "OLD ANCHOR", "NEW PAYLOAD")]
    errors = []
    n, out, exc = call(gsd.sync_skills, errors)
    count = {k: sum(k in e for e in errors) for k in ("gsd-x", "gsd-gone", "gsd-unshipped", "gsd-orphan")}
    if exc or count != {"gsd-x": 0, "gsd-gone": 1, "gsd-unshipped": 0, "gsd-orphan": 1}:
        failures.append("skills: patches with no target file: raised %s, errors per skill %s, want "
                        "one each for gsd-gone and gsd-orphan, none for gsd-x and gsd-unshipped: %s" % (exc, count, errors))


def write_bytes(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def tree_crlf(failures):
    """A runtime file that holds its LF text with CRLF line ends is not in sync: it is listed as
    changed and rewritten. Beside it, a byte-identical file stays in sync and a missing one is new,
    so a check that always answered "differs", or swapped new and changed, fails here too."""
    d = case_dir("tree-crlf")
    src, dst = os.path.join(d, "stage"), os.path.join(d, "runtime")
    for name in ("crlf.md", "gone.md", "same.md"):
        write(os.path.join(src, name), "line one\nline two\n")
    write_bytes(os.path.join(dst, "crlf.md"), b"line one\r\nline two\r\n")
    write_bytes(os.path.join(dst, "same.md"), b"line one\nline two\n")
    errors = []
    n, out, exc = call(gsd.sync_tree, src, dst, {}, "toy", errors)
    lines = out.splitlines()
    if exc or errors or n != 2 or "   1 in sync" not in lines:
        failures.append("crlf: raised %s, errors %s, count %s (want 2), want '1 in sync': %s"
                        % (exc, errors, n, sandbox.tail(out, 4)))
    if "   wrote 1 changed: crlf.md" not in lines or "   wrote 1 new: gone.md" not in lines:
        failures.append("crlf: want crlf.md changed and gone.md new: %s" % sandbox.tail(out, 4))
    got = {name: read_bytes(os.path.join(dst, name)) if os.path.exists(os.path.join(dst, name)) else None
           for name in ("crlf.md", "gone.md", "same.md")}
    if set(got.values()) != {b"line one\nline two\n"}:
        failures.append("crlf: runtime files not all LF text: %r" % got)


def tree_blocked_path(failures):
    """A user's own entry at a staged name is kept and reported, and the walk goes on: it was an
    OSError out of sync_tree that stopped the later trees and the defaults step with no line saying why.
    (a) a directory `a.cjs/` where the stage has a file a.cjs: lib.write_text raised "OSError: could not
    atomically replace <dst>/a.cjs ... [Errno 21] Is a directory"; (b) a file `lib` where the stage has
    lib/x.cjs: "FileExistsError: [Errno 17] File exists: '<dst>/lib'". In both, the user's entry must stay
    byte for byte, the other staged files must land, and errors must name the blocked path."""
    for name, blocked, mine in (("tree-blocked-dir", "a.cjs", "a.cjs"), ("tree-blocked-file", "lib", os.path.join("lib", "x.cjs"))):
        d = case_dir(name)
        src, dst = os.path.join(d, "stage"), os.path.join(d, "runtime")
        for rel in (mine, "b.cjs", os.path.join("zz", "y.cjs")):
            write(os.path.join(src, rel), "staged\n")
        if name == "tree-blocked-dir":
            write(os.path.join(dst, "a.cjs", "own.txt"), "the user's own\n")
            keep = os.path.join(dst, "a.cjs", "own.txt")
        else:
            write(os.path.join(dst, "lib"), "the user's own\n")
            keep = os.path.join(dst, "lib")
        errors = []
        n, out, exc = call(gsd.sync_tree, src, dst, {}, "toy", errors)
        got = {rel: read(os.path.join(dst, rel)) for rel in ("b.cjs", os.path.join("zz", "y.cjs"))}
        mine_line = [e for e in errors if e.startswith("toy %s: " % mine) and e.endswith("; the entry at that path is not ours, left as it is")]
        if exc or n != 2 or set(got.values()) != {"staged\n"} or read(keep) != "the user's own\n" or len(errors) != 1 or len(mine_line) != 1:
            failures.append("%s: raised %s, count %s (want 2), others %s, user's entry %r, errors %s"
                            % (name, exc, n, got, read(keep), errors))


def tree_not_utf8(failures):
    """A runtime file that is not UTF-8 is rewritten, not a UnicodeDecodeError out of the run."""
    d = case_dir("tree-not-utf8")
    src, dst = os.path.join(d, "stage"), os.path.join(d, "runtime")
    write(os.path.join(src, "latin.md"), "caf\u00e9\n")
    write_bytes(os.path.join(dst, "latin.md"), b"caf\xe9\n")
    errors = []
    n, out, exc = call(gsd.sync_tree, src, dst, {}, "toy", errors)
    got = read_bytes(os.path.join(dst, "latin.md"))
    if exc or errors or n != 1 or "   wrote 1 changed: latin.md" not in out.splitlines() \
            or got != "caf\u00e9\n".encode():
        failures.append("not-utf8: raised %s, errors %s, count %s, file %r: %s"
                        % (exc, errors, n, got, sandbox.tail(out, 4)))


def skills_crlf(failures):
    """sync_skills compares the same way: a forge SKILL.md with CRLF line ends is drift."""
    p = skills_setup("skills-crlf", "upstream OLD ANCHOR text\n", "stale\n")
    write_bytes(p, b"upstream NEW PAYLOAD text\r\n")
    errors = []
    n, out, exc = call(gsd.sync_skills, errors)
    if exc or errors or n != 1 or read_bytes(p) != b"upstream NEW PAYLOAD text\n":
        failures.append("skills: a CRLF SKILL.md: raised %s, errors %s, changed %s, file %r"
                        % (exc, errors, n, read_bytes(p)))


def refs_setup(name):
    d = case_dir(name)
    gsd.SKILLS_MIRROR = os.path.join(d, "home", ".claude", "skills")
    gsd.AGENTS_DIR = os.path.join(d, "home", ".claude", "agents")
    gsd.GSD_DIR = os.path.join(d, "home", ".claude", "gsd-core")
    gsd.FORGE_SKILLS = os.path.join(d, "forge-skills")
    return d


def refs_no_dirs(failures):
    """A fresh HOME: no skills mirror, no agents dir. Both count as empty."""
    refs_setup("refs-none")
    errors = []
    _, out, exc = call(gsd.check_skill_refs, errors)
    if exc or errors or "0 gsd-* skills, 0 agents installed" not in out:
        failures.append("refs: no ~/.claude at all: raised %s, errors %s: %s" % (exc, errors, sandbox.tail(out, 2)))


def refs_no_agents(failures):
    """The mirror is there, the agents dir is not: the mirror is still read, and a routing row
    to a name that is neither a skill nor an agent is still reported. Also the control that the
    check reads a directory that exists."""
    d = refs_setup("refs-mirror-only")
    real = os.path.join(d, "forge-skills", "gsd-toy")
    write(os.path.join(real, "SKILL.md"), "| route | gsd-zz-toy-missing |\n")
    os.makedirs(gsd.SKILLS_MIRROR)
    os.symlink(real, os.path.join(gsd.SKILLS_MIRROR, "gsd-toy"))
    errors = []
    _, out, exc = call(gsd.check_skill_refs, errors)
    dangling = [e for e in errors if "gsd-toy -> gsd-zz-toy-missing" in e]
    if exc or len(errors) != 1 or not dangling or "1 gsd-* skills, 0 agents installed" not in out:
        failures.append("refs: mirror without agents dir: raised %s, errors %s: %s" % (exc, errors, sandbox.tail(out, 2)))


def refs_forge_only(failures):
    """A skill forge has just written is not in the mirror until relink_skills runs, and the GSD step runs first on
    a fresh apply (forge skills: online skills, gsd runtime, skill links): a routing row to it, and a skill that only
    forge's skills/ holds, resolve from there. Seen failing on 3c608bc, whose first `forge skills --apply` of the 43
    new skills exited 1: "refs: a skill only in forge's skills/: errors ['dangling reference: gsd-toy -> gsd-new']"."""
    d = refs_setup("refs-forge-only")
    real = os.path.join(gsd.FORGE_SKILLS, "gsd-toy")
    write(os.path.join(real, "SKILL.md"), "| route | gsd-new |\n| route | gsd-zz-missing |\n")
    write(os.path.join(gsd.FORGE_SKILLS, "gsd-new", "SKILL.md"), "no routes\n")
    os.makedirs(gsd.SKILLS_MIRROR)
    os.symlink(real, os.path.join(gsd.SKILLS_MIRROR, "gsd-toy"))
    errors = []
    _, out, exc = call(gsd.check_skill_refs, errors)
    dangling = sorted(e for e in errors if e.startswith("dangling"))
    if exc or dangling != ["dangling reference: gsd-toy -> gsd-zz-missing"]:
        failures.append("refs: a skill only in forge's skills/: raised %s, errors %s (want only gsd-zz-missing dangling)" % (exc, errors))


def npm_nag_throttle(failures):
    """npm_nag asks npm at most once a day, and the stamp is what says when it last did: no stamp
    (its directory not there either, as on a fresh HOME) checks and writes one; a stamp a minute
    old does not check, print or rewrite; a stamp two days old checks again and is rewritten.
    npm_latest is a stub that records its timeout, and the module's subprocess is replaced by one
    that raises, so nothing here reaches npm or the network."""
    d = case_dir("npm-nag")
    gsd.NPM_STAMP = os.path.join(d, "home", ".cache", "forge", "gsd-stage", "NPM-CHECKED")
    calls = []

    def latest(timeout=60):
        calls.append(timeout)
        return "9.9.9"

    class NoSubprocess:
        def __getattr__(self, name):
            raise AssertionError("npm_nag reached subprocess.%s" % name)

    def stamped(t0, t1):
        """Whether the stamp holds a time within [t0, t1] (to %f's microsecond) and 9.9.9."""
        parts = (read(gsd.NPM_STAMP) or "").split()
        return len(parts) == 2 and t0 - 1e-5 <= float(parts[0]) <= t1 + 1e-5 and parts[1] == "9.9.9"

    real = gsd.npm_latest, gsd.subprocess
    gsd.npm_latest, gsd.subprocess = latest, NoSubprocess()
    try:
        t0 = time.time()
        _, out, exc = call(gsd.npm_nag, "1.0.0")
        t1 = time.time()
        if exc or calls != [8] or not stamped(t0, t1) or "GSD 9.9.9 is published (installed 1.0.0)" not in out:
            failures.append("npm: no stamp: raised %s, npm_latest calls %s (want [8]), stamp %r, said %r"
                            % (exc, calls, read(gsd.NPM_STAMP), out))

        del calls[:]
        write(gsd.NPM_STAMP, "%f 9.9.9\n" % (time.time() - 60))
        before = read(gsd.NPM_STAMP)
        _, out, exc = call(gsd.npm_nag, "1.0.0")
        if exc or calls or read(gsd.NPM_STAMP) != before or out:
            failures.append("npm: a stamp a minute old: raised %s, npm_latest calls %s (want none), stamp "
                            "rewritten %s, said %r" % (exc, calls, read(gsd.NPM_STAMP) != before, out))

        del calls[:]
        write(gsd.NPM_STAMP, "%f 1.0.0\n" % (time.time() - 2 * 86400))
        t0 = time.time()
        _, out, exc = call(gsd.npm_nag, "1.0.0")
        t1 = time.time()
        if exc or calls != [8] or not stamped(t0, t1):
            failures.append("npm: a stamp two days old: raised %s, npm_latest calls %s (want [8]), stamp %r"
                            % (exc, calls, read(gsd.NPM_STAMP)))

        # A dry-run writes nothing, the stamp included, and so does not ask npm either: `forge
        # sync` from a worktree or by hand wrote the real ~/.cache/forge/gsd-stage/NPM-CHECKED
        # and ran `npm view` (found in use). Seen failing before the fix: "npm: a dry-run
        # with no stamp: raised None, npm_latest calls [8] (want none), stamp written True".
        # call()'s guard wants apply on; it runs first, and the dry-run CTX only for npm_nag itself.
        del calls[:]
        os.remove(gsd.NPM_STAMP)
        guard()
        gsd.CTX = gsd.lib.Ctx(False, None, True)
        buf, exc = io.StringIO(), None
        try:
            with contextlib.redirect_stdout(buf):
                gsd.npm_nag("1.0.0")
        except Exception as e:
            exc = "%s: %s" % (type(e).__name__, e)
        finally:
            gsd.CTX = gsd.lib.Ctx(True, None, True)
        out = buf.getvalue()
        if exc or calls or os.path.exists(gsd.NPM_STAMP) or out:
            failures.append("npm: a dry-run with no stamp: raised %s, npm_latest calls %s (want none), "
                            "stamp written %s" % (exc, calls, os.path.exists(gsd.NPM_STAMP)))
    finally:
        gsd.npm_latest, gsd.subprocess = real


def defaults_world(name):
    """A toy ~/.gsd and a toy forge config/gsd holding forge's REAL defaults.json bytes (so the
    node case below proves the file forge ships, not a stand-in); returns (src, dst)."""
    d = case_dir(name)
    gsd.BLOCKS = os.path.join(d, "blocks")
    gsd.GSD_DEFAULTS = os.path.join(d, "home", ".gsd", "defaults.json")
    src = os.path.join(gsd.BLOCKS, "defaults.json")
    write(src, read(os.path.join(FORGE, "config", "gsd", "defaults.json")))
    return src, gsd.GSD_DEFAULTS


def run_defaults(apply):
    global DRY_OK
    real, DRY_OK = gsd.CTX, not apply
    gsd.CTX = gsd.lib.Ctx(apply, None, True)
    try:
        errors = []
        n, out, exc = call(lambda e: gsd.sync_defaults(e), errors)  # looked up inside call(): a crash is a failure line
        LAST_CHANGES[:] = [n]
        return out, exc, errors
    finally:
        gsd.CTX, DRY_OK = real, False


def defaults_copy(failures):
    """~/.gsd/defaults.json is a real-file COPY of forge's config/gsd/defaults.json, never a link:
    GSD's settings workflow writes that file (settings.md:393-399), and through a link the write
    would land in forge's tracked file. Absent: a dry-run writes nothing and says it would copy,
    an apply copies (the positive control: the write path is live), a second apply changes
    nothing. A link there, to forge's file or to another, is replaced by the copy and the file it
    pointed at keeps its bytes (write_text writes through a link, so a link left in place would
    overwrite forge's file). A real file that differs is the user's own (GSD's settings workflow writes it
    legitimately) and is never overwritten, dry-run or apply: no error, 0 changes, one plain line
    with no '!', and the bytes kept.
    A real file with forge's bytes is in sync. Forge's file gone is an error. Red before
    the script had GSD_DEFAULTS and sync_defaults: see the module docstring."""
    src, dst = defaults_world("defaults-absent")
    forge_bytes = read_bytes(src)
    out, exc, errors = run_defaults(False)
    if exc or errors or os.path.lexists(dst) or os.path.exists(os.path.dirname(dst)) or "would copy" not in out:
        failures.append("defaults: absent, dry-run: raised %s, errors %s, file there %s, said %s"
                        % (exc, errors, os.path.lexists(dst), sandbox.tail(out, 2)))
    out, exc, errors = run_defaults(True)
    if (exc or errors or os.path.islink(dst) or not os.path.isfile(dst) or read_bytes(dst) != forge_bytes
            or "copied" not in out):
        failures.append("defaults: absent, apply: raised %s, errors %s, link %s, bytes equal %s: %s"
                        % (exc, errors, os.path.islink(dst), os.path.isfile(dst) and read_bytes(dst) == forge_bytes,
                           sandbox.tail(out, 2)))
    before = os.lstat(dst).st_mtime_ns if os.path.lexists(dst) else None
    out, exc, errors = run_defaults(True)
    if exc or errors or before is None or os.lstat(dst).st_mtime_ns != before or "in sync" not in out:
        failures.append("defaults: a second apply: raised %s, errors %s, said %s" % (exc, errors, sandbox.tail(out, 2)))

    for label, other in (("a link to forge's file", "defaults.json"),
                         ("a link to another file", "defaults.other.json"),
                         ("a dangling link into another checkout", os.path.join("wt", "defaults.json"))):
        src, dst = defaults_world("defaults-" + label.replace(" ", "-").replace("'", ""))
        theirs = os.path.join(os.path.dirname(src), other)
        if other == "defaults.other.json":
            write(theirs, "other bytes\n")
        kept = read_bytes(theirs) if os.path.isfile(theirs) else None
        os.makedirs(os.path.dirname(dst))
        os.symlink(theirs, dst)
        out, exc, errors = run_defaults(False)
        if exc or errors or os.readlink(dst) != theirs or "would replace the link" not in out:
            failures.append("defaults: %s, dry-run: raised %s, errors %s, link now %s: %s"
                            % (label, exc, errors, os.readlink(dst) if os.path.islink(dst) else None, sandbox.tail(out, 2)))
        out, exc, errors = run_defaults(True)
        if (exc or errors or os.path.islink(dst) or read_bytes(dst) != read_bytes(src)
                or "replaced the link" not in out or (kept is not None and read_bytes(theirs) != kept)):
            failures.append("defaults: %s, apply: raised %s, errors %s, still a link %s, the target's bytes kept %s: %s"
                            % (label, exc, errors, os.path.islink(dst),
                               kept is None or read_bytes(theirs) == kept, sandbox.tail(out, 2)))

    src, dst = defaults_world("defaults-differs")
    write(dst, '{"workflow": {"ui_phase": true}}\n')
    mine, forge_bytes = read_bytes(dst), read_bytes(src)
    for apply in (False, True):
        out, exc, errors = run_defaults(apply)
        if (exc or errors or LAST_CHANGES[0] != 0 or "differs from" not in out or "left alone" not in out
                or any(ln.lstrip().startswith("!") for ln in out.splitlines())
                or os.path.islink(dst) or read_bytes(dst) != mine or read_bytes(src) != forge_bytes):
            failures.append("defaults: a real file that differs, apply=%s: raised %s, errors %s, changes %s, "
                            "a link now %s, bytes kept %s: %s"
                            % (apply, exc, errors, LAST_CHANGES[0], os.path.islink(dst), read_bytes(dst) == mine,
                               sandbox.tail(out, 2)))

    src, dst = defaults_world("defaults-same-bytes")
    write(dst, read(src))
    before = os.lstat(dst).st_mtime_ns
    for apply in (False, True):
        out, exc, errors = run_defaults(apply)
        if exc or errors or os.path.islink(dst) or os.lstat(dst).st_mtime_ns != before or "in sync" not in out:
            failures.append("defaults: forge's own bytes as a real file, apply=%s: raised %s, errors %s, said %s"
                            % (apply, exc, errors, sandbox.tail(out, 2)))

    src, dst = defaults_world("defaults-no-source")
    os.remove(src)
    out, exc, errors = run_defaults(True)
    if exc or len(errors) != 1 or "defaults.json" not in errors[0] or os.path.lexists(dst):
        failures.append("defaults: forge's file gone: raised %s, errors %s, file there %s"
                        % (exc, errors, os.path.lexists(dst)))


GSD_CONFIG_JS = """
const {cmdConfigNewProject} = require(process.argv[1]);
cmdConfigNewProject(process.argv[2], '', false);
"""


def defaults_gsd_reads(failures):
    """GSD itself, run on the toy HOME, reads the copy: a project it creates has workflow.ui_phase
    and workflow.ui_safety_gate false, and without the file true (GSD's own default) -- the pair is
    the control, so a file GSD ignored, or a node call that always said false, fails one half.
    buildNewProjectConfig is not exported, so this goes through cmdConfigNewProject, which writes
    its result to .planning/config.json in a toy project dir. Skipped, with a printed line, when
    node or the installed package is missing. Red before the copy existed: with sync_defaults
    absent the first half raises AttributeError (the file is never made)."""
    try:
        pkg_cfg = os.path.join(gsd.package_root(), "gsd-core", "bin", "lib", "config.cjs")
    except SystemExit:
        pkg_cfg = ""
    node = shutil.which("node")
    if not node or not os.path.isfile(pkg_cfg):
        print("SKIP defaults_gsd_reads: node %s, package config.cjs %s" % (node, pkg_cfg or "not found"))
        return

    def ui_flags(tag, with_file):
        src, dst = defaults_world(tag)
        write(src, '{"workflow": {"ui_phase": false, "ui_safety_gate": false}}\n')
        if with_file:
            out, exc, errors = run_defaults(True)
            if exc or errors or not os.path.isfile(dst):
                return "sync_defaults failed: raised %s, errors %s" % (exc, errors)
        home = os.path.dirname(os.path.dirname(dst))
        proj = os.path.join(os.path.dirname(home), "project")
        os.makedirs(proj)
        env = {k: v for k, v in os.environ.items() if k not in ("GSD_HOME", "GSD_WORKSTREAM")}
        env["HOME"] = home
        r = subprocess.run([node, "-e", GSD_CONFIG_JS, pkg_cfg, proj], env=env, cwd=proj,
                           capture_output=True, text=True, timeout=60)
        cfg = os.path.join(proj, ".planning", "config.json")
        if r.returncode or not os.path.isfile(cfg):
            return "node exit %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[:200])
        wf = json.loads(read(cfg)).get("workflow", {})
        return (wf.get("ui_phase"), wf.get("ui_safety_gate"))

    got = ui_flags("gsd-reads-with", True)  # with a toy file that caps both: the mechanism, not forge's choice
    if got != (False, False):
        failures.append("gsd reads: with the copy, (ui_phase, ui_safety_gate) = %s, want (False, False)" % (got,))
    got = ui_flags("gsd-reads-without", False)
    if got != (True, True):
        failures.append("gsd reads: without the file, (ui_phase, ui_safety_gate) = %s, want GSD's own (True, True)" % (got,))


def skills_no_dir(failures):
    """A stranger's checkout has no skills/ until something puts a skill there, and sync_skills
    listed it with os.listdir. Seen failing on a2e69f6: "skills no dir: apply: raised
    FileNotFoundError: [Errno 2] No such file or directory: '<toy>/skills-no-dir-apply/forge-skills'"
    (and the same for the dry-run). Apply creates skills/ and the skill; a dry-run creates neither and
    says it would. The staged package is not read here, so the case has a gsd-x upstream skill that
    forge has not written yet: every upstream skill is shipped, so it is new (one change), never an
    error. Controls: skills_control above, with skills/ present, passes through the same code."""
    global DRY_OK
    for label, apply in (("apply", True), ("dry-run", False)):
        d = case_dir("skills-no-dir-" + label)
        gsd.STAGE = os.path.join(d, "stage", "cfg")
        gsd.FORGE_SKILLS = os.path.join(d, "forge-skills")
        write(os.path.join(gsd.STAGE, "skills", "gsd-x", "SKILL.md"), "upstream\n")
        gsd.SKILL_PATCHES = {}
        gsd.CTX = gsd.lib.Ctx(apply, None, True)
        DRY_OK = not apply
        try:
            errors = []
            n, out, exc = call(gsd.sync_skills, errors)
        finally:
            gsd.CTX = gsd.lib.Ctx(True, None, True)
            DRY_OK = False
        made = os.path.isdir(gsd.FORGE_SKILLS)
        wrote = read(os.path.join(gsd.FORGE_SKILLS, "gsd-x", "SKILL.md"))
        if exc or errors or n != 1 or made != apply or wrote != ("upstream\n" if apply else None) or "1 new: gsd-x" not in out:
            failures.append("skills no dir: %s: raised %s, errors %s, changed %s (want 1), skills/ made %s "
                            "(want %s), skill written %r, output %r" % (label, exc, errors, n, made, apply, wrote, out))


def skills_all_shipped(failures):
    """Every upstream skill is shipped, not a chosen subset ("all the functionalities, no cap"):
    forge has gsd-a and the staged package has gsd-a and gsd-b, so a dry-run names gsd-b as new and writes nothing, an
    apply writes it with the patches applied, and a forge-authored name is never taken for an upstream one. Seen
    failing on c2a741a, which listed gsd-b as "not shipped" and wrote nothing: "skills all: dry-run: changed 0 (want 1)
    ... 'upstream skills not shipped here (1): gsd-b'"."""
    global DRY_OK
    for label, apply in (("dry-run", False), ("apply", True)):
        d = case_dir("skills-all-" + label)
        gsd.STAGE = os.path.join(d, "stage", "cfg")
        gsd.FORGE_SKILLS = os.path.join(d, "forge-skills")
        write(os.path.join(gsd.STAGE, "skills", "gsd-a", "SKILL.md"), "a\n")
        write(os.path.join(gsd.STAGE, "skills", "gsd-b", "SKILL.md"), "b OLD ANCHOR\n")
        write(os.path.join(gsd.FORGE_SKILLS, "gsd-a", "SKILL.md"), "a\n")
        gsd.SKILL_PATCHES = {"gsd-b": [("p-b", "replace", "OLD ANCHOR", "NEW PAYLOAD")]}
        gsd.CTX = gsd.lib.Ctx(apply, None, True)
        DRY_OK = not apply
        try:
            errors = []
            n, out, exc = call(gsd.sync_skills, errors)
        finally:
            gsd.CTX = gsd.lib.Ctx(True, None, True)
            DRY_OK = False
        wrote = read(os.path.join(gsd.FORGE_SKILLS, "gsd-b", "SKILL.md"))
        if (exc or errors or n != 1 or wrote != ("b NEW PAYLOAD\n" if apply else None) or "not shipped" in out
                or "2 shipped here (1 new)" not in out):
            failures.append("skills all: %s: raised %s, errors %s, changed %s (want 1), gsd-b %r, output %r"
                            % (label, exc, errors, n, wrote, out))

def skills_authored_over_upstream(failures):
    """A forge-authored skill that upstream ALSO ships (gsd-sketch is rewritten by forge; the package still has one) is neither
    compared nor overwritten: forge's text stays, no drift line names it, and an apply leaves it as it was. Seen failing with the
    authored name removed from the skip (the mutant in the commit message): "skills authored over upstream: apply: gsd-a is
    'upstream text' (want forge's own), drift reported 1"."""
    global DRY_OK
    for label, apply in (("dry-run", False), ("apply", True)):
        d = case_dir("skills-authored-" + label)
        gsd.STAGE = os.path.join(d, "stage", "cfg")
        gsd.FORGE_SKILLS = os.path.join(d, "forge-skills")
        gsd.FORGE_AUTHORED = {"gsd-a"}
        write(os.path.join(gsd.STAGE, "skills", "gsd-a", "SKILL.md"), "upstream text\n")
        write(os.path.join(gsd.FORGE_SKILLS, "gsd-a", "SKILL.md"), "forge's own text\n")
        gsd.SKILL_PATCHES = {}
        gsd.CTX = gsd.lib.Ctx(apply, None, True)
        DRY_OK = not apply
        try:
            errors = []
            n, out, exc = call(gsd.sync_skills, errors)
        finally:
            gsd.CTX = gsd.lib.Ctx(True, None, True)
            gsd.FORGE_AUTHORED = REAL_AUTHORED
            DRY_OK = False
        kept = read(os.path.join(gsd.FORGE_SKILLS, "gsd-a", "SKILL.md"))
        if exc or errors or kept != "forge's own text\n" or "gsd-a" in out.split("forge skills vs package")[-1].split("\n", 2)[-1]:
            failures.append("skills authored over upstream: %s: raised %s, errors %s, gsd-a is %r (want forge's own), output %r"
                            % (label, exc, errors, kept, out))


def update_text_names_no_machine(failures):
    """The gsd-update patch payload is written into skills/gsd-update/SKILL.md, which a stranger
    generates: it must not name the author's checkout. Seen failing on a2e69f6:
    "update text: names an absolute path of this machine: ['gsd-update/forge-update-route: <home>/dev/Projects/forge/skills/', ...]" (five
    paths). The real
    SKILL_PATCHES are read from REAL_PATCHES, since the cases above replace gsd.SKILL_PATCHES."""
    bad = []
    for name, patches in REAL_PATCHES.items():
        for pid, op, anchor, payload in patches:
            if not payload.startswith("file:"):
                bad += ["%s/%s: %s" % (name, pid, m) for m in re.findall(r"/(?:home|Users|root)/[^\s`]*", payload)]
    if bad:
        failures.append("update text: names an absolute path of this machine: %s" % bad)


def unpatched_main(failures):
    """With gsd on and `gsd_patches` false, main() is a stranger's GSD, installed by GSD's own installer:
    it stages nothing, patches nothing, copies nothing, reaches for neither npm nor the package, prints
    one line that says so (no '!') and exits 0. With `gsd_patches` true it goes on to the package, as
    before. package_root, stage and the module's subprocess are replaced by ones that raise, so a gate
    that lets main() through shows up as the sentinel, and the toy HOME is checked for anything written.
    The positive control is the true case beside it: it reaches package_root. Seen failing before the
    gate: "unpatched main: gsd_patches false: raised Reached: package_root, output '', want one line
    saying unpatched, exit 0, nothing written" (main went on to the package), and the same for the absent
    key. The true case passes before the gate too: it is the positive control, and with `not` dropped
    from the gate it fails with "gsd_patches true: reached package_root False"."""
    class Reached(Exception):
        pass

    def package_root():
        raise Reached("package_root")

    class NoSubprocess:
        def __getattr__(self, name):
            raise Reached("subprocess.%s" % name)
    real = gsd.package_root, gsd.subprocess, gsd.lib.SETTINGS
    gsd.package_root, gsd.subprocess = package_root, NoSubprocess()
    try:
        for label, doc, patched in (("gsd_patches false", {"integrations": {"gsd": True}, "gsd_patches": False}, False),
                                    ("gsd_patches absent", {"integrations": {"gsd": True}}, False),
                                    ("gsd_patches true", {"integrations": {"gsd": True}, "gsd_patches": True}, True)):
            d = case_dir("unpatched-" + label.replace(" ", "-"))
            gsd.lib.SETTINGS = os.path.join(d, "forge.json")
            write(gsd.lib.SETTINGS, json.dumps(doc))
            code, out, exc = call(gsd.main)
            reached = exc == "Reached: package_root"
            written = [n for n in ("AGENTS_DIR", "GSD_DIR", "STAGE_ROOT") if os.path.exists(getattr(gsd, n))]
            lines = [l for l in out.splitlines() if l.strip()]
            if patched:
                if not reached or code is not None:
                    failures.append("unpatched main: %s: reached package_root %s, raised %s, output %r" % (label, reached, exc, out))
            elif exc or code != 0 or written or len(lines) != 1 or "unpatched" not in out or "!" in out:
                failures.append("unpatched main: %s: raised %s, exit %s, wrote %s, output %r, want one line "
                                "saying unpatched, exit 0, nothing written" % (label, exc, code, written, out))
    finally:
        gsd.package_root, gsd.subprocess, gsd.lib.SETTINGS = real


def check_mode(failures):
    """`--check` is what session start asks: read-only, and never a restage. Exit 0 when the runtime is what
    forge's staged, patched copy would write, 2 when it differs (a file, or a staging made for another
    package version), 1 on an error. The staged tree, the runtime and the package are toy trees; the module's
    subprocess raises, so a check that restages (runs GSD's installer) shows up as the sentinel, and the toy
    runtime's bytes and the staging's presence are compared after. Controls: the in-sync case is the one that
    must exit 0 (a check that always said 2 would fail it), and the differing file's case proves the compare
    reads the files. Seen failing on 26a3ed5, which has no --check: "check: a differing runtime file: exit 0
    (want 2), raised None, output 'MODE: DRY-RUN ...'" and "check: a staging for another version: raised
    Reached: subprocess.run" (the old main restages under any flag)."""
    class Reached(Exception):
        pass

    class NoSubprocess:
        def __getattr__(self, name):
            raise Reached("subprocess.%s" % name)
    paths = {n: getattr(gsd, n) for n in PATHS}  # the case points every one at its own toy dir
    real = (gsd.package_root, gsd.subprocess, gsd.CTX, getattr(gsd, "CHECK", False), gsd.AGENT_PATCHES, gsd.ENGINE_PATCHES,
            gsd.lib.SETTINGS)
    paths = {n: getattr(gsd, n) for n in PATHS}  # the case points every one at its own toy dir
    global DRY_OK
    DRY_OK = True
    gsd.subprocess, gsd.CTX, gsd.CHECK, gsd.AGENT_PATCHES, gsd.ENGINE_PATCHES = NoSubprocess(), gsd.lib.Ctx(False, None, True), True, {}, {}
    try:
        for label, runtime_text, stamp, want, scripts_in_runtime in (
                ("an in-sync runtime", "staged\n", "1.0.0\n", 0, True),
                ("a differing runtime file", "installed\n", "1.0.0\n", 2, True),
                ("a staging for another version", "staged\n", "0.9.0\n", 2, True),
                ("scripts staged but missing from the runtime", "staged\n", "1.0.0\n", 2, False)):
            d = case_dir("check-" + label.replace(" ", "-"))
            for n, v in (("AGENTS_DIR", "home/.claude/agents"), ("GSD_DIR", "home/.claude/get-shit-done"), ("STAGE_ROOT", "home/stage"),
                         ("SKILLS_MIRROR", "home/.claude/skills"), ("SCRIPTS_DIR", "home/.claude/scripts"), ("BLOCKS", "blocks"), ("GSD_DEFAULTS", "home/.gsd/defaults.json")):
                setattr(gsd, n, os.path.join(d, v))
            gsd.STAGE, gsd.STAMP = os.path.join(gsd.STAGE_ROOT, "cfg"), os.path.join(gsd.STAGE_ROOT, "STAGED-VERSION")
            gsd.NPM_STAMP = os.path.join(gsd.STAGE_ROOT, "NPM-CHECKED")
            pkg = os.path.join(d, "pkg")
            write(os.path.join(pkg, "package.json"), '{"version": "1.0.0"}')
            gsd.package_root = lambda pkg=pkg: pkg
            write(os.path.join(gsd.STAGE, "agents", "gsd-x.md"), "staged\n")
            write(os.path.join(gsd.STAGE, "get-shit-done", "e.md"), "staged\n")
            os.makedirs(os.path.join(gsd.STAGE, "skills"))
            write(gsd.STAMP, stamp)
            write(os.path.join(gsd.AGENTS_DIR, "gsd-x.md"), runtime_text)
            write(os.path.join(gsd.GSD_DIR, "e.md"), "staged\n")
            write(os.path.join(gsd.STAGE, "scripts", "fix-slash-commands.cjs"), "staged\n")
            if scripts_in_runtime:
                write(os.path.join(gsd.SCRIPTS_DIR, "fix-slash-commands.cjs"), "staged\n")
            write(os.path.join(gsd.BLOCKS, "defaults.json"), "{}\n")
            write(gsd.GSD_DEFAULTS, "{}\n")
            gsd.lib.SETTINGS = os.path.join(d, "forge.json")
            write(gsd.lib.SETTINGS, json.dumps({"integrations": {"gsd": True}, "gsd_patches": True}))
            before = {p: read(p) for p in (os.path.join(gsd.AGENTS_DIR, "gsd-x.md"), os.path.join(gsd.GSD_DIR, "e.md"), gsd.STAMP)}
            code, out, exc = call(gsd.main)
            after = {p: read(p) for p in before}
            if exc or code != want or before != after or not os.path.isdir(os.path.join(gsd.STAGE, "skills")):
                failures.append("check: %s: exit %s (want %d), raised %s, files untouched %s, output %r"
                                % (label, code, want, exc, before == after, out[-200:]))
        gsd.CTX = gsd.lib.Ctx(True, None, True)  # --check --apply writes nothing: it refuses
        try:
            gsd.main()
            failures.append("check: with --apply, main() returned instead of refusing")
        except SystemExit as e:
            if "--check reads only" not in str(e):
                failures.append("check: with --apply, exit message %r" % (e.code,))
    finally:
        (gsd.package_root, gsd.subprocess, gsd.CTX, gsd.CHECK, gsd.AGENT_PATCHES, gsd.ENGINE_PATCHES, gsd.lib.SETTINGS) = real
        for n, v in paths.items():
            setattr(gsd, n, v)
        DRY_OK = False


def scripts_beside_engine(failures):
    """gsd-core 1.18's engine requires ../../../scripts/*.cjs from gsd-core/bin/lib, so the staged scripts/ must land in
    ~/.claude/scripts, and the package's changeset/ release tooling must not. Seen failing before the sync existed:
    `node ~/.claude/gsd-core/bin/gsd-tools.cjs` died with "Cannot find module '../../../scripts/fix-slash-commands.cjs'"."""
    d = case_dir("scripts-beside-engine")
    gsd.STAGE = os.path.join(d, "stage")
    gsd.SCRIPTS_DIR = os.path.join(d, "home", ".claude", "scripts")
    for rel in ("fix-slash-commands.cjs", os.path.join("lib", "cli-exit.cjs"), os.path.join("changeset", "x.md")):
        write(os.path.join(gsd.STAGE, "scripts", rel), "staged\n")
    errors = []
    n, out, exc = call(lambda: gsd.sync_tree(os.path.join(gsd.STAGE, "scripts"), gsd.SCRIPTS_DIR, {}, "scripts", errors,
                                              only=gsd.scripts_wanted))
    landed = sorted(os.path.relpath(os.path.join(b, f), gsd.SCRIPTS_DIR)
                    for b, _d, fs in os.walk(gsd.SCRIPTS_DIR) for f in fs) if os.path.isdir(gsd.SCRIPTS_DIR) else []
    want = ["fix-slash-commands.cjs", os.path.join("lib", "cli-exit.cjs")]
    if exc or errors or landed != sorted(want):
        failures.append("scripts beside the engine: raised %s, errors %s, landed %s, want %s" % (exc, errors, landed, want))


def package_location(failures):
    """package_root() finds `@opengsd/gsd-core` where mise installed it (`mise where npm:@opengsd/gsd-core`, then
    node_modules/@opengsd/gsd-core under it), else under `npm root -g`, else exits naming the package and the fix.
    `mise` and `npm` are scripts of the case on PATH, so neither the machine's mise nor its npm answers. Seen failing on
    43a581a, which looks for get-shit-done-cc under `npm root -g` alone: "package location: mise knows it: returned
    SystemExit: ! get-shit-done-cc not found under `npm root -g` (<toy>/npm-root) -- is GSD installed?" (and the
    same for the other two cases)."""
    d = case_dir("package-location")
    pkg_rel = os.path.join("node_modules", "@opengsd", "gsd-core")
    mise_dir, npm_root = os.path.join(d, "mise-install"), os.path.join(d, "npm-root")
    write(os.path.join(mise_dir, pkg_rel, "package.json"), '{"version": "1.0.0"}')
    write(os.path.join(npm_root, "@opengsd", "gsd-core", "package.json"), '{"version": "1.0.0"}')
    bindir = os.path.join(d, "bin")

    def tools(mise_answer, npm_answer):
        write(os.path.join(bindir, "mise"), "#!/bin/sh\n%s\n" % (
            'echo "%s"' % mise_answer if mise_answer else 'echo "mise ERROR not installed" >&2; exit 1'))
        write(os.path.join(bindir, "npm"), "#!/bin/sh\necho '%s'\n" % npm_answer)
        for n in ("mise", "npm"):
            os.chmod(os.path.join(bindir, n), 0o755)
    real_path = os.environ["PATH"]
    os.environ["PATH"] = bindir + os.pathsep + real_path
    try:
        for label, mise_answer, npm_answer, want in (
                ("mise knows it", mise_dir, os.path.join(d, "empty"), os.path.join(mise_dir, pkg_rel)),
                ("only npm root -g has it", None, npm_root, os.path.join(npm_root, "@opengsd", "gsd-core")),
                ("neither has it", None, os.path.join(d, "empty"), None)):
            tools(mise_answer, npm_answer)
            try:
                got = gsd.package_root()
            except SystemExit as e:
                got = str(e)
            if want is None:
                if not (isinstance(got, str) and "@opengsd/gsd-core" in got and "forge toolchain --fix" in got):
                    failures.append("package location: %s: returned %r, want an exit naming the package and `forge toolchain --fix`" % (label, got))
            elif got != want:
                failures.append("package location: %s: returned %r, want %r" % (label, got, want))
    finally:
        os.environ["PATH"] = real_path


def real_package(failures):
    """Against the real `@opengsd/gsd-core` (staged by its own installer into a toy dir; skipped, with a printed
    line, when the package, node or the installer's output is missing): every patch's anchor matches the staged text and
    changes it, and every agent Ponytail's subagent hook gives its ruleset to (hooks/ponytail_subagent.py AGENTS)
    exists, so a rename upstream cannot switch Ponytail off in silence. Seen failing on 43a581a, whose patches were
    written for get-shit-done-cc 1.42.3: "real package: gsd-planner.md: anchor for patch 'planner-edit' no longer
    matches upstream" and four more (reach-routing twice, classifier-hash-dispatch, npm-package-name, no-graphify)."""
    try:
        pkg = gsd.package_root()
    except SystemExit as e:
        print("SKIP real_package: NOT RUN, NOT ARMED: %s" % e)
        return
    if not shutil.which("node"):
        print("SKIP real_package: NOT RUN, NOT ARMED: no node")
        return
    d = case_dir("real-package")
    saved = {n: getattr(gsd, n) for n in ("STAGE_ROOT", "STAGE", "STAMP", "BLOCKS")}
    gsd.BLOCKS = os.path.join(FORGE, "config", "gsd")  # the real prose payloads: the patches are the real ones
    gsd.STAGE_ROOT = os.path.join(gsd.HOME, ".cache", "forge", "gsd-stage")  # under HOME: the installer then writes `~/` and `$HOME/` forms
    gsd.STAGE, gsd.STAMP = os.path.join(gsd.STAGE_ROOT, "cfg"), os.path.join(gsd.STAGE_ROOT, "STAGED-VERSION")
    try:
        os.makedirs(gsd.STAGE_ROOT)
        guard_ok = os.path.realpath(gsd.STAGE).startswith(TOY + os.sep)
        if not guard_ok:
            sys.exit("FAIL harness: the staging dir is outside the toy root")
        shutil.rmtree(gsd.STAGE_ROOT, ignore_errors=True)
        os.makedirs(gsd.STAGE_ROOT)
        gsd.stage(pkg, gsd.package_version(pkg))
        errors = []
        leaks = []
        for base, _dirs, files in os.walk(gsd.STAGE):
            for fn in files:
                try:
                    text = gsd.normalize(read(os.path.join(base, fn)))
                except UnicodeDecodeError:
                    continue
                if "gsd-stage" in text:
                    leaks.append(os.path.relpath(os.path.join(base, fn), gsd.STAGE))
        if leaks:
            failures.append("real package: %d staged file(s) still name the staging directory after normalising, e.g. %s"
                            % (len(leaks), leaks[:3]))
        for kind, patches, base, path in (("agents", gsd.AGENT_PATCHES, "agents", "%s"), ("engine", gsd.ENGINE_PATCHES, "gsd-core", "%s"),
                                          ("skills", REAL_PATCHES, "skills", "%s/SKILL.md")):
            for name, plist in patches.items():
                src = os.path.join(gsd.STAGE, base, path % name)
                if not os.path.isfile(src):
                    failures.append("real package: %s %s is not in the staged package" % (kind, name))
                    continue
                before = len(errors)
                staged = gsd.normalize(read(src))
                got = gsd.apply_patches(staged, name, plist, errors)
                if len(errors) == before and got == staged:
                    failures.append("real package: %s: patches %s change nothing, so they are retired or already upstream"
                                    % (name, [p[0] for p in plist]))
        failures += ["real package: " + e for e in errors]
        names = {n for n in os.listdir(os.path.join(gsd.STAGE, "skills"))} | {f[:-3] for f in os.listdir(os.path.join(gsd.STAGE, "agents"))}
        if "gsd-ns-context" in REAL_PATCHES:
            failures.append("real package: gsd-ns-context is patched (%s), but every skill it routes to is shipped now"
                            % [p[0] for p in REAL_PATCHES["gsd-ns-context"]])
        router = read(os.path.join(gsd.STAGE, "skills", "gsd-ns-context", "SKILL.md"))
        dangling = sorted(set(re.findall(r"\|\s*(gsd-[a-z0-9-]+)[^|]*\|\s*$", router, re.M)) - names)
        if dangling:
            failures.append("real package: gsd-ns-context routes to %s, which the package does not ship" % dangling)
        spec = importlib.util.spec_from_file_location("ponytail_subagent", os.path.join(FORGE, "hooks", "ponytail_subagent.py"))
        ponytail = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ponytail)
        agents = {f[:-3] for f in os.listdir(os.path.join(gsd.STAGE, "agents")) if f.endswith(".md")}
        if not ponytail.AGENTS or ponytail.AGENTS - agents:
            failures.append("real package: Ponytail's agents %s are not all staged agents (missing %s)"
                            % (sorted(ponytail.AGENTS), sorted(ponytail.AGENTS - agents)))
    finally:
        for n, v in saved.items():
            setattr(gsd, n, v)


def defaults_uncapped(failures):
    """forge sets no GSD default: config/gsd/defaults.json is an empty object, so a new project gets GSD's own
    (ui_phase and ui_safety_gate on: no cap), and a ~/.gsd/defaults.json that holds forge's
    EARLIER text (the one that switched both off) is forge's own stale copy: replaced, dry-run and apply, where a
    file that differs from both is still the user's and left alone (defaults_copy). Seen failing on c2a741a:
    "defaults uncapped: shipped file is {'workflow': {'ui_phase': False, 'ui_safety_gate': False}}, want {}" and
    "defaults uncapped: forge's earlier text, apply: ... 'differs from ... left alone'"."""
    shipped = json.loads(read(os.path.join(FORGE, "config", "gsd", "defaults.json")))
    if shipped != {}:
        failures.append("defaults uncapped: shipped file is %r, want {}" % (shipped,))
    for apply in (False, True):
        src, dst = defaults_world("defaults-former-%s" % apply)
        write(dst, gsd.FORMER_DEFAULTS[0])
        out, exc, errors = run_defaults(apply)
        got = read(dst)
        if exc or errors or LAST_CHANGES[0] != 1 or "earlier text" not in out or got != (read(src) if apply else gsd.FORMER_DEFAULTS[0]):
            failures.append("defaults uncapped: forge's earlier text, apply=%s: raised %s, errors %s, changes %s, file now %r: %s"
                            % (apply, exc, errors, LAST_CHANGES[0], got, sandbox.tail(out, 2)))


def hooks_tree(failures):
    """The staged hooks go to ~/.claude/hooks (gsd-core's own place) except the two files forge keeps its own
    version of (hooks/gsd-prompt-guard.js, hooks/gsd-read-injection-scanner.js, hardened, wired from forge's hooks/)
    and the scripts of other runtimes; hooks/lib and the registry go with them, which the hooks require. Seen failing
    on c2a741a: "hooks tree: wanted ... AttributeError: module 'sync_gsd_runtime' has no attribute 'hook_wanted'"."""
    want = {"gsd-context-monitor.js": True, "gsd-workflow-guard.js": True, "gsd-session-state.sh": True,
            "lib/hook-exit.js": True, "lib/injection-patterns.js": True, "managed-hooks-registry.cjs": True,
            "gsd-prompt-guard.js": False, "gsd-read-injection-scanner.js": False, "gsd-cursor-stop.js": False,
            "gsd-windsurf-pre-write.js": False}
    try:
        got = {rel: gsd.hook_wanted(rel) for rel in want}
    except AttributeError as e:
        failures.append("hooks tree: %s" % e)
        return
    if got != want:
        failures.append("hooks tree: wanted %s, want %s" % ({k: v for k, v in got.items() if v != want[k]}, {k: v for k, v in want.items() if got[k] != v}))
    d = case_dir("hooks-tree")
    gsd.STAGE = os.path.join(d, "stage", "cfg")
    gsd.HOOKS_DIR = os.path.join(d, "home", ".claude", "hooks")
    for rel in ("gsd-context-monitor.js", "lib/hook-exit.js", "gsd-prompt-guard.js"):
        write(os.path.join(gsd.STAGE, "hooks", rel), "staged %s\n" % rel)
    errors = []
    n, out, exc = call(lambda: gsd.sync_tree(os.path.join(gsd.STAGE, "hooks"), gsd.HOOKS_DIR, {}, "hooks", errors, only=gsd.hook_wanted))
    if exc or errors or n != 2 or os.path.exists(os.path.join(gsd.HOOKS_DIR, "gsd-prompt-guard.js")):
        failures.append("hooks tree: raised %s, errors %s, would change %s (want 2: the monitor and lib/hook-exit.js), forge-owned file copied %s"
                        % (exc, errors, n, os.path.exists(os.path.join(gsd.HOOKS_DIR, "gsd-prompt-guard.js"))))


def normalize_forms(failures):
    """The installer writes the staging directory into the text in three spellings: `$HOME/<rel>`, `~/<rel>` (gsd-core's
    @-references) and the absolute path; each goes back to the real config dir in its own spelling, and one left
    over is an error, not a file that points into the cache. Seen failing on bb37a85, which knew two of the three:
    "normalize forms: '@~/.cache/forge/gsd-stage/cfg/gsd-core/x.md' became itself, want '@~/.claude/gsd-core/x.md'"
    (59 of 75 skills, 27 agents and 77 engine files on this machine carried it) and "leak: no error for a file that
    still names the staging directory"."""
    saved = gsd.STAGE
    rel = os.path.join(".cache", "forge", "gsd-stage", "cfg")
    gsd.STAGE = os.path.join(gsd.HOME, rel)
    try:
        for label, text, want in (
                ("$HOME form", "@$HOME/%s/gsd-core/x.md" % rel, "@$HOME/.claude/gsd-core/x.md"),
                ("~ form", "@~/%s/gsd-core/x.md" % rel, "@~/.claude/gsd-core/x.md"),
                ("absolute form", "%s/gsd-core/x.md" % gsd.STAGE, "$HOME/.claude/gsd-core/x.md"),
                ("bare directory, ~ form", "cd ~/%s" % rel, "cd ~/.claude"),
                ("bare directory, $HOME form", "cd $HOME/%s" % rel, "cd $HOME/.claude")):
            got = gsd.normalize(text)
            if got != want:
                failures.append("normalize forms: %s: %r became %r, want %r" % (label, text, got, want))
        d = case_dir("normalize-leak")
        src = os.path.join(d, "x.md")
        write(src, "see ${HOMEDIR}/%s/gsd-core/x.md\n" % rel)  # a spelling the installer does not use, and no rule knows
        errors = []
        gsd.want_text(src, "x.md", [], errors)
        if not any("staging directory" in e and "x.md" in e for e in errors):
            failures.append("normalize forms: no error for a file that still names the staging directory: %s" % errors)
        write(src, "see ~/.claude/gsd-core/x.md\n")
        errors = []
        gsd.want_text(src, "x.md", [], errors)
        if errors:
            failures.append("normalize forms: a clean file raised %s" % errors)
    finally:
        gsd.STAGE = saved


def quick_lean(failures):
    """`gsd-quick` means quick: ENGINE_PATCHES puts a short "forge lean path" block first in workflows/quick.md, a
    `replace` on the exact `<purpose>` line (config/gsd/quick-lean.md), so an upstream rewrite of that line is an error,
    not a silent skip. The block names the state GSD reads back and keeps it (the SUMMARY.md with `status: complete`
    that audit-open scans, the STATE.md row through quick-tasks-append, the branching, the ROADMAP.md gate), turns the
    subagent steps off by default, and leaves the four flags as the way back to the full pipeline. Cases: (1) the entry
    exists, is a replace anchored on `<purpose>`, its payload file exists and names the kept state, the flags and every
    step it overrides; (2) on a toy file whose first line is `<purpose>` the block lands first and a second application
    changes nothing; (3) on the real staged quick.md (read only; NOT RUN, NOT ARMED when there is no staging) the
    patch applies without an error and the block is the first thing in the file. Seen failing on a59e67d:
    "quick lean: ENGINE_PATCHES has no entry for workflows/quick.md (keys: ['workflows/ingest-docs.md',
    'references/mandatory-initial-read.md'])", and cases 2 and 3 with "quick lean: toy: no patch to apply" and
    "quick lean: real staged quick.md: no patch to apply". Negative control (a backup copy of sync_gsd_runtime.py with
    the ENGINE_PATCHES entry removed, restored from the backup): case 1 fails with the message above."""
    entries = gsd.ENGINE_PATCHES.get("workflows/quick.md")
    if not entries:
        failures.append("quick lean: ENGINE_PATCHES has no entry for workflows/quick.md (keys: %s)" % list(gsd.ENGINE_PATCHES))
        failures.append("quick lean: toy: no patch to apply")
        failures.append("quick lean: real staged quick.md: no patch to apply")
        return
    real_blocks = os.path.join(FORGE, "config", "gsd")
    if len(entries) != 1 or entries[0][1] != "replace" or entries[0][2] != "<purpose>" or not entries[0][3].startswith("file:"):
        failures.append("quick lean: want one `replace` anchored on '<purpose>' with a file: payload, got %s" % [(e[0], e[1], e[2]) for e in entries])
        return
    block = read(os.path.join(real_blocks, entries[0][3][5:]))
    if block is None:
        failures.append("quick lean: payload file %s does not exist" % entries[0][3][5:])
        return
    if not block.startswith("<purpose>\n") or not block.endswith("\n"):
        failures.append("quick lean: the payload must begin with the `<purpose>` line and end with a newline, begins %r" % block[:20])
    must = ("SUMMARY.md", "status: complete", "STATE.md", "Quick Tasks Completed", "quick-tasks-append", "roadmap_exists",
            "--full", "--validate", "--discuss", "--research", "ROADMAP.md", "Step 2.5", "Step 5", "Step 6", "Step 6.25",
            "Step 6.5", "Step 7", "Step 8", "no subagent")
    gone = [m for m in must if m not in block]
    if gone:
        failures.append("quick lean: the block does not name %s" % gone)
    saved = gsd.BLOCKS
    gsd.BLOCKS = real_blocks
    try:
        patches = {"workflows/quick.md": entries}
        toy = "<purpose>\nUpstream first sentence.\n</purpose>\n\n<process>\nrest\n</process>\n"
        once = gsd.apply_patches(toy, "workflows/quick.md", entries, errs := [])
        twice = gsd.apply_patches(once, "workflows/quick.md", entries, errs)
        if errs or not once.startswith(block) or once.count(block) != 1 or not once.endswith(toy[len("<purpose>\n"):]):
            failures.append("quick lean: toy: errors %s, block first %s, block count %d, rest of the file kept %s"
                            % (errs, once.startswith(block), once.count(block), once.endswith(toy[len("<purpose>\n"):])))
        if twice != once:
            failures.append("quick lean: toy: a second application changed the text")
        drift = gsd.apply_patches("<intro>\nupstream rewrote the first line\n", "workflows/quick.md", entries, errs2 := [])
        if len(errs2) != 1 or drift != "<intro>\nupstream rewrote the first line\n":
            failures.append("quick lean: toy: a missing anchor gave errors %s (want one) and text %r" % (errs2, drift))
        import pwd
        stage = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".cache", "forge", "gsd-stage", "cfg", "gsd-core", "workflows", "quick.md")
        if not os.path.isfile(stage):
            print("SKIP quick_lean real staged quick.md: NOT RUN, NOT ARMED: no staging at %s" % stage)
            return
        staged = read(stage)
        got = gsd.apply_patches(staged, "workflows/quick.md", entries, errs3 := [])
        if errs3 or not got.startswith(block) or got == staged or not got.endswith(staged[len("<purpose>\n"):]):
            failures.append("quick lean: real staged quick.md: errors %s, block first %s, changed %s" % (errs3, got.startswith(block), got != staged))
    finally:
        gsd.BLOCKS = saved


def quick_lean_readers(failures):
    """The lean path of quick_lean once wrote no PLAN.md, but the gsd-quick skill's `status <slug>` and `resume <slug>`
    read the task description from it ("first non-empty line from PLAN.md after frontmatter", "description from PLAN.md"),
    so a lean task was invisible to both, and its resume rule ("a quick directory that already has a PLAN.md runs the
    full pipeline") would have sent a lean task into the heavy path once it had one. The block now writes a minimal
    PLAN.md (frontmatter with `mode: lean`, the description alone on the first line after it, a short checklist) where
    the planner would have, and the skill text that told the agent to spawn a planner and an executor and to "Preserve
    all workflow gates" is replaced by a SKILL_PATCHES entry for gsd-quick. Cases: (a) the payload names the minimal
    PLAN.md, the two readers (`status <slug>`, `resume <slug>`), the fields they read and the `mode: lean` marker, and
    those fields exist in the real staged skill's STATUS and RESUME text (read only; NOT RUN, NOT ARMED without a
    staging); (b) SKILL_PATCHES has a gsd-quick entry, and with it applied the two old sentences are gone, the text
    changed and a second application changes nothing. Seen failing on the branch before the fix (bfbe9e6):
    "quick lean readers: the block does not name ['minimal PLAN.md', '`status <slug>`', '`resume <slug>`',
    'first non-empty line', 'after frontmatter', 'mode: lean']" and "quick lean readers: SKILL_PATCHES has no entry for
    gsd-quick (keys: [...])". Negative control (a backup copy of config/gsd/quick-lean.md with the sentence that names
    the minimal PLAN.md deleted, restored from the backup): case (a) fails with the first message."""
    entries = gsd.ENGINE_PATCHES.get("workflows/quick.md")
    block = read(os.path.join(FORGE, "config", "gsd", entries[0][3][5:])) if entries and entries[0][3].startswith("file:") else None
    if block is None:
        failures.append("quick lean readers: no payload file to read (quick_lean reports why)")
    else:
        need = ("minimal PLAN.md", "`status <slug>`", "`resume <slug>`", "first non-empty line", "after frontmatter", "mode: lean")
        gone = [m for m in need if m not in block]
        if gone:
            failures.append("quick lean readers: the block does not name %s" % gone)
    import pwd
    home = pwd.getpwuid(os.getuid()).pw_dir
    stage_skill = os.path.join(home, ".cache", "forge", "gsd-stage", "cfg", "skills", "gsd-quick", "SKILL.md")
    staged = read(stage_skill) if os.path.isfile(stage_skill) else None
    if staged is None:
        print("SKIP quick_lean_readers real staged gsd-quick skill: NOT RUN, NOT ARMED: no staging at %s" % stage_skill)
    else:
        status_part = staged.split("## STATUS subcommand")[1].split("## RESUME subcommand")[0] if "## STATUS subcommand" in staged else ""
        resume_part = staged.split("## RESUME subcommand")[1].split("## RUN subcommand")[0] if "## RESUME subcommand" in staged else ""
        if "first non-empty line" not in status_part or "after frontmatter" not in status_part or "PLAN.md" not in resume_part:
            failures.append("quick lean readers: the staged skill's STATUS/RESUME text no longer reads the description from PLAN.md "
                            "as the block says (status has the fields %s, resume names PLAN.md %s)"
                            % ("first non-empty line" in status_part and "after frontmatter" in status_part, "PLAN.md" in resume_part))
    skill_entries = REAL_PATCHES.get("gsd-quick")
    if not skill_entries:
        failures.append("quick lean readers: SKILL_PATCHES has no entry for gsd-quick (keys: %s)" % sorted(REAL_PATCHES))
        return
    old = ("- Spawns gsd-planner (quick mode) + gsd-executor(s)", "Preserve all workflow gates")
    toy = "\n".join(("intro", old[0], "mid", "Execute end-to-end.",
                     "Preserve all workflow gates (validation, task description, planning, execution, state updates, commits).", "end"))
    for label, text in (("toy", toy), ("real staged skill", staged)):
        if text is None:
            continue
        got = gsd.apply_patches(text, "gsd-quick", skill_entries, errs := [])
        again = gsd.apply_patches(got, "gsd-quick", skill_entries, errs)
        left = [o for o in old if o in got]
        if errs or left or got == text or again != got:
            failures.append("quick lean readers: %s: errors %s, old sentences left %s, changed %s, second application stable %s"
                            % (label, errs, left, got != text, again == got))


def quick_lean_review(failures):
    """An independent review found the lean block under-specified. Each assertion below is one finding: (1) a lean
    `resume` was not defined (`init.quick` mints a new quick id, a null task_dir and a new branch, and Step 1 would read
    `resume foo` as the description), (2) a failed or empty commit at item 6 let Step 7 record an unrelated HEAD,
    (3) `{type}` was undefined, (4) the project's own check was not named, (5) Step 7c did not say what to pass for
    --status, (6) the upstream <purpose> text that still follows the block says quick mode spawns a planner and
    executors, (7) the block cited upstream line numbers that cannot be counted in the patched file. Seen failing on
    the branch before the fix (4a6397b): "quick lean review: the block does not say ['quick_id from the directory name',
    'skip quick-tasks-append', 'no PLAN.md in the directory', 'do not run Step 7', '{type} is feat, fix, refactor, docs,
    chore or test', 'Run the check named in CLAUDE.md', 'Status column', 'upstream's description of the full pipeline',
    'no planner or executor is spawned']" and "quick lean review: the block still cites 'upstream lines 701'". Negative
    control (a backup copy of config/gsd/quick-lean.md with the failed-commit sentence deleted, restored from the
    backup): the first message names 'do not run Step 7'."""
    entries = gsd.ENGINE_PATCHES.get("workflows/quick.md")
    block = read(os.path.join(FORGE, "config", "gsd", entries[0][3][5:])) if entries and entries[0][3].startswith("file:") else None
    if block is None:
        failures.append("quick lean review: no payload file to read (quick_lean reports why)")
        return
    flat = " ".join(block.split())
    need = ("quick_id from the directory name", "skip quick-tasks-append", "no PLAN.md in the directory", "do not run Step 7",
            "{type} is feat, fix, refactor, docs, chore or test", "Run the check named in CLAUDE.md", "Status column",
            "upstream's description of the full pipeline", "no planner or executor is spawned")
    gone = [m for m in need if m not in flat]
    if gone:
        failures.append("quick lean review: the block does not say %s" % gone)
    if "upstream lines 701" in block:
        failures.append("quick lean review: the block still cites 'upstream lines 701'")
    # item 5 must not tell the agent to tick the checklist (that moved to item 6, after the commit step)
    item5 = flat.split("5a. **Where Step 5")[0].split("5. **The discussion")[-1]
    if "Tick the PLAN.md checklist" in item5:
        failures.append("quick lean review: the tick sentence is still in item 5 instead of item 6")
    if "Tick the PLAN.md checklist" not in flat.split("6. **Step 6 (executor's commit)")[-1].split("7. **Step 6")[0]:
        failures.append("quick lean review: item 6 does not tick the PLAN.md checklist")


def main():
    failures = []
    cases = (tree_failed_anchor, tree_control, skills_failed_anchor, skills_control,
             tree_missing_target, skills_missing_target, tree_crlf, tree_blocked_path, tree_not_utf8, skills_crlf,
             refs_no_dirs, refs_no_agents, refs_forge_only, npm_nag_throttle, defaults_copy,
             defaults_gsd_reads, skills_no_dir, update_text_names_no_machine, unpatched_main, check_mode, scripts_beside_engine, package_location, real_package, normalize_forms, skills_all_shipped, skills_authored_over_upstream, defaults_uncapped, hooks_tree, quick_lean, quick_lean_readers, quick_lean_review)
    for case in cases:
        case(failures)
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over %d cases" % (len(failures), len(cases)))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
