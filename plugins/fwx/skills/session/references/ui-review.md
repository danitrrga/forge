<!-- referent: none, own text: no source reviews a UI walk's fixes one by one with the owner; the flow is the tree's review node and the walk's plan -->
# Reviewing the fixes of a UI walk

Step 8 of `SKILL.md` sends you here when the part had a UI walk. You never wait on the page and nothing he presses on it runs anything: a click is too weak a link to revert a change, and a rejection is worth its reason.

1. `fwx walk review-page --run <run> --fixed <file>` builds an item per fix (before, after, finding) and per `CONTRADICTED` finding left unfixed; `python3 <paths.verdict> verdict <review dir>` opens the page for him. Say in one line that it is ready and end your turn. With no `paths.verdict`, number the items in the chat, each screenshot opened first with `fwx open <file>`.
2. He pastes the text of `Copy answers`. Save it with `mktemp`, run `fwx walk review-answers --run <run> <file>`, remove it. It prints `{accepted, redo, not_defect, contradicted_wanted, open, stale}`: `redo` is "the fix does not work, fix it again", `not_defect` is "this is not a defect", each a list of `{id, note}`. Ask for the reason of every id in `open`; never guess it.
3. Give each note word for word to the `decisions` agent, `source` starting `ui-walk review`. `not_defect`: `support` `approved`, so the next walk treats the same finding as `CONTRADICTED`. `redo`: the row says the fix was rejected and why, without `approved`, because the design stands.
4. With any rejection, stop and ask before touching anything: for each rejected fix one line with what reverting undoes (its commit) and "revert it?", and for each `redo` also "another fix round?".
5. Run only what his words ask for. A revert: `fwx rounds <part> --reset "<his note>"`, stage `executing` with `part <N> corrections`, `fwx wave prepare ... --revert <ids he named>`, `fwx:execute`, stage `reviewing`, back to step 8. A fix round without revert is the same without `--revert`. A `CONTRADICTED` finding he wants applied is a change of intention: step 7.

With no rejection, return to step 8.
