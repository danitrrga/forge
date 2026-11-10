---
name: post-mortem
description: Launches a fresh post-mortem agent on a finished plan and returns the one-line status of its result. Use once the phase is in its postmortem stage, or when a job comes back (structural BASE..BRANCH).
user-invocable: false
---
<!-- referent: pstack plugins/pstack/skills/thermos/SKILL.md @36885ea -->
<!-- Differs from the referent: one agent, not two, and in the foreground because the status needs its file; the agent reads its own brief, so the brief never enters this conversation; the model comes from the fwx configuration; a job that came back adds `--diff`. -->

You run the post-mortem of one phase and hand back its status. The session writes the stages and talks with the owner; you do neither, and you never open `postmortem.md`, so it stays out of this conversation.

You are given the phase folder, the language of the conversation, whether anyone can answer (`--unattended` when nobody can; then English) and, when a job came back, `structural BASE..BRANCH`.

1. Run `fwx plan brief <dir> postmortem --head`. It prints `{agent, model, round}`. On exit 1 the phase is not ready (no `postmortem` stage row, no `plan.md`, no `context.md`) and on exit 2 the folder or configuration cannot be used: return the message and stop.
2. Launch the `Agent` tool with that `agent` as `subagent_type` and that `model`, unchanged: the owner set the model for this size of work, and a default from elsewhere in the session does not replace it. The prompt is "Run `fwx plan brief <dir> postmortem` and follow it." with `--unattended` and `--diff BASE..BRANCH` added if they apply, then "Write in <language>." A launch returns at once: wait for the agent's completion notice before step 3.
3. Run `fwx plan status <dir> postmortem`, with `--unattended` if it applies. On `failed`, launch the agent once more the same way and run the status again.
4. End your reply with the line step 3 printed, copied as it is and with nothing after it, because the session reads that line.
