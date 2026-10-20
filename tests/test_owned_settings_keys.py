#!/usr/bin/env python3
"""skills.write_settings_local and skills.mirror_for_codex claim more of what they write (step 10,
increment I3, task T1), so a coming `forge uninstall` can take out everything forge put in a project's
settings.local.json and in the ignore file it edited. Beyond the permission items and profile hooks of
test_owned_settings_local.py, a run now also claims (forge/owned.py), owner the profile's name unless said:
  kind key  ["skillOverrides"], ["enabledPlugins"], ["env"] (hash only: it holds resolved secrets),
            ["permissions", k] for each non-list key forge writes (defaultMode), and
            ["enableAllProjectMcpServers"], ["enabledMcpjsonServers"], ["disabledMcpjsonServers"]
  kind hook ["hooks", event, command], owner "hindsight", for each per-project row forge keeps (project_hooks)
  kind item ["line", entry] on the .gitignore (or .git/info/exclude) forge added `.agents/` to, part "skills";
            a line that was already there is never claimed, and a claim stays while the line stays.
Only what forge writes in that run is claimed (a key the profile does not declare is not). A key claim is never
pruned by sync (those keys already go by declaration). The registry never holds the secret, a dry-run records
nothing, and a hand-edited env is no longer removable.

Runs in-process against a toy HOME and toy projects; lib.may_write() is stubbed to allow, because this checkout
may be a linked worktree, which never writes.

Seen failing on 78d36ba (this file against that commit's forge/skills.py), 19 of 50 checks red; the first
ones, one per claim:
  FAIL missing claim key ['skillOverrides'] -- present: [...]
  FAIL missing claim key ['enabledPlugins']
  FAIL missing claim key ['env']
  FAIL missing claim key ['permissions', 'defaultMode']
  FAIL missing claim key ['enableAllProjectMcpServers'] (and the two mcpjson lists)
  FAIL missing claim hook ['hooks', 'UserPromptSubmit', 'node /opt/toy/hs.js']
  FAIL missing claim item ['line', '.agents/'] on the .gitignore, and on the exclude file in the repo-owned case
and the checks that read them after: owner, the digest of the value written, removable() of an unedited and an
edited env, the claim kept on a second apply.
The controls that pass there on purpose: no secret in the registry, a dry-run records nothing, a line that was
already there is not claimed, a key the profile does not declare is not claimed. A Hindsight row deleted from the
code is now taken out through its claim (before: left firing), and one edited by hand is named; both are red there.
Negative controls on the finished code (74 checks), each mutation put back from a copy of forge/skills.py, each
seen red: skillOverrides, enabledPlugins, permissions key, each of the three mcpjson claims and the hook row's claim
dropped (1 red each, 3 for the row); env claiming the unresolved profile value (2: the sum is not the digest of what
was written); the row's owner not hindsight (1); a row claimed though it was not merged (1); an existing .agents/
line claimed (1); the claim dropped by a run that adds nothing (3); the part's other claims not kept in a shared
exclude file (2); the claim recorded in a dry-run (1); no exclude file ever looked for (5); the prune loop acting
on key claims (4)."""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("owned-settings-keys-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(os.path.join(HOME, ".claude", "skills", "g1"))
os.makedirs(os.path.join(HOME, ".claude", "skills", "g2"))
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
from forge import lib, owned, skills  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")

APPLY = lib.Ctx(True, None, False)
DRY = lib.Ctx(False, None, False)
FAKE_TOKEN = "fake-settings-keys-token-91c2-NOT-REAL"
REGISTRY = owned.path()
HS_CMD = "node /opt/toy/hs.js"
HS_ROW = ("UserPromptSubmit", HS_CMD, 10, "hs.js", None, True)
HS_OFF = HS_ROW[:5] + (False,)

failures, n_checks, n_proj = [], [0], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", str(detail)[:600])


def project(git=False):
    n_proj[0] += 1
    p = os.path.join(TOY, "proj%d" % n_proj[0])
    os.makedirs(os.path.join(p, ".claude"))
    if git:
        sandbox.git(p, "init", "-q")
    return p


def slp(p):
    return os.path.join(p, ".claude", "settings.local.json")


def doc(p):
    with open(slp(p), encoding="utf-8") as fh:
        return json.load(fh)


def profile(p, **keys):
    return dict({"project": "toy", "project_path": p}, **keys)


FULL = dict(skills_keep=["g1"], plugins_keep=["plug@toy"], env={"TOKEN": "${FAKE_TOKEN}", "PLAIN": "x"},
            permissions={"defaultMode": "acceptEdits", "allow": ["Bash(a:*)"]},
            enableAllProjectMcpServers=False, mcpjson_approved=["srv"], mcpjson_disabled=["old"])


def run(p, ctx=APPLY, rows=(HS_ROW,), **keys):
    """(the line, what the call printed) for a toy profile of `keys`."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        line = skills.write_settings_local(ctx, profile(p, **keys), {"FAKE_TOKEN": FAKE_TOKEN}, [], rows)
    return line, out.getvalue()


def drop_registry():
    if os.path.exists(REGISTRY):
        os.remove(REGISTRY)


def slurp(file):
    return open(file, "rb").read() if os.path.exists(file) else b""


def claimed(file, part=None):
    return {(c["kind"], tuple(c["at"])): c for c in owned.previous(file, part)[0]}


def want(file, kind, at, label, owner="toy", value=None, part=None):
    """The claim (kind, at) is there, with the owner, and with the digest of `value` when given."""
    c = claimed(file, part).get((kind, tuple(at)))
    check("missing claim %s %s%s" % (kind, list(at), label), c is not None, "present: %s" % sorted(claimed(file, part)))
    if c is not None:
        check("claim %s %s: owner %s" % (kind, list(at), owner), c["owner"] == owner, c)
        if value is not None:
            check("claim %s %s: the sum is the digest of the value written" % (kind, list(at)), c["sum"] == owned.digest(value), c)
    return c


# 1. A profile that declares everything: each key claim, the Hindsight row, nothing else odd.
drop_registry()
p = project()
line, _ = run(p, **FULL)
d, now = doc(p), claimed(slp(p))
want(slp(p), "key", ["skillOverrides"], "", value=d["skillOverrides"])
check("skillOverrides holds the skill it switched off", d["skillOverrides"] == {"g2": "off"}, d)
want(slp(p), "key", ["enabledPlugins"], "", value=d["enabledPlugins"])
env_claim = want(slp(p), "key", ["env"], "", value=d["env"]) or {"sum": "no claim"}  # a missing claim is a red check, not a crash
check("env received the resolved secret (the control for the registry checks)", d["env"]["TOKEN"] == FAKE_TOKEN, d)
want(slp(p), "key", ["permissions", "defaultMode"], "", value="acceptEdits")
want(slp(p), "key", ["enableAllProjectMcpServers"], "", value=False)
want(slp(p), "key", ["enabledMcpjsonServers"], "", value=["srv"])
want(slp(p), "key", ["disabledMcpjsonServers"], "", value=["old"])
want(slp(p), "hook", ["hooks", "UserPromptSubmit", HS_CMD], "", owner="hindsight", value=skills.canonical_hook(HS_CMD, 10))
check("the permission item is still claimed (the existing claim)", ("item", ("permissions", "allow", "Bash(a:*)")) in now, now)
check("no claim for the list keys as keys", not any(k[0] == "key" and k[1][:2] in (("permissions", "allow"), ("permissions", "deny"))
                                                    for k in now), now)
check("the registry holds no secret value", slurp(REGISTRY) != b"" and FAKE_TOKEN.encode() not in slurp(REGISTRY),
      "the registry is missing, or holds it")
check("a second run is already current", "already current" in run(p, **FULL)[0], line)
check("a second run keeps every claim", claimed(slp(p)).keys() == now.keys(), sorted(set(now) ^ set(claimed(slp(p)))))

# 2. removable(): an env nobody touched is forge's, one edited by hand is the user's.
check("removable: the env as written", owned.removable(env_claim, doc(p)["env"]), env_claim)
d = doc(p)
d["env"]["PLAIN"] = "edited by hand"
check("removable: an env edited by hand is not removable", not owned.removable(env_claim, d["env"]), env_claim)

# 3. Only what the run writes is claimed: a bare profile claims no key, and a key the profile does not declare
# is not claimed even when the file holds it.
drop_registry()
p = project()
lib.write_json(slp(p), {"enabledMcpjsonServers": ["by-hand"], "permissions": {"defaultMode": "plan"}})
run(p, rows=(), permissions={"allow": ["Bash(a:*)"]})
got = claimed(slp(p))
check("a key the profile does not declare is not claimed, though the file holds it",
      not any(k[0] == "key" for k in got) and doc(p)["enabledMcpjsonServers"] == ["by-hand"]
      and doc(p)["permissions"]["defaultMode"] == "plan", (sorted(got), doc(p)))

# 4. A dry-run records nothing, whether the registry exists or not.
drop_registry()
p = project()
run(p, DRY, **FULL)
check("dry-run on a first run: no registry written", not os.path.exists(REGISTRY), REGISTRY)
run(p, **FULL)
before = slurp(REGISTRY)
run(p, DRY, **dict(FULL, mcpjson_approved=["other"]))
check("dry-run: the registry is untouched", slurp(REGISTRY) == before and before != b"", "registry changed")

# 5. Key claims are never pruned by sync: the profile stops declaring the keys, they go by declaration (as
# before), their claims go with them, and the line says nothing was pruned.
drop_registry()
p = project()
run(p, **FULL)
line, printed = run(p, permissions={"allow": ["Bash(a:*)"]})
d = doc(p)
check("keys no longer declared: written by declaration, skillOverrides/enabledPlugins/env are gone",
      not any(k in d for k in ("skillOverrides", "enabledPlugins", "env")), d)
check("keys no longer declared: the line prunes nothing", ", pruned" not in line, line)
check("keys no longer declared: the claims of the keys that went are gone",
      not any(k[0] == "key" and k[1] in (("skillOverrides",), ("enabledPlugins",), ("env",)) for k in claimed(slp(p))), sorted(claimed(slp(p))))
check("keys no longer declared: the keys that stay in the file keep theirs (defaultMode, the mcpjson keys)",
      {("key", ("permissions", "defaultMode")), ("key", ("enabledMcpjsonServers",))} <= set(claimed(slp(p))) and "defaultMode" in doc(p)["permissions"],
      (sorted(claimed(slp(p))), doc(p)))

# 5b. The three .mcp.json keys (and permissions.<k>) are written only while declared and never taken out (a
# value approved in a session may sit there), so a key forge wrote stays in the file after the profile stops declaring it, and its
# claim must stay with it while it is still what forge wrote (a Codex review: "the claim disappears"); one
# edited by hand since is the user's and loses the claim.
drop_registry()
p = project()
run(p, rows=(), mcpjson_approved=["srv"], mcpjson_disabled=["old"], enableAllProjectMcpServers=False)
d = doc(p)
d["disabledMcpjsonServers"] = ["old", "by-hand"]
lib.write_json(slp(p), d)
run(p, rows=(), permissions={"allow": ["Bash(a:*)"]})
got = claimed(slp(p))
check("mcp keys no longer declared: still in the file", doc(p)["enabledMcpjsonServers"] == ["srv"]
      and doc(p)["enableAllProjectMcpServers"] is False, doc(p))
check("mcp keys no longer declared: the untouched ones keep their claim",
      ("key", ("enabledMcpjsonServers",)) in got
      and ("key", ("enableAllProjectMcpServers",)) in got, sorted(got))
check("mcp keys no longer declared: the one edited by hand loses it", ("key", ("disabledMcpjsonServers",)) not in got, sorted(got))
run(p, rows=(), permissions={"allow": ["Bash(a:*)"]})
check("a second run keeps the carried claims", claimed(slp(p)).keys() == got.keys(), sorted(set(got) ^ set(claimed(slp(p)))))

# 6. The Hindsight row: claimed while wanted; when the row goes off, _own_hook takes it out and the prune loop
# finds nothing more to do (they do not fight): one entry removed, no ', pruned', the claim gone. A row of
# the profile's own `hooks` with the same command keeps its (profile) claim.
drop_registry()
p = project()
run(p, **FULL)
check("hindsight row: written", HS_CMD in json.dumps(doc(p)["hooks"]), doc(p))
line, printed = run(p, rows=(HS_OFF,), **FULL)
check("hindsight row off: the entry is gone", "hooks" not in doc(p), doc(p))
check("hindsight row off: _own_hook counted it, the prune loop did not", "entries removed 1" in line and ", pruned" not in line, line)
check("hindsight row off: its claim is gone", ("hook", ("hooks", "UserPromptSubmit", HS_CMD)) not in claimed(slp(p)), sorted(claimed(slp(p))))
check("hindsight row off: nothing printed", printed == "", printed)
# A row deleted from the code altogether (no table row, on or off) is no longer owned by _own_hook, so the
# claim is what takes its entry out: the one place the prune loop acts on a hindsight claim.
drop_registry()
p = project()
run(p, **FULL)
line, _ = run(p, rows=(), **FULL)
check("hindsight row deleted from the code: the claim prunes its entry", "hooks" not in doc(p) and ", pruned 1)" in line, (doc(p), line))
drop_registry()
p = project()
run(p, **FULL)
d = doc(p)
d["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeout"] = 99  # edited by hand
lib.write_json(slp(p), d)
line, printed = run(p, rows=(), **FULL)
check("hindsight row deleted from the code, entry edited by hand: it stays and is named",
      HS_CMD in json.dumps(doc(p)["hooks"]) and HS_CMD in printed and ", pruned" not in line, (printed, line))
own = {"UserPromptSubmit": [{"hooks": [skills.canonical_hook(HS_CMD, 10)]}]}
run(p, rows=(HS_ROW,), hooks=own, **FULL)
run(p, rows=(HS_OFF,), hooks=own, **FULL)
check("hindsight row off but the profile declares the command: entry kept, claimed for the profile",
      HS_CMD in json.dumps(doc(p)["hooks"]) and claimed(slp(p)).get(("hook", ("hooks", "UserPromptSubmit", HS_CMD)), {}).get("owner") == "toy",
      (doc(p), sorted(claimed(slp(p)))))

# A per-project row that cannot be merged (the file's hooks is not an object) is not written, so not claimed.
drop_registry()
p = project()
lib.write_json(slp(p), {"hooks": "by hand"})
line, _ = run(p, **FULL)
check("hindsight row not merged: left alone with its summary", doc(p)["hooks"] == "by hand" and "not merged" in line, (doc(p), line))
check("hindsight row not merged: no claim for it", ("hook", ("hooks", "UserPromptSubmit", HS_CMD)) not in claimed(slp(p)), sorted(claimed(slp(p))))

# 7. The .agents/ line: claimed on the file forge added it to, part "skills"; never when it was already there.


def with_skill(p):
    os.makedirs(os.path.join(p, ".claude", "skills", "s1"))
    with open(os.path.join(p, ".claude", "skills", "s1", "SKILL.md"), "w") as fh:
        fh.write("---\nname: s1\n---\n")
    return p


def mirror(p, ctx=APPLY, **keys):
    return skills.mirror_for_codex(ctx, profile(p, **keys))


LINE = ["line", ".agents/"]
# 7a. no .gitignore: forge creates it with the line and claims it; a second apply, which adds nothing, keeps it.
drop_registry()
p = with_skill(project(git=True))
gi = os.path.join(p, ".gitignore")
mirror(p, DRY)
check("dry-run: no registry", not os.path.exists(REGISTRY), REGISTRY)
out = mirror(p)
check("gitignore: forge added the line", "+gitignore" in out and ".agents/" in slurp(gi).decode(), out)
want(gi, "item", LINE, " on the .gitignore", value=".agents/", part="skills")
mirror(p)
want(gi, "item", LINE, " on the .gitignore after a second apply", value=".agents/", part="skills")
# 7b. other parts of the same file keep their claims.
other = owned.claim("item", ["line", "x"], "x", "core")
owned.record(gi, [other], True, part="gitignore:system-doc")
mirror(p)
check("another writer's part of the same file is kept", ("item", ("line", "x")) in claimed(gi, "gitignore:system-doc"), sorted(claimed(gi)))
check("claims by part: ours is only in part skills", ("item", tuple(LINE)) in claimed(gi, "skills")
      and ("item", tuple(LINE)) not in claimed(gi, "gitignore:system-doc"), sorted(claimed(gi)))
# 7c. a line that was already there is never claimed, not on the first run and not on later ones.
drop_registry()
p = with_skill(project(git=True))
gi = os.path.join(p, ".gitignore")
with open(gi, "w") as fh:
    fh.write("node_modules/\n.agents/\n")
mirror(p)
mirror(p)
check("an existing line is never claimed", ("item", tuple(LINE)) not in claimed(gi) and not os.path.exists(REGISTRY),
      sorted(claimed(gi)))
# 7d. a repo-owned project (writes_tracked_files false): the line goes to .git/info/exclude, and is claimed there.
drop_registry()
p = with_skill(project(git=True))
ex = os.path.join(p, ".git", "info", "exclude")
out = mirror(p, writes_tracked_files=False)
check("exclude: forge added the line", "+exclude" in out and "/.agents/" in slurp(ex).decode(), out)
check("exclude: the project's .gitignore was not written", not os.path.exists(os.path.join(p, ".gitignore")))
want(ex, "item", ["line", "/.agents/"], " on the exclude file", value="/.agents/", part="skills")
mirror(p, writes_tracked_files=False)
want(ex, "item", ["line", "/.agents/"], " on the exclude file after a second apply", value="/.agents/", part="skills")
check("exclude: the .gitignore has no claim either", not claimed(os.path.join(p, ".gitignore")), "")

# 7e. a dry-run never drops a claim: the line is taken out by hand after the claim, and a dry-run leaves the record.
drop_registry()
p = with_skill(project(git=True))
gi = os.path.join(p, ".gitignore")
mirror(p)
before = slurp(REGISTRY)
os.remove(gi)
mirror(p, DRY)
check("dry-run: the claim of a line that was taken out by hand stays until an apply", slurp(REGISTRY) == before and before != b"", "")
mirror(p)
check("apply: the line is back and claimed", ("item", tuple(LINE)) in claimed(gi, "skills") and ".agents/" in slurp(gi).decode(), sorted(claimed(gi)))

# 7f. two projects of one repository, both repo-owned, share the exclude file: each keeps the other's claim.
drop_registry()
root = project(git=True)
sub = os.path.join(root, "sub")
os.makedirs(os.path.join(sub, ".claude"))
with_skill(root)
with_skill(sub)
ex = os.path.join(root, ".git", "info", "exclude")
mirror(root, writes_tracked_files=False)
mirror(sub, writes_tracked_files=False)
check("shared exclude file: both lines written", {"/.agents/", "/sub/.agents/"} <= set(slurp(ex).decode().split()), slurp(ex))
check("shared exclude file: each project's line stays claimed",
      {("item", ("line", "/.agents/")), ("item", ("line", "/sub/.agents/"))} <= set(claimed(ex, "skills")), sorted(claimed(ex, "skills")))
before = slurp(REGISTRY)
mirror(root, writes_tracked_files=False)
mirror(sub, writes_tracked_files=False)
check("shared exclude file: a run that adds nothing leaves the record byte for byte", slurp(REGISTRY) == before, "")

print("%d checks, %d failed" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
