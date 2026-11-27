<!-- referent: none, own text: no source has a one-screen report of this shape. The orchestrator fills it from `fwx wave --run <R> --json` and the last `evidence` row of `audit.tsv`; it is pasted to the owner after a part and is the pull request body at the close, so nothing is saved. At most 40 lines filled. -->
# Report: <phase folder name>, <part N | all parts>

## Goal
<The problem this work solves, in one or two sentences, in the owner's words where they exist. Not the diff.>

## Done
<One line per part or task: what now works, in plain words. What the review found (`wave --run` `findings`) and what was checked (`criteria`, `gaps`), including the `findings.consider` ones not fixed.>

## Assumptions taken without asking
<Each choice you made yourself because one option was clearly better, one line: the choice and why. `None` otherwise.>

## Outside
<Each defect seen outside the work (`wave --run` `outside` and `findings.outside`): where, what, the fix, and the Linear key of its `filed:` entry in step 5's stage row, else `none filed`. `None` otherwise.>

## Evidence
<Commit `<sha>`, the command and its exit code, copied from the last `evidence` row of `audit.tsv`. A walk that did not finish is said here, not left out.>

## PR
<The pull request URL. Before the close: `not opened yet`. With no GitHub `origin`: `git diff <base>..<head>`.>
