---
name: plan
description: Launches a fresh planner agent on a finished discuss, checks the plan it writes and returns the one-line status. Use once the phase is in its planning stage, after the pre-mortem, and again to replan.
user-invocable: false
---
<!-- referent: pstack plugins/pstack/skills/thermos/SKILL.md @36885ea -->
<!-- Differs from the referent: one agent, waited for; it reads its own brief; its model comes from the fwx configuration; a script checks the plan and its errors go back once. -->

You run the planning step of one phase and hand back its status. You never open `plan.md`, so it stays out of this conversation.

You are given the phase folder, the language of the conversation, and whether anyone can answer (`--unattended` when nobody can; then English).

1. Run `fwx plan brief <dir> plan --head`: it prints `{agent, model, round}`. On exit 1 (phase not ready) or 2 (folder or configuration unusable) return its message and stop.
2. Launch the `Agent` tool with that `agent` as `subagent_type` and exactly that `model`: the owner chose it in the fwx configuration, so it holds over any default of yours. The prompt is "Run `fwx plan brief <dir> plan` and follow it." with `--unattended` added if it applies, then "Write in <language>." A launch returns at once: wait for the agent's completion notice before step 3. If the launch fails or the agent returns an error, launch it once more the same way.
3. Run `fwx plan check <dir>`. On exit 1 with `plan.md: file: missing`, launch once more as in step 2 and check again. On any other exit 1, `SendMessage` its output to the same agent, once, as the errors to fix before it replies as before, and wait for its notice.
4. Run `fwx plan status <dir> plan`, with `--unattended` if it applies.
5. Reply with what the planner returned and, last, the line `fwx plan status` printed, unchanged; a `failed` status goes back with its reason.
