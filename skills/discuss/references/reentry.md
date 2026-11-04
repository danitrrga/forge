<!-- copied-from: pstack plugins/pstack/skills/poteto-mode/playbooks/session-pickup.md @36885ea (line 3, word for word) -->
<!-- referent: none, the rest is written here -->
# Re-entry

You own the resume point. Read the prior trail, don't redo it.

The phase is back in `discuss` (`bound.reentry`): a critique or its review sent it back, or the owner did not sign off on the UI walk. Make no phase and gather no context.

- Read the last `stage` row of the phase's `audit.tsv`: its detail says where the phase came back from and why.
- Read the `decisions.tsv` rows with `supersedes`: what was reopened.
- Your first check says what came back and why, then go on at step 4. At sign-off give the whole playback again and run `fwx:session <phase>`.

**Splitting into phases.** When the owner chooses to split, or gather context showed the topic does not fit one session: make the other phases with `fwx state new-phase`, write each one's `context.md` with what is known, and bind the session back to the current phase with `fwx state use <phase_dir>`.
