<!-- copied-from: pstack plugins/pstack/skills/poteto-mode/playbooks/orchestrate.md @36885ea (lines 40-53: the nine fields in their order; the TIMEBOX clause "on expiry, return partial findings and stop rather than run on" and the FORBIDDEN list "no PR retargets or merges, no rebase, no force-push, no fixes outside scope" word for word; "paths it may not" in SCOPE) -->
<!-- Differs from the referent: markdown headings instead of a column of labels, because `fwx wave prepare` fills the slots and its test reads the fields back; the pasted STANDING is a path, because the executor's agent definition (agents/executor.md) is the agent's own prompt; a field that code can fill is filled by `lib/fwx/execute/brief.py` and an empty one stops the launch. -->
<!-- Everything above the first heading is dropped when a brief is written. A `$name` is a slot brief.py fills; a missing or an unused slot fails the test. -->
# Brief: $heading

## GOAL
$goal

## SCOPE
You may write only these files, in your own worktree (your starting directory, made from the base below):
$files
You may not write any other path, except your TMPDIR and your report. The files of the tasks that run beside yours: $may_not
Run: $run
Base: $base (your first step is `fwx wave check-base $base`).
Your branch is the one your worktree starts on; the report names it.
Every commit ends with these trailers, given with `git commit --trailer`:
$trailers
Your TMPDIR is $tmpdir

## CONTEXT
$context

## ACCEPTANCE
$acceptance

## VERIFY
Run only these; `fwx verify` runs the project's checks later, on the merged commit.
$verify

## TIMEBOX
$minutes minutes: a guide, since nothing cuts an agent off; on expiry, return partial findings and stop rather than run on: commit what is sound, report `failed` with the reason `timebox`.

## FORBIDDEN
- no PR retargets or merges, no rebase, no force-push, no push, no fixes outside scope
- no writing in `.fwx/`
What you see outside your files goes in `outside` of your report, not in a commit.

## REPORT
Write it as JSON to $report, with Bash (a heredoc): Write is refused outside your worktree. Its fields: `{status, branch, worktree, head, commits, red: {cmd, message}, green: {cmd}, question, outside, could_not_run, reason}`, `status` being `done`, `wrong-base`, `question` or `failed`.
Your whole reply is one line: `<status> <report path> commits=<n>`.

## STANDING
Your standing orders are your agent definition, $standing; they hold beside everything above.
