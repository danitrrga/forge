<!-- copied-from: mattpocock/skills skills/productivity/grilling/SKILL.md @4ae2317ddb22 (lines 8, 26, 28; adapted: "user" reads "owner", line 8 reads "decision tree" and loses "and give your recommended answer", lines 10-22 become a format with options and what each implies and no recommendation, line 24 dropped) -->
<!-- copied-from: EveryInc/compound-engineering-plugin skills/ce-brainstorm/references/ @3449230705a5 (interaction-rules.md 27 and dialogue.md 78, adapted: "user" reads "owner", the list number of 27 dropped; approaches.md 13 not used, it recommends) -->
<!-- copied-from: humanlayer/humanlayer apps/riptide-rpi-claude-plugin/skills/create-prd/SKILL.md @316e74ef9af0 (line 16, two sentences, adapted: "user" reads "owner", "document" reads `decisions.tsv`, the example in brackets dropped) -->
<!-- referent: none, the last seven bullets are written here -->
# Rounds

Work the decision tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question. Then wait for the owner's answers before the next round.

Format a round like so, each option with what it implies:

**Q1** - **<question title>**: <question body, might be multiple paragraphs>

a. <option>: <what it implies>
b. <option>: <what it implies>

---

**Q2** - ...

The owner answers in one line, for example `1 b; 2 a (a note)`.

Each round the owner answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the owner's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent with a fresh context window to find it; don't ask the owner for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the owner's: put each to them and wait.

**Ask only for owner decisions** — Look up answers available in the repository, existing research, or other reachable sources. A lookup in progress does not delay unrelated questions. The owner decides unresolved product direction, preferences, and scope. Choose technical details from project evidence within the request instead of asking the owner to choose them.

- Ask what the owner is already thinking before offering your own ideas. This surfaces hidden context and prevents fixation on AI-generated framings.

The owner won't always answer outright - they may push back, think out loud, or ask a clarifying question of their own. That's still part of the conversation, not a decision: answer it, keep the discussion going, and leave `decisions.tsv` alone.

- Never ask in the abstract: name the concrete choice and its options.
- Never recommend an option or mark one as better: the owner decides without pressure. A choice that is clearly better and is neither a matter of taste nor of the owner's direction is not asked: decide it, record it as `agent-assumption`, and it comes back in the playback's call outs for the owner to overturn.
- Questions go only in the orchestrator's own message: the owner does not read an agent's report or file, so a question there is never answered.
- A pending question is not repeated every turn, because the repeat buries the new check. Ask it again only when the next round depends on it.
- The check goes at the top of the message and the round below it, so the owner reads what you understood before the questions.
- A bare "yes" is returned with its reading in the next check ("I read your yes as b: ..."), so a wrong reading shows up and is corrected.
