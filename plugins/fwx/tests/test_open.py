#!/usr/bin/env python3
"""`fwx open FILE|URL`: shows a page to the owner through the opener the project's configuration names (`open.command`, an argv
list with `{url}` and `{path}`), else prints the command to paste.

Every case runs `bin/fwx open` in a toy repo whose `.claude/fwx.json` names the opener, with PATH set to ONE temp dir that
holds only the fakes of that case (the opener `viewer`, sentinel `xdg-open` and `open` that record a call, and a link to
`git`, which the configuration lookup needs), so no real program can run: a "program missing" case finds nothing behind
the dir. `fakes()` asserts that construction before each case. The `viewer` fake plays a list of canned exit codes, one
per call (the last one repeats), and records its argv.

Seen red before the configured opener existed (the first version of open.py hard-coded an IDE's CLI; 37 FAIL, first lines):
  FAIL: {url}: the viewer got the file URL: got [], want [['--show', 'file:///tmp/.../page.html']]
  FAIL: --json opened: opened, by, target: got (False, None, '/tmp/.../page.html'), want (True, 'viewer', '/tmp/.../page.html')
Before that, with no command at all, `fwx open` was an unknown command (exit 2).

Controls, each seen red with open.py changed in one place (176 checks each, first FAIL line):
  - nothing printed when the opener fails (no fallback):
      FAIL: opener exits 1: says NOT OPENED: got '', want a line starting 'NOT OPENED: '
  - the NOT OPENED line without the paste-ready line:
      FAIL: opener exits 1: the paste command is on its own line: got 1, want 2
  - `--print` still runs the configured command:
      FAIL: --print, good config: the viewer was not called: got [['file:///tmp/.../page.html']], want []
  - the table ignored:
      FAIL: {url}: the viewer got the file URL: got [], want [['--show', 'file:///tmp/.../page.html']]
  - run through a shell (argv joined):
      FAIL: a path with a space: the URL is percent-encoded and the path is not: got [[..., '/tmp/.../a', 'dir/my', 'page.html']]
  - no placeholder check:
      FAIL: no placeholder: exit 2: got 0, want 2
  - placeholders replaced only when they are a whole element:
      FAIL: {path}: the absolute path, and placeholders replaced inside an element: got [[..., 'x={url}|{path}']]
  - a program missing from PATH counted as opened:
      FAIL: opener missing: says NOT OPENED: got 'opened /tmp/.../page.html (by nosuchviewer)', want a line starting 'NOT OPENED: '
  - a non-zero exit counted as opened:
      FAIL: opener exits 1: says NOT OPENED: got 'opened /tmp/.../page.html (by viewer)', want a line starting 'NOT OPENED: '
  - no timeout:
      FAIL: a hanging opener: not opened: got True, want False
  - a string command accepted:
      FAIL: a string command: exit 2: got 0, want 2

Review round (CodeRabbit on the PR), seen red on the open.py before each fix (232 checks):
  - the Windows paste line for `https://example.com/" & echo INJECTED & rem "` broke out of its quotes, and a `%NAME%` expands
    inside them; a newline in a pasted line runs what follows:
      FAIL: windows: a double quote cannot be quoted in cmd.exe, no line is made: got 'start "" "https://example.com/" & echo INJECTED & rem ""', want None
      FAIL: windows: a %VAR% would expand even inside quotes, no line is made: got 'start "" "C:\\%USERPROFILE%\\x.html"', want None
      FAIL: linux: a newline in the target makes no line (pasted, it would run what follows): got "xdg-open 'https://x.test/a\ntouch pwned'", want None
    The POSIX line (`$(...)`, backticks, quotes) was already safe: shlex.quote, proved by running each line through /bin/sh
    (control: unquoted, `FAIL: linux line for 'https://example.com/$(touch pwned)' reaches the shell as one literal argument`).
  - placeholders replaced in two passes:
      FAIL: placeholder text inside the target https://example.com/{path} is not replaced again: got [['https://example.com/https://example.com/{path}', ...
  - undecodable opener output (text=True strict decoding):
      FAIL: an opener printing undecodable bytes, exit 0: no crash: got 1, want 0
  - second review round (250 checks), seen red before the fix:
      FAIL: windows: !NAME! expands under cmd /v:on, no line is made: got 'start "" "https://example.test/!OPEN_TARGET!"', want None
      FAIL: no safe line with --print --json: exit 2 as without --json: got 0, want 2
    and from the sweep of the same two classes: a backslash (fish reads it inside single quotes), a bidi or C1 control
    character, a `%NAME%` whose name holds a space.
  - explicit null is "not set", pinned (it already was; controls: raising on null fails `open null: exit 0: got 2, want 0`).
"""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
s = helpers.Suite()

SENTINELS = ("xdg-open", "open")
GIT = shutil.which("git")
NO_TABLE = "NOT OPENED: no opener configured (set open.command in the fwx configuration)"

VIEWER = """#!%(py)s
import json, os, sys, time
d = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
n = sum(1 for _ in open(os.path.join(d, "calls.log"))) - 1
answers = json.load(open(os.path.join(d, "answers.json")))
rc = answers[min(n, len(answers) - 1)]
if rc == "sleep":
    time.sleep(5)
    rc = 0
if rc in ("junk0", "junk1"):  # output that is not valid text in any locale
    sys.stdout.buffer.write(b"\\xff\\xfe junk\\n")
    sys.stderr.buffer.write(b"\\xff\\xfe junk\\n")
    sys.exit(int(rc[-1]))
sys.stderr.write("viewer says no\\n" if rc else "")
sys.exit(rc)
"""
SENTINEL = """#!%(py)s
import os, sys
d = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(d, "sentinel.log"), "a") as f:
    f.write(os.path.basename(sys.argv[0]) + " " + " ".join(sys.argv[1:]) + "\\n")
"""


def fakes(viewer=None):
    """A temp dir that is the whole PATH: the sentinels, git, and a `viewer` that exits with the next of `viewer` if given."""
    d = helpers.mkdtemp("fwx-open-path-")
    for name in SENTINELS:
        helpers.write(d, name, SENTINEL % {"py": sys.executable}, 0o755)
    os.symlink(GIT, os.path.join(d, "git"))
    if viewer is not None:
        helpers.write(d, "viewer", VIEWER % {"py": sys.executable}, 0o755)
        helpers.write(d, "answers.json", json.dumps(viewer))
    # by construction: PATH is this dir alone, and it holds nothing but the fakes of this case
    s.ok("path: only fakes", set(os.listdir(d)) <= {"viewer", "answers.json", "git", *SENTINELS}, str(os.listdir(d)))
    return d


def log(d, name):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f if ln.strip()]
    except OSError:
        return []


def calls(d):
    return [json.loads(ln) for ln in log(d, "calls.log")]


def repo(cfg):
    """A toy repo with `page.html`, `a dir/my page.html` and a `.claude/fwx.json` holding `cfg` (text, or a dict; None: no file)."""
    files = {"page.html": "<h1>hi</h1>", "a dir/my page.html": "<h1>hi</h1>"}
    if cfg is not None:
        files[".claude/fwx.json"] = cfg if isinstance(cfg, str) else json.dumps(dict({"schema": 1}, **cfg))
    return helpers.toy_repo(files)


def table(command):
    return {"open": {"command": command}}


def run(d, work, *args):
    return helpers.fwx(work, "open", *args, env={"PATH": d})


def one(label, cfg, viewer, *args, target="page.html"):
    """Run `fwx open target args` against config `cfg` with a viewer: (fake dir, repo, result)."""
    d, work = fakes(viewer), repo(cfg)
    return d, work, run(d, work, target, *args)


def not_opened(label, r):
    lines = r.stdout.splitlines()
    s.eq("%s: exit 0" % label, r.returncode, 0)
    s.ok("%s: says NOT OPENED" % label, bool(lines) and lines[0].startswith("NOT OPENED: "),
         "got %r, want a line starting 'NOT OPENED: '" % (lines[:1] and lines[0] or r.stdout))
    s.eq("%s: the paste command is on its own line" % label, len(lines), 2)
    s.ok("%s: that line is xdg-open or open or start with the path" % label,
         len(lines) == 2 and lines[1].split()[0] in ("xdg-open", "open", "start") and "page.html" in lines[1], r.stdout)
    return lines


def config_error(label, r, key):
    s.eq("%s: exit 2" % label, r.returncode, 2)
    s.eq("%s: one line on stderr" % label, len(r.stderr.strip().splitlines()), 1)
    s.ok("%s: names %s" % (label, key), key in r.stderr, r.stderr)


# --help
d, work = fakes(), repo(None)
r = run(d, work, "--help")
s.eq("--help: exit 0", r.returncode, 0)
s.ok("--help: names FILE|URL", "FILE" in r.stdout, r.stdout)

# {url}: a file becomes a file URL, the command runs without a shell, nothing is printed as NOT OPENED
d, work, r = one("url", table(["viewer", "--show", "{url}"]), [0])
page = os.path.join(work, "page.html")
s.eq("{url}: exit 0", r.returncode, 0)
s.eq("{url}: the viewer got the file URL", calls(d), [["--show", "file://" + page]])
s.ok("{url}: no NOT OPENED", "NOT OPENED" not in r.stdout + r.stderr, r.stdout)
s.ok("{url}: no system opener ran", log(d, "sentinel.log") == [], str(log(d, "sentinel.log")))

# {path}: the absolute path; both placeholders replaced inside one element, and in two
d, work, r = one("path", table(["viewer", "{path}", "x={url}|{path}"]), [0])
page = os.path.join(work, "page.html")
s.eq("{path}: exit 0", r.returncode, 0)
s.eq("{path}: the absolute path, and placeholders replaced inside an element", calls(d), [[page, "x=file://%s|%s" % (page, page)]])

# a path with a space becomes a valid file URL; {path} stays as it is
d, work = fakes([0]), repo(table(["viewer", "{url}", "{path}"]))
r = run(d, work, os.path.join("a dir", "my page.html"))
sp = os.path.join(work, "a dir", "my page.html")
s.eq("a path with a space: the URL is percent-encoded and the path is not", calls(d), [["file://" + sp.replace(" ", "%20"), sp]])

# a command from a shell string is never run by a shell: metacharacters stay in one argument
d, work, r = one("meta", table(["viewer", "{url}; touch pwned"]), [0])
s.eq("no shell: the whole element is one argument", [c[0].endswith("; touch pwned") for c in calls(d)], [True])
s.ok("no shell: nothing was created", not os.path.exists(os.path.join(work, "pwned")))

# --json on success
d, work, r = one("json", table(["viewer", "{url}"]), [0], "--json")
got = json.loads(r.stdout or "null") or {}
s.eq("--json opened: exit 0", r.returncode, 0)
s.eq("--json opened: opened, by, target", (got.get("opened"), got.get("by"), got.get("target")),
     (True, "viewer", os.path.join(work, "page.html")))
s.ok("--json opened: command names the target", "page.html" in (got.get("command") or ""), str(got))

# the opener exits 1: NOT OPENED with the reason, the paste line, exit 0
d, work, r = one("exit1", table(["viewer", "{url}"]), [1])
lines = not_opened("opener exits 1", r)
s.ok("opener exits 1: the reason says exit 1 and what it wrote", lines and "exit 1" in lines[0] and "viewer says no" in lines[0], r.stdout)
s.eq("opener exits 1: called once, no retry", len(calls(d)), 1)
s.ok("opener exits 1: no system opener ran", log(d, "sentinel.log") == [], str(log(d, "sentinel.log")))
d, work, r = one("exit1j", table(["viewer", "{url}"]), [1], "--json")
got = json.loads(r.stdout or "null") or {}
s.eq("--json not opened: opened false and by null", (got.get("opened"), got.get("by")), (False, None))
s.ok("--json not opened: command holds the path", "page.html" in (got.get("command") or ""), str(got))

# the program is not on PATH: NOT OPENED, the line, nothing called
d, work, r = one("missing", table(["nosuchviewer", "{url}"]), [0])
lines = not_opened("opener missing", r)
s.ok("opener missing: the reason names it", lines and "nosuchviewer" in lines[0], r.stdout)
s.eq("opener missing: the viewer on PATH was not called", calls(d), [])

# the opener hangs: NOT OPENED naming the timeout (the module's TIMEOUT_S is cut to 0.3 s, in this process, PATH set for it)
import importlib  # noqa: E402

try:
    mod = importlib.import_module("fwx.commands.open")
except Exception as e:  # noqa: BLE001
    mod = None
    s.ok("import fwx.commands.open", False, "%s: %s" % (type(e).__name__, e))
if mod and not hasattr(mod, "command_opener"):
    s.ok("fwx.commands.open.command_opener exists", False, "missing")
if mod and hasattr(mod, "command_opener"):
    old = os.environ.get("PATH")
    d = fakes(["sleep"])
    os.environ["PATH"] = d
    mod.TIMEOUT_S = 0.3
    t0 = time.time()
    try:
        res = mod.show("/srv/p.html", [("viewer", mod.command_opener(["viewer", "{url}"]))])
    finally:
        os.environ["PATH"] = old
    s.eq("a hanging opener: not opened", res["opened"], False)
    s.ok("a hanging opener: the reason says timed out", "timed out" in res["reason"], str(res))
    s.ok("a hanging opener: it did not wait for the sleep", time.time() - t0 < 4, "%.1fs" % (time.time() - t0))

# no `open` table: nothing is opened or called, the one fixed line, the paste line
for label, cfg in (("no table", {}), ("empty table", {"open": {}}), ("no config file", None)):
    d, work, r = one(label, cfg, [0])
    lines = not_opened("%s" % label, r)
    s.eq("%s: the reason is the fixed one" % label, lines[0] if lines else None, NO_TABLE)
    s.eq("%s: the viewer on PATH was not called" % label, calls(d), [])
    s.ok("%s: no system opener ran" % label, log(d, "sentinel.log") == [], str(log(d, "sentinel.log")))
# outside any git repository there is no configuration: the same
d, outside = fakes([0]), helpers.mkdtemp("fwx-open-nogit-")
helpers.write(outside, "page.html", "<h1>hi</h1>")
r = run(d, outside, "page.html")
s.eq("outside a repository: the fixed reason", r.stdout.splitlines()[:1], [NO_TABLE])
s.eq("outside a repository: exit 0", r.returncode, 0)

# bad shapes: exit 2, one line, the key named, nothing called
for label, cfg, key in (("a string command", table("viewer {url}"), "open.command"),
                        ("an empty list", table([]), "open.command"),
                        ("a number in the list", table(["viewer", 3, "{url}"]), "open.command"),
                        ("no placeholder", table(["viewer", "--fixed"]), "open.command"),
                        ("an open that is not a table", {"open": "viewer"}, "open"),
                        ("a command of null elements", table([None]), "open.command")):
    d, work, r = one(label, cfg, [0])
    config_error(label, r, key)
    s.eq("%s: no call" % label, calls(d), [])
d, work, r = one("bad json", '{"schema": 1, "open": ', [0])
s.eq("a file that is not JSON: exit 2", r.returncode, 2)
s.eq("a file that is not JSON: no call", calls(d), [])

# --print and --no-open: the configured viewer is not called, the config is not read, only the command is printed
for flag in ("--print", "--no-open"):
    for label, cfg in (("good config", table(["viewer", "{url}"])), ("bad config", table("x"))):
        d, work, r = one(label, cfg, [0], flag)
        s.eq("%s, %s: exit 0" % (flag, label), r.returncode, 0)
        s.eq("%s, %s: the viewer was not called" % (flag, label), calls(d), [])
        s.ok("%s, %s: no system opener ran" % (flag, label), log(d, "sentinel.log") == [], str(log(d, "sentinel.log")))
        s.eq("%s, %s: one line, the command" % (flag, label), len(r.stdout.splitlines()), 1)
        s.ok("%s, %s: no NOT OPENED line" % (flag, label), "NOT OPENED" not in r.stdout, r.stdout)
        s.ok("%s, %s: the command holds the path" % (flag, label), "page.html" in r.stdout, r.stdout)
d, work, r = one("printjson", table(["viewer", "{url}"]), [0], "--print", "--json")
got = json.loads(r.stdout or "null") or {}
s.eq("--print --json: opened false, by null", (got.get("opened"), got.get("by")), (False, None))

# a missing file: exit 2, one line, nothing called, before the configuration is looked at
d, work = fakes([0]), repo(table(["viewer", "{url}"]))
r = run(d, work, "nope.html")
s.eq("a missing file: exit 2", r.returncode, 2)
s.eq("a missing file: one line on stderr", len(r.stderr.strip().splitlines()), 1)
s.ok("a missing file: names the file", "nope.html" in r.stderr, r.stderr)
s.eq("a missing file: no call", calls(d), [])
s.eq("a missing file with --print: exit 2", run(d, work, "--print", "nope.html").returncode, 2)

# arguments: none, two, an unknown flag
for label, args in (("no argument", ()), ("two arguments", ("page.html", "page.html")), ("an unknown flag", ("page.html", "--frob"))):
    d, work = fakes([0]), repo(table(["viewer", "{url}"]))
    r = run(d, work, *args)
    s.eq("%s: exit 2" % label, r.returncode, 2)
    s.eq("%s: no call" % label, calls(d), [])

# URLs pass through unchanged: {url} and {path} are both the URL
for url in ("https://example.com/a?b=1&c=2#x", "http://example.org/", "file:///srv/x/index.html"):
    d, work = fakes([0]), repo(table(["viewer", "{url}", "{path}"]))
    r = run(d, work, url)
    s.eq("URL %s: exit 0" % url, r.returncode, 0)
    s.eq("URL %s: {url} and {path} are the URL, unchanged" % url, calls(d), [[url, url]])
    d, work = fakes(), repo(None)
    r = run(d, work, url, "--print")
    s.ok("URL %s: --print shows it unchanged" % url, url in r.stdout, r.stdout)
    s.eq("URL %s: --print exit 0" % url, r.returncode, 0)

# the core: openers are tried in order, the first that works wins; the command for each system
if mod and hasattr(mod, "paste_command"):
    seen = []

    def first(url, path):
        seen.append(("first", url))
        return False, "first said no"

    def second(url, path):
        seen.append(("second", url))
        return True, ""

    res = mod.show("/srv/p.html", [("first", first), ("second", second)])
    s.eq("openers are tried in order, the first that works wins", seen,
         [("first", "file:///srv/p.html"), ("second", "file:///srv/p.html")])
    s.eq("the winner is named", (res["opened"], res["by"]), (True, "second"))
    res = mod.show("/srv/p.html", [("first", first)])
    s.eq("no opener works: not opened", (res["opened"], res["by"]), (False, None))
    s.ok("no opener works: the reason says why", "first said no" in res["reason"], str(res))
    s.eq("no openers: not opened", mod.show("/srv/p.html", [])["opened"], False)
    for plat, word in (("linux", "xdg-open"), ("darwin", "open"), ("win32", "start")):
        s.ok("the command for %s starts with %s" % (plat, word),
             mod.paste_command("/srv/p.html", plat).startswith(word), mod.paste_command("/srv/p.html", plat))
    s.eq("the paste command quotes a space on linux", mod.paste_command("/srv/a b.html", "linux"), "xdg-open '/srv/a b.html'")
    s.eq("the windows command gives start an empty title", mod.paste_command("C:\\a b.html", "win32"), 'start "" "C:\\a b.html"')
    with open(mod.__file__, encoding="utf-8") as f:
        text = f.read().lower()
    s.ok("the module names no IDE", "orca" not in text, "orca is named in open.py")

# the target is never rescanned: a URL or a path that itself holds {path} or {url} reaches the opener unchanged
for url in ("https://example.com/{path}", "https://example.com/{url}/{path}"):
    d, work, r = one("rescan", table(["viewer", "{url}", "{path}", "u={url}"]), [0], target=url)
    s.eq("placeholder text inside the target %s is not replaced again" % url, calls(d), [[url, url, "u=" + url]])
d, work = fakes([0]), repo(table(["viewer", "{path}", "{url}"]))
helpers.write(work, "x{url}y.html", "<h1>hi</h1>")
r = run(d, work, "x{url}y.html")
tricky = os.path.join(work, "x{url}y.html")
s.eq("a file whose name holds {url}: both placeholders get the real values", calls(d), [[tricky, "file://" + tricky.replace("{", "%7B").replace("}", "%7D")]])

# an opener that prints bytes no locale decodes: the exit code still decides
for label, code, opened in (("exit 0", "junk0", True), ("exit 1", "junk1", False)):
    d, work, r = one("junk", table(["viewer", "{url}"]), [code], "--json")
    got = json.loads(r.stdout or "null") or {}
    s.eq("an opener printing undecodable bytes, %s: no crash" % label, r.returncode, 0)
    s.ok("an opener printing undecodable bytes, %s: no traceback" % label, "Traceback" not in r.stderr, r.stderr[-300:])
    s.eq("an opener printing undecodable bytes, %s: opened" % label, got.get("opened"), opened)

# an explicit null is the same as the key left out: no opener, no error (the generated file writes null for "not set")
for label, cfg in (("open null", {"open": None}), ("command null", {"open": {"command": None}})):
    d, work, r = one(label, cfg, [0])
    lines = not_opened(label, r)
    s.eq("%s: the fixed reason" % label, lines[0] if lines else None, NO_TABLE)
    s.eq("%s: no call" % label, calls(d), [])

# the line to paste is safe to paste, or not printed
if mod and hasattr(mod, "paste_command"):
    nasty = ["https://example.com/$(touch pwned)", "https://example.com/`touch pwned`", "https://example.com/'; touch pwned; '",
             'https://example.com/" ; touch pwned ; "', "/srv/a b/$HOME/it's.html", "https://example.com/a&c|d>e;f*?[x]~"]
    for target in nasty:
        for plat in ("linux", "darwin"):
            cmd = mod.paste_command(target, plat)
            word = "xdg-open" if plat == "linux" else "open"
            # what a POSIX shell makes of the line, with the opener swapped for the printf builtin: exactly one argument, the target
            r = subprocess.run(["/bin/sh", "-c", cmd.replace(word, "printf '%s\\n'", 1)], capture_output=True, text=True, cwd=work)
            s.eq("%s line for %r reaches the shell as one literal argument" % (plat, target), r.stdout, target + "\n")
    s.eq("no file was created by pasting them", os.path.exists(os.path.join(work, "pwned")), False)
    win = 'https://example.com/" & echo INJECTED & rem "'
    s.eq("windows: a double quote cannot be quoted in cmd.exe, no line is made", mod.paste_command(win, "win32"), None)
    s.eq("windows: a %VAR% would expand even inside quotes, no line is made", mod.paste_command("C:\\%USERPROFILE%\\x.html", "win32"), None)
    s.eq("windows: & inside the quotes is literal, the line is made", mod.paste_command("https://x.test/?a=1&b=2", "win32"),
         'start "" "https://x.test/?a=1&b=2"')
    s.eq("windows: a percent-encoded URL is fine", mod.paste_command("https://x.test/a%20b", "win32"), 'start "" "https://x.test/a%20b"')
    s.eq("windows: !NAME! expands under cmd /v:on, no line is made", mod.paste_command("https://example.test/!OPEN_TARGET!", "win32"), None)
    s.eq("windows: a lone ! is dropped under cmd /v:on, no line is made", mod.paste_command("https://example.test/a!b", "win32"), None)
    s.eq("windows: %NAME% with a space in the name is refused too", mod.paste_command("C:\\%USER NAME%\\x.html", "win32"), None)
    for plat in ("linux", "darwin"):
        s.eq("%s: a backslash is read differently inside single quotes by fish, no line is made" % plat,
             mod.paste_command("/srv/a\\b.html", plat), None)
    for plat in ("linux", "darwin", "win32"):
        for label, ch in (("a bidi override", "\u202e"), ("a C1 control (NEL)", "\x85")):
            s.eq("%s: %s in the target makes no line (the owner would read another target)" % (plat, label),
                 mod.paste_command("https://x.test/a" + ch + "b", plat), None)
    for plat in ("linux", "darwin", "win32"):
        s.eq("%s: a newline in the target makes no line (pasted, it would run what follows)" % plat,
             mod.paste_command("https://x.test/a\ntouch pwned", plat), None)
# through the command: a refused line is said on the NOT OPENED line, not printed, exit 0; --print has nothing to print, exit 2
d, work = fakes([1]), repo(table(["viewer", "{url}"]))
r = run(d, work, "https://x.test/a\nb")
s.eq("no safe line: exit 0", r.returncode, 0)
s.eq("no safe line: one line, NOT OPENED with both reasons", len(r.stdout.splitlines()), 1)
s.ok("no safe line: says so", r.stdout.startswith("NOT OPENED: ") and "no command to paste" in r.stdout, r.stdout)
r = run(d, work, "https://x.test/a\nb", "--print")
s.eq("no safe line with --print: exit 2", r.returncode, 2)
s.eq("no safe line with --print: nothing on stdout", r.stdout, "")
s.ok("no safe line with --print: one line on stderr", len(r.stderr.strip().splitlines()) == 1, r.stderr)
got = json.loads(run(d, work, "https://x.test/a\nb", "--json").stdout or "null") or {}
s.eq("no safe line with --json: command is null", got.get("command", "absent"), None)
for flag in ("--print", "--no-open"):
    r = run(d, work, "https://x.test/a\nb", flag, "--json")
    got = json.loads(r.stdout or "null") or {}
    s.eq("no safe line with %s --json: exit 2 as without --json" % flag, r.returncode, 2)
    s.eq("no safe line with %s --json: the JSON is still printed, command null" % flag, (got.get("opened"), got.get("command", "absent")), (False, None))
    s.eq("no safe line with %s --json: one line on stderr" % flag, len(r.stderr.strip().splitlines()), 1)
r = run(d, work, "https://x.test/a\nb", "--json")
s.eq("no safe line with --json and an opener that fails: exit 0", r.returncode, 0)

s.done()
