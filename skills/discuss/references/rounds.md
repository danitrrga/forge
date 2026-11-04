<!-- copied-from: mattpocock/skills skills/productivity/grilling/SKILL.md @4ae2317ddb22 (lines 8, 26, 28; adapted: line 8 and the format of lines 10-22) -->
<!-- copied-from: EveryInc/compound-engineering-plugin skills/ce-brainstorm/references/ @3449230705a5 (interaction-rules.md 27 adapted; approaches.md 13; dialogue.md 78) -->
<!-- copied-from: humanlayer/humanlayer apps/riptide-rpi-claude-plugin/skills/create-prd/SKILL.md @316e74ef9af0 (line 16, two sentences, adapted) -->
<!-- referent: none, the last six bullets are written here -->
# Rounds

Work the decision tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so, each option with its cost:

**Q1** - **<question title>**: <question body, might be multiple paragraphs>

a. <option>: <its cost>
b. <option>: <its cost>

Recommend: <letter>, because <reason>

---

**Q2** - ...

The user answers in one line, for example `1 b; 2 a (a note)`.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent with a fresh context window to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

**Ask only for user decisions** — Look up answers available in the repository, existing research, or other reachable sources. A lookup in progress does not delay unrelated questions. The user decides unresolved product direction, preferences, and scope. Choose technical details from project evidence within the request instead of asking the user to choose them.

Present approaches first, then evaluate. Let the user see all options before hearing which one is recommended — leading with a recommendation before the user has seen alternatives anchors the conversation prematurely.

- Ask what the user is already thinking before offering your own ideas. This surfaces hidden context and prevents fixation on AI-generated framings.

The user won't always answer outright - they may push back, think out loud, or ask a clarifying question of their own. That's still part of the conversation, not a decision: answer it, keep the discussion going, and leave the decision log alone.

- Never ask in the abstract: name the concrete choice and its options.
- A choice with a clear recommendation that is neither a matter of taste nor of the user's direction is not asked: make it, record it as `agent-assumption`, and it comes back in the playback's call outs for the user to overturn.
- Questions go only in the orchestrator's own message: the user does not read an agent's report or file, so a question there is never answered.
- A pending question is not repeated every turn, because the repeat buries the new check. Ask it again only when the next round depends on it.
- The check goes at the top of the message and the round below it, so the user reads what you understood before the questions.
- A bare "yes" is returned with its reading in the next check ("I read your yes as b: ..."), so a wrong reading shows up and is corrected.
