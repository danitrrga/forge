<purpose>
<forge_free_form>
FORGE OVERRIDE, read before the rest of this file; where they conflict, this wins. A spike here is free-form and run by you, the main agent, in this conversation, so the owner can steer it.

1. Run every experiment yourself, in the conversation. Never spawn a subagent for an experiment, for research or for verification (`research`, `build_spikes`).
2. Gates are guidance, not stops. Never wait at one; propose and carry on unless the owner redirects.
   - `align`, and "Get Alignment and Execute" in `frontier_mode`: do not present the whole table and wait. Say in one or two sentences which experiment is next and start it.
   - `build_spikes` step g (the "Verification Required" checkpoint) and step j (the report): after each experiment give the result in plain words, what you saw and what it means. Then ask where to go next, one question, only when there is a real fork; otherwise state the next experiment and start it.
   - `build_spikes` step k (core assumption invalidated) is a real fork: ask the one question.
3. Do these when they help the experiment in front of you, not as a fixed sequence: `decompose` (including its risk ordering), `research` (a briefing, the approach table), and the forensic log layer of `build_spikes` step b.
4. Mandatory, because other GSD commands read it back:
   - Each spike's `README.md` with its frontmatter (`build_spikes` step e) and a final `verdict`. `/gsd-next` counts `verdict: PENDING` as unfinished work and `/gsd-spike --wrap-up` reads the frontmatter, so never leave a finished experiment PENDING.
   - The spike's row in `.planning/spikes/MANIFEST.md` with its Idea column, and the idea's Requirements as the owner states them (`create_manifest`, `build_spikes` step h). `--wrap-up`, `/gsd-discuss-phase` and `/gsd-new-project` read this file.
   - The commit (`build_spikes` step i; `update_conventions` is guidance, and its commit follows it when you do update `CONVENTIONS.md`) when `COMMIT_DOCS` is true.
</forge_free_form>
