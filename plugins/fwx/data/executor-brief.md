<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/orchestrate.md @36885ea (lines 40-53: the nine fields in their order; the TIMEBOX clause "on expiry, return partial findings and stop rather than run on" word for word; the FORBIDDEN list and "paths it may not" in SCOPE). Differs: the referent's FORBIDDEN also bans fixes outside the scope; here the owner's ownership rule (playbooks/principles.md rule 12) lets an agent fix a small defect outside its task, so only the coordination bans stay. -->
<!-- Differs from the referent: markdown headings instead of a column of labels, because `fwx wave new` fills the slots and its test reads the fields back; the pasted STANDING is a path, because the executor's agent definition (agents/executor.md) is the agent's own prompt; a field that code can fill is filled by `lib/fwx/execute/brief.py` and an empty one stops the launch. -->
<!-- Everything above the first heading is dropped when a brief is written. A `$name` is a slot brief.py fills; a missing or an unused slot fails the test. -->
# Brief: $heading

## GOAL
$goal

## SCOPE
You may write these files, in your own worktree (your starting directory):
$files
Beside them, a small defect you see outside your task is yours to fix, in its own commit, unless its file is one of the files of the tasks that run beside yours, which you may not write: $may_not
Anything else you see outside your task, a large defect or one in those files, you file as a Linear issue before you return (`fwx linear new --template general < <JSON in your scratch folder>`) and put in `outside` of your report with the key (playbooks/principles.md rule 12). Write nothing under `.git`, nothing in the main checkout and nothing in `.fwx/`.
Run: $run
Base: the `BASE` line of your prompt, the tip of the phase branch when your wave launched (it differs from wave to wave). Your first step is `fwx base` with that sha.
Your branch is the one your worktree starts on; the report names it.
Every commit ends with these trailers, given with `git commit --trailer`:
$trailers
Your scratch folder is the one `fwx scratch new $run $unit` prints: a folder of your own worktree that git ignores, never under `.git`. Your TMPDIR is `tmp/` inside it.

## CONTEXT
$context

## ACCEPTANCE
$acceptance

## VERIFY
Run only these, and the tests that a small outside fix of yours needs (its red and green); `fwx verify` runs the project's checks later, on the merged commit.
$verify

## TIMEBOX
$minutes minutes: a guide, since nothing cuts an agent off; on expiry, return partial findings and stop rather than run on: commit what is sound, report `failed` with the reason `timebox`.

## FORBIDDEN
- no PR retargets or merges, no rebase, no force-push, no push
- no writing in `.fwx/`

## REPORT
Write it as JSON to `report.json` directly in your scratch folder, not in its `tmp/` (the Write tool is enough). Its fields: `{status, branch, worktree, head, commits, red: {cmd, message}, green: {cmd}, question, outside, could_not_run, reason}`, `status` being `done`, `wrong-base`, `question` or `failed`. Each item of `outside` is `{where: path:line, what, fix, size: small|large, issue: <Linear key>|null}`: a defect you saw outside your task and did not fix, `issue` the key you filed it under, `null` only where the project has no Linear project, or when `fwx linear new` failed: then add `issue_error`, the first line of its error, and the run goes on. A report whose items lack that shape is rejected.
Your whole reply is one line: `<status> <report path> commits=<n>`, the report path in full.

## STANDING
Your standing orders are your agent definition, $standing; they hold beside everything above.
