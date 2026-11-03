# Principles
<!-- referent: pstack plugins/pstack/skills/correct/SKILL.md @36885ea (the ladder of layers and the rule table; here reordered to this framework's four layers) -->
<!-- referent: pstack plugins/pstack/skills/principle-encode-lessons-in-structure/SKILL.md @36885ea -->
<!-- referent: EveryInc/compound-engineering-plugin skills/ce-plan/references/structure.md @3449230 (rule 5, the sentence on risk) -->

These principles sit above the writing guide for agent text. They say where a fix goes and which rules hold for the whole system. Each rule carries the incident or source behind it and what enforces it. A rule that nothing enforces says so and is a guideline.

## Where a fix goes

Put each fix at the strongest layer that works. The layers, strongest first, are the four values of the `layer` field of a weekly-improvement proposal, in this order:

1. **`code`.** Make the mistake impossible: one owner for each piece of state, one supported way for each task, a generated list instead of hand-copied ones, the old way deleted when an agent would copy it.
2. **`check`.** If the mistake can still be written, a lint, test or CI check fails on it, and its message names what to use instead: the failure message is the prompt. When the pattern is already widespread, the check fails only on a change that adds more. A hook that denies a tool call belongs here last, for what must be stopped before the change exists; a CI check covers every contributor, a hook only the agent.
3. **`prose`.** Only for judgment. pstack: "Nothing fails when an agent skips them."
4. **`skill`.** Last, and only when the mistake has happened twice and no layer above covers it. pstack: "A class counts once it has happened twice."

The order is the owner's, and pstack's `correct` skill writes the same ladder. A proposal at `check`, `prose` or `skill` names each stronger layer and why it did not work. A rule is deleted once its mistake can no longer happen.

## Rules of the system

1. **A rule without exceptions names what enforces it** (`enforced-by:` a script, permission, hook or lint). With no enforcer it is a guideline and is written as one.
   Source: pstack, "If the rule was already there and nothing enforces it, that's a repeat"; the Claude Code best-practices guide says a line that cannot have exceptions "belongs in a hook". Guideline: the review of each new text checks it.
2. **A check is seen to fail before it is trusted.** Looking at zero things is a failure. A check that could not run prints `NOT RUN, NOT ARMED` and is neither pass nor fail. A skipped, neutral or cancelled result from an outside check is not green.
   Incident: CodeRabbit reports success when it skips a review, and a CI job that times out ends as cancelled, not failed. Guideline: each new check's commit message records the failing run.
3. **Each thing is said in one place and the rest point to it.** Decisions and contracts have one home; a plan cites it and does not copy it.
   Source: pstack's plan playbook keeps rebase steps out of the plan and points to the playbook. Guideline.
4. **Who checks is not who made it, and may find nothing.** A reviewer starts with a fresh context, does not see the author's reasoning, and has no quota of findings.
   Incident: in marshal's demo the agent reported itself confident right after its own visual check had failed. Anthropic: "A reviewer that's asked to find problems will always find something." Guideline.
5. **A risk is a claim to judge, not something to build.** A critic's objection is checked against the code before the plan changes; a guard, retry or mode nobody asked for is built only when leaving it out causes harm nobody would catch in time, or adding it later would be expensive.
   Source: Every, "Risk has no natural limit: any design has one more way to fail." Guideline.
6. **What the system can fix alone, it fixes.** The owner receives only what needs judgment.
   Source: the owner's decision that a merge reaches him only when one of the merge rules names its case. Enforced by: `fwx decide` and its rule file.
7. **What always loads costs the most: delete before adding.** Add a rule after the model has stumbled on the same thing repeatedly, and prune by ablation: remove a rule and see whether anything gets worse.
   Source: the creator of Claude Code advises deleting CLAUDE.md, skills and hooks every six months and adding back only what the model keeps missing; a study of repository context files (arXiv 2602.11988) found they tend to lower task success and raise cost by over 20%. The owner's Musk-style pass (question, delete, simplify, speed up, automate) runs in that order. Guideline.
8. **Success is silent; only failure speaks.** A passing check prints nothing an agent must read.
   Source: HumanLayer, "Skill issue: harness engineering for coding agents": "success is silent, and only failures produce verbose output." Guideline.
9. **State lives on disk and each file has one writer.**
   Source: a concurrent writer must not split a row. Enforced by: `state.append_audit`, the one writer of `audit.tsv`, which appends each row in a single write.
10. **Reuse what exists before building it.** Before planning a part, search the repository, its docs and its archive.
    Incident: a part was planned from scratch while a design for it already sat in the docs. Guideline.
11. **Every agent starts from one shared base context.** Once the owner has stated the problem, each agent spawned starts from the same base context, polished once and aligned with the task and the project: what the codebase holds, what the owner wants and the parts of the machinery. Its prompt adds only its own part, and agents do not each read the same document.
    Source: the owner's instruction that all agents work the same way. Guideline until its mechanism exists: how Claude Code can hand a spawned agent a ready context is still being researched.
