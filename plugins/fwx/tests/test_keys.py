#!/usr/bin/env python3
"""core.keys: job keys and attempt branches, the port of marshal's job-key-regressions.ts with the prefix `factory-`.

Every case of that file's branch table is here (23 rows) with `factory/` turned into `factory-`, the round trip of
every key through its attempt branches, the four `job_key` refusals, the `is_job_key` refusals, and the two forms the
plan names (`factory-DTC-12` is attempt 1, `factory-DTC-12-a2` is attempt 2, whose `-a2` is not part of the key).
The old `factory/DTC-12` form is rejected everywhere. The file's last block (the report identity of marshal's MCP
server) belongs to another module and is not ported.

Seen red before the code existed (lib/fwx/core/keys.py absent; the test stops at the import):
  FAIL: cannot import fwx.core.keys: cannot import name 'keys' from 'fwx.core' (unknown location)

Controls, each seen red on a copy of the repo with one thing changed (first FAIL line shown):
  - `parse_branch` without the 64-character limit:
      FAIL: a 65-character key does not: got {'key': 'GH-aaaa...aaaa-1', 'attempt': 1}, want None
  - `is_job_key` without the 64-character limit:
      FAIL: is_job_key refuses 65
  - the number of a key may start with `a` (`-a?[0-9]+`), so `-a2` reads as part of the key:
      FAIL: parse_branch('factory-FAC-10-a2'): got {'key': 'FAC-10-a2', 'attempt': 1}, want {'key': 'FAC-10', 'attempt': 2}
  - the branch pattern also accepts `factory/` (`factory[/-]`):
      FAIL: parse_branch('factory/DTC-12'): got {'key': 'DTC-12', 'attempt': 1}, want None
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
sys.path.insert(0, os.path.join(ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx.core import keys  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.core.keys: %s" % e)
    sys.exit(1)

# ---- one parser for every attempt branch ---------------------------------------------------------------------------

BRANCHES = [
    ("factory-FAC-59", {"key": "FAC-59", "attempt": 1}),
    ("factory-FAC-10-a2", {"key": "FAC-10", "attempt": 2}),
    ("factory-FAC-10-a12", {"key": "FAC-10", "attempt": 12}),
    ("factory-ENG2-7", {"key": "ENG2-7", "attempt": 1}),
    ("factory-fac-5", {"key": "fac-5", "attempt": 1}),
    ("factory-GH-marshal-factory-42", {"key": "GH-marshal-factory-42", "attempt": 1}),
    ("factory-GH-marshal-factory-42-a3", {"key": "GH-marshal-factory-42", "attempt": 3}),
    ("factory-GH-a-1-a2", {"key": "GH-a-1", "attempt": 2}),
    ("factory-SL-c0123-1730000000-a2", {"key": "SL-c0123-1730000000", "attempt": 2}),
    ("factory-onboarding", None),
    ("factory-FAC", None),
    ("factory-FAC-", None),
    ("factory-FAC-5-a", None),
    ("factory-FAC-5-A2", None),
    ("factory-GH-Marshal-42", None),
    ("factory-GH--42", None),
    ("factory-FAC-5/x", None),
    ("FAC-5", None),
    ("feature/FAC-5", None),
    ("worktree-agent-abc", None),
    ("factory-GH-%s-1" % ("x" * 80), None),
    ("", None),
    (None, None),
    # the two forms of the plan
    ("factory-DTC-12", {"key": "DTC-12", "attempt": 1}),
    ("factory-DTC-12-a2", {"key": "DTC-12", "attempt": 2}),
    # the slash form marshal used is not a branch of this framework
    ("factory/DTC-12", None),
    ("factory/FAC-10-a2", None),
    ("factory/", None),
    # no digit is a Unicode digit
    ("factory-FAC-٥", None),
]
for branch, want in BRANCHES:
    s.eq("parse_branch(%r)" % branch, keys.parse_branch(branch), want)

# the key of a 64-character branch tail is the limit: 64 passes, 65 does not
k64 = "GH-" + "a" * (64 - len("GH--1")) + "-1"
s.eq("the test key is 64 characters long", len(k64), 64)
s.eq("a 64-character key parses", keys.parse_branch("factory-" + k64), {"key": k64, "attempt": 1})
s.eq("a 64-character key with an attempt parses", keys.parse_branch("factory-" + k64 + "-a2"), {"key": k64, "attempt": 2})
s.eq("a 65-character key does not", keys.parse_branch("factory-" + k64[:-2] + "a-1"), None)
s.ok("is_job_key accepts 64", keys.is_job_key(k64))
s.ok("is_job_key refuses 65", not keys.is_job_key(k64[:-2] + "a-1"))
s.eq("MAX_KEY_LENGTH", keys.MAX_KEY_LENGTH, 64)
s.eq("the branch prefix", keys.BRANCH_PREFIX, "factory-")

# ---- every key a source makes round-trips through its attempt branches ---------------------------------------------

made = [keys.job_key("FAC", 7), keys.job_key("GH", 42, "ski043/Factory Demo"), keys.job_key("SL", "1730000000", "C0123")]
s.eq("made keys", made, ["FAC-7", "GH-ski043-factory-demo-42", "SL-c0123-1730000000"])
s.eq("job_key with a Linear team key", keys.job_key("DTC", 12), "DTC-12")
for key in ["FAC-1", "FAC-123", "DTC-12"] + made:
    s.ok("is_job_key(%r)" % key, keys.is_job_key(key))
    for attempt in (1, 2, 10):
        s.eq("%s attempt %d round trip" % (key, attempt), keys.parse_branch(keys.attempt_branch(key, attempt)),
             {"key": key, "attempt": attempt})
s.eq("a first attempt has no suffix", keys.attempt_branch("FAC-5", 1), "factory-FAC-5")
s.eq("the plan's first attempt", keys.attempt_branch("DTC-12", 1), "factory-DTC-12")
s.eq("the plan's second attempt", keys.attempt_branch("DTC-12", 2), "factory-DTC-12-a2")
s.eq("attempt 0 is no suffix either", keys.attempt_branch("DTC-12", 0), "factory-DTC-12")


def raises(fn, *args):
    try:
        fn(*args)
    except ValueError as e:
        return str(e)
    return None


for label, args in (("a prefix is uppercase", ("gh", 1)), ("a key ends in its number", ("GH", "x")),
                    ("a key stays short enough for a branch", ("GH", 1, "y" * 80))):
    msg = raises(keys.job_key, *args)
    s.ok("job_key refuses: " + label, msg is not None and "cannot make a job key" in msg, "got %r" % msg)
s.ok("job_key refuses an empty prefix", raises(keys.job_key, "", 1) is not None)

for bad in ["FAC-5-a2", "GH-x", "GH-X-1", "FAC 5", "factory/FAC-5", "factory-FAC-5", "FAC-5.", "", "FAC-٥"]:
    s.eq("is_job_key(%r) is False" % bad, keys.is_job_key(bad), False)
s.eq("is_job_key(None) is False", keys.is_job_key(None), False)

# ---- no one else holds the old slash form ---------------------------------------------------------------------------

with open(os.path.join(ROOT, "lib", "fwx", "core", "keys.py"), encoding="utf-8") as fh:
    src = fh.read()
s.ok("keys.py carries its copied-from header", src.startswith("# copied-from:") or "\n# copied-from:" in src[:400])
s.ok("keys.py names the source commit", "999ad209598517a4c826073b5a0edc2a4097a4fa" in src)

s.done()
