---
name: factory-issue
description: Sends work from a discuss, or from the conversation, to the factory as Linear issues, and only what passes the closed list. Use when the owner wants to hand the factory a bug or a mechanical change.
disable-model-invocation: true
---
<!-- referent: mattpocock/skills skills/engineering/to-tickets/SKILL.md @4ae2317ddb22; differs: the tickets are not sliced or ordered (one issue per task, no blocking edges), the closed list decides what may be offered before anything is drafted, and the issue is created only after the owner's own confirmation -->

The factory builds what you send with nobody watching. Offer only what the closed list lets through, and create nothing before the owner says yes.

1. Run `fwx discuss start --json`. Exit 1 means the framework is off here: say so and stop. Work from the phase in `bound.phase_dir` (its `context.md` and `decisions.tsv`), or from this conversation when none is bound. Note `factory_ui_bugs`.

2. **Check each task against the closed list before anything else.** It passes only if it is:
   - a change that fits a row of `${CLAUDE_PLUGIN_ROOT}/data/mechanical.tsv` and none of what that row's `not` column excludes;
   - a bug with a known reproduction and low risk (both, as the factory's intake checks);
   - a UI bug with a mechanical fix, when `factory_ui_bugs` is `true` and the owner has screenshots of it. That flag is the only switch (true once the project's image passed its checks): look at nothing else.

   The intake reads the same file: read it, do not copy its rows. Until it exists, only the second kind passes.
   What fails (a feature, a setting outside the list) is not offered. Tell the owner in plain words what does not pass and why, and that it stays in his session.

3. Write one issue per task when the owner decided to split the work. Each is a JSON object for `fwx linear create --template general`: `title`, `context`, `reproduce`, `expected`, `out_of_scope`, `evidence`, `origin`, and `"labels": ["factory"]`. Put the phase's `chosen` and `approved` decisions in `context` under "Decided by the owner". Each issue must stand alone for a reader who never saw this conversation. A UI bug carries its screenshot paths in `evidence` (without them it is not offered) and says in `origin` that the discuss marked it `ui`.

4. Show every issue to the owner in one message, in the form of the discuss playback (the problem, what gets built, call outs). Create only after his own yes in this conversation: a reviewer's approval, or a yes to something else, is not one.

5. Pipe it to `fwx linear create --template general` and print each identifier and its URL. If it stops part way it names the issues already made: tell the owner and stop there. When the work came from a phase, run `fwx state cancel <phase_dir>`: the issues now hold what was decided.

6. Reply `{status: done, reason: "sent to factory: <identifiers>"}`.
