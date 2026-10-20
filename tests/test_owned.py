#!/usr/bin/env python3
"""forge/owned.py, the record of what forge wrote (increment I2 of step 10, task T1): ~/.local/state/forge/
owned.json holds, per file forge merged into, one claim per value it put there -- kind, JSON path, the
SHA-256 of the value and the owner, never the value, since a resolved env holds secrets. Nothing calls
the module yet; this is its core alone: claim, digest, load, previous, stale, removable, record.

HOME is a toy dir set before forge.lib is imported (lib.STATE is computed at import), so the registry
under test is the toy's. lib.may_write() is stubbed to allow in the cases that write, because this
checkout may be a linked worktree, which never writes; the refusal case restores the real one and
arranges a refusal that does not depend on where the suite runs: a settings.json naming another checkout.

Seen failing before forge/owned.py existed (every case red, at the import):
  ImportError: cannot import name 'owned' from 'forge' (.../forge/__init__.py)
Negative controls on the finished module, each put back from a copy of forge/owned.py: see the commit
message that added this file for the messages they produced."""
import contextlib
import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

top = sandbox.mkdtemp("owned-test-")
HOME = os.path.join(top, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME
os.environ.pop("CLAUDE_PROJECT_DIR", None)
from forge import lib, owned  # noqa: E402

failures, n_checks = [], [0]
FAKE_TOKEN = "fake-owned-token-9c1e-NOT-REAL"
A = os.path.join(top, "proj-a", ".claude", "settings.local.json")
B = os.path.join(top, "proj-b", ".claude", "settings.local.json")
REGISTRY = os.path.join(HOME, ".local", "state", "forge", "owned.json")
real_may_write = lib.may_write


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", detail)


def allow(yes, why=""):
    lib.may_write = (lambda: (True, "")) if yes else (lambda: (False, why))


def put(text):
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    with open(REGISTRY, "w", encoding="utf-8") as fh:
        fh.write(text)


def identities(claims):
    return sorted((c["kind"], tuple(c["at"])) for c in claims)


perm1 = owned.claim("item", ["permissions", "allow", "Bash(ls:*)"], "Bash(ls:*)", "core")
perm2 = owned.claim("item", ["permissions", "allow", "Bash(git status:*)"], "Bash(git status:*)", "core")
env = owned.claim("key", ["env", "TOKEN"], FAKE_TOKEN, "toy-profile")
hook = owned.claim("hook", ["hooks", "SessionStart", 0], {"type": "command", "command": "x"}, "gsd")
lnk = owned.claim("file", [], "skills/x -> /forge/skills/x", "core")

# the digest
check("digest is sha256 of the compact, sorted, non-ASCII-kept JSON",
      owned.digest({"b": 1, "a": "é"}) == hashlib.sha256('{"a":"é","b":1}'.encode("utf-8")).hexdigest(), owned.digest({"b": 1, "a": "é"}))
check("key order does not change the digest", owned.digest({"a": 1, "b": 2}) == owned.digest({"b": 2, "a": 1}))
check("a different value has a different digest", owned.digest("x") != owned.digest("y"))

# no file: nothing stale
claims, warn = owned.previous(A)
check("no file: previous is empty and says nothing", claims == [] and warn == "", "%r %r" % (claims, warn))
check("no file: nothing is stale", owned.stale(claims, [perm1]) == [])
check("no file: load is empty without a warning", owned.load() == ({}, ""))

# a dry-run and a checkout that may not write leave no file
allow(True)
check("dry-run (apply=False) reports no write", owned.record(A, [perm1], apply=False) is False)
check("dry-run creates no registry", not os.path.exists(REGISTRY), REGISTRY)
other = os.path.join(top, "other-forge")
os.makedirs(os.path.join(other, "bin"))
with open(os.path.join(other, "bin", "forge"), "w"):
    pass
lib.may_write = real_may_write
sandbox.installed_settings(HOME, other)
ok, why = lib.may_write()
check("arming: the toy HOME refuses this checkout", ok is False and why, "%r %r" % (ok, why))
wrote = owned.record(A, [perm1], apply=True)
check("a checkout that may not write: record writes nothing",
      wrote is False and not os.path.exists(REGISTRY), "%r, registry exists %s" % (wrote, os.path.exists(REGISTRY)))
allow(False, "forge: stub refusal")
check("a stubbed refusal writes nothing either", owned.record(A, [perm1], apply=True) is False and not os.path.exists(REGISTRY))

# round trip
allow(True)
check("record with apply on an allowed checkout reports the write",
      owned.record(A, [perm1, perm2, env, hook, lnk], apply=True) is True)
check("the registry is where lib.STATE says", os.path.isfile(REGISTRY) and REGISTRY == owned.path(), owned.path())
doc = json.load(open(REGISTRY))
check("the file is version 1 with one entry per path", doc.get("version") == 1 and list(doc.get("claims", {})) == [A], str(doc)[:200])
got, warn = owned.previous(A)
check("round trip: previous returns what record wrote", got == [perm1, perm2, env, hook, lnk] and warn == "", "%r %r" % (got, warn))
check("a claim carries kind, at, sum, owner", set(perm1) == {"kind", "at", "sum", "owner"} and perm1["sum"] == owned.digest("Bash(ls:*)"), perm1)
check("the registry file is private (0600)", os.stat(REGISTRY).st_mode & 0o777 == 0o600, oct(os.stat(REGISTRY).st_mode & 0o777))

# no secret value in the file
text = open(REGISTRY, encoding="utf-8").read()
check("arming: a claim was made for FAKE_TOKEN and its hash is in the file", env["sum"] in text, "hash missing")
check("the registry never holds a value a claim was made for", FAKE_TOKEN not in text, "value found in the file")

# one path leaves another's claims alone, and replaces its own
owned.record(B, [perm1], apply=True)
owned.record(A, [perm2], apply=True)
check("record of one path replaces its own claims", owned.previous(A)[0] == [perm2], owned.previous(A)[0])
check("record of one path keeps another path's claims", owned.previous(B)[0] == [perm1], owned.previous(B)[0])
owned.record(A, [], apply=True)
check("record with no claims drops that file's entry and keeps the other",
      owned.previous(A)[0] == [] and owned.previous(B)[0] == [perm1] and A not in json.load(open(REGISTRY))["claims"])

# stale: exactly the dropped identities
prev = [perm1, perm2, env, hook]
now = [owned.claim("item", ["permissions", "allow", "Bash(ls:*)"], "Bash(ls:*)", "core"), env]
check("stale is exactly the claims whose identity is not claimed now",
      owned.stale(prev, now) == [perm2, hook], "got %r" % identities(owned.stale(prev, now)))
check("a claim whose value changed but identity stays is not stale",
      owned.stale([env], [owned.claim("key", ["env", "TOKEN"], "new", "toy-profile")]) == [])
check("nothing claimed now makes every previous claim stale", owned.stale(prev, []) == prev)
check("the same JSON path under another kind is a different identity",
      owned.stale([env], [owned.claim("item", ["env", "TOKEN"], FAKE_TOKEN, "core")]) == [env])

# removable: only a value still what forge wrote
check("removable: an intact value is removable", owned.removable(perm1, "Bash(ls:*)") is True)
check("removable: an intact object is removable whatever its key order",
      owned.removable(hook, {"command": "x", "type": "command"}) is True)
edited = owned.removable(perm1, "Bash(ls:*) --edited")
check("removable: an edited value is never removable", edited is False,
      "removable(claim, edited value) = %r, want False" % edited)
check("removable: an edited object is never removable", owned.removable(hook, {"type": "command", "command": "y"}) is False)

# a record that cannot be trusted loads as empty and says so
bad = (("corrupt JSON", "{not json"),
       ("version 2", json.dumps({"version": 2, "claims": {A: [perm1]}})),
       ("a list instead of an object", "[]"),
       ("claims as a list", json.dumps({"version": 1, "claims": []})),
       ("a claim missing its sum", json.dumps({"version": 1, "claims": {A: [{"kind": "item", "at": [], "owner": "core"}]}})),
       ("an unknown kind", json.dumps({"version": 1, "claims": {A: [dict(perm1, kind="bogus")]}})))
for label, body in bad:
    put(body)
    try:
        claims, warn = owned.load()
        got = owned.previous(A)
        raised = None
    except Exception as e:  # load must never raise
        claims, warn, got, raised = None, None, None, e
    check("%s loads as empty" % label, raised is None and claims == {} and got[0] == [], "raised %r, claims %r" % (raised, claims))
    check("%s says so in forge's '  ! ' style, naming the file" % label,
          raised is None and warn.startswith("  ! ") and REGISTRY in warn and "\n" not in warn, repr(warn))
    check("%s: nothing is stale (the safe direction)" % label, raised is None and owned.stale(got[0], [perm1]) == [])
put(json.dumps({"version": 1, "claims": {A: [perm1]}}))
check("arming: a well-formed file loads without a warning", owned.load() == ({A: [perm1]}, ""), repr(owned.load()))
put("{not json")
owned.record(B, [perm2], apply=True)
check("record over an unreadable registry replaces it with this file's claims",
      owned.load() == ({B: [perm2]}, ""), repr(owned.load()))

lib.may_write = real_may_write
sandbox.cleanup(bool(failures))
if failures:
    print("\n%d of %d checks failed" % (len(failures), n_checks[0]))
    sys.exit(1)
print("test_owned: %d checks passed" % n_checks[0])
