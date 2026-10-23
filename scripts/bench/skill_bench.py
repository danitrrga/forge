#!/usr/bin/env python3
"""skill-bench: a task database for measuring whether an agent skill makes a coding agent better.

  skill_bench.py validate [--bench DIR] [--min-per-concept N] [--oracle-timeout S]   # prove every task can fail and pass
  skill_bench.py list     [--bench DIR]                                               # tasks per field and concept
  skill_bench.py run      --arm none --arm NAME=SKILLDIR ... [--tasks all|ids|field:ui] [--k 3] [--out DIR] [--keep-work]
  skill_bench.py report   --out DIR [--base none]                                     # paired comparison of the arms
  skill_bench.py calibrate --out DIR [--arm none]   # write <bench>/calibration.json: each task's baseline pass rate
  skill_bench.py select   --tasks hard[:RATE]       # print the task ids a selector picks (hard = baseline rate <= RATE, default 0.7)

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
INVALID: counted, never scored as a fail. Only tasks a model can still fail carry signal about a skill, so `calibrate` records the no-skill arm's pass rate per task and
`--tasks hard` keeps those at or under 0.7; `report` prints how many tasks were saturated (baseline of 0.9 or more).
Space: runs go to $XDG_DATA_HOME/forge/skill-bench/runs/<timestamp> (durable, not /tmp); each finished run keeps result.json and a
gzipped transcript and drops its working copy (--keep-work keeps it); report and calibrate read the latest run when --out is absent.
`report` compares every arm with --base per task (the k trials averaged first):
paired mean difference, 95% bootstrap CI over tasks, sign-flip permutation p, discordant counts, Wilson intervals per arm,
and the token, cost and time deltas, as benchmarks/skill-bench/SOURCES.md recommends."""
import argparse
import gzip
import hashlib
import json
import math
import os
import random
import shutil
import signal
import subprocess
import sys
import platform
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


def data_dir():
    """Durable home of run results: $XDG_DATA_HOME/forge/skill-bench (not the cache and never /tmp, which a reboot empties)."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "forge", "skill-bench")


def latest_run():
    runs = os.path.join(data_dir(), "runs")
    found = sorted(os.listdir(runs)) if os.path.isdir(runs) else []
    if not found:
        sys.exit("! no run under %s: pass --out" % runs)
    return os.path.join(runs, found[-1])


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run_oracle(task_dir, repo, message, timeout):
    """(results, error): the oracle's list of {id, passed, evidence} on a repo copy, or why it gave none."""
    meta = project_meta(task_dir)
    if meta is not None:
        return run_checks(meta, repo, timeout, task_dir)
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


def project_meta(task_dir):
    """task.json of a project task (source.kind == "project"), else None."""
    try:
        meta = read_json(os.path.join(task_dir, "task.json"))
    except Exception:
        return None
    return meta if (meta.get("source") or {}).get("kind") == "project" else None


def sh(cmd, cwd, timeout):
    """(returncode, output tail) of a shell command; a timeout is returncode 124."""
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "timeout after %ss" % timeout
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()[-300:]


def materialize(task_dir, repo, setup_timeout=900):
    """Fill repo with a task's starting tree and return an error string or None. A project task is a `git archive` of its base
    commit (in the git repository that holds the bench) committed into a fresh repository, so the history, and with it the
    merged fix, is not there to read; the bench itself is removed from the tree, then the setup commands run."""
    meta = project_meta(task_dir)
    if meta is None:
        shutil.copytree(os.path.join(task_dir, "repo"), repo)
        return None
    bench = os.path.dirname(os.path.dirname(task_dir))
    top = subprocess.run(["git", "-C", bench, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode:
        return "bench is not inside a git repository"
    commit = (meta.get("base") or {}).get("commit", "")
    os.makedirs(repo)
    arc = subprocess.run("git -C %s archive %s | tar -x -C %s" % (_q(top.stdout.strip()), _q(commit), _q(repo)), shell=True,
                         capture_output=True, text=True)
    if arc.returncode or not os.listdir(repo):
        return "base commit %s not found in %s" % (commit[:12] or "?", top.stdout.strip())
    shutil.rmtree(os.path.join(repo, os.path.basename(bench)), ignore_errors=True)
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=bench", "-c", "user.email=bench", "commit", "-qm", "start"]):
        subprocess.run(["git", "-C", repo] + c, check=True, capture_output=True)
    for cmd in meta.get("setup") or []:
        rc, out = sh(cmd, repo, setup_timeout)
        if rc:
            return "setup failed (%s): %s" % (cmd, out[-120:])
    return None


def _q(x):
    import shlex
    return shlex.quote(x)


def run_checks(meta, repo, timeout, task_dir=None):
    """(results, None) for a project task: each check's shell command run in repo, exit status 0 = passed. Files in the task's
    overlay/ directory are copied over the tree first: the hidden tests that came with the merged fix, which the ideal diff leaves
    out (a correct answer that did not add that very test would fail otherwise) and the agent never sees."""
    if task_dir and os.path.isdir(os.path.join(task_dir, "overlay")):
        shutil.copytree(os.path.join(task_dir, "overlay"), repo, dirs_exist_ok=True)
    res = []
    for c in meta.get("checks") or []:
        rc, out = sh(c["cmd"], repo, c.get("timeout", timeout))
        res.append({"id": c["id"], "passed": rc == 0, "evidence": out[-160:]})
    return res, None


def fresh(task_dir, patch_rel=None):
    """A temp copy of the task's starting tree with patch_rel applied: (dir, error)."""
    d = tempfile.mkdtemp(prefix="skillbench-")
    repo = os.path.join(d, "repo")
    err = materialize(task_dir, repo)
    if err:
        return d, err
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


def validate_project(bench, tid, concepts, timeout):
    """(problems, n_checks) for a project task: see the module docstring."""
    td = os.path.join(bench, "tasks", tid)
    meta = project_meta(td)
    bad = [("task.json lacks %s" % k) for k in KEYS + ("base", "checks") if k not in meta]
    if meta.get("id") != tid:
        bad.append("task.json id %r is not the directory name" % meta.get("id"))
    c = concepts.get(meta.get("concept"))
    if c is None:
        bad.append("concept %r is not declared in concepts.json" % meta.get("concept"))
    elif c.get("field") != meta.get("field"):
        bad.append("field %r is not the field of concept %s" % (meta.get("field"), meta.get("concept")))
    checks = meta.get("checks") or []
    if not checks:
        bad.append("zero checks: the task looks at nothing")
    for c in checks:
        if not (c.get("id") and c.get("cmd") and c.get("before") in ("fail", "pass")):
            bad.append("check %r needs id, cmd and before (fail or pass)" % c.get("id"))
    if len({c.get("id") for c in checks}) != len(checks):
        bad.append("check ids are not unique")
    if not os.path.exists(os.path.join(td, "ideal", "solution.patch")):
        bad.append("ideal/solution.patch is missing")
    if meta.get("message_required") and not os.path.exists(os.path.join(td, "ideal", "message.md")):
        bad.append("ideal/message.md is missing (message_required)")
    if bad:
        return bad, 0
    before = {c["id"]: c["before"] == "pass" for c in checks}
    start, err = verdict(td, None, "", timeout)
    if err:
        return [("start: " + err)], 0
    wrong = [r["id"] for r in start if r["passed"] != before[r["id"]]]
    if wrong:
        bad.append("at base these checks do not give their declared 'before' verdict: %s" % ", ".join(wrong))
    if not any(not v for v in before.values()) or all(r["passed"] for r in start):
        bad.append("no check fails at base: the task is already solved")
    shape = lambda r: [(x["id"], bool(x["passed"])) for x in (r or [])]  # noqa: E731
    if any(shape(verdict(td, None, "", timeout)[0]) != shape(start) for _ in range(2)):
        bad.append("a check is nondeterministic: runs at base disagree")
    runs = [verdict(td, "ideal/solution.patch", "", timeout) for _ in range(3)]
    for res, err in runs[:1]:
        if err:
            bad.append("ideal: " + err)
        elif not all(x["passed"] for x in res):
            bad.append("ideal fails: %s" % ", ".join(x["id"] for x in res if not x["passed"]))
    if not any(r[1] for r in runs) and len({tuple(shape(r[0])) for r in runs}) > 1:
        bad.append("a check is nondeterministic: the ideal diff gives different verdicts on three runs")
    for name, must_pass in (("alt", True), ("naive", False)):
        if not os.path.exists(os.path.join(td, name, "solution.patch")):
            continue
        res, err = verdict(td, "%s/solution.patch" % name, "", timeout)
        if err:
            bad.append("%s: %s" % (name, err))
        elif must_pass and not all(x["passed"] for x in res):
            bad.append("alt fails: %s" % ", ".join(x["id"] for x in res if not x["passed"]))
        elif not must_pass and all(x["passed"] for x in res):
            bad.append("naive solution passes every check: the checks cannot tell a wrong answer from a right one")
    return bad, len(checks)


def validate_task(bench, tid, concepts, timeout):
    """(problems, n_checks) for one task."""
    td = os.path.join(bench, "tasks", tid)
    if project_meta(td) is not None:
        return validate_project(bench, tid, concepts, timeout)
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

def tree_hash(d):
    """sha256 over the sorted files of a directory, each as relative path, NUL, bytes, NUL: what an arm's skill is, exactly."""
    h = hashlib.sha256()
    for root, dirs, files in sorted(os.walk(d)):
        dirs.sort()
        for f in sorted(files):
            full = os.path.join(root, f)
            h.update(os.path.relpath(full, d).encode() + b"\0" + open(full, "rb").read() + b"\0")
    return h.hexdigest()


def cli_version(claude_bin):
    try:
        r = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        return (r.stdout.strip().splitlines() or ["unknown"])[0]
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def write_manifest(a, tasks, arms):
    """<out>/run.json: which model, CLI, arms (by skill content hash) and tasks (by fingerprint) a run directory holds. A directory
    already holding results is only extended by a run with the same model alias and the same content behind every arm name, so the
    names in a report always mean the same thing."""
    path = os.path.join(a.out, "run.json")
    fp = hashlib.sha256()
    for t in sorted(tasks):
        fp.update(tree_hash(os.path.join(a.bench, "tasks", t)).encode())
    new_arms = {n: {"skills": [{"dir": d, "sha256": tree_hash(d)} for d in ps]} for n, ps in arms}
    ver = cli_version(a.claude_bin)
    man = {"model_alias": a.model, "cli_version": ver, "k": a.k, "seed": a.seed, "sandbox": a.sandbox, "force_skill": a.force_skill,
           "bench": a.bench, "tasks": sorted(tasks), "tasks_fingerprint": fp.hexdigest(), "arms": new_arms, "platform": sys.platform,
           "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "invocations": 1}
    if os.path.isfile(path):
        old = read_json(path)
        if old.get("model_alias") != a.model:
            sys.exit("! %s was started with model %r, this run asks for %r: use a new --out (a result file must mean one model)"
                     % (a.out, old.get("model_alias"), a.model))
        for n, v in new_arms.items():
            if n in old.get("arms", {}) and old["arms"][n] != v:
                sys.exit("! arm %r changed since %s was started (its skill content differs): use a new arm name or a new --out" % (n, a.out))
        old["arms"].update(new_arms)
        old["tasks"] = sorted(set(old.get("tasks", [])) | set(tasks))
        old["invocations"] = old.get("invocations", 1) + 1
        old["cli_versions"] = sorted(set(old.get("cli_versions", [old.get("cli_version")])) | {ver})
        man = old
    with open(path, "w") as fh:
        json.dump(man, fh, indent=1)
        fh.write("\n")


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


def calibration(bench):
    p = os.path.join(bench, "calibration.json")
    if not os.path.isfile(p):
        sys.exit("! %s was never calibrated: run a no-skill baseline (run --arm none --k 3), then `calibrate --out <that run>`" % bench)
    return read_json(p)


def select_tasks(bench, selector):
    """Task ids for a selector: comma-separated `all`, ids, `field:F`, `concept:C`, and `hard[:RATE]`, which keeps the tasks whose
    calibrated baseline pass rate is at most RATE (default 0.7) and intersects with whatever the others picked."""
    concepts, ids = load(bench)
    parts = [x for x in selector.split(",") if x]
    hard = [x for x in parts if x == "hard" or x.startswith("hard:")]
    rest = [x for x in parts if x not in hard]
    chosen = []
    for part in rest or ["all"]:
        if part == "all":
            chosen += ids
        elif part.startswith(("field:", "concept:")):
            key, _, val = part.partition(":")
            chosen += [t for t in ids if read_json(os.path.join(bench, "tasks", t, "task.json")).get(key) == val]
        elif part in ids:
            chosen.append(part)
        else:
            sys.exit("! no task %r in %s" % (part, bench))
    chosen = list(dict.fromkeys(chosen))
    if hard:
        limit = float(hard[0].partition(":")[2] or 0.7)
        rates = calibration(bench)["tasks"]
        chosen = [t for t in chosen if t in rates and rates[t]["rate"] <= limit]
    return chosen


def agent_home(out):
    """A CLAUDE_CONFIG_DIR with no hooks, skills or CLAUDE.md; only the login is shared with the real home."""
    d = os.path.join(out, "agent-home")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "settings.json"), "w") as fh:
        json.dump({"model": "sonnet"}, fh)
    real = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    link = os.path.join(d, ".credentials.json")
    if os.path.exists(real) and not os.path.lexists(link):
        try:
            os.symlink(real, link)
        except FileExistsError:   # another worker made it between the check and the call
            pass
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
    """(final message, usage dict, cost, turns, skill_called, is_error, model id) from claude's stream-json lines."""
    msg, usage, cost, turns, called, err, model = "", {}, None, None, False, False, "unknown"
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init" and ev.get("model"):
            model = ev["model"]
        if ev.get("type") == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use" and (c.get("name") == "Skill" or ".claude/skills/" in json.dumps(c.get("input", {}))):
                    called = True
        if ev.get("type") == "result":
            msg, usage = ev.get("result") or "", ev.get("usage") or {}
            cost, turns, err = ev.get("total_cost_usd"), ev.get("num_turns"), bool(ev.get("is_error"))
    return msg, usage, cost, turns, called, err, model


def do_job(job, a):
    """One job, never fatal: whatever goes wrong inside it becomes an INVALID result, so one crash cannot end the whole run."""
    try:
        return _do_job(job, a)
    except Exception as e:   # noqa: BLE001
        task, arm, _, trial = job
        base = os.path.join(a.out, task, arm, str(trial))
        os.makedirs(base, exist_ok=True)
        res = {"task": task, "arm": arm, "trial": trial, "invalid": True, "passed": None, "started": time.time(),
               "invalid_reason": "runner error: %s: %s" % (type(e).__name__, str(e)[:160]), "field": None, "concept": None,
               "skill_called": False, "tokens": 0, "cost_usd": None, "duration_s": 0, "checks": []}
        with open(os.path.join(base, "result.json"), "w") as fh:
            json.dump(res, fh, indent=1)
        return res


def _do_job(job, a):
    task, arm, paths, trial = job
    base = os.path.join(a.out, task, arm, str(trial))
    shutil.rmtree(base, ignore_errors=True)
    work = os.path.join(base, "work")
    td = os.path.join(a.bench, "tasks", task)
    err = materialize(td, work)
    if err:
        res = {"task": task, "arm": arm, "trial": trial, "invalid": True, "passed": None, "invalid_reason": err, "started": time.time(),
               "field": None, "concept": None, "skill_called": False, "tokens": 0, "cost_usd": None, "duration_s": 0, "checks": []}
        with open(os.path.join(base, "result.json"), "w") as fh:
            json.dump(res, fh, indent=1)
        return res
    if project_meta(td) is None:
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
    msg, usage, cost, turns, called, err, model_id = parse_stream(stdout or "")
    res = {"task": task, "field": meta.get("field"), "concept": meta.get("concept"), "arm": arm, "trial": trial,
           "model": a.model, "model_id": model_id, "started": started, "duration_s": round(time.time() - started, 1), "timed_out": timed_out, "skill_called": called,
           "tokens": sum(usage.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
           "cost_usd": cost, "turns": turns, "agent_error": err, "message_chars": len(msg), "checks": [], "passed": False, "invalid": False}
    checks, why = run_oracle(td, work, msg, a.oracle_timeout)
    if why:
        res.update(invalid=True, passed=None, invalid_reason=why)
    else:
        res.update(checks=checks, passed=bool(checks) and all(c["passed"] for c in checks))
    with open(os.path.join(base, "result.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    if not a.keep_work:   # space: the scored working copy goes, the plain transcript is kept gzipped (about a tenth of its size)
        shutil.rmtree(work, ignore_errors=True)
        plain = os.path.join(base, "agent.jsonl")
        if os.path.exists(plain):
            with open(plain, "rb") as src, gzip.open(plain + ".gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.remove(plain)
    return res


def cmd_run(a):
    if not a.out:
        a.out = os.path.join(data_dir(), "runs", time.strftime("%Y%m%d-%H%M%S"))
        print("results go to %s" % a.out)
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
    write_manifest(a, tasks, arms)
    agent_home(a.out)   # made once here: the workers share it
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
    a.out = a.out or latest_run()
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
    man = read_json(os.path.join(a.out, "run.json")) if os.path.isfile(os.path.join(a.out, "run.json")) else {}
    models = {x: sorted({r.get("model_id", "unknown") for r in res if r["arm"] == x}) for x in arms}
    print("skill-bench report: %d runs (%d invalid), %d tasks, arms %s, base %s"
          % (len(res), sum(invalid.values()), len({r["task"] for r in res}), ", ".join(arms), a.base))
    print("  models: %s | alias %s | CLI %s%s" % ("; ".join("%s=%s" % (x, "+".join(models[x])) for x in arms), man.get("model_alias", "?"),
                                                  ", ".join(man.get("cli_versions") or [man.get("cli_version", "?")]),
                                                  "" if man else " (no run.json: this directory predates the manifest)"))
    if len({tuple(v) for v in models.values()}) > 1:
        print("! arms ran on different models: %s" % "; ".join("%s=%s" % (x, "+".join(models[x])) for x in arms))
        if not a.allow_mixed_models:
            print("  A difference between them would measure the model, not the skill. Re-run on one model, or pass --allow-mixed-models.")
            return 1
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
    base_rates = {t: mean(v) for (t, ar), v in score.items() if ar == a.base}
    sat = sorted(t for t, r in base_rates.items() if r >= 0.9)
    print("  %d of %d tasks are saturated (base pass rate 0.9 or more: no room to improve)%s"
          % (len(sat), len(base_rates), "" if len(sat) < len(base_rates) / 2 else "; most of this score cannot move"))
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


def concepts_path(bench):
    """A bench's own concepts.json, else forge's: a project's .bench holds tasks only and shares the 27 concepts."""
    own = os.path.join(bench, "concepts.json")
    return own if os.path.isfile(own) else os.path.join(DEFAULT_BENCH, "concepts.json")


def cmd_calibrate(a):
    a.out = a.out or latest_run()
    res = [r for r in load_results(a.out) if r["arm"] == a.arm and not r["invalid"]]
    if not res:
        sys.exit("! no valid results of arm %r under %s" % (a.arm, a.out))
    tasks = {}
    for r in res:
        tasks.setdefault(r["task"], []).append(1.0 if r["passed"] else 0.0)
    man = read_json(os.path.join(a.out, "run.json")) if os.path.isfile(os.path.join(a.out, "run.json")) else {}
    doc = {"arm": a.arm, "model": sorted({r.get("model") or "?" for r in res})[0], "date": time.strftime("%Y-%m-%d"),
           "model_ids": sorted({r.get("model_id", "unknown") for r in res}), "cli_version": man.get("cli_version", "unknown"),
           "tasks": {t: {"rate": round(mean(v), 3), "n": len(v)} for t, v in sorted(tasks.items())}}
    with open(os.path.join(a.bench, "calibration.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    hard = [t for t, v in doc["tasks"].items() if v["rate"] <= 0.7]
    print("calibrated %d tasks on arm %s (%s): %d hard (rate <= 0.7), %d saturated (>= 0.9)"
          % (len(tasks), a.arm, doc["model"], len(hard), sum(1 for v in doc["tasks"].values() if v["rate"] >= 0.9)))
    return 0


def cmd_select(a):
    for t in select_tasks(a.bench, a.tasks):
        print(t)
    return 0


def load(bench):
    concepts = read_json(concepts_path(bench))
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
    owns = os.path.isfile(os.path.join(a.bench, "concepts.json"))  # coverage is forge's bench's rule, not a project's
    thin = {c: n for c, n in per_concept.items() if owns and n < a.min_per_concept}
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
    r.add_argument("--out", help="default: $XDG_DATA_HOME/forge/skill-bench/runs/<timestamp>")
    r.add_argument("--keep-work", action="store_true", help="keep each run's working copy (default: dropped once scored, to save space)")
    r.add_argument("--model", default="sonnet")
    r.add_argument("--workers", type=int, default=3)
    r.add_argument("--timeout", type=int, default=900)
    r.add_argument("--oracle-timeout", type=int, default=120)
    r.add_argument("--claude-bin", default="claude")
    r.add_argument("--sandbox", choices=("auto", "bwrap", "none"), default="auto")
    r.add_argument("--force-skill", action="store_true", help="tell the agent to use the arm's first skill (default: let it decide)")
    r.add_argument("--seed", type=int, default=1)
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("calibrate")
    c.add_argument("--bench", default=DEFAULT_BENCH)
    c.add_argument("--out", help="default: the latest run under the data dir")
    c.add_argument("--arm", default="none")
    c.set_defaults(fn=cmd_calibrate)
    sl = sub.add_parser("select")
    sl.add_argument("--bench", default=DEFAULT_BENCH)
    sl.add_argument("--tasks", default="all")
    sl.set_defaults(fn=cmd_select)
    q = sub.add_parser("report")
    q.add_argument("--out", help="default: the latest run under the data dir")
    q.add_argument("--base", default="none")
    q.add_argument("--bootstrap", type=int, default=10000)
    q.add_argument("--allow-mixed-models", action="store_true", help="compare arms that ran on different models (default: refused)")
    q.set_defaults(fn=cmd_report, bench=None)
    a = p.parse_args()
    if a.bench is not None:
        a.bench = os.path.abspath(a.bench)
    if a.bench is not None and not os.path.isfile(concepts_path(a.bench)):
        sys.exit("! %s has no concepts.json" % a.bench)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
