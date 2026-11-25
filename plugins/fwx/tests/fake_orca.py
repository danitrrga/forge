#!/usr/bin/env python3
"""A fake `orca` for tests/test_wave_run.py: it records every call with the Orca variables it carried, answers the calls `fwx wave run`
makes in the JSON envelope Orca prints (`{"ok": true, "result": {...}}`), refuses what Orca was seen to refuse (the creation flags beside
`--worktree`, `worker-release` of a dispatch that is not settled: `dispatch_inactive`), and plays the worker at `worker-start`.

State is in $FAKE_ORCA_DIR: `behave.json` (what the test wants), `state.json` (repos, runs, dispatches), `calls.jsonl` (one row per call).
`behave.json`: {"units": {unit: mode | [mode per launch] | {mode, files, findings}}, "files": {unit: {path: text}}, "criteria": [ids],
"registered": [paths]}. A mode is `ok` (the worker commits, writes its report and `worker_done`), `garbled` (a reply that names no report),
`bad-outside` (a report whose `outside` item is malformed), `idle` (done, but it never settles: state ready, activity idle), `wait` (an
agent waiting on a prompt), `hang` (never ends), `later` (running until the test creates `go-<unit>`), `fail` (Orca says failed),
`failed-report` and `question` (the executor's report says so) and `showfail` (worker-show fails). `merge: <unit>` makes a resolver merge that unit's branch. The worker reads its role, run and unit from the marker `fwx-worker.json` in its git dir, as the real one does.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DIR = os.environ["FAKE_ORCA_DIR"]
CREATION = ("--name", "--repo", "--base-branch", "--display-name", "--comment", "--setup")
SESSION_VARS = ("ORCA_AGENT_SESSION_ID", "ORCA_AGENT_SESSION_SPAWN_TOKEN", "ORCA_STRUCTURED_SESSION")
GIT = ["git", "-c", "user.email=w@w", "-c", "user.name=w", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def load(name, default):
    try:
        with open(os.path.join(DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, data):
    with open(os.path.join(DIR, name), "w", encoding="utf-8") as f:
        json.dump(data, f)


def say(result=None, rc=0, error=None):
    print(json.dumps({"ok": error is None, "result": result} if error is None else {"ok": False, "error": error}))
    sys.exit(rc)


def git(cwd, *args):
    return subprocess.run(GIT + ["-C", cwd] + list(args), capture_output=True, text=True)


def flag(argv, name):
    return argv[argv.index(name) + 1] if name in argv else None


def mode_of(behave, unit, launch):
    m = (behave.get("units") or {}).get(unit, "ok")
    if isinstance(m, list):
        m = m[min(launch - 1, len(m) - 1)]
    return m if isinstance(m, dict) else {"mode": m}


def scratch(wt, run, unit):
    folder = os.path.join(wt, ".fwx-agent", run, unit)
    os.makedirs(os.path.join(folder, "tmp"), exist_ok=True)
    with open(os.path.join(wt, ".fwx-agent", ".gitignore"), "w", encoding="utf-8") as f:
        f.write("*\n")
    return folder


def commit(wt, files, message, trailers):
    for rel, text in files.items():
        p = os.path.join(wt, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if text is None:
            git(wt, "rm", "-q", "-f", rel)
            continue
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", message + "\n\n" + "\n".join(trailers))


def play(behave, wt, marker, launch):
    """What the worker does and says: (reply, mode)."""
    role, run, unit = marker["role"], marker["run"], marker["unit"]
    spec = mode_of(behave, unit, launch)
    mode = spec["mode"]
    folder = scratch(wt, run, unit)
    report = os.path.join(folder, "report.json")
    if mode == "garbled":
        return "I could not finish this one", mode
    if mode in ("hang", "wait", "showfail"):
        return "", mode
    if role == "executor" and mode in ("failed-report", "question", "bad-outside"):  # no commit: the report is all there is
        rep = {"failed-report": {"status": "failed", "reason": "could not do it"}, "question": {"status": "question", "question": "which one do you mean?"},
               "bad-outside": {"status": "done", "branch": git(wt, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip(), "outside": [{"where": "x"}]}}[mode]
        with open(report, "w", encoding="utf-8") as f:
            json.dump(rep, f)
        return "%s %s commits=0" % (rep["status"], report), mode
    if role == "executor":
        branch = git(wt, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
        files = spec.get("files") or (behave.get("files") or {}).get(unit) or {"work/%s.txt" % unit: "x\n"}
        part = run.rsplit("-", 2)[0]
        findings = spec.get("findings") or []
        if spec.get("merge"):  # a resolver: merges the branch that conflicted, taking its side, and commits with the run's trailer
            git(wt, "merge", "--no-ff", "-q", "-X", "theirs", "-m", "resolve", "worktree-%s-%s" % (run, spec["merge"]))
            git(wt, "commit", "--amend", "-q", "-m", "resolve\n\nFwx-Run: " + run)
        elif findings:
            for i, f in enumerate(findings):
                commit(wt, {k: "%s%s\n" % (v, f) for k, v in files.items()}, "fix " + f, ["Fwx-Finding: " + f, "Fwx-Run: " + run])
        else:
            trailers = ["Fwx-Run: " + run] + ([] if unit.startswith(("fix", "resolve")) else ["Fwx-Task: %s/%s" % (part, unit)])
            commit(wt, files, "work " + unit, trailers)
        rep = {"status": "done", "branch": branch, "outside": [{"where": "x"}] if mode == "bad-outside" else []}
        with open(report, "w", encoding="utf-8") as f:
            json.dump(rep, f)
        return "done %s commits=1" % report, mode
    rep = {"looked_at": ["a"], "findings": [], "outside": [], "criteria": [{"id": c, "met": "yes", "evidence": "seen"} for c in behave.get("criteria", [])]}
    with open(report, "w", encoding="utf-8") as f:
        json.dump(rep, f)
    return "reviewed %s looked_at=1 findings=0 criteria_no=0 criteria_unproven=0" % report, mode


def shape(d):
    mode, state = d["mode"], d["state"]
    if state in ("stopped",):
        return {"state": "stopped", "stage": "process_stopped"}
    if mode in ("ok", "bad-outside", "garbled", "failed-report", "question"):
        return {"state": "succeeded", "stage": "settled"}
    if mode == "fail":
        return {"state": "failed", "stage": "settled"}
    if mode == "later":
        return {"state": "succeeded", "stage": "settled"} if os.path.exists(os.path.join(DIR, "go-" + d["unit"])) else {"state": "running", "stage": "working"}
    if mode == "idle":
        return {"state": "ready", "stage": "idle", "activity": "idle"}
    if mode == "wait":
        return {"state": "running", "stage": "working", "observation": {"agentWait": {"kind": "prompt", "evidence": "hook"}}}
    return {"state": "running", "stage": "working"}


def main(argv):
    state = load("state.json", {"repos": [], "runs": 0, "n": 0, "dispatches": {}, "launches": {}})
    behave = load("behave.json", {})
    env = {k: (k in os.environ) for k in SESSION_VARS}
    log = {"argv": argv, "env": env, "t": time.time(), "cwd": os.getcwd()}
    open_now = [d for d in state["dispatches"].values() if not d.get("released")]
    cmd = " ".join(argv[:3]) if argv[:1] == ["orchestration"] else " ".join(argv[:2])

    def done_log(**kw):
        log.update(kw)
        with open(os.path.join(DIR, "calls.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(log) + "\n")
        save("state.json", state)

    if argv[:2] == ["repo", "list"]:
        done_log()
        say({"repos": [{"id": "r%d" % i, "path": p} for i, p in enumerate(state["repos"] + behave.get("registered", []))]})
    if argv[:2] == ["repo", "add"]:
        state["repos"].append(os.path.realpath(flag(argv, "--path")))
        done_log()
        say({"repo": {"path": flag(argv, "--path")}})
    if argv[:2] == ["orchestration", "run-create"]:
        state["runs"] += 1
        done_log()
        say({"run": {"id": "run_%d" % state["runs"], "objective": flag(argv, "--objective")}})
    if argv[:2] == ["orchestration", "worker-start"]:
        wt = (flag(argv, "--worktree") or "")
        bad = [c for c in CREATION if c in argv]
        if not wt.startswith("path:") or bad:
            done_log(refused="creation flags beside --worktree: %s" % bad)
            say(rc=1, error={"code": "invalid_argument", "message": "creation flags %s cannot go with --worktree path:" % bad})
        wt = wt[len("path:"):]
        marker_path = os.path.join(git(wt, "rev-parse", "--absolute-git-dir").stdout.strip(), "fwx-worker.json")
        marker = load_abs(marker_path)
        spec_file = flag(argv, "--spec-file")
        try:
            with open(spec_file, encoding="utf-8") as f:
                spec = f.read()
        except (OSError, TypeError):
            spec = None
        try:
            with open(os.path.join(wt, ".claude", "settings.local.json"), encoding="utf-8") as f:
                settings = json.load(f)
        except (OSError, ValueError):
            settings = None
        state["n"] += 1
        did = "ctx_%d" % state["n"]
        unit = (marker or {}).get("unit", "?")
        key = "%s/%s" % ((marker or {}).get("run"), unit)
        state["launches"][key] = launch = state["launches"].get(key, 0) + 1
        reply, mode = play(behave, wt, marker, launch) if marker else ("", "hang")
        state["dispatches"][did] = {"unit": unit, "mode": mode, "state": "running", "reply": reply, "worktree": wt, "released": False}
        done_log(start={"dispatch": did, "unit": unit, "role": (marker or {}).get("role"), "launch": launch, "marker": marker, "spec": spec, "settings": settings,
                        "status": git(wt, "status", "--porcelain").stdout, "head": git(wt, "rev-parse", "HEAD").stdout.strip(),
                        "open_before": len(open_now), "worktree": wt, "agent": flag(argv, "--agent"), "model": flag(argv, "--model"), "run": flag(argv, "--run"),
                        "files_at_start": sorted(os.listdir(wt))})
        say({"dispatchId": did, "taskId": "task_%d" % state["n"], "runId": flag(argv, "--run"), "state": "running"})
    if argv[:2] == ["orchestration", "worker-show"]:
        d = state["dispatches"].get(flag(argv, "--dispatch"))
        done_log(dispatch=flag(argv, "--dispatch"))
        if d is None or d["mode"] == "showfail":
            say(rc=1, error={"code": "unavailable", "message": "worker-show failed"})
        say(dict(shape(d), dispatchId=flag(argv, "--dispatch"), liveness="alive"))
    if argv[:2] == ["orchestration", "worker-read"]:
        d = state["dispatches"].get(flag(argv, "--dispatch"))
        done_log(dispatch=flag(argv, "--dispatch"))
        msgs = [{"role": "user", "blocks": [{"type": "text", "text": "the spec"}]},
                {"role": "assistant", "blocks": [{"type": "text", "text": "working\n" + (d or {}).get("reply", "")}]}]
        say({"dispatchId": flag(argv, "--dispatch"), "source": "transcript", "transcript": {"messages": msgs}})
    if argv[:2] == ["orchestration", "worker-stop"]:
        d = state["dispatches"].get(flag(argv, "--dispatch"))
        if d and d["state"] != "stopped" and shape(d)["state"] not in ("succeeded", "failed"):
            d["state"] = "stopped"
        done_log(dispatch=flag(argv, "--dispatch"))
        say({"dispatchId": flag(argv, "--dispatch"), "processAction": "closed_agent_terminal"})
    if argv[:2] == ["orchestration", "worker-release"]:
        d = state["dispatches"].get(flag(argv, "--dispatch"))
        if d is None or shape(d)["state"] not in ("succeeded", "failed", "stopped"):
            done_log(dispatch=flag(argv, "--dispatch"), refused="dispatch_inactive")
            say(rc=1, error={"code": "dispatch_inactive", "message": "only a settled worker can release"})
        d["released"] = True
        done_log(dispatch=flag(argv, "--dispatch"))
        say({"dispatchId": flag(argv, "--dispatch"), "released": "released"})
    done_log(unknown=cmd)
    say(rc=2, error={"code": "unknown", "message": "the fake does not know %s" % " ".join(argv)})


def load_abs(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    main(sys.argv[1:])
