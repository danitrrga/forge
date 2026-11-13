# Execute
<!-- copied-from: marshal-factory playbooks/factory.md @999ad209598517a4c826073b5a0edc2a4097a4fa (the three rules of "Standing rules" named in the section below, each line as written there) -->
<!-- copied-from: pstack plugins/pstack/skills/poteto-mode/playbooks/orchestrate.md @36885ea (line 110, the sentence "Never reaches the human: ..." of "Rules of the stretch", as written there) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/orchestrate.md @36885ea (the shape: one line saying who owns what, the units delegated with a complete brief) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/worktree-cleanup.md @36885ea (short numbered steps; cleanup that lists what it keeps) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/bug-fix.md @36885ea (the failing test first, in its own commit) -->
<!-- Differs from the referents: one block per node of the tree, because `fwx playbook lint` compares them; cleanup never forces or deletes by hand (the referent prunes with `--force` after a human decision; here `fwx wave remove` removes only merged worktrees); the gate is a script, not the coordinator's judgment. Written from `workflows/execute.js` and `lib/fwx/execute/`: where this text and the code differ, the code rules. -->

Version: 2

This playbook says what each node of the execution stretch of the workflow does, who does it and where it leads, as `workflows/execute.js` built it. The `execute` workflow (`/fwx:execute`) runs from the output of `fwx wave new` (its `args`); the orchestrator works from the workflow and reads this only to know what a returned status means, and no agent loads it. The orchestrator writes no code: it acts on what `execute` returns. The nodes whose Who is `script` (n_C6, n_C7, n_C8, n_C10, p_PAR, p_CLEAN) are run, not deliberated (the rule is in `session.md`).

## Standing rules

Three rules are copied from the factory playbook as written. Where they name `factory-verify` or `report_stage`, read `fwx verify` and the `failed` status that `execute` returns. The line under each rule names what enforces it here. The executor does not run the proof of the second rule: `fwx verify` runs it at n_C7 on the merged head, and an executor runs only the tests its task lists. The `bun` command, the sandbox sentence and `pr` in that rule have no counterpart here.

- **Clean up only what you started.** Other runs and the operator's own servers share this machine. Start a dev server on a free port, remember its PID, and stop that PID before the turn ends. Never `pkill` or `killall` by name, and never stop a process you did not start.
  Enforced by `fwx wave remove --run R`, which removes only the worktrees of its own run, lists in `leftover` the processes still inside them and kills none; the walk's browsers and app are closed by the walk's own cleanup (`fwx walk stop`, in `ui-walk.md`).
- **Prove the commit you ship.** Before you report `pr`, run `factory-verify` in the worktree on the final pushed commit, with nothing uncommitted. In a sandbox it is on `PATH`; elsewhere run the command the `report_stage` reply for `verifying` names (`bun <factory root>/hooks/verify.ts`). It runs the repo's checks at `HEAD` and reports exit codes and output for that exact commit. The factory merges only a head whose checks passed there, and runs them itself when it can. Uncommitted changes make the run count for nothing. If you push again, run it again.
  Enforced by `fwx verify`, which runs the recipe on a clean tree at the exact commit, writes the `evidence` row with that SHA and exits 2 when it cannot prove the commit (dirty tree, moved HEAD); `fwx wave --run R` reports `gate: pass` only when the last evidence row is green for the head and, for a run that merged branches, that run's own last `wave merge --final` was green (the evidence row is the part's, not the run's), `fail` otherwise (its `why` says when it is the run) and `none` with no row.
- **Giving up means `failed`.** If you cannot finish (three fix rounds on the same failure, a broken toolchain, a dead end), call `report_stage` with `stage: "failed"` and the reason in `summary`, then end the turn.
  Enforced by `fwx rounds` and `fwx wave fix`, which count the three rounds per job, not per failure: when different things keep failing the task is hard and needs the owner. Only `wave fix` spends a round (n_C8 says when), and `execute` returns `failed` when it refuses one.

## Rules of the stretch

- **Four runs.** `wave new` builds the `args` of the waves of a part; or of `--fix <fix.json>`, one fixer for a list of findings (the UI walk's), whose diff goes through the gate and the review like any other; or of `--revert <ids>`, which launches nothing and reviews nothing (n_C9); or of `--from gate`, which launches nothing and goes in at the gate (n_C7F loops back to n_C7). `--from gate` needs every task on the phase branch and judges the head as it is; its `base` is where the part's first run started, so that the review covers the whole part (`prepare.py` has the rest).
- **Commands go through a runner.** An executor of the smallest size runs each command (`fwx capacity`, `fwx wave ...`, `fwx verify`) and returns its stdout and exit code. The workflow decides from the JSON on that stdout, never from the exit code or from what the runner says. A runner with no JSON ends the run `failed` (`runner did not return: <step>`); the commands that can run twice (`capacity`, reading a report, `cleanup`) are asked a second time first.
- **A writer has its own worktree.** Every agent that writes code (executor, fixer, resolver) runs with `isolation: worktree`, which starts from the phase branch because `worktree.baseRef` is `head`: `wave new` refuses to run otherwise, since the default is `origin/<default branch>` and nothing says so. The runner works in the integration checkout, and agents that only read (reviewers, the verifier) need no worktree. `fwx base <sha>` is each writer's first step and exits 42 on the wrong base or a main checkout, and 43 when the base is right but the project's `worktree_setup` failed in that worktree (`.fwx-agent/worktree-setup-failed.json` then holds its line). The sha is the phase head when the agent's wave launches, which the workflow puts in the prompt as `BASE` (a later wave starts from the head after the earlier waves merged, so the brief, written once at `wave new`, holds none); only `fwx wave merge` and `fwx wave revert` write the phase branch.
- **A failed setup ends the job.** A worktree has none of the project's installed dependencies, so `wave new` (the phase worktree), `base` (each writer's) and `wave merge` and `wave revert` (after a merge or a revert that changed a dependency file) run `worktree_setup` first. If it fails, `execute` returns `needs-owner` (session) or `failed` (factory) with the setup's own line, spends no round and launches no new attempt, because a new worktree would fail the same way: the workflow reads the record `base` left in the writer's worktree and the `setup` key of the `integrate` and `revert` result, and the start of the writer's reason is only a second net.
- **A brief with an empty field is not launched.** `wave new` writes one brief per task in `<git-common-dir>/fwx/runs/<run>/briefs/` and exits 2 naming the task and the field, with nothing written; it exits 1 (`needs-owner`, no round) for a red base, and 2 for the other things that must stop a run before it starts (`prepare.py` lists them). A brief has nine fields (GOAL, SCOPE, CONTEXT, ACCEPTANCE, VERIFY, TIMEBOX, FORBIDDEN, REPORT, STANDING) and carries the absolute paths of `context.md`, `decisions.tsv` and `plan.md`. The prompt of an executor is one line naming its file. The fixer of a gate or review failure, the resolver, the reviewers and the verifier have no file: their prompt is their brief, with the same paths (the fixer of `--fix` has one, `fix.brief`). The executors, the fixer, the resolver and the reviewers write their report as JSON in a folder of their own worktree that git ignores (`fwx scratch new <run> <unit>` makes it and prints it; never under `.git`, which Claude Code asks permission for) and reply with one line naming the file in full; the workflow reads only that unit's `report.json` there. The review-verifier and the runner write none: they answer through a structured output (`{verdicts: [...]}`, `{stdout, rc}`).
- **An agent that returns nothing, or without what its brief asks for, has not passed.** That is a `null` or empty reply, a reply line that the file contradicts, a `done` with no branch, a `question` with no question, a review with an empty `looked_at`. The workflow relaunches it once with no round; a second miss goes to `gaps` and the run ends `failed`. A new attempt after `failed` or `wrong-base` is another matter: the same brief plus the previous report quoted as data, started from the base and never from that work. An `agentType` that does not exist ends `failed` at once.
- **Ponytail runs when code is reviewed and never when it is executed.** The reviewer definitions invoke it; the executor's and the verifier's do not.
- **What `execute` returns** is `{status, reason, phase_dir, details}`, `status` being `done`, `failed` or `needs-owner`; each node below says which of them it ends with. `details` carries the gate's evidence line, the rounds, `plan_failures`, the criteria, the findings by group (`fixed` with its commit), `outside`, `gaps`, `kept_worktrees` and `leftover`.
- **What reaches the owner.** Never reaches the human: frontier nudges, rebase mechanics, retries, CI flake triage, review-thread triage, format fixes, scope the brief already forbids (refuse and continue), and "should I keep going". Here the retries are the relaunch and the fix rounds, and a scope the brief forbids is refused by the executor and reported in `outside`. What reaches him is `needs-owner`, and in the session a `failed` too (a part that gave up is one of the ways into n_L8 of `session.md`).
- **After a crash or an exhausted quota the session resumes from disk:** the owner says "continue", the orchestrator reads the last `stage` row, which may name any stage and not only `executing` (the exits of n_L3 in `session.md`), and the phase branch, and `fwx wave new` lists in `done` every task whose `Fwx-Task` trailer the phase branch already holds. The factory resumes by stage from its tick (its own playbook).

## Nodes

### n_C5 · Executors in parallel, one per task, each in its own worktree
- **Who:** agent executor
- **Stage:** executing
- **Writes:** nothing
- **Invokes:** command fwx capacity
- **Does:** Each executor takes one task of the wave and starts by the kind the plan gives it. A bug starts with a test that reproduces it, in its own commit, and the executor quotes what the failing run says. A refactor starts with a characterization test that passes before anything moves, in its own commit, because a refactor has no failing test to write and a type check or lint does not pin behaviour. A feature starts with the tests its criteria list, failing, in their own commit. A UI task carries no test. Then the code, and the executor returns `done`, `wrong-base`, `question` or `failed`. `done` is integrated. `wrong-base` and `failed` leave their branch out of the merge: the workflow calls `fwx wave fix` and, when a round is left, launches the task again in a new worktree. `question` spends no round: the run ends `needs-owner` with the question, which the session puts to the owner at the review of the part. Before each batch the workflow runs `fwx capacity --role executor --want N --wait 540`, which waits up to nine minutes for room: it starts `allowed` executors at once, and `allowed 0` ends the run `failed` with the reason capacity, launching none. A wave with `serial: true` (two tasks that write the same file, or one inside a folder the other declares; `wave new` also lists them in `plan_failures`) runs one executor at a time. When the executors of the wave have returned, `fwx wave merge` merges their branches into the phase branch in order, with `--no-ff`, and runs `checks_quick`; a branch whose worktree holds a live agent is not merged, nothing is, and the run ends `failed`.
- **Exits:**
  - to n_C6: the executors of the wave have returned and their branches merge
  - to n_C8: the branches conflict or the code does not build
  - to n_L8: session: an executor asks a question, or the machine has no capacity to launch it
  - to n_Z3: factory: an executor asks a question, or the machine has no capacity to launch it
- **Why:** an executor's own report does not decide: the gate in the next nodes overwrites it.

### p_PAR · The parallel limit
- **Who:** script fwx capacity
- **Stage:** executing
- **Writes:** nothing
- **Invokes:** command fwx capacity
- **Does:** At most 3 executors run at once with the owner present and 4 when nobody is present (`--unattended`, which the factory always passes), until the measured memory figures replace them; `limits.per_project.executor` overrides the number, and `limits.on` false lifts every limit. `fwx capacity` counts the executors alive (their worktree lock names a process that still runs) and the room free memory leaves above `ram_min_free_gb`, at `ram_per_agent_mb` each; under the floor it gives 0.
- **Exits:** none

### n_C6 · Is there another wave?
- **Who:** script /fwx:execute
- **Stage:** executing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The workflow takes the waves of `args.waves` that still have a task not on the phase branch (`done`), and launches only those tasks. The last wave is integrated with `--final`, which runs the gate on the merged result. A wave starts after the one before it is merged, so its worktrees, made from the phase branch, hold that wave's files. With every task already `done` and no `--from gate` there is nothing to run and the run ends `needs-owner`, its reason being the `fwx wave new ... --from gate` command that goes on.
- **Exits:**
  - loop n_C5: yes, another wave remains
  - to n_C7: no, that was the last wave

### n_C7 · Do the checks pass at the exact commit?
- **Who:** script fwx verify
- **Stage:** reviewing
- **Writes:** audit.tsv
- **Invokes:** command fwx verify
- **Does:** Between waves only `checks_quick` runs, after each merge, in `executing` (after the project's `worktree_setup` again when the merge changed a dependency file). The gate is the `--final` integrate of the last wave, and again of each review fix, and the workflow enters `reviewing` before each one (the fix a red gate sends back, n_C8 to n_C5, is made in `executing`). With `--from gate` it is the `--final` integrate with no branch: nothing is merged and the gate runs on the head as it is. Once the merge and `checks_quick` are green, `fwx verify` runs the project's whole recipe once on a clean tree at the merged head and appends an `evidence` row with the SHA (`fwx wave --run R` says `gate: pass` only when the last row is green for that head). Exit 0 passes, 1 is a failing check, 2 is that it could not prove the commit (dirty tree, moved HEAD, no recipe): in the session the run ends `needs-owner` and the orchestrator takes it from n_C7F, in the factory it ends `failed`. A diff that edits the recipe, the CI, or a file a check runs (a script it calls, the configuration of the tool it names) ends `needs-owner` without a round and without a review, because it changes what counts as passing: the session asks him, the factory hands over. A protected path does not stop here: n_C9 reviews it first.
- **Exits:**
  - to n_C9: the checks pass and the diff edits no recipe or CI
  - to n_C8: a check fails
  - to n_Z3: factory: the diff edits the checks recipe or CI
  - to n_Z4c: factory: the checks cannot run
  - to n_L8: session: the diff edits the checks recipe or CI
  - to n_C7F: session: the checks cannot run

### n_C7F · The orchestrator tries to fix it: dirty tree or environment
- **Who:** orchestrator
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** Run `fwx verify` to read why it exited 2 (the run's reason has only its exit and, when there is one, its evidence line) and fix the cause (clean the tree, install the missing tool) without asking. No round is spent, because no code was judged. A recipe command that does not run is not repaired here: the recipe is what decides that the work passes, so editing it is the owner's call, and it leaves by the second exit. The owner is also asked when the cause lies outside the project or needs a choice. The workflow has already returned, so the orchestrator runs `fwx verify` itself to see that the cause is gone, then runs `fwx wave new --from gate` and `/fwx:execute` again: that is the loop back to n_C7, and the gate on the head (then the review of n_C9) runs inside it. A `wave new` without `--from gate` finds every task `done` and returns `needs-owner`.
- **Exits:**
  - loop n_C7: fixed, the checks run again
  - to n_L8: it cannot be fixed, or the recipe command is what fails

### n_C8 · Are there fix attempts left? (3 per job)
- **Who:** script fwx wave fix
- **Stage:** -
- **Writes:** audit.tsv
- **Invokes:** command fwx wave fix
- **Does:** `wave fix` spends one of the job's three rounds (`rounds` in the configuration) with `fwx rounds --use`, unless the last row of `audit.tsv` is the red evidence of this head: this failure is the round (verify wrote it), so no second is spent. It exits 1 only when three were spent before this failure, so the third round is fixed and only the failure after it ends the run `failed`, reason `rounds exhausted`. A conflict between executors spends a round like any failure. The fix is made in `executing` (n_C5), also when the failure came from the gate or the review. Who fixes depends on what failed. An executor that returned `failed` or `wrong-base` is launched again on its task. A red `checks_quick` or gate, or commits that are not one per finding, goes to a fixer: an executor with the failure as data and no brief file, test first when a test can express it. A conflict goes to the conflict resolver, on a new branch from the tip of the phase branch: it runs `git merge --no-commit` of the conflicting branch, never rebases, and when the two changes contradict and the plan does not say which wins it runs `git merge --abort` and returns `question` naming both. What a fixer or resolver makes returns through `fwx wave merge`, in place of the branch that failed. The node has no stage of its own: it runs in the stage of the node that sent it here (executing, reviewing or ui-walk).
- **Exits:**
  - loop n_C5: attempts left, fix
  - to n_Z4c: 3 attempts spent, factory
  - to n_L8: 3 attempts spent, session

### n_C9 · Code and security review: the verifier sorts each finding
- **Who:** agent reviewer, review-verifier, security-reviewer
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** skill ponytail:ponytail-review
- **Does:** In parallel and without a worktree, the reviewer, and the security-reviewer when the plan asks for it (`security_review` in `postmortem.md`, or `--security`) or the diff touches a protected path, read the diff and the part's success criteria in `plan.md`; "no findings" is a valid result. The reviewer runs the measure of each criterion, cites what it printed and returns `met` as `yes`, `no` or `unproven`: a criterion it could not run is `unproven`, never `yes`, and stays in the result's `criteria`; only a `no` is a finding, and a report in which no finding names it is a miss. Finding ids carry the pass (`r1-F1`, `r2-F1`), because `wave merge --findings` and `wave revert` find a commit by its id. One review-verifier, the cheap role, sees the findings and the diff, not the reporter's reasoning, and sorts each finding into the four groups of the next block. The `fix` ones go to one fixer after one round, one commit per finding with its test seen failing and a `Fwx-Finding` trailer; `fwx wave merge --findings <ids> --final` refuses anything that is not one commit per finding, merges, runs the gate again, and the next pass reviews the diff of the fix only. That shape lets the owner reject one fix alone with `--revert` (above): `fwx wave revert` undoes the commit of each finding and `fwx verify` is the gate; there is no review, since that code was reviewed. A diff that touches a protected path is reviewed like any other and, once no finding is left to fix, ends `needs-owner` (`protected path`), never `done`: the session asks him, the factory hands over. A reviewer that returns `null`, an empty `looked_at` or an invalid report is relaunched once, and a second miss ends the run `failed`.
- **Exits:**
  - loop n_C8: fix: launches the fix and spends a round
  - to n_C10: no finding is left to fix and the diff touches no protected path
  - to n_Z3: factory: no finding is left to fix and the diff touches a protected path
  - to n_L8: session: no finding is left to fix and the diff touches a protected path
- **Why:** the one who verifies a finding is not the one who reported it, and the verifier sees the finding and the diff, not the reporter's reasoning.

### p_GRP · The four groups of findings
- **Who:** agent review-verifier
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The verifier returns one verdict per finding through a structured output: the group, a severity of its own and, for a real one, the layer that would have caught it (`code`, `check`, `rule` or `none`). `fix` is fixed. `consider` is not fixed and spends no round: it goes to the phase report in a session and to the handover in the factory, in `findings.consider` of the result with its file, line and severity. `note` is kept in the report's notes, and `dismiss` is dropped with its reason.
- **Exits:** none

### p_CLEAN · Clean worktrees and browsers
- **Who:** script fwx wave remove
- **Stage:** executing
- **Writes:** nothing
- **Invokes:** command fwx wave remove
- **Does:** Runs in a `finally`, so also after a failure. `fwx wave remove --run R` removes the worktrees of the run (those whose branch carries its `Fwx-Run` trailer or that `wave merge` named) that are unlocked, clean and merged, with `git worktree remove` (no `--force`) and `git branch -d`. What it cannot remove (a live agent, a dirty or unmerged worktree) it lists in `kept` with the reason, and it lists in `leftover` the processes still inside a worktree of the run, killing none; the phase branch, the main checkout and other runs' worktrees are never touched. The browsers of a UI walk are closed by the walk's own `finally` (`fwx walk stop`, in `ui-walk.md`), not here. Without `/proc` it exits 77, `NOT RUN, NOT ARMED`, and the workflow records the miss in `gaps`.
- **Exits:** none

### n_C10 · Is it the owner's session or the factory?
- **Who:** script /fwx:execute
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** `execute` makes no choice here: it returns its result, and the answer is `args.plane`, set by `fwx wave new --plane`. The session goes on to the UI question and to the review of the part with the owner; the factory goes on to its own handover.
- **Exits:**
  - to n_C11: the owner's session
  - to n_R6: factory
