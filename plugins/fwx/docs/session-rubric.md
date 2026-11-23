# Rubric for judging an executor session

A judge agent reads one executor session (the transcript and the diff it produced) and scores it on four dimensions. The same
rubric is applied to every session being compared, so that the medians per dimension can be set side by side.

## How to score

- Each dimension is an integer from 0 to 10. Every score cites the transcript line or the diff line that supports it. A score
  without a citation is not valid.
- **no score:** when nothing in the transcript or the diff shows a dimension, or a criterion of it does not apply to the task
  (for example, test-first craft on a task that carries no test), write `no score` for it and say why in one line. Never fill a
  gap with a middle number. A `no score` is left out of the median; it is neither a 0 nor a 5.
- Judge what happened, not what the session claimed. A report that says "done" counts only where the diff or a command's output
  in the transcript shows it.
- Judge the session on its own task. Do not reward work the task did not ask for.
- Output one block per dimension: `dimension: score | citation | one-line reason`, then a list of the criteria that were
  `no score`.

## Rules the work is held to

These are the engine's rules and the way of working the sessions are expected to follow. A criterion below names the rule it
comes from.

- A test is trusted only after it was seen failing: it was run against the old code, and the failure message was kept (in the
  test's comment, the commit message or the report).
- The smallest diff that does the task. Nothing added "just in case"; subtract before adding.
- Only what the task names is written. A defect outside the task is fixed in its own commit when it is small, otherwise it is
  reported with the fix that is proposed.
- Nothing personal in a file that ships: no names, home paths, addresses or private dates.
- "Done" comes with the check that supports it and its exit code. A check that could not run is reported as not run, never as
  green.
- Everything is committed at hand-in, with the trailers the brief asks for.

## Code quality

Scored on the diff.

- The change is the smallest one that does the task, in the place where the code already lives; the data shape was settled
  before the code that uses it.
- No dead code, no narrating comments, no names or branches nobody uses. The one comment that stays is the one recording a test's
  negative control (its failure message).
- Test-first craft, scored only where the task carries a test: the reproducing test was committed before the fix and run, and the
  failure it printed is the one the task predicted. A test whose expected values were edited to get a pass is a 0 for this
  criterion. Where the task carries no test, this criterion is `no score`.
- A test fixes what the code does, not how: it does not break when the code is refactored without changing behaviour. A change that
  needed two edits to the same test to pass is looked at: the first failure's cause must have been understood, not only silenced.
- Failure paths: an input that cannot be handled fails loudly, with a message that says what to do instead.

Scale: 9 to 10, nothing to remove and nothing missing; 6 to 8, correct with a little excess or one weak spot; 3 to 5, correct but
over-built, or a test that would not have caught the defect; 0 to 2, wrong, or it breaks something that worked.

## Speed

Scored on the transcript.

- The number of steps taken to reach the first failing test and to reach the green one, against what the task needed.
- No repeated reads of the same file, no waiting on a process that was not needed, no checks beyond the ones the brief lists
  (the project's own checks run later, on the merged commit).
- After two failed fixes of the same problem, the session attacked the premise (what it assumed) instead of trying a third
  variation of the same fix.
- Independent commands were run together.

Scale: 9 to 10, no wasted step; 6 to 8, a few redundant calls; 3 to 5, a loop or a long detour that cost a large part of the
session; 0 to 2, most of the session was wasted. Report the tokens and the number of tool calls beside the score, as figures, and
do not let them replace the judgement.

## Organisation

Scored on the transcript and on what was handed in.

- The session started from the brief and the base check, wrote only in the files the task lists, and stayed in its own worktree
  and scratch folder.
- Commits are small, each does one thing, and each carries the trailers the brief asks for.
- What the session started it cleaned up (servers, temporary files); nothing of it is left uncommitted or in the project outside
  the scratch folder.
- The report has the shape the brief asks for and every field is true: the commits listed exist, the red message is quoted from a
  run, what could not be run is listed.
- A question, where the task could not be done, offers two or three concrete options and a recommendation, instead of a vague
  ask.

Scale: 9 to 10, nothing out of place; 6 to 8, one slip (a missing trailer, a field left empty); 3 to 5, several slips or a
report that does not match the work; 0 to 2, work outside the scope, lost work or a false report.

## Task done

Scored on the result, with the acceptance and the verify commands of the task as the measure.

- Every acceptance line of the task is met, and the session shows it with the command that proves it and its exit code, not only
  by saying so.
- The behaviour the task asked for works in the case the task describes, and nothing that worked before is broken (the diff
  touches no behaviour the task did not name).
- A small defect found on the way is handled as the rules above say: fixed in its own commit, or reported with the fix.
- Where the session could not finish, it said so and why, instead of reporting "done".

Scale: 9 to 10, all acceptance lines met and shown; 6 to 8, met but one is shown only by assertion; 3 to 5, one acceptance line
missed; 0 to 2, the task is not done or is reported done when it is not. When the task's acceptance is not available to the
judge, this dimension is `no score`.
