#!/usr/bin/env python3
"""hooks.write_user_settings claims more of ~/.claude/settings.json (step 10, increment I3, task T2), so a
coming `forge uninstall` can take out everything forge wrote there. Beyond the hook claims of
test_owned_user_hooks.py, a run now also claims (forge/owned.py), owner "core", in the same record call:
  kind key   [k] for each plain key of config/forge.json's `user_settings` it writes, and ["env", k] for each
             key of its `env`, over the value written;
  kind item  ["permissions", "deny", rule] for each SECRET_DENY rule it left in the deny list.
Only what the run wrote is claimed: an `env` or `permissions.deny` of the wrong shape is left alone with a "!"
line and claims nothing, and a key of the file that `user_settings` does not name is the user's. The claim
keeps only the digest of the value; a dry-run records nothing; a value edited by hand is not removable.

Runs in-process against a toy HOME and a toy config/forge.json; lib.may_write() is stubbed to allow, because
this checkout may be a linked worktree, which never writes.

Seen failing on 78d36ba (this file against that commit's forge/hooks.py), 33 of 51 checks red; the first:
  FAIL missing claim key ['model'] -- present: ['hook ...' only]
  FAIL missing claim key ['env', 'FOO']
  FAIL missing claim item ['permissions', 'deny', 'Read(//**/.mcp.json)'] (one per SECRET_DENY rule)
and the checks that read them after: owner core, the digest of the value, removable() of an unedited and a hand-
edited value, the claims kept on a second apply, none for a wrong-shaped env or deny.
The controls that pass there on purpose: the hook claims stay, a dry-run records nothing, a key the user's
file holds and `user_settings` does not name is not claimed.
Negative controls on the finished code (107 checks), each mutation put back from a copy of forge/hooks.py, each
seen red: the plain-key claims dropped (6); the env-key claims dropped (4); env claimed though it is not an object
(1); the deny claims dropped (24, one per rule); deny claimed despite its "!" line (1); the claims not passed to
record (33); record called as an apply in a dry-run (2)."""
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("owned-user-settings-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, sandbox.FORGE)
from forge import lib, owned  # noqa: E402

lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
from forge import hooks  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
REGISTRY = owned.path()
FAKE_TOKEN = "fake-user-settings-token-5d0a-NOT-REAL"
WANTED = {"model": "sonnet", "toyMode": {"a": 1}, "env": {"FOO": "1", "BAR": FAKE_TOKEN}}

ROW = {"event": "UserPromptSubmit", "command": "python3 <ROOT>/toy/keep_row.py", "timeout": 10,
       "marker": "keep_row.py", "matcher": None, "agents": ["claude"]}
failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", str(detail)[:600])


_n = [0]


def world(user_settings=WANTED, seed=None, keep=False):
    """A toy forge.json with `user_settings`, hooks reloaded over it, and none of the files a run leaves."""
    _n[0] += 1
    lib.SETTINGS = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
        json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}, "user_settings": user_settings,
                   "codex_harness": False, "user_hooks": [ROW]}, fh)
    lib.settings.cache_clear()
    importlib.reload(hooks)
    hooks.USER_SETTINGS = SETTINGS
    for p in () if keep else (SETTINGS, SETTINGS + ".bak", REGISTRY):
        if os.path.exists(p):
            os.remove(p)
    if seed is not None:
        lib.write_json(SETTINGS, seed)
    return hooks


def run(h, apply=True):
    try:
        return h.write_user_settings(lib.Ctx(apply, None, True))
    except Exception as e:  # a crash is a red check, not a traceback
        return "raised %s: %s" % (type(e).__name__, e)


def doc():
    with open(SETTINGS, encoding="utf-8") as fh:
        return json.load(fh)


def claimed():
    return {(c["kind"], tuple(c["at"])): c for c in owned.previous(SETTINGS)[0]}


def want(kind, at, value, owner="core"):
    c = claimed().get((kind, tuple(at)))
    check("missing claim %s %s" % (kind, list(at)), c is not None,
          "present: %s" % sorted(k for k in claimed() if k[0] != "hook" or len(k[1]) != 3))
    if c is not None:
        check("claim %s %s: owner %s" % (kind, list(at), owner), c["owner"] == owner, c)
        check("claim %s %s: the sum is the digest of the value written" % (kind, list(at)), c["sum"] == owned.digest(value), c)
    return c


# 1. Every key and env key of user_settings, and every SECRET_DENY rule.
h = world()
line = run(h)
d, now = doc(), claimed()
check("the run wrote the keys (the control for the claims)", d["model"] == "sonnet" and d["env"]["FOO"] == "1", (line, d))
want("key", ["model"], "sonnet")
want("key", ["toyMode"], {"a": 1})
env_foo = want("key", ["env", "FOO"], "1")
env_bar = want("key", ["env", "BAR"], FAKE_TOKEN)
check("no claim for env as a whole (its keys are claimed one by one)", ("key", ("env",)) not in now, sorted(now))
check("SECRET_DENY is not empty", len(h.SECRET_DENY) > 5, h.SECRET_DENY)
for rule in h.SECRET_DENY:
    want("item", ["permissions", "deny", rule], rule)
check("the registry holds no value, not even an env value that looks like a token",
      os.path.exists(REGISTRY) and FAKE_TOKEN.encode() not in open(REGISTRY, "rb").read(), "registry missing or holds it")

# 2. removable(): as written, and after a hand edit.
check("removable: an env key as written", env_foo is not None and owned.removable(env_foo, doc()["env"]["FOO"]), env_foo)
d = doc()
d["env"]["FOO"] = "2"
d["model"] = "opus"
check("removable: an env key edited by hand is not removable", env_foo is not None and not owned.removable(env_foo, d["env"]["FOO"]), env_foo)
model = claimed().get(("key", ("model",)))
check("removable: a plain key edited by hand is not removable", model is not None and not owned.removable(model, d["model"]), model)
check("removable: the plain key as written", model is not None and owned.removable(model, "sonnet"), model)

# 3. A second run, with the file as it is, keeps every claim and is already current.
h = world()
run(h)
first = claimed()
line = run(h)
check("a second run is already current", "already current" in line, line)
check("a second run keeps every claim", claimed() == first and len(first) > 0, sorted(set(first) ^ set(claimed())))

# 4. The hook claims stay, beside the new ones: the same run records both.
h = world()
run(h)
check("hook claims stay", any(k[0] == "hook" for k in claimed()), sorted(claimed()))

# 5. A dry-run records nothing; with a record and a pending change, it leaves the file and the record as they are.
h = world()
run(h, apply=False)
check("dry-run on a first run: no registry", not os.path.exists(REGISTRY), REGISTRY)
run(h)
before_reg, before_file = open(REGISTRY, "rb").read(), open(SETTINGS, "rb").read()
h = world(dict(WANTED, model="haiku", extra="new"), keep=True)
line = run(h, apply=False)
check("dry-run: there was a change to make (the control)", line.lstrip().startswith("would write") and "model" in line, line)
check("dry-run: the registry is untouched", open(REGISTRY, "rb").read() == before_reg, "registry changed")
check("dry-run: the file is untouched", open(SETTINGS, "rb").read() == before_file, "file changed")

# 6. A key of the file that user_settings does not name is the user's: never claimed.
h = world(seed={"theme": "dark", "env": {"MINE": "1"}, "permissions": {"deny": ["Bash(rm:*)"]}})
run(h)
now = claimed()
check("a key user_settings does not name is not claimed", ("key", ("theme",)) not in now and ("key", ("env", "MINE")) not in now, sorted(now))
check("a deny rule the user wrote is not claimed", ("item", ("permissions", "deny", "Bash(rm:*)")) not in now, sorted(now))
check("and it stays", "Bash(rm:*)" in doc()["permissions"]["deny"] and doc()["env"]["MINE"] == "1", doc())

# 7. A shape forge leaves alone claims nothing for it: env not an object, permissions.deny not a list.
h = world(seed={"env": ["not", "an", "object"]})
line = run(h)
now = claimed()
check("env not an object: left alone, with its '!' line", doc()["env"] == ["not", "an", "object"] and "env is not an object" in line, (line, doc()))
check("env not an object: no env claim", not any(k[1][:1] == ("env",) for k in now), sorted(now))
check("env not an object: the plain keys and the deny rules are still claimed", ("key", ("model",)) in now
      and any(k[0] == "item" for k in now), sorted(now))
h = world(seed={"permissions": {"deny": "Bash(rm:*)"}})
line = run(h)
now = claimed()
check("deny not a list: left alone", doc()["permissions"]["deny"] == "Bash(rm:*)" and "not a list" in line, (line, doc()))
check("deny not a list: no deny claim", not any(k[0] == "item" for k in now), sorted(now))

# 8. A key that already holds the wanted value is claimed too (a first run after the claims were introduced:
# the value is current, forge's config still names it, and a later uninstall must find the claim).
h = world(seed={"model": "sonnet"})
run(h)
want("key", ["model"], "sonnet")

sandbox.cleanup(bool(failures))
print("%d checks, %d failed" % (n_checks[0], len(failures)))
sys.exit(1 if failures else 0)
