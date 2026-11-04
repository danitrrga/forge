---
name: pre-mortem
description: Launches a fresh pre-mortem agent on a settled discuss and returns the one-line status of its result. Use once the phase is in its premortem stage, before the plan.
user-invocable: false
---
<!-- referent: pstack plugins/pstack/skills/thermos/SKILL.md @36885ea -->
<!-- Differs from the referent: one agent, not two, and in the foreground because the status needs its file; the agent reads its own brief, so the brief never enters this conversation; the model comes from the fwx configuration. -->

You run the pre-mortem of one phase and hand back its status. The session writes the stages and talks with the owner; you do neither, and you never open `premortem.md`, so it stays out of this conversation.

You are given the phase folder, the language of the conversation, and whether anyone can answer (`--unattended` when nobody can; then English).

1. Run `fwx plan brief <dir> premortem --head`. It prints `{agent, model, round}`. On exit 1 the phase is not ready (no `premortem` stage row, no `context.md`) and on exit 2 the folder or configuration cannot be used: return the message and stop.
2. Launch the `Agent` tool with that `agent` as `subagent_type` and that `model`, unchanged: the owner set the model for this size of work, and a default from elsewhere in the session does not replace it. The prompt is "Run `fwx plan brief <dir> premortem` and follow it." with `--unattended` added if it applies, then "Write in <language>." A launch returns at once: wait for the agent's completion notice before step 3.
3. Run `fwx plan status <dir> premortem`, with `--unattended` if it applies. On `failed`, launch the agent once more the same way and run the status again.
4. End your reply with the line step 3 printed, copied as it is and with nothing after it, because the session reads that line.
