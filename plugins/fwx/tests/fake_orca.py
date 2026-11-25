#!/usr/bin/env python3
"""A fake `orca` for tests/test_wave_run.py: it records every call with the Orca variables it carried, answers the calls `fwx wave run`
makes in the JSON envelope Orca prints (`{"ok": true, "result": {...}}`), refuses what Orca was seen to refuse (the creation flags beside
`--worktree`, `worker-release` of a dispatch that is not settled: `dispatch_inactive`), and plays the worker at `worker-start`.

State is in $FAKE_ORCA_DIR: `behave.json` (what the test wants), `state.json` (repos, runs, dispatches), `calls.jsonl` (one row per call).
`behave.json`: {"units": {unit: mode | [mode per launch] | {mode, files, findings}}, "files": {unit: {path: text}}, "criteria": [ids],
"registered": [paths]}. A mode is `ok` (the worker commits, writes its report and `worker_done`), `garbled` (a reply that names no report),
`bad-outside` (a report whose `outside` item is malformed), `idle` (done, but it never settles: state ready, activity idle), `wait` (an
agent waiting on a prompt), `hang` (never ends), `later` (running until the test creates `go-<unit>`), `fail` (Orca says failed),
`failed-report` and `question` (the executor's report says so) and `showfail` (worker-show fails). `release_fail: [unit]` makes `worker-release` of
that unit's dispatches fail with an error object whose `message` is null. `orchestration run-create`, `worker-start` and `send` with no `--from` (and none of the session variables
in its environment) fails with Orca 1.4.273's `no_active_sender_terminal`; `terminal create|show|close` keep `state.json["terminals"]`. `discover_after: N` makes Orca discover a worktree only after N `worktree show` calls on its path (the first N answer `selector_not_found`, as Orca 1.4.273 does for a worktree made with git that it has not
found yet), and `start_not_found: M` makes the first M `worker-start`s on a worktree answer `selector_not_found` even when `show` knows it; with `discover_after` set, `worker-start` on a worktree that is not yet discovered answers `selector_not_found`
too (neither set: every worktree is known at once, as before).
Orchestrator steering (Orca 1.4.273, live probe): a worker's `worker_done` and a worker's `question` land in the run's inbox (`state.json["inbox"]`); `orchestration check
--terminal T --run R --peek [--types a,b]` lists the unread ones of that run (only those types when `--types` is given) and never marks them read, `--peek` with `--all` is refused, a
check with neither consumes; `send --type escalation` from a run's terminal is refused (`sender_not_assignee`), `--type status` to `orca_session_id:<uuid>` lands in `state.json["chat"]`
(`behave["status_fail"]` refuses it); mode `ask` (`{mode: ask, question}`) posts a `question` and parks the worker (ready, idle, not waiting on a person), and a `send` to its `dispatch:<id>`
wakes it: it works (running, activity working, for one `worker-show`), commits, posts its `worker_done` and settles. `merge: <unit>` makes a resolver merge that unit's branch. The worker reads its role, run and unit from the marker `fwx-worker.json` in its git dir, as the real one does.
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
    """Atomic: a reader (the test, or another call of the fake) sees the old file or the new one, never a half-written one."""
    path = os.path.join(DIR, name)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


STATE = {}  # the state of the call in progress: `say` saves it before it prints, for every command


def say(result=None, rc=0, error=None):
    if STATE:
        save("state.json", STATE)
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


def play(behave, wt, marker, launch, force=None):
    """What the worker does and says: (reply, mode, spec)."""
    role, run, unit = marker["role"], marker["run"], marker["unit"]
    spec = mode_of(behave, unit, launch)
    mode = force or spec.get("mode", "ok")
    folder = scratch(wt, run, unit)
    report = os.path.join(folder, "report.json")
    if mode == "garbled":
        return "I could not finish this one", mode, spec
    if mode in ("hang", "wait", "wait-unknown", "wait-absent", "showfail", "ask"):
        return "", mode, spec
    if role == "executor" and mode in ("failed-report", "question", "bad-outside"):  # no commit: the report is all there is
        rep = {"failed-report": {"status": "failed", "reason": "could not do it"}, "question": {"status": "question", "question": "which one do you mean?"},
               "bad-outside": {"status": "done", "branch": git(wt, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip(), "outside": [{"where": "x"}]}}[mode]
        with open(report, "w", encoding="utf-8") as f:
            json.dump(rep, f)
        return "%s %s commits=0" % (rep["status"], report), mode, spec
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
        return "done %s commits=1" % report, mode, spec
    findings = spec.get("findings") or []
    rep = {"looked_at": ["a"], "findings": findings, "outside": [], "criteria": [{"id": c, "met": "yes", "evidence": "seen"} for c in behave.get("criteria", [])]}
    with open(report, "w", encoding="utf-8") as f:
        json.dump(rep, f)
    return "reviewed %s looked_at=1 findings=%d criteria_no=0 criteria_unproven=0" % (report, len(findings)), mode, spec


def shape(d):
    mode, state = d["mode"], d["state"]
    if state in ("stopped",):
        return {"state": "stopped", "stage": "process_stopped"}
    if mode in ("ok", "bad-outside", "garbled", "failed-report", "question"):
        return {"state": "succeeded", "stage": "settled"}
    if mode == "fail":
        return {"state": "failed", "stage": "settled"}
    if mode == "ask":  # the worker asked and ended its turn: ready and idle, not waiting on a person
        return {"state": "ready", "stage": "input_accepted", "activity": "idle", "waitingOnHuman": False}
    if mode == "woken":  # answered: working for one show, then done
        return {"state": "succeeded", "stage": "settled"} if d.get("shows", 0) >= 2 else {"state": "running", "stage": "working", "activity": "working"}
    if mode == "later":
        return {"state": "succeeded", "stage": "settled"} if os.path.exists(os.path.join(DIR, "go-" + d["unit"])) else {"state": "running", "stage": "working"}
    if mode == "idle":
        return {"state": "ready", "stage": "idle", "activity": "idle", "waitingOnHuman": False}
    if mode == "wait":
        return {"state": "ready", "stage": "input_accepted", "activity": "idle", "waitingOnHuman": True}
    if mode == "wait-unknown":
        return {"state": "ready", "stage": "input_accepted", "activity": "idle", "waitingOnHuman": "unknown"}
    if mode == "wait-absent":
        return {"state": "ready", "stage": "input_accepted", "activity": "idle"}
    return {"state": "running", "stage": "working"}


def post(state, **m):
    """A message in the inbox of Orca run `m["run"]`."""
    state["msgs"] = state.get("msgs", 0) + 1
    state.setdefault("inbox", []).append(dict({"id": "msg_%d" % state["msgs"], "handled": False, "body": "", "subject": "", "from": "", "to": "", "payload": {}}, **m))


def shown(m):
    return {k: m[k] for k in ("id", "type", "from", "to", "subject", "handled", "body", "payload")}


def main(argv):
    state = STATE
    state.update(load("state.json", {"repos": [], "runs": 0, "n": 0, "dispatches": {}, "launches": {}}))
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
    if argv[:2] == ["worktree", "show"]:
        wt = (flag(argv, "--worktree") or "")[len("path:"):]
        seen = state.setdefault("shows", {})
        seen[wt] = seen.get(wt, 0) + 1
        if seen[wt] <= behave.get("discover_after", 0):
            done_log(refused="selector_not_found", show=wt)
            say(rc=1, error={"code": "selector_not_found", "message": "No workspace matches --worktree path:%s." % wt})
        done_log(show=wt)
        say({"worktree": {"path": wt}})
    if argv[:2] == ["terminal", "create"]:
        state["n_terms"] = state.get("n_terms", 0) + 1
        handle = "term_%d" % state["n_terms"]
        state.setdefault("terminals", {})[handle] = {"title": flag(argv, "--title"), "worktree": flag(argv, "--worktree"), "open": True}
        done_log(terminal=handle)
        say({"terminal": {"handle": handle, "title": flag(argv, "--title"), "worktree": flag(argv, "--worktree")}})
    if argv[:2] == ["terminal", "show"] and flag(argv, "--terminal") in state.get("terminals", {}) and not state["terminals"][flag(argv, "--terminal")]["open"]:
        term = state["terminals"][flag(argv, "--terminal")]  # a closed handle is not an error in Orca 1.4.273: ok, with `orphaned: true`
        done_log(terminal=flag(argv, "--terminal"), orphaned=True)
        say({"terminal": {"handle": flag(argv, "--terminal"), "title": term["title"], "worktreePath": term["worktree"], "orphaned": True}})
    if argv[:2] in (["terminal", "show"], ["terminal", "close"]):
        handle = flag(argv, "--terminal")
        term = state.setdefault("terminals", {}).get(handle)
        if term is None or not term["open"]:
            done_log(terminal=handle, refused="terminal_not_found")
            say(rc=1, error={"code": "terminal_not_found", "message": "no live terminal %s" % handle})
        if argv[1] == "close":
            term["open"] = False
        done_log(terminal=handle)
        say({"terminal": {"handle": handle, "title": term["title"]}} if argv[1] == "show" else {"closed": True, "handle": handle})
    def need_sender():
        """`run-create`, `worker-start` and `send` take a sender terminal: `--from`, or the session variables / ORCA_TERMINAL_HANDLE of a live Orca terminal."""
        sender = flag(argv, "--from")
        if sender is None and not any(os.environ.get(k) for k in SESSION_VARS + ("ORCA_TERMINAL_HANDLE",)):  # as Orca 1.4.273 answers
            done_log(refused="no_active_sender_terminal")
            say(rc=1, error={"code": "no_active_sender_terminal", "message": "Could not determine the calling terminal for this orchestration command. "
                             "Pass --from with your own terminal's handle ... or run the command inside a live Orca terminal with ORCA_TERMINAL_HANDLE set."})
        if sender is not None and not state.setdefault("terminals", {}).get(sender, {}).get("open"):
            done_log(refused="sender_not_open")
            say(rc=1, error={"code": "terminal_not_found", "message": "sender %s is not a live terminal" % sender})
        return sender

    if argv[:2] == ["orchestration", "send"]:
        sender = need_sender()
        to, typ, subject = flag(argv, "--to"), flag(argv, "--type"), flag(argv, "--subject")
        body = flag(argv, "--body")
        if body is None and flag(argv, "--body-file"):
            with open(flag(argv, "--body-file"), encoding="utf-8") as f:
                body = f.read()
        sent = {"to": to, "type": typ, "subject": subject, "body": body}
        if typ == "escalation" and sender is not None:  # Orca 1.4.273: only the worker a task was dispatched to may escalate; a run's terminal is nobody's assignee
            done_log(sender=sender, send=sent, refused="sender_not_assignee")
            say(rc=1, error={"code": "sender_not_assignee", "message": "only the assignee of a dispatched task may send an escalation"})
        if (to or "").startswith("orca_session_id:"):
            if behave.get("status_fail"):
                done_log(sender=sender, send=sent, refused="status_fail")
                say(rc=1, error={"code": "unavailable", "message": "the chat of %s cannot be reached" % to})
            state.setdefault("chat", []).append(dict(sent, **{"from": sender}))
        d = state["dispatches"].get(to[len("dispatch:"):]) if (to or "").startswith("dispatch:") else None
        if d and d["mode"] == "ask":  # a worker parked on `ask` is woken by mail to its dispatch: it carries on and finishes
            marker = load_abs(os.path.join(git(d["worktree"], "rev-parse", "--absolute-git-dir").stdout.strip(), "fwx-worker.json"))
            reply, _, _ = play(behave, d["worktree"], marker, d["launch"], "ok")
            d.update(reply=reply, mode="woken", answered=body, shows=0)
            post(state, run=d["orca_run"], type="worker_done", subject="done " + d["unit"], to="run:" + str(d["orca_run"]), payload={"dispatchId": to[len("dispatch:"):]})
        done_log(sender=sender, send=sent)
        say({"sent": True})
    if argv[:2] == ["orchestration", "check"]:
        term = flag(argv, "--terminal")
        if "--peek" in argv and "--all" in argv:
            done_log(refused="invalid_argument")
            say(rc=1, error={"code": "invalid_argument", "message": "--peek and --all cannot be combined"})
        if term is not None and not state.setdefault("terminals", {}).get(term, {}).get("open"):
            done_log(refused="terminal_not_found")
            say(rc=1, error={"code": "terminal_not_found", "message": "no live terminal %s" % term})
        types = flag(argv, "--types")
        rows = [m for m in state.get("inbox", []) if m["run"] == flag(argv, "--run") and (("--all" in argv) or not m["handled"]) and (not types or m["type"] in types.split(","))]
        if "--peek" not in argv and "--all" not in argv:
            for m in rows:
                m["handled"] = True
        done_log(check={"peek": "--peek" in argv, "types": types, "ids": [m["id"] for m in rows]})
        say({"messages": [shown(m) for m in rows]})
    if argv[:2] == ["orchestration", "run-create"]:
        sender = need_sender()
        state["runs"] += 1
        done_log(sender=sender)
        say({"run": {"id": "run_%d" % state["runs"], "objective": flag(argv, "--objective")}})
    if argv[:2] == ["orchestration", "worker-start"]:
        sender = need_sender()
        wt = (flag(argv, "--worktree") or "")
        bad = [c for c in CREATION if c in argv]
        if not wt.startswith("path:") or bad:
            done_log(refused="creation flags beside --worktree: %s" % bad)
            say(rc=1, error={"code": "invalid_argument", "message": "creation flags %s cannot go with --worktree path:" % bad})
        wt = wt[len("path:"):]
        tries = state.setdefault("start_tries", {})
        tries[wt] = tries.get(wt, 0) + 1
        late = behave.get("discover_after", 0)
        if (late and state.get("shows", {}).get(wt, 0) <= late) or tries[wt] <= behave.get("start_not_found", 0):
            done_log(refused="selector_not_found", start_try=wt)
            say(rc=1, error={"code": "selector_not_found", "message": "No workspace matches --worktree path:%s. Nothing was started; no effects were applied." % wt})
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
        try:
            fmode = os.stat(os.path.join(wt, ".claude", "settings.local.json")).st_mode & 0o777
        except OSError:
            fmode = None
        state["n"] += 1
        did = "ctx_%d" % state["n"]
        unit = (marker or {}).get("unit", "?")
        key = "%s/%s" % ((marker or {}).get("run"), unit)
        state["launches"][key] = launch = state["launches"].get(key, 0) + 1
        reply, mode, pspec = play(behave, wt, marker, launch) if marker else ("", "hang", {})
        state["dispatches"][did] = {"unit": unit, "mode": mode, "state": "running", "reply": reply, "worktree": wt, "released": False,
                                    "pages": pspec.get("pages", 1), "trailing": pspec.get("trailing"), "launch": launch, "orca_run": flag(argv, "--run")}
        if mode == "ask":
            post(state, run=flag(argv, "--run"), type="question", subject="Question", body=pspec.get("question", "which one?"), to="run:" + str(flag(argv, "--run")),
                 payload={"dispatchId": did})
        elif mode in ("ok", "bad-outside", "failed-report", "question"):
            post(state, run=flag(argv, "--run"), type="worker_done", subject="done " + unit, to="run:" + str(flag(argv, "--run")), payload={"dispatchId": did})
        done_log(start={"dispatch": did, "unit": unit, "role": (marker or {}).get("role"), "launch": launch, "marker": marker, "spec": spec, "settings": settings, "settings_mode": fmode,
                        "status": git(wt, "status", "--porcelain").stdout, "head": git(wt, "rev-parse", "HEAD").stdout.strip(),
                        "open_before": len(open_now), "worktree": wt, "agent": flag(argv, "--agent"), "model": flag(argv, "--model"), "run": flag(argv, "--run"), "sender": sender,
                        "files_at_start": sorted(os.listdir(wt))})
        say({"dispatchId": did, "taskId": "task_%d" % state["n"], "runId": flag(argv, "--run"), "state": "running"})
    if argv[:2] == ["orchestration", "worker-show"]:
        d = state["dispatches"].get(flag(argv, "--dispatch"))
        done_log(dispatch=flag(argv, "--dispatch"))
        if d is None or d["mode"] == "showfail":
            say(rc=1, error={"code": "unavailable", "message": "worker-show failed"})
        d["shows"] = d.get("shows", 0) + 1
        say(dict(shape(d), dispatchId=flag(argv, "--dispatch"), liveness="alive"))
    if argv[:2] == ["orchestration", "worker-read"]:
        d = state["dispatches"].get(flag(argv, "--dispatch"))
        cur = flag(argv, "--cursor")
        done_log(dispatch=flag(argv, "--dispatch"), cursor=cur)
        user = {"role": "user", "blocks": [{"type": "text", "text": "the spec"}]}
        asst = [{"role": "assistant", "blocks": [{"type": "text", "text": "working\n" + (d or {}).get("reply", "")}]}]
        if (d or {}).get("trailing"):
            asst.append({"role": "assistant", "blocks": [{"type": "text", "text": d["trailing"]}]})
        if cur == "cur-end":
            msgs, nxt, limited = [], "cur-end", False
        elif (d or {}).get("pages", 1) > 1 and not cur:
            msgs, nxt, limited = [user], "cur-1", True
        elif (d or {}).get("pages", 1) > 1 and cur == "cur-1":
            msgs, nxt, limited = asst, "cur-end", True
        else:
            msgs, nxt, limited = [user] + asst, "cur-end", False
        say({"dispatchId": flag(argv, "--dispatch"), "source": "transcript",
             "transcript": {"messages": msgs, "nextCursor": nxt, "limited": limited, "returnedMessageCount": len(msgs)},
             "cursor": nxt})
    if argv[:2] == ["orchestration", "worker-stop"]:
        d = state["dispatches"].get(flag(argv, "--dispatch"))
        if d and d["state"] != "stopped" and shape(d)["state"] not in ("succeeded", "failed"):
            d["state"] = "stopped"
        done_log(dispatch=flag(argv, "--dispatch"))
        say({"dispatchId": flag(argv, "--dispatch"), "processAction": "closed_agent_terminal"})
    if argv[:2] == ["orchestration", "worker-release"]:
        d = state["dispatches"].get(flag(argv, "--dispatch"))
        if d and d["unit"] in behave.get("release_fail", []):  # an error object whose `message` is null, as Orca was not seen to send but may
            done_log(dispatch=flag(argv, "--dispatch"), refused="release_fail")
            say(rc=1, error={"code": "internal", "message": None})
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
