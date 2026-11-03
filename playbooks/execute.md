# Execute
<!-- copied-from: marshal-factory playbooks/factory.md @999ad209598517a4c826073b5a0edc2a4097a4fa (the three rules of "Standing rules" named in the section below, each line as written there) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/orchestrate.md @36885ea (the shape: one line saying who owns what, the units delegated with a complete brief) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/worktree-cleanup.md @36885ea (short numbered steps; cleanup that lists what it keeps) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/bug-fix.md @36885ea (the failing test first, in its own commit) -->
<!-- Differs from the referents: one block per node of the tree, because `fwx playbooks check` compares them; cleanup never forces or deletes by hand (the referent prunes with `--force` after a human decision; here `fwx wave cleanup` removes only merged worktrees); the gate is a script, not the coordinator's judgment. -->

Version: 1

This playbook says what each node of the execution stretch of the workflow does, who does it and where it leads. The `execute` workflow (`/fwx:execute`) runs it from the output of `fwx wave prepare`; the orchestrator reads it to know what a returned status means. The orchestrator writes no code: it acts on what the commands print.

## Standing rules

Three rules are copied from the factory playbook as written. Where they name `factory-verify` or `report_stage`, read `fwx verify` and the `failed` status that `execute` returns. The line under each rule names what enforces it here. The executor does not run the proof of the second rule: `fwx verify` runs it at n_C7 on the merged head, and an executor runs only the tests its task lists. The `bun` command, the sandbox sentence and `pr` in that rule have no counterpart here.

- **Clean up only what you started.** Other runs and the operator's own servers share this machine. Start a dev server on a free port, remember its PID, and stop that PID before the turn ends. Never `pkill` or `killall` by name, and never stop a process you did not start.
  Enforced by `fwx wave cleanup --run R`, which removes only the worktrees of its own run, lists in `leftover` the processes still inside them and kills none; the walk's browsers and app are closed by `fwx walk down`.
- **Prove the commit you ship.** Before you report `pr`, run `factory-verify` in the worktree on the final pushed commit, with nothing uncommitted. In a sandbox it is on `PATH`; elsewhere run the command the `report_stage` reply for `verifying` names (`bun <factory root>/hooks/verify.ts`). It runs the repo's checks at `HEAD` and reports exit codes and output for that exact commit. The factory merges only a head whose checks passed there, and runs them itself when it can. Uncommitted changes make the run count for nothing. If you push again, run it again.
  Enforced by `fwx verify`, which runs the recipe on a clean tree at the exact commit, writes the `evidence` row with that SHA and exits 2 when it cannot prove the commit (dirty tree, moved HEAD); `fwx wave summary --run R` reports `gate: fail` unless the last evidence row is green for the head.
- **Giving up means `failed`.** If you cannot finish (three fix rounds on the same failure, a broken toolchain, a dead end), call `report_stage` with `stage: "failed"` and the reason in `summary`, then end the turn.
  Enforced by `fwx rounds` and `fwx wave fix-round`, which count the three rounds per job, not per failure: when different things keep failing the task is hard and needs the owner. Only `fix-round` spends a round, and if this failure is the round (verify wrote it) it spends no second; it exits 1 only when three were spent before this failure, and `execute` then returns `failed`.

## Rules of the stretch

- Every agent that writes code works in its own worktree; agents that only read (reviewers, researchers) need none. `fwx wave check-base <sha>` is each writer's first step and exits 42 on the wrong base or a main checkout; only `fwx wave integrate` merges or reverts on the phase branch.
- A brief with an empty field is not launched: `fwx wave prepare` writes one brief per task and exits 2 naming the task and the field. Each brief carries the absolute paths of `context.md`, `decisions.tsv` and `plan.md`.
- An agent that returns nothing, or without what its brief asks for, has not passed. The workflow relaunches it once without spending a round; a second miss is recorded as a gap and the run ends `failed`.
- Ponytail runs when code is reviewed and never when it is executed. The reviewer definitions invoke it and the executor's does not.
- After a crash or an exhausted quota the session resumes from disk: the owner says "continue", the orchestrator reads the last `stage` row and the phase branch, and `fwx wave prepare` lists in `done` every task whose `Fwx-Task` trailer the phase branch already holds. The factory resumes by stage from its tick (its own playbook).

## Nodes

### n_C5 · Executors in parallel, one per task, each in its own worktree
- **Who:** agent executor
- **Stage:** executing
- **Writes:** nothing
- **Invokes:** command fwx capacity
- **Does:** Each executor takes one task from the wave and starts by the kind the plan gives it. A bug starts with a test that reproduces it, in its own commit, and the executor quotes what the failing run says. A refactor starts with a characterization test that passes before anything moves, in its own commit, because a refactor has no failing test to write and a type check or lint does not pin behaviour. A feature starts with the tests its criteria list, failing, in their own commit. A UI task carries no test. Then the code, and the executor returns `done`, `wrong-base`, `question` or `failed`. `done` is integrated. `wrong-base` and `failed` leave their branch out of the merge and the task is fixed through `fwx wave fix-round`, which spends a round. `question` is not a failure: the orchestrator puts it to the owner, and the factory ends the job `needs-owner`. `fwx capacity --role executor --want N` says how many may start now and `allowed 0` ends the run as `failed` with the reason capacity; two tasks that write the same file never share a batch. When the executors of the wave have returned, `fwx wave integrate` merges their branches into the phase branch in order and runs `checks_quick`.
- **Exits:**
  - to n_C6: the executors of the wave have returned and their branches merge
  - to n_C8: the branches conflict or the code does not build
- **Why:** an executor's own report does not decide: the gate in the next nodes overwrites it.

### p_PAR · The parallel limit
- **Who:** script fwx capacity
- **Stage:** executing
- **Writes:** nothing
- **Invokes:** command fwx capacity
- **Does:** At most 3 executors run at once with the owner present and 4 when nobody is present (`--unattended`), until the measured memory figures replace them; `limits.per_project.executor` overrides the number, and free memory under `ram_min_free_gb` gives 0.
- **Exits:** none

### n_C6 · Is there another wave?
- **Who:** script /fwx:execute
- **Stage:** executing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The workflow compares the waves of `args.waves` with the tasks already done. The last wave is integrated with `--final`, which runs the whole gate on the merged result.
- **Exits:**
  - loop n_C5: yes, another wave remains
  - to n_C7: no, that was the last wave

### n_C7 · Do the checks pass at the exact commit?
- **Who:** script fwx verify
- **Stage:** reviewing
- **Writes:** audit.tsv
- **Invokes:** command fwx verify
- **Does:** `fwx verify --json` runs the project's recipe once on a clean tree and appends an `evidence` row with the SHA; exit 0 is a pass, 1 a failing check, 2 that it could not prove the commit. A diff that edits the checks recipe, CI or a protected path goes to the owner without spending a round, because it changes what counts as passing or touches what needs the owner's judgment: the session asks him, the factory ends `needs-owner`.
- **Exits:**
  - to n_C9: the checks pass and the diff touches no recipe, CI or protected path
  - to n_C8: a check fails
  - to n_Z3: factory: the diff edits the checks recipe, CI or a protected path
  - to n_Z4c: factory: the checks cannot run
  - to n_L8: session: the diff edits the checks recipe, CI or a protected path
  - to n_C7F: session: the checks cannot run

### n_C7F · The orchestrator tries to fix it: dirty tree, environment or a recipe that does not run
- **Who:** orchestrator
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** Read why `fwx verify` exited 2 and fix the cause (clean the tree, install the missing tool) without asking. No round is spent, because no code was judged. A recipe command that does not run is not repaired here: the recipe is what decides that the work passes, so editing it is the owner's call, and it leaves by the second exit. The owner is also asked when the cause lies outside the project or needs a choice.
- **Exits:**
  - loop n_C7: fixed, the checks run again
  - to n_L8: it cannot be fixed, or the recipe command is what fails

### n_C8 · Are there fix attempts left? (3 per job)
- **Who:** script fwx wave fix-round
- **Stage:** -
- **Writes:** audit.tsv
- **Invokes:** command fwx wave fix-round
- **Does:** `fix-round` spends one of the job's three rounds with `fwx rounds --use`, unless the last row of `audit.tsv` is the red evidence of this head: this failure is the round (verify wrote it), so no second is spent. It exits 1 only when three were spent before this failure. A fixer receives the failure and its work returns through `fwx wave integrate`; a conflict goes to the executor's conflict resolver instead, on a new branch from the tip of the phase branch. The node has no stage of its own: it runs in the stage of the node that sent it here (executing, reviewing or ui-walk).
- **Exits:**
  - loop n_C5: attempts left, fix
  - to n_Z4c: 3 attempts spent, factory
  - to n_L8: 3 attempts spent, session

### n_C9 · Code and security review: the verifier sorts each finding
- **Who:** agent reviewer, review-verifier, security-reviewer
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** skill ponytail:ponytail-review
- **Does:** The reviewer, and the security-reviewer when the plan asks for it, read the diff without a worktree and the part's success criteria in `plan.md`; "no findings" is a valid result. The reviewer returns each criterion as met or not met with its evidence, and a criterion that is not met is a finding with that evidence. Each finding goes to one review-verifier, the cheap role, which sorts it into one of the four groups of the next block; only `fix` is fixed, one commit per finding with a `Fwx-Finding` trailer, merged with `fwx wave integrate --findings`, and the diff of the fix is reviewed again. A reviewer that returns `null` or an empty `looked_at` is relaunched once, and a second miss ends the run `failed`.
- **Exits:**
  - loop n_C8: fix: launches the fix and spends a round
  - to n_C10: no finding is left to fix
- **Why:** the one who verifies a finding is not the one who reported it, and the verifier sees the finding and the diff, not the reporter's reasoning.

### p_GRP · The four groups of findings
- **Who:** agent review-verifier
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** `fix` is fixed. `consider` is not fixed and spends no round: it goes to the phase report in a session and to the handover in the factory. `note` is kept in the report's notes, and `dismiss` is dropped with its reason.
- **Exits:** none

### p_CLEAN · Clean worktrees and browsers
- **Who:** script fwx wave cleanup
- **Stage:** executing
- **Writes:** nothing
- **Invokes:** command fwx wave cleanup
- **Does:** Runs in a `finally`, so also after a failure. `fwx wave cleanup --run R` removes the merged worktrees of the run with `git worktree remove` (no `--force`) and `git branch -d`, keeps and lists in `kept` any that is locked, dirty or unmerged, and lists in `leftover` the processes still inside a worktree of the run without killing them.
- **Exits:** none

### n_C10 · Is it the owner's session or the factory?
- **Who:** script /fwx:execute
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The answer is `args.plane`, set by `fwx wave prepare --plane`. The session goes on to the UI question and to the review of the part with the owner; the factory goes on to its own handover.
- **Exits:**
  - to n_C11: the owner's session
  - to n_R6: factory
