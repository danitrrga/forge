#!/usr/bin/env python3
"""skill-bench: a task database for measuring whether an agent skill makes a coding agent better.

  skill_bench.py validate [--bench DIR] [--min-per-concept N] [--oracle-timeout S]   # prove every task can fail and pass
  skill_bench.py list     [--bench DIR]                                               # tasks per field and concept
  skill_bench.py run      --arm none --arm NAME=SKILLDIR ... [--tasks all|ids|field:ui] [--k 3] [--out DIR]
  skill_bench.py report   --out DIR [--base none]                                     # paired comparison of the arms

A task is a directory benchmarks/skill-bench/tasks/<id>/ (the spec is benchmarks/skill-bench/README.md). It is only
evidence if its oracle is proved able to fail and able to pass, so `validate` checks per task:
  start    the untouched repo fails the oracle (the task is not already solved)
  ideal    ideal/solution.patch applied: every check passes
  alt      alt/solution.patch (a second, differently built correct answer) applied: every check passes, so the
           oracle is not fitted to one implementation
  naive    naive/solution.patch (a plausible wrong answer) applied: at least one check fails
  oracle   gives the same verdict twice, returns at least one check (looking at nothing is a failure), finishes
Per bench, every concept declared in concepts.json has at least --min-per-concept tasks. Nothing in the bench is
written: every run is on a temp copy. Exit 1 when anything above fails.

`run` plays each task as an arm x trial job: a throwaway git copy of repo/, the arm's skill directories mounted under
.claude/skills/, `claude -p` in an isolated config dir (no user hooks, skills or CLAUDE.md; only the login is shared) and
inside bubblewrap when available (home hidden, only the work dir writable), then the task oracle scores the tree and the
final reply. Jobs are interleaved across arms, resumable (finished jobs are skipped), and a run whose oracle crashes is
INVALID: counted, never scored as a fail. `report` compares every arm with --base per task (the k trials averaged first):
paired mean difference, 95% bootstrap CI over tasks, sign-flip permutation p, discordant counts, Wilson intervals per arm,
and the token, cost and time deltas, as benchmarks/skill-bench/SOURCES.md recommends."""
import argparse
import json
import math
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

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


# ----------------------------------------------------------------------------------------------------------- statistics

def wilson(k, n, z=1.96):
    """Wilson score interval for k successes in n trials; (None, None) for n = 0."""
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def sign_flip_p(diffs, rng, n_perm=20000):
    """Two-sided paired sign-flip permutation p-value for the mean of per-task differences: exact up to 16 tasks."""
    n = len(diffs)
    if n == 0:
        return None
    obs = abs(sum(diffs)) / n
    if n <= 16:
        hits = 0
        for mask in range(1 << n):
            tot = sum(d if mask >> i & 1 else -d for i, d in enumerate(diffs))
            hits += abs(tot) / n >= obs - 1e-12
        return hits / (1 << n)
    hits = sum(abs(sum(d if rng.random() < 0.5 else -d for d in diffs)) / n >= obs - 1e-12 for _ in range(n_perm))
    return (1 + hits) / (n_perm + 1)


def bootstrap_ci(diffs, rng, reps=10000):
    """95% percentile bootstrap interval of the mean difference, resampling tasks."""
    n = len(diffs)
    if n == 0:
        return None, None
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(reps))
    return means[int(0.025 * reps)], means[min(reps - 1, int(0.975 * reps))]


# ----------------------------------------------------------------------------------------------------------------- run

def parse_arms(specs):
    """[(name, [skill dirs])] from --arm NAME or NAME=DIR[:DIR...]; `none` and a bare name mount nothing."""
    arms = []
    for spec in specs:
        name, _, dirs = spec.partition("=")
        paths = [d for d in dirs.split(":") if d]
        for d in paths:
            if not os.path.isfile(os.path.join(d, "SKILL.md")):
                sys.exit("! arm %s: %s has no SKILL.md" % (name, d))
        arms.append((name, paths))
    if len({n for n, _ in arms}) != len(arms):
        sys.exit("! two arms share a name")
    return arms


def select_tasks(bench, selector):
    concepts, ids = load(bench)
    if selector == "all":
        return ids
    out = []
    for part in selector.split(","):
        if part.startswith(("field:", "concept:")):
            key, _, val = part.partition(":")
            out += [t for t in ids if read_json(os.path.join(bench, "tasks", t, "task.json")).get(key) == val]
        elif part in ids:
            out.append(part)
        else:
            sys.exit("! no task %r in %s" % (part, bench))
    return list(dict.fromkeys(out))


def agent_home(out):
    """A CLAUDE_CONFIG_DIR with no hooks, skills or CLAUDE.md; only the login is shared with the real home."""
    d = os.path.join(out, "agent-home")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "settings.json"), "w") as fh:
        json.dump({"model": "sonnet"}, fh)
    real = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    link = os.path.join(d, ".credentials.json")
    if os.path.exists(real) and not os.path.lexists(link):
        os.symlink(real, link)
    return d


def wrap(cmd, sandbox, work, home, claude_bin):
    """`cmd` inside bubblewrap: the real home hidden by a tmpfs, only the work dir and the agent home writable."""
    if sandbox == "none" or (sandbox == "auto" and not shutil.which("bwrap")):
        return cmd
    h = os.path.expanduser("~")
    real_cred = os.path.join(h, ".claude", ".credentials.json")
    binds = ["--bind", work, work, "--bind", home, home]
    for ro in (os.path.join(h, ".local", "share", "mise"), os.path.join(h, ".local", "bin"), os.path.dirname(os.path.realpath(claude_bin))):
        binds += ["--ro-bind-try", ro, ro]
    if os.path.exists(real_cred):
        binds += ["--bind", real_cred, real_cred]
    return (["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", h]
            + binds + ["--unshare-pid", "--die-with-parent", "--chdir", work, "--"] + cmd)


def parse_stream(text):
    """(final message, usage dict, cost, turns, skill_called, is_error) from claude's stream-json lines."""
    msg, usage, cost, turns, called, err = "", {}, None, None, False, False
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use" and (c.get("name") == "Skill" or ".claude/skills/" in json.dumps(c.get("input", {}))):
                    called = True
        if ev.get("type") == "result":
            msg, usage = ev.get("result") or "", ev.get("usage") or {}
            cost, turns, err = ev.get("total_cost_usd"), ev.get("num_turns"), bool(ev.get("is_error"))
    return msg, usage, cost, turns, called, err


def do_job(job, a):
    task, arm, paths, trial = job
    base = os.path.join(a.out, task, arm, str(trial))
    shutil.rmtree(base, ignore_errors=True)
    work = os.path.join(base, "work")
    td = os.path.join(a.bench, "tasks", task)
    shutil.copytree(os.path.join(td, "repo"), work)
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=bench", "-c", "user.email=bench", "commit", "-qm", "start"]):
        subprocess.run(["git", "-C", work] + c, check=True, capture_output=True)
    for sd in paths:
        shutil.copytree(sd, os.path.join(work, ".claude", "skills", os.path.basename(sd.rstrip("/"))))
    meta = read_json(os.path.join(td, "task.json"))
    prompt = meta["prompt"]
    if a.force_skill and paths:
        prompt = "Use the skill in .claude/skills/%s for this task.\n\n%s" % (os.path.basename(paths[0].rstrip("/")), prompt)
    home = agent_home(a.out)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_CODE_ENTRYPOINT")}
    env["CLAUDE_CONFIG_DIR"] = home
    cmd = wrap([a.claude_bin, "-p", prompt, "--model", a.model, "--output-format", "stream-json", "--verbose",
                "--permission-mode", "bypassPermissions", "--no-session-persistence"], a.sandbox, work, home, a.claude_bin)
    started, timed_out = time.time(), False
    p = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    try:
        stdout, stderr = p.communicate(timeout=a.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(p.pid, signal.SIGKILL)
        stdout, stderr = p.communicate()
    with open(os.path.join(base, "agent.jsonl"), "w") as fh:
        fh.write(stdout or "")
    with open(os.path.join(base, "agent.err"), "w") as fh:
        fh.write(stderr or "")
    msg, usage, cost, turns, called, err = parse_stream(stdout or "")
    res = {"task": task, "field": meta.get("field"), "concept": meta.get("concept"), "arm": arm, "trial": trial,
           "started": started, "duration_s": round(time.time() - started, 1), "timed_out": timed_out, "skill_called": called,
           "tokens": sum(usage.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
           "cost_usd": cost, "turns": turns, "agent_error": err, "message_chars": len(msg), "checks": [], "passed": False, "invalid": False}
    checks, why = run_oracle(td, work, msg, a.oracle_timeout)
    if why:
        res.update(invalid=True, passed=None, invalid_reason=why)
    else:
        res.update(checks=checks, passed=bool(checks) and all(c["passed"] for c in checks))
    with open(os.path.join(base, "result.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    return res


def cmd_run(a):
    tasks = select_tasks(a.bench, a.tasks)
    arms = parse_arms(a.arm or ["none"])
    rng = random.Random(a.seed)
    jobs = []
    for trial in range(1, a.k + 1):
        block = [(t, n, ps, trial) for t in tasks for n, ps in arms]
        rng.shuffle(block)
        jobs += block
    todo = [j for j in jobs if not os.path.exists(os.path.join(a.out, j[0], j[1], str(j[3]), "result.json"))]
    print("%d to run, %d already done (%d tasks x %d arms x k=%d)" % (len(todo), len(jobs) - len(todo), len(tasks), len(arms), a.k))
    os.makedirs(a.out, exist_ok=True)
    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(lambda j: do_job(j, a), todo):
            done += 1
            print("  [%d/%d] %s %s #%d: %s" % (done, len(todo), r["task"], r["arm"], r["trial"],
                                              "INVALID " + r.get("invalid_reason", "") if r["invalid"] else ("pass" if r["passed"] else "fail")), flush=True)
    print("results in %s" % a.out)
    return 0


# -------------------------------------------------------------------------------------------------------------- report

def load_results(out):
    res = []
    for root, _, files in os.walk(out):
        if "result.json" in files:
            res.append(read_json(os.path.join(root, "result.json")))
    return res


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def cmd_report(a):
    res = load_results(a.out)
    if not res:
        sys.exit("! no results under %s" % a.out)
    arms = sorted({r["arm"] for r in res}, key=lambda x: (x != a.base, x))
    if a.base not in arms:
        sys.exit("! base arm %r has no results (arms: %s)" % (a.base, ", ".join(arms)))
    score = {}   # (task, arm) -> mean pass over valid trials
    for r in res:
        if not r["invalid"]:
            score.setdefault((r["task"], r["arm"]), []).append(1.0 if r["passed"] else 0.0)
    invalid = {x: sum(1 for r in res if r["arm"] == x and r["invalid"]) for x in arms}
    print("skill-bench report: %d runs (%d invalid), %d tasks, arms %s, base %s"
          % (len(res), sum(invalid.values()), len({r["task"] for r in res}), ", ".join(arms), a.base))
    for x in arms:
        v = [r for r in res if r["arm"] == x and not r["invalid"]]
        k, n = sum(1 for r in v if r["passed"]), len(v)
        lo, hi = wilson(k, n)
        print("  %-12s pass %d/%d%s | %d invalid | tokens/run %s | cost/run %s | s/run %s | skill called in %s" % (
            x, k, n, " (%.2f-%.2f)" % (lo, hi) if n else "", invalid[x],
            "%.0f" % mean([r["tokens"] for r in v]) if v else "-",
            "$%.2f" % mean([r["cost_usd"] for r in v if r["cost_usd"] is not None] or [0]) if v else "-",
            "%.0f" % mean([r["duration_s"] for r in v]) if v else "-",
            "%.0f%% of runs" % (100 * mean([1.0 if r["skill_called"] else 0.0 for r in v])) if v else "-"))
    rng = random.Random(20261023)
    for x in arms:
        if x == a.base:
            continue
        tasks = sorted({t for (t, ar) in score if ar == x} & {t for (t, ar) in score if ar == a.base})
        diffs = [mean(score[(t, x)]) - mean(score[(t, a.base)]) for t in tasks]
        if not diffs:
            print("\narm %s vs %s: no task has valid runs in both" % (x, a.base))
            continue
        lo, hi = bootstrap_ci(diffs, rng, a.bootstrap)
        p = sign_flip_p(diffs, rng)
        better, worse = sum(d > 1e-12 for d in diffs), sum(d < -1e-12 for d in diffs)
        print("\narm %s vs %s: n=%d tasks | diff %+.3f [95%% CI %+.3f, %+.3f] | p=%.4f | %d better, %d worse, %d same"
              % (x, a.base, len(tasks), mean(diffs), lo, hi, p, better, worse, len(diffs) - better - worse))
        for label, key in (("tokens", "tokens"), ("cost", "cost_usd"), ("seconds", "duration_s")):
            va = mean([r[key] for r in res if r["arm"] == x and not r["invalid"] and r[key] is not None] or [None]) if any(
                r["arm"] == x and not r["invalid"] and r[key] is not None for r in res) else None
            vb = mean([r[key] for r in res if r["arm"] == a.base and not r["invalid"] and r[key] is not None]) if any(
                r["arm"] == a.base and not r["invalid"] and r[key] is not None for r in res) else None
            if va is not None and vb:
                print("  %-7s %s %.2f vs %s %.2f (%+.0f%%)" % (label, x, va, a.base, vb, 100 * (va - vb) / vb))
        fields = sorted({r["field"] for r in res})
        row = []
        for f in fields:
            fd = [mean(score[(t, x)]) - mean(score[(t, a.base)]) for t in tasks if any(r["task"] == t and r["field"] == f for r in res)]
            if fd:
                row.append("%s %+.2f (n=%d)" % (f, mean(fd), len(fd)))
        print("  by field (descriptive only): " + ", ".join(row))
    print("\nNote: a flat result means 'not larger than the minimum detectable effect', not 'no effect'; see SOURCES.md.")
    return 0


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
    r = sub.add_parser("run")
    r.add_argument("--bench", default=DEFAULT_BENCH)
    r.add_argument("--arm", action="append")
    r.add_argument("--tasks", default="all")
    r.add_argument("--k", type=int, default=3)
    r.add_argument("--out", required=True)
    r.add_argument("--model", default="sonnet")
    r.add_argument("--workers", type=int, default=3)
    r.add_argument("--timeout", type=int, default=900)
    r.add_argument("--oracle-timeout", type=int, default=120)
    r.add_argument("--claude-bin", default="claude")
    r.add_argument("--sandbox", choices=("auto", "bwrap", "none"), default="auto")
    r.add_argument("--force-skill", action="store_true", help="tell the agent to use the arm's first skill (default: let it decide)")
    r.add_argument("--seed", type=int, default=1)
    r.set_defaults(fn=cmd_run)
    q = sub.add_parser("report")
    q.add_argument("--out", required=True)
    q.add_argument("--base", default="none")
    q.add_argument("--bootstrap", type=int, default=10000)
    q.set_defaults(fn=cmd_report, bench=None)
    a = p.parse_args()
    if a.bench is not None and not os.path.isfile(os.path.join(a.bench, "concepts.json")):
        sys.exit("! %s has no concepts.json" % a.bench)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
