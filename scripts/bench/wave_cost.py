#!/usr/bin/env python3
"""What a 3-task wave costs in agents, the old way against the new (09.6 T63, criterion C5; decision D20: an isolated measure, no live run).

  python3 scripts/bench/wave_cost.py --old REV --new REV [--write-ttl auto|1h]

Old arm: workflows/execute.js of REV (the part's base, before the part deletes it) under tests/workflow_stub.mjs, with the answers of
`green()` in REV's tests/test_execute_workflow.py: two tasks in parallel, a third, a clean review, `--final`. It is counted by the
launches the script made; any count but 13 (3 executors, 1 reviewer, 9 runners) is exit 1, since a different count is a different run.
New arm: `fwx wave run` of REV on the toy repo of tests/test_wave_run.py (the same three tasks, no GitHub origin, so a local gate),
against the fake `orca` of tests/fake_orca.py, which plays each worker; both come from the checkout this script is in, REV only
supplies the fwx under test. It is counted by the workers it started, and the write price of each is read from the settings copy
the run put in its worktree: 5 minutes where that copy carries D31's FORCE_PROMPT_CACHING_5M=1, 1 hour otherwise or with `--write-ttl 1h`.

Both arms are priced with the constants below (research/wave-cost.md of the phase: its sections 1, 3 and 4), on the sonnet row, which
decides, and the haiku row, which does not. It passes when the new arm's sonnet delta over the old, times the 4 waves a part has, is
at most 0.50 USD per part (D27). Left out as too small to move the verdict: input tokens, the session's own turns (the old arm
spends 6 more per part, about 0.45 USD, so leaving them out is the stricter reading).

Exit 0 passed, 1 a failed check or an arm that did not run, 2 a usage problem.

Controls, each seen red once (the first line each printed):
  --write-ttl 1h (D31's switch off):                 FAIL: new arm above 0.50 USD per part: +3.86
  --new 6a696db (master before `fwx wave run`):      new arm: fwx wave run exited 2: usage: fwx wave --run R [--part-dir D]
  --old a commit whose execute.js has no cleanup
  runner (`st.cleanup = null`):                      FAIL: old arm launches 12, want 13
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

TOP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
TESTS = os.path.join(TOP, "plugins", "fwx", "tests")
LIMIT = 0.50  # USD per part, the band D27 was chosen on
WAVES_PER_PART = 4  # research/wave-cost.md section 4: waves 1 to 4 of part 6, each priced as a 3-task wave
OLD_LAUNCHES = 13  # 3 executors, 1 reviewer, 9 runners (4 reports, 2 diffs, 2 merges, 1 cleanup)
NEW_WORKERS = 4

# USD per million tokens (wave-cost.md section 3: the claude-api model table, write 1.25x for 5m and 2x for 1h of the input price).
PRICE = {
    "sonnet": {"out": 10.00, "read": 0.10, "w5m": 2.50, "w1h": 4.00},  # Sonnet 5.5, the configured model of every role
    "haiku": {"out": 0.50, "read": 0.01, "w5m": 0.125, "w1h": 0.20},  # Haiku 5.5 up to 100K-token prompts; read at 0.1x is assumed
}

# A subagent's whole life, measured from transcripts (wave-cost.md section 4). Executors: the mean of part 5's T51 to T54, session
# 3041169a-a031-4388-b59e-123d72d5164a, workflow wf_17b2137e-0bc and its three siblings. Reviewer: part 5's r1, wf_6b80fd9c-6e0. Runner:
# the mean of the 66 runners of parts 3 to 5 of the same session. turns: assistant turns; write, read, out: summed usage tokens.
# start_write and start_total: the first request, a cold executor (agent a1e552b7f457cea59) and reviewer r1.
AGENT = {
    "executor": {"turns": 45.5, "write": 164382, "read": 5698712, "out": 60251, "start_write": 23413, "start_total": 23413, "worker_start": 60600},
    "reviewer": {"turns": 26, "write": 100527, "read": 1934237, "out": 11792, "start_write": 25887, "start_total": 31193, "worker_start": 58500},
    "runner": {"turns": 2.5, "write": 25604, "read": 39787, "out": 1050},
}
# An Orca worker's first request, measured on today's boundary probes: 52,966 tokens cold (session b68ef865-0ccc-4b18-a2d0-d1e4277896d0)
# and, with the 23,128-token system-and-tools prefix warm, 29,855 written over it (session 5778240a). worker_start above is estimated:
# the probe's 53.0k plus the agent file, base context and task text a subagent also carries (about 22k and 16k characters).
# Those estimates predate the removal of the base context (no agent is handed one now), so 60600 and 58500 are an upper bound.
PREFIX_WARM = 23128
# What a worker writes at 5 minutes with the switch, measured on the haiku worker ctx_6f862dc229a0 (5m 54957, 54957, 630, 328; 1h 0).
SWITCH = "FORCE_PROMPT_CACHING_5M"

OLD_START_READ = {"executor": 0, "reviewer": 5304}  # what a subagent's first request reads from cache (the reviewer's, r1)


def sh(*cmd, cwd=None, env=None):
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, env=env, timeout=600)


class Tree:
    """A detached worktree of REV in a temp dir of its own, removed with it."""

    def __init__(self, rev):
        self.rev, self.dir = rev, tempfile.mkdtemp(prefix="wave-cost-")
        self.root = os.path.join(self.dir, "tree")
        r = sh("git", "-c", "core.hooksPath=/dev/null", "-C", TOP, "worktree", "add", "--detach", "-q", self.root, rev)
        if r.returncode:
            self.close()
            sys.exit("wave_cost: cannot check out %s: %s" % (rev, r.stderr.strip()))

    def close(self):
        sh("git", "-C", TOP, "worktree", "remove", "--force", self.root)
        shutil.rmtree(self.dir, ignore_errors=True)


def old_arm(root):
    """Launch labels of execute.js at `root` under the stub, or an exit-1 message."""
    code = ("import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import test_execute_workflow as t\n"
            "rec, err = t.go(t.SCRIPT)\n"
            "print(json.dumps({'labels': [l['label'] for l in rec['launches']] if rec else [], 'error': err or ((rec or {}).get('error') or {}).get('message')}))\n")
    r = sh(sys.executable, "-I", "-c", code, os.path.join(root, "plugins", "fwx", "tests"), cwd=root)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        sys.exit("old arm: the stub run printed nothing readable (rc %d): %s" % (r.returncode, (r.stderr or r.stdout).strip()[-300:]))
    if got["error"]:
        sys.exit("old arm: execute.js stopped: %s" % got["error"])
    return got["labels"]


def old_roles(labels):
    roles = {"executor": 0, "reviewer": 0, "runner": 0}
    for label in labels:
        kind = "runner" if label.startswith("executor:runner-") else label.split(":")[0]
        if kind not in roles:
            sys.exit("old arm: a launch labelled %r is neither an executor, a reviewer nor a runner" % label)
        roles[kind] += 1
    return roles


def new_arm(root):
    """({role: workers}, {role: [write ttl of each worker]}) of `fwx wave run` at `root` against the fake orca."""
    sys.path.insert(0, TESTS)
    import helpers
    import test_wave_run as t
    w = t.World(tasks=t.THREE, cap=3)
    try:
        r = w.run(root=os.path.join(root, "plugins", "fwx"))
        if r.returncode:
            sys.exit("new arm: fwx wave run exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-300:]))
        roles, ttl = {"executor": 0, "reviewer": 0}, {"executor": [], "reviewer": []}
        for start in w.starts():
            role = (start["marker"] or {}).get("role")
            if role not in roles:
                sys.exit("new arm: a worker with role %r" % role)
            roles[role] += 1
            switched = ((start["settings"] or {}).get("env") or {}).get(SWITCH) == "1"
            ttl[role].append("5m" if switched else "1h")
        return roles, ttl
    finally:
        w.stop()
        helpers.cleanup()


def cost(model, roles, ttls=None):
    """USD of one wave's agents. `ttls` None prices subagents (writes at 5 minutes, the stats as measured); else workers: each
    one's start replaced by the worker's, the larger prefix re-read on every later turn, its writes at its own price."""
    p, total = PRICE[model], 0.0
    for role, n in roles.items():
        a = AGENT[role]
        for i in range(n):
            write, read = a["write"], a["read"]
            price = p["w5m"]
            if ttls is not None:
                extra = a["worker_start"] - a["start_total"]
                write += a["worker_start"] - PREFIX_WARM - a["start_write"]
                read += PREFIX_WARM - OLD_START_READ[role] + (a["turns"] - 1) * extra
                price = p["w" + ttls[role][i]]
            total += (write * price + read * p["read"] + a["out"] * p["out"]) / 1e6
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--old", required=True, help="the part's base: a revision where workflows/execute.js and its tests exist")
    ap.add_argument("--new", required=True, help="the revision whose `fwx wave run` is measured")
    ap.add_argument("--write-ttl", choices=("auto", "1h"), default="auto", help="1h prices every worker's writes at 1 hour, as with D31's switch off")
    args = ap.parse_args()
    old_tree = new_tree = None
    try:
        old_tree, new_tree = Tree(args.old), Tree(args.new)
        labels = old_arm(old_tree.root)
        old = old_roles(labels)
        if len(labels) != OLD_LAUNCHES:
            print("FAIL: old arm launches %d, want %d" % (len(labels), OLD_LAUNCHES))
            return 1
        new, ttl = new_arm(new_tree.root)
        if sum(new.values()) != NEW_WORKERS:
            print("FAIL: new arm starts %d workers, want %d" % (sum(new.values()), NEW_WORKERS))
            return 1
    finally:
        for tree in (old_tree, new_tree):
            if tree:
                tree.close()
    switched = sum(t == "5m" for v in ttl.values() for t in v)
    if args.write_ttl == "1h":
        ttl = {role: ["1h"] * len(v) for role, v in ttl.items()}
    print("old arm: %d launches (%d executors, %d reviewer, %d runners), execute.js of %s under the workflow stub" % (
        len(labels), old["executor"], old["reviewer"], old["runner"], args.old))
    print("new arm: %d workers (%d executors, %d reviewer); %d of %d settings copies carry %s=1; writes priced at %s" % (
        NEW_WORKERS, new["executor"], new["reviewer"], switched, NEW_WORKERS, SWITCH,
        "1 hour for all (--write-ttl 1h)" if args.write_ttl == "1h" else "5 minutes where they do, 1 hour elsewhere"))
    print("\n| Row | Old (USD) | New (USD) | Delta per wave | Per part, %d waves |\n|---|---|---|---|---|" % WAVES_PER_PART)
    per_part = {}
    for model, name in (("sonnet", "Sonnet 5.5"), ("haiku", "Haiku 5.5, flat price")):
        o, n = cost(model, old), cost(model, new, ttl)
        per_part[model] = (n - o) * WAVES_PER_PART
        print("| %s | %.2f | %.2f | %+.2f | %+.2f |" % (name, o, n, round(n - o, 2) + 0.0, round(per_part[model], 2) + 0.0))
    if per_part["sonnet"] > LIMIT:
        print("\nFAIL: new arm above %.2f USD per part: %+.2f" % (LIMIT, per_part["sonnet"]))
        return 1
    print("\nok: the new arm's sonnet delta is %+.2f USD per part, at most %.2f" % (per_part["sonnet"], LIMIT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
