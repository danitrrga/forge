#!/usr/bin/env python3
"""skills.write_settings_local prunes from <project>/.claude/settings.local.json what the profile no
longer declares (step 10, increment I2, task T2). It records, per file, each permissions allow/deny/ask
rule, each additionalDirectories entry and each profile hook entry it wrote (forge/owned.py), so the next
run can tell its own leftovers from the user's in-session approvals and take out only the former. An
element forge never claimed is never touched; with no previous record nothing is pruned; a hook entry
edited by hand after it was written stays and is named on a '  ! ' line; a dry-run prunes nothing on
disk, does not write the registry, and says ', pruned N' in the pending ('would write') line.

Runs in-process against a toy HOME and toy projects; the fake token is the one a toy profile's env
resolves, and the registry must never hold it. lib.may_write() is stubbed to allow, because this
checkout may be a linked worktree, which never writes.

Seen failing on bcab228 (write_settings_local only adds), 19 of 37 checks red; the first two:
  FAIL allow: X is claimed -- {}
  FAIL allow rule removed from the profile: X is gone -- X still in the file: ['Bash(x:*)', 'Bash(z:*)', 'Bash(y:*)']
and likewise: additionalDirectories entry stays, hook entry stays, no ', pruned 1' in the line, the
dry-run's 'would write' line has no ', pruned 1', no claim recorded, the registry never written.
Negative controls on the finished code, each put back from a copy of forge/skills.py: see the commit
message that added this file."""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("owned-settings-local-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
from forge import cli, lib, owned, skills  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")

APPLY = lib.Ctx(True, None, False)
DRY = lib.Ctx(False, None, False)
FAKE_TOKEN = "fake-settings-local-token-4e7b-NOT-REAL"
REGISTRY = owned.path()
HOOK = {"type": "command", "command": "python3 /opt/toy/hooks/audit.py", "timeout": 10}
HOOK2 = {"type": "command", "command": "python3 /opt/toy/hooks/track.py", "timeout": 10}

failures, n_checks, n_proj = [], [0], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", detail)


def project(settings=None):
    n_proj[0] += 1
    p = os.path.join(TOY, "proj%d" % n_proj[0])
    os.makedirs(os.path.join(p, ".claude"))
    if settings is not None:
        lib.write_json(slp(p), settings)
    return p


def slp(p):
    return os.path.join(p, ".claude", "settings.local.json")


def doc(p):
    with open(slp(p), encoding="utf-8") as fh:
        return json.load(fh)


def run(p, ctx=APPLY, **keys):
    """(the line, what the call printed): a toy profile of `keys`, always with the fake token in env."""
    prof = dict({"project": "toy", "project_path": p, "env": {"TOKEN": "${FAKE_TOKEN}"}}, **keys)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        line = skills.write_settings_local(ctx, prof, {"FAKE_TOKEN": FAKE_TOKEN}, [])
    return line, out.getvalue()


def drop_registry():
    if os.path.exists(REGISTRY):
        os.remove(REGISTRY)


def slurp(file):
    return open(file, "rb").read() if os.path.exists(file) else b""


def claimed(p):
    return {(c["kind"], tuple(c["at"])): c for c in owned.previous(slp(p))[0]}


def perms(**k):
    return {"permissions": k}


# 1. An allow rule: written and claimed; taken out of the profile, it goes; the user's own stays.
drop_registry()
p = project()
line, _ = run(p, **perms(allow=["Bash(x:*)", "Bash(z:*)"]))
check("allow: X is in the file", "Bash(x:*)" in doc(p)["permissions"]["allow"], doc(p))
check("allow: X is claimed", ("item", ("permissions", "allow", "Bash(x:*)")) in claimed(p), claimed(p))
check("allow: the claim's owner is the profile", all(c["owner"] == "toy" for c in claimed(p).values()), claimed(p))
check("allow: a first run prunes nothing", ", pruned" not in line, line)
d = doc(p)
d["permissions"]["allow"].append("Bash(y:*)")  # the user's in-session approval
lib.write_json(slp(p), d)
line, _ = run(p, **perms(allow=["Bash(z:*)"]))
check("allow rule removed from the profile: X is gone", "Bash(x:*)" not in doc(p)["permissions"]["allow"],
      "X still in the file: %s" % doc(p)["permissions"]["allow"])
check("allow: the user's rule Y stays", "Bash(y:*)" in doc(p)["permissions"]["allow"], doc(p))
check("allow: the still-declared rule Z stays", "Bash(z:*)" in doc(p)["permissions"]["allow"], doc(p))
check("allow: the line says pruned 1", ", pruned 1)" in line, line)
check("allow: the claim for X is gone", ("item", ("permissions", "allow", "Bash(x:*)")) not in claimed(p), claimed(p))
line2, _ = run(p, **perms(allow=["Bash(z:*)"]))
check("allow: a second run is already current and prunes nothing", "already current" in line2 and "pruned" not in line2, line2)

# 2. deny and ask are claimed the same way; an emptied list leaves no key behind.
drop_registry()
p = project()
run(p, **perms(deny=["Bash(rm:*)"], ask=["Bash(git push:*)"], allow=["Bash(a:*)"]))
run(p, **perms(allow=["Bash(a:*)"]))
check("deny and ask: both go, no empty list left", set(doc(p)["permissions"]) == {"allow"}, doc(p)["permissions"])

# 3. additionalDirectories, the entry 'granted for good'.
drop_registry()
p = project()
run(p, **perms(allow=["Bash(a:*)"], additionalDirectories=["/opt/toy/one", "/opt/toy/two"]))
check("dirs: written and claimed", doc(p)["permissions"]["additionalDirectories"] == ["/opt/toy/one", "/opt/toy/two"]
      and ("item", ("permissions", "additionalDirectories", "/opt/toy/one")) in claimed(p), doc(p))
run(p, **perms(allow=["Bash(a:*)"], additionalDirectories=["/opt/toy/two"]))
check("dirs: an entry taken out of the profile goes", doc(p)["permissions"]["additionalDirectories"] == ["/opt/toy/two"], doc(p))
d = doc(p)
d["permissions"]["additionalDirectories"].append("/opt/user/own")
lib.write_json(slp(p), d)
line, _ = run(p, **perms(allow=["Bash(a:*)"]))
check("dirs: the key gone from the profile takes its entry, not the user's",
      doc(p)["permissions"].get("additionalDirectories") == ["/opt/user/own"], doc(p))
check("dirs: says pruned 1", ", pruned 1)" in line, line)

# 4. Hooks: a profile hook entry goes when undeclared and unchanged; an edited one stays and is named.
drop_registry()
p = project()
run(p, hooks={"PostToolUse": [{"hooks": [HOOK, HOOK2]}]})
check("hooks: written and claimed", len(doc(p)["hooks"]["PostToolUse"][0]["hooks"]) == 2
      and ("hook", ("hooks", "PostToolUse", HOOK["command"])) in claimed(p), doc(p))
d = doc(p)
d["hooks"]["PostToolUse"][0]["hooks"][1]["timeout"] = 99  # edited by hand after it was written
d["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "echo user"}]}]
lib.write_json(slp(p), d)
line, printed = run(p, hooks={})
left = [h["command"] for g in doc(p).get("hooks", {}).get("PostToolUse", []) for h in g["hooks"]]
check("hooks: the unchanged entry goes", HOOK["command"] not in left, "still in the file: %s" % left)
check("hooks: the edited entry stays", HOOK2["command"] in left, left)
check("hooks: the edited entry is named on a '  ! ' line", any(
    l.startswith("  ! ") and HOOK2["command"] in l and "settings.local.json" in l for l in printed.splitlines()), printed)
check("hooks: the user's own hook stays", doc(p)["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo user", doc(p))
check("hooks: says pruned 1", ", pruned 1)" in line, line)

# 5. A group, an event and the hooks key emptied by the run are removed with it.
drop_registry()
p = project()
run(p, hooks={"Stop": [{"hooks": [HOOK]}]}, **perms(allow=["Bash(a:*)"]))
run(p, **perms(allow=["Bash(a:*)"]))
check("hooks: an emptied event and hooks key are removed", "hooks" not in doc(p), doc(p))

# 6. A profile that dropped everything it declared still prunes (no early return).
drop_registry()
p = project()
run(p, env=None, **perms(allow=["Bash(x:*)"]))  # no env key: nothing else keeps the run going
run(p, env=None)
check("nothing declared any more: the rule still goes", "Bash(x:*)" not in json.dumps(doc(p).get("permissions", {})), doc(p))

# 7. No registry: nothing is pruned, and the run records the claims.
drop_registry()
p = project({"permissions": {"allow": ["Bash(old:*)"]}})
line, _ = run(p, **perms(allow=["Bash(new:*)"]))
check("no registry: nothing is pruned", doc(p)["permissions"]["allow"] == ["Bash(old:*)", "Bash(new:*)"]
      and "pruned" not in line, (doc(p), line))
check("no registry: the run records its claims", os.path.exists(REGISTRY) and bool(claimed(p)), claimed(p))

# 8. A rule forge never claimed is never touched, through two runs.
drop_registry()
p = project({"permissions": {"allow": ["Bash(mine:*)"]}})
run(p, **perms(allow=["Bash(x:*)"]))
run(p, **perms(allow=["Bash(q:*)"]))
check("unclaimed: the user's rule stays through two runs", "Bash(mine:*)" in doc(p)["permissions"]["allow"], doc(p))

# 9. A dry-run prunes nothing on disk, does not write the registry, and says pruned in its pending form.
drop_registry()
p = project()
run(p, **perms(allow=["Bash(x:*)", "Bash(z:*)"]))
before_file, before_reg = open(slp(p), "rb").read(), slurp(REGISTRY)
line, _ = run(p, DRY, **perms(allow=["Bash(z:*)"]))
check("dry-run: the file is untouched", open(slp(p), "rb").read() == before_file)
check("dry-run: the registry is untouched", slurp(REGISTRY) == before_reg and before_reg != b"", "registry missing or changed")
check("dry-run: 'would write' with ', pruned 1'", line.lstrip().startswith("would write") and ", pruned 1)" in line, line)
check("dry-run: forge doctor's pending-write detection sees it", cli.pending_writes([line]) == 1, line)
drop_registry()
run(project(), DRY, **perms(allow=["Bash(x:*)"]))
check("dry-run on a first run: no registry written", not os.path.exists(REGISTRY), REGISTRY)

# 10. The registry never holds a secret the toy profile resolves into env.
drop_registry()
p = project()
run(p, hooks={"Stop": [{"hooks": [HOOK]}]}, **perms(allow=["Bash(x:*)"]))
check("the file received the secret (the control for the next check)", doc(p)["env"]["TOKEN"] == FAKE_TOKEN, doc(p))
check("the registry holds no secret value", slurp(REGISTRY) != b"" and FAKE_TOKEN.encode() not in slurp(REGISTRY),
      "the registry is missing, or holds it")
# Since the key claims (test_owned_settings_keys.py) env IS claimed, as a key, and only by its digest.
check("the env claim keeps only a digest", set(claimed(p).get(("key", ("env",)), {})) == {"kind", "at", "sum", "owner"}, claimed(p))

# 11. A broken registry prunes nothing and its warning is printed.
p = project()
run(p, **perms(allow=["Bash(x:*)"]))
os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
with open(REGISTRY, "w") as fh:
    fh.write("{not json")
line, printed = run(p, **perms(allow=["Bash(z:*)"]))
check("broken registry: nothing pruned", "Bash(x:*)" in doc(p)["permissions"]["allow"] and "pruned" not in line, (doc(p), line))
check("broken registry: the warning is printed", "  ! could not read" in printed, printed)

# 12. A profile that declares nothing, with no record, leaves the file alone (None).
drop_registry()
p = project()
check("nothing declared, no record: None",
      skills.write_settings_local(APPLY, {"project": "toy", "project_path": p}, {}, []) is None)

# 13. cli.settings_forge_would_write (the frozen drift row) computes the document in memory, with
# write_json swapped for a recorder and apply true: the registry is not written, and the document it
# returns is the settings file's, not the registry's.
lib.SETTINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "config", "forge.json")
drop_registry()
p = project()
doc_in_memory = cli.settings_forge_would_write(
    "toy", {"project": "toy", "project_path": p, "permissions": {"allow": ["Bash(x:*)"]}}, {})
check("in-memory computation: the document is the settings file's",
      isinstance(doc_in_memory, dict) and doc_in_memory.get("permissions") == {"allow": ["Bash(x:*)"]}
      and "claims" not in doc_in_memory and "version" not in doc_in_memory, doc_in_memory)
check("in-memory computation: the registry is not written", not os.path.exists(REGISTRY), REGISTRY)
check("in-memory computation: the file is not written", not os.path.exists(slp(p)), slp(p))

# 14. A hand-edited `permissions` of the wrong shape is left alone and named, the rest of the profile still written,
# and nothing is claimed for what was not merged. Red on 34c191b: write_settings_local raised "AttributeError: 'list'
# object has no attribute 'get'" at cur[k] = list(dict.fromkeys((cur.get(k) or []) + ...)), which ends sync's loop over
# every later profile. The control: a well-formed file is merged as before (sections 1 to 13).
def run_errors(p, **keys):
    errors = []
    prof = dict({"project": "toy", "project_path": p, "env": {"A": "1"}}, **keys)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            line = skills.write_settings_local(APPLY, prof, {}, errors)
    except Exception as e:  # a crash is a red check, not a traceback
        return "raised %s: %s" % (type(e).__name__, e), errors
    return line, errors


drop_registry()
p = project({"permissions": ["not", "an", "object"]})
line, errors = run_errors(p, **perms(allow=["Bash(ls)"]))
check("permissions not an object: no crash", not line.startswith("raised"), line)
check("permissions not an object: left alone", doc(p).get("permissions") == ["not", "an", "object"], doc(p))
check("permissions not an object: named on a '!' line", any("permissions" in e and "not an object" in e for e in errors), errors)
check("permissions not an object: the rest of the profile is written", doc(p).get("env") == {"A": "1"}, doc(p))
check("permissions not an object: nothing is claimed for the rules", not any(k[0] == "item" for k in claimed(p)), claimed(p))
p = project({"permissions": {"allow": "Bash(ls)", "deny": ["Bash(rm:*)"]}})
line, errors = run_errors(p, **perms(allow=["Bash(pwd)"], deny=["Bash(dd:*)"]))
check("an allow that is not a list: no crash", not line.startswith("raised"), line)
check("an allow that is not a list: left alone and named", doc(p)["permissions"]["allow"] == "Bash(ls)"
      and any("allow" in e for e in errors), (doc(p), errors))
check("an allow that is not a list: the deny list is still merged", doc(p)["permissions"]["deny"] == ["Bash(rm:*)", "Bash(dd:*)"], doc(p))

# 15. Without a resolved secret the write keeps the file's own mode and gives the once-ever .bak the same: it wrote
# at the umask default and widened a settings.local.json the user kept 0600. Red on 34c191b: "FAIL a 0600 file
# with no secret stays 0600 -- (644, 644)". Controls: a 0644 file stays 0644; a file with a secret is 0600 as before.
for first in (0o600, 0o644):
    drop_registry()
    p = project({"permissions": {"allow": ["Bash(old)"]}})
    os.chmod(slp(p), first)
    run_errors(p, **perms(allow=["Bash(ls)"]))
    got = (os.stat(slp(p)).st_mode & 0o777, os.stat(slp(p) + ".bak").st_mode & 0o777)
    check("a %o file with no secret stays %o, and so does its .bak" % (first, first), got == (first, first),
          "(%o, %o)" % got)
drop_registry()
p = project({"permissions": {"allow": ["Bash(old)"]}})
os.chmod(slp(p), 0o644)
run(p, **perms(allow=["Bash(ls)"]))
check("a file that now holds a secret is 0600", os.stat(slp(p)).st_mode & 0o777 == 0o600, oct(os.stat(slp(p)).st_mode))

print("%d checks, %d failed" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
