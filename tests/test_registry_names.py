#!/usr/bin/env python3
"""The registry of projects is called "project", not "profile" (plan 4.4, U14): the one file each project has is
config/projects/<name>.claude.json, read by lib.projects(), its fields typed by lib.PROJECT_FIELDS and checked by
lib.project_error. "Profile" is left free for the set of skills, plugins and servers one session uses (@profile).

1. No tracked file holds an old registry name (the path config/profiles and its os.path.join spelling, PROFILE_FIELDS,
   profile_error, lib.profiles(, lib.PROFILES), except a line that names the new folder as well: the lines that
   explain the rename and the one-line instruction below. `--at REV` counts the old names in a commit instead.
   In a copy with no checkout the scan cannot run: the last line says NOT RUN, NOT ARMED and the exit is 77.
   Control: one name put back in a copy of a file is reported as `old registry name in <file>:<line>`.
2. While the owner's data moves (U15), the registry may be found only under its old name. lib.projects() then exits
   1 with `config/profiles/ was renamed config/projects/: mv config/profiles config/projects`; without the check it
   returned {} and every project vanished silently. A config/projects -> profiles link is the bridge: read and
   written through, as before.
3. Writing a project file there (forge new) exits 1 the same way; without the check lib.write_text created a real
   config/projects/ holding the one new file, a split registry nobody noticed.

Seen failing first, at the branch point (1f20680), before the rename:
  FAIL tracked files hold no old registry name -- 333 hit(s), first: old registry name in CLAUDE.md:124 (PROFILE_FIELDS)
  (--at 1f20680: config/profiles 74 lines, "config", "profiles" 86, PROFILE_FIELDS 20, profile_error 51,
  lib.profiles( 31, lib.PROFILES 71)
  AttributeError: module 'forge.lib' has no attribute 'PROJECTS'
After the rename, with `sys.exit(RENAMED)` taken out of lib.require_registry (negative control, run by hand):
  FAIL old folder only: lib.projects() exits 1 naming the mv -- projects vanished silently: {}
  FAIL old folder only: write_text into config/projects/ exits 1 naming the mv -- split registry written silently:
  ['fresh.claude.json']
  FAIL old folder only: the process exits 1 with the one line on stderr -- rc=0 stderr=''
A config/projects link that leads nowhere is no bridge; red while the condition used lexists:
  FAIL dangling link: lib.projects() exits 1 naming the mv -- the projects read as {}
  FAIL dangling link: write_text into config/projects/ exits 1 naming the mv -- wrote through it: None
Onto such a link the mv alone fails, and a plain file under the new name is no registry either; red while
the condition used exists and there was one line:
  FAIL dangling link: lib.projects() exits 1 naming the rm and the mv -- got '... : mv config/... config/projects'
  NotADirectoryError: [Errno 20] Not a directory: '.../config/projects'   (the plain file)"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

failures, n_checks = [], [0]


def check(name, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(name)
        print("FAIL %s -- %s" % (name, detail))


OLD = ["config/" + "profiles", '"config", "' + 'profiles"', "PROFILE" + "_FIELDS", "profile" + "_error",
       "lib." + "profiles(", "lib." + "PROFILES"]
NEW_DIR = re.compile(r'config/projects|"config", "projects"')
# Never the registry: an excluded history or a file whose word has another sense (the measurement's N files).
EXCLUDED = re.compile(r"^(docs/archive/|framework-discuss/|benchmarks/|design/)")
SELF = "tests/test_registry_names.py"  # names the old ones to explain them


def hits_in(name, text):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if NEW_DIR.search(line):
            continue
        for old in OLD:
            if old in line:
                out.append("old registry name in %s:%d (%s)" % (name, i, old))
    return out


def scan(root, files):
    out, looked = [], 0
    for f in files:
        p = os.path.join(root, f)
        if not f or f == SELF or EXCLUDED.search(f) or os.path.islink(p) or not os.path.isfile(p):
            continue
        try:
            text = open(p, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue
        looked += 1
        out += hits_in(f, text)
    return out, looked


def tracked(root):
    """The tracked files, or None when `root` is no git checkout (a plain copy): the scan cannot run there."""
    r = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True)
    return r.stdout.split("\n") if r.returncode == 0 else None


def at(rev):
    """Count the old names in commit `rev`, lines per name, the way the scan reads them."""
    for old in OLD:
        r = subprocess.run(["git", "-C", ROOT, "grep", "-n", "-F", "-e", old, rev, "--", ".",
                            ":!docs/archive", ":!framework-discuss", ":!benchmarks", ":!design", ":!" + SELF],
                           capture_output=True, text=True)
        lines = [l for l in r.stdout.splitlines() if not NEW_DIR.search(l)]
        print("%-22s %d line(s) at %s" % (old, len(lines), rev))


if "--at" in sys.argv:
    at(sys.argv[sys.argv.index("--at") + 1])
    sys.exit(0)

# 1. The scan over every tracked file, and its control.
files = tracked(ROOT)
not_run = None if files is not None else "%s is no git checkout, so the tracked files were not scanned" % ROOT
if files is not None:
    hits, looked = scan(ROOT, files)
    check("the scan read the tracked files", looked > 100, "read %d file(s)" % looked)
    check("tracked files hold no old registry name", not hits,
          "%d hit(s), first: %s" % (len(hits), "; ".join(hits[:5])))
planted = hits_in("forge/lib.py", "x = 1\nnames = lib." + "profiles()\n")
check("control: a name put back is reported with its file and line",
      planted == ["old registry name in forge/lib.py:2 (lib." + "profiles()"], repr(planted))
check("control: a line that names the new folder too is the rename's own text, not a hit",
      not hits_in("x", "config/" + "profiles/ was renamed config/projects/\n"), "")

# 2 and 3. The old folder only, the link, and the split write; in a toy checkout's config/ with lib pointed at it.
from forge import lib  # noqa: E402

top = sandbox.mkdtemp("registry-names-")
try:
    cfg = os.path.join(top, "config")
    old_dir, new_dir = os.path.join(cfg, "profiles"), os.path.join(cfg, "projects")
    os.makedirs(old_dir)
    with open(os.path.join(old_dir, "demo.claude.json"), "w") as fh:
        fh.write('{"project": "demo", "project_path": "/srv/demo"}\n')
    real = lib.PROJECTS
    lib.PROJECTS = new_dir
    try:
        def exits(fn):
            try:
                got = fn()
            except SystemExit as e:
                return e.code
            return got

        got = exits(lib.projects)
        check("old folder only: lib.projects() exits 1 naming the mv", got == lib.RENAMED,
              "projects vanished silently: %r" % (got,))
        got = exits(lambda: lib.write_text(os.path.join(new_dir, "fresh.claude.json"), "{}\n"))
        check("old folder only: write_text into config/projects/ exits 1 naming the mv", got == lib.RENAMED,
              "split registry written silently: %r" % (sorted(os.listdir(new_dir)) if os.path.isdir(new_dir) else got,))
        check("old folder only: nothing was created under config/projects/", not os.path.lexists(new_dir), "")
        check("the instruction is the one line the plan names",
              lib.RENAMED == "config/" + "profiles/ was renamed config/projects/: mv config/" + "profiles config/projects",
              repr(lib.RENAMED))
        r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from forge import lib; "
                            "lib.PROJECTS = %r; lib.projects()" % (ROOT, new_dir)],
                           capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        check("old folder only: the process exits 1 with the one line on stderr",
              r.returncode == 1 and r.stderr == lib.RENAMED + "\n", "rc=%r stderr=%r" % (r.returncode, r.stderr))
        # A write elsewhere is not the registry's business.
        other = os.path.join(top, "elsewhere", "x.json")
        check("old folder only: a write outside config/projects/ goes on", exits(lambda: lib.write_text(other, "{}\n")) is None
              and os.path.isfile(other), "")

        # The bridge of U15: config/projects -> profiles.
        if os.path.isdir(new_dir) and not os.path.islink(new_dir):
            sandbox.rmtree(new_dir)  # the split folder the write made when the check failed above
        os.symlink("profiles", new_dir)
        check("link: lib.projects() reads through it", list(lib.projects()) == ["demo"], repr(lib.projects()))
        lib.write_text(os.path.join(new_dir, "fresh.claude.json"), '{"project": "fresh", "project_path": "/srv/fresh"}\n')
        check("link: a new file written through it lands in the real folder and the link stays",
              os.path.islink(new_dir) and sorted(os.listdir(old_dir)) == ["demo.claude.json", "fresh.claude.json"],
              repr(sorted(os.listdir(old_dir))))
        check("link: lib.projects() sees the new file", sorted(lib.projects()) == ["demo", "fresh"], repr(lib.projects()))

        # A link that leads nowhere is no bridge: the registry would read as empty.
        os.remove(new_dir)
        os.symlink("gone", new_dir)
        # The mv alone fails onto a link (ENOTDIR), so the line says to remove what is in the way first.
        blocked = ("config/" + "profiles/ was renamed config/projects/ and config/projects is not a folder: "
                   "rm config/projects, then mv config/" + "profiles config/projects")
        got = exits(lib.projects)
        check("dangling link: lib.projects() exits 1 naming the rm and the mv", got == blocked, "got %r" % (got,))
        got = exits(lambda: lib.write_text(os.path.join(new_dir, "fresh2.claude.json"), "{}\n"))
        check("dangling link: write_text into config/projects/ exits 1 naming the rm and the mv", got == blocked,
              "wrote through it: %r" % (got,))
        # A plain file under the new name is no registry either: it would read as no projects.
        os.remove(new_dir)
        open(new_dir, "w").close()
        got = exits(lib.projects)
        check("plain file: lib.projects() exits 1 naming the rm and the mv", got == blocked, "the projects read as %r" % (got,))
        os.remove(new_dir)
        os.symlink("profiles", new_dir)

        # After the move: the new folder only, and neither (a toy checkout has none).
        os.remove(new_dir)
        os.rename(old_dir, new_dir)
        check("moved: lib.projects() reads config/projects/", sorted(lib.projects()) == ["demo", "fresh"], repr(lib.projects()))
        os.rename(new_dir, os.path.join(top, "aside"))
        check("neither folder: no projects, no exit (a toy checkout)", exits(lib.projects) == {}, "")
    finally:
        lib.PROJECTS = real
finally:
    sandbox.cleanup()

print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
if not failures and not_run:
    # Neither a pass nor a fail (rule 4): forge test shows the last line as a WARN.
    print("NOT RUN, NOT ARMED: " + not_run)
    sys.exit(77)
sys.exit(1 if failures else 0)
