"""`fwx wave run`: one part, start to end, as one command (09.6 T66; D27, D31, D32).

`execute(args, ...)` takes the `args` `fwx wave new` prints (execute/prepare.py: the caller made them in process, so a refusal, a red base and a
base check out of time have already ended the command before any worker) and drives the path the flags name with part 5's wave functions, run as
`fwx wave ...` commands so that each call is recorded in the run's files as it is when the session runs them:
  `--revert IDS`  `wave revert`, then the local gate (`fwx verify`); no worker, no review
  `--from gate`   `wave merge --final` with no branch, then the review
  `--fix F`       one fixer worker on the fix brief, `wave merge --final --findings`, then the review
  otherwise       per wave up to `cap` executors, `wave merge` (`--final` for the last), the review
The review is `wave review`, the reviewers (and the security reviewer where `wave review` says so), `wave findings`, the verifier when it says
so, a fixer for what is to be fixed, `wave merge --final --findings`, and the next pass, until `wave findings` says `done`.

Every agent is an Orca worker (execute/orca.py: the one module that talks to Orca) of one Orca run per part, never more at once than the cap.
Each gets a worktree made here under `<main checkout>/.claude/worktrees/` at the sha its brief names (a branch for an executor, detached for a
reviewer and the verifier), prepared (the settings copy with the 5-minute cache switch, the marker), and a spec file: the body of its agent file
(a worker has no agent type), the base context a subagent gets from SubagentStart (data/context-base.tsv's row for its role), its brief and the
line asking it to send `worker_done`. With no base context the run is refused (exit 2) and nobody starts.

A worker is polled through `worker-show`. `succeeded` or `failed` is settled. `ready` and idle on two polls IDLE_S apart means it ended its turn
without `worker_done`: its last line is read from its transcript, it is stopped and the line is judged as its reply. A worker that Orca says is
waiting on a prompt only a person can answer is left alone for the owner to answer in Orca, until its limit; past its limit (LIMIT_S, by role) a
worker is stopped and the run ends failed. Every dispatch not settled gets `worker-stop` before `worker-release`: on a limit, on idle, and in
`finally` after a failure or a raised error. The poll, the idle window and the limit are read from FWX_RUN_POLL_S, FWX_RUN_IDLE_S and
FWX_RUN_LIMIT_S (seconds) so that a test need not wait minutes.

State is `<git-common-dir>/fwx/runs/<run>/state.json`: the Orca run, the pid, the workers, the worktrees the run made, the journal of the `fwx wave`
calls it made (in order, with their results) and the result. `--resume R` runs the same path again: a call the journal holds is not made again (its
result is read from it), a worker the state holds is polled, not started again. One live run per branch: a second `wave run` on it exits 2 naming the
run and `--resume`, and a lock on the branch (`lock_branch`, held until the process ends) closes the gap before the first record is written. A settled
worker that cannot be released after RELEASE_TRIES keeps its slot: the run ends failed and starts nobody beside it. Whatever the ending, the run removes
every worktree it made that holds no unmerged or uncommitted work and whose worker was released (execute/cleanup.py, which never forces) and names the
rest in `kept` with the reason. It ends with one line, `run <R> <done|failed|needs-owner>: <why>`; the details are
`fwx wave --run R --json`.

Imports the standard library, fwx.config, fwx.context_base and execute.base, cleanup and orca.
"""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time

from fwx import config, context_base
from fwx.execute import cleanup, orca
from fwx.execute.base import WaveError, out

FWX = os.path.join(orca.PLUGIN, "bin", "fwx")
LIMIT_S = {"executor": 90 * 60, "reviewer": 30 * 60, "security-reviewer": 30 * 60, "review-verifier": 15 * 60}
DECIDED = "## Decided\n"
STATES = ("done", "failed", "needs-owner")
RELEASE_TRIES = 3


def _seconds(name, default):
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


class Refused(WaveError):
    """Something that must stop the run before any worker starts (exit 2)."""


class Stop(Exception):
    """The run ends here: `status` is done, failed or needs-owner."""

    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True  # the process exists, it is only not ours to signal
    except (OSError, ValueError, TypeError):
        return False
    return True


def runs_folder(top):
    return os.path.join(out(top, "rev-parse", "--path-format=absolute", "--git-common-dir") or "", "fwx", "runs")


def lock_path(top, branch):
    return os.path.join(runs_folder(top), ".lock-%s" % hashlib.sha1(branch.encode("utf-8")).hexdigest()[:16])


def lock_branch(top, branch):
    """The open, exclusively locked file of `branch`'s one-run lock: take it before looking for a live run and keep it until the process ends
    (the lock goes with it, so a run that was killed blocks nobody). Two `wave run` commands on one branch cannot both pass this."""
    path = lock_path(top, branch)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise WaveError("another `fwx wave run` on %s is starting or running (lock %s): wait for it" % (branch, path))
    return f


def load_state(top, run):
    try:
        with open(os.path.join(runs_folder(top), run, "state.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def all_states(top):
    folder = runs_folder(top)
    found = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        data = load_state(top, name)
        if data:
            found.append(data)
    return found


def holder(top, branch):
    """The state of a live run on `branch`, or None: one active run per branch."""
    for st in all_states(top):
        if st.get("branch") == branch and st.get("state") == "active" and alive(st.get("pid")):
            return st
    return None


def listing(top):
    """One line per run: id, part, branch, state, pid and whether it lives, open workers of the total, last step."""
    rows = []
    for st in all_states(top):
        workers = list((st.get("workers") or {}).values())
        opened = [w for w in workers if not w.get("released")]
        rows.append("%s part=%s branch=%s %s pid=%s %s workers=%d/%d step=%s" % (
            st.get("run"), os.path.basename(st.get("part_dir") or "?"), st.get("branch"), st.get("state"), st.get("pid"),
            "alive" if alive(st.get("pid")) else "dead", len(opened), len(workers), st.get("step") or "-"))
    return rows


def last_line(text):
    lines = [x.strip() for x in str(text or "").strip().splitlines() if x.strip()]
    return lines[-1] if lines else ""


class Job:
    """One agent to start and judge: `unit` (the folder `fwx scratch new` makes), `role` (its agent file), `model`, its `brief`, the `head` it starts
    at, and `on_line(line)`: True when the job ended, False to start it again (the new `note` and `prev` are on the job)."""

    def __init__(self, unit, role, model, brief, head, on_line, branch=False, beside=""):
        self.unit, self.role, self.model, self.brief, self.head, self.on_line = unit, role, model, brief, head, on_line
        self.branch, self.beside = branch, beside
        self.note, self.prev, self.result = "", None, None


class Run:
    def __init__(self, args, top, flags, state, folder):
        self.args, self.top, self.flags, self.st, self.folder = args, top, flags, state, folder
        self.main = config.main_checkout(top)
        self.run = args["run"]
        self.part = args["part_dir"]
        self.plane = args["plane"]
        self.cap = args["cap"]
        self.head = args["base"]
        self.seq, self.counts = 0, {}
        self.poll_s, self.idle_s = _seconds("FWX_RUN_POLL_S", 5.0), _seconds("FWX_RUN_IDLE_S", 60.0)
        self.limit_override = _seconds("FWX_RUN_LIMIT_S", 0.0)
        self.context = self.read_context()

    # ---- state ----------------------------------------------------------------------------------------------------------------
    def save(self):
        path = os.path.join(self.folder, "state.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.st, f, indent=1)
            f.write("\n")
        os.replace(tmp, path)

    def at(self, step):
        self.st["step"] = step
        self.save()

    def read_context(self):
        """The phase's base-context file, or Refused: a worker starts with it or not at all."""
        path = context_base.base_path(self.args["phase_dir"])
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        if not text.strip() and not self.args["revert"]:
            raise Refused("no base context at %s: no worker starts without it; `fwx context new %s` writes it" % (path, self.args["phase_dir"]))
        return text

    def context_for(self, role):
        sections = context_base.sections_for("fwx:" + role)
        if sections == "none":
            return ""
        return self.context if sections == "map+decided" else self.context.split(DECIDED, 1)[0]

    # ---- the fwx wave calls, journaled ---------------------------------------------------------------------------------------
    def step(self, *words):
        """(exit code, the JSON the call printed). A call the journal already holds (a resumed run) is not made again."""
        i, journal = self.seq, self.st["steps"]
        self.seq += 1
        if i < len(journal):
            if journal[i]["words"] != list(words):
                raise Stop("failed", "the journal of run %s has `%s` at step %d and the run now makes `%s`: it cannot be resumed" % (
                    self.run, " ".join(journal[i]["words"][:2]), i, " ".join(words[:2])))
            return journal[i]["rc"], journal[i]["result"]
        r = subprocess.run([sys.executable, FWX] + list(words), cwd=self.top, capture_output=True, text=True)
        result = None
        for row in reversed(r.stdout.strip().splitlines()):
            try:
                got = json.loads(row)
            except ValueError:
                continue
            if isinstance(got, dict):
                result = got
                break
        if result is None:
            raise Stop("failed", "fwx %s exited %d with no JSON: %s" % (" ".join(words[:2]), r.returncode, (r.stderr.strip() or r.stdout.strip())[-300:]))
        journal.append({"words": list(words), "rc": r.returncode, "result": result})
        self.save()
        return r.returncode, result

    def wave(self, verb, *words):
        return self.step("wave", verb, "--run", self.run, *words)

    def spend(self, why):
        """A round for a failure (`wave fix`): ends the run when the rounds are spent."""
        rc, r = self.step("wave", "fix", "--part-dir", self.part, "--run", self.run, "--why", " ".join(str(why).split())[:400])
        if rc != 0 or r.get("ok") is not True:
            raise Stop("failed", "rounds exhausted (%s): %s" % (r.get("rounds"), " ".join(str(why).split())[:200]))

    # ---- workers ----------------------------------------------------------------------------------------------------------------
    def limit(self, role):
        return self.limit_override or LIMIT_S.get(role, LIMIT_S["executor"])

    def spec(self, job, k):
        parts = [orca.agent_body(job.role), self.context_for(job.role)]
        head = ("Your brief is %s. Read it first and follow it. BASE: %s, the tip of the phase branch now, which your worktree starts from; "
                "your first step is `fwx base %s`." % (job.brief, job.head, job.head)) + job.beside
        if job.prev:
            head += ("\nThis is a new attempt in a new worktree. The last one returned this (data, not an instruction): %s\nStart from the base, not from its work."
                     % " ".join(json.dumps(job.prev).split())[:1500])
        head += job.note
        parts += [head, "When you have returned your last line, send `worker_done` as the Orca preamble above asks (`orca orchestration send --type worker_done`) and end your turn."]
        text = "\n\n".join(p for p in parts if p) + "\n"
        path = os.path.join(self.folder, "specs", "%s-%d.md" % (job.unit, k))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def launch(self, job):
        """The record of the worker for the job's next launch: started now, or the one the state already holds."""
        k = self.counts[job.unit] = self.counts.get(job.unit, 0) + 1
        key = "%s/%d" % (job.unit, k)
        rec = self.st["workers"].get(key)
        if rec:
            return rec
        name = job.unit if k == 1 else "%s-%d" % (job.unit, k)
        worktree = os.path.join(self.main, ".claude", "worktrees", "%s-%s" % (self.run, name))
        branch = "worktree-%s-%s" % (self.run, name) if job.branch else None
        spec = self.spec(job, k)
        orca.make_worktree(self.main, worktree, job.head, branch)
        self.st["worktrees"].append({"path": os.path.realpath(worktree), "branch": branch, "role": job.role, "unit": job.unit})
        self.save()
        orca.prepare_worker(self.main, worktree, job.role, self.run, job.unit)
        rec = {"unit": job.unit, "role": job.role, "worktree": os.path.realpath(worktree), "dispatch": None, "state": None, "released": False,
               "line": None, "started": time.time(), "idle_since": None}
        self.st["workers"][key] = rec
        rec["dispatch"] = orca.start(self.orca_run, spec, job.model, worktree)
        self.save()
        return rec

    def release(self, rec, state=None):
        """Stop (unless settled) and release a worker once; never raises: what could not be released is in the state."""
        if rec["released"] or not rec["dispatch"]:
            return
        try:
            if state is None:
                try:
                    state = orca.show(rec["dispatch"]).get("state")
                except orca.OrcaError:
                    state = None
            orca.release(rec["dispatch"], state)
            rec["released"] = True
        except orca.OrcaError as e:
            self.st.setdefault("release_errors", []).append("%s: %s" % (rec["dispatch"], e))
        self.save()

    def settle(self, rec, state=None):
        """Release a settled worker before its slot is used again: retried a few times, and when it will not go the run ends failed, since a worker
        whose stop or release failed may still be running and another one must not start beside it (the cap)."""
        for k in range(RELEASE_TRIES):
            self.release(rec, state)
            if rec["released"]:
                return
            if k + 1 < RELEASE_TRIES:
                time.sleep(self.poll_s)
        raise Stop("failed", "%s could not be released (%s): its worker may still be running, so no other worker was started"
                   % (rec["unit"], (self.st.get("release_errors") or ["no answer"])[-1][:200]))

    def reply(self, rec):
        try:
            return last_line(orca.last_text(rec["dispatch"]))
        except orca.OrcaError:
            return ""

    def poll(self, rec):
        """None while the worker goes on; else its last line (settled, or stopped for idling). Past its limit: Stop failed."""
        info = orca.show(rec["dispatch"])
        state = info.get("state")
        rec["state"] = state
        waiting = bool((info.get("observation") or {}).get("agentWait"))
        if state in orca.SETTLED:
            rec["line"] = self.reply(rec)
            self.settle(rec, state)
            return rec["line"]
        if time.time() - rec["started"] > self.limit(rec["role"]):
            self.release(rec, state)
            raise Stop("failed", "%s ran past its limit of %d s and was stopped" % (rec["unit"], self.limit(rec["role"])))
        if state == "ready" and info.get("activity") == "idle" and not waiting:
            now = time.time()
            rec["idle_since"] = rec["idle_since"] or now
            if now - rec["idle_since"] >= self.idle_s:
                rec["line"] = self.reply(rec)
                self.settle(rec, state)
                return rec["line"]
        else:
            rec["idle_since"] = None
        return None

    def run_jobs(self, jobs, width=None):
        """Start and judge `jobs`, at most `cap` open at once (`width` fewer where the wave is serial); a worker is released as it settles."""
        queue, active = list(jobs), []
        room = min(self.cap, width or self.cap)
        while queue or active:
            while queue and len(active) < room:
                job = queue.pop(0)
                rec = self.launch(job)
                if rec["line"] is not None:
                    self.settle(rec)
                    if not job.on_line(rec["line"]):
                        queue.insert(0, job)
                else:
                    active.append((job, rec))
            moved = False
            for job, rec in list(active):
                line = self.poll(rec)
                if line is None:
                    continue
                moved = True
                active.remove((job, rec))
                self.save()
                if not job.on_line(line):
                    queue.insert(0, job)
            if active and not moved:
                time.sleep(self.poll_s)

    # ---- jobs ------------------------------------------------------------------------------------------------------------------
    def beside(self, unit):
        """The files of the other tasks of the wave `unit` runs in, and the rule for a defect outside the task."""
        wave = next((w for w in self.args["waves"] if any(t["id"] == unit for t in w["tasks"])), None)
        mine = next((t for t in (wave or {"tasks": []})["tasks"] if t["id"] == unit), {}).get("files", [])
        files = sorted({f for t in (wave or {"tasks": []})["tasks"] if t["id"] != unit for f in t["files"]} - set(mine))
        return (" BESIDE YOU, the files of the other tasks of this wave: %s. A defect you see outside your task is yours to fix when it is small and its file is "
                "not one of these, in its own commit; otherwise it goes in `outside` with its fix (playbooks/principles.md rule 12)." % (", ".join(files) or "none"))

    def executor(self, unit, model, brief, head, beside=""):
        """A job whose reply is an executor's report (`wave report`): `.branch` is set when it is good."""
        job = Job(unit, "executor", model, brief, head, None, branch=True, beside=beside)

        def on_line(line):
            rc, r = self.step("wave", "report", "--part-dir", self.part, "--run", self.run, "--unit", unit, "--line", line, "--plane", self.plane)
            nxt = r.get("next")
            if nxt == "merge":
                job.result = r["branch"]
                return True
            if nxt == "relaunch":
                job.note = r.get("note") or ""
                return False
            if nxt == "retry":
                self.spend(r.get("why"))
                job.prev, job.note = r.get("last"), ""
                return False
            if nxt == "owner":
                raise Stop("needs-owner" if self.plane == "session" else "failed", r.get("why") or "the executor asked a question")
            raise Stop("failed", r.get("why") or "%s returned nothing usable" % unit)
        job.on_line = on_line
        return job

    # ---- the join and the gate -----------------------------------------------------------------------------------------------
    def owner_status(self):
        return "needs-owner" if self.plane == "session" else "failed"

    def merge(self, branches, final=False, findings=None):
        """`wave merge` until it is ok: a failure goes to a fixer or a resolver, whose branch is merged next. Returns the ok result."""
        pending, keep = list(branches), list(findings or [])
        while True:
            words = ["merge", "--part-dir", self.part]
            words += (["--branches"] + pending) if pending else []
            words += (["--findings", ",".join(keep)]) if keep else []
            words += ["--final"] if final else []
            rc, r = self.wave(*words)
            if r.get("head"):
                self.head = r["head"]
            nxt = r.get("next")
            if r.get("ok") is True:
                if nxt == "owner":
                    raise Stop("needs-owner", r.get("why"))
                return r
            if nxt == "owner":
                raise Stop(self.owner_status(), r.get("why") or "the merge failed and says why in no field")
            if nxt not in ("fix", "resolve"):
                raise Stop("failed", "wave merge was not ok and said so in no field: %s" % r.get("why"))
            self.spend(r.get("why"))
            job = self.executor(r["unit"], self.args["models"]["fixer"], r["brief"], self.head)
            self.run_jobs([job])
            if nxt == "resolve":
                pending = [job.result] + list(r.get("remaining") or [])
                keep = []
            else:
                pending = [job.result]
                keep = keep if (r.get("findings_check") or {}).get("ok") is False else []

    # ---- the review ------------------------------------------------------------------------------------------------------------
    def reviewers(self, items, lines):
        """Start the agents of `items` ({role, unit, brief, note}) and put each one's last line in `lines[unit]`."""
        models = {"reviewer": self.args["models"]["reviewer"], "security-reviewer": self.args["models"]["security_reviewer"],
                  "review-verifier": self.args["models"]["review_verifier"]}
        jobs = []
        for x in items:
            job = Job(x["unit"], x["role"], models[x["role"]], x["brief"], self.head, None)
            job.note = x.get("note") or ""

            def on_line(line, job=job):
                lines[job.unit] = line
                return True
            job.on_line = on_line
            jobs.append(job)
        self.run_jobs(jobs)

    def review_pass(self, frm, first):
        """One review of `frm..head`: the result of `wave findings` that asks for a fixer, or None when nothing is left to fix."""
        self.at("review")
        rc, r = self.wave("review", "--part-dir", self.part, "--from", frm, "--to", self.head, *(["--security"] if self.args["security"]["needed"] else []))
        if rc != 0:
            raise Stop("failed", "wave review exited %d: %s" % (rc, r))
        units = [{"role": x["role"], "unit": x["unit"], "brief": x["brief"]} for x in r["reviewers"]]
        lines, verifier = {}, None
        self.reviewers(units, lines)
        control = ["--control-findings", self.flags["control"]] if first and self.flags.get("control") else []
        while True:
            if verifier:
                rc, r = self.wave("findings", "--verdicts", lines[verifier] or "no reply")
            else:
                said = [(" " + lines[x["unit"]]) if lines[x["unit"]].startswith("-") else (lines[x["unit"]] or "no reply") for x in units]
                rc, r = self.wave("findings", "--report", *said, *control)
            nxt = r.get("next")
            if nxt == "verify":
                verifier = r["unit"]
                self.reviewers([{"role": "review-verifier", "unit": verifier, "brief": r["brief"]}], lines)
            elif nxt == "relaunch":
                self.reviewers(r["relaunch"], lines)
            elif nxt == "stop":
                raise Stop("failed", r.get("why"))
            elif nxt == "owner":
                raise Stop("needs-owner", r.get("why"))
            elif nxt == "done":
                return None
            elif nxt == "fix":
                return r
            else:
                raise Stop("failed", "wave findings said %r: %s" % (nxt, r.get("why")))

    def review(self):
        frm, first = self.args["base"], True
        while True:
            fix = self.review_pass(frm, first)
            first = False
            if fix is None:
                return
            self.spend(fix["why"])
            before = self.head
            self.at("fix")
            job = self.executor(fix["unit"], self.args["models"]["fixer"], fix["brief"], fix["head"])
            self.run_jobs([job])
            self.merge([job.result], final=True, findings=fix["ids"])
            frm = before

    # ---- the paths -----------------------------------------------------------------------------------------------------------------
    def revert(self):
        self.at("revert")
        ids = ",".join(self.args["revert"])
        rc, r = self.wave("revert", "--part-dir", self.part, "--findings", ids)
        if r.get("head"):
            self.head = r["head"]
        if isinstance(r.get("setup"), str) and r["setup"].strip():
            raise Stop(self.owner_status(), " ".join(r["setup"].split())[:600])
        if r.get("ok") is not True:
            raise Stop("failed", "a revert conflicted%s: nothing was reverted past it" % ((" on " + r["failed"]["id"]) if r.get("failed") else ""))
        rc, g = self.step("verify", "--json", "--dir", self.part)
        if g.get("rc") == 2:
            raise Stop(self.owner_status(), "verify could not run after the revert")
        if g.get("rc") != 0:
            raise Stop("failed", "the gate failed after the revert: %s" % " ".join("%s=%s" % (c.get("cmd"), c.get("rc")) for c in g.get("commands") or []))
        return "the reverts passed the gate on %s" % str(self.head)[:8]

    def execute(self):
        args = self.args
        if args["revert"]:
            return self.revert()
        self.orca_run = self.st.get("orca_run") or orca.run_create("fwx wave run %s" % self.run)
        self.st["orca_run"] = self.orca_run
        self.save()
        if not self.st.get("repo_added"):
            orca.ensure_repo(self.main)
            self.st["repo_added"] = True
            self.save()
        done = set(args["done"])
        if args["from"] == "gate":
            self.at("gate")
            self.merge([], final=True)
        elif args["fix"]:
            self.at("fix")
            ids = [f["id"] for f in args["fix"]["findings"]]
            job = self.executor("fix", args["models"]["fixer"], args["fix"]["brief"], self.head)
            self.run_jobs([job])
            self.merge([job.result], final=True, findings=ids)
        else:
            todo = [w for w in args["waves"] if any(t["id"] not in done for t in w["tasks"])]
            if not todo:
                raise Stop("needs-owner", "every task of the part is already on the phase branch: nothing to execute; to run the gate and the review on it: "
                           "fwx wave run --part-dir %s --plane %s --branch %s --from gate" % (self.part, self.plane, args["branch"]))
            for i, w in enumerate(todo):
                self.at("wave %s" % w["n"])
                jobs = [self.executor(t["id"], args["models"]["executor"][t["id"]], t["brief"], self.head, self.beside(t["id"])) for t in w["tasks"] if t["id"] not in done]
                self.run_jobs(jobs, 1 if w["serial"] else None)
                self.merge([j.result for j in jobs], final=i == len(todo) - 1)
        self.review()
        return "the gate and the review passed on %s" % str(self.head)[:8]


def spawn_state(args, top, branch, flags):
    return {"run": args["run"], "branch": branch, "part_dir": args["part_dir"], "plane": args["plane"], "pid": os.getpid(), "state": "active", "step": "start",
            "orca_run": None, "workers": {}, "worktrees": [], "steps": [], "args": args, "flags": flags, "result": None, "started": time.time()}


def drive(args, top, flags, state=None):
    """(status, why, result line): the run end to end. `state` is a resumed run's; a refusal before any worker is `Refused` (exit 2)."""
    folder = os.path.join(runs_folder(top), args["run"])
    os.makedirs(folder, exist_ok=True)
    st = state or spawn_state(args, top, args["branch"], flags)
    st["pid"], st["state"] = os.getpid(), "active"
    r = Run(args, top, flags, st, folder)
    r.save()
    status, why = "failed", ""
    try:
        why = r.execute()
        status = "done"
    except Stop as e:
        status, why = e.status, e.reason
    except orca.OrcaError as e:
        status, why = "failed", "orca: %s" % e
    except WaveError as e:
        status, why = "failed", str(e)
    except Exception as e:  # nothing may end the run without its cleanup and its line
        status, why = "failed", "script error: %s: %s" % (type(e).__name__, e)
    finally:
        kept = finish(r, st, folder)
    st["state"] = status if status in STATES else "failed"
    st["result"] = {"status": st["state"], "why": why, "kept": kept["kept"], "removed": kept["removed"], "leftover": kept.get("leftover", [])}
    r.save()
    why = " ".join(str(why).split())
    n = len(kept["kept"])
    return st["state"], "run %s %s: %s%s" % (args["run"], st["state"], why[:600], (" (%d worktree%s kept)" % (n, "" if n == 1 else "s")) if n else ""), kept["kept"]


def finish(r, st, folder):
    """Release every worker still open, then remove the worktrees of the run: `{removed, kept, leftover}`."""
    for rec in st["workers"].values():
        r.release(rec)
    branches, paths = cleanup.recorded_of(os.path.dirname(os.path.dirname(runs_folder(r.top))), st["run"])
    try:
        hold = {os.path.realpath(w["worktree"]): "its worker could not be released, so it may still be using it"
                for w in st["workers"].values() if w.get("dispatch") and not w["released"]}
        got = cleanup.cleanup(r.top, st["run"], branches, paths, hold)
    except (WaveError, cleanup.NoProc) as e:
        return {"removed": [], "kept": [{"worktree": w["path"], "branch": w.get("branch"), "why": "cleanup could not run: %s" % e} for w in st["worktrees"]], "leftover": []}
    return got
