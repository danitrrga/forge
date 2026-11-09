# UI walk
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/visual-parity.md @36885ea (the baseline is the spec and a run is not allowed to edit it; the anti-shortcut clauses) -->
<!-- Differs from the referent: it demands a zero pixel difference on one migrated component; here agents explore a whole screen and a finding is a judgement of the owner's approved design, so a difference from the baseline is reported for the owner to decide, not failed. Written from `workflows/ui-walk.js` and `lib/fwx/commands/walk.py`: where this text and the code differ, the code rules. -->

Version: 2

This playbook says what each node of the UI-walk stretch does, who does it and where it leads. The `ui-walk` workflow (`/fwx:ui-walk`) runs the walk and returns `done` or `failed`, never `needs-owner` or `back-to-discuss`; the orchestrator of the session reads this to fix, re-check and show the owner what the walk found.

## What changed from version 1

- n_C12 follows `workflows/ui-walk.js`: the walkers run within the quota `fwx walk up` returns, a small `ui-verifier` judges the control, the close runs in a `finally`, and `recheck` is verifiers only.
- The control rule now says what `control.found` of `false` or `null` does to the result: the reason starts with `The run does not count`.
- Since the owner's answers on version 1: the walk also covers the screens that use what changed, and the `decisions` agent is the one writer of the row that keeps a rejected fix's screen as approved.
- No node or arrow is added, removed or retitled.

## Rules of the stretch

- The walk touches only the local app, seeded with demo data and its demo account, and never a real account. Enforced by `fwx walk up`, which refuses a URL that is not local, and by `fwx walk ab`, which refuses `connect`, `--cdp`, `--profile`, `--headed` and `auth` and checks each URL a walker opens.
- A walk that does not find its planted fault does not count. `fwx walk arm-control` plants one on the first screen of the first tramo, with no walker told about it, a small `ui-verifier` judges whether any finding describes it, and the workflow returns `control.found`; `false` or `null` (the control was not planted, its tramo's critic returned nothing, or the judge could not read) says first in `reason`, which starts with `The run does not count`, that the run proves nothing. Guideline: the session reads that field before it trusts an empty result.
- The baseline is the approved demo and the rows of `decisions.tsv`. A walker or verifier never edits them or the planted control to make a finding go away; a finding that contradicts the baseline is marked `CONTRADICTED`, is not fixed and goes to the owner's review of the part.
- The machine holds only so many walkers: `fwx walk up` returns the quota, the workflow runs no more walkers than that at once, and logs which ones wait in the queue.
- At the end no browser is left running. `fwx walk down` closes the walk's browsers and app in a `finally`, counts the processes it looked at and exits 1 if one is left; the workflow ends `failed` then. A walker or verifier that returns nothing twice is a gap in `details.gaps` and also ends the run `failed`, after the verdicts that exist are collected.
- The walk finds and the session fixes: a fix is `fwx wave prepare --fix <fix.json>` followed by `/fwx:execute`, one commit per finding. The run spends a round only when it fails, and then one per failure however many findings it holds (`fwx wave fix-round` at n_C8).

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
- **Does:** `fwx walk up` starts the app and returns the quota of walkers; the ui-verifier lists the screens the part changed and the screens that use what changed (a screen that imports a changed component or token), grouped in tramos, so that a shared change is walked where it lands; only the scope grows, and a difference from the baseline stays a finding for the owner to judge, not a failure. After `fwx walk arm-control` plants the fault, each tramo gets a `breaker` that tries to break it and a `critic` that judges it as a designer (and a Firefox critic when the plan asks for Firefox), through `fwx walk ab`, within the quota; a ui-verifier per tramo drops what does not reproduce and saves `verified-<tramo>.json`, and a small one judges whether the control was found. In a `finally`, `fwx walk findings` writes the confirmed and plausible findings to `fix.json` and the contradicted ones to `contradicted.json`, `fwx screenshot` captures the walked screens and `fwx walk down` closes everything. After the fixes the workflow runs again with `recheck` and only the verifiers, each finding with its screenshot after the fix; it saves `rechecked-<tramo>.json` and leaves `fix.json` as it is.
- **Exits:**
  - to p_REPORT: nothing more to fix
  - loop n_C8: findings: fixes, one commit each

### p_REJ · A rejected fix is reverted and recorded
- **Who:** agent decisions
- **Stage:** phase-review
- **Writes:** nothing
- **Invokes:** command fwx walk review-answers
- **Does:** In the review of the part the owner accepts or rejects each fix on the review page; `fwx walk review-answers` reads the answers. Each rejected fix is reverted with `fwx wave prepare --revert` and `/fwx:execute`, and the `decisions` agent, the one writer of `decisions.tsv` (its file is listed by the discuss block of `session.md`, so this block lists none), adds a row there keeping the screen as it was approved, so that the next walk reads it as baseline and does not propose the fix again.
- **Exits:** none
