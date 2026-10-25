<purpose>
<forge_free_form>
FORGE OVERRIDE, read before the rest of this file; where they conflict, this wins. A spike here is free-form and run by you, the main agent, in this conversation, so the owner can steer it. It does not apply to `--wrap-up`; `--quick` still skips `decompose` and `align`.

1. Run every experiment yourself, in the conversation. Never spawn a subagent for an experiment, for research or for verification (`research`, `build_spikes`). The original never spawns one either; this is a safeguard.
2. The owner steers between turns, so a gate becomes a turn boundary, not a wait inside a turn.
   - `frontier_mode`, "Get Alignment and Execute": present the candidates in one short list, each with its Given/When/Then and risk order, recommend one, and end your turn. The owner picks; do not start any. A picked spike gets its MANIFEST row and its README stub in the same step, so no row is left without a README.
   - `align`: give the table, or one or two sentences naming the next experiment.
   - End your turn after steps h and i of `build_spikes` (MANIFEST, commit), with the verdict in plain words, the proposed next experiment and how many remain. Continue in the same turn only to finish the experiment in hand. After the last planned experiment, or when the owner stops, offer `report` and `update_conventions`; they run only on his say-so.
   - A real fork (`build_spikes` step k, an invalidated core assumption, is one) gets one AskUserQuestion, or plain text with `--text`.
3. Still in force: `load_prior_context` and `reground`; name the prior spikes you reuse. Order by risk silently; do not present the decomposition table (`decompose`). Research whenever an external library, API or service is involved; skip it for pure logic with no external dependencies. The forensic log layer of `build_spikes` step b is for when it helps.
4. Mandatory, because other GSD commands read it back:
   - Each spike's `README.md`, with all frontmatter fields (`build_spikes` step e, including `validates` as Given/When/Then and `type`, even when `decompose` is skipped) and its Investigation Trail and Results sections, which `--wrap-up` and `frontier_mode` read.
   - The `verdict`: VALIDATED, INVALIDATED, PARTIAL (the winner of competing approaches is VALIDATED; WINNER is only a value of the report table) or PENDING. Only a finished and verified experiment gets a final one. A verdict that needs the owner's own judgment (a UI he must feel) stays PENDING until he answers: write the line literally as `verdict: PENDING`, unquoted (`/gsd-next` greps it), and say so in your turn. When he answers, update the README and the MANIFEST row and commit again.
   - The spike's row in `.planning/spikes/MANIFEST.md` with its Idea column, its Verdict column equal to the README's, and the idea's Requirements as the owner states them (`create_manifest`, `build_spikes` step h). `--wrap-up`, `/gsd-discuss-phase` and `/gsd-new-project` read this file.
   - The commit (`build_spikes` step i) when `COMMIT_DOCS` is true: before each commit, in every mode, run `setup_directory`'s `config-get commit_docs` line (the only place `COMMIT_DOCS` is set).
</forge_free_form>
