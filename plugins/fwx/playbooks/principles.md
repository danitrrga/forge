# Principles
<!-- referent: pstack plugins/pstack/skills/correct/SKILL.md @36885ea (the ladder of layers and the rule table; here reordered to this framework's four layers) -->
<!-- referent: pstack plugins/pstack/skills/principle-encode-lessons-in-structure/SKILL.md @36885ea -->
<!-- referent: EveryInc/compound-engineering-plugin skills/ce-plan/references/structure.md @3449230 (rule 5, the sentence on risk) -->

These principles sit above the writing guide for agent text. They say where a fix goes and which rules hold for the whole system. Each rule carries the incident or source behind it and what enforces it.

## Where a fix goes

Put each fix at the strongest layer that works. The layers, strongest first, are the four values of the `layer` field of a weekly-improvement proposal:

1. **`code`.** Make the mistake impossible: one owner for each piece of state, one supported way for each task, a generated list instead of hand-copied ones, the old way deleted when an agent would copy it.
2. **`check`.** If the mistake can still be written, a lint, test or CI check fails on it, and its message names what to use instead: the failure message is the prompt. When the pattern is already widespread, the check fails only on a change that adds more. A hook that denies a tool call belongs here last, for what must be stopped before the change exists; a CI check covers every contributor, a hook only the agent.
3. **`prose`.** Only for judgment. pstack: "Nothing fails when an agent skips them."
4. **`skill`.** Last, and only when the mistake has happened twice and no layer above covers it. pstack: "A class counts once it has happened twice."

The order is the owner's. A proposal at `check`, `prose` or `skill` names each stronger layer and why it did not work. A rule is deleted once its mistake can no longer happen. Guideline: the proposal reviewer lowers each proposal to its highest layer.

## Rules of the system

1. **A rule without exceptions names what enforces it** (`enforced-by:` a script, permission, hook or lint). With no enforcer it is a guideline and is written as one.
   Source: pstack, "If the rule was already there and nothing enforces it, that's a repeat". Guideline: the review of each new text checks it.
2. **A check is seen to fail before it is trusted.** Looking at zero things is a failure. A check that could not run prints `NOT RUN, NOT ARMED` and is neither pass nor fail. A skipped, neutral or cancelled result from an outside check is not green.
   Incident: CodeRabbit reports success when it skips a review, and a CI job that times out ends as cancelled, not failed. Guideline: each new check's commit message records the failing run.
3. **Each thing is said in one place and the rest point to it.** pstack's plan playbook points to the rebase playbook instead of copying its steps; see writing guide principle 2. Guideline.
4. **Who checks is not who made it, and may find nothing.** In marshal's demo the agent reported itself confident right after its own visual check had failed; see writing guide principle 12. Guideline.
5. **A risk is a claim to judge, not something to build.** Every: "Risk has no natural limit: any design has one more way to fail." A critic's objection is checked against the code before the plan changes; see writing guide principle 5. Guideline.
6. **What the system can fix alone, it fixes.** The owner receives only what needs judgment. Enforced by: `fwx decide` and its rule file.
7. **What always loads costs the most: delete before adding.** A study of repository context files (arXiv 2602.11988) found they tend to lower task success and raise cost by over 20%; see writing guide principle 24. The five-step improvement pass (question, delete, simplify, accelerate, automate) runs in that order. Guideline.
8. **Success is silent; only failure speaks.** A passing check prints nothing an agent must read.
   Source: HumanLayer, "Skill issue: harness engineering for coding agents": "success is silent, and only failures produce verbose output." Guideline.
9. **State lives on disk and each file has one writer.** A concurrent writer must not split a row. Enforced for `audit.tsv` by `state.append_audit`, which appends each row in a single write; otherwise a guideline.
10. **Reuse what exists before building it.** Before planning a part, search the repository, its docs and its archive.
    Incident: a part was planned from scratch while a design for it already sat in the docs. Guideline.
11. **Every agent starts from one shared base context.** Once the owner has stated the problem, each agent spawned starts from the same base context, polished once and aligned with the task and the project: what the codebase holds, what the owner wants and the parts of the machinery. Its prompt adds only its own part, and agents do not each read the same document.
    Source: the owner's instruction that all agents work the same way. Guideline until its mechanism exists: how Claude Code can hand a spawned agent a ready context is still being researched.
12. **Agents own the result, not the brief.** An agent owns the code it touches and the codebase around it: its quality, its speed, how it works with other software and technologies, how it treats the people who use it, and how tidy the repository stays. Nothing an agent sees is left as a mention. A defect it sees is fixed in its own commit when the fix is small and no task running beside it lists the file; otherwise it is an `outside` item with the fix proposed, `{where: path:line, what, fix, size: small|large, fixed: <commit>|null}`. A reviewer reads the connected code too, and a defect nearby is an `outside` item, never dismissed as not introduced by the diff. Planner and pre-mortem count the other software a result touches and the people who use it among the success criteria. The coordination limits (no rebase, push or merge, nothing written in `.fwx/`, its own worktree, clean up what it started) protect parallel work and say nothing about scope. A one-use document (a brief, a report, scratch) lives in its run's or job's own folder, never in a general folder of the project; a superseded version of a living file is deleted, because git holds the history; a run's folder goes when its work closes.
    Source, the owner's words: "Agents have full responsibility on the code that they're working in and the entire code base"; "you're responsible of everything that software it's supposed to be... Also like how it interacts with people"; "temporary and only one use docs should not be in like the general folders... we only want to keep the latest versions... it's growing a lot our code base... you have to be responsible for this as well".
    Enforced by: `workflows/execute.js`, which rejects a report whose `outside` items lack the shape (the executor is told why and writes it again), fails an executor whose branch changed a file that a task beside it lists or that another executor of the wave changed first (read from `git diff`, not from its report), and turns every item left unfixed into a Linear issue through `fwx linear` (one that cannot become one stays in `details.outside` and goes to the part report's Outside section). The tidiness part is a guideline until `fwx verify`'s one-use file check (PR feat/fwx-verify-one-use-files) lands.
13. **Move fast; speed never skips the proof.** Source, the owner's words: "We have to move fast". Do the agreed next step and report after, drive the pace of the session, run independent work in parallel up to the cap, and cut the ceremony that protects nothing (the test: if the step goes, does a check or a decision go with it). The check that proves the work is never what is cut. Enforced for the parallel work by `args.cap` of `fwx wave new` (`limits.default_cap`, `limits.per_project.executor`); the rest is a guideline.
