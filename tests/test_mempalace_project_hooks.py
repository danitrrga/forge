#!/usr/bin/env python3
"""A project that uses MemPalace gets its Claude Code hooks in its own .claude/settings.local.json and
nowhere else. A project uses it when its `servers` list holds `mempalace` (derived, no project field). With
the `mempalace` integration on, three rows (Stop, SessionEnd, PreCompact, each running one of the scripts
under hooks/mempalace/) land there through skills.write_settings_local; no SessionStart row, the
measurement of 7.1 U1 found retrieval hits 3 of 3 without it. Off, or with the line gone, the entries a run
wrote before are removed by their exact command, and a foreign hook is never touched. The doctor's
session-start row (memory_doctor.py) belongs to either memory integration. The copied scripts are the upstream
files byte for byte: their sha256 is in hooks/mempalace/NOTICE.md and a test compares it.

Runs in-process against a toy forge.json (lib.SETTINGS), a toy HOME and toy projects; nothing real is
written. The script cases run the copied files with a fake `mempalace` and a PATH that holds only the fake
directory.

Seen failing on cc2a8ef (no mempalace rows, SCOPES without "mempalace", no hooks/mempalace/), 19 of 34 checks red (the
other 15 are controls true before as after; one of the 19, "nothing of MemPalace in USER_HOOKS", was red by a bug of this
file, a match on "mempal" in a worktree path, fixed afterwards and shown red by mutation M4 below), messages kept:
  on: a mempalace project's settings.local.json gains the Stop row -- Stop [] (SessionEnd [] and PreCompact [] the same; the
    line says nothing of the rows; a project that declares only the server is not written: line None, file None)
  on: the doctor's would-write for a mempalace project not yet written holds the rows -- would write None
  both on: a project that lists both servers gets both sets -- the file held only the two Hindsight rows
  on: a foreign hook on the same event stays beside the row -- Stop [foreign hook only]
  off, server dropped: the seeded rows go -- the file still held the three commands (the old code never owned them)
  user scope loses a MemPalace command by its exact text -- the Stop and SessionEnd commands stayed in the user-scope doc
  scope mempalace: lands only in the MemPalace project -- mp [], plain []
  memory_doctor.py: hindsight off and mempalace on, the row is written -- (live, taken out) (False, True)
  hooks/mempalace: every script matches the sha256 NOTICE.md records -- looked at 0 script(s), problems ['NOTICE.md is not there']
  hooks/mempalace: the four scripts are there -- missing [all four]
  the script cases ran -- bash '/usr/bin/bash', scripts dir exists False: nothing was looked at
Review round of PR 179 (head ccebfd5): the owner check below ("MemPalace's rows are claimed by [None]" on that code, 2 red) and
the SessionEnd timing check, which was a clock (`took < 1.5`) and is now a mark file: with the `&` taken off the real script
it reads "TimeoutExpired: ... timed out after 30 seconds" (the save waits for a release file the test creates after the return).
Negative controls on the finished code, each put back from the committed file (red count of 40 checks; the first red line):
  M1 SCOPES["mempalace"] removed -- 14 red: "on: a mempalace project's settings.local.json gains the Stop row -- Stop [];
    line ('raised', 'KeyError', \"'mempalace'\")"
  M2 the three mempalace markers out of ROW_INTEGRATION -- 4 red: "off: the row goes and the foreign hook stays -- Stop
    [foreign hook, the mempalace command]"
  M3 memory_doctor.py's ROW_INTEGRATION value back to "hindsight" -- 1 red: "memory_doctor.py: hindsight off and mempalace on,
    the row is written -- (live, taken out) (False, True)"
  M4 a mempalace row in the user-scope table -- 1 red: "on: nothing of MemPalace in USER_HOOKS (user scope)"
  M5 a SessionStart row added to the three -- 7 red, among them "on: no SessionStart row (retrieval hit 3 of 3 without it)"
  inside this file, on a toy copy of the scripts: a byte added to a script -- 'sha256 differs'; NOTICE.md removed -- 'NOTICE.md
    is not there' with 0 looked at; the SessionEnd script with its `&` taken off -- 'without the `&` the SessionEnd script waits
    for the save' (took 3.0 s)"""
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

REPO = sandbox.FORGE
TOY = sandbox.mkdtemp("mempalace-project-hooks-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.path.insert(0, REPO)
from forge import lib  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
INTEGRATIONS = {"codex": False, "gsd": False, "hindsight": False, "mempalace": True}
lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": INTEGRATIONS}, fh)
from forge import cli, hooks, skills  # noqa: E402

APPLY = lib.Ctx(True, None, False)
SERVER = "mempalace"
HS_SERVER = "hindsight-coding-agents"
SCRIPT_DIR = os.path.join(REPO, "hooks", "mempalace")
failures, n_cases = [], [0]


def check(label, ok, detail=""):
    n_cases[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))


def attempt(fn, *a, **k):
    try:
        return fn(*a, **k)
    except SystemExit as e:
        return ("exit", str(e))
    except Exception as e:  # a missing feature is a red check, not a traceback
        return ("raised", type(e).__name__, str(e))


def toy_settings(n, **over):
    doc = {"integrations": dict(INTEGRATIONS), "gsd_patches": True, "house_hooks": True, "user_settings": {},
           "user_hooks": []}
    doc.update(over)
    path = os.path.join(TOY, "forge-%d.json" % n)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()
    return attempt(importlib.reload, hooks)


def project(name, servers, **extra):
    p = os.path.join(TOY, "projects", name)
    os.makedirs(os.path.join(p, ".claude"), exist_ok=True)
    return dict({"project": name, "project_path": p, "servers": servers}, **extra)


def slp(prof):
    return os.path.join(prof["project_path"], ".claude", "settings.local.json")


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def raw(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def write(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def entries(doc, event):
    return [(h.get("command"), g.get("matcher"), h.get("timeout")) for g in ((doc or {}).get("hooks") or {}).get(event, [])
            for h in g.get("hooks", [])]


def all_commands(doc):
    return {c for ev in ((doc or {}).get("hooks") or {}) for c, _, _ in entries(doc, ev)}


def run(prof):
    """write_settings_local with the rows forge/sync.py hands it."""
    rows = attempt(hooks.project_hooks, prof) if hasattr(hooks, "project_hooks") else ()
    if isinstance(rows, tuple) and rows and rows[0] in ("raised", "exit"):
        return rows
    return attempt(skills.write_settings_local, APPLY, prof, None, None, rows)


def group(cmd, timeout):
    return {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}


def mp_cmd(name):
    return 'bash "%s"' % os.path.join(REPO, "hooks", "mempalace", name)


STOP_CMD, END_CMD, PRE_CMD = (mp_cmd("mempal-stop-hook.sh"), mp_cmd("mempal-session-end-hook.sh"),
                              mp_cmd("mempal-precompact-hook.sh"))
ROWS = {STOP_CMD, END_CMD, PRE_CMD}
HS_UP = 'node "%s/claude-hook.js"' % os.path.join(HOME, ".hindsight", "coding-agents", "dist")
HS_STOP = 'node "%s/claude-stop-hook.js"' % os.path.join(HOME, ".hindsight", "coding-agents", "dist")
FOREIGN = "node /opt/herdr/notify.js"
SEEDED = {"permissions": {"allow": ["Bash(ls)"]},
          "hooks": {"Stop": [group(STOP_CMD, 30)], "SessionEnd": [group(END_CMD, 10)], "PreCompact": [group(PRE_CMD, 90)]}}

# 1. Integration on. A MemPalace project's file gains the three rows, a second run leaves it as it is, a
# project without the line gets none and its file does not change by a byte, one that declares nothing else
# is still written.
toy_settings(1)
mp = project("mp", [SERVER, "other"], permissions={"allow": ["Bash(ls)"]})
bare = project("bare", [SERVER])
plain = project("plain", ["other"], permissions={"allow": ["Bash(ls)"]})
line = run(mp)
doc = read(slp(mp))
check("on: a mempalace project's settings.local.json gains the Stop row", entries(doc, "Stop") == [(STOP_CMD, None, 30)],
      "Stop %r; line %r" % (entries(doc, "Stop"), line))
check("on: it gains the SessionEnd row", entries(doc, "SessionEnd") == [(END_CMD, None, 10)], "SessionEnd %r" % (entries(doc, "SessionEnd"),))
check("on: it gains the PreCompact row", entries(doc, "PreCompact") == [(PRE_CMD, None, 90)], "PreCompact %r" % (entries(doc, "PreCompact"),))
check("on: no SessionStart row (retrieval hit 3 of 3 without it)", "SessionStart" not in (doc or {}).get("hooks", {}),
      "hooks %r" % ((doc or {}).get("hooks"),))
check("on: the line says so", isinstance(line, str) and all(("%s on" % m) in line for m in (
    "mempal-stop-hook.sh Stop", "mempal-session-end-hook.sh SessionEnd", "mempal-precompact-hook.sh PreCompact")), "line %r" % (line,))
# Who claims each row (the uninstall worlds of tests/test_uninstall.py take them by integration). Red on ccebfd5, where
# project_hooks carried no owner and skills.py claimed every row as "hindsight": "MemPalace's rows are claimed by [None]".
prows = attempt(hooks.project_hooks, mp)
owners = {r[1]: (r[6] if len(r) > 6 else None) for r in prows} if isinstance(prows, list) else {}
check("on: MemPalace's three rows are claimed by mempalace", {owners.get(c) for c in ROWS} == {"mempalace"} and len(owners) >= 3,
      "MemPalace's rows are claimed by %r" % (sorted({owners.get(c) for c in ROWS}, key=str),))
check("on: Hindsight's rows are claimed by hindsight (control)", {owners.get(c) for c in (HS_UP, HS_STOP)} == {"hindsight"},
      "owners %r" % (sorted(set(owners.values())),))
before = raw(slp(mp))
again = run(mp)
check("on: a second run is already current", isinstance(again, str) and "already current" in again and raw(slp(mp)) == before,
      "line %r" % (again,))
line = run(bare)
check("on: a mempalace project that declares nothing else is still written", entries(read(slp(bare)), "Stop") == [(STOP_CMD, None, 30)],
      "line %r, file %r" % (line, read(slp(bare))))
run(plain)
check("on: a project without the line gets none (control)", not (ROWS & all_commands(read(slp(plain)))), "file %r" % (read(slp(plain)),))
base_bytes = raw(slp(plain))
toy_settings(2, integrations=dict(INTEGRATIONS, mempalace=False))
run(plain)
off_bytes = raw(slp(plain))
toy_settings(3)
run(plain)
check("a project without the line: its settings.local.json is byte-identical with the switch on and off",
      base_bytes is not None and base_bytes == off_bytes == raw(slp(plain)),
      "on %r, off %r, on again %r" % (base_bytes, off_bytes, raw(slp(plain))))
claude_rows = [r for r in hooks.USER_HOOKS if "/hooks/mempalace/" in r[1]]  # not "mempal": a worktree can be named for it
check("on: nothing of MemPalace in USER_HOOKS (user scope)", not claude_rows, "rows %r" % (claude_rows,))
want = attempt(cli.settings_forge_would_write, "mp", mp, {})
check("on: the doctor's would-write matches the file after the run (None: nothing to write)", want is None, "would write %r" % (want,))
unwritten = project("unwritten", [SERVER])
want = attempt(cli.settings_forge_would_write, "unwritten", unwritten, {})
check("on: the doctor's would-write for a mempalace project not yet written holds the rows",
      isinstance(want, dict) and entries(want, "Stop") == [(STOP_CMD, None, 30)] and not os.path.exists(slp(unwritten)),
      "would write %r" % (want,))

# 2. One memory system per project: a Hindsight project gets no MemPalace row and a MemPalace project no
# Hindsight one, with both integrations on.
toy_settings(4, integrations=dict(INTEGRATIONS, hindsight=True))
hs = project("hs", [HS_SERVER])
both = project("both", [HS_SERVER, SERVER])
run(hs)
run(mp)
check("both on: a Hindsight project gets no MemPalace row", not (ROWS & all_commands(read(slp(hs)))), "file %r" % (read(slp(hs)),))
check("both on: a Hindsight project still gets its own rows", {HS_UP, HS_STOP} <= all_commands(read(slp(hs))), "file %r" % (read(slp(hs)),))
check("both on: a MemPalace project gets no Hindsight row", not ({HS_UP, HS_STOP} & all_commands(read(slp(mp)))), "file %r" % (read(slp(mp)),))
run(both)
check("both on: a project that lists both servers gets both sets (the doctor's one-backend row is U3's to flag)",
      (ROWS | {HS_UP, HS_STOP}) <= all_commands(read(slp(both))), "file %r" % (read(slp(both)),))

# 3. A foreign hook on the same events stays; a project's own `hooks` that names the same command keeps it.
toy_settings(5)
fx = project("fx", [SERVER], hooks={"Stop": [group(FOREIGN, 5)]})
run(fx)
doc = read(slp(fx))
check("on: a foreign hook on the same event stays beside the row", (FOREIGN, None, 5) in entries(doc, "Stop") and (STOP_CMD, None, 30) in entries(doc, "Stop"),
      "Stop %r" % (entries(doc, "Stop"),))
toy_settings(6, integrations=dict(INTEGRATIONS, mempalace=False))
run(fx)
check("off: the row goes and the foreign hook stays", entries(read(slp(fx)), "Stop") == [(FOREIGN, None, 5)], "Stop %r" % (entries(read(slp(fx)), "Stop"),))
declared = project("declared", ["other"], hooks={"Stop": [group(STOP_CMD, 30)]})
run(declared)
check("a project `hooks` entry with the same command is never taken out",
      entries(read(slp(declared)), "Stop") == [(STOP_CMD, None, 30)], "Stop %r" % (entries(read(slp(declared)), "Stop"),))

# 4. Integration off: nobody gets them, the entries an earlier run wrote go (seeded here as that run leaves
# them), user scope loses them too; the line leaves the project: the same.
write(slp(mp), SEEDED)
write(slp(bare), {"hooks": SEEDED["hooks"]})
line = run(mp)
doc = read(slp(mp))
check("off: nobody gets them, the seeded rows go", not (ROWS & all_commands(doc)) and (doc or {}).get("permissions"), "file %r, line %r" % (doc, line))
check("off: the line counts what it took out", isinstance(line, str) and line.count("entries removed 1") == 3, "line %r" % (line,))
run(bare)
check("off: a project that declared only the server loses them too", not (ROWS & all_commands(read(slp(bare)))),
      "file %r" % (read(slp(bare)),))
user = {"hooks": {"Stop": [group(STOP_CMD, 30), group(FOREIGN, 5)], "SessionEnd": [group(END_CMD, 10)]}}
attempt(hooks.reconcile, user, hooks.CLAUDE)
check("user scope loses a MemPalace command by its exact text, the foreign hook stays",
      not (ROWS & all_commands(user)) and FOREIGN in all_commands(user), "%r" % (user,))
toy_settings(7)
write(slp(mp), SEEDED)
run(dict(mp, servers=["other"]))
check("server dropped: the rows a run wrote before go", not (ROWS & all_commands(read(slp(mp)))), "file %r" % (read(slp(mp)),))

# 5. A user_hooks row with "scope": "mempalace" is written per project, to MemPalace projects only.
AUDIT = {"event": "SessionStart", "command": "python3 <ROOT>/scripts/toy_wake.py", "timeout": 10, "marker": "toy_wake.py",
         "matcher": None, "agents": ["claude"], "scope": "mempalace"}
AUDIT_CMD = AUDIT["command"].replace("<ROOT>", lib.ROOT)
toy_settings(8, user_hooks=[AUDIT])
check("scope mempalace: the user_hooks row is not a user-scope row", AUDIT_CMD not in [r[1] for r in hooks.USER_HOOKS],
      "USER_HOOKS commands %r" % ([r[1] for r in hooks.USER_HOOKS][-3:],))
run(mp)
run(plain)
check("scope mempalace: lands only in the MemPalace project",
      entries(read(slp(mp)), "SessionStart") == [(AUDIT_CMD, None, 10)] and AUDIT_CMD not in all_commands(read(slp(plain))),
      "mp %r, plain %r" % (entries(read(slp(mp)), "SessionStart"), entries(read(slp(plain)), "SessionStart")))
toy_settings(9, user_hooks=[AUDIT], integrations=dict(INTEGRATIONS, mempalace=False))
run(mp)
check("scope mempalace off: no project gets it, the earlier entry goes", AUDIT_CMD not in all_commands(read(slp(mp))),
      "SessionStart %r" % (entries(read(slp(mp)), "SessionStart"),))

# 6. The doctor's session-start row belongs to either memory integration: it runs while hindsight OR mempalace is on.
def doctor_row_live(**on):
    h = toy_settings(30 + len(failures) + n_cases[0], integrations=dict(INTEGRATIONS, **on))
    if isinstance(h, tuple):
        return h
    live = any("memory_doctor.py" in r[1] for r in hooks.USER_HOOKS)
    wiped = any("memory_doctor.py" in r[1] for r in hooks.OFF_HOOKS)
    return live, wiped


got = doctor_row_live(hindsight=False, mempalace=True)
check("memory_doctor.py: hindsight off and mempalace on, the row is written", got == (True, False), "(live, taken out) %r" % (got,))
got = doctor_row_live(hindsight=True, mempalace=False)
check("memory_doctor.py: hindsight on and mempalace off, the row is written (control)", got == (True, False), "(live, taken out) %r" % (got,))
got = doctor_row_live(hindsight=True, mempalace=True)
check("memory_doctor.py: both on, one row", got == (True, False) and sum("memory_doctor.py" in r[1] for r in hooks.USER_HOOKS) == 1,
      "(live, taken out) %r" % (got,))
got = doctor_row_live(hindsight=False, mempalace=False)
check("memory_doctor.py: both off, the row is not written and is taken out by its command (control)", got == (False, True),
      "(live, taken out) %r" % (got,))

# 7. The scripts: upstream's files byte for byte, their sha256 in NOTICE.md; the rows run existing ones.
HEX = re.compile(r"\b[0-9a-f]{64}\b")
SCRIPTS = ("mempal-stop-hook.sh", "mempal-session-end-hook.sh", "mempal-precompact-hook.sh", "mempal_hook_run.sh")


def notice_problems(directory):
    """(problems, how many scripts looked at): every *.sh of `directory` must have a line in NOTICE.md that names
    it and carries its sha256, and every script NOTICE.md names must exist."""
    notice = os.path.join(directory, "NOTICE.md")
    if not os.path.isfile(notice):
        return ["NOTICE.md is not there"], 0
    with open(notice, encoding="utf-8") as fh:
        text = fh.read()
    problems, looked = [], 0
    for name in sorted(f for f in os.listdir(directory) if f.endswith(".sh")):
        looked += 1
        lines = [ln for ln in text.splitlines() if name in ln and HEX.search(ln)]
        digest = hashlib.sha256(raw(os.path.join(directory, name))).hexdigest()
        if not lines:
            problems.append("%s has no sha256 line in NOTICE.md" % name)
        elif not any(digest in ln for ln in lines):
            problems.append("%s: sha256 differs from NOTICE.md (file %s)" % (name, digest))
    if "copied-from:" not in text:
        problems.append("NOTICE.md has no copied-from line")
    return problems, looked


problems, looked = notice_problems(SCRIPT_DIR)
check("hooks/mempalace: every script matches the sha256 NOTICE.md records", not problems and looked == len(SCRIPTS),
      "looked at %d script(s), problems %r" % (looked, problems))
check("hooks/mempalace: the four scripts are there", all(os.path.isfile(os.path.join(SCRIPT_DIR, n)) for n in SCRIPTS),
      "missing %r" % ([n for n in SCRIPTS if not os.path.isfile(os.path.join(SCRIPT_DIR, n))],))
if os.path.isdir(SCRIPT_DIR):  # negative control: one flipped byte in a toy copy is found
    copy = os.path.join(TOY, "notice-copy")
    shutil.copytree(SCRIPT_DIR, copy)
    victim = os.path.join(copy, "mempal-stop-hook.sh")
    with open(victim, "ab") as fh:
        fh.write(b"#")
    problems, _ = notice_problems(copy)
    check("negative control: a byte added to a toy copy is reported", any("sha256 differs" in p for p in problems), "problems %r" % (problems,))
    os.remove(os.path.join(copy, "NOTICE.md"))
    problems, looked = notice_problems(copy)
    check("negative control: a missing NOTICE.md is reported, with nothing looked at", problems == ["NOTICE.md is not there"] and looked == 0,
          "problems %r, looked %d" % (problems, looked))

# 8. The scripts do what the rows need: SessionEnd returns at once while its save goes on in the background,
# and a missing mempalace never answers with the blocking exit code of a Stop hook (2).
BASH = shutil.which("bash")
FAKE = os.path.join(TOY, "fake-bin")
os.makedirs(FAKE)
for tool in ("cat", "sleep", "printf"):  # the system dirs are never on PATH (ORDERS 10): only what the scripts call
    src = shutil.which(tool)
    if src:
        os.symlink(src, os.path.join(FAKE, tool))
MARK = os.path.join(TOY, "mark")


def fake_mempalace(body):
    path = os.path.join(FAKE, "mempalace")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n" + body)
    os.chmod(path, 0o755)


def run_script(directory, name, payload=b'{"session_id": "toy"}'):
    t0 = time.monotonic()
    r = subprocess.run([BASH, os.path.join(directory, name)], input=payload, capture_output=True, timeout=30,
                       env={"PATH": FAKE, "HOME": HOME}, cwd=TOY)
    return r, time.monotonic() - t0


RELEASE = os.path.join(TOY, "release")


def slow_save(cap):
    """A fake mempalace whose save finishes only when RELEASE exists (or after `cap` seconds), then writes MARK. Which
    came first, the hook's return or the save's end, is then decided by the files and not by how fast this machine is."""
    for f in (MARK, RELEASE):
        if os.path.exists(f):
            os.remove(f)
    fake_mempalace('n=0\nwhile [ ! -e "%s" ] && [ $n -lt %d ]; do sleep 0.1; n=$((n+1)); done\nprintf done > "%s"\n'
                   % (RELEASE, cap * 10, MARK))


def end_hook_check(directory, label):
    slow_save(60)
    try:
        r, took = run_script(directory, "mempal-session-end-hook.sh")
    except (OSError, subprocess.SubprocessError) as e:
        check(label, False, "%s: %s" % (type(e).__name__, e))
        return
    # Red on ccebfd5 was a clock (`took < 1.5`, which a loaded machine can miss); the mark is the bound now: the hook
    # returned before the save could finish, because the save waits for a file only this test creates, after the return.
    check(label, r.returncode == 0 and r.stdout == b"{}" and not os.path.exists(MARK),
          "exit %d, stdout %r, mark present %r: the hook waited for the save" % (r.returncode, r.stdout, os.path.exists(MARK)))
    with open(RELEASE, "w") as fh:
        fh.write("go")
    for _ in range(300):  # the detached save finishes after the release: wait for it, so the toy dir can go
        if os.path.exists(MARK):
            break
        time.sleep(0.1)
    check(label + ": and the save still ran in the background", os.path.exists(MARK), "no mark after 30 s")


if BASH and os.path.isdir(SCRIPT_DIR):
    end_hook_check(SCRIPT_DIR, "the SessionEnd script returns at once ({}) and does not wait for the save")
    # negative control: the same script with the `&` taken off blocks for the three seconds of the fake save
    copy = os.path.join(TOY, "script-copy")
    shutil.copytree(SCRIPT_DIR, copy)
    path = os.path.join(copy, "mempal-session-end-hook.sh")
    text = raw(path).decode("utf-8")
    patched = text.replace("</dev/null &\n", "</dev/null\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(patched)
    slow_save(3)  # the save gives up waiting after 3 s: the patched hook, which waits for it, then returns with the mark written
    r, took = run_script(copy, "mempal-session-end-hook.sh")
    check("negative control: without the `&` the SessionEnd script waits for the save",
          patched != text and os.path.exists(MARK),
          "patched %s, mark present %r after %.1f s" % (patched != text, os.path.exists(MARK), took))
    os.remove(os.path.join(FAKE, "mempalace"))
    r, took = run_script(SCRIPT_DIR, "mempal-stop-hook.sh")
    check("a Stop hook with no mempalace on PATH fails without the blocking exit code",
          r.returncode == 1 and b"could not find a runnable mempalace" in r.stderr, "exit %d, stderr %r" % (r.returncode, r.stderr))
    fake_mempalace('printf "%s" "$*" > "' + MARK + '"\n')
    if os.path.exists(MARK):
        os.remove(MARK)
    r, took = run_script(SCRIPT_DIR, "mempal-stop-hook.sh")
    got = open(MARK).read() if os.path.exists(MARK) else None
    check("the Stop script runs `mempalace hook run --hook stop --harness claude-code`",
          r.returncode == 0 and got == "hook run --hook stop --harness claude-code", "exit %d, mempalace got %r, stderr %r" % (r.returncode, got, r.stderr))
else:
    check("the script cases ran", False, "bash %r, scripts dir exists %r: nothing was looked at" % (BASH, os.path.isdir(SCRIPT_DIR)))

sandbox.cleanup(bool(failures))
if failures:
    print("%d of %d checks failed" % (len(failures), n_cases[0]))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % n_cases[0])
