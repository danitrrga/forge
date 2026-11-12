# UI walk
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/visual-parity.md @36885ea (the baseline is the spec and a run is not allowed to edit it; the anti-shortcut clauses) -->
<!-- Differs from the referent: it demands a zero pixel difference on one migrated component; here agents explore a whole screen and a finding is a judgement of the owner's approved design, so a difference from the baseline is reported for the owner to decide, not failed. Written from `workflows/ui-walk.js` and `lib/fwx/commands/walk.py`: where this text and the code differ, the code rules. -->

Version: 2

This playbook says what each node of the UI-walk stretch does, who does it and where it leads. The `ui-walk` workflow (`/fwx:ui-walk`) runs the walk and returns `done` or `failed`, never `needs-owner` or `back-to-discuss`; the orchestrator of the session reads this to fix, re-check and show the owner what the walk found.

## What changed from version 1

- n_C12 follows `workflows/ui-walk.js`: its order, the verdict files and `recheck` as verifiers only.
- The control and close rules say what the result carries: `control.found`, `reason`, `details.gaps`.
- From the owner's answers: the walk also covers the screens that use what changed, and the `decisions` agent is the one writer of the row that keeps a rejected fix's screen as approved.
- No node or arrow is added, removed or retitled.

## Rules of the stretch

- The walk touches only the local app, seeded with demo data and its demo account, and never a real account. Enforced by `fwx walk up`, which refuses a URL that is not local, and by `fwx walk ab`, which refuses `connect`, `--cdp`, `--profile`, `--headed` and `auth` and checks each URL a walker opens.
- A walk that does not find its planted fault does not count. `fwx walk arm-control` plants one on the first screen of the first tramo with no walker told about it, and a small `ui-verifier` judges whether a finding describes it. `arm-control` first reads the title's computed style and rendered box on that screen without and with the plant and refuses (`target not found`, `no visible change`) when a walker could not see the fault, that is when the box does not change by at least `FWX_WALK_CONTROL_MIN_BOX_PX` pixels (default 1): the control is then not planted and the run does not count. When `control.found` is `false` or `null` (the fault was not planted, that tramo's critic returned nothing, or the judge could not read), `reason` contains `The run does not count`; the session reads it before it trusts an empty result. Only the walkers' browsers carry the plant (`fwx walk ab` leaves it out of a verifier's session), and as a net the verified row the judge names (and the rows tied to it as duplicates) is moved from `verified-<tramo>.json` to `control-<tramo>.json` before `fwx walk findings` reads the files: the fixer never gets the planted fault.
- The baseline is the approved demo and the rows of `decisions.tsv`. A walker or verifier is asked never to edit them or the planted control to make a finding go away; nothing enforces it. A finding that contradicts the baseline is marked `CONTRADICTED`, is not fixed and goes to the owner's review of the part.
- No more walkers run at once than the quota `fwx walk up` returns; the rest queue and the workflow logs which. A job closes its own browser sessions before it frees its slot, so the quota bounds browsers and not only agents.
- At the end no browser is left running. `fwx walk down` closes the walk's browsers and app in a `finally`, counts the processes it looked at and exits 1 if one is left; the workflow ends `failed` then. A walker or verifier that returns nothing twice is a gap in `details.gaps` and also ends the run `failed`, after the verdicts that exist are collected; so does a `fwx walk findings` that fails (no `fix.json` was collected).
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
- **Writes:** fix.json, contradicted.json, control.json, coverage.md, down.json, verified-tramo.json, control-tramo.json, rechecked-tramo.json
- **Invokes:** workflow ui-walk
- **Does:** `fwx walk up` starts the app; the ui-verifier lists the screens the part changed and the screens that use what changed (a screen that imports a changed component or token) and groups them in tramos, a tramo being one to four screens used together, so that a shared change is walked where it lands; only the scope grows, and a difference from the baseline stays a finding for the owner to judge, not a failure. Each tramo gets a `breaker` that tries to break it and a `critic` that judges it as a designer (and a Firefox critic when the plan asks for Firefox), through `fwx walk ab`; a ui-verifier returns the verdicts of each tramo, the workflow saves them, and `fwx walk findings` keeps the confirmed and plausible ones in `fix.json` and the contradicted ones in `contradicted.json`, while `fwx screenshot` captures the walked screens. After the fixes the workflow runs again with `recheck`: only the verifiers, each finding with its screenshot after the fix, and `fix.json` stays as it is.
- **Exits:**
  - to p_REPORT: nothing more to fix
  - loop n_C8: findings: fixes, one commit each

### p_REJ · A rejected fix is reverted and recorded
- **Who:** agent decisions
- **Stage:** phase-review
- **Writes:** nothing
- **Invokes:** command fwx walk review-answers
- **Does:** In the review of the part the owner accepts or rejects each fix on the review page; `fwx walk review-answers` reads the answers he pasted: `accepted`, `redo` and `not_defect` (each with his note and the fix's commit), `contradicted_wanted`, and `open`, where a `redo` or `not_defect` with no note is also listed in `missing_note`. A rejected fix is reverted with `fwx wave prepare --revert` and `/fwx:execute` only when his words ask for it. For `not_defect`, the `decisions` agent, the one writer of `decisions.tsv` (its file is listed by the discuss block of `session.md`, so this block lists none), adds a row there keeping the screen as it was approved, so that the next walk reads it as baseline and does not propose the fix again. A `redo` records nothing: the screen is not approved as it is, so the finding stays open for another fix.
- **Exits:** none
