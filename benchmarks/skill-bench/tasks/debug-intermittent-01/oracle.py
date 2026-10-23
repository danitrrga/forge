"""Oracle for debug-intermittent-01: profiles share one cached defaults dict, so tests pass or fail by order.

load_defaults() is lru_cached and new_profile() updates the dict it returns, so every profile's prefs are
the same object, nested notifications included. Clearing the cache in the tests makes the suite green in any
order and leaves production profiles leaking into each other; a shallow copy fixes the theme and still shares
notifications. The oracle builds profiles in fresh processes in the orders that expose both leaks, then
runs the repo's suite in 12 fixed shuffled orders, each in its own process."""
import json
import os
import subprocess
import sys

DEFAULTS = {"theme": "light", "language": "en", "timezone": "UTC",
            "notifications": {"email": True, "push": True, "digest": "weekly"}}

PROBE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from prefs.profiles import mute_notifications, new_profile, set_digest
res = {}
res["fresh"] = json.loads(json.dumps(new_profile("zoe")["prefs"]))  # a snapshot, not the live dict

a = new_profile("ana", theme="dark", language="es")
b = new_profile("ben")
res["top_after_override"] = {k: b["prefs"].get(k) for k in ("theme", "language")}
b["prefs"]["timezone"] = "Europe/Madrid"
res["top_after_assign"] = new_profile("cleo")["prefs"].get("timezone")

c = new_profile("dan")
mute_notifications(a)
set_digest(a, "daily")
res["nested_existing"] = c["prefs"]["notifications"]
res["nested_new"] = new_profile("eve")["prefs"]["notifications"]
res["muted_one"] = a["prefs"]["notifications"]
print(json.dumps(res))
'''

ORDERED = r'''
import json, os, random, sys, unittest
repo, seed = sys.argv[1], int(sys.argv[2])
sys.path.insert(0, repo)
def flat(s):
    for t in s:
        yield from (flat(t) if isinstance(t, unittest.TestSuite) else [t])
tests = list(flat(unittest.defaultTestLoader.discover(os.path.join(repo, "tests"), top_level_dir=repo)))
random.Random(seed).shuffle(tests)
r = unittest.TestResult()
unittest.TestSuite(tests).run(r)
print(json.dumps({"run": r.testsRun, "bad": [t.id().split(".")[-1] for t, _ in r.failures + r.errors],
                  "skipped": len(r.skipped) + len(r.expectedFailures)}))
'''


def run(code, *args):
    r = subprocess.run([sys.executable, "-I", "-B", "-c", code] + list(args), capture_output=True, text=True,
                       timeout=20, cwd=args[0])
    lines = r.stdout.strip().splitlines()
    if r.returncode or not lines:
        return None, (r.stderr.strip().splitlines() or ["no output"])[-1]
    return json.loads(lines[-1]), None


def check(repo, message):
    repo = os.path.abspath(repo)
    out = []
    res, err = run(PROBE, repo)
    if err:
        for cid in ("defaults-unchanged", "top-level-isolated", "nested-isolated"):
            out.append({"id": cid, "passed": False, "evidence": "probe failed: " + err})
    else:
        out.append({"id": "defaults-unchanged", "passed": res["fresh"] == DEFAULTS,
                    "evidence": "first profile in a fresh process: %r" % (res["fresh"],)})
        ok = res["top_after_override"] == {"theme": "light", "language": "en"} and res["top_after_assign"] == "UTC"
        out.append({"id": "top-level-isolated", "passed": ok,
                    "evidence": "after ana overrides theme/language: ben has %r; after ben sets timezone, cleo has %r"
                    % (res["top_after_override"], res["top_after_assign"])})
        want = DEFAULTS["notifications"]
        ok = (res["nested_existing"] == want and res["nested_new"] == want
              and res["muted_one"] == {"email": False, "push": False, "digest": "daily"})
        out.append({"id": "nested-isolated", "passed": ok,
                    "evidence": "after muting ana and setting her digest daily: dan (made before) %r, eve (made after) %r, ana %r"
                    % (res["nested_existing"], res["nested_new"], res["muted_one"])})

    bad = []
    counts = set()
    for seed in range(12):
        s, err = run(ORDERED, repo, str(seed))
        if err:
            bad.append("seed %d: crashed: %s" % (seed, err))
            continue
        counts.add(s["run"])
        if s["bad"] or s["skipped"] or s["run"] < 4:
            bad.append("seed %d: %d tests, failed %s, skipped %d" % (seed, s["run"], s["bad"], s["skipped"]))
    out.append({"id": "suite-green-in-any-order", "passed": not bad,
                "evidence": "; ".join(bad[:3]) + (" (%d of 12 orders bad)" % len(bad) if bad else "")
                or "12 shuffled orders, each in a fresh process, all green (%s tests)" % sorted(counts)})
    return out
