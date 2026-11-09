#!/usr/bin/env python3
"""rename.py: replace the provisional name `fwx` and the work folder `.fwx/` for the day the definitive name is chosen.

rename-script: keep-provisional-name
(That line makes this script, and any file carrying it, leave itself alone: it names the provisional name on purpose.)

    python3 scripts/rename.py --name NEW --dir NEW_FOLDER [--apply | --check] PATH...

Each PATH is one of: a git repo root (its tracked files are walked), a folder that is not a repo (every file
under it, `.git` left out) or a single file. Contents: `.fwx` used as a path becomes `.NEW_FOLDER`; the token
`fwx` becomes NEW, `FWX` becomes NEW in capitals and `Fwx` NEW with a capital initial. A token is not
surrounded by a letter or a digit, so `fwx@fwx`, `<!-- fwx:evidence -->`, `lib/fwx/`, `FWX_TIMING` change and
`fwxprobe` does not. Paths: files and folders whose name carries the token are renamed (`git mv` inside a repo,
a plain rename elsewhere); the PATH's own name is not, and neither is anything above it. Binary files and
symlinks have no contents changed, and are counted. A file that carries the marker line above is kept whole.

By default nothing is written: every file with its occurrences, every `old -> new` path and the totals are
printed. `--apply` writes, then counts again; `--check` only counts. Both exit 1 when an occurrence is left.
A rename that would land on a file or merge into a folder that exists is refused (exit 2) before anything is written.
NEW is `^[a-z][a-z0-9]*$` (a Python package and a command); NEW_FOLDER is `^[a-z][a-z0-9-]*$`, with or without
its leading dot.
"""
import argparse
import os
import re
import subprocess
import sys

OLD = "fwx"
KEEP_MARKER = "rename-script: keep-provisional-name"
# a dotted `.fwx` (a work folder) or the bare token, not touching a letter or a digit
TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:\.(fwx)|(fwx|FWX|Fwx))(?![A-Za-z0-9])")
NAME_RE = re.compile(r"[a-z][a-z0-9]*\Z")
FOLDER_RE = re.compile(r"[a-z][a-z0-9-]*\Z")
NOT_DONE = (
    "not done by this script:",
    "  - move the folder the repo lives in to its new name",
    "  - rename the GitHub repo",
    "  - run `forge sync --apply --all`: it regenerates the files of every project (the old .claude/fwx.json goes",
    "    away by forge's claim, because the name comes from the marketplace.json)",
)


def git_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


class Rule:
    def __init__(self, name, folder):
        self.name, self.folder = name, folder

    def _sub(self, m):
        if m.group(1):
            return "." + self.folder
        word = m.group(2)
        return self.name if word == "fwx" else self.name.upper() if word == "FWX" else self.name.capitalize()

    def text(self, s):
        return TOKEN.sub(self._sub, s)

    def path(self, rel):
        """A relative path with the token replaced in each component (never across a slash)."""
        return "/".join(self.text(c) for c in rel.split("/"))


def count(s):
    return sum(1 for _ in TOKEN.finditer(s))


class Target:
    """One PATH: `base` is the folder the relative names hang from, `files` the names to look at."""

    def __init__(self, arg):
        self.arg = arg
        real = os.path.realpath(arg)
        if os.path.isfile(real) and not os.path.isdir(real):
            self.kind, self.base, self.files = "file", os.path.dirname(real), [os.path.basename(arg.rstrip("/"))]
        elif os.path.isdir(real):
            top = subprocess.run(["git", "-C", real, "rev-parse", "--show-toplevel"], env=git_env(),
                                 capture_output=True, text=True)
            self.base = real
            if top.returncode == 0 and os.path.realpath(top.stdout.strip()) == real:
                self.kind = "git repo"
                out = subprocess.run(["git", "-C", real, "ls-files", "-z"], env=git_env(),
                                     capture_output=True, text=True, check=True).stdout
                self.files = sorted(f for f in out.split("\0") if f)
            else:
                self.kind = "folder"
                self.files = self.walk(real)
        else:
            raise ValueError("no such file or folder: %s" % arg)

    @staticmethod
    def walk(base):
        found = []
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if d != ".git"]
            found += [os.path.relpath(os.path.join(dp, n), base).replace(os.sep, "/") for n in fns]
        return sorted(found)

    def refresh(self, rule):
        if self.kind == "git repo":
            out = subprocess.run(["git", "-C", self.base, "ls-files", "-z"], env=git_env(),
                                 capture_output=True, text=True, check=True).stdout
            self.files = sorted(f for f in out.split("\0") if f)
        elif self.kind == "folder":
            self.files = self.walk(self.base)
        else:  # a loose file may have been renamed
            self.files = [f for f in (self.files[0], rule.path(self.files[0])) if os.path.lexists(self.abs(f))][-1:]

    def abs(self, rel):
        return os.path.join(self.base, rel)


class Item:
    def __init__(self, rel):
        self.rel = rel
        self.kind = "text"       # text | binary | symlink | kept
        self.occurrences = 0
        self.new_text = None     # bytes to write, None when the contents stay
        self.new_rel = rel


def scan(target, rule):
    """Read every file once: what it holds, what it would become, where it would move."""
    items = []
    for rel in target.files:
        if not os.path.lexists(target.abs(rel)):  # tracked but deleted in the work tree
            continue
        it = Item(rel)
        p = target.abs(rel)
        if os.path.islink(p):
            it.kind = "symlink"
        else:
            with open(p, "rb") as f:
                data = f.read()
            try:
                if b"\0" in data[:8192]:
                    raise UnicodeDecodeError("utf-8", b"", 0, 1, "NUL")
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                it.kind = "binary"
            else:
                if KEEP_MARKER in text:
                    it.kind = "kept"
                else:
                    it.occurrences = count(text)
                    if it.occurrences:
                        it.new_text = rule.text(text).encode("utf-8")
        if it.kind != "kept":
            it.new_rel = rule.path(rel)
        items.append(it)
    return items


def conflicts(target, items):
    """Where a rename would land on something that exists: a file, or a folder it would merge into.
    A new path never carries the token (NEW and NEW_FOLDER are checked), so two renames cannot meet."""
    bad = []
    for old, new in sorted(dir_moves(items).items()):
        if os.path.lexists(target.abs(new)):
            bad.append("%s -> %s: folder %s exists" % (old, new, new))
    for it in items:
        if it.new_rel != it.rel and os.path.lexists(target.abs(it.new_rel)):
            bad.append("%s -> %s: %s exists" % (it.rel, it.new_rel, it.new_rel))
    return bad


def dir_moves(items):
    """{old folder: new folder} for each folder whose own name changes."""
    moves = {}
    for it in items:
        old, new = it.rel.split("/"), it.new_rel.split("/")
        for i in range(len(old) - 1):
            if old[i] != new[i]:
                moves["/".join(old[:i + 1])] = "/".join(new[:i + 1])
    return moves


def move(target, it):
    src, dst = target.abs(it.rel), target.abs(it.new_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if target.kind == "git repo":
        subprocess.run(["git", "-C", target.base, "mv", "--", it.rel, it.new_rel], env=git_env(),
                       capture_output=True, text=True, check=True)
    else:
        os.rename(src, dst)
    parent = os.path.dirname(src)
    while parent != target.base and parent.startswith(target.base):  # the folder the file left, if now empty
        try:
            os.rmdir(parent)
        except OSError:
            break
        parent = os.path.dirname(parent)


def apply(target, items):
    for it in items:
        if it.new_text is not None:
            try:
                with open(target.abs(it.rel), "wb") as f:
                    f.write(it.new_text)
            except OSError as e:  # left as it was; the count after says so and the exit is 1
                sys.stderr.write("rename.py: cannot write %s: %s\n" % (it.rel, e.strerror))
    for it in items:
        if it.new_rel != it.rel:
            move(target, it)


def totals(items_by_target):
    files = occ = paths = binary = kept = 0
    for items in items_by_target:
        for it in items:
            if it.occurrences:
                files += 1
                occ += it.occurrences
            if it.new_rel != it.rel:
                paths += 1
            binary += it.kind in ("binary", "symlink")
            kept += it.kind == "kept"
    return files, occ, paths, binary, kept


def report(target, items, out):
    out.write("%s (%s)\n" % (target.arg, target.kind))
    for it in items:
        if it.occurrences:
            out.write("  %s: %d occurrence(s)\n" % (it.rel, it.occurrences))
    for old, new in sorted(dir_moves(items).items()):
        out.write("  rename dir %s -> %s\n" % (old, new))
    for it in items:
        if it.new_rel != it.rel and it.rel.rsplit("/", 1)[-1] != it.new_rel.rsplit("/", 1)[-1]:
            out.write("  rename %s -> %s\n" % (it.rel, it.new_rel))
    for it in items:
        if it.kind == "kept":
            out.write("  kept (marker): %s\n" % it.rel)
        elif it.kind in ("binary", "symlink"):
            out.write("  skipped (%s): %s\n" % (it.kind, it.rel))


def parse(argv):
    ap = argparse.ArgumentParser(prog="rename.py", description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True, help="new name, ^[a-z][a-z0-9]*$")
    ap.add_argument("--dir", required=True, help="new work folder name, ^[a-z][a-z0-9-]*$, with or without the dot")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write (default: dry run)")
    mode.add_argument("--check", action="store_true", help="only count; exit 1 if any occurrence is left")
    ap.add_argument("paths", nargs="+", metavar="PATH", help="a repo root, a folder or a file")
    return ap.parse_args(argv)


def main(argv):
    a = parse(argv)
    folder = a.dir[1:] if a.dir.startswith(".") else a.dir
    problems = []
    if not NAME_RE.match(a.name):
        problems.append("--name %r: must match ^[a-z][a-z0-9]*$" % a.name)
    elif a.name == OLD:
        problems.append("--name %r is the provisional name itself" % a.name)
    if not FOLDER_RE.match(folder):
        problems.append("--dir %r: must match ^[a-z][a-z0-9-]*$ (a leading dot is allowed)" % a.dir)
    elif TOKEN.search(folder):
        problems.append("--dir %r still holds the provisional name as a token" % a.dir)
    targets = []
    if not problems:
        for p in a.paths:
            try:
                targets.append(Target(p))
            except ValueError as e:
                problems.append(str(e))
            except subprocess.CalledProcessError as e:
                problems.append("git failed in %s: %s" % (p, (e.stderr or "").strip()))
    if problems:
        for p in problems:
            sys.stderr.write("rename.py: %s\n" % p)
        return 2
    rule = Rule(a.name, folder)
    scanned = [scan(t, rule) for t in targets]
    bad = [c for t, items in zip(targets, scanned) for c in conflicts(t, items)]
    if bad:
        for c in bad:
            sys.stderr.write("rename.py: conflict: %s\n" % c)
        sys.stderr.write("rename.py: nothing was written\n")
        return 2
    mode = "apply" if a.apply else "check" if a.check else "dry run, nothing written"
    sys.stdout.write("%s -> %s, .%s/ -> .%s/ (%s)\n" % (OLD, a.name, OLD, folder, mode))
    for t, items in zip(targets, scanned):
        report(t, items, sys.stdout)
    sys.stdout.write("total: %d file(s) with %d occurrence(s), %d path(s) to rename, %d binary skipped, %d kept\n"
                     % totals(scanned))
    left = 0
    if a.apply:
        for t, items in zip(targets, scanned):
            apply(t, items)
        after = []
        for t in targets:
            t.refresh(rule)
            after.append(scan(t, rule))
        _, occ, paths, _, _ = totals(after)
        left = occ + paths
        sys.stdout.write("after: %d occurrence(s) and %d path(s) left\n" % (occ, paths))
        for t, items in zip(targets, after):
            for it in items:
                if it.occurrences or it.new_rel != it.rel:
                    sys.stdout.write("  left in %s: %s\n" % (t.arg, it.rel))
    elif a.check:
        _, occ, paths, _, _ = totals(scanned)
        left = occ + paths
    if not a.check:
        sys.stdout.write("\n" + "\n".join(NOT_DONE) + "\n")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
