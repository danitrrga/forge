"""scripts/rename.py: replaces the provisional name and work folder everywhere, on token boundaries,
in contents and in paths, and writes nothing without --apply.

rename-script: keep-provisional-name
(That line makes scripts/rename.py leave this file alone: it names the provisional name on purpose.)

The world is a toy repo with one file of every shape (a package folder, a command, the work folder, `fwx@fwx`,
a config file, FWX_TIMING, an HTML marker comment, `fwxprobe`, CRLF, a binary, a kept file) and, beside it, a
toy forge configuration folder that is not a repo. `scenario()` runs the whole story against a given script, so
a copy of the script with one line broken is run through the same checks: each control below must go red.

Seen red before scripts/rename.py existed (python3: can't open file '.../scripts/rename.py': [Errno 2]; 70 of the
checks failed, among them):
  FAIL: before: --check exits 1: got 2, want 1
  FAIL: before: totals: got '', want 'total: 10 file(s) with 23 occurrence(s), 9 path(s) to rename, 2 binary skipped, 1 kept'
  FAIL: apply: exit 0: got 2, want 0
  FAIL: after: --check exits 0: got 2, want 0

Controls, each a copy of rename.py with one line broken, seen red on the check named (the scenario is run again on
the copy; the control passes only when that check fails):
  contents only, no path is moved:   FAIL: apply: exit 0: got 1, want 0   (the recount finds lib/fwx; the plan's control)
  paths are not even looked at:      FAIL: dry run: totals: got '... 0 path(s) to rename ...'
  plain replace, no token limits:    FAIL: after: content of docs/boundaries.txt: got b'forjaxprobe aforjax forjax2 ...'
  the dry run writes:                FAIL: dry run: the tree is byte-identical
  --check always exits 0:            FAIL: before: --check exits 1: got 0, want 1
  capitals are not mapped:           FAIL: after: content of README.md: got b'... forjax_TIMING Forjax uses fwxprobe.'
  NUL is not a binary mark:          FAIL: after: binary assets/forjax-logo.bin is untouched ...: got b'\x00forjax\x00'
  non-UTF-8 decoded anyway:          FAIL: after: binary assets/forjax-latin.dat is untouched ...: got b'forjax \xef\xbf\xbd ...'
  the marker is ignored:             FAIL: after: the kept file is untouched
  rename onto an existing file:      FAIL: conflict: exit 2: got 1, want 2
  rename into an existing folder:    FAIL: conflict (folder to merge into): exit 2: got 0, want 2
  no git mv in a repo:               FAIL: after: git mv staged the renames (no untracked file):  D .claude/fwx.json ...
  the recount after --apply gone:    FAIL: read-only file: apply exits 1: got 0, want 1
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

SCRIPT = os.path.join(helpers.ROOT, "scripts", "rename.py")
NAME, FOLDER = "forjax", ".forjax"
TOTAL = "total: %d file(s) with %d occurrence(s), %d path(s) to rename, %d binary skipped, %d kept"

TEXT = {
    "lib/fwx/__init__.py": '"""fwx package."""\nimport fwx.commands\nPREFIX = "FWX_TIMING"\n',
    "lib/fwx/commands/__init__.py": "",
    "bin/fwx": '#!/usr/bin/env python3\nprint("fwx", "Fwx")\n',
    ".fwx/PROJECT.md": "# fwx project\nWork folder .fwx/ of fwx.\n",
    ".fwx/notes/fwx-notes.md": "see fwx\n",
    "README.md": "fwx@fwx\n<!-- fwx:evidence -->\nFWX_TIMING Fwx uses fwxprobe.\n",
    ".claude/fwx.json": '{"schema": 1, "dir": ".fwx/"}\n',
    "docs/boundaries.txt": "fwxprobe afwx fwx2 xfwx.json\n(fwx) x.fwx .fwx/ _fwx\n",
    "docs/crlf.txt": "fwx\r\nFWX\r\n",
    "scripts/kept.py": "# rename-script: keep-provisional-name\nNAME = 'fwx'\n",
}
BINARY = {"assets/fwx-logo.bin": b"\x00fwx\x00", "assets/fwx-latin.dat": b"fwx \xe9\xff fwx"}
FORGE = {
    "config/forge.json": '{"framework": {"plugin_source": {"path": "~/projects/fwx"}}}\n',
    "config/profiles/fwx.claude.json": '{"name": "fwx", "framework": true}\n',
}
# what each text file must read after the rename
AFTER = {
    "lib/forjax/__init__.py": '"""forjax package."""\nimport forjax.commands\nPREFIX = "FORJAX_TIMING"\n',
    "lib/forjax/commands/__init__.py": "",
    "bin/forjax": '#!/usr/bin/env python3\nprint("forjax", "Forjax")\n',
    ".forjax/PROJECT.md": "# forjax project\nWork folder .forjax/ of forjax.\n",
    ".forjax/notes/forjax-notes.md": "see forjax\n",
    "README.md": "forjax@forjax\n<!-- forjax:evidence -->\nFORJAX_TIMING Forjax uses fwxprobe.\n",
    ".claude/forjax.json": '{"schema": 1, "dir": ".forjax/"}\n',
    "docs/boundaries.txt": "fwxprobe afwx fwx2 xfwx.json\n(forjax) x.forjax .forjax/ _forjax\n",
    "docs/crlf.txt": "forjax\r\nFORJAX\r\n",
    "scripts/kept.py": TEXT["scripts/kept.py"],
}


def run(script, *args):
    return subprocess.run([sys.executable, script] + list(args), cwd=tempfile.gettempdir(),
                          env=helpers.clean_env(), capture_output=True, text=True)


def snapshot(root):
    """Every file (bytes and mode) and every folder under root, .git left out: what 'unchanged' means."""
    snap = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".git"]
        for n in dns:
            snap[os.path.relpath(os.path.join(dp, n), root) + "/"] = None
        for n in fns:
            p = os.path.join(dp, n)
            with open(p, "rb") as f:
                snap[os.path.relpath(p, root)] = (f.read(), os.stat(p).st_mode)
    return snap


def read(root, rel):
    try:
        with open(os.path.join(root, rel), "rb") as f:
            return f.read()
    except OSError:
        return None


def total_line(out):
    lines = [l for l in out.splitlines() if l.startswith("total:")]
    return lines[-1] if lines else ""


def world():
    """(toy repo, toy forge configuration folder)."""
    repo = helpers.toy_repo(TEXT)
    for rel, data in BINARY.items():
        os.makedirs(os.path.dirname(os.path.join(repo, rel)), exist_ok=True)
        with open(os.path.join(repo, rel), "wb") as f:
            f.write(data)
    os.chmod(os.path.join(repo, "bin", "fwx"), 0o755)
    helpers.git(repo, "add", "-A")
    helpers.git(repo, "commit", "-q", "-m", "more")
    forge = helpers.mkdtemp("fwx-forge-")
    for rel, text in FORGE.items():
        helpers.write(forge, rel, text)
    return repo, forge


def status(repo):
    return helpers.git(repo, "status", "--porcelain")


def scenario(script, s):
    repo, forge = world()
    args = ["--name", NAME, "--dir", FOLDER]
    before = (snapshot(repo), snapshot(forge))
    want_before = TOTAL % (10, 23, 9, 2, 1)

    # the count before: more than 0, exit 1 (an occurrence is left), nothing written
    r = run(script, *args, "--check", repo, forge)
    s.eq("before: --check exits 1", r.returncode, 1)
    s.eq("before: totals", total_line(r.stdout), want_before)
    s.ok("before: the count is more than 0", "0 occurrence(s)" not in total_line(r.stdout), r.stdout)
    s.ok("before: --check writes nothing", (snapshot(repo), snapshot(forge)) == before)

    # the dry run, the default: lists and totals, byte-identical tree
    r = run(script, *args, repo, forge)
    s.eq("dry run: exit 0", r.returncode, 0)
    s.ok("dry run: the tree is byte-identical", (snapshot(repo), snapshot(forge)) == before)
    s.eq("dry run: git status is clean", status(repo), "")
    s.eq("dry run: totals", total_line(r.stdout), want_before)
    for line in ("rename bin/fwx -> bin/forjax", "rename dir lib/fwx -> lib/forjax",
                 "rename dir .fwx -> .forjax", "rename config/profiles/fwx.claude.json -> config/profiles/forjax.claude.json",
                 "README.md: 5 occurrence(s)", "kept (marker): scripts/kept.py", "skipped (binary): assets/fwx-logo.bin", "skipped (binary): assets/fwx-latin.dat"):
        s.ok("dry run: prints %r" % line, line in r.stdout, r.stdout)
    for line in ("not done by this script", "move the folder", "rename the GitHub repo", "forge sync --apply --all"):
        s.ok("dry run: says what it does not do (%s)" % line, line in r.stdout, r.stdout[-400:])

    # --apply
    r = run(script, *args, "--apply", repo, forge)
    s.eq("apply: exit 0", r.returncode, 0)
    s.ok("apply: counts again and finds nothing left", "after: 0 occurrence(s) and 0 path(s) left" in r.stdout, r.stdout[-300:])
    r = run(script, *args, "--check", repo, forge)
    s.eq("after: --check exits 0", r.returncode, 0)
    s.eq("after: totals", total_line(r.stdout), TOTAL % (0, 0, 0, 2, 1))
    for rel, text in AFTER.items():
        s.eq("after: content of " + rel, read(repo, rel), text.encode())
    s.eq("after: binary assets/forjax-logo.bin is untouched (NUL byte), its path is renamed",
         read(repo, "assets/forjax-logo.bin"), BINARY["assets/fwx-logo.bin"])
    s.eq("after: binary assets/forjax-latin.dat is untouched (not UTF-8), its path is renamed",
         read(repo, "assets/forjax-latin.dat"), BINARY["assets/fwx-latin.dat"])
    s.eq("after: the kept file is untouched", read(repo, "scripts/kept.py"), TEXT["scripts/kept.py"].encode())
    tracked = set(helpers.git(repo, "ls-files").split())
    s.eq("after: tracked files", tracked, set(AFTER) | {"assets/forjax-logo.bin", "assets/forjax-latin.dat"})
    s.ok("after: the old folders are gone", not os.path.exists(os.path.join(repo, "lib", "fwx"))
         and not os.path.exists(os.path.join(repo, ".fwx")))
    s.ok("after: the executable bit survives", os.access(os.path.join(repo, "bin", "forjax"), os.X_OK))
    s.ok("after: git mv staged the renames (no untracked file)", "??" not in status(repo), status(repo))
    s.eq("after: forge.json", read(forge, "config/forge.json"),
         b'{"framework": {"plugin_source": {"path": "~/projects/forjax"}}}\n')
    s.eq("after: the profile moved and changed", read(forge, "config/profiles/forjax.claude.json"),
         b'{"name": "forjax", "framework": true}\n')
    s.eq("after: the old profile is gone", read(forge, "config/profiles/fwx.claude.json"), None)

    # a second --apply does nothing
    again = (snapshot(repo), snapshot(forge))
    r = run(script, *args, "--apply", repo, forge)
    s.eq("second apply: exit 0", r.returncode, 0)
    s.ok("second apply: nothing changes", (snapshot(repo), snapshot(forge)) == again)

    # --dir without the dot is the same folder; a loose file is renamed too
    loose = helpers.mkdtemp("fwx-loose-")
    helpers.write(loose, "fwx.claude.json", '{"name": "fwx"}\n')
    r = run(script, "--name", NAME, "--dir", "forjax", "--apply", os.path.join(loose, "fwx.claude.json"))
    s.eq("loose file: exit 0", r.returncode, 0)
    s.eq("loose file: renamed and rewritten", read(loose, "forjax.claude.json"), b'{"name": "forjax"}\n')
    s.eq("loose file: the old one is gone", read(loose, "fwx.claude.json"), None)

    # a file that cannot be written is said so, stays as it was, and the exit is 1
    if os.geteuid() == 0:
        print("read-only file: skipped, running as root writes anywhere")
    else:
        ro = helpers.toy_repo({"a.txt": "fwx\n", "b.txt": "fwx\n"})
        os.chmod(os.path.join(ro, "a.txt"), 0o444)
        r = run(script, *args, "--apply", ro)
        s.eq("read-only file: apply exits 1", r.returncode, 1)
        s.ok("read-only file: says it cannot write", "cannot write a.txt" in r.stderr, r.stderr)
        s.ok("read-only file: still counted as left", "after: 1 occurrence(s) and 0 path(s) left" in r.stdout, r.stdout[-200:])
        s.eq("read-only file: unchanged", read(ro, "a.txt"), b"fwx\n")
        s.eq("read-only file: the other one is done", read(ro, "b.txt"), b"forjax\n")

    # names that are refused: exit 2 and nothing written
    bad_repo, _ = world()
    bad_before = snapshot(bad_repo)
    for label, bad in (("uppercase name", ["--name", "Forjax", "--dir", ".forjax"]),
                       ("hyphen in name", ["--name", "for-jax", "--dir", ".forjax"]),
                       ("name starting with a digit", ["--name", "1x", "--dir", ".forjax"]),
                       ("empty name", ["--name", "", "--dir", ".forjax"]),
                       ("the provisional name as the name", ["--name", "fwx", "--dir", ".forjax"]),
                       ("uppercase folder", ["--name", "forjax", "--dir", "Forjax"]),
                       ("folder starting with a hyphen", ["--name", "forjax", "--dir=-x"]),
                       ("empty folder", ["--name", "forjax", "--dir", ""]),
                       ("folder that still holds the token", ["--name", "forjax", "--dir", ".x-fwx"]),
                       ("no --dir", ["--name", "forjax"]),
                       ("--apply with --check", ["--name", "forjax", "--dir", ".forjax", "--apply", "--check"])):
        r = run(script, *bad, bad_repo)
        s.eq("refused (%s): exit 2" % label, r.returncode, 2)
        s.ok("refused (%s): says why on stderr" % label, bool(r.stderr.strip()), "stderr was empty")
        s.ok("refused (%s): writes nothing" % label, snapshot(bad_repo) == bad_before)
    r = run(script, *args)
    s.eq("no path: exit 2", r.returncode, 2)
    r = run(script, *args, "--apply", os.path.join(bad_repo, "no-such-path"))
    s.eq("missing path: exit 2", r.returncode, 2)
    s.ok("missing path: writes nothing", snapshot(bad_repo) == bad_before)

    # a rename that would land on an existing file is refused before anything is written, even with --apply
    clash = helpers.toy_repo({"bin/fwx": "fwx\n", "bin/forjax": "other\n", "README.md": "fwx\n"})
    clash_before = snapshot(clash)
    r = run(script, *args, "--apply", clash)
    s.eq("conflict: exit 2", r.returncode, 2)
    s.ok("conflict: names the file in the way", "bin/forjax" in r.stderr, r.stderr)
    s.ok("conflict: not even the contents are written", snapshot(clash) == clash_before)
    merge = helpers.toy_repo({"lib/fwx/a.py": "fwx\n", "lib/forjax/b.py": "other\n"})
    merge_before = snapshot(merge)
    r = run(script, *args, "--apply", merge)
    s.eq("conflict (folder to merge into): exit 2", r.returncode, 2)
    s.ok("conflict (folder to merge into): names the folder", "lib/forjax" in r.stderr, r.stderr)
    s.ok("conflict (folder to merge into): nothing is written", snapshot(merge) == merge_before)


def real_copy(script, s):
    """A copy of this very repo, renamed: the renamed package imports and the dispatcher runs."""
    root = helpers.ROOT
    if not (os.path.isfile(os.path.join(root, "bin", "fwx")) and os.path.isdir(os.path.join(root, "lib", "fwx"))):
        print("real copy: skipped, this repo no longer carries the provisional name")
        return
    files = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           env=helpers.clean_env(), capture_output=True, text=True, check=True).stdout.split("\0")
    copy = helpers.mkdtemp("fwx-real-")
    helpers.git(copy, "init", "-q", "-b", "master")
    n = 0
    for rel in files:
        if rel and os.path.isfile(os.path.join(root, rel)):
            os.makedirs(os.path.dirname(os.path.join(copy, rel)) or copy, exist_ok=True)
            shutil.copy2(os.path.join(root, rel), os.path.join(copy, rel))
            n += 1
    s.ok("real copy: copied the repo's files (%d)" % n, n > 10)
    helpers.git(copy, "add", "-A")
    helpers.git(copy, "commit", "-q", "-m", "copy")
    r = run(script, "--name", NAME, "--dir", FOLDER, "--apply", copy)
    s.eq("real copy: --apply exit 0", r.returncode, 0)
    r = run(script, "--name", NAME, "--dir", FOLDER, "--check", copy)
    s.eq("real copy: --check exit 0", r.returncode, 0)
    r = subprocess.run([sys.executable, os.path.join(copy, "bin", "forjax"), "help"], cwd=copy,
                       env=helpers.clean_env(), capture_output=True, text=True)
    s.eq("real copy: bin/forjax help exits 0", r.returncode, 0)
    s.ok("real copy: help is in the new name", r.stdout.startswith("usage: forjax"), r.stdout[:80])
    r = subprocess.run([sys.executable, "-c", "import forjax.commands.rounds as t; print(t.main.__name__)"],
                       cwd=copy, env=helpers.clean_env(PYTHONPATH=os.path.join(copy, "lib")),
                       capture_output=True, text=True)
    s.ok("real copy: the renamed package imports", r.returncode == 0 and r.stdout.strip() == "main", r.stderr[-300:])
    s.ok("real copy: lib/fwx is gone", not os.path.exists(os.path.join(copy, "lib", "fwx")))


# each control: (label, the line of rename.py to break, what it becomes, a check that must then FAIL)
CONTROLS = [
    ("contents only, no path is moved", "        if it.new_rel != it.rel:\n            move(target, it)",
     "        if False:\n            move(target, it)", "apply: exit 0"),
    ("paths are not even looked at", "it.new_rel = rule.path(rel)", "it.new_rel = rel", "dry run: totals"),
    ("no token boundaries (plain replace)",
     'TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:\\.(fwx)|(fwx|FWX|Fwx))(?![A-Za-z0-9])")',
     'TOKEN = re.compile(r"(?:\\.(fwx)|(fwx|FWX|Fwx))")', "after: content of docs/boundaries.txt"),
    ("the dry run writes", "    if a.apply:\n        for t, items", "    if a.apply or not a.check:\n        for t, items",
     "dry run: the tree is byte-identical"),
    ("--check always exits 0", "return 1 if left else 0", "return 0", "before: --check exits 1"),
    ("capitals are not mapped", 'self.name.upper() if word == "FWX"', 'self.name if word == "FWX"',
     "after: content of README.md"),
    ("NUL bytes are not a binary mark", 'if b"\\0" in data[:8192]:', "if False:", "forjax-logo.bin is untouched"),
    ("a non-UTF-8 file is decoded anyway", 'text = data.decode("utf-8")', 'text = data.decode("utf-8", "replace")',
     "forjax-latin.dat is untouched"),
    ("the marker is ignored", "if KEEP_MARKER in text:", "if False:", "after: the kept file is untouched"),
    ("a rename onto an existing file is allowed", "if it.new_rel != it.rel and os.path.lexists(target.abs(it.new_rel)):",
     "if False:", "conflict: exit 2"),
    ("a rename into an existing folder is allowed", "if os.path.lexists(target.abs(new)):", "if False:",
     "conflict (folder to merge into): exit 2"),
    ("a repo is renamed without git mv", 'if target.kind == "git repo":\n        subprocess.run(["git", "-C", target.base, "mv"',
     'if False:\n        subprocess.run(["git", "-C", target.base, "mv"', "after: git mv staged the renames"),
    ("the count after the write is skipped", "after.append(scan(t, rule))", "after.append([])", "read-only file: apply exits 1"),
]


s = helpers.Suite()
if not os.path.isfile(SCRIPT):
    print("scripts/rename.py does not exist yet")
scenario(SCRIPT, s)
real_copy(SCRIPT, s)

for label, old, new, red in CONTROLS:
    try:
        with open(SCRIPT, encoding="utf-8") as f:
            src = f.read()
    except OSError:
        src = ""
    s.ok("control %s: the line to break exists in rename.py" % label, old in src, old)
    d = helpers.mkdtemp("fwx-mut-")
    mutant = os.path.join(d, "rename.py")
    with open(mutant, "w", encoding="utf-8") as f:
        f.write(src.replace(old, new, 1))
    ms = helpers.Suite()
    try:
        scenario(mutant, ms)
    except Exception as e:  # a mutant may crash the scenario: that is red too
        ms.fails.append("FAIL: crashed: %r" % e)
    s.ok("control %s: goes red on %r" % (label, red), any(red in f for f in ms.fails),
         "failures were: %s" % "; ".join(f[:160] for f in ms.fails[:4]))

s.done()
