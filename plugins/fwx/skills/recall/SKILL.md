---
name: recall
description: "Reconstruct your recent working context from your own chat history, live state, and the shared record (user reports, prior fixes, incidents), then hand back a tight current-state brief. Use for 'recall my work on X', 'catch me up', 'what have I been working on', 'where did I leave off', before starting or resuming work."
disable-model-invocation: true
---
<!-- copied-from: cursor/plugins pstack/skills/recall/SKILL.md @b7b93c36be9b (word for word except the passages adapted here: the paragraph naming the two records and the one on transcripts, where the sources become this project's `.fwx/` documents, git and gh; step 1, where `session-pickup` reads `${CLAUDE_PLUGIN_ROOT}/skills/discuss/references/reentry.md` and the `automate-me` sentence is dropped; step 2's "transcripts" reads "`.fwx/` documents"; step 3, whose chat-history fan-out reads the `.fwx/` documents and whose pointer to the `poteto-mode` Subagents section reads "name the model on every launch (CLAUDE.md)"; step 4, without Cursor's MCP agent mode; step 5, without the transcript; and the last paragraph of the Output contract, without the `unslop` skill and the chat UUIDs) -->

# Recall

**Before you start or resume work, you rebuild the user's recent working context and hand back a tight capsule of where things stand now and what to do next.**

Keep it tight and on-topic. Read only what the in-scope threads need, then stop.

Your context lives in two records. The project's `.fwx/` documents hold what you did and decided. The shared record holds everything that happened around the same code under other names: the symptoms users keep reporting, the fixes that shipped and got reverted, the errors still firing in prod. That second record lives in source control, the issue tracker, chat and issue channels, long-form docs, and error tracking. A feature with a long bug tail keeps most of its story there, so don't reconstruct it from your own documents alone.

The documents live in `.fwx/`: `project.md` (or `PROJECT.md`), `adr.tsv`, the current milestone's `milestone.md` (or `MILESTONE.md`), and one folder per phase with its `context.md`, `decisions.tsv` and plan. `fwx phase list --json` lists the phases with their stage and folder; it is read-only and exits 0.

1. Classify, then route. One specific prior phase to resume is `${CLAUDE_PLUGIN_ROOT}/skills/discuss/references/reentry.md`, not this. A human-readable summary of your work is a different task. Recall loads working context across recent work before you act. If the user already gave you a full state capsule (paths, branch, the change), use it and skip the mining.
2. Lock the scope before searching. Pin the window ("recent" is a real range, default the last 7 days), the topic if named, and the workspace (default the active one. Never read another project's `.fwx/` documents without being asked). State the scope back. Never quietly turn "all" into "recent N".
3. Fan out across your `.fwx/` documents. Read `project.md`, `adr.tsv` and the milestone first, then take the open phases from `fwx phase list --json` and, for the phase he names, its `context.md`, `decisions.tsv` and stage rows. Spawn parallel subagents on a fast, cheap model, each taking a slice of the corpus. Tell every subagent to order candidates by real modification time (`ls -t`) and never by folder name, grep the topic first and then read only the matching documents and only their relevant regions, and skip the current session's own files plus obvious noise (scratch, eval, and test folders). Each returns the same schema, one block per phase: topic, the user's goal, decisions, open threads, struggles and corrections, and artifacts (PRs, tickets, branches), each citing the file it came from. For one or two phases, skip the fan-out and search directly. The raw documents stay in the subagents. The main thread gets only their findings. Pick each subagent's reasoning level for the job: name the model on every launch (CLAUDE.md).
4. Sweep the shared record whenever the topic names a feature, file, subsystem, area, or bug. This is the default, not a judgment call, and "my work on X" does not exempt it. Spawn one investigator subagent per source and ask each "what's the current state, what's been tried and didn't hold, and what are users still reporting". Run them in parallel with the `.fwx/` mining. Null results are findings. Skip an unavailable source and say so. Fold what comes back into the brief. Skip this step only for pure activity recall with no named target ("what did I do this week"), where your own documents and live state are the entire answer.
5. Verify against live state. Take the PRs, branches, and tickets that the mining and the sweep surfaced and check them with `git` and `gh`. When the answer hinges on what an agent actually did (the files it changed, the commits it made), read the commits and their diffs with `git`, not just a summary of them.
6. Write the brief to the contract below. Group by thread. Stay on the named topic.

## Output contract

Lead with the capsule, then the thread status, then the problems, then the next move. Deeper detail goes below or gets cut.

- **Capsule.** At most 5 bullets. What this work is and where it stands overall.
- **Threads.** One line each, prefixed with exactly one status tag: `[merged #N]`, `[open PR #N]`, `[in flight <branch>]`, `[verified, uncommitted]`, `[reverted #N]`, or `[planned, not started]`. A thread with no tag is not done yet, so tag it.
- **Problems.** At most 5, the recurring ones. Include the symptoms users keep reporting and any fix that shipped and was reverted, so the next attempt starts where the last one failed.
- **Next move.** The single most useful next action, concrete.

An adjacent feature or ticket stays out unless it blocks this one. When the capsule and thread lines outgrow a screen, cut detail before you cut threads. Cite `.fwx/` findings by file and shared-record findings by their source (PR #, ticket ID, chat permalink, error-tracker issue), and sanitize private context before any public output.

**Reply:** the brief, to the contract above.
