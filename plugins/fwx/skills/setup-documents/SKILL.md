---
name: setup-documents
description: Set up or refresh the project's long-lived documents: project.md and durable/identity.md, value.md and philosophy.md. Use when the owner asks to write, redo or update the project's purpose, identity, value or philosophy documents.
disable-model-invocation: true
---
<!-- referent: cursor/plugins pstack/skills/setup-pstack/SKILL.md @b7b93c36be9b and mattpocock/skills skills/engineering/setup-matt-pocock-skills/SKILL.md @4ae2317ddb22 (read for the run-once, owner-invoked setup that explores, shows what it found, asks and then writes); differs: the output is the project's own `.fwx/` documents, mined by research agents before any question and judged by two reviewers before any write -->

Rules. The owner runs this skill and it does this one step: it starts no other skill and no phase. The owner's own statements outrank anything an agent wrote, and where the owner changed their mind the latest wins. Write a document with real content or not at all: never an empty template. In the documents refer to the owner as "they". Each fact is said once, in the document it belongs to.

1. **Find the root and read what exists.** `fwx phase list --json` gives `plan_root`, the `.fwx/` to use; with no `.fwx/` yet, create only that folder. Read `project.md` (or `PROJECT.md`), `durable/`, `adr.tsv`, the milestones, each phase's `context.md` and `decisions.tsv`, the README files and the recent git history. When documents exist this is a refresh: keep what still holds and change what does not.

2. **Mine before writing.** Launch two or three fresh research agents in parallel, in the background, each with one angle and the model `fwx model researcher normal` prints (one may run on a second vendor's model when the project configures one). The angles: (a) the owner's own words, where the project keeps them (discuss files, decisions quoted from the owner, issues); (b) the written record (documents, ADRs, research); (c) how the project's history changed direction. Each returns its findings as its reply, every one with its source: purpose, who it is for, what it is not, the problem and why this rather than the alternatives, the principles each with the case that decided it, the trade-offs taken with their cost, the terms the owner uses, contradictions (where an agent or a document drifted from the owner, where the owner changed their mind), and the open questions only the owner can answer. Read the replies after their completion notices.

3. **Ask once.** One short round of numbered questions, only on what conflicts or is open, each with its options and a `Recommended:` line. Never ask what the repo answers. Their answers go into the drafts.

4. **Draft.** Write `project.md` (one page: Purpose, Architecture, Where things are) and `durable/identity.md`, `durable/value.md` and `durable/philosophy.md` from the files of `${CLAUDE_PLUGIN_ROOT}/templates/`, keeping their headings and their `referent:` comment. `durable/brand.md` and `durable/design-contract.md` are written only when the owner runs a design session for them, so skip them here.

5. **Write the prose.** Hand the drafts to a fresh writer agent on a model that writes well, not the model that drafted. Its rules: keep every fact, add nothing, keep the headings and the `referent:` comments, say "they" for the owner, repeat nothing across files, and never come out longer than the draft.

6. **Review until both agree.** Launch two fresh reviewers from different vendors where the project has them. Each is first aligned on the owner's real goal from the mining and the owner's answers, never from the code, and then judges the final text of all the files: `AGREE`, or `DISAGREE` with the exact replacement text. Apply their edits and run both again until both say AGREE. A change of direction from the owner restarts at step 4, with the reviewers aligned again.

7. **Write and show.** Put the files in `plan_root` with lowercase names and run `python3 -m fwx.layout <plan_root>` with `${CLAUDE_PLUGIN_ROOT}/lib` on `PYTHONPATH`; it must exit 0. Commit them the way the project commits `.fwx/`, open them for the owner to read the way the user's instructions say, and say in one line what changed and what stayed.
