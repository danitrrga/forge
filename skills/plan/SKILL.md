---
name: plan
description: Launches a fresh planner agent on a finished discuss, checks the plan it writes and returns the one-line status. Use once the phase is in its planning stage, after the pre-mortem, and again to replan.
user-invocable: false
---
<!-- referent: pstack plugins/pstack/skills/thermos/SKILL.md @36885ea -->
<!-- Differs from the referent: one agent, run in the foreground because the check needs its file; the agent reads its own brief, so the brief never enters this conversation; the model comes from the fwx configuration; the plan is checked by script and its errors go back to the agent once. -->

You run the planning step of one phase and hand back its status. The session reads the plan the owner sees, writes the stages and talks with the owner; you do none of these, and you never open `plan.md`, so it stays out of this conversation.

You are given the phase folder, the language of the conversation, and whether anyone can answer (`--unattended` when nobody can; then write English).

1. Run `fwx plan brief <dir> plan --head`. It prints `{agent, model, round}`. On exit 1 the phase is not ready (no `planning` stage row, no `context.md`, or no `premortem.md` after a pre-mortem): return its message and stop.
2. Launch `agent` as the subagent type given, in the foreground because step 3 needs the file it writes, with exactly that `model` (the owner chose it for this step in the fwx configuration, so it holds over any default of yours), and the prompt "Run `fwx plan brief <dir> plan` and follow it." plus `--unattended` if it applies, "Write in <language>." and "The template of `plan.md` is ${CLAUDE_PLUGIN_ROOT}/templates/phase/plan.md." Every path in the brief is absolute, so the agent needs nothing else from you. If the launch fails or the agent returns an error, launch it once more the same way.
3. Run `fwx plan check <dir>`. On exit 1 with `plan.md: file: missing` among the errors the agent left no plan: launch it once more as in step 2 and run the check again. On any other exit 1, send its output to the same agent with SendMessage, once, saying these are the errors to fix before it replies as before.
4. Run `fwx plan status <dir> plan`, with `--unattended` if it applies.
5. Reply with what the planner returned and, as your last line, the line `fwx plan status` printed, unchanged. A `failed` status is returned as it is, with its reason.
