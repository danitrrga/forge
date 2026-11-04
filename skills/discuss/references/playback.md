<!-- copied-from: EveryInc/compound-engineering-plugin skills/ce-brainstorm/references/synthesis-summary.md @3449230705a5 (lines 31, 33, 35, 36, 38, 40, 42, 92, each adapted: "user" reads "owner", "the (scoping) synthesis" reads "the playback", "the doc" reads `context.md`; also line 40 loses its Deep-scope and ce-noslop sentences, line 92 loses " The loop is:") -->
<!-- copied-from: EveryInc/compound-engineering-plugin skills/ce-brainstorm/references/dialogue.md @3449230705a5 (line 87, adapted: "user" reads "owner", "Phase 1.3" and "Phase 2.5" read "the playback", "one-question-at-a-time dialogue" reads "the rounds"; three passages dropped, listed in NOTICE) -->
<!-- referent: none, the last three bullets are written here -->
# Playback

The playback is what the owner actually sees. Its job is to let the owner check, in one read, whether you understood them: the problem they are trying to solve, what will be built, and which calls they might want to change. Write it in your own words from your understanding, the way a collaborator would play a discussion back before writing it up ("So the real problem is X. We're building Y, deferring Z, and I'm assuming W. Sound right?"). Show what you understood and what you assumed, not what the owner said. Replaying their answers back ("you said X, then you said Y") shows recall rather than understanding, and they just lived through it.

Start with the playback itself, with no process narration or repo findings above it. It contains, in this order:

- **The problem** — 1–2 sentences, as prose: who has the problem, what it costs them now, and what will be true when it is solved. State the goal behind the request, not the feature restated. When the owner never said why, say what you inferred so they can correct it.
- **What we're building** — 1–3 sentences of prose on the shape that emerged, forward-looking and in plain words. Say what the thing is and how it holds together, not the requested features listed back; the choices the owner made in dialogue show up here as part of that description. Shape only; the requirements belong in `context.md`.
- **Call outs** — flat bullets for what the owner has not already seen stated this way: bets you made without asking, deferrals the owner did not explicitly make, and consequences of combining the owner's answers that they are unlikely to have tracked. A call-out is not a question you could have asked during dialogue; if one reads that way, the dialogue missed it, so say so plainly.

Leave out anything the owner cannot judge without reading code (file paths, names, data shapes, exact wording), mechanical choices with no real alternative, and anything the prose already says. Keep each bullet to one sentence a collaborator would say aloud, with no nested bullets. Include only what the owner needs to know to judge whether the requirements are right: your understanding of the problem and the shape, and the decisions or assumptions that would change what gets built if they were wrong. Everything else belongs in `context.md`. A larger scope means naming those decisions at a higher level, not adding lines. Omit an empty section rather than padding it.

If a question genuinely cannot be defaulted, resolve it before presenting the playback, then integrate the answer. Never present the playback with open questions beside it, since the owner then has no clear way to respond.

A revision is not a confirmation. After any owner revision (even a trivially-understood swap like "move deferred item X back into scope"), integrate the change, re-present the revised playback with the change reflected, and wait for explicit confirmation before writing `context.md`.

**Before the playback: integration check.** Mentally combine what the owner has said so far and raise any non-obvious consequences the dialogue hasn't probed. If owner-stated X plus owner-stated Y plus your-default-Z produces a downstream effect the owner is unlikely to have tracked through the rounds, probe it now while you're still in dialogue. One probe per genuine combination effect, asked open-ended. The playback's call-outs are a safety net for residuals — NOT a punt list for consequences you could have asked about now.

- Build the playback from `decisions.tsv` and the summaries in `research/`, never from memory: memory drops what a long conversation held.
- "Call outs" lists every row whose `support` is `agent-assumption` or `unexamined`, so the owner sees each decision they did not make or did not examine.
- Write the playback in the owner's language.
