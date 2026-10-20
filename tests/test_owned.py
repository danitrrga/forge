#!/usr/bin/env python3
"""forge/owned.py, the record of what forge wrote (increment I2 of step 10, task T1): ~/.local/state/forge/
owned.json holds, per file forge merged into, one claim per value it put there -- kind, JSON path, the
SHA-256 of the value and the owner, never the value, since a resolved env holds secrets. The module's core:
claim, digest, load, previous, stale, removable, record.

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

# simplify-5 T3: hook_site decodes a hook claim's `at` once, in both layouts. Seen failing on the code before
# it existed: "AttributeError: module 'forge.owned' has no attribute 'hook_site'". Negative control, its two
# branches swapped (put back from a copy): see the commit message for the FAIL lines.
check("hook_site: a settings.local.json claim [hooks, event, command] has any matcher",
      owned.hook_site(["hooks", "SessionStart", "cmd"]) == ("SessionStart", owned.ANY, "cmd"), owned.hook_site(["hooks", "SessionStart", "cmd"]))
check("hook_site: a settings.json claim [event, matcher, command] is itself",
      owned.hook_site(["PreToolUse", "Bash", "cmd"]) == ("PreToolUse", "Bash", "cmd")
      and owned.hook_site(["SessionStart", None, "cmd"]) == ("SessionStart", None, "cmd"), owned.hook_site(["PreToolUse", "Bash", "cmd"]))

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

# parts: several writers claim in one file (step 10, I3, task T0). Seen failing before `part` existed:
#   TypeError: record() got an unexpected keyword argument 'part'
# Negative control, record() made to ignore `part` (replace the file's whole list), put back from a copy:
#   FAIL parts: recording part B leaves part A's claims -- got [('item', ('b',))], want a and b both
put("")
os.remove(REGISTRY)
F = os.path.join(top, "proj-p", ".gitignore")
ca = owned.claim("item", ["a"], "a", "core")
cb = owned.claim("item", ["b"], "b", "core")
cc = owned.claim("item", ["c"], "c", "core")
owned.record(F, [ca], apply=True, part="skills")
owned.record(F, [cb], apply=True, part="mcp")
got = owned.previous(F)[0]
check("parts: recording part B leaves part A's claims", identities(got) == [("item", ("a",)), ("item", ("b",))],
      "got %s, want a and b both" % identities(got))
check("parts: previous(file, part) gives only that part's claims",
      identities(owned.previous(F, "skills")[0]) == [("item", ("a",))]
      and identities(owned.previous(F, "mcp")[0]) == [("item", ("b",))] and owned.previous(F, "none")[0] == [])
check("parts: the part is stored in each claim and a claim made without one carries no part field",
      {c.get("part") for c in got} == {"skills", "mcp"} and "part" not in ca and "part" not in owned.claim("key", ["k"], 1, "core"),
      repr(got))
owned.record(F, [cc], apply=True, part="skills")
check("parts: re-recording a part replaces that part only",
      identities(owned.previous(F, "skills")[0]) == [("item", ("c",))] and identities(owned.previous(F, "mcp")[0]) == [("item", ("b",))])
owned.record(F, [], apply=True, part="skills")
check("parts: no claims for a part drops that part and keeps the other",
      owned.previous(F, "skills")[0] == [] and identities(owned.previous(F)[0]) == [("item", ("b",))])
owned.record(F, [], apply=True, part="mcp")
check("parts: dropping the last part drops the file's entry", F not in owned.load()[0], repr(owned.load()[0]))
owned.record(F, [ca], apply=True, part="skills")
owned.record(F, [cb], apply=True, part="mcp")
owned.record(F, [cc], apply=True)
check("part None still replaces the whole file's claims, parts included",
      identities(owned.previous(F)[0]) == [("item", ("c",))] and owned.previous(F, "skills")[0] == [], repr(owned.previous(F)[0]))
before = open(REGISTRY, encoding="utf-8").read()
owned.record(F, [ca], apply=False, part="skills")
check("parts: a dry-run records nothing", open(REGISTRY, encoding="utf-8").read() == before)
put(json.dumps({"version": 1, "claims": {F: [ca, cb]}}))
check("an old registry without part fields loads, its claims count as part None",
      owned.load() == ({F: [ca, cb]}, "") and owned.previous(F) == ([ca, cb], "") and owned.previous(F, "skills")[0] == [])
owned.record(F, [cc], apply=True, part="skills")
check("recording a part beside old part-less claims keeps them",
      identities(owned.previous(F)[0]) == [("item", ("a",)), ("item", ("b",)), ("item", ("c",))], repr(owned.previous(F)[0]))
put(json.dumps({"version": 1, "claims": {F: [dict(ca, part=3)]}}))
check("a claim whose part is not a string makes the registry untrusted", owned.load()[0] == {} and owned.load()[1].startswith("  ! "))

# simplify-5 T1: record() of a part whose claims are unchanged writes nothing. A replaced part moves to
# the end of the file's list, so with two parts in one file the first one re-recorded would reorder
# (and rewrite) the registry on every run. Seen failing with the guard absent (record as on ebc4601):
#   FAIL parts: re-recording the first of two parts unchanged leaves the registry's bytes -- bytes changed True, mtime changed True, returned True
os.remove(REGISTRY)
owned.record(F, [ca], apply=True, part="skills")
owned.record(F, [cb], apply=True, part="mcp")
os.utime(REGISTRY, ns=(10**9, 10**9))
before, mtime = open(REGISTRY, "rb").read(), os.stat(REGISTRY).st_mtime_ns
wrote = owned.record(F, [dict(ca)], apply=True, part="skills")
changed = (open(REGISTRY, "rb").read() != before, os.stat(REGISTRY).st_mtime_ns != mtime)
check("parts: re-recording the first of two parts unchanged leaves the registry's bytes", changed == (False, False) and wrote is False,
      "bytes changed %s, mtime changed %s, returned %r" % (changed + (wrote,)))
owned.record(F, [dict(ca, owner="other")], apply=True, part="skills")
check("parts: a changed owner is still recorded, and the part moves last",
      [c["owner"] for c in owned.previous(F)[0]] == ["core", "other"], repr(owned.previous(F)[0]))

# the .bak lib.write_text creates is claimed, as part "bak", once, never with its content
# Seen failing before the hook: FAIL bak: a new .bak is claimed as kind file at [], owner core -- got [] (no claim)
os.remove(REGISTRY)
cfg = os.path.join(top, "proj-q", "settings.json")
os.makedirs(os.path.dirname(cfg))
orig = json.dumps({"env": {"TOKEN": FAKE_TOKEN}})
with open(cfg, "w", encoding="utf-8") as fh:
    fh.write(orig)
bak = cfg + ".bak"
allow(False, "forge: stub refusal")
lib.write_text(cfg, json.dumps({"env": {}}), mode=0o600, backup=True)
check("bak: a checkout that may not write claims nothing", os.path.exists(bak) and not os.path.exists(REGISTRY),
      "bak exists %s, registry exists %s" % (os.path.exists(bak), os.path.exists(REGISTRY)))
os.remove(bak)
with open(cfg, "w", encoding="utf-8") as fh:
    fh.write(orig)
allow(True)
lib.write_text(cfg, json.dumps({"env": {}}), mode=0o600, backup=True)
got = owned.previous(bak, "bak")[0]
check("bak: a new .bak is claimed as kind file at [], owner core",
      len(got) == 1 and got[0]["kind"] == "file" and got[0]["at"] == [] and got[0].get("part") == "bak" and got[0]["owner"] == "core",
      "got %r (no claim)" % got)
check("bak: the claim is the digest of the .bak's content, so removable() says it is unchanged",
      bool(got) and owned.removable(got[0], orig) and not owned.removable(got[0], orig + " edited"))
regtext = open(REGISTRY, encoding="utf-8").read() if os.path.exists(REGISTRY) else None
check("bak: the claim holds no content (and a registry exists to hold none)", regtext is not None and FAKE_TOKEN not in regtext)
check("bak: the original file is the one the .bak holds", open(bak, encoding="utf-8").read() == orig)
check("bak: only the .bak is claimed, not the file written", cfg not in owned.load()[0], repr(list(owned.load()[0])))
lib.write_text(cfg, json.dumps({"env": {"X": 1}}), mode=0o600, backup=True)
check("bak: a second write leaves the claim as it was",
      os.path.exists(REGISTRY) and open(REGISTRY, encoding="utf-8").read() == regtext)
if os.path.exists(REGISTRY):
    os.remove(REGISTRY)
lib.write_text(cfg, json.dumps({"env": {"X": 2}}), mode=0o600, backup=True)
check("bak: a .bak that existed before is never claimed", not os.path.exists(REGISTRY), "registry exists after a write beside an old .bak")
other_cfg = os.path.join(top, "proj-q", "other.json")
with open(other_cfg, "w", encoding="utf-8") as fh:
    fh.write(orig)
lib.write_text(other_cfg, "{}", mode=0o600)
check("bak: backup=False creates no .bak and claims nothing", not os.path.exists(other_cfg + ".bak") and not os.path.exists(REGISTRY))
owned.claim_backup(bak, apply=False)
check("bak: claim_backup in a dry-run claims nothing", not os.path.exists(REGISTRY))
owned.claim_backup(os.path.join(top, "proj-q", "gone.bak"), apply=True)
check("bak: claim_backup of a missing file claims nothing and does not raise", not os.path.exists(REGISTRY))

lib.may_write = real_may_write
sandbox.cleanup(bool(failures))
if failures:
    print("\n%d of %d checks failed" % (len(failures), n_checks[0]))
    sys.exit(1)
print("test_owned: %d checks passed" % n_checks[0])
