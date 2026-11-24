<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/orchestrate.md @36885ea (lines 40-53: the nine fields in their order; the TIMEBOX clause "on expiry, return partial findings and stop rather than run on" word for word; the FORBIDDEN list and "paths it may not" in SCOPE). Differs: FORBIDDEN keeps only the coordination bans, since a small defect outside the task is fixed (playbooks/principles.md rule 12); markdown headings, because `fwx wave new` fills the slots and its test reads the fields back; STANDING is a path, since the agent definition is the agent's own prompt. -->
<!-- Everything above the first heading is dropped when a brief is written. A `$name` is a slot `lib/fwx/execute/brief.py` fills; a missing or an unused slot fails the test. -->
# Brief: $heading

## GOAL
$goal

## SCOPE
You may write these files, in your own worktree (your starting directory):
$files
A small defect you see outside your task is yours to fix, in its own commit, unless its file is one of the tasks that run beside yours, which you may not write: $may_not
Anything else outside your task you file as a Linear issue (`fwx linear new --template general < <JSON in your scratch folder>`) and put in `outside` of your report with its key (playbooks/principles.md rule 12). Write nothing under `.git`, in the main checkout or in `.fwx/`.
Run: $run
Base: the `BASE` line of your prompt, the tip of the phase branch when your wave launched. Your first step is `fwx base` with that sha. Your branch is the one your worktree starts on.
Every commit ends with these trailers, given with `git commit --trailer`:
$trailers
Your scratch folder is the one `fwx scratch new $run $unit` prints, in your worktree and ignored by git. Your TMPDIR is `tmp/` inside it.

## CONTEXT
$context

## ACCEPTANCE
$acceptance

## VERIFY
Run only these, and the tests a small outside fix of yours needs; `fwx verify` runs the project's checks later, on the merged commit.
$verify

## TIMEBOX
$minutes minutes: a guide, since nothing cuts an agent off; on expiry, return partial findings and stop rather than run on: commit what is sound, report `failed` with the reason `timebox`.

## FORBIDDEN
- no PR retargets or merges, no rebase, no force-push, no push
- no writing in `.fwx/`

## REPORT
Write it as JSON to `report.json` directly in your scratch folder, not in its `tmp/` (the file-write tool is enough). Its fields: `{status, branch, worktree, head, commits, red: {cmd, message}, green: {cmd}, question, assumptions, outside, could_not_run, reason}`. Each item of `outside` is `{where: path:line, what, fix, size: small|large, issue: <Linear key>|null}`; `issue` is `null` only where the project has no Linear project, or with `issue_error` when `fwx linear new` failed. A report whose items lack that shape is rejected.
Your whole reply is one line: `<status> <report path> commits=<n>`, the report path in full.

## STANDING
Your standing orders are your agent definition, $standing; they hold beside everything above.
