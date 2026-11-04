<!-- copied-from: EveryInc/compound-engineering-plugin skills/ce-brainstorm/references/synthesis-summary.md @3449230705a5 (lines 31, 33, 35, 36, 38, 42, 92 adapted) -->
<!-- copied-from: EveryInc/compound-engineering-plugin skills/ce-brainstorm/references/dialogue.md @3449230705a5 (line 87, adapted) -->
<!-- referent: none, the first sentence and the last three bullets are written here -->
# Playback

Below, "scoping synthesis" means the playback, and "write the doc" means freeze the discuss.

The scoping synthesis is what the user actually sees. Its job is to let the user check, in one read, whether you understood them: the problem they are trying to solve, what will be built, and which calls they might want to change. Write it in your own words from your understanding, the way a collaborator would play a discussion back before writing it up ("So the real problem is X. We're building Y, deferring Z, and I'm assuming W. Sound right?"). Show what you understood and what you assumed, not what the user said. Replaying their answers back ("you said X, then you said Y") shows recall rather than understanding, and they just lived through it.

Start with the synthesis itself, with no process narration or repo findings above it. It contains, in this order:

- **The problem** — 1–2 sentences, as prose: who has the problem, what it costs them now, and what will be true when it is solved. State the goal behind the request, not the feature restated. When the user never said why, say what you inferred so they can correct it.
- **What we're building** — 1–3 sentences of prose on the shape that emerged, forward-looking and in plain words. Say what the thing is and how it holds together, not the requested features listed back; the choices the user made in dialogue show up here as part of that description. Shape only; the requirements belong in the doc.
- **Call outs** — flat bullets for what the user has not already seen stated this way: bets you made without asking, deferrals the user did not explicitly make, and consequences of combining the user's answers that they are unlikely to have tracked. A call-out is not a question you could have asked during dialogue; if one reads that way, the dialogue missed it, so say so plainly.

If a question genuinely cannot be defaulted, resolve it before presenting the synthesis, then integrate the answer. Never present the synthesis with open questions beside it, since the user then has no clear way to respond.

A revision is not a confirmation. After any user revision, integrate the change, re-present the revised scoping synthesis with the change reflected, and wait for explicit confirmation before writing the doc.

**Before the playback: integration check.** Mentally combine what the user has said so far and raise any non-obvious consequences the dialogue hasn't probed. If user-stated X plus user-stated Y plus your-default-Z produces a downstream effect the user is unlikely to have tracked through the rounds, probe it now while you're still in dialogue. One probe per genuine combination effect, asked open-ended. The playback's call-outs are a safety net for residuals — not a punt list for consequences you could have asked about now.

- Build the playback from `decisions.tsv` and the summaries in `research/`, never from memory: memory drops what a long conversation held.
- "Call outs" lists every row whose `support` is `agent-assumption` or `unexamined`, so the user sees each decision they did not make or did not examine.
- Write the playback in the user's language.
