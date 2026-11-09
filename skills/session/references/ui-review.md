<!-- referent: none, own text: no source reviews a UI walk's fixes one by one with the owner; the flow is the tree's review node and the walk's plan -->
# Reviewing the fixes of a UI walk

Step 8 of `SKILL.md` sends you here when the part had a UI walk. Show every fix of the walk, one item each with its before, its after and the finding, plus each `CONTRADICTED` finding that was left unfixed. Run `fwx walk review-page --run <run> --fixed <file>`, serve the page with `python3 <paths.verdict> verdict <review dir> --serve`, wait with `verdict wait` in the background and read the answers with `fwx walk review-answers`. With no `paths.verdict`, give a numbered list in the chat with the `xdg-open` lines of the screenshots and images pasted before it; he answers by number.

Each rejection goes to the `decisions` agent: `support` `approved` (the owner approved the earlier design, so the walk must not undo it, even though he rejects the fix), his note as `why`, `source` starting `ui-walk review`. The next walk then treats the same finding as `CONTRADICTED` and does not propose it again.

Then, for the rejected ones: `fwx rounds <part> --reset "<his note>"` (the tree restarts the attempts on a rejection), write stage `executing` with `part <N> corrections`, run `fwx wave prepare ... --revert <rejected ids>`, launch `fwx:execute`, write stage `reviewing`, and go back to step 8. A `CONTRADICTED` finding he wants applied is a change of intention: step 7.
