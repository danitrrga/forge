#!/usr/bin/env python3
"""forge doctor's `owned` row reads the hook claims of both writers. forge/hooks.py (user scope) records a
hook at [event, matcher, command]; forge/skills.py (a profile's hooks in <project>/.claude/settings.local.json)
records it at ["hooks", event, command], with no matcher. The row once read every 3-element hook claim in
the first layout, looked for the event "hooks" and WARNed on every profile hook nobody had touched.

Runs in-process against a toy HOME and a toy project; lib.may_write() is stubbed to allow, because this
checkout may be a linked worktree, which never writes.

Seen failing on af8a883 (owned_row reads every hook claim as [event, matcher, command]):
  FAIL after an unedited apply: PASS naming the claim and the file -- Result(level='WARN', name='owned', detail='changed since forge wrote them, so a sync leaves or repairs them: <toy>/.claude/settings.local.json ["hooks", "PostToolUse", "python3 /opt/toy/hooks/audit.py"]; looked at 1 claim(s) in 1 file(s)')
  FAIL a hook under another matcher, unedited: PASS -- (the same WARN)
The hand-edit and gone-from-the-file checks pass on that code for the wrong reason (the row WARNs on
everything); they are the negative control of the fix: a row that simply never compared would fail them."""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("owned-doctor-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
from forge import lib, owned  # noqa: E402
lib.SETTINGS = os.path.join(TOY, "forge.json")  # a toy forge.json: the worktree has none
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
from forge import cli, skills  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")

CMD = "python3 /opt/toy/hooks/audit.py"
HOOK = {"type": "command", "command": CMD, "timeout": 10}
failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", detail)


def apply(p, groups):
    prof = {"project": "toy", "project_path": p, "hooks": {"PostToolUse": groups}}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        skills.write_settings_local(lib.Ctx(True, None, False), prof, {}, [])


def row():
    r = cli.owned_row()
    return r, r.level, r.detail


p = os.path.join(TOY, "proj")
os.makedirs(os.path.join(p, ".claude"))
slp = os.path.join(p, ".claude", "settings.local.json")
at = json.dumps(["hooks", "PostToolUse", CMD])

# 1. Unedited, no matcher: PASS, and it looked at the claim.
apply(p, [{"hooks": [HOOK]}])
r, level, detail = row()
check("after an unedited apply: PASS naming the claim and the file -- %r" % (r,),
      level == "PASS" and "1 claim(s) in 1 file(s)" in detail, r)

# 2. Edited by hand: WARN naming the file and the `at`, no value.
with open(slp, encoding="utf-8") as fh:
    d = json.load(fh)
d["hooks"]["PostToolUse"][0]["hooks"][0]["timeout"] = 99
lib.write_json(slp, d)
r, level, detail = row()
check("a hand edit: WARN naming the file and the at -- %r" % (r,),
      level == "WARN" and lib.short(slp) in detail and at in detail, r)
check("a hand edit: the WARN names no value -- %r" % (r,), "99" not in detail, r)

# 3. A hook under a matcher the profile declared: PASS when unedited.
# (a fresh project and record: the edited entry of case 2 would stay beside the new one)
os.remove(owned.path())
p = os.path.join(TOY, "proj2")
os.makedirs(os.path.join(p, ".claude"))
slp = os.path.join(p, ".claude", "settings.local.json")
apply(p, [{"matcher": "Bash", "hooks": [dict(HOOK, timeout=5)]}])
r, level, detail = row()
check("a hook under another matcher, unedited: PASS -- %r" % (r,), level == "PASS", r)

# 4. Removed by hand from the file: the claim has no entry, WARN.
lib.write_json(slp, {"hooks": {}})
r, level, detail = row()
check("a hook gone from the file: WARN -- %r" % (r,), level == "WARN" and at in detail, r)

# 5. A claimed file is read and parsed once, whatever its number of claims. Red on 34c191b: the row called
# owned.current without the loaded document, so every claim re-read the file: "FAIL a file with 40 claims is read
# once -- 40 read(s)" (one per rule). Controls: the verdict is the same as before (PASS, the
# claims counted), and an edited rule is still named.
os.remove(owned.path())
p = os.path.join(TOY, "proj3")
os.makedirs(os.path.join(p, ".claude"))
slp = os.path.join(p, ".claude", "settings.local.json")
rules = ["Bash(r%d)" % i for i in range(40)]
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    skills.write_settings_local(lib.Ctx(True, None, False), {"project": "toy", "project_path": p,
                                                              "permissions": {"allow": rules}}, {}, [])
reads, real_read = [], lib.read_owned


def counting_read(path, *rest):
    reads.append(path)
    return real_read(path, *rest)


lib.read_owned = counting_read
try:
    r, level, detail = row()
finally:
    lib.read_owned = real_read
n = reads.count(slp)
check("a file with 40 claims is read once -- %d read(s)" % n, n == 1, n)
check("and the row still passes over every claim -- %r" % (r,), level == "PASS" and "40 claim(s) in 1 file(s)" in detail, r)
with open(slp, encoding="utf-8") as fh:
    d = json.load(fh)
d["permissions"]["allow"].remove("Bash(r7)")
lib.write_json(slp, d)
r, level, detail = row()
check("an edited rule is still named -- %r" % (r,), level == "WARN" and "Bash(r7)" in detail and "Bash(r8)" not in detail, r)

# 6. A claimed file that cannot be read is named once: the short path and the reason, not the path twice. Red on
# 34c191b: "FAIL ... named once -- 2 occurrence(s) in: could not read: ~/.../settings.local.json (<full path>
# unreadable (Expecting value: line 1 column 1 (char 0)))". Control: the reason is still there.
with open(slp, "w", encoding="utf-8") as fh:
    fh.write("{not json")
r, level, detail = row()
short = lib.short(slp)
check("an unreadable claimed file is named once -- %d occurrence(s) in: %s" % (detail.count(os.path.basename(os.path.dirname(os.path.dirname(slp)))), detail),
      level == "WARN" and detail.count(os.path.basename(os.path.dirname(os.path.dirname(slp)))) == 1, r)
check("and the reason is there", "Expecting" in detail and "could not read: %s (" % short in detail, r)

print("%d checks, %d failed" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
