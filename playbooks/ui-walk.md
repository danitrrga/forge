# UI walk
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/visual-parity.md @36885ea (the baseline is the spec and a run is not allowed to edit it; the anti-shortcut clauses) -->
<!-- Differs from the referent: it demands a zero pixel difference on one migrated component; here agents explore a whole screen and a finding is a judgement of the owner's approved design, so a difference from the baseline is reported for the owner to decide, not failed. -->

Version: 1

This playbook says what each node of the UI-walk stretch does, who does it and where it leads. The `ui-walk` workflow (`/fwx:ui-walk`) runs the walk; the orchestrator of the session reads this to fix, re-check and show the owner what the walk found.

## Rules of the stretch

- The walk touches only the local app, seeded with demo data and its demo account, and never a real account. Enforced by `fwx walk up`, which refuses a URL that is not local, and by `fwx walk ab`, which refuses `connect`, `--cdp`, `--profile`, `--headed` and `auth` and checks each URL a walker opens.
- A walk that does not find its planted fault does not count. `fwx walk arm-control` plants one on a screen no walker is told about, a judge reads whether it was found, and the workflow returns `control.found`; `false` or `null` says first that the run proves nothing. Guideline: the session reads that field before it trusts an empty result.
- The baseline is the approved demo and the rows of `decisions.tsv`. A walker or verifier never edits them or the planted control to make a finding go away; a finding that contradicts the baseline is marked `CONTRADICTED`, is not fixed and goes to the owner's review of the part.
- At the end no browser is left running. `fwx walk down` closes the walk's browsers and app in a `finally`, counts the processes it looked at and exits 1 if one is left; the workflow ends `failed` then.
- The walk finds and the session fixes: a fix is `fwx wave prepare --fix <fix.json>` followed by `/fwx:execute`, one commit per finding, and one `fix.json` run spends one round, however many findings it holds (`fwx wave fix-round` at n_C8 spends it).

## Nodes

### n_C11 · Does the part touch UI?
- **Who:** script fwx wave prepare
- **Stage:** reviewing
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The part touches UI when one of its tasks has `ui: true` in the plan, which the planner sets by the nature of the change and not by the files it edits. `fwx wave prepare` prints the flag of every task.
- **Exits:**
  - to n_C12: yes
  - to p_REPORT: no

### n_C12 · UI walk: agents tour the app with seeded data; do they find anything?
- **Who:** agent ui-walker, ui-verifier
- **Stage:** ui-walk
- **Writes:** fix.json, contradicted.json
- **Invokes:** workflow ui-walk
- **Does:** `fwx walk up` starts the app; the ui-verifier lists the screens the part changed; for each one a `breaker` tries to break it and a `critic` judges it as a designer, both through `fwx walk ab`; a verifier drops what does not reproduce, and `fwx walk findings` writes the confirmed and plausible ones to `fix.json` and the contradicted ones to `contradicted.json`. After the fixes the workflow runs again with `recheck` and only the verifiers, each finding with its screenshot after the fix.
- **Exits:**
  - to p_REPORT: nothing more to fix
  - loop n_C8: findings: fixes, one commit each

### p_REJ · A rejected fix is reverted and recorded
- **Who:** agent decisions
- **Stage:** phase-review
- **Writes:** nothing
- **Invokes:** command fwx walk review-answers
- **Does:** In the review of the part the owner accepts or rejects each fix on the review page; `fwx walk review-answers` reads the answers. Each rejected fix is reverted with `fwx wave prepare --revert` and `/fwx:execute`, and the `decisions` agent adds a row to `decisions.tsv` keeping the screen as it was approved, so that the next walk reads it as baseline and does not propose the fix again.
- **Exits:** none
