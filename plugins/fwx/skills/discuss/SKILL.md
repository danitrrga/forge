---
name: discuss
description: Start a work session with the owner, or continue one. Use whenever the owner opens a conversation about work on the project.
argument-hint: "[target: a phase folder, to re-enter it]"
---
<!-- referent: EveryInc/compound-engineering-plugin skills/ce-brainstorm/SKILL.md @3449230705a5 and mattpocock/skills skills/productivity/grilling/SKILL.md @4ae2317ddb22; differs: each step loads its reference where it needs it and the skill ends in a handoff to `fwx:session`; the owner decides without recommendations; agents are launched in the background and their files are read by other agents; the tree's first lane is the order of the steps -->

Rules. Only the owner and you speak. Launch every agent in the background, `model` exactly as the start JSON gives it, with the absolute paths of the phase's `context.md` and `decisions.tsv`. A launch returns at once: read its result only after its completion notice. You write neither `decisions.tsv` nor `research/`. A dead agent is not "no findings": say so, launch it once more.

Context. Read no long file or investigation yourself: a `researcher` returns summary and path. Its `## Unproven` lines are not findings: say them as not checked. Run `fwx budget --json` now and before each playback, heavy read or generation. Context high or `week_tight` true: delegate more, ask for shorter reports, offer to split a topic too big for one session. `unknown` is not zero; quota never stops you. After a compaction, redo the playback from `context.md`, `decisions.tsv` and the summaries.

1. **Start.** Run `fwx discuss --json`, with `--phase $ARGUMENTS` when a `target` phase path was given. Exit 1: say in one line the framework is off, go on as plain Claude. `bound.stage` after `discuss`: `fwx:session <bound.phase_dir>`, no conversation. `bound.reentry`: follow `${CLAUDE_PLUGIN_ROOT}/skills/discuss/references/reentry.md`. `bound.stage` null with a `phase_dir` is a discuss not yet frozen: continue it, no second phase. An `open_phases` entry with `stage` null: ask in round one whether the message continues it. Exit 2: give its one-line reason and stop.

2. **Gather context** before you classify the request. Read only: the code the message touches and `.fwx/` (`PROJECT.md`, `durable/`, `adr.tsv`); for UI work, also the identity and design documents and the component skill (the `.claude/skills/` one whose description says so). What the repo, the app or Linear can answer is looked up, never asked. No phase, no agent yet.

3. **What does the owner ask?** Unsure: ask in round one.
   - Work on the project: the subproject from the message and `subprojects` (unsure: ask, research waits). Then `fwx phase new <slug> [--subproject S]` and launch two or three `researcher` (`models.researcher.small`): code map, `.fwx/` state, for UI the design documents and component skill. Do not wait. First check: what you understood, the subproject and why, what waits in Linear (`waiting.groups` by age, each issue with its URL; "Linear: not checked (reason)" if NOT RUN).
   - Improve the system, or a new model: give `/fwx:improve`.
   - Trivial: only the owner calls a change trivial, by no threshold of yours; when it could be, offer "plain Claude, no workflow" in round one. Picked: one line, no phase; if it passes the closed list (step 9), give `/fwx:factory-issue`.
   - Continue: with no phase bound, `fwx:session`; for an issue the factory returned (a `needs-owner` or `factory-failed` one he picks), `fwx:session retake <KEY>`; a `factory-review` one, its URL only.

4. **Check** at the top of every reply to an owner message, a question too: up to three lines, about 50 words: what you understood; "Noted: ..." per decision; a bare "yes" read aloud ("I read your yes as b: ..."). His question gets an answer and no row. Under it, if needed, a numbered round per `${CLAUDE_PLUGIN_ROOT}/skills/discuss/references/rounds.md`, with no recommendation, only for his taste or direction or what is unclear.

5. **Record.** With decisions in the turn, launch `decisions` (`models.decisions.small`) with the phase folder, the decision and the exchange word for word between `<exchange>` tags. A lettered or verdict answer is `chosen` (a verdict's JSON is its `source`); a plain yes to what you noted, `approved`; what you decide unasked, `agent-assumption`, as is whether the work is UI by its nature. A row returned `unexamined`: raise it once next round, with the alternative and what each costs.

6. **Research.** A fact you can look up goes to a `researcher` without holding the round; a bigger investigation, after his yes, to one on `models.researcher.normal`.

7. **UI with demos.** For a bounded UI decision launch `demo` (`models.demo.normal`); when it returns, open the page for the owner the way the user's instructions say, say in one line it is ready and end the turn, never waiting on it. His pasted answer's pick and note go into `Approved UI` of `context.md`. No UI choice is closed in chat. Without `verdict_tool`, hand him each figure the same way; he answers by letter.

8. **Playback and sign-off.** When all is said, wait for every `decisions` to return, then give the playback per `${CLAUDE_PLUGIN_ROOT}/skills/discuss/references/playback.md`. He may correct, want more research, split into phases (`references/reentry.md`) or sign off; only that ends it.

9. **Demo in the app, and the closed list.** With UI and `verdict_command`, `demo` (`models.demo.normal`) runs it in the app; a UI change goes back to step 7. Then ask whether it is a bug or on the closed list of mechanical changes (`factory-issue`'s rule). Yes: give him `/fwx:factory-issue`; if he declines, or no: step 10.

10. **Freeze.** Rewrite `context.md` with the sections of `${CLAUDE_PLUGIN_ROOT}/templates/phase/context.md`. `Surfaces` lists `ui` when the work is UI by its nature (what a person sees or uses), not its file extension: a typo in a `.tsx` is not, a visible change in a `.ts` is. With `decisions.tsv` complete, run `fwx:session <phase>`, stage still `discuss`. On "cancel": `fwx phase remove <phase>`, reply `{status: done, reason: "cancelled", phase_dir}`.
