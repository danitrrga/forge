#!/usr/bin/env python3
"""`fwx open FILE|URL`: shows a page to the owner through the first opener that works, else prints the command to paste.

Every case runs `bin/fwx open` with PATH set to ONE temp dir that holds only the fakes of that case (`orca`, plus a
sentinel `xdg-open` and `open` that record a call), so no real program can run: a "program missing" case finds nothing
behind the dir. `fakes()` asserts that construction before each case. The `orca` fake plays a list of canned answers,
one per call (the last one repeats), and records its argv.

Seen red before the command existed (lib/fwx/commands/open.py absent; `fwx open` is an unknown command, exit 2):
  FAIL: orca answers ok: exit 0: got 2, want 0
  FAIL: orca answers ok: the fake got `tab create --url file://<path> --json`: got [], want [['tab', 'create', '--url', 'file:///tmp/.../page.html', '--json']]

Controls, each seen red with open.py changed in one place (111 checks each, first FAIL lines):
  - the `--worktree active` retry removed:
      FAIL: orca fails first, ok on the retry: two calls: got 1, want 2
  - no fallback: nothing printed when every opener failed:
      FAIL: orca fails twice (ok:false twice): says NOT OPENED: got '', want a line starting 'NOT OPENED: '
      FAIL: orca fails twice (ok:false twice): the command is on its own line: got 0, want 2
  - no fallback command: the NOT OPENED line without the paste-ready line:
      FAIL: orca fails twice (ok:false twice): the command is on its own line: got 1, want 2
  - `--print` still calls orca:
      FAIL: --print: the fake orca was not called: got 1, want 0
  - the fallback opens the page by itself (runs `xdg-open`):
      FAIL: orca fails twice (ok:false twice): no system opener ran: ['xdg-open file:///tmp/.../page.html']
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
s = helpers.Suite()

OK = ('{"id": "x", "ok": true, "result": {"browserPageId": "p1"}, "_meta": {}}', 0)
REFUSED = ('{"id": "x", "ok": false, "error": {"code": "browser_no_tab", "message": "no tab to attach to"}}', 0)
CRASH = ("", 3)  # exits non-zero with no JSON
SENTINELS = ("xdg-open", "open")

ORCA = """#!%(py)s
import json, os, sys
d = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
n = sum(1 for _ in open(os.path.join(d, "calls.log"))) - 1
answers = json.load(open(os.path.join(d, "answers.json")))
out, rc = answers[min(n, len(answers) - 1)]
sys.stdout.write(out)
sys.exit(rc)
"""
SENTINEL = """#!%(py)s
import os, sys
d = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(d, "sentinel.log"), "a") as f:
    f.write(os.path.basename(sys.argv[0]) + " " + " ".join(sys.argv[1:]) + "\\n")
"""


def fakes(orca=None):
    """A temp dir that is the whole PATH: the sentinels, and an `orca` answering `orca` (a list of (stdout, rc)) if given."""
    d = helpers.mkdtemp("fwx-open-path-")
    for name in SENTINELS:
        helpers.write(d, name, SENTINEL % {"py": sys.executable}, 0o755)
    if orca is not None:
        helpers.write(d, "orca", ORCA % {"py": sys.executable}, 0o755)
        helpers.write(d, "answers.json", json.dumps(orca))
    # by construction: PATH is this dir alone, and it holds nothing but the fakes of this case
    s.ok("path: only fakes", set(os.listdir(d)) <= {"orca", "answers.json", *SENTINELS}, str(os.listdir(d)))
    return d


def log(d, name):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f if ln.strip()]
    except OSError:
        return []


def calls(d):
    return [json.loads(ln) for ln in log(d, "calls.log")]


def run(d, *args, cwd=None):
    return helpers.fwx(cwd or d, "open", *args, env={"PATH": d})


work = helpers.mkdtemp("fwx-open-work-")
page = helpers.write(work, "page.html", "<h1>hi</h1>")
spaced = helpers.write(work, "a dir/my page.html", "<h1>hi</h1>")
URL = "file://" + page

# a plain `fwx open` needs no PATH: the first red of this file
r = run(fakes([OK]), "--help")
s.eq("--help: exit 0", r.returncode, 0)
s.ok("--help: names FILE|URL", "FILE" in r.stdout, r.stdout)

# orca answers ok: one call, the file URL, nothing printed as NOT OPENED
d = fakes([OK])
r = run(d, "page.html", cwd=work)
s.eq("orca answers ok: exit 0", r.returncode, 0)
s.eq("orca answers ok: the fake got `tab create --url file://<path> --json`", calls(d), [["tab", "create", "--url", URL, "--json"]])
s.ok("orca answers ok: no NOT OPENED", "NOT OPENED" not in r.stdout + r.stderr, r.stdout)
s.ok("orca answers ok: no system opener ran", log(d, "sentinel.log") == [], str(log(d, "sentinel.log")))

# a path with a space becomes a valid file URL
d = fakes([OK])
r = run(d, spaced)
s.eq("a path with a space: exit 0", r.returncode, 0)
s.eq("a path with a space: the URL is percent-encoded", [c[3] for c in calls(d)], ["file://" + spaced.replace(" ", "%20")])

# --json on success
d = fakes([OK])
r = run(d, page, "--json")
got = json.loads(r.stdout or "null")
s.eq("--json opened: exit 0", r.returncode, 0)
s.eq("--json opened: opened and by", (got or {}).get("opened"), True)
s.eq("--json opened: by", (got or {}).get("by"), "orca")
s.eq("--json opened: target", (got or {}).get("target"), page)
s.ok("--json opened: command names the target", page in ((got or {}).get("command") or ""), str(got))

# the first call fails (ok:false), the retry with --worktree active works
d = fakes([REFUSED, OK])
r = run(d, page)
s.eq("orca fails first, ok on the retry: exit 0", r.returncode, 0)
c = calls(d)
s.eq("orca fails first, ok on the retry: two calls", len(c), 2)
s.eq("orca fails first, ok on the retry: the retry adds --worktree active",
     c[1] if len(c) > 1 else None, ["tab", "create", "--url", URL, "--worktree", "active", "--json"])
s.ok("orca fails first, ok on the retry: no NOT OPENED", "NOT OPENED" not in r.stdout + r.stderr, r.stdout)
d = fakes([REFUSED, OK])
got = json.loads(run(d, page, "--json").stdout or "null") or {}
s.eq("orca fails first, ok on the retry: opened", got.get("opened"), True)

# orca fails both times: nothing opens, one NOT OPENED line with the reason, then the command; exit 0
for label, answers, reason in (("ok:false twice", [REFUSED, REFUSED], "browser_no_tab"),
                               ("exit 3 with no JSON", [CRASH, CRASH], "exit 3")):
    d = fakes(answers)
    r = run(d, page)
    lines = r.stdout.splitlines()
    s.eq("orca fails twice (%s): exit 0" % label, r.returncode, 0)
    s.eq("orca fails twice (%s): two calls" % label, len(calls(d)), 2)
    s.ok("orca fails twice (%s): says NOT OPENED" % label, bool(lines) and lines[0].startswith("NOT OPENED: "),
         "got %r, want a line starting 'NOT OPENED: '" % (lines[:1] and lines[0] or r.stdout))
    s.ok("orca fails twice (%s): the reason is named" % label, reason in (lines[0] if lines else ""), r.stdout)
    s.eq("orca fails twice (%s): the command is on its own line" % label, len(lines), 2)
    s.ok("orca fails twice (%s): the command is xdg-open or open or start with the path" % label,
         len(lines) == 2 and lines[1].split()[0] in ("xdg-open", "open", "start") and page in lines[1], r.stdout)
    s.ok("orca fails twice (%s): no system opener ran" % label, log(d, "sentinel.log") == [], str(log(d, "sentinel.log")))
d = fakes([REFUSED, REFUSED])
got = json.loads(run(d, page, "--json").stdout or "null") or {}
s.eq("orca fails twice, --json: opened false and by null", (got.get("opened"), got.get("by")), (False, None))
s.ok("orca fails twice, --json: command is a string with the path", page in (got.get("command") or ""), str(got))

# no orca on PATH: no call, NOT OPENED, the command
d = fakes()
r = run(d, page)
lines = r.stdout.splitlines()
s.eq("no orca: exit 0", r.returncode, 0)
s.ok("no orca: says NOT OPENED", bool(lines) and lines[0].startswith("NOT OPENED: "), r.stdout)
s.ok("no orca: the reason says there is no orca", "orca" in (lines[0] if lines else ""), r.stdout)
s.eq("no orca: two lines", len(lines), 2)
s.eq("no orca: no call", calls(d), [])
s.ok("no orca: no system opener ran", log(d, "sentinel.log") == [], str(log(d, "sentinel.log")))

# --print and --no-open: the orca on PATH is not called, only the command is printed
for flag in ("--print", "--no-open"):
    d = fakes([OK])
    r = run(d, page, flag)
    s.eq("%s: exit 0" % flag, r.returncode, 0)
    s.eq("%s: the fake orca was not called" % flag, len(calls(d)), 0)
    s.ok("%s: no system opener ran" % flag, log(d, "sentinel.log") == [], str(log(d, "sentinel.log")))
    s.eq("%s: one line, the command" % flag, len(r.stdout.splitlines()), 1)
    s.ok("%s: no NOT OPENED line" % flag, "NOT OPENED" not in r.stdout, r.stdout)
    s.ok("%s: the command holds the path" % flag, page in r.stdout, r.stdout)
d = fakes([OK])
got = json.loads(run(d, page, "--print", "--json").stdout or "null") or {}
s.eq("--print --json: opened false, by null", (got.get("opened"), got.get("by")), (False, None))

# a missing file: exit 2, one line, nothing called
d = fakes([OK])
r = run(d, "nope.html", cwd=work)
s.eq("a missing file: exit 2", r.returncode, 2)
s.eq("a missing file: one line on stderr", len(r.stderr.strip().splitlines()), 1)
s.ok("a missing file: names the file", "nope.html" in r.stderr, r.stderr)
s.eq("a missing file: no call", calls(d), [])
r = run(fakes([OK]), "--print", "nope.html", cwd=work)
s.eq("a missing file with --print: exit 2", r.returncode, 2)

# arguments: none, two, an unknown flag
for label, args in (("no argument", ()), ("two arguments", (page, page)), ("an unknown flag", (page, "--frob"))):
    d = fakes([OK])
    r = run(d, *args)
    s.eq("%s: exit 2" % label, r.returncode, 2)
    s.eq("%s: no call" % label, calls(d), [])

# URLs pass through unchanged, http(s) and file
for url in ("https://example.com/a?b=1&c=2#x", "http://example.org/", "file:///srv/x/index.html"):
    d = fakes([OK])
    r = run(d, url)
    s.eq("URL %s: exit 0" % url, r.returncode, 0)
    s.eq("URL %s: passed unchanged" % url, [c[3] for c in calls(d)], [url])
    d = fakes()
    r = run(d, url, "--print")
    s.ok("URL %s: --print shows it unchanged" % url, url in r.stdout, r.stdout)
    s.eq("URL %s: --print exit 0" % url, r.returncode, 0)

# a new opener is one function: the core names neither orca nor a system
import importlib  # noqa: E402

try:
    mod = importlib.import_module("fwx.commands.open")
except Exception as e:  # noqa: BLE001
    mod = None
    s.ok("import fwx.commands.open", False, "%s: %s" % (type(e).__name__, e))
if mod:
    seen = []

    def first(url):
        seen.append(("first", url))
        return False, "first said no"

    def second(url):
        seen.append(("second", url))
        return True, ""

    res = mod.show("https://example.com/", [("first", first), ("second", second)])
    s.eq("openers are tried in order, the first that works wins", seen,
         [("first", "https://example.com/"), ("second", "https://example.com/")])
    s.eq("the winner is named", (res["opened"], res["by"]), (True, "second"))
    res = mod.show("https://example.com/", [("first", first)])
    s.eq("no opener works: not opened", (res["opened"], res["by"]), (False, None))
    s.ok("no opener works: the reason says why", "first said no" in res["reason"], str(res))
    res = mod.show("https://example.com/", [], do_open=False)
    s.eq("no openers and nothing asked: not opened", res["opened"], False)
    for plat, word in (("linux", "xdg-open"), ("darwin", "open"), ("win32", "start")):
        s.ok("the command for %s starts with %s" % (plat, word),
             mod.paste_command("/srv/p.html", plat).startswith(word), mod.paste_command("/srv/p.html", plat))
    s.eq("the paste command quotes a space on linux", mod.paste_command("/srv/a b.html", "linux"), "xdg-open '/srv/a b.html'")
    s.eq("the windows command gives start an empty title", mod.paste_command("C:\\a b.html", "win32"), 'start "" "C:\\a b.html"')
    names = [n for n, _ in mod.OPENERS]
    s.ok("the default list is not empty", len(names) >= 1, str(names))

s.done()
