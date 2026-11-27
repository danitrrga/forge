<!-- copied-from: pstack plugins/pstack/skills/poteto-mode/playbooks/session-pickup.md @36885ea (line 3, word for word) -->
<!-- referent: mattpocock/skills skills/engineering/wayfinder/SKILL.md @abeeaf9 (the map and its decision tickets; differs: the map is a milestone and the tickets are phases in `.fwx/`, not issues in a tracker); the rest is written here -->
# Re-entry

You own the resume point. Read the prior trail, don't redo it.

The phase is back in `discuss` (`bound.reentry`): a critique or its review sent it back, or the owner did not sign off on the UI walk. Make no phase and gather no context.

- Read the last `stage` row of the phase's `audit.tsv`: its detail says where the phase came back from and why.
- Read the `decisions.tsv` rows with `supersedes`: what was reopened.
- Your first check says what came back and why, then go on at step 4. At sign-off give the whole playback again and run `fwx:session <phase>`.

**Wayfinder mode: a topic too big for one session.** When the owner chooses to split, or gather context showed the topic does not fit one session, chart it as a map in `.fwx/`, with no Linear. The map is a milestone (`fwx milestone new`): its `milestone.md` holds the Destination (its Goal), Decisions so far, Not yet specified and Out of scope (its Out). Each decision still open is one decision ticket, a phase made with `fwx phase new <slug> --milestone <vN>` whose `context.md` says the question, what is known and what blocks it; each is settled in its own discuss session, never more than one per session. When a ticket settles, add one line with a pointer to its phase's `decisions.tsv` under Decisions so far, and turn what was Not yet specified into tickets as it becomes clear. Bind the session back to the current phase with `fwx session attach <phase_dir>`.
