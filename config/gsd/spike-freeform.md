<purpose>
<forge_free_form>
FORGE OVERRIDE, read before the rest of this file; where they conflict, this wins. A spike here is free-form and run by you, the main agent, in this conversation, so the owner can steer it. It does not apply to `--wrap-up`; `--quick` still skips `decompose` and `align`.

1. Run every experiment yourself, in the conversation. Never spawn a subagent for an experiment, for research or for verification (`research`, `build_spikes`). The original never spawns one either; this is a safeguard.
2. The owner steers between turns, so a gate becomes a turn boundary, not a wait inside a turn.
   - `frontier_mode`, "Get Alignment and Execute": present the candidates in one short list, recommend one, and end your turn. The owner picks; do not start any.
   - `align`: give the table, or one or two sentences naming the next experiment.
   - After each experiment (`build_spikes` steps g and j), commit, then end your turn with the verdict in plain words and the proposed next experiment. Continue in the same turn only to finish the experiment in hand.
   - A real fork (`build_spikes` step k, an invalidated core assumption, is one) gets one AskUserQuestion, or plain text with `--text`.
3. Still in force: risk ordering (the riskiest question first), `load_prior_context` and `reground`. `decompose` (without presenting its table), `research` and the forensic log layer of `build_spikes` step b are for when they help the experiment in front of you, except `research`: do it whenever the spike touches an external library, API or service, and skip it for pure logic with no external dependencies.
4. Mandatory, because other GSD commands read it back:
   - Each spike's `README.md`, with all frontmatter fields (`build_spikes` step e, including `validates` as Given/When/Then and `type`, even when `decompose` is skipped) and its Investigation Trail and Results sections, which `--wrap-up` and `frontier_mode` read.
   - The `verdict`: VALIDATED, INVALIDATED, PARTIAL, WINNER (a comparison's best), PENDING or ABANDONED (dropped). Only a finished and verified experiment gets a final one. A verdict that needs the owner's own judgment (a UI he must feel) stays PENDING until he answers; say so in your turn. `/gsd-next` counts `verdict: PENDING` as unfinished work.
   - The spike's row in `.planning/spikes/MANIFEST.md` with its Idea column, its Verdict column equal to the README's, and the idea's Requirements as the owner states them (`create_manifest`, `build_spikes` step h). `--wrap-up`, `/gsd-discuss-phase` and `/gsd-new-project` read this file.
   - The commit (`build_spikes` step i) when `COMMIT_DOCS` is true. Only `setup_directory` sets it and `frontier_mode` skips that step, so resolve it there in every mode before committing.
5. `report` and `update_conventions` run only when the owner says the session is done; there is no other defined end.
</forge_free_form>
