#!/usr/bin/env python3
"""skill-bench: a task database for measuring whether an agent skill makes a coding agent better.

  skill_bench.py validate [--bench DIR] [--min-per-concept N] [--oracle-timeout S]   # prove every task can fail and pass
  skill_bench.py list     [--bench DIR]                                               # tasks per field and concept

A task is a directory benchmarks/skill-bench/tasks/<id>/ (the spec is benchmarks/skill-bench/README.md). It is only
evidence if its oracle is proved able to fail and able to pass, so `validate` checks per task:
  start    the untouched repo fails the oracle (the task is not already solved)
  ideal    ideal/solution.patch applied: every check passes
  alt      alt/solution.patch (a second, differently built correct answer) applied: every check passes, so the
           oracle is not fitted to one implementation
  naive    naive/solution.patch (a plausible wrong answer) applied: at least one check fails
  oracle   gives the same verdict twice, returns at least one check (looking at nothing is a failure), finishes
Per bench, every concept declared in concepts.json has at least --min-per-concept tasks. Nothing in the bench is
written: every run is on a temp copy. Exit 1 when anything above fails."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BENCH = os.path.join(ROOT, "benchmarks", "skill-bench")
RUNNER = """
import json, runpy, sys
oracle, repo, msg = sys.argv[1:4]
ns = runpy.run_path(oracle)
print("\\n" + json.dumps(ns["check"](repo, open(msg).read())))
"""
KEYS = ("id", "field", "concept", "difficulty", "prompt", "source", "message_required")


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run_oracle(task_dir, repo, message, timeout):
    """(results, error): the oracle's list of {id, passed, evidence} on a repo copy, or why it gave none."""
    with tempfile.TemporaryDirectory() as t:
        runner, msg = os.path.join(t, "runner.py"), os.path.join(t, "message.txt")
        for p, text in ((runner, RUNNER), (msg, message)):
            with open(p, "w") as fh:
                fh.write(text)
        try:
            r = subprocess.run([sys.executable, "-I", runner, os.path.join(task_dir, "oracle.py"), repo, msg],
                               cwd=repo, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, "oracle timeout after %ss" % timeout
    if r.returncode:
        return None, "oracle crashed: %s" % (r.stderr.strip().splitlines() or ["no output"])[-1]
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
        assert isinstance(res, list) and all("id" in c and "passed" in c for c in res)
    except Exception:
        return None, "oracle output is not a list of {id, passed, evidence}"
    return res, None


def fresh(task_dir, patch_rel=None):
    """A temp copy of the task's repo with patch_rel applied: (dir, error)."""
    d = tempfile.mkdtemp(prefix="skillbench-")
    repo = os.path.join(d, "repo")
    shutil.copytree(os.path.join(task_dir, "repo"), repo)
    if patch_rel:
        r = subprocess.run(["git", "apply", "--whitespace=nowarn", os.path.join(task_dir, patch_rel)], cwd=repo,
                           capture_output=True, text=True)
        if r.returncode:
            return d, "%s does not apply: %s" % (patch_rel, (r.stderr.strip().splitlines() or ["?"])[0])
    return d, None


def verdict(task_dir, patch_rel, message, timeout):
    """(results, error) for the task's repo with patch_rel (or nothing) applied."""
    d, err = fresh(task_dir, patch_rel)
    try:
        return (None, err) if err else run_oracle(task_dir, os.path.join(d, "repo"), message, timeout)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def read_message(task_dir, name):
    p = os.path.join(task_dir, name, "message.md")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else None


def validate_task(bench, tid, concepts, timeout):
    """(problems, n_checks) for one task."""
    td = os.path.join(bench, "tasks", tid)
    bad = []
    try:
        meta = read_json(os.path.join(td, "task.json"))
    except Exception as e:
        return ["task.json unreadable: %s" % e], 0
    missing = [k for k in KEYS if k not in meta]
    if missing:
        bad.append("task.json lacks %s" % ", ".join(missing))
    if meta.get("id") != tid:
        bad.append("task.json id %r is not the directory name" % meta.get("id"))
    c = concepts.get(meta.get("concept"))
    if c is None:
        bad.append("concept %r is not declared in concepts.json" % meta.get("concept"))
    elif c.get("field") != meta.get("field"):
        bad.append("field %r is not the field of concept %s (%r)" % (meta.get("field"), meta.get("concept"), c.get("field")))
    src = meta.get("source") or {}
    if src.get("kind") not in ("authored", "public"):
        bad.append("source.kind must be authored or public")
    elif src["kind"] == "public" and not (src.get("ref") and src.get("license")):
        bad.append("a public source needs ref and licence in source")
    if not str(meta.get("prompt", "")).strip():
        bad.append("prompt is empty")
    for rel in ("repo", "oracle.py", "ideal/solution.patch", "alt/solution.patch", "naive/solution.patch"):
        if not os.path.exists(os.path.join(td, rel)):
            bad.append("%s is missing" % rel)
    if bad:
        return bad, 0
    need_msg = bool(meta.get("message_required"))
    msgs = {n: read_message(td, n) for n in ("ideal", "alt", "naive")}
    for n in ("ideal", "alt"):
        if need_msg and msgs[n] is None:
            bad.append("%s/message.md is missing (message_required)" % n)
    msgs = {n: m or "" for n, m in msgs.items()}

    start, err = verdict(td, None, "", timeout)
    n_checks = len(start or [])
    if err:
        return bad + ["start: " + err], 0
    if not start:
        return bad + ["oracle returned zero checks (it looks at nothing)"], 0
    if all(x["passed"] for x in start):
        bad.append("start state already passes the oracle: the task is already solved")
    shape = lambda r: [(x["id"], bool(x["passed"])) for x in (r or [])]  # noqa: E731
    if any(shape(verdict(td, None, "", timeout)[0]) != shape(start) for _ in range(2)):
        bad.append("oracle is nondeterministic: runs on the start state disagree")
    for name in ("ideal", "alt"):
        res, err = verdict(td, "%s/solution.patch" % name, msgs[name], timeout)
        if err:
            bad.append("%s: %s" % (name, err))
        elif not res:
            bad.append("%s: oracle returned zero checks" % name)
        elif not all(x["passed"] for x in res):
            bad.append("%s fails the oracle: %s" % (name, ", ".join(x["id"] for x in res if not x["passed"])))
    res, err = verdict(td, "naive/solution.patch", msgs["naive"], timeout)
    if err:
        bad.append("naive: " + err)
    elif res and all(x["passed"] for x in res):
        bad.append("naive solution passes the oracle: the oracle cannot tell a wrong answer from a right one")
    return bad, n_checks


def load(bench):
    concepts = read_json(os.path.join(bench, "concepts.json"))
    tdir = os.path.join(bench, "tasks")
    ids = sorted(d for d in os.listdir(tdir) if os.path.isdir(os.path.join(tdir, d))) if os.path.isdir(tdir) else []
    return concepts, ids


def cmd_validate(a):
    concepts, ids = load(a.bench)
    problems, per_concept = 0, {c: 0 for c in concepts}
    for tid in ids:
        bad, n = validate_task(a.bench, tid, concepts, a.oracle_timeout)
        try:
            per_concept[read_json(os.path.join(a.bench, "tasks", tid, "task.json")).get("concept")] += 1
        except Exception:
            pass
        if bad:
            problems += len(bad)
            for b in bad:
                print("  ! %s: %s" % (tid, b))
        else:
            print("  %s: ok (%d checks)" % (tid, n))
    thin = {c: n for c, n in per_concept.items() if n < a.min_per_concept}
    for c, n in sorted(thin.items()):
        problems += 1
        print("  ! coverage: %s has %d task(s), want at least %d" % (c, n, a.min_per_concept))
    print("\n%d tasks | %d/%d concepts at %d or more | %d failure(s)"
          % (len(ids), len(concepts) - len(thin), len(concepts), a.min_per_concept, problems))
    return 1 if problems else 0


def cmd_list(a):
    concepts, ids = load(a.bench)
    count = {}
    for tid in ids:
        try:
            c = read_json(os.path.join(a.bench, "tasks", tid, "task.json")).get("concept")
        except Exception:
            c = "?"
        count[c] = count.get(c, 0) + 1
    for c, meta in sorted(concepts.items(), key=lambda kv: (kv[1].get("field"), kv[0])):
        print("%-8s %-34s %d" % (meta.get("field"), c, count.get(c, 0)))
    print("%d tasks, %d concepts" % (len(ids), len(concepts)))
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("validate", cmd_validate), ("list", cmd_list)):
        s = sub.add_parser(name)
        s.add_argument("--bench", default=DEFAULT_BENCH)
        if name == "validate":
            s.add_argument("--min-per-concept", type=int, default=2)
            s.add_argument("--oracle-timeout", type=int, default=60)
        s.set_defaults(fn=fn)
    a = p.parse_args()
    if not os.path.isfile(os.path.join(a.bench, "concepts.json")):
        sys.exit("! %s has no concepts.json" % a.bench)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
