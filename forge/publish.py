"""Keeping personal data out of the public history, and committing to the right one.

`forge check-public` scans text for what must not be published. Four sources, one per
git moment: the staged files (pre-commit), a commit message file (commit-msg), a range of
commits (pre-push) and the whole engine tree (CI, the merge gate).

Two lists run together:
  * the public list, below: home paths, email addresses, private IPv4 ranges, tailnet host
    names, private-key headers, files over 1 MiB, font and image files (except the few in
    PUBLIC_ASSETS, pinned by path and sha256). It is in this file, so a stranger's checkout has it;
  * the private list, config/publish-deny.txt: one regular expression per line, names and
    addresses the owner of the checkout forbids. It is data and may be missing; a list that
    is there but holds no pattern, or an invalid one, is an error (exit 2), never a pass.

`forge commit` puts each changed path in the history that owns it, when the checkout has two:
the engine history (what the engine's .gitignore does not ignore) and the data history in
.forge-data.git (everything else, same work tree). With one history it is `git add` plus
`git commit`.

Exit codes: 0 clean, 1 hits (or nothing checked by --all), 2 the check could not run.
"""
import hashlib
import ipaddress
import os
import re
import subprocess
import sys

from forge import lib

DENY = os.path.join("config", "publish-deny.txt")
ALLOWLIST = os.path.join("publish", "engine.gitignore")
DATA_GIT = ".forge-data.git"
MAX_BYTES = 1024 * 1024
ASSET_EXT = {".woff", ".woff2", ".ttf", ".otf", ".eot", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
             ".bmp", ".tif", ".tiff", ".avif", ".heic", ".svg"}
# The image files a person has looked at and found free of personal data, by repo-relative path and the
# sha256 of the bytes looked at. Only the extension rule is waived, and only for those exact bytes at that
# path: a changed byte fails again until someone looks again, and an SVG is still read line by line.
PUBLIC_ASSETS = {
    "docs/assets/banner.png": "2d41030c0b4da782a446eaca1a27056bb9222b89e3f829658376fe3a52c0c998",
    "docs/assets/banner-dark.png": "a8cb60d242cfeb49af95f186003dfb01a38d5e0a0b5551fc54d25444a2ca5f25",
    "docs/assets/social-preview.png": "212dc7ba8d3fc16fa4a69d03d7d5697fd6ef96211fbdcc2773345cb54e72a8b8",
    "docs/assets/fig-sync.png": "536d54b574de739727b78a7a9aa7b90d6d49db1876f2441517c5b7d688902011",
    "docs/assets/fig-sync-dark.png": "d8ed2a47fb7e32b87ba1abe436c6bd5b37143a64d1f9b5d1a0509d6d649d359a",
    "docs/assets/fig-trim.png": "68f616e2abdd1991087faf4548182fc122635234e06a80cc0d35b2a1461cff0a",
    "docs/assets/fig-trim-dark.png": "795a8e6dde77b7efc6dccf338a8f0aded697b47a4f6068163d390fa7f0d8bf76",
    "docs/assets/fig-bench.png": "9c4dfecd2307dfd37f2bd87f08fef07368f5cc9f2c58b23ad520853d239a93e5",
    "docs/assets/fig-bench-dark.png": "0c6552f887efd95af7b32aaa976ee805337eef27c9d1dc271a053fa51da0bee5",
}
# Where dates are data (a skill-bench task's calendar, its leap day), not the record of a decision: in these files a
# private pattern that matches a bare ISO date is not applied. Every other private pattern still is.
DATED_DATA = ("benchmarks/skill-bench/tasks/",)
SAMPLE_DATE = "-".join(("2000", "01", "31"))  # joined, so this line holds no date
# The one home name that is documentation, not a person.
HOME_OK = {"user"}
# example.com and example.org are IANA documentation names (RFC 2606); example.test sits under the .test TLD that RFC 6761 reserves
# for tests and documentation. None of them can be a real address, which is why fixtures use them.
EMAIL_OK = ("example.com", "example.org", "example.test")
# The two public no-reply addresses, matched whole and nothing wider: the commit trailer's address and a
# GitHub no-reply `<digits>+<name>@`. Any other name at those hosts is an address like any other.
EMAIL_PUBLIC_RE = re.compile(r"noreply@anthropic\.com|[0-9]{1,20}\+[A-Za-z0-9-]{1,39}@users\.noreply\.github\.com",
                             re.IGNORECASE)
# 10/8, 172.16/12, 192.168/16 and 100.64/10, as (address, prefix length): this file is scanned
# too, and a dotted literal here would be a hit.
PRIVATE_NETS = [ipaddress.IPv4Network(n) for n in ((10 << 24, 8), ((172 << 24) | (16 << 16), 12),
                                                    ((192 << 24) | (168 << 16), 16), ((100 << 24) | (64 << 16), 10))]
# Every quantifier that can meet a long line is bounded: a minified file is one line of megabytes.
# A user name starts with a letter, a digit or an underscore: `/home/.claude` is a toy path, not a person.
HOME_RE = re.compile(r"/(?:home|Users)/([A-Za-z0-9_][A-Za-z0-9._-]{0,63})")
# The local part must hold a letter or digit: a bare "-" (a diff marker) before @functools.lru_cache is a decorator, not an address.
EMAIL_RE = re.compile(r"(?=[A-Za-z0-9._%+-]{0,63}[A-Za-z0-9])[A-Za-z0-9._%+-]{1,64}@([A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,24})")
IPV4_RE = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w]|\.\d)")
TAILNET_RE = re.compile(r"[A-Za-z0-9.-]{0,253}\.ts\.net(?![A-Za-z0-9-])")
KEY_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
# Exact technical tokens the private list does not apply to: one string a file format requires, with the
# reason. The token is taken out of the line, case-sensitively and only where it stands alone (not inside a
# longer word or name), before the private list runs; the same word anywhere else is still a hit, and the
# public list never sees this. Not a place for a name or a date: those are renamed or removed.
PRIVATE_ALLOW = {
    "LIFEOS-SYSTEM-POINTER": "the begin and end marker written into every managed CLAUDE.md; "
                             "renaming it rewrites every project's file",
}
ALLOW_RE = re.compile("(?<![\\w-])(?:%s)(?![\\w-])" % "|".join(re.escape(t) for t in PRIVATE_ALLOW))


class CheckError(Exception):
    """The check could not run: the caller exits 2, so a broken check is never a pass."""


def public_hits(line):
    """[(rule, matched text)] for one line, by the public list."""
    out = []
    if "/home/" in line or "/Users/" in line:
        for m in HOME_RE.finditer(line):
            if m.group(1) not in HOME_OK:
                out.append(("home path", m.group(0)))
    if "@" in line:
        for m in EMAIL_RE.finditer(line):
            d = m.group(1).lower()
            if not EMAIL_PUBLIC_RE.fullmatch(m.group(0)) and not any(d == ok or d.endswith("." + ok) for ok in EMAIL_OK):
                out.append(("email", m.group(0)))
    if "." in line:
        for m in IPV4_RE.finditer(line):
            try:
                ip = ipaddress.ip_address(m.group(0))
            except ValueError:
                continue
            if any(ip in net for net in PRIVATE_NETS):
                out.append(("private ip", m.group(0)))
    if "ts.net" in line:
        for m in TAILNET_RE.finditer(line):
            out.append(("tailnet host", m.group(0)))
    if "PRIVATE KEY-----" in line:
        for m in KEY_RE.finditer(line):
            out.append(("private key", m.group(0)))
    return out


def main_checkout(root):
    """The main checkout of the repository `root` is a linked worktree of, else None."""
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    except OSError:
        return None
    common = os.path.abspath(os.path.join(root, r.stdout.strip())) if r.returncode == 0 and r.stdout.strip() else ""
    main = os.path.dirname(common)
    if os.path.basename(common) != ".git" or os.path.realpath(main) == os.path.realpath(root):
        return None
    return main


def load_deny(root):
    """The private list as [(line number, compiled pattern)], None when the file is not there. A linked
    worktree has no private files of its own, so it reads the main checkout's."""
    p = os.path.join(root, DENY)
    if not os.path.exists(p):
        main = main_checkout(root)
        p = os.path.join(main, DENY) if main else p
    if not os.path.exists(p):
        return None
    pats = []
    with open(p, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                pats.append((n, re.compile(line, re.IGNORECASE)))
            except re.error as e:
                raise CheckError("%s:%d: invalid pattern %r: %s" % (DENY, n, line, e))
    if not pats:
        raise CheckError("%s has no pattern: an empty list checks nothing" % DENY)
    return pats


def scan(path, data, deny):
    """[(line or 0, rule, text)] for one file's bytes. LICENSE is exempt from the private list: it
    must name a holder. A file under DATED_DATA is exempt from its date patterns only."""
    out = []
    if os.path.splitext(path)[1].lower() in ASSET_EXT and PUBLIC_ASSETS.get(path) != hashlib.sha256(data).hexdigest():
        out.append((0, "binary asset", os.path.splitext(path)[1].lower()))
    if len(data) > MAX_BYTES:
        out.append((0, "size", "%d bytes" % len(data)))
    if b"\0" in data:
        return out
    private = None if path == "LICENSE" else deny
    if private and path.startswith(DATED_DATA):
        private = [(n, pat) for n, pat in private if not pat.search(SAMPLE_DATE)]
    for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        for rule, text in public_hits(line):
            out.append((n, rule, text))
        checked = ALLOW_RE.sub(" ", line) if private else line
        for _, pat in private or ():
            m = pat.search(checked)
            if m:  # one private hit per line is enough to name it
                out.append((n, "private list", m.group(0)))
                break
    return out


def git(args, check=True, binary=False):
    r = subprocess.run(["git", "-C", lib.ROOT] + args, capture_output=True, text=not binary)
    if check and r.returncode:
        err = r.stderr if not binary else r.stderr.decode("utf-8", "replace")
        raise CheckError("git %s: %s" % (" ".join(args[:3]), err.strip()))
    return r.stdout


def raw_entries(out):
    """[(mode, blob sha, path)] from `git diff --raw -z` or `git diff-tree --raw -z` output."""
    toks, ents, i = out.split("\0"), [], 0
    while i + 1 < len(toks):
        if toks[i].startswith(":"):
            f = toks[i][1:].split()
            if f[1] != "160000":
                ents.append((f[1], f[3], toks[i + 1]))
            i += 2
        else:
            i += 1
    return ents


def nul_list(out):
    return [p for p in out.split("\0") if p]


def engine_files():
    """The files check-public --all covers. With one history that holds everything (before the split),
    the allowlist picks the engine's; with two, the engine history tracks the engine and nothing else."""
    files = nul_list(git(["ls-files", "-c", "-z"]))
    allow = os.path.join(lib.ROOT, ALLOWLIST)
    if os.path.exists(allow) and not os.path.isdir(os.path.join(lib.ROOT, DATA_GIT)):
        out = set(nul_list(git(["ls-files", "-c", "-i", "-z", "--exclude-from=" + allow])))
        files = [f for f in files if f not in out]
    return files


def source_staged():
    return [("", p, ("blob", sha)) for _, sha, p in raw_entries(git(["diff", "--cached", "--raw", "-z", "--no-renames",
                                                                      "--diff-filter=ACMR"]))], 0


def source_all():
    items = []
    for p in engine_files():
        full = os.path.join(lib.ROOT, p)
        if os.path.islink(full):
            items.append(("", p, ("bytes", os.readlink(full).encode())))
        elif os.path.isfile(full):
            items.append(("", p, ("file", full)))
    return items, 0


def source_range(spec):
    m = re.match(r"^0+\.\.(.+)$", spec)
    args = [m.group(1), "--not", "--remotes"] if m else [spec]
    revs = git(["rev-list", "--reverse"] + args).split()
    items = []
    for c in revs:
        tag = c[:7]
        items.append((tag, "(message)", ("bytes", git(["log", "-1", "--format=%B", c], binary=True))))
        for _, sha, p in raw_entries(git(["diff-tree", "-r", "--raw", "-z", "--no-renames", "--no-commit-id", "--root",
                                          "--diff-filter=ACMR", c])):
            items.append((tag, p, ("blob", sha)))
    return items, len(revs)


def source_message(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise CheckError("cannot read the message file: %s" % e)
    # git strips the comment lines; keep their line numbers.
    lines = [b"" if l.startswith(b"#") else l for l in data.split(b"\n")]
    return [("", "(message)", ("bytes", b"\n".join(lines)))], 0


def read(src):
    kind, v = src
    if kind == "bytes":
        return v
    if kind == "file":
        with open(v, "rb") as f:
            return f.read()
    return git(["cat-file", "blob", v], binary=True)


def cmd_check_public(a):
    try:
        deny = load_deny(lib.ROOT)
        if a.staged:
            items, ncommits = source_staged()
        elif a.all:
            items, ncommits = source_all()
        elif a.message:
            items, ncommits = source_message(a.message)
        else:
            items, ncommits = source_range(a.range)
        cache, hits, bad_files = {}, [], set()
        for tag, path, src in items:
            key = (src[1], path) if src[0] == "blob" else None  # a range names one blob in many commits
            found = cache.get(key) if key else None
            if found is None:
                found = scan(path, read(src), deny)
                if key:
                    cache[key] = found
            label = (tag + ":" if tag else "") + path
            for n, rule, text in found:
                hits.append("FAIL %s%s [%s] %s" % (label, ":%d" % n if n else "", rule, text[:80]))
                bad_files.add(label)
    except CheckError as e:
        print("forge check-public: %s" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("forge check-public: %s" % e, file=sys.stderr)
        return 2
    lists = "public list" + (" + private list, %d pattern(s)" % len(deny) if deny else "")
    where = ", %d commit(s)" % ncommits if a.range else ""
    for h in hits:
        print(h)
    if hits:
        print("FAIL check-public: %d hit(s) in %d of %d file(s) checked (%s%s)" % (len(hits), len(bad_files), len(items), lists, where))
        return 1
    if a.all and not items:
        print("FAIL check-public: 0 file(s) checked: an empty tree means a wrong root (%s)" % lists)
        return 1
    print("PASS check-public: %d file(s) checked (%s%s)" % (len(items), lists, where))
    return 0


# --- forge commit

def history(data, literal=True):
    """The argv prefix of one history: the engine's, or the data history over the same work tree.
    Literal pathspecs, except for check-ignore, which refuses the option."""
    lit = ["--literal-pathspecs"] if literal else []
    if data:
        return ["git"] + lit + ["--git-dir", os.path.join(lib.ROOT, DATA_GIT), "--work-tree", lib.ROOT]
    return ["git"] + lit + ["-C", lib.ROOT]


def run(argv, stdin=None):
    return subprocess.run(argv, cwd=lib.ROOT, input=stdin, capture_output=True, text=True)


def status_paths(data, paths):
    """[(XY, path)] of one history's changes, untracked files included, the git directories never.

    The data history shares its work tree with the engine, so the engine's allowlist .gitignore
    applies to it too: `/*` hides every untracked data file from its `git status`. Its untracked files
    are listed from its own info/exclude alone, and `git add` needs -f for them (see commit_side)."""
    pathspec = ["--"] + paths if paths else []
    r = run(history(data) + ["status", "--porcelain=v1", "-z", "--no-renames",
                             "--untracked-files=no" if data else "--untracked-files=all"] + pathspec)
    if r.returncode:
        raise CheckError("git status failed: %s" % r.stderr.strip())
    entries = [(e[:2], e[3:]) for e in nul_list(r.stdout)]
    if data:
        exclude = os.path.join(lib.ROOT, DATA_GIT, "info", "exclude")
        r = run(history(True) + ["ls-files", "-o", "-z"] + (["--exclude-from=" + exclude] if os.path.exists(exclude) else [])
                + pathspec)
        if r.returncode:
            raise CheckError("git ls-files failed: %s" % r.stderr.strip())
        entries += [("??", p) for p in nul_list(r.stdout)]
    return [(xy, p) for xy, p in entries if p not in (".git", DATA_GIT) and not p.startswith((".git/", DATA_GIT + "/"))]


def route(paths, two):
    """({engine paths}, {data paths}, {untracked data paths}) for the changed paths."""
    eng = status_paths(False, paths)
    if not two:
        return {p for _, p in eng}, set(), set()
    tracked = set(nul_list(run(history(False) + ["ls-files", "-z"]).stdout))
    cand, untracked = {p for _, p in eng}, set()
    for xy, p in status_paths(True, paths):
        if p not in tracked:
            cand.add(p)
            if xy == "??":
                untracked.add(p)
    ordered = sorted(cand)
    if not ordered:
        return set(), set(), set()
    r = run(history(False, literal=False) + ["check-ignore", "--no-index", "-z", "--stdin"], "\0".join(ordered) + "\0")
    if r.returncode not in (0, 1):  # 1 is "none ignored"
        raise CheckError("git check-ignore failed: %s" % r.stderr.strip())
    ignored = set(nul_list(r.stdout))
    return {p for p in ordered if p not in ignored}, {p for p in ordered if p in ignored}, untracked & ignored


def commit_side(name, data, paths, msg):
    """Stage and commit `paths` in one history. (exit code, line to print)."""
    # -f on the data side: the engine's .gitignore, shared through the work tree, ignores these paths.
    for argv in (["add", "-A"] + (["-f"] if data else []) + ["--"] + paths, ["commit", "-q", "-m", msg, "--only", "--"] + paths):
        r = run(history(data) + argv)
        if r.returncode:
            return 1, "forge commit: the %s commit failed:\n%s" % (name, (r.stdout + r.stderr).rstrip())
    short = run(history(data) + ["rev-parse", "--short", "HEAD"]).stdout.strip()
    return 0, "%-8s %s  %d file(s)" % (name, short, len(paths))


def cmd_commit(a):
    if not a.paths and not a.all:
        print("forge commit: name the paths to commit, or pass --all for every change", file=sys.stderr)
        return 2
    paths = []
    for p in a.paths:
        rel = os.path.relpath(os.path.abspath(p), lib.ROOT)
        if rel == ".." or rel.startswith(".." + os.sep):
            print("forge commit: %s is outside the checkout (%s)" % (p, lib.ROOT), file=sys.stderr)
            return 2
        paths.append(rel)
    two = os.path.isdir(os.path.join(lib.ROOT, DATA_GIT))
    try:
        eng, priv, fresh = route(paths, two)
    except CheckError as e:
        print("forge commit: %s" % e, file=sys.stderr)
        return 2
    if not eng and not priv:
        print("nothing to commit")
        return 0
    # The engine first: a hook that refuses its message or content stops everything, before the
    # data history has moved.
    for name, data, group in (("engine", False, sorted(eng)), ("private", True, sorted(priv))):
        if group:
            code, line = commit_side(name, data, group, a.message)
            print(line)
            if code:
                return code
    for p in sorted(fresh)[:20]:
        hint = "" if "/" not in p else " (a file under an ignored directory needs !/%s/ and /%s/* first)" % (
            p.split("/")[0], p.split("/")[0])
        print("note: %s went to the private history; to publish it, add !/%s to .gitignore%s" % (p, p, hint))
    if len(fresh) > 20:
        print("note: ... and %d more new file(s) went to the private history" % (len(fresh) - 20))
    return 0
