<!-- referent: open-gsd/gsd-core gsd-core/references/ui-brand.md @1.18.0 (the npm package version; the package is published without a commit pin) -->
<!-- Differs from the referent: the banner reads `### fwx ▸ <STAGE>` and its stage names are this repo's stages; colour per agent role and the `<role>:<id>` label are new; the spawn line keeps the referent's "runs in a subagent" phrase. -->

# Style: what the owner sees in the terminal

You own how every agent is coloured, labelled and announced. The owner reads the terminal while agents run, so the colour says what kind of agent is acting, the title says which stage, and pink says that something waits for him.

## Colour per role

Each agent definition carries a `color` field with one of the eight Claude Code colours. One colour per family, so the colour alone tells a family apart. Pink belongs to the talk family only: a pink row is an agent that is talking with the owner or waiting for his answer, so nothing else may use it.

| Family | Colour | Roles |
|---|---|---|
| talk | pink | `orchestrator`, `demo` |
| research | cyan | `researcher`, `intake`, `classifier` |
| critique | yellow | `pre-mortem`, `post-mortem` |
| plan | purple | `planner`, `decisions`, `state`, `factory-orchestrator` |
| execute | green | `executor` |
| review | red | `reviewer`, `review-verifier`, `security-reviewer` |
| UI | blue | `ui-walker`, `ui-verifier`, `vision` |
| improve | orange | `skill-proposer`, `detector`, `analytics-verifier` |

These are all 21 roles of `ROLES` in `lib/fwx/config.py`. `decisions` and `state` sit in the plan family because they write the records the plan rests on; `factory-orchestrator` sits there because it runs the loop with no owner to talk to, so it never takes pink. A new role gets a family before it gets a file, and a ninth family needs a ninth colour, which does not exist: fold it into an existing family.

A workflow's `agent()` call shows its colour only when it names the agent definition with `agentType`. Without it the row has a label and no colour.

## Stage titles

A workflow's `meta.phases` titles and its `phase()` calls use the stage name exactly as `data/stages.json` spells it (`executing`, `ui-walk`, `phase-review`), so the progress tree, `fwx stage` and the audit log show one name.

## Labels

An agent's label is `<role>:<id>`: the role key as in `ROLES`, then the plan unit it works on (`executor:u3`). A role with no unit uses the round (`post-mortem:r2`). Lower case, one colon, no spaces.

## `log()` lines

One plain line: `<stage>: <what happened with counts>; <what was left out, or none>`, for example `executing: 4 of 5 units passed; u3 blocked`. Write the numbers and the exception, because a line that says "done" hides a cap. No emphasis, no emoji, no box characters: `log()` draws above the progress tree.

## Announcements in the conversation

A stage opens with a heading and nothing else above it:

```
### fwx ▸ EXECUTING
```

The stage name is the `stages.json` name in capitals. Plain lines follow it. Do not draw rows of box characters or a `---` above the heading: in a narrow pane a fixed-width row wraps and leaves stray glyphs, while a heading adapts. A `---` between two sections needs a blank line above it, otherwise Markdown reads the line before it as a heading and swallows it.

Status symbols are single characters: `✓` done, `✗` failed, `⚠` warning, `◆` running, `○` waiting. A progress line is `Units: 3/5 complete`.

Starting an agent says it runs in a subagent, so silence is not mistaken for a freeze:

```
◆ executor:u3 started (runs in a subagent, no output until it returns)
✓ executor:u3 done: 2 files changed, checks pass
```

Anything that waits for the owner ends with one line that names his answer, and it is the last line of the message:

```
→ Reply "approved", or say what to change
```
