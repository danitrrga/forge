#!/usr/bin/env python3
"""forge/lib.py decides which project a session writes, so a wrong answer rewrites someone
else's config: until a fix every session start in forge or in a second project rewrote all 19 projects and
hot-reloaded a frozen project's sessions. This builds profiles, a nested profile, a linked worktree and
an unregistered repo in a temp dir and checks every answer, then the lock.

The None cases are the negative control: a resolver that always finds the nearest profile
would hand the worktree and the unregistered repo to a real project. The worktree cases were
seen to fail by mutation: without `if linked: return None` resolve_project(app-wt/src) is
'wtsrc', and with context's may_write guard replaced by `if False:` an --apply from a worktree
scopes to every project: "context worktree --apply [] = (None, True), want (set(), False)"
(re-seen when hook_scope folded into context).

may_write() is checked against a temp HOME's settings.json naming no checkout, this one, one no
longer on disk, another, two, or holding bad JSON. Each refusal was seen to fail by mutation: without the installed-root comparison, "names another checkout (a copy) =
(True, ''), want (False, 'forge: ... is not the checkout this machine runs (...) -- nothing
written')" and "scope --apply from a copy = (None, True), want (set(), False)" (context's, re-seen
again); with bad JSON read as None,
"settings.json unparseable refuses = (True, False)"; without the two-checkouts refusal, "settings.json
two different checkouts refuses = (True, False)"; keeping a dead entry, "names a checkout no longer
on disk (forge relocated) = (False, ...)".

require_write() is may_write() as an exit 1, for the scripts that must not fall through to a
dry-run. Seen failing: before it existed, "AttributeError: module 'forge.lib' has no
attribute 'require_write'"; printing and returning as apply_allowed does, "require_write from a
copy = 'returned', want 'forge: ...'"; exiting always, "require_write from this checkout = '',
want 'returned'". The copy refusal gained "; apply from <installed>": before, "names another
checkout (a copy) = (False, '... -- nothing written'), want (False, '... -- nothing written; apply
from .../installed')".

A toy HOME only writes a toy world. Before that rule, "a toy HOME, one profile outside = (True,
'')"; with the real-HOME exemption removed, "the real HOME with no forge entry, profiles anywhere
(a fresh machine) = (False, 'forge: HOME is a sandbox ...')". The session-start case feeds cli the
real refusal from every step it runs: before the pattern it "showed ''"; without the deduplication it
showed the refusal four times, and since the app session runs two steps twice, as
"agent config: forge: cannot tell ... | system doc: forge: cannot tell ...".

Seen failing before their fixes (round 2): "context ('--project', 'app', '--project',
'dev') = ({'app'}, False), want the exit 'forge: --project given more than once'"; "profiles() on an
unreadable directory = {}, want PermissionError"; "session start from the cwd .../dev/app gave its
steps CLAUDE_PROJECT_DIR [None, None, None, None]". With the flag-as-name guard deleted, "context
('--project', '--apply') exited with 'forge: unknown project: --apply (...)', want 'unknown project:
(none given) (...)'" -- the old substring check passed that mutation. Both scope messages were
re-seen by mutation on when hook_scope folded into context."""
import argparse
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import cli, lib  # noqa: E402
import sandbox  # noqa: E402
from sandbox import git  # noqa: E402
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # lib.ROOT is a toy by the time a late part runs
FIXTURES = os.path.join(REPO, "tests", "fixtures", "config")


def checker():
    """(want, failures): want(label, got, expected) records one case, and a failure when they differ."""
    failures, n = [], [0]

    def want(label, got, expected):
        n[0] += 1
        if got != expected:
            failures.append("%s = %r, want %r" % (label, got, expected))
    want.count = lambda: n[0]
    return want, failures


def raised(fn, *a, **k):
    """fn's result, or ('raised', the exception type's name, its text)."""
    try:
        return fn(*a, **k)
    except Exception as e:
        return ("raised", type(e).__name__, str(e))


def read_cases(tmp):
    """read_json, read_owned, Unreadable, dumps and short (design §2; S1 items 3, 4 and 8).

    read_json is the old lenient load(), warning line included: S2 swaps it in with the dry-run
    byte-identical. Seen failing on a mutated copy: with the warning's two leading
    spaces dropped, "read_json on bad JSON = ({}, '! could not read .../bad.json: Expecting property
    name ...'), want ({}, '  ! could not read .../bad.json: ...')". read_owned's `missing` is shared
    between calls, so it is handed back as a copy: returning it as is, "read_owned missing, after a
    caller mutated the last one = {'mutated': 1}, want {}". Unreadable subclassing Exception instead
    of ValueError, which may_write() catches: "read_owned of bad JSON = (False, ...), want (True,
    ...)". dumps is the comparison form and must be the write_atomic bytes; with indent=3, "dumps(sample)
    = '{\\n   \"b\": [...', want '{\\n  \"b\": [...'". short() reads lib.HOME when called, which the
    tests patch; with the real home baked in, "short(HOME/x) = '.../home/user', want '~/x'"."""
    want, failures = checker()
    d = os.path.join(tmp, "read")
    os.makedirs(d)
    bad, lst, missing = (os.path.join(d, n) for n in ("bad.json", "list.json", "missing.json"))
    with open(bad, "w") as f:
        f.write("{not json")
    with open(lst, "w") as f:
        f.write("[1]")
    parse_err = "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"

    def quiet_read(*a, **k):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            got = raised(lib.read_json, *a, **k)
        return got, out.getvalue()
    want("read_json on bad JSON", quiet_read(bad), ({}, "  ! could not read %s: %s\n" % (bad, parse_err)))
    want("read_json on bad JSON, quiet", quiet_read(bad, quiet=True), ({}, ""))
    want("read_json on bad JSON with a default", quiet_read(bad, {"d": 1}, quiet=True), ({"d": 1}, ""))
    want("read_json missing", quiet_read(missing), ({}, ""))
    want("read_json missing with a default", quiet_read(missing, []), ([], ""))
    want("read_json of a list", quiet_read(lst), ([1], ""))

    got = lib.read_owned(missing)
    got["mutated"] = 1
    want("read_owned missing, after a caller mutated the last one", lib.read_owned(missing), {})
    want("read_owned missing=None", lib.read_owned(missing, missing=None), None)
    obj = os.path.join(d, "obj.json")
    with open(obj, "w") as f:
        f.write('{"k": [1]}')
    want("read_owned of an object", lib.read_owned(obj), {"k": [1]})
    for label, p, reason in (("bad JSON", bad, parse_err), ("a list", lst, "top level is list, not an object"),
                             ("a directory", d, "[Errno 21] Is a directory: '%s'" % d)):
        try:
            got = lib.read_owned(p)
        except lib.Unreadable as e:
            got = (isinstance(e, ValueError), e.path, e.reason)
        want("read_owned of %s" % label, got, (True, p, reason))

    sample = {"b": [1, {"ü": "ñ"}], "a": None, "e": {}}
    # Checked once against the old write_atomic, extracted with ast from sync_agent_config.py at
    # 9bccdb7: b'{\n  "b": [\n    1,\n    {\n      "\xc3\xbc": "\xc3\xb1"\n    }\n  ],\n  "a": null,\n  "e": {}\n}'
    want("dumps(sample)", lib.dumps(sample), '{\n  "b": [\n    1,\n    {\n      "ü": "ñ"\n    }\n  ],\n  "a": null,\n  "e": {}\n}')
    want("short(HOME/x)", lib.short(os.path.join(lib.HOME, "x")), "~/x")
    want("short(elsewhere)", lib.short("/elsewhere/x"), "/elsewhere/x")
    return failures, want.count()


def profile_type_cases(tmp):
    """profile_error: the one place that knows each profile field's type (PROFILE_FIELDS). Red
    before it existed: "AttributeError: module 'forge.lib' has no attribute
    'profile_error'". A present field must have its type, null included; a field the table does
    not name is not checked; a bool is not an int and an int is not a bool."""
    want, failures = checker()
    ok = {"project": "x", "project_path": "/p", "servers": ["a"], "skills_keep": ["*"], "plugins_keep": [],
          "env": {"K": "v"}, "permissions": {"allow": ["Bash(ls:*)"]}, "frozen": True,
          "writes_tracked_files": False, "enableAllProjectMcpServers": False,
          "mcpjson_approved": [], "mcpjson_disabled": ["s"], "hooks": {"E": []}, "command_guard": True, "_doc": 1, "some_unknown_key": 5}
    for label, prof, expected in (
            ("an empty profile", {}, None),
            ("every field well typed, unknown fields ignored", ok, None),
            ("a JSON list", [1], "the profile is not a JSON object"),
            ("null", None, "the profile is not a JSON object"),
            ("servers null", {"servers": None}, "servers is not a list of strings"),
            ("servers [5]", {"servers": [5]}, "servers is not a list of strings"),
            ("skills_keep a string", {"skills_keep": "*"}, "skills_keep is not a list of strings"),
            ("project_path 5", {"project_path": 5}, "project_path is not a string"),
            ("frozen 1", {"frozen": 1}, "frozen is not a boolean"),
            ("env a list", {"env": []}, "env is not a JSON object of strings"),
            ("an env value 1", {"env": {"K": 1}}, "env is not a JSON object of strings"),
            ("permissions a list", {"permissions": []}, "permissions is not a JSON object"),
            ("hooks a list", {"hooks": []}, "hooks is not a JSON object"),
            ("hooks null", {"hooks": None}, "hooks is not a JSON object"),
            ("command_guard 1", {"command_guard": 1}, "command_guard is not a boolean"),
            ("command_guard null", {"command_guard": None}, "command_guard is not a boolean"),
            ("command_guard \"true\"", {"command_guard": "true"}, "command_guard is not a boolean"),
            # Round 10: a worktree_guard object whose "on" is not a boolean read as off, the doctor PASSed.
            # Red before: "profile_error(worktree_guard.on "true") = None, want 'worktree_guard.on is not a
            # boolean'" (and 1, null); "profile_error(worktree_guard true, no project) = None, want 'project
            # is missing, and worktree_guard is on (its command names the project)'" (7 of 274 failed).
            ("worktree_guard.on \"true\"", {"worktree_guard": {"on": "true"}}, "worktree_guard.on is not a boolean"),
            ("worktree_guard.on 1", {"worktree_guard": {"on": 1}}, "worktree_guard.on is not a boolean"),
            ("worktree_guard.on null", {"worktree_guard": {"on": None}}, "worktree_guard.on is not a boolean"),
            ("worktree_guard.on false", {"worktree_guard": {"on": False, "worktree_dirs": []}}, None),
            ("worktree_guard {} with a project", {"project": "x", "worktree_guard": {}}, None),
            # Round 10: no "project" and a guard on made sync write `--project None`.
            ("command_guard on, no project", {"command_guard": True}, "project is missing, and command_guard is on (its command names the project)"),
            ("worktree_guard true, no project", {"worktree_guard": True}, "project is missing, and worktree_guard is on (its command names the project)"),
            ("worktree_guard {}, no project", {"worktree_guard": {}}, "project is missing, and worktree_guard is on (its command names the project)"),
            ("worktree_guard on, project \"\"", {"project": "", "worktree_guard": True}, "project is missing, and worktree_guard is on (its command names the project)"),
            ("guards off, no project", {"command_guard": False, "worktree_guard": {"on": False}}, None),
            ("a guard on, project named", {"project": "x", "command_guard": True, "worktree_guard": True}, None)):
        want("profile_error(%s)" % label, raised(lambda: lib.profile_error(prof)), expected)

    # profiles() leaves out a profile of the wrong shape and names it in `skipped`, as it does an
    # unreadable one, so every caller is protected and not only forge/sync.py. Red before:
    # "profiles() beside a project_path 5 = ({'ok': {...}, 'pp5': {...}}, []), want
    # ({'ok': ...}, [('pp5.claude.json', 'project_path is not a string')])" and "resolve_project
    # beside a project_path 5 = ('raised', 'TypeError', 'expected str, bytes or os.PathLike
    # object, not int')".
    d = os.path.join(tmp, "typed-profiles")
    os.makedirs(d)
    for n, text in (("ok", '{"project_path": "/x"}'), ("pp5", '{"project_path": 5}')):
        with open(os.path.join(d, n + ".claude.json"), "w") as f:
            f.write(text)
    real_profiles, lib.PROFILES = lib.PROFILES, d
    skipped = []
    got = raised(lib.profiles, skipped)
    want("profiles() beside a project_path 5", (got, skipped),
         ({"ok": {"project_path": "/x"}}, [("pp5.claude.json", "project_path is not a string")]))
    want("resolve_project beside a project_path 5", raised(lib.resolve_project, "/x/sub"), "ok")
    lib.PROFILES = real_profiles
    return failures, want.count()


RACER = """import os, sys, time
sys.path.insert(0, sys.argv[1])
from forge import lib
p, tag, go = sys.argv[2:5]
while not os.path.exists(go):
    time.sleep(0.001)
for i in range(200):
    lib.write_text(p, tag * 300000 + str(i), mode=0o600)
"""


def holds_cases(tmp):
    """holds(path, text): whether `path` already holds `text`, byte for byte. It is write_text's
    unchanged-content check and forge/mcp.py's for .codex/config.toml; the latter read with
    universal newlines and raised on a file that is not UTF-8. Red before it existed:
    "AttributeError: module 'forge.lib' has no attribute 'holds'". Read with universal newlines
    (newline="" removed), "CRLF against LF text = True, want False", and write_text's byte-exact
    cases, which now go through holds, stay red: "a CRLF target is rewritten to the LF text =
    b'a\\r\\nb', want b'a\\nb'", the lone-CR one and "CRLF text over the same CRLF bytes keeps the
    mtime"."""
    want, failures = checker()
    d = os.path.join(tmp, "holds")
    os.makedirs(os.path.join(d, "a-directory"))

    def put(name, data):
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    holds = lambda *a: raised(lib.holds, *a)
    want("identical bytes", holds(put("same", "a\nbü".encode()), "a\nbü"), True)
    want("CRLF against LF text", holds(put("crlf", b"a\r\nb"), "a\nb"), False)
    want("a missing file", holds(os.path.join(d, "missing"), "a"), False)
    want("a file that is not UTF-8", holds(put("latin", b"\xff"), "ÿ"), False)
    want("a directory", holds(os.path.join(d, "a-directory"), ""), False)
    return failures, want.count()


def write_cases(tmp):
    """write_text and write_json (S1 items 1 and 2): write_atomic_text verbatim, with the .bak made
    optional and four additions -- no temp file left by any exception, fsync, mode='keep', and a
    check() that can refuse the temp file before it is renamed into place.

    Each was seen failing on a mutated copy of lib.py, and the red is quoted by its
    case. Where a case needs the old behaviour for its control, the mutation restores it."""
    want, failures = checker()
    d = os.path.join(tmp, "write")
    os.makedirs(d)
    mask = os.umask(0o022)
    mode_of = lambda p: os.stat(p).st_mode & 0o777
    leftovers = lambda: sorted(n for n in os.listdir(d) if ".tmp" in n)

    def put(p, text, mode=None):
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        if mode is not None:
            os.chmod(p, mode)

    def body(p):
        with open(p, encoding="utf-8") as f:
            return f.read()

    # Unchanged content is not rewritten. Red with the skip removed: "unchanged content keeps the
    # mtime = 1790751939745779867, want 1000000000000000000" (the rewrite's own mtime).
    p = os.path.join(d, "same.txt")
    lib.write_text(p, "a", mode=0o600)
    os.utime(p, ns=(10 ** 18, 10 ** 18))
    lib.write_text(p, "a", mode=0o600)
    want("unchanged content keeps the mtime", os.stat(p).st_mtime_ns, 10 ** 18)

    # A target that is not UTF-8 is replaced, not a crash: the unchanged-content check read it as
    # text and caught only OSError. Red before the fix: "a target that is not UTF-8 = (('raised',
    # 'UnicodeDecodeError', ...), ...), want (None, 'b')" -- verbatim from write_atomic_text.
    latin = os.path.join(d, "latin1.txt")
    with open(latin, "wb") as f:
        f.write(b"caf\xe9")
    got = raised(lib.write_text, latin, "b")
    want("a target that is not UTF-8", (got if got is None else got[:2], body(latin) if got is None else None), (None, "b"))

    # The unchanged-content check is byte-exact: read with universal newlines, a target holding
    # CRLF (or a lone CR) compared equal to the LF text and was never rewritten, so `path` did not
    # hold `text`. Red before the fix: "a CRLF target is rewritten to the LF text =
    # b'a\r\nb', want b'a\nb'" and "a lone-CR target is rewritten to the LF text = b'a\rb', want
    # b'a\nb'". The control, text that is itself CRLF over the same bytes, is skipped: it was red
    # too, the same defect's other face (read as 'a\nb', never equal, rewritten every run): "CRLF
    # text over the same CRLF bytes keeps the mtime = (b'a\r\nb', 1790762008140344091), want
    # (b'a\r\nb', 1000000000000000000)".
    raw = lambda p: open(p, "rb").read()
    for label, old in (("a CRLF target", b"a\r\nb"), ("a lone-CR target", b"a\rb")):
        crlf = os.path.join(d, "crlf.txt")
        with open(crlf, "wb") as f:
            f.write(old)
        lib.write_text(crlf, "a\nb")
        want("%s is rewritten to the LF text" % label, raw(crlf), b"a\nb")
    with open(crlf, "wb") as f:
        f.write(b"a\r\nb")
    os.utime(crlf, ns=(10 ** 18, 10 ** 18))
    lib.write_text(crlf, "a\r\nb")
    want("CRLF text over the same CRLF bytes keeps the mtime", (raw(crlf), os.stat(crlf).st_mtime_ns), (b"a\r\nb", 10 ** 18))
    lib.write_text(p, "a", mode=0o640)
    want("unchanged content, another mode: the mode is applied", mode_of(p), 0o640)

    # A secret over a loose file: the file and its once-ever .bak are 0600 (~/.claude.json.bak was
    # 644 once). Red with the .bak created at the umask default and never chmodded: "mode
    # 0600 over 0644: the .bak = 420, want 384". A loose .bak beside current content is tightened
    # too; red with that block skipped: "a loose .bak beside current content = 420, want 384".
    p = os.path.join(d, "secret.json")
    put(p, "old", 0o644)
    lib.write_text(p, "new", mode=0o600, backup=True)
    want("mode 0600 over 0644: the file", (body(p), mode_of(p)), ("new", 0o600))
    want("mode 0600 over 0644: the .bak", mode_of(p + ".bak"), 0o600)
    want("mode 0600 over 0644: the .bak holds the old text", body(p + ".bak"), "old")
    lib.write_text(p, "newer", mode=0o600, backup=True)
    want("the .bak is once-ever", body(p + ".bak"), "old")
    os.chmod(p + ".bak", 0o644)
    lib.write_text(p, "newer", mode=0o600, backup=True)
    want("a loose .bak beside current content", mode_of(p + ".bak"), 0o600)
    # A .bak that is a link is someone else's file: never copied to or chmodded through. Red with
    # the islink test dropped: "a linked .bak's target = ('theirs', 384), want ('theirs', 420)".
    other = os.path.join(d, "someone-elses")
    put(other, "theirs", 0o644)
    p = os.path.join(d, "linked-bak.json")
    put(p, "old", 0o644)
    os.symlink(other, p + ".bak")
    lib.write_text(p, "new", mode=0o600, backup=True)
    want("a linked .bak's target", (body(other), mode_of(other)), ("theirs", 0o644))

    # backup=False, the default, makes no .bak. Red with `backup` ignored (the old always-on copy):
    # "backup=False makes no .bak = True, want False".
    p = os.path.join(d, "nobak.txt")
    put(p, "old")
    lib.write_text(p, "new")
    want("backup=False makes no .bak", os.path.lexists(p + ".bak"), False)

    # A symlinked path: its target is written and the link kept. Red without the realpath: "a
    # symlinked path: link kept, target written = (False, 'old'), want (True, 'new')".
    target = os.path.join(d, "real.txt")
    put(target, "old")
    p = os.path.join(d, "link.txt")
    os.symlink("real.txt", p)
    lib.write_text(p, "new")
    want("a symlinked path: link kept, target written", (os.path.islink(p), body(target)), (True, "new"))

    # A replace that fails once lands through the first retry name. Red with the retries removed:
    # "a replace failing once = (('raised', 'OSError', 'write_text: could not atomically replace
    # .../flaky.txt (...): None'), None), want (None, 'v')".
    p = os.path.join(d, "flaky.txt")
    calls, real_replace = [], os.replace

    def flaky(src, dst):
        calls.append(os.path.basename(src))
        if len(calls) == 1:
            raise OSError(18, "Invalid cross-device link")
        return real_replace(src, dst)
    os.replace = flaky
    try:
        got = raised(lib.write_text, p, "v")
    finally:
        os.replace = real_replace
    pid = os.getpid()
    want("a replace failing once", (got, body(p) if os.path.exists(p) else None), (None, "v"))
    want("a replace failing once: the names tried", calls, ["flaky.txt.tmp.%d" % pid, "flaky.txt.tmp0.%d" % pid])
    want("a replace failing once: temp files left", leftovers(), [])

    # A write that raises leaves no temp file and the old text: a lone surrogate cannot be encoded.
    # Red with the cleanup loop emptied (the old code had none around the first write): "a raising
    # write: temp files left = [..., 'raising.txt.tmp.<pid>'], want []".
    p = os.path.join(d, "raising.txt")
    put(p, "old")
    got = raised(lib.write_text, p, "bad \udc80")
    want("a raising write", (got[:2], body(p)), (("raised", "UnicodeEncodeError"), "old"))
    want("a raising write: temp files left", leftovers(), [])

    # check(tmp) sees the temp file before the rename and refuses it by raising. Red with check
    # ignored: "check() raising leaves the target unchanged = (None, 'new'), want (('raised',
    # 'ValueError', 'refused'), 'old')".
    p = os.path.join(d, "checked.txt")
    put(p, "old")
    seen = []

    def refuse(t):
        seen.append((body(t), mode_of(t)))
        raise ValueError("refused")
    got = raised(lib.write_text, p, "new", mode=0o600, check=refuse)
    want("check() raising leaves the target unchanged", (got, body(p)), (("raised", "ValueError", "refused"), "old"))
    want("check() saw the temp file's text and mode", seen, [("new", 0o600)])
    want("check() raising: temp files left", leftovers(), [])
    lib.write_text(p, "new", check=lambda t: None)
    want("check() passing", body(p), "new")

    # mode='keep' is rotate_secret's rule: the target's own mode, 0600 when there is none. Red
    # with 'keep' read as None: "mode='keep' preserves 0600 = 420, want 384".
    p = os.path.join(d, "kept.txt")
    put(p, "old", 0o600)
    lib.write_text(p, "new", mode="keep")
    want("mode='keep' preserves 0600", mode_of(p), 0o600)
    put(p, "old", 0o640)
    lib.write_text(p, "new", mode="keep", backup=True)
    want("mode='keep' preserves 0640, .bak too", (mode_of(p), mode_of(p + ".bak")), (0o640, 0o640))
    lib.write_text(os.path.join(d, "kept-new.txt"), "x", mode="keep")
    want("mode='keep' on a new file", mode_of(os.path.join(d, "kept-new.txt")), 0o600)

    # fsync=True syncs the file before the rename and its directory after. Red with the directory
    # sync dropped: "fsync=True syncs = ['file'], want ['file', 'dir']".
    synced, real_fsync = [], os.fsync

    def spy(fd):
        synced.append("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        return real_fsync(fd)
    os.fsync = spy
    try:
        lib.write_text(os.path.join(d, "synced.txt"), "x", fsync=True)
        want("fsync=True syncs", synced, ["file", "dir"])
        del synced[:]
        lib.write_text(os.path.join(d, "unsynced.txt"), "x")
        want("fsync=False syncs", synced, [])
    finally:
        os.fsync = real_fsync

    # write_json's bytes are the old write_atomic's (checked once against it, as in read_cases).
    # Red with indent=3: "write_json bytes = b'{\n   \"b\": ...', want b'{\n  \"b\": ...'".
    sample = {"b": [1, {"ü": "ñ"}], "a": None, "e": {}}
    old = b'{\n  "b": [\n    1,\n    {\n      "\xc3\xbc": "\xc3\xb1"\n    }\n  ],\n  "a": null,\n  "e": {}\n}'
    p = os.path.join(d, "doc.json")
    lib.write_json(p, sample)
    with open(p, "rb") as f:
        want("write_json bytes", f.read(), old)
    lib.write_json(p, sample, newline=True, ensure_ascii=True)
    with open(p, "rb") as f:
        want("write_json newline, ensure_ascii", f.read(), old.replace(b"\xc3\xbc", b"\\u00fc").replace(b"\xc3\xb1", b"\\u00f1") + b"\n")

    # Two processes writing one path 200 times each, as two SessionStart runs racing did: each
    # write lands whole, and neither leaves a temp file. Red with one fixed ".tmp" name (the
    # old code), in 5 runs of 5: "two writers: exit codes = ([0, 1], [[], ["FileNotFoundError:
    # [Errno 2] No such file or directory: '.../raced.txt.tmp'"]]), want ([0, 0], [[], []])". The
    # payload is large and both wait for `go`, so the loops overlap: two fresh interpreters would
    # otherwise finish 200 small writes one after the other, and the red would never fire.
    p, go = os.path.join(d, "raced.txt"), os.path.join(d, "go")
    here = os.path.dirname(os.path.dirname(os.path.abspath(lib.__file__)))
    racers = [subprocess.Popen([sys.executable, "-c", RACER, here, p, tag, go], stderr=subprocess.PIPE, text=True)
              for tag in "AB"]
    open(go, "w").close()
    errs = [r.communicate()[1] for r in racers]
    want("two writers: exit codes", ([r.returncode for r in racers], [e.strip().splitlines()[-1:] for e in errs]),
         ([0, 0], [[], []]))
    last = body(p)
    want("two writers: the file holds one whole write",
         (len(last) > 300000 and last[0] in "AB" and last[:300000] == last[0] * 300000 and last[300000:].isdigit()), True)
    want("two writers: temp files left", leftovers(), [])
    os.umask(mask)
    return failures, want.count()


def git_cases(tmp):
    """in_git_repo, git_ignores, git_tracks and gitignore_has (S1 item 5), sync_agent_config's
    copies moved. git runs with no user or system config: a global core.excludesFile would decide
    what check-ignore says. Seen failing on a mutated copy, each red quoted by its case."""
    want, failures = checker()
    saved = {k: os.environ.get(k) for k in sandbox.GIT_ENV}
    os.environ.update(sandbox.GIT_ENV)
    repo, plain = os.path.join(tmp, "gitrepo"), os.path.join(tmp, "plain", "sub")
    os.makedirs(os.path.join(repo, "tracked"))
    os.makedirs(os.path.join(repo, "other"))
    os.makedirs(plain)
    git(repo, "init", "-q")
    with open(os.path.join(repo, ".gitignore"), "w") as f:
        f.write("*.log\n.codex/\n.agents\n")
    open(os.path.join(repo, "tracked", "a.txt"), "w").close()
    open(os.path.join(repo, "other", "b.txt"), "w").close()
    git(repo, "add", ".gitignore", "tracked/a.txt")
    git(repo, "commit", "-q", "-m", "x")
    want("the temp dir is under no repository (else the plain cases prove nothing)", lib.git_dir(plain)[0], None)

    # The walk, not a git fork per project. Red with the answer inverted: "in_git_repo(repo/other) = False, want True".
    want("in_git_repo(repo/other)", lib.in_git_repo(os.path.join(repo, "other")), True)
    want("in_git_repo(plain)", lib.in_git_repo(plain), False)
    # Red with the return code ignored: "git_ignores(repo, x.txt) = True, want False".
    want("git_ignores(repo, x.log)", lib.git_ignores(repo, "x.log"), True)
    want("git_ignores(repo, x.txt)", lib.git_ignores(repo, "x.txt"), False)
    want("git_ignores(plain, x.log)", lib.git_ignores(plain, "x.log"), False)
    # git_tracks fails closed: where git cannot answer, the directory is treated as tracked and
    # nothing is touched. Red with a failed git read as "nothing tracked": "git_tracks(plain, sub)
    # = False, want True".
    want("git_tracks(repo, tracked)", lib.git_tracks(repo, "tracked"), True)
    want("git_tracks(repo, other)", lib.git_tracks(repo, "other"), False)
    want("git_tracks(plain, sub)", lib.git_tracks(plain, "sub"), True)
    want("git_tracks(a missing dir, x)", lib.git_tracks(os.path.join(tmp, "missing"), "x"), True)

    # gitignore_has reads the line itself; `.agents` counts for `.agents/`. Red with the
    # slash-less form dropped: "gitignore_has(repo, .agents/) = False, want True".
    want("gitignore_has(repo, .codex/)", lib.gitignore_has(repo, ".codex/"), True)
    want("gitignore_has(repo, .agents/)", lib.gitignore_has(repo, ".agents/"), True)
    want("gitignore_has(repo, .other/)", lib.gitignore_has(repo, ".other/"), False)
    want("gitignore_has(no .gitignore)", lib.gitignore_has(plain, ".codex/"), False)
    # A .gitignore that is a symlink proves nothing: git does not read one. Red with the islink
    # test dropped: "gitignore_has(a symlinked .gitignore) = True, want False".
    linked = os.path.join(tmp, "linked-gi")
    os.makedirs(linked)
    os.symlink(os.path.join(repo, ".gitignore"), os.path.join(linked, ".gitignore"))
    want("gitignore_has(a symlinked .gitignore)", lib.gitignore_has(linked, ".codex/"), False)
    # One that cannot be read raises Unreadable, so whether the entry is ignored is unknown and the
    # caller writes nothing. Red with only OSError caught: "gitignore_has(a .gitignore not UTF-8) =
    # ('raised', 'UnicodeDecodeError', ...), want ('Unreadable', .../.gitignore)".
    for label, make in (("a .gitignore that is a directory", lambda gi: os.makedirs(gi)),
                        ("a .gitignore not UTF-8", lambda gi: open(gi, "wb").write(b"\xff\n"))):
        where = os.path.join(tmp, label.replace(" ", "-"))
        os.makedirs(where)
        make(os.path.join(where, ".gitignore"))
        got = raised(lib.gitignore_has, where, ".codex/")
        try:
            lib.gitignore_has(where, ".codex/")
        except lib.Unreadable as e:
            got = ("Unreadable", e.path)
        except Exception:
            pass
        want("gitignore_has(%s)" % label, got, ("Unreadable", os.path.join(where, ".gitignore")))
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return failures, want.count()


def symlink_cases(tmp):
    """replace_symlink (S1 item 6): a link repointed through a temp link and a rename is never
    absent, where the unlink-then-symlink pairs (relink_skills, the codex skill mirror, jev's setup)
    lose it when symlink() fails after the unlink -- and relink goes on past that since 781b620.

    The control is in the test: the old pair, run under the same failing symlink(), must lose the
    link, or the case proves nothing. Seen failing on a mutated copy, replace_symlink
    written as that pair: "replace_symlink with symlink() failing: the link = None, want 'new'"."""
    want, failures = checker()
    d = os.path.join(tmp, "links")
    os.makedirs(d)
    link = os.path.join(d, "skill")
    target = lambda: os.readlink(link) if os.path.islink(link) else None
    leftovers = lambda: sorted(n for n in os.listdir(d) if ".tmp" in n)

    os.symlink("old", link)
    lib.replace_symlink("new", link)
    want("replace_symlink repoints", (target(), leftovers()), ("new", []))
    lib.replace_symlink("fresh", os.path.join(d, "absent"))
    want("replace_symlink creates", os.readlink(os.path.join(d, "absent")), "fresh")
    open("%s.tmp.%d" % (link, os.getpid()), "w").close()  # a leftover at the temp name
    # Red with the leftover not removed first: "replace_symlink over a leftover temp = (('raised',
    # 'FileExistsError', "[Errno 17] File exists: 'newer' -> '.../skill.tmp.<pid>'"), 'new', [...])".
    got = raised(lib.replace_symlink, "newer", link)
    want("replace_symlink over a leftover temp", (got, target(), leftovers()), (None, "newer", []))

    def old_pair(tgt, lnk):
        os.unlink(lnk)
        os.symlink(tgt, lnk)
    real_symlink = os.symlink

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    for label, fn in (("the unlink-then-symlink control", old_pair), ("replace_symlink", lib.replace_symlink)):
        if os.path.lexists(link):
            os.unlink(link)
        real_symlink("new", link)
        os.symlink = full
        try:
            got = raised(fn, "other", link)
        finally:
            os.symlink = real_symlink
        if fn is old_pair:
            want("%s loses the link (else this case proves nothing)" % label, target(), None)
        else:
            want("%s with symlink() failing" % label, got[:2], ("raised", "OSError"))
            want("%s with symlink() failing: the link" % label, target(), "new")
            want("%s with symlink() failing: temp links left" % label, leftovers(), [])

    # Red with no cleanup after a refused rename: "replace_symlink over a real directory =
    # (('raised', 'IsADirectoryError'), True, ['real-dir.tmp.<pid>']), want (..., True, [])".
    real_dir = os.path.join(d, "real-dir")
    os.makedirs(os.path.join(real_dir, "kept"))
    got = raised(lib.replace_symlink, "x", real_dir)
    want("replace_symlink over a real directory", (got[:2], os.path.isdir(os.path.join(real_dir, "kept")), leftovers()),
         (("raised", "IsADirectoryError"), True, []))
    return failures, want.count()


def record_cases(tmp):
    """lib.record and the helpers that call it: each real change on disk is one line in the file
    FORGE_WRITE_LOG names, a change not made is none, and a log that cannot be written never fails
    the write. cli.written turns one step's lines into its session-start note.

    Seen failing on a mutated copy: with replace_symlink's and symlink's record calls
    gone, "symlink = (None, []), want (None, ['link D/l'])"; with record's `except OSError` gone,
    "write_text with a log that cannot be opened = (('raised', 'IsADirectoryError', ...), 'd'),
    want (None, 'd')" -- the write made, and the run failed anyway."""
    want, failures = checker()
    d = os.path.join(tmp, "record")
    os.makedirs(d)
    log = os.path.join(tmp, "record.log")
    saved = os.environ.get("FORGE_WRITE_LOG")

    def logged(fn, *a, **k):
        """(what fn returned or raised, the log's lines it added)."""
        open(log, "w").close()
        got = raised(fn, *a, **k)
        with open(log, encoding="utf-8") as f:
            return got, [l.replace(d, "D") for l in f.read().splitlines()]
    os.environ["FORGE_WRITE_LOG"] = log
    try:
        p = os.path.join(d, "f.txt")
        want("write_text, a new file", logged(lib.write_text, p, "a", mode=0o600), (None, ["wrote D/f.txt"]))
        want("write_text, the same text", logged(lib.write_text, p, "a", mode=0o600), (None, []))
        os.chmod(p, 0o644)
        want("write_text, the same text with a loose mode", logged(lib.write_text, p, "a", mode=0o600),
             (None, ["wrote D/f.txt"]))
        want("write_text with a backup", logged(lib.write_text, p, "b", mode=0o600, backup=True),
             (None, ["wrote D/f.txt.bak", "wrote D/f.txt"]))
        os.chmod(p + ".bak", 0o644)
        want("write_text, the same text beside a loose .bak", logged(lib.write_text, p, "b", mode=0o600, backup=True),
             (None, ["chmod D/f.txt.bak"]))

        def refuse(tmp_path):
            raise ValueError("refused")
        got, lines = logged(lib.write_text, p, "c", check=refuse)
        want("write_text refused by check()", (got[:2], lines), (("raised", "ValueError"), []))
        link = os.path.join(d, "l")
        want("symlink", logged(lib.symlink, "x", link), (None, ["link D/l"]))
        want("replace_symlink", logged(lib.replace_symlink, "y", link), (None, ["link D/l"]))
        want("unlink", logged(lib.unlink, link), (None, ["unlink D/l"]))
        want("chmod", logged(lib.chmod, p, 0o600), (None, ["chmod D/f.txt"]))
        want("makedirs, a new directory", logged(lib.makedirs, os.path.join(d, "a", "b")), (None, ["mkdir D/a/b"]))
        want("makedirs, one already there", logged(lib.makedirs, os.path.join(d, "a", "b")), (None, []))
        # The change is made before its line: a log nobody can append to must not fail it.
        os.environ["FORGE_WRITE_LOG"] = d
        want("write_text with a log that cannot be opened", (raised(lib.write_text, p, "d"), open(p).read()), (None, "d"))
        os.environ["FORGE_WRITE_LOG"] = log
        # A file name that is not UTF-8 reaches Python surrogate-escaped. The write is made, so its
        # line must not raise either; it is backslash-escaped, keeping the log UTF-8 for cli's
        # strict read. Red before the fix: "write_text to a file name that is not
        # UTF-8 = (('raised', 'UnicodeEncodeError', "'utf-8' codec can't encode character '\\udce9'
        # in position 39: surrogates not allowed"), []), want (None, ['wrote D/caf\\\\udce9.txt'])" -- the file
        # written, and the call raised anyway.
        want("write_text to a file name that is not UTF-8", logged(lib.write_text, os.path.join(d, "caf\udce9.txt"), "x"),
             (None, ["wrote D/caf\\udce9.txt"]))
        os.environ.pop("FORGE_WRITE_LOG")
        want("write_text with no log", logged(lib.write_text, p, "e"), (None, []))
    finally:
        if saved is None:
            os.environ.pop("FORGE_WRITE_LOG", None)
        else:
            os.environ["FORGE_WRITE_LOG"] = saved

    h = lib.HOME
    lines = [("wrote", h + "/.claude.json"), ("wrote", "/p/a"), ("chmod", h + "/.claude.json"), ("wrote", "/p/a"),
             ("wrote", "/p/b"), ("wrote", "/p/c"), ("link", "/p/l"), ("wrote", cli.CACHE + "gsd-stage/NPM-CHECKED")]
    want("cli.written: per kind in the order seen, each path once, forge's cache left out",
         cli.written(lines), "wrote 4 file(s): ~/.claude.json, /p/a, /p/b +1 more; chmod 1: ~/.claude.json; linked 1: /p/l")
    want("cli.written, only the cache", cli.written([("wrote", cli.CACHE + "x")]), "")

    # cli.CHANGED keeps the warnings, failures and refusals, and no longer the lines that only say
    # something was written: the write log names those.
    for line, shown in (
            ("  ~ other-app            copy:AGENT-SYSTEM.md, SKIP-agents-md(non-forge content):AGENTS.md", True),
            ("relink_skills: 86 skills | 0 linked, 0 pruned | BLOCKED(real dir in mirror): ~/.claude/skills/x", True),
            ("relink_skills: memory unlink failed: [Errno 13] Permission denied", True),
            ("   jev-proxy did not start: port closed", True),  # a warning (exit 0), no "!"
            ("   ! any failure at all", True),
            ("GSD 1.43.0 is published (installed 1.42.3). Update: see the procedure at the top of "
             "scripts/sync/sync_gsd_runtime.py", True),
            ("  ! app                  ERROR: boom -- skipped, other projects unaffected", True),
            # sync_system_doc's only ERROR line starts with '!'; an ERROR anywhere else in a step's
            # output (a third-party installer, say) is not one of ours. Red while CHANGED had a bare
            # '| ERROR' alternative (round 5): "FAIL cli.CHANGED shows 'some ERROR in text' = True,
            # want False".
            ("  ! app ERROR: boom -- skipped, other projects unaffected", True),
            ("some ERROR in text", False),
            ("forge: /x is a linked worktree -- nothing written; apply from the main checkout", True),
            ("   ~/.claude.json -> wrote", False),
            ("relink_skills: 86 skills | 86 linked, 0 pruned", False),
            ("  ~ app                  copy:AGENT-SYSTEM.md, create:CLAUDE.md", False),
            ("   wrote 2 changed: a.md, b.md", False),
            ("GSD runtime in sync (2 file(s) written).", False),
            ("chmod 600 ~/.claude.json (it carries resolved secrets)", False),
            ("   ~/.codex/hooks.json -> repaired SessionStart caveman_house_rules.py", False)):
        want("cli.CHANGED shows %r" % line, bool(cli.CHANGED.search(line)), shown)
    return failures, want.count()


def cli_test_cases(tmp):
    """cmd_test (forge test) in-process, lib.ROOT pointed at toy dirs. A failed `git ls-files` (not a
    repository, or no git on PATH) and a list with no tests are each a FAIL and exit 1. Seen failing
    on b6222aa, where each printed "SUMMARY: 0 passed, 0 warnings, 0 failures" and
    returned 0: "forge test outside a git repository = (True, 0, False, False), want (True, 1, True,
    True)", "forge test in a repo with no tests = (0, False), want (1, True)", the same for "a repo
    with only a benchmarks/ test", and "forge test with no git on PATH = ('raised',
    'FileNotFoundError'), want (1, True)". The control, a repo with one passing tracked test, is
    (0, PASS) before and after."""
    want, failures = checker()
    root, real_path = lib.ROOT, os.environ.get("PATH", "")

    def forge_test():
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli.cmd_test(None)
        return rc, out.getvalue()

    def toy(name, tests):
        d = os.path.join(tmp, "cmdtest", name)
        os.makedirs(d)
        if tests is not None:
            git(d, "init", "-q")
            for rel in tests:
                rel, code = rel if isinstance(rel, tuple) else (rel, 0)
                os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
                with open(os.path.join(d, rel), "w") as f:
                    f.write("import sys\nprint('NOT RUN: no registry')\nsys.exit(%d)\n" % code)
                git(d, "add", rel)
        return d

    try:
        lib.ROOT = toy("nogit", None)
        # Only a toy that is really outside every repository proves the case.
        outside = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=lib.ROOT, capture_output=True).returncode != 0
        rc, out = forge_test()
        want("forge test outside a git repository", (outside, rc, "not a git repository" in out,
                                                     "SUMMARY: 0 passed, 0 warnings, 1 failures" in out), (True, 1, True, True))
        for name, tests in (("empty", []), ("bench-only", ["benchmarks/test_x.py"])):
            lib.ROOT = toy(name, tests)
            rc, out = forge_test()
            want("forge test in a repo with %s" % ("no tests" if not tests else "only a benchmarks/ test"),
                 (rc, "no tests found" in out), (1, True))
        lib.ROOT = toy("ok", ["test_ok.py"])
        rc, out = forge_test()
        want("control: forge test with one passing tracked test", (rc, "PASS" in out and "test_ok.py" in out,
                                                                  "SUMMARY: 1 passed, 0 warnings, 0 failures" in out),
             (0, True, True))
        # A test that could not run exits 77 (repo-kit/kit.py NOT_RUN): a WARN that says so and why, never a PASS.
        lib.ROOT = toy("notrun", ["test_ok.py", ("test_off.py", 77)])
        rc, out = forge_test()
        want("forge test with a test that exits 77 (NOT RUN)",
             (rc, "WARN  test_off.py" in out and "NOT RUN, NOT ARMED: no registry" in out,
              "SUMMARY: 1 passed, 1 warnings, 0 failures" in out), (0, True, True))
        # Only a file whose basename starts with test_ and ends .py is a test. Red on c40e9bd (pathspec
        # '*test_*.py'): "forge test with a tracked helper that merely contains test_ = (1, True, False), want
        # (0, False, True)": contest_helper.py (exit 3) ran and printed "FAIL  contest_helper.py".
        lib.ROOT = toy("helper", ["test_ok.py", ("contest_helper.py", 3), ("sub/latest_x.py", 3), ("test_notes.txt", 3)])
        rc, out = forge_test()
        want("forge test with a tracked helper that merely contains test_", (rc, "contest_helper" in out or "latest_x" in out
             or "test_notes" in out, "SUMMARY: 1 passed, 0 warnings, 0 failures" in out), (0, False, True))
        lib.ROOT = toy("subdir", ["sub/test_deep.py"])
        rc, out = forge_test()
        want("control: a test in a subdirectory is found", (rc, "PASS  test_deep.py" in out), (0, True))
        # A name with a space is one test. Red on c40e9bd (r.stdout.split()): "forge test with a file name
        # containing a space = (1, False, False), want (0, True, True)": FAIL file.py and FAIL test_my.
        lib.ROOT = toy("space", ["test_my file.py"])
        rc, out = forge_test()
        want("forge test with a file name containing a space", (rc, "PASS  test_my file.py" in out,
                                                                "SUMMARY: 1 passed, 0 warnings, 0 failures" in out), (0, True, True))
        lib.ROOT = toy("failing", ["test_ok.py", ("test_bad.py", 1)])
        rc, out = forge_test()
        want("control: forge test with a test that exits 1", (rc, "FAIL  test_bad.py" in out,
                                                              "SUMMARY: 1 passed, 0 warnings, 1 failures" in out), (1, True, True))
        # An on-demand suite (hooks/test_guard_mutants.py: 326 mutants on every core, minutes of full CPU) is
        # not run by default and says so: a SKIP line naming how to run it, never a PASS, and not in the
        # summary's counts (non-negotiable 7). Its toy exits 1, so a run of it would be a FAIL.
        lib.ROOT = toy("ondemand", ["test_ok.py", ("hooks/test_guard_mutants.py", 1)])
        rc, out = forge_test()
        want("forge test skips the on-demand mutant suite and says it was not run",
             (rc, "SKIP  test_guard_mutants.py" in out and "NOT RUN" in out and "forge test --mutants" in out,
              "FAIL" in out, "PASS  test_guard_mutants.py" in out,
              "SUMMARY: 1 passed, 0 warnings, 0 failures" in out), (0, True, False, False, True))
        # --mutants runs only the on-demand suites: test_bad.py (exit 1) is not run, the mutant toy is.
        lib.ROOT = toy("ondemand-only", [("test_bad.py", 1), ("hooks/test_guard_mutants.py", 0)])
        with contextlib.redirect_stdout(io.StringIO()) as o:
            rc = cli.cmd_test(argparse.Namespace(mutants=True))
        out = o.getvalue()
        want("forge test --mutants runs only the on-demand suites",
             (rc, "PASS  test_guard_mutants.py" in out, "test_bad.py" in out,
              "SUMMARY: 1 passed, 0 warnings, 0 failures" in out), (0, True, False, True))
        # A child of forge test runs at the lowest CPU priority and, where ionice exists, in the idle I/O
        # class, so a dictation tool on the same machine keeps its cores (measured: voxtype's voice
        # detector 0.3 s -> 50+ s while forge test ran). Under a parent already at nice 19 this proves nothing.
        lib.ROOT = toy("prio", ["test_nice.py", "test_ionice.py"])
        for name, code in (("test_nice.py", "import os, sys\nsys.exit(0 if os.nice(0) == 19 else 1)\n"),
                           ("test_ionice.py", "import os, shutil, subprocess, sys\n"
                            "w = shutil.which('ionice')\n"
                            "sys.exit(0 if not w or 'idle' in subprocess.run([w, '-p', str(os.getpid())], "
                            "capture_output=True, text=True).stdout else 1)\n")):
            with open(os.path.join(lib.ROOT, name), "w") as f:
                f.write(code)
        rc, out = forge_test()
        want("a child of forge test runs at nice 19 and in the idle I/O class",
             (rc, "PASS  test_nice.py" in out, "PASS  test_ionice.py" in out), (0, True, True))
        os.environ["PATH"] = os.path.join(tmp, "cmdtest", "no-bin")
        got = raised(forge_test)
        want("forge test with no git on PATH", (got[0], "git" in got[1]) if isinstance(got[0], int) else got[:2], (1, True))
    finally:
        os.environ["PATH"] = real_path
        lib.ROOT = root
    return failures, want.count()


def settings_cases(tmp):
    """lib.settings(), lib.on() and INTEGRATIONS (docs/portable-design.md sections 4 and 5, T2): the
    one data file the engine reads, and the switch every integration is gated by. Red on the code
    before them: "AttributeError: module 'forge.lib' has no attribute 'SETTINGS'" and, with that one
    constant added, "AttributeError: module 'forge.lib' has no attribute 'settings'", which is every
    case here (a missing file must exit with the `!` line, on("codex") on a file holding false must be False).

    A missing file is an exit 1 with the `!` line, never an empty dict: an engine that read {} would
    switch every integration off and write a stranger's settings from nothing. config/forge.json
    (the fixture's, all on but jev) and examples/forge.json (a stranger's) are loaded as the real files: the stranger's has
    every integration off and no personal data.

    Each case was seen failing on a mutated copy of lib.py: a missing file returning {},
    "settings with no file = {}, want ('exit', '! config/forge.json missing -- run bin/forge init')";
    bool() for `is True`, "on('jev') on the string 'false' = True, want False"; the unknown-name check
    dropped, "on('codeX'), a name that is no integration = False, want True"; the deepcopy dropped,
    "settings after a caller mutated the last one = True, want False"; lru_cache(maxsize=0), "a file
    rewritten after it was read (cached) = False, want True"; the object check dropped, "settings on a
    list = False, want True"; and on examples/forge.json with codex true, "examples/forge.json
    integrations, all off = {'codex': True, ...}, want {'codex': False, ...}".

    The values of the machine's file are not asserted here:
    the tasks that wire it in compare the generated output, which is the proof they were copied right."""
    want, failures = checker()
    d = os.path.join(tmp, "settings")
    os.makedirs(d)
    real = lib.SETTINGS
    missing_line = "! config/forge.json missing -- run bin/forge init"

    def put(name, text):
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(text)
        return p

    def exits(fn, *a):
        try:
            return fn(*a)
        except SystemExit as e:
            return ("exit", e.code)

    try:
        lib.settings.cache_clear()
        lib.SETTINGS = os.path.join(d, "absent.json")
        want("settings with no file", exits(lib.settings), ("exit", missing_line))
        want("on('codex') with no file", exits(lib.on, "codex"), ("exit", missing_line))

        lib.SETTINGS = put("off.json", '{"integrations": {"codex": false, "gsd": true, "jev": "false"}}')
        want("on('codex') on a file holding false", lib.on("codex"), False)
        want("on('gsd') on a file holding true", lib.on("gsd"), True)
        want("on('hindsight') with the key absent", lib.on("hindsight"), False)
        want("on('jev') on the string 'false'", lib.on("jev"), False)
        want("on('codeX'), a name that is no integration", str(raised(lib.on, "codeX")).startswith("('raised', 'ValueError'"), True)

        got = lib.settings()
        got["x"] = 1
        want("settings after a caller mutated the last one", "x" in lib.settings(), False)

        lib.SETTINGS = put("later.json", '{"integrations": {"codex": true}}')
        want("a path read first time", lib.on("codex"), True)
        put("later.json", '{"integrations": {"codex": false}}')
        want("a file rewritten after it was read (cached)", lib.on("codex"), True)
        lib.settings.cache_clear()
        want("the same file after cache_clear", lib.on("codex"), False)

        lib.SETTINGS = put("nokeys.json", "{}")
        want("a file with no integrations key", [lib.on(n) for n in lib.INTEGRATIONS], [False] * len(lib.INTEGRATIONS))

        for label, text in (("bad JSON", "{not json"), ("a list", "[1]")):
            lib.SETTINGS = put(label.replace(" ", "-") + ".json", text)
            got = exits(lib.settings)
            want("settings on %s" % label, isinstance(got, tuple) and str(got[1]).startswith("! config/forge.json unreadable"), True)
    finally:
        lib.SETTINGS = real
        lib.settings.cache_clear()

    want("INTEGRATIONS", lib.INTEGRATIONS, ("codex", "gsd", "jev", "hindsight", "caveman"))
    ours = json.load(open(os.path.join(FIXTURES, "forge.json")))
    want("tests/fixtures/config/forge.json integrations, all on but jev (its setup.py is a private skill)",
         ours["integrations"], {n: n != "jev" for n in lib.INTEGRATIONS})
    theirs = json.load(open(os.path.join(REPO, "examples", "forge.json")))
    want("examples/forge.json integrations, all off", theirs["integrations"], {n: False for n in lib.INTEGRATIONS})
    for key, empty in (("user_settings", {}), ("user_hooks", []), ("instruction_files_skip", []),
                       ("doctor_extra", [])):
        want("examples/forge.json %s" % key, theirs.get(key), empty)
    want("examples/forge.json has no session_wait", "session_wait" in theirs, False)
    want("examples/forge.json skill_keep tables are empty",
         {k: v for k, v in theirs.get("skill_keep", {}).items()
          if not k.startswith("_") and any(v.values() if isinstance(v, dict) else v)}, {})
    return failures, want.count()


def main():
    # The world's forge.json is the toy all-on fixture, never this checkout's config/forge.json: a
    # stranger's engine copy has none. Red there before (M1, docs/audits/portable-measure.md):
    # "FileNotFoundError: .../config/forge.json" from settings_cases' read of it.
    lib.SETTINGS = os.path.join(FIXTURES, "forge.json")
    lib.settings.cache_clear()
    tmp = sandbox.mkdtemp("lib-test-")
    dev, prof_dir = os.path.join(tmp, "dev"), os.path.join(tmp, "profiles")
    os.makedirs(prof_dir)
    for name, rel in (("dev", ""), ("app", "app"), ("vault", "app/vault")):
        os.makedirs(os.path.join(dev, rel, "src"), exist_ok=True)
        with open(os.path.join(prof_dir, name + ".claude.json"), "w") as f:
            f.write('{"project_path": "%s"}' % os.path.join(dev, rel).rstrip("/"))
    git(os.path.join(dev, "app"), "init", "-q")
    git(os.path.join(dev, "app"), "commit", "-q", "--allow-empty", "-m", "x")
    git(os.path.join(dev, "app"), "worktree", "add", "-q", os.path.join(dev, "app-wt"))
    # A profile whose directory is inside the linked worktree, below its root: only the
    # worktree check refuses it -- the nested-repo check sees the worktree root above the profile.
    os.makedirs(os.path.join(dev, "app-wt", "src"))
    with open(os.path.join(prof_dir, "wtsrc.claude.json"), "w") as f:
        f.write('{"project_path": "%s"}' % os.path.join(dev, "app-wt", "src"))
    os.makedirs(os.path.join(dev, "newrepo", "sub"))
    git(os.path.join(dev, "newrepo"), "init", "-q")
    lib.PROFILES = prof_dir
    lib.ROOT = tmp  # not a worktree, wherever the test itself is run from
    lib.HOME = os.path.join(tmp, "home")  # no settings.json yet: the real one names the real checkout

    cases = {
        os.path.join(dev, "app"): "app",
        os.path.join(dev, "app", "src"): "app",
        os.path.join(dev, "app", "vault"): "vault",  # deepest profile wins
        dev: "dev",
        os.path.join(dev, "app-wt"): None,  # a linked worktree writes nothing
        os.path.join(dev, "app-wt", "src"): None,  # ... nor does a profile inside one
        os.path.join(dev, "newrepo", "sub"): None,  # an unregistered repo is not `dev`'s
        "/": None,
    }
    failures = ["resolve_project(%s) = %r, want %r" % (p, lib.resolve_project(p), want)
                for p, want in cases.items() if lib.resolve_project(p) != want]

    def scope(argv, applying):
        """context's (only, globals) for argv, with --apply added when `applying`."""
        return tuple(lib.context(argv + (["--apply"] if applying else []))[1:])

    # session_scope is the one place that says a session gets its own project and forge's session
    # also the user-scope files. No profile here is called forge, so only this reaches its True.
    # Red before it existed: "session_scope('forge') = ('raised', 'AttributeError',
    # \"module 'forge.lib' has no attribute 'session_scope'\"), want ({'forge'}, True)"; with
    # `name == "forge"` replaced by False, "session_scope('forge') = ({'forge'}, False), want
    # ({'forge'}, True)".
    sessions = {"forge": ({"forge"}, True), "vault": ({"vault"}, False), None: (set(), False)}
    for n, want in sessions.items():
        got = raised(lambda: tuple(lib.session_scope(n)))
        if got != want:
            failures.append("session_scope(%r) = %r, want %r" % (n, got, want))
    # The loop above compares tuple(...), so a session_scope returning a plain tuple passed it, and
    # cli's session start reads session_scope(name).globals. Red with session_scope returning
    # `({name} if name else set(), name == "forge")`: "session_scope returned
    # [('tuple', False), ('tuple', False), ('tuple', False)], want a lib.Scope with .globals, for
    # forge, vault and no project" -- the loop above stayed green on that mutation.
    kinds = [(type(got).__name__, getattr(got, "globals", None) == want[1] and isinstance(got, lib.Scope))
             for got, want in ((raised(lib.session_scope, n), want) for n, want in sessions.items())]
    if kinds != [("Scope", True)] * len(sessions):
        failures.append("session_scope returned %r, want a lib.Scope with .globals, for forge, vault and no project" % kinds)

    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    scopes = {"terminal": (scope([], False), (None, True)),
              "--project": (scope(["--project", "app"], True), ({"app"}, False)),
              # argparse's other spelling; unmatched, it ran unscoped: every project and the user files
              "--project=app": (scope(["--project=app"], True), ({"app"}, False))}
    os.environ["CLAUDE_PROJECT_DIR"] = os.path.join(dev, "app", "vault")
    scopes["session"] = (scope([], True), ({"vault"}, False))
    scopes["--all in a session"] = (scope(["--all"], True), (None, True))
    # The SessionStart path: an unregistered session dir is silently nobody's.
    os.environ["CLAUDE_PROJECT_DIR"] = os.path.join(dev, "newrepo", "sub")
    scopes["unregistered session"] = (scope([], True), (set(), False))
    failures += ["context %s = %r, want %r" % (k, got, want) for k, (got, want) in scopes.items() if got != want]
    os.environ.pop("CLAUDE_PROJECT_DIR", None)

    # A mistyped --project is an error, not a silent no-op that prints OK. A flag in the name's
    # place is "(none given)", not a project called "--apply"; a second --project is refused
    # rather than dropped (argv.index took the first, argparse in `forge sync` keeps the last).
    bad = {("--project",): "unknown project: (none given) (known: app, dev, vault, wtsrc)",
           ("--project", "--apply"): "unknown project: (none given) (known: app, dev, vault, wtsrc)",
           ("--project", "nosuch"): "unknown project: nosuch (known: app, dev, vault, wtsrc)",
           ("--project", "app", "--project", "dev"): "forge: --project given more than once",
           ("--project=app", "--project", "dev"): "forge: --project given more than once"}
    for argv, want in bad.items():
        try:
            got = scope(list(argv), False)
            failures.append("context %r = %r, want the exit %r" % (argv, got, want))
        except SystemExit as e:
            if want not in str(e.code):
                failures.append("context %r exited with %r, want %r" % (argv, e.code, want))

    # A profiles directory that cannot be listed is an error, not "no profiles": glob swallowed
    # the PermissionError, and every caller then saw a machine with no projects.
    if os.geteuid() != 0:  # root reads a mode-000 directory anyway
        locked = os.path.join(tmp, "locked-profiles")
        os.makedirs(locked)
        open(os.path.join(locked, "a.claude.json"), "w").write("{}")
        os.chmod(locked, 0)
        real_profiles, lib.PROFILES = lib.PROFILES, locked
        try:
            failures.append("profiles() on an unreadable directory = %r, want PermissionError" % lib.profiles())
        except PermissionError:
            pass
        lib.PROFILES = real_profiles
        os.chmod(locked, 0o755)

    # A profile that is not a JSON object is left out, not a crash: may_write and resolve_project
    # call .get on every profile, and one holding `null` raised AttributeError in both, so from a
    # session start too. The generator reports the file itself ('! could not read', '! no
    # project_path'). Red before: "profiles() over bad profiles = ('raised', 'JSONDecodeError', ...)"
    # and "resolve_project beside a null profile = ('raised', 'AttributeError', "'list' object has
    # no attribute 'get'")".
    bad = os.path.join(tmp, "bad-profiles")
    os.makedirs(bad)
    for n, text in (("ok", '{"project_path": "/x"}'), ("null", "null"), ("list", "[1]"), ("broken", "{nope")):
        open(os.path.join(bad, n + ".claude.json"), "w").write(text)
    real_profiles, lib.PROFILES = lib.PROFILES, bad
    got = raised(lib.profiles)
    if got != {"ok": {"project_path": "/x"}}:
        failures.append("profiles() over bad profiles = %r, want only 'ok'" % (got,))
    os.remove(os.path.join(bad, "broken.claude.json"))
    got = raised(lib.resolve_project, "/x/sub")
    if got != "ok":
        failures.append("resolve_project beside a null profile = %r, want 'ok'" % (got,))
    lib.PROFILES = real_profiles

    # A linked worktree of forge writes nothing, whatever the scope; a dry-run there is untouched.
    lib.ROOT = os.path.join(dev, "app-wt")
    wt = {}
    with contextlib.redirect_stdout(io.StringIO()):
        for argv in ([], ["--all"], ["--project", "app"]):
            wt["worktree --apply %r" % argv] = (scope(argv, True), (set(), False))
        wt["worktree dry-run"] = (scope([], False), (None, True))
    failures += ["context %s = %r, want %r" % (k, got, want) for k, (got, want) in wt.items() if got != want]
    lib.ROOT = tmp

    # Only the checkout this machine's SessionStart hook runs may write. Once, two copies
    # of forge in /tmp -- plain copies, not worktrees -- rewrote ~20 projects' CLAUDE.md pointers
    # with their own path and registered a project in master.
    settings = os.path.join(lib.HOME, ".claude", "settings.json")
    other, gone = os.path.join(tmp, "installed"), os.path.join(tmp, "moved-away")
    for d in (tmp, other):
        os.makedirs(os.path.join(d, "bin"), exist_ok=True)
        open(os.path.join(d, "bin", "forge"), "w").close()

    def names(*roots, text=None):
        """settings.json whose SessionStart hook runs each root's bin/forge, or holding `text`."""
        if text is None:
            sandbox.installed_settings(lib.HOME, *roots, hooks={"Stop": "not a list"}, theme="dark")
            return
        os.makedirs(os.path.dirname(settings), exist_ok=True)
        with open(settings, "w") as f:
            f.write(text)

    copy_msg = "forge: %s is not the checkout this machine runs (%s) -- nothing written; apply from %s" % (
        tmp, other, other)
    guard = {}

    def exits():
        """The code require_write() exited with, or "returned"."""
        try:
            lib.require_write()
        except SystemExit as e:
            return e.code
        return "returned"
    guard["no settings.json (a fresh machine)"] = (lib.may_write(), (True, ""))
    names()
    guard["no forge entry (the harness's toy HOME before its first apply)"] = (lib.may_write(), (True, ""))
    names(tmp)
    guard["names this checkout"] = (lib.may_write(), (True, ""))
    guard["require_write from this checkout"] = (exits(), "returned")
    guard["installed_root, named"] = (lib.installed_root(), tmp)
    names(gone)
    guard["names a checkout no longer on disk (forge relocated)"] = (lib.may_write(), (True, ""))
    names(other)
    guard["names another checkout (a copy)"] = (lib.may_write(), (False, copy_msg))
    guard["require_write from a copy"] = (exits(), copy_msg)  # exit 1 with it, not a dry-run
    with contextlib.redirect_stdout(io.StringIO()) as out:
        guard["scope --apply from a copy"] = (scope(["--all"], True), (set(), False))
    guard["scope's message from a copy"] = (out.getvalue(), copy_msg + "\n")
    guard["scope dry-run from a copy"] = (scope(["--all"], False), (None, True))

    # lib.context (S1 item 7): its one may_write() call is also Ctx.apply's answer, where
    # sync_agent_config called may_write() a second time to downgrade APPLY. Seen failing on a
    # mutated copy: with the apply flag not downgraded, "context --apply from a copy =
    # ((True, set(), False), 1, ...), want ((False, set(), False), 1, ...)"; with a second may_write()
    # for it, "context --apply from this checkout = ((True, None, True), 2, ''), want ((True, None,
    # True), 1, '')"; with the unknown-project exit moved after the refusal, "context --apply
    # --project nosuch from a copy = ((False, set(), False), 1, 'forge: ... is not the checkout ...'),
    # want (('exit', 'forge: unknown project: nosuch'), 0, '')"; with `invert` ignored, "context,
    # relink's inverted --dry-run, absent = ((False, None, True), 0, ''), want ((True, None, True), 1,
    # '')"; with Ctx.wants() ignoring a None scope, "Ctx.wants = (True, False, False, False), want
    # (True, False, True, False)"; with context returning a plain tuple, "context returns a Ctx =
    # ('raised', 'AttributeError', \"'tuple' object has no attribute '_asdict'\"), want {'apply':
    # False, 'only': None, 'globals': True}" (re-seen when hook_scope folded into context).
    real_may_write = lib.may_write

    def ctx_of(argv, **kw):
        """(the Ctx as a tuple or ('exit', code), how often may_write() ran, what was printed)."""
        calls = []
        lib.may_write = lambda: (calls.append(1), real_may_write())[1]
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                got = tuple(lib.context(argv, **kw))
        except SystemExit as e:
            got = ("exit", str(e.code).split(" (known")[0])
        finally:
            lib.may_write = real_may_write
        return got, len(calls), out.getvalue()
    guard["context --apply from a copy"] = (ctx_of(["--all", "--apply"]), ((False, set(), False), 1, copy_msg + "\n"))
    guard["context dry-run from a copy"] = (ctx_of(["--all"]), ((False, None, True), 0, ""))
    guard["context --apply --project nosuch from a copy"] = (ctx_of(["--apply", "--project", "nosuch"]),
                                                             (("exit", "forge: unknown project: nosuch"), 0, ""))
    names(tmp)
    guard["context --apply from this checkout"] = (ctx_of(["--apply"]), ((True, None, True), 1, ""))
    guard["context --apply --project app"] = (ctx_of(["--apply", "--project", "app"]), ((True, {"app"}, False), 1, ""))
    guard["context, relink's inverted --dry-run, absent"] = (ctx_of([], flag="--dry-run", invert=True),
                                                             ((True, None, True), 1, ""))
    guard["context, relink's inverted --dry-run, given"] = (ctx_of(["--dry-run"], flag="--dry-run", invert=True),
                                                            ((False, None, True), 0, ""))
    wants = lambda ctx, name: ctx.wants(name)
    guard["Ctx.wants"] = ((wants(lib.Ctx(True, {"app"}, False), "app"), wants(lib.Ctx(True, {"app"}, False), "dev"),
                           wants(lib.Ctx(False, None, True), "dev"), wants(lib.Ctx(False, set(), False), "app")),
                          (True, False, True, False))
    guard["context returns a Ctx"] = (raised(lambda: lib.context([])._asdict()),
                                      {"apply": False, "only": None, "globals": True})
    lib.ROOT = os.path.join(dev, "app-wt")
    names(lib.ROOT)
    guard["a worktree, even the named one"] = (lib.may_write()[0], False)
    guard["a worktree's message"] = (lib.may_write()[1].endswith("is a linked worktree -- nothing written; apply from the main checkout"), True)
    lib.ROOT = tmp
    for label, kw in (("unparseable", {"text": "{not json"}), ("two different checkouts", {})):
        names(tmp, other, **kw)
        ok, why = lib.may_write()
        guard["settings.json %s refuses" % label] = ((ok, why.startswith("forge: cannot tell which checkout this machine runs")
                                                      and settings in why and "fix it by hand" in why), (False, True))
    # installed_root reads through read_owned since S1 and keeps each refusal's exact text, captured
    # from the lib before the move. Seen failing with the OSError branch dropped: "may_write
    # when settings.json is a directory = '... runs: /…/settings.json is not valid JSON ([Errno 21] Is a
    # directory: ...) ...', want '... runs: [Errno 21] Is a directory: ...'".
    refusal = "forge: cannot tell which checkout this machine runs: %s -- nothing written; fix it by hand"
    for label, body, text in (
            ("bad JSON", b"{not json", "%s is not valid JSON (Expecting property name enclosed in double quotes: "
                                       "line 1 column 2 (char 1))" % settings),
            ("a list", b"[1]", "%s is not a JSON object" % settings),
            ("not UTF-8", b"\xff", "%s is not valid JSON ('utf-8' codec can't decode byte 0xff in position 0: "
                                   "invalid start byte)" % settings),
            ("a directory", None, "[Errno 21] Is a directory: '%s'" % settings)):
        if os.path.isfile(settings):
            os.remove(settings)
        if body is None:
            os.makedirs(settings)
        else:
            with open(settings, "wb") as f:
                f.write(body)
        guard["may_write when settings.json is %s" % label] = (lib.may_write(), (False, refusal % text))
    os.rmdir(settings)

    # A toy HOME only writes a toy world: the incident's agents set HOME to a scratch dir, so no
    # settings.json named any checkout, and the copy's profiles still named the real projects.
    guard["a toy HOME, every profile beside the checkout"] = (lib.may_write(), (True, ""))
    outside = os.path.join(prof_dir, "outside.claude.json")
    with open(outside, "w") as f:
        f.write('{"project_path": "/nonexistent-forge-guard/outside"}')
    guard["a toy HOME, one profile outside"] = (lib.may_write(), (False, "forge: HOME is a sandbox (%s) but profiles "
                                                              "point outside it (outside) -- nothing written" % lib.HOME))
    real_pwd = getattr(lib, "pwd", None)
    lib.pwd = types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_dir=lib.HOME))
    guard["the real HOME with no forge entry, profiles anywhere (a fresh machine)"] = (lib.may_write(), (True, ""))

    # A uid with no passwd entry (a container, `unshare` with no mapping) cannot say whether HOME
    # is a sandbox: it refuses, in the house style cli.CHANGED shows at session start. Red before
    # the fix: "may_write with a uid missing from passwd = ('raised', 'KeyError',
    # "'getpwuid(): uid not found: 4242'"), want (False, True, True)". The message is pinned: a fix
    # that falls through to the toy-HOME check instead (real_home = "/nonexistent") also refuses
    # here, as "HOME is a sandbox ... -- nothing written" (outside.claude.json is present), and is
    # fail-open once every profile is in-world. Red on that mutation: "may_write with a
    # uid missing from passwd = (False, False, True), want (False, True, True)".
    def no_entry(uid):
        raise KeyError("getpwuid(): uid not found: 4242")
    lib.pwd = types.SimpleNamespace(getpwuid=no_entry)
    try:
        got = raised(lib.may_write)
    finally:
        lib.pwd = real_pwd
    guard["with a uid missing from passwd"] = (
        got if got[0] == "raised" else (got[0], got[1].startswith("forge: uid ") and "has no passwd entry" in got[1]
                                        and got[1].endswith(" -- nothing written"),
                                        bool(cli.CHANGED.search(got[1]))), (False, True, True))
    lib.pwd = real_pwd
    os.remove(outside)
    failures += ["may_write %s = %r, want %r" % (k, got, want) for k, (got, want) in guard.items() if got != want]

    # `forge sync --project X --all` contradicts itself: argparse refuses it.
    cli.cmd_sync = lambda a: 0  # never run the real generators
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            got = cli.main(["sync", "--project", "app", "--all"])
        failures.append("forge sync --project app --all returned %r, want a usage error" % got)
    except SystemExit as e:
        if e.code != 2:
            failures.append("forge sync --project app --all exited %r, want 2" % e.code)

    lib.STATE, lib.LOCK = tmp, os.path.join(tmp, "sync.lock")
    held = subprocess.Popen([sys.executable, "-c", "import fcntl,time; f=open(%r,'a'); fcntl.flock(f, fcntl.LOCK_EX); print(1, flush=True); time.sleep(5)" % lib.LOCK],
                            stdout=subprocess.PIPE)
    held.stdout.readline()
    try:
        with lib.lock(timeout=0.5):
            failures.append("lock taken while another process held it")
    except TimeoutError:
        pass
    held.kill()
    held.wait()
    with lib.lock(timeout=2):
        pass

    # A master session start that writes nothing because of a refusal says so: forge/cli.py's
    # CHANGED filter is all the user sees of a SessionStart. The two steps an app session runs
    # print the same line.
    names(tmp, text="{not json")
    why = lib.may_write()[1]
    os.remove(settings)
    real_run = lib.run
    lib.run = lambda args, capture=False, env=None: subprocess.CompletedProcess(args, 0, why + "\nMODE: DRY-RUN\n", "")
    os.environ["CLAUDE_PROJECT_DIR"] = os.path.join(dev, "app")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cli.cmd_session_start(None)
    os.environ.pop("CLAUDE_PROJECT_DIR")
    msg = json.loads(out.getvalue() or "{}").get("systemMessage", "")
    if not why or msg.count(why) != 1:
        failures.append("session start refused by %r showed %r, want the refusal exactly once" % (why, msg))

    # With no CLAUDE_PROJECT_DIR the session start resolves its project from the cwd, and the
    # generators it runs must get that same directory: they scope themselves by the variable
    # alone (lib.context), and without it every one of them ran over all projects and the user files.
    seen_env, ran = [], []
    lib.run = lambda args, capture=False, env=None: (seen_env.append((env or {}).get("CLAUDE_PROJECT_DIR")),
                                                     ran.append(args[0]),
                                                     subprocess.CompletedProcess(args, 0, "", ""))[2]
    cwd = os.getcwd()
    os.chdir(os.path.join(dev, "app"))
    with contextlib.redirect_stdout(io.StringIO()):
        cli.cmd_session_start(None)
    os.chdir(cwd)
    if not seen_env or set(seen_env) != {os.path.join(dev, "app")}:
        failures.append("session start from the cwd %s gave its steps CLAUDE_PROJECT_DIR %r"
                        % (os.path.join(dev, "app"), seen_env))

    # Outside forge a session start runs only the two steps that write a project: relink_skills and
    # sync_gsd_runtime write only user-scope files and return 0 at once without ctx.globals, and in
    # an app session each cost 0.2-0.6 s of interpreter start for nothing. Red on the old cli.py:
    # "session start in app ran ['scripts/sync/relink_skills.py',
    # 'scripts/sync/sync_gsd_runtime.py', 'scripts/sync/sync_agent_config.py',
    # 'scripts/sync/sync_system_doc.py'], want ['scripts/sync/sync_agent_config.py',
    # 'scripts/sync/sync_system_doc.py']".
    project_steps = ["scripts/sync/sync_agent_config.py", "scripts/sync/sync_system_doc.py"]
    if ran != project_steps:
        failures.append("session start in app ran %r, want %r" % (ran, project_steps))
    # forge's session still runs all four, in SYNC's order. This passes on the old cli.py, which ran
    # every step everywhere; it is the control on the skip: with `and not scope.globals` deleted
    # from cli, so the two steps are skipped in every session, red: "session start in
    # forge ran ['scripts/sync/sync_agent_config.py', 'scripts/sync/sync_system_doc.py'], want
    # ['scripts/sync/relink_skills.py', 'scripts/sync/sync_gsd_runtime.py',
    # 'scripts/sync/sync_agent_config.py', 'scripts/sync/sync_system_doc.py']".
    forge_dir, forge_prof = os.path.join(dev, "forge"), os.path.join(prof_dir, "forge.claude.json")
    os.makedirs(forge_dir)
    with open(forge_prof, "w") as f:
        f.write('{"project_path": "%s"}' % forge_dir)
    del ran[:]
    os.environ["CLAUDE_PROJECT_DIR"] = forge_dir
    with contextlib.redirect_stdout(io.StringIO()):
        cli.cmd_session_start(None)
    os.environ.pop("CLAUDE_PROJECT_DIR")
    os.remove(forge_prof)
    os.rmdir(forge_dir)
    every = ["scripts/sync/relink_skills.py", "scripts/sync/sync_gsd_runtime.py"] + project_steps
    if ran != every:
        failures.append("session start in forge ran %r, want %r" % (ran, every))

    # A profile lib.profiles() leaves out is named at every session start. Left out silently, a
    # session in that project resolved to no project (or to a shallower one) and synced nothing
    # with no sign why. Red before: "session start beside an unreadable profile showed ''".
    broken = os.path.join(prof_dir, "broken.claude.json")
    with open(broken, "w") as f:
        f.write("null")
    lib.run = lambda args, capture=False, env=None: subprocess.CompletedProcess(args, 0, "", "")
    os.environ["CLAUDE_PROJECT_DIR"] = os.path.join(dev, "app")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cli.cmd_session_start(None)
    os.environ.pop("CLAUDE_PROJECT_DIR")
    os.remove(broken)
    msg = json.loads(out.getvalue() or "{}").get("systemMessage", "")
    if "broken.claude.json" not in msg:
        failures.append("session start beside an unreadable profile showed %r" % msg)
    lib.run = real_run

    more = 0
    for part in (read_cases, profile_type_cases, holds_cases, write_cases, git_cases, symlink_cases,
                 record_cases, cli_test_cases, settings_cases):
        f, n = part(tmp)
        failures += f
        more += n

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over %d cases" % (len(failures), len(cases) + len(sessions) + len(scopes) + len(bad) + len(wt) + len(guard) + 8 + more))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
