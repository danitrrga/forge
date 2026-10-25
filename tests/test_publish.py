#!/usr/bin/env python3
"""`forge check-public`, `forge commit`, the allowlist in publish/engine.gitignore and the three
githooks. Every world is a toy repository built under TMPDIR: the hooks are only ever wired
(core.hooksPath) inside one, never in this checkout.

Every planted string is built by concatenation, so this file passes the public list itself (the
last case runs the list over it and over forge/publish.py).

Red messages are quoted in the commit that added this file.
"""
import difflib
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sandbox  # noqa: E402

failures = []
notrun = []
FORGE = sandbox.FORGE
ALLOWLIST = os.path.join(FORGE, "publish", "engine.gitignore")
DENY = os.path.join(FORGE, "config", "publish-deny.txt")
# The two private files exist wherever the data does; a stranger's checkout has neither, and then
# the cases that need them print NOT RUN instead of failing. config/profiles/ alone is not the
# data: `forge init` creates it in a stranger's checkout (red there before, M1: "FAIL
# config/publish-deny.txt does not exist", "FAIL publish/engine.gitignore does not exist"). Either
# file present is the data, so a checkout that lost one of them still fails on that one.
HAVE_DATA = os.path.isdir(os.path.join(FORGE, "config", "profiles")) and (os.path.exists(DENY) or os.path.exists(ALLOWLIST))


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def has(label, text, *needles):
    for n in needles:
        if n not in text:
            failures.append("%s: output lacks %r, got %r" % (label, n, text[-400:]))


def lacks(label, text, *needles):
    for n in needles:
        if n in text:
            failures.append("%s: output has %r, got %r" % (label, n, text[-400:]))


def j(*parts):
    return "".join(parts)


HOME_DIR = j("/ho", "me/")
USERS_DIR = j("/Us", "ers/")
TS_NET = j(".ts", ".net")
KEY_HEAD = j("-----BEGIN ", "RSA PRIVATE KEY-----")
NOREPLY = j("12345+someone@users", ".noreply.github.com")

TMP = sandbox.mkdtemp("publish-test-")
HOME = os.path.join(TMP, "home")
os.makedirs(HOME)
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ENV = sandbox.bare_env(HOME, TMP, **IDENT)
_n = [0]


def run(argv, cwd, env=None):
    try:
        r = subprocess.run(argv, cwd=cwd, env=env or ENV, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    except subprocess.TimeoutExpired:
        return 124, "timed out after 60 s: %s" % " ".join(argv[:6])
    return r.returncode, r.stdout + r.stderr


def forge(root, *args):
    return run([sys.executable, os.path.join(root, "bin", "forge")] + list(args), root)


GIT_C = ["-c", "commit.gpgsign=false", "-c", "init.defaultBranch=master", "-c", "maintenance.auto=false",
         "-c", "gc.auto=0"]


def g(root, *args, data=False):
    base = ["git", "--git-dir", os.path.join(root, ".forge-data.git"), "--work-tree", root] if data else ["git", "-C", root]
    return run(base + GIT_C + list(args), root)


def git_out(root, *args, data=False):
    code, out = g(root, *args, data=data)
    if code:
        failures.append("setup: git %s failed: %s" % (" ".join(args), out[-300:]))
    return out.strip()


def write(root, rel, text, mode=None):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w" if isinstance(text, str) else "wb") as f:
        f.write(text)
    if mode:
        os.chmod(p, mode)


def toy(name, overlay=False, deny=False, hooks=False):
    """A toy checkout with the real bin/forge, forge/ package and githooks/ in it. With `overlay`: an
    engine history that tracks what its allowlist un-ignores, and a data history beside it."""
    _n[0] += 1
    root = os.path.join(TMP, "%s-%d" % (name, _n[0]))
    os.makedirs(root)
    os.makedirs(os.path.join(root, "bin"))
    shutil.copy2(os.path.join(FORGE, "bin", "forge"), os.path.join(root, "bin", "forge"))
    shutil.copytree(os.path.join(FORGE, "forge"), os.path.join(root, "forge"), ignore=shutil.ignore_patterns("__pycache__"))
    if os.path.isdir(os.path.join(FORGE, "githooks")):
        shutil.copytree(os.path.join(FORGE, "githooks"), os.path.join(root, "githooks"))
    if deny and os.path.exists(DENY):
        write(root, "config/publish-deny.txt", open(DENY).read())
    git_out(root, "init", "-q")
    if overlay:
        write(root, ".gitignore", "/*\n!/bin/\n!/forge/\n!/githooks/\n!/.gitignore\n/.forge-data.git\n__pycache__/\n")
        data = os.path.join(root, ".forge-data.git")
        run(["git", "--git-dir", data, "init", "-q"], root)
        run(["git", "--git-dir", data, "config", "core.worktree", root], root)
        run(["git", "--git-dir", data, "config", "status.showUntrackedFiles", "no"], root)
        write(root, ".forge-data.git/info/exclude", "/.git\n/.forge-data.git\n/bin\n/forge\n/githooks\n/.gitignore\n")
    if hooks:
        git_out(root, "config", "core.hooksPath", "githooks")
    return root


def head(root, data=False):
    code, out = g(root, "rev-parse", "HEAD", data=data)
    return out.strip() if code == 0 else "0" * 40  # no commit yet


def files_of(root, rev="HEAD", data=False):
    code, out = g(root, "show", "--name-only", "--format=", rev, data=data)
    return sorted(out.split()) if code == 0 else ["git failed: " + out.strip()[:80]]


def dirty(root):
    """(the engine's uncommitted lines, the data history's). The data history shares the work tree
    with the engine's allowlist .gitignore, which hides its untracked files from its own status, so
    those are listed from its info/exclude alone."""
    eng = g(root, "status", "--porcelain", "--untracked-files=all")[1].splitlines()
    data = g(root, "status", "--porcelain", "--untracked-files=no", data=True)[1].splitlines()
    excl = os.path.join(root, ".forge-data.git", "info", "exclude")
    data += ["?? " + p for p in g(root, "ls-files", "-o", "--exclude-from=" + excl, data=True)[1].split()
             if not p.startswith(".forge-data.git/")]
    return eng, data


def commit_files(root, msg, *files):
    git_out(root, "add", "-A", "--", *files)
    return g(root, "commit", "-q", "-m", msg)


# --- 1. the public patterns, each seen failing on a planted string and passing on its allowed form
PUBLIC_CASES = [
    # (label, file name, content, expected rule or None)
    ("home path", "a.txt", "x = " + HOME_DIR + "alice/dev\n", "home path"),
    ("home path, a macOS home", "a.txt", "x = " + USERS_DIR + "bob/dev\n", "home path"),
    ("home path, the documentation name passes", "a.txt", "x = " + HOME_DIR + "user/dev\n", None),
    # A user name starts with a letter, a digit or an underscore: a dot directory right under the home root is a toy path.
    ("home path, a dot directory under the root is not a user", "a.txt", "x = " + HOME_DIR + ".claude/skills " + HOME_DIR + ".codex\n", None),
    ("home path, a user's own dot directory still hits", "a.txt", "x = " + HOME_DIR + "alice/.claude/skills\n", "home path"),
    ("home path, a user name that starts with an underscore still hits", "a.txt", "x = " + HOME_DIR + "_svc/dev\n", "home path"),
    ("email", "a.txt", "mail bob@" + j("acme", ".io") + " now\n", "email"),
    ("email, the no-reply form passes", "a.txt", "mail " + NOREPLY + " now\n", None),
    ("email, the trailer's no-reply address passes", "a.txt", "Co-Authored-By: Claude Sonnet <noreply@" + j("anthropic", ".com") + ">\n", None),
    ("email, a no-reply name without the digits is refused", "a.txt", "mail someone@" + j("users", ".noreply.github.com") + "\n", "email"),
    ("email, a subdomain of the no-reply host is refused", "a.txt", "mail 12345+x@a." + j("users", ".noreply.github.com") + "\n", "email"),
    ("email, another name at the anthropic domain is refused", "a.txt", "mail bob@" + j("anthropic", ".com") + "\n", "email"),
    ("email, a longer local part before noreply is refused", "a.txt", "mail xnoreply@" + j("anthropic", ".com") + "\n", "email"),
    ("email, noreply at another domain is refused", "a.txt", "mail noreply@" + j("acme", ".io") + "\n", "email"),
    ("email, the anthropic address with a suffix domain is refused", "a.txt", "mail noreply@" + j("anthropic", ".com.acme.io") + "\n", "email"),
    ("email, example.com passes", "a.txt", "mail bob@" + j("example", ".com") + "\n", None),
    ("email, example.org passes", "a.txt", "mail bob@" + j("example", ".org") + "\n", None),
    ("email, example.test passes (RFC 6761 reserves .test)", "a.txt", "mail bob@" + j("example", ".test") + "\n", None),
    ("email, a subdomain of example.test passes", "a.txt", "mail bob@mail." + j("example", ".test") + "\n", None),
    ("email, another .test domain is refused (only example.test is a documentation name)", "a.txt", "mail bob@" + j("acme", ".test") + "\n", "email"),
    ("email, example.test as a suffix of another name is refused", "a.txt", "mail bob@" + j("notexample", ".test") + "\n", "email"),
    ("email, a Python decorator after a diff minus is no address", "a.txt", "-@functools.lru_cache(maxsize=1)\n", None),
    ("email, a decorator on its own line is no address", "a.txt", "@functools.lru_cache\n", None),
    ("email, a real-looking name is still refused after the decorator rule", "a.txt", "mail -bob@" + j("acme", ".io") + "\n", "email"),
    ("email, localhost passes", "a.txt", "mail bob@" + j("local", "host") + "\n", None),
    ("ipv4 10/8", "a.txt", "host " + j("10.", "1.2.3") + "\n", "private ip"),
    ("ipv4 172.16/12", "a.txt", "host " + j("172.", "16.0.9") + "\n", "private ip"),
    ("ipv4 172.16/12, upper edge", "a.txt", "host " + j("172.", "31.255.1") + "\n", "private ip"),
    ("ipv4, 172.32 passes", "a.txt", "host " + j("172.", "32.0.1") + "\n", None),
    ("ipv4 192.168/16", "a.txt", "host " + j("192.", "168.0.10") + "\n", "private ip"),
    ("ipv4 100.64/10", "a.txt", "host " + j("100.", "64.0.1") + "\n", "private ip"),
    ("ipv4 100.64/10, upper edge", "a.txt", "host " + j("100.", "127.9.9") + "\n", "private ip"),
    ("ipv4, 100.128 passes", "a.txt", "host " + j("100.", "128.0.1") + "\n", None),
    ("ipv4, the documentation range passes", "a.txt", "host " + j("192.", "0.2.1") + " and " + j("198.", "51.100.1") + "\n", None),
    ("ipv4, a three-part version passes", "a.txt", "v " + j("10.", "1.2") + "\n", None),
    ("ipv4, a longer dotted number passes", "a.txt", "v " + j("1.1", "0.1.2.3") + "\n", None),
    ("tailnet name", "a.txt", "ssh box.tail1234" + TS_NET + " now\n", "tailnet host"),
    ("tailnet name, ts.network passes", "a.txt", "ssh box.ts" + ".network now\n", None),
    ("private key header", "a.txt", KEY_HEAD + "\nabc\n", "private key"),
    ("private key, a public key header passes", "a.txt", j("-----BEGIN ", "PUBLIC KEY-----") + "\n", None),
    ("a file over 1 MiB", "big.txt", "a" * (1024 * 1024 + 1), "size"),
    ("a file of exactly 1 MiB passes", "ok.txt", "a" * (1024 * 1024), None),
    ("font extension", "f.woff2", b"\x00\x01", "binary asset"),
    ("image extension", "i.png", b"\x89PNG", "binary asset"),
    ("image extension, upper case", "i.JPG", b"\xff\xd8", "binary asset"),
    ("a text extension passes", "t.md", "plain\n", None),
]


def public_cases():
    for label, name, content, rule in PUBLIC_CASES:
        root = toy("pub")
        write(root, "docs/" + name, content)
        git_out(root, "add", "docs/" + name)
        for mode in ("--all", "--staged"):
            code, out = forge(root, "check-public", mode)
            want("%s, %s = exit" % (label, mode), code, 0 if rule is None else 1)
            if rule:
                has("%s, %s" % (label, mode), out, "docs/" + name, "[" + rule + "]")
            else:
                has("%s, %s" % (label, mode), out, "PASS check-public")
    # A file is named with its line.
    root = toy("pub-line")
    write(root, "a.txt", "ok\nok\n" + HOME_DIR + "alice/x\n")
    git_out(root, "add", "a.txt")
    code, out = forge(root, "check-public", "--all")
    has("the hit names its line", out, "a.txt:3 [home path]")
    # Nothing checked is a FAIL for --all (an empty tree means a wrong root), not for --staged.
    root = toy("pub-empty")
    code, out = forge(root, "check-public", "--all")
    want("--all over no file = exit", code, 1)
    has("--all over no file", out, "FAIL check-public", "0 file(s)")
    code, out = forge(root, "check-public", "--staged")
    want("--staged over nothing staged = exit", code, 0)
    has("--staged over nothing staged", out, "PASS check-public", "0 file(s)")
    code, out = forge(root, "check-public")
    want("no mode = exit", code, 2)


# --- 1b. a reviewed asset: an image or font file is refused by its extension, since its bytes cannot
# be read for personal data; publish.PUBLIC_ASSETS names the few a person has looked at, by path and
# sha256. Red before the pin existed: "the pinned bytes at the pinned path = [(0, 'binary asset',
# '.png')], want []".
def pinned_asset_cases():
    sys.path.insert(0, FORGE)
    from forge import publish
    import hashlib
    data = b"\x89PNG reviewed"
    saved = dict(getattr(publish, "PUBLIC_ASSETS", {}))
    try:
        publish.PUBLIC_ASSETS = {"docs/assets/x.png": hashlib.sha256(data).hexdigest()}
        want("the pinned bytes at the pinned path", publish.scan("docs/assets/x.png", data, None), [])
        want("one changed byte at the pinned path", publish.scan("docs/assets/x.png", data + b"!", None),
             [(0, "binary asset", ".png")])
        want("the pinned bytes at another path", publish.scan("docs/assets/y.png", data, None),
             [(0, "binary asset", ".png")])
        # A pinned text asset (an SVG) is still read line by line: the pin waives the extension rule only.
        svg = ("<svg><text>" + HOME_DIR + "alice</text></svg>\n").encode()
        publish.PUBLIC_ASSETS = {"docs/assets/x.svg": hashlib.sha256(svg).hexdigest()}
        want("a pinned SVG is still scanned", [r for _, r, _ in publish.scan("docs/assets/x.svg", svg, None)], ["home path"])
    finally:
        publish.PUBLIC_ASSETS = saved
    # Every real pin matches the file it names, so a stale pin is a failure here, not a silent hit later.
    for rel, digest in saved.items():
        full = os.path.join(FORGE, rel)
        got = hashlib.sha256(open(full, "rb").read()).hexdigest() if os.path.exists(full) else "(missing)"
        want("pin of %s" % rel, got, digest)


# --- 2. the private list
def private_cases():
    root = toy("deny")
    write(root, "config/publish-deny.txt", "# a comment\n\nsecret-word\n(?i)other\\d+\n")
    write(root, "a.txt", "has a Secret-Word inside\n")
    write(root, "b.txt", "has other42 inside\n")
    write(root, "c.txt", "a clean line\n")
    git_out(root, "add", "a.txt", "b.txt", "c.txt")
    code, out = forge(root, "check-public", "--all")
    want("private list, two files hit = exit", code, 1)
    has("private list", out, "a.txt:1 [private list]", "b.txt:1 [private list]", "3 file(s) checked", "2 pattern(s)")
    lacks("private list", out, "c.txt")
    # LICENSE is exempt from the private list only.
    write(root, "LICENSE", "Copyright (c) secret-word\n")
    write(root, "a.txt", "clean\n")
    write(root, "b.txt", "clean\n")
    git_out(root, "add", "a.txt", "b.txt", "LICENSE")
    code, out = forge(root, "check-public", "--all")
    want("LICENSE with a private word = exit", code, 0)
    write(root, "LICENSE", "Copyright (c) x\n" + HOME_DIR + "alice/x\n")
    git_out(root, "add", "LICENSE")
    code, out = forge(root, "check-public", "--all")
    want("LICENSE with a public hit = exit", code, 1)
    has("LICENSE with a public hit", out, "LICENSE:2 [home path]")
    # A skill-bench task holds dates as data (a calendar, a leap day): in its files a private pattern that matches a bare
    # ISO date is not applied. Every other private pattern still is, and a date anywhere else is still refused.
    task, day = "benchmarks/skill-bench/tasks/t-01/repo/cal.txt", j("2026-03", "-09")
    for label, rel, line, hits in (
            ("a date in a task file", task, day + " 09:00", False),
            ("a private word in a task file", task, "secret-word on " + day, True),
            ("a date outside the tasks", "forge/x.py", "# decided " + day, True),
            ("a date in the benchmark's own docs", "benchmarks/skill-bench/SOURCES.md", "Researched " + day, True),
            ("a date under a look-alike directory", "benchmarks/skill-bench/tasks-old/x.txt", day, True)):
        root = toy("deny-dated")
        write(root, "config/publish-deny.txt", "20\\d\\d-\\d\\d-\\d\\d\nsecret-word\n")
        write(root, rel, line + "\n")
        git_out(root, "add", rel)
        code, out = forge(root, "check-public", "--all")
        want("dated data, %s = exit" % label, code, 1 if hits else 0)
        if hits:
            has("dated data, %s" % label, out, rel + ":1 [private list]")
    # An allowed token is one exact string a project's file format requires (forge/publish.py PRIVATE_ALLOW):
    # it passes the private list where it stands alone, and the same word anywhere else is still refused.
    marker = j("LIFE", "OS-SYSTEM-POINTER")
    word = j("Life", "OS")
    root = toy("deny-allow")
    write(root, "config/publish-deny.txt", word.lower() + "\n")
    for label, line, hits in (
            ("the allowed token alone", "<!-- BEGIN %s (managed) -->" % marker, False),
            ("the allowed token twice on a line", "%s %s" % (marker, marker), False),
            ("the bare name", "the %s vault" % word, True),
            ("the allowed token and the bare name on one line", "%s then %s" % (marker, word), True),
            ("the allowed token in lower case", marker.lower(), True),
            ("the allowed token as the start of a longer name", marker + "-2", True),
            ("the allowed token as the end of a longer name", "X" + marker, True)):
        write(root, "a.txt", line + "\n")
        git_out(root, "add", "a.txt")
        code, out = forge(root, "check-public", "--all")
        want("private allow, %s = exit" % label, code, 1 if hits else 0)
        if hits:
            has("private allow, %s" % label, out, "a.txt:1 [private list]")
    # The allowance is for the private list only: the public list still runs over the line.
    write(root, "a.txt", marker + " " + HOME_DIR + "alice/x\n")
    git_out(root, "add", "a.txt")
    code, out = forge(root, "check-public", "--all")
    want("private allow, the public list still runs = exit", code, 1)
    has("private allow, the public list still runs", out, "a.txt:1 [home path]")
    # A broken list is an error, never a pass.
    for label, body, needle in (("an invalid pattern", "ok\n(unclosed\n", "publish-deny.txt:2"),
                                ("an empty list", "# only a comment\n\n", "no pattern")):
        root = toy("deny-bad")
        write(root, "config/publish-deny.txt", body)
        write(root, "a.txt", "clean\n")
        git_out(root, "add", "a.txt")
        code, out = forge(root, "check-public", "--all")
        want("%s = exit" % label, code, 2)
        has(label, out, needle)


def real_deny_cases():
    """The file this machine ships, not a toy list."""
    if not HAVE_DATA:
        notrun.append("config/publish-deny.txt cases (no data on this machine)")
        return
    if not os.path.exists(DENY):
        failures.append("config/publish-deny.txt does not exist")
        return
    passing = "\n".join([
        "git clone https://github.com/" + j("dani", "trrga") + "/forge",
        "Copyright (c) " + j("dani", "trrga"),
        "Copyright (c) 2026 " + j("dani", "trrga"),
        "author " + j("123456+dani", "trrga") + "@users.noreply.github.com",
    ]) + "\n"
    root = toy("realdeny", deny=True)
    write(root, "README.md", passing)
    git_out(root, "add", "README.md")
    code, out = forge(root, "check-public", "--all")
    want("the clone URL, the no-reply address and the copyright line = exit", code, 0)
    has("the clone URL, the no-reply address and the copyright line", out, "PASS check-public", "private list")
    # The handle alone is not on the list: the file's every pattern is run over it.
    import re
    bad = []
    for line in open(DENY):
        line = line.strip()
        if line and not line.startswith("#") and re.search(line, j("dani", "trrga"), re.I):
            bad.append(line)
    want("a pattern that matches the bare handle", bad, [])
    # Refused, each by a rule the public list does not have: only the loaded file can say it.
    probes = [("the home path", HOME_DIR + j("dani", "trrga") + "/dev/x"), ("the surname", "by Tar" + "raga"),
              ("the first name", "ask Dan" + "iel"), ("a decision date", "decided " + j("2026-", "10-13")),
              ("the tailnet", "host " + j("tail", "470542")), ("a host name", "the home" + "lab box"),
              ("the LAN address", "ip " + j("192.", "168.0.10")), ("the second address", "mail me@" + j("member.", "vdw", "aals.nl"))]
    for label, text in probes:
        root = toy("realdeny-hit", deny=True)
        write(root, "README.md", text + "\n")
        git_out(root, "add", "README.md")
        code, out = forge(root, "check-public", "--all")
        want("%s = exit" % label, code, 1)
        has(label, out, "README.md:1")
    for label, text in probes[1:2] + probes[2:3] + probes[3:6]:
        root = toy("realdeny-only", deny=True)
        write(root, "README.md", text + "\n")
        git_out(root, "add", "README.md")
        code, out = forge(root, "check-public", "--all")
        has("%s is named by the private list" % label, out, "[private list]")
        os.remove(os.path.join(root, "config", "publish-deny.txt"))
        code, out = forge(root, "check-public", "--all")
        want("%s without the file = exit (the public list alone passes it)" % label, code, 0)


# --- 3. the allowlist and today's engine files
def allowlist_cases():
    if not HAVE_DATA:
        notrun.append("allowlist cases (no data on this machine)")
        return
    if not os.path.exists(ALLOWLIST):
        failures.append("publish/engine.gitignore does not exist")
        return
    # The copy is what tests/sandbox.py's copy_engine filters by: a line the engine's .gitignore gained and the copy
    # lacks leaves that file out of every engine sandbox (scripts/sync/materialise_skills.py once failed two suites so).
    with open(ALLOWLIST, encoding="utf-8") as a, open(os.path.join(FORGE, ".gitignore"), encoding="utf-8") as b:
        drift = [l for l in difflib.unified_diff(a.read().splitlines(), b.read().splitlines(), lineterm="", n=0)
                 if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    want("publish/engine.gitignore is the engine's .gitignore, line for line (- copy, + .gitignore)", drift, [])
    code, out = run(["git", "-C", FORGE, "ls-files", "-c", "-z"], FORGE)
    tracked = set(p for p in out.split("\0") if p)
    code, out = run(["git", "-C", FORGE, "ls-files", "-c", "-i", "-z", "--exclude-from=publish/engine.gitignore"], FORGE)
    ignored = set(p for p in out.split("\0") if p)
    engine = tracked - ignored
    private = ["hooks/test_audit_tool_use.py",
               "hooks/audit_tool_use.py", "hooks/track_skill_usage.py", "scripts/sync/hindsight_doctor.py",
               "scripts/sync/test_hindsight_doctor.py", "tests/test_gate.py", j("config/profiles/life", "os.claude.json"),
               "config/mcp-registry.json", "config/toolchain.json", "docs/portable-design.md", "design/taste/README.md",
               "skills/new-project/SKILL.md", j("mcp-servers/vdw", "aals-mcp.py"), "scripts/dev/gate.py",
               "scripts/backup/t7-backup.sh", ".claude/settings.json", "publish/engine.gitignore"]
    public = ["bin/forge", "forge/cli.py", "forge/publish.py", "hooks/guard_tool_use.py", "hooks/test_guard_tool_use.py",
              "hooks/worktree_guard.py", "hooks/gsd-prompt-guard.js", "hooks/omarchy_notify.py",
              "hooks/test_guard_mutants.py", "config/gsd/defaults.json", "scripts/sync/sync_skill_keep.py",
              "scripts/sync/test_sync_skill_keep.py", "scripts/sync/memory_doctor.py", "scripts/metrics/harness-metrics.mjs",
              "githooks/pre-commit", "githooks/commit-msg", "githooks/pre-push", "tests/sandbox.py",
              "tests/test_publish.py", "tests/test_sync_agent_config.py", ".gitignore", "CLAUDE.md", "README.md", "AGENTS.md",
              "scripts/sync/materialise_skills.py", "scripts/bench/skill_bench.py", "benchmarks/skill-bench/README.md",
              "config/forge.lock.json"]
    want("tracked and ignored by the allowlist, of the private paths", sorted(p for p in private if p in tracked and p not in ignored), [])
    want("tracked and not ignored, of the engine paths", sorted(p for p in public if p in tracked and p in ignored), [])
    want("every named engine path is tracked", sorted(p for p in public if p not in tracked), [])
    # docs/assets/ holds the README's images and benchmarks/skill-bench/ the benchmark, which are public; the rest of
    # docs/ and benchmarks/ is not. Of config/, gsd/ and the lock (the versions a release ships) are.
    want("no skill, doc, design file or profile in the engine",
         sorted(p for p in engine if (p.split("/")[0] in ("skills", "docs", "design", "benchmarks", "mcp-servers", "repo-kit", ".claude")
                                      and not p.startswith(("docs/assets/", "benchmarks/skill-bench/")))
                or p.startswith("config/profiles/")
                or (p.startswith("config/") and not p.startswith("config/gsd/") and p != "config/forge.lock.json")), [])
    # The private list runs over today's engine files: exit 0, no hit in any file. The gate's `public tree` row
    # holds the same state from the other side.
    if not os.path.exists(DENY):
        failures.append("config/publish-deny.txt does not exist")
        return
    code, out = forge(FORGE, "check-public", "--all")
    hits = [l for l in out.splitlines() if l.startswith("FAIL ") and ":" in l.split()[1] and not l.startswith("FAIL check-public:")]
    want("today's engine files with the private list: no hit", hits, [])
    want("today's engine files with the private list = exit", code, 0)
    leaked = sorted(set(l.split()[1].rsplit(":", 1)[0] for l in hits
                        if (l.split()[1].split("/")[0] in ("docs", "skills", "design", "benchmarks", "mcp-servers", "repo-kit", ".claude")
                            and not l.split()[1].startswith(("docs/assets/", "benchmarks/skill-bench/")))
                        or l.split()[1].startswith("config/profiles/")))
    want("the control names nothing outside the engine", leaked, [])


def own_files_cases():
    """The new files are engine files: the public list, and the private list where it exists, pass them."""
    for deny in (False, True):
        if deny and not (HAVE_DATA and os.path.exists(DENY)):
            continue
        root = toy("own", deny=deny)
        for rel in ("forge/publish.py", "tests/test_publish.py"):
            if not os.path.exists(os.path.join(FORGE, rel)):
                failures.append("%s does not exist" % rel)
                return
            write(root, rel, open(os.path.join(FORGE, rel)).read())
        git_out(root, "add", "forge/publish.py", "tests/test_publish.py")
        code, out = forge(root, "check-public", "--staged")
        want("forge/publish.py and tests/test_publish.py, %s list = exit" % ("both" if deny else "public"), code, 0)
        if code:
            has("own files", out, "PASS")


# --- 4. range and message
def range_cases():
    root = toy("range")
    write(root, "a.txt", "clean\n")
    commit_files(root, "one", "a.txt")
    first = head(root)
    write(root, "b.txt", "mail bob@" + j("acme", ".io") + "\n")
    commit_files(root, "two", "b.txt")
    second = head(root)
    write(root, "b.txt", "clean again\n")
    commit_files(root, "three", "b.txt")
    third = head(root)
    code, out = forge(root, "check-public", "--range", first + ".." + third)
    want("a planted address in a commit that a later one fixes = exit", code, 1)
    has("range", out, second[:7] + ":b.txt:1 [email]", "2 commit(s)")
    code, out = forge(root, "check-public", "--range", second + ".." + third)
    want("the same range starting after it = exit", code, 0)
    has("range after the plant", out, "PASS check-public", "1 commit(s)")
    code, out = forge(root, "check-public", "--range", "0" * 40 + ".." + third)
    want("a new branch (all-zero remote) over the whole history = exit", code, 1)
    has("new branch", out, second[:7] + ":b.txt:1 [email]", "3 commit(s)")
    code, out = forge(root, "check-public", "--range", "nosuchrev.." + third)
    want("an unknown revision = exit", code, 2)
    # A message is scanned too.
    write(root, "c.txt", "x\n")
    commit_files(root, "fix for bob@" + j("acme", ".io") + " (note)", "c.txt")
    code, out = forge(root, "check-public", "--range", third + "..HEAD")
    want("a planted address in a message = exit", code, 1)
    has("range message", out, ":(message):1 [email]")
    mf = os.path.join(TMP, "msg")
    for label, text, rc in (("a clean message", "feat: x\n\n# Please enter the commit message\n# /ho" + "me/alice/x\n", 0),
                            ("a message with an address", "feat: x for bob@" + j("acme", ".io") + "\n", 1),
                            ("a message with a no-reply address", "Co-Authored-By: A <" + NOREPLY + ">\n", 0)):
        open(mf, "w").write(text)
        code, out = forge(root, "check-public", "--message", mf)
        want("%s = exit" % label, code, rc)
    code, out = forge(root, "check-public", "--message", os.path.join(TMP, "nofile"))
    want("a missing message file = exit", code, 2)


# --- 5. forge commit
def commit_cases():
    root = toy("overlay", overlay=True)
    write(root, "config/profiles/a.claude.json", "{}\n")
    write(root, "notes.txt", "n\n")
    code, out = forge(root, "commit", "--all", "-m", "seed")
    want("seed = exit", code, 0)
    git_out(root, "config", "core.hooksPath", "githooks")
    engine = [".gitignore", "bin/forge"] + ["forge/" + f for f in os.listdir(os.path.join(FORGE, "forge")) if f.endswith(".py")]
    if os.path.isdir(os.path.join(root, "githooks")):
        engine += ["githooks/" + f for f in os.listdir(os.path.join(root, "githooks"))]
    want("seed: engine files", files_of(root), sorted(engine))
    want("seed: data files", files_of(root, data=True), ["config/profiles/a.claude.json", "notes.txt"])
    want("seed: nothing from either git directory in the data history",
         [f for f in files_of(root, data=True) if f.startswith((".git/", ".forge-data.git/"))], [])
    want("seed: a second run has nothing to commit = exit", forge(root, "commit", "--all", "-m", "again")[0], 0)
    # The routing: one change in each history, and a new file outside the allowlist.
    e0, d0 = head(root), head(root, data=True)
    write(root, "forge/extra.py", "X = 1\n")
    write(root, "config/profiles/a.claude.json", '{"a": 1}\n')
    write(root, "notes/new.md", "new\n")
    code, out = forge(root, "commit", "--all", "-m", "mixed change")
    want("mixed change = exit", code, 0)
    want("mixed: engine files", files_of(root), ["forge/extra.py"])
    want("mixed: data files", files_of(root, data=True), ["config/profiles/a.claude.json", "notes/new.md"])
    want("mixed: both histories grew by one", (g(root, "rev-list", "--count", e0 + "..HEAD")[1].strip(),
                                               g(root, "rev-list", "--count", d0 + "..HEAD", data=True)[1].strip()), ("1", "1"))
    want("mixed: one message", (g(root, "log", "-1", "--format=%s")[1].strip(), g(root, "log", "-1", "--format=%s", data=True)[1].strip()),
         ("mixed change", "mixed change"))
    has("mixed: both hashes", out, head(root)[:7], head(root, data=True)[:7])
    has("mixed: the private-by-default line", out, "notes/new.md went to the private history; to publish it, add !/notes/new.md to .gitignore")
    lacks("mixed: a tracked data file is not announced", out, "config/profiles/a.claude.json went")
    want("mixed: nothing left in either", dirty(root), ([], []))
    # Named paths narrow the set.
    write(root, "forge/extra.py", "X = 2\n")
    write(root, "config/profiles/a.claude.json", '{"a": 2}\n')
    write(root, "notes.txt", "changed\n")
    code, out = forge(root, "commit", "-m", "only one", "notes.txt")
    want("named path = exit", code, 0)
    want("named path: data files", files_of(root, data=True), ["notes.txt"])
    want("named path: the engine did not move", files_of(root), ["forge/extra.py"])
    want("named path: the other changes stay", dirty(root), ([" M forge/extra.py"], [" M config/profiles/a.claude.json"]))
    # A path outside the checkout is refused.
    code, out = forge(root, "commit", "-m", "x", "/etc/hostname")
    want("a path outside the checkout = exit", code, 2)
    # A deletion in each history.
    os.remove(os.path.join(root, "forge", "extra.py"))
    os.remove(os.path.join(root, "notes.txt"))
    code, out = forge(root, "commit", "-m", "deletions", "forge/extra.py", "notes.txt")
    want("deletions = exit", code, 0)
    want("deletions: files", (files_of(root), files_of(root, data=True)), (["forge/extra.py"], ["notes.txt"]))
    # A path removed with `git rm` (the deletion already staged, the file gone from disk) is committed too.
    # Red before the change: "git rm: engine = exit: got 1, want 0" with "fatal: pathspec 'forge/gone.py' did not
    # match any files" (the plain `git add -A -- path` has nothing to match), and the same for the data history.
    write(root, "forge/gone.py", "G = 1\n")
    write(root, "gone.txt", "g\n")
    want("git rm: seed = exit", forge(root, "commit", "-m", "to remove", "forge/gone.py", "gone.txt")[0], 0)
    git_out(root, "rm", "-q", "--", "forge/gone.py")
    git_out(root, "rm", "-q", "--", "gone.txt", data=True)
    code, out = forge(root, "commit", "-m", "git rm engine", "forge/gone.py")
    want("git rm: engine = exit", code, 0)
    want("git rm: engine files", files_of(root), ["forge/gone.py"])
    want("git rm: the removed engine file is gone from HEAD", g(root, "ls-tree", "-r", "--name-only", "HEAD")[1].split().count("forge/gone.py"), 0)
    code, out = forge(root, "commit", "-m", "git rm data", "gone.txt")
    want("git rm: data = exit", code, 0)
    want("git rm: data files", files_of(root, data=True), ["gone.txt"])
    want("git rm: the removed data file is gone from HEAD", g(root, "ls-tree", "-r", "--name-only", "HEAD", data=True)[1].split().count("gone.txt"), 0)
    # The git directories are never routed, even with no exclude line for them.
    root = toy("overlay-noexclude", overlay=True)
    write(root, ".forge-data.git/info/exclude", "/bin\n/forge\n/githooks\n/.gitignore\n")
    write(root, "n.txt", "n\n")
    code, out = forge(root, "commit", "--all", "-m", "seed")
    want("no exclude lines: data files", files_of(root, data=True), ["n.txt"])
    # Without a second history it is plain add and commit.
    root = toy("single")
    write(root, "a.txt", "a\n")
    write(root, "forge/x.py", "x\n")
    code, out = forge(root, "commit", "--all", "-m", "single")
    want("single history = exit", code, 0)
    want("single history: one commit with everything", [f for f in files_of(root) if f in ("a.txt", "forge/x.py")], ["a.txt", "forge/x.py"])
    lacks("single history", out, "private history")
    write(root, "a.txt", "b\n")
    write(root, "forge/x.py", "y\n")
    code, out = forge(root, "commit", "-m", "named", "a.txt")
    want("single history, named path: files", files_of(root), ["a.txt"])
    # Nothing to commit, and a missing message.
    code, out = forge(root, "commit", "-m", "named too", "a.txt")
    want("nothing to commit = exit", code, 0)
    has("nothing to commit", out, "nothing to commit")
    code, out = forge(root, "commit")
    want("no message = exit", code, 2)
    # No path and no --all must not sweep every change into a commit (a 31-file commit once did).
    # Red before the change: "no paths, no --all = exit: got 0, want 2".
    write(root, "forge/swept.py", "X = 2\n")
    e1, d1 = head(root), head(root, data=True)
    code, out = forge(root, "commit", "-m", "no paths")
    want("no paths, no --all = exit", code, 2)
    has("no paths, no --all", out, "--all")
    want("no paths, no --all = neither history moved", (head(root), head(root, data=True)), (e1, d1))


# --- 6. the hooks, only in toy repositories
def hook_cases():
    real = os.path.join(FORGE, "githooks")
    for name in ("pre-commit", "commit-msg", "pre-push"):
        p = os.path.join(real, name)
        want("githooks/%s is an executable file" % name, os.path.isfile(p) and os.access(p, os.X_OK), True)
    root = toy("hooks", overlay=True)
    write(root, "config/profiles/a.claude.json", "{}\n")
    code, out = forge(root, "commit", "--all", "-m", "seed")
    want("hooks: seed = exit", code, 0)
    git_out(root, "config", "core.hooksPath", "githooks")
    if os.path.isdir(os.path.join(root, "githooks")):
        modes = git_out(root, "ls-files", "-s", "githooks")
        want("hooks: modes in the index", sorted(l.split()[0] for l in modes.splitlines()), ["100755"] * len(os.listdir(os.path.join(root, "githooks"))))
    # pre-commit: a clean engine commit passes through the hook ...
    write(root, "forge/extra.py", "X = 1\n")
    git_out(root, "add", "forge/extra.py")
    before = head(root)
    code, out = g(root, "commit", "-q", "-m", "clean")
    want("pre-commit, a clean commit = (exit, moved)", (code, head(root) != before), (0, True))
    # ... and a data path added with -f is refused, by the hook's own words.
    write(root, "config/profiles/a.claude.json", '{"a": 1}\n')
    git_out(root, "add", "-f", "config/profiles/a.claude.json")
    before = head(root)
    code, out = g(root, "commit", "-q", "-m", "data")
    want("pre-commit, a data path added with -f = (exit, moved)", (code, head(root) != before), (1, False))
    has("pre-commit, a data path added with -f", out, "pre-commit: refused", "config/profiles/a.claude.json", "ignored by .gitignore")
    git_out(root, "reset", "-q")
    # pre-commit runs check-public: a planted address is refused with the finding, a no-reply form passes.
    for label, text, rc in (("a planted address", "mail bob@" + j("acme", ".io") + "\n", 1), ("its no-reply form", "mail " + NOREPLY + "\n", 0)):
        write(root, "forge/extra.py", "# " + text)
        git_out(root, "add", "forge/extra.py")
        before = head(root)
        code, out = g(root, "commit", "-q", "-m", "x")
        want("pre-commit, %s = (exit, moved)" % label, (code, head(root) != before), (rc, rc == 0))
        if rc:
            has("pre-commit, %s" % label, out, "forge/extra.py:1 [email]", "FAIL check-public")
        else:
            has("pre-commit, %s" % label, out, "PASS check-public")
    # commit-msg: the same patterns over the message.
    write(root, "forge/extra.py", "X = 3\n")
    git_out(root, "add", "forge/extra.py")
    before = head(root)
    code, out = g(root, "commit", "-q", "-m", "fix for bob@" + j("acme", ".io"))
    want("commit-msg, a planted address = (exit, moved)", (code, head(root) != before), (1, False))
    has("commit-msg, a planted address", out, "(message):1 [email]")
    code, out = g(root, "commit", "-q", "-m", "fix for " + NOREPLY)
    want("commit-msg, the no-reply form = (exit, moved)", (code, head(root) != before), (0, True))
    # The standard trailer must not be refused as an address.
    write(root, "forge/extra.py", "X = 4\n")
    git_out(root, "add", "forge/extra.py")
    before = head(root)
    code, out = g(root, "commit", "-q", "-m", "x\n\nCo-Authored-By: Claude Sonnet <noreply@" + j("anthropic", ".com") + ">")
    want("commit-msg, the standard trailer = (exit, moved)", (code, head(root) != before), (0, True))
    # pre-push: a commit made with --no-verify is caught on the way out; clean history goes.
    remote = os.path.join(TMP, "remote.git")
    run(["git", "init", "-q", "--bare", remote], TMP)
    git_out(root, "remote", "add", "origin", remote)
    code, out = g(root, "push", "-q", "origin", "master")
    want("pre-push, a clean history = exit", code, 0)
    pushed = run(["git", "--git-dir", remote, "rev-parse", "master"], TMP)[1].strip()
    want("pre-push, a clean history arrived", pushed, head(root))
    write(root, "forge/leak.py", "# " + HOME_DIR + "alice/dev\n")
    git_out(root, "add", "forge/leak.py")
    code, out = g(root, "commit", "-q", "--no-verify", "-m", "leak")
    want("pre-push, setup: --no-verify commit = exit", code, 0)
    leaked = head(root)
    code, out = g(root, "push", "-q", "origin", "master")
    want("pre-push, a planted home path = exit", code, 1)
    has("pre-push, a planted home path", out, leaked[:7] + ":forge/leak.py:1 [home path]")
    want("pre-push, the remote did not move", run(["git", "--git-dir", remote, "rev-parse", "master"], TMP)[1].strip(), pushed)
    # A later commit that deletes the file does not unpublish it: the range still holds it.
    os.remove(os.path.join(root, "forge", "leak.py"))
    git_out(root, "add", "-A", "--", "forge/leak.py")
    g(root, "commit", "-q", "-m", "remove it")
    code, out = g(root, "push", "-q", "origin", "master")
    want("pre-push, the leak removed by a later commit = exit", code, 1)
    # A branch with no remote counterpart: the whole branch is the range.
    code, out = g(root, "push", "-q", "origin", "master:fresh")
    want("pre-push, a new remote branch = exit", code, 1)
    has("pre-push, a new remote branch", out, "forge/leak.py:1 [home path]")
    # Deleting a remote branch is not scanned.
    run(["git", "--git-dir", remote, "branch", "gone", pushed], TMP)
    code, out = g(root, "push", "-q", "origin", ":gone")
    want("pre-push, a branch deletion = exit", code, 0)
    # A hook that cannot find bin/forge says so, in its own words, and refuses.
    os.rename(os.path.join(root, "bin", "forge"), os.path.join(root, "bin", "forge.off"))
    write(root, "forge/extra.py", "X = 4\n")
    git_out(root, "add", "forge/extra.py")
    before = head(root)
    code, out = g(root, "commit", "-q", "-m", "no forge")
    want("pre-commit, bin/forge missing = (exit, moved)", (code, head(root) != before), (1, False))
    has("pre-commit, bin/forge missing", out, "pre-commit: refused", "bin/forge")


def worktree_cases():
    """A linked worktree has no config/publish-deny.txt of its own (private files exist only in the main
    checkout), so the list is read from the main checkout `git rev-parse --git-common-dir` names. Red before
    the fallback: "private list, staged file in a linked worktree = exit = 0, want 1" and "output lacks
    'a.txt:1 [private list]', got 'PASS check-public: 1 file(s) checked (public list)'"."""
    word = j("secret", "-word")
    for label, deny_in_main in (("main has a list", True), ("main has no list", False)):
        main = toy("deny-main")
        if deny_in_main:
            write(main, "config/publish-deny.txt", word + "\n")
        # the deny file stays untracked, as in the real checkout: the worktree must not get it from git
        git_out(main, "add", "bin", "forge", "githooks")
        git_out(main, "commit", "-q", "-m", "base")
        tree = os.path.join(TMP, "linked-%d" % _n[0])
        git_out(main, "worktree", "add", "-q", "-b", "wt", tree)
        if os.path.exists(os.path.join(tree, "config", "publish-deny.txt")):
            failures.append("worktree case: the linked worktree holds the deny file itself, the case proves nothing")
        write(tree, "a.txt", "has a %s inside\n" % word)
        git_out(tree, "add", "a.txt")
        code, out = forge(tree, "check-public", "--staged")
        if deny_in_main:
            want("private list, staged file in a linked worktree = exit", code, 1)
            has("private list in a linked worktree", out, "a.txt:1 [private list]", "1 pattern(s)")
        else:
            # no list anywhere: None as before, no crash, the public list alone
            want("no list in the main checkout, linked worktree = exit", code, 0)
            has("no list in the main checkout, linked worktree", out, "PASS check-public: 1 file(s) checked (public list)")
            lacks("no list in the main checkout, linked worktree", out, "private list")


def worktree_layout_cases():
    """The main checkout of a linked worktree is found from the common git dir's `core.worktree` when it is
    set (a submodule), else from a common dir called `.git`. Red before core.worktree was read, quoted:
    "submodule layout, linked worktree = exit = 0, want 1" and "output lacks '[private list]', got 'PASS
    check-public: 1 file(s) checked (public list)'". A deny file that is not UTF-8 was exit 1 with a
    UnicodeDecodeError traceback, one with `a{` and a 20-digit count exit 1 with an OverflowError traceback;
    both want exit 2.
    Not covered, because git cannot answer it: after `git init --separate-git-dir` neither the git dir nor its
    config names the main tree (no core.worktree; `git worktree list` reports the git dir itself as the main
    tree), so a linked worktree of such a checkout cannot find the main's list."""
    word = j("secret", "-word")

    def check_message(tree, text):
        write(tree, "msg.txt", text + "\n")
        return forge(tree, "check-public", "--message", os.path.join(tree, "msg.txt"))

    def commit_base(main):
        git_out(main, "add", "bin", "forge", "githooks")
        git_out(main, "commit", "-q", "-m", "base")

    # control: a plain checkout, git dir `.git` inside it
    main = toy("plain-main")
    write(main, "config/publish-deny.txt", word + "\n")
    commit_base(main)
    tree = os.path.join(TMP, "linked-%d" % _n[0])
    git_out(main, "worktree", "add", "-q", "-b", "wt", tree)
    code, out = check_message(tree, "a %s inside" % word)
    want("plain layout, linked worktree = exit", code, 1)
    has("plain layout, linked worktree", out, "[private list]")

    # a submodule: its git dir is <super>/.git/modules/sub, named otherwise, and carries core.worktree
    sub_src = toy("sub-src")
    commit_base(sub_src)
    sup = toy("super")
    write(sup, "README", "x\n")
    git_out(sup, "add", "README")
    git_out(sup, "commit", "-q", "-m", "base")
    git_out(sup, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub_src, "sub")
    sub = os.path.join(sup, "sub")
    write(sub, "config/publish-deny.txt", word + "\n")
    tree = os.path.join(TMP, "linked-%d" % _n[0])
    git_out(sub, "worktree", "add", "-q", "-b", "wt", tree)
    code, out = check_message(tree, "a %s inside" % word)
    want("submodule layout, linked worktree = exit", code, 1)
    has("submodule layout, linked worktree", out, "[private list]")

    # E1-3: an invalid list is exit 2 with the file named, never a traceback
    for label, raw, needles in (("not UTF-8", b"ok\n\xff\xfe\n", ("publish-deny.txt",)),
                                ("overflowing repeat count", b"a{99999999999999999999}\n", ("publish-deny.txt:1",))):
        main = toy("bad-deny")
        write(main, "config/publish-deny.txt", raw)
        write(main, "msg.txt", "clean\n")
        code, out = forge(main, "check-public", "--message", os.path.join(main, "msg.txt"))
        want("deny file %s = exit" % label, code, 2)
        has("deny file %s" % label, out, "forge check-public:", *needles)
        lacks("deny file %s" % label, out, "Traceback")


def main():
    public_cases()
    pinned_asset_cases()
    private_cases()
    worktree_cases()
    worktree_layout_cases()
    real_deny_cases()
    allowlist_cases()
    own_files_cases()
    range_cases()
    commit_cases()
    hook_cases()
    for msg in failures:
        print("FAIL", msg)
    for msg in notrun:
        print("NOT RUN", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
