<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/session-pickup.md @36885ea (the shape: short steps, one line saying who owns what, a closing reply; the resume block of the retake node) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/multi-phase-plan.md @36885ea (the plan node: "You own the plan, not the code", the plan is checked by a script before the hand-back) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/feature.md @36885ea (the delegation node: one line of ownership, implementation delegated, verification on the real surface) -->
<!-- Differs from the referents: pstack has no owner gates, no size tag and no return edge to the discuss, so those blocks are new here; the block format is this repo's (Appendix C of the playbook plan), one block per node of the tree; pstack's playbooks name models and skills by path, these name neither a model nor a skill path. -->

# Session: the supervised workflow

Version: 1

One supervised workflow carries every piece of work done with the owner in the chat. Its first step is fixed by the kind of work and its other steps switch on by condition; only the factory, the trivial change and the weekly improvement have workflows of their own. This file is the source of truth for it: every node of the owner's tree and every arrow out of it has a block below, with the rules of that step, and a change to the workflow changes its block in the same job.

## Rules for the whole workflow

- Only the orchestrator talks with the owner. An agent that needs an answer returns the question and the orchestrator asks it; an agent that talks to the owner answers a question nobody framed.
- Every agent starts from the same shared base context, which a hook hands it. Its brief adds its own part only and does not send it to read the shared documents again. The brief also carries the absolute paths of `context.md` and `decisions.tsv` and asks for a short return with a path (the orchestrator keeps its own context small so that it does not compact before the post-mortem).
- No model is named in any text. The model of each launch comes from `fwx model <role> <size>`, and every launch states it.
- A dead agent, an empty return or a missing file is a failure to report, never "no findings": a critic that did not run has not cleared the work.
- One file has one writer, and the block that lists a file under Writes is that writer. The orchestrator writes `context.md`; the `decisions` agent alone writes `decisions.tsv` and every block that records an answer hands it to that agent; `audit.tsv` is written by the scripts, not by a block.
- The orchestrator reads no long file or investigation by hand: an agent reads it and returns paths and counts. Before a heavy step and before a wave it looks at `fwx budget --json`; a tight week is a one-line warning, never a stop.
- What goes back to the discuss goes back by one rule, given once at the discuss block.

### n_L1 · The owner opens a chat and writes to Claude
- **Who:** owner
- **Stage:** -
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** Every piece of work starts as a message in a chat; nothing is classified yet and no phase exists. The first reader is the orchestrator, who reads before it decides what the message is.
- **Exits:**
  - to n_GC_L: the message reaches the orchestrator

### p_PERFIL · Session profile (not built)
- **Who:** later
- **Stage:** -
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** Not built. A project will have profiles (code, marketing and others); the owner switches one with a command without leaving the chat, it holds for that session only, and an agent may launch another session with another profile. Until it exists, a session has the project's one profile.
- **Exits:** none

### n_GC_L · Gather context
- **Who:** orchestrator
- **Stage:** -
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator reads the repository, the state of the phase and what the owner asks; when the work touches UI it also loads the durable identity and design documents and the project's component skill, so what is loaded follows the surface and not the kind of work. It reads before it classifies because a request that looks simple can turn out much bigger once the code is read. Reading creates no phase and no agent, so a trivial change costs a few reads.
- **Exits:**
  - to n_L2: the reading is done

### n_L2 · What does the owner ask for?
- **Who:** orchestrator
- **Stage:** -
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator classifies the request by what the reading found, not by how the message was worded: work on the project, improving the system, a trivial change, or resuming. A request that the reading showed to be larger than it looked is classified at its real size.
- **Exits:**
  - to n_L4: work on the project
  - to n_CX_W: improve the system, or a new model comes out; it continues in the weekly improvement cycle
  - to n_Z6: a trivial change
  - to n_L3: resume

### n_L4 · Discuss
- **Who:** orchestrator
- **Stage:** discuss
- **Writes:** decisions.tsv, research/, demo/
- **Invokes:** skill fwx:discuss
- **Does:** The orchestrator finds out what the owner wants, asking in numbered rounds, and decides UI by demos; the `decisions` agent writes each decision to `decisions.tsv`, a `researcher` writes each investigation to `research/`, and a `demo` agent writes the demo pages to `demo/`. A fact that can be looked up goes to a researcher without blocking the round. Whether the work is UI is judged by its nature (what a person sees or uses), not by file extension, and is recorded as an assumption the owner confirms at the approval. The orchestrator proposes the demo and the owner confirms: with a project command that starts the app with seeded data and captures it, the demo runs in the app, otherwise it is the discuss's HTML page, and a UI change always returns to that page. If the topic does not fit one session the orchestrator proposes splitting it into phases before planning. If the owner cancels, `fwx state cancel` deletes the phase folder.
  Return to the discuss is one explicit edge, taken from the critique, from the review of a part and from the owner's review of the UI walk: the orchestrator proposes it in one line, the owner confirms, the `decisions` agent writes the changed decision (superseding the old row), `fwx stage <phase> discuss --why "<from where>: <reason>"` moves the stage, and the discuss opens at the first check that says what came back and why, with no new gather context.
- **Exits:**
  - to n_L5: every decision is recorded and the orchestrator gives the strong playback

### n_Z6 · A trivial change
- **Who:** orchestrator
- **Stage:** -
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** Claude alone does it, with no workflow, no phase and no agent; the discuss workflow does not run for a change this small. The orchestrator may say the factory could take it and ask the owner, who decides.
- **Exits:** none

### n_L3 · Resume work left half done
- **Who:** orchestrator
- **Stage:** -
- **Writes:** nothing
- **Invokes:** command fwx state resolve
- **Does:** The orchestrator owns the resume point and reads the prior trail instead of redoing it: it resolves the phase, reads the last `stage` row of `audit.tsv`, the branch and worktree, what is already merged (`git log` against the default branch), `context.md`, `decisions.tsv`, the frontmatter of `plan.md` and the last `state.md`, and does not repeat anything done. A new session carries on this way because the plan, the discuss and the base context are all on disk. A job the factory handed back arrives here from the factory lane (`factory-return` reference of the session skill).
- **Exits:**
  - to n_L3a: handed back by the factory; it continues in the post-mortem of the plan, as a structural review of what is left
  - to n_L3b: the owner says "continue"; it continues in the executors, on the part and branch the last stage row names

### n_L5 · The owner gives the final approval
- **Who:** owner
- **Stage:** discuss
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator gives the strong playback once the decisions are back: what will be built and what it bets on, whole again after every correction, and the discuss does not end because the questions ran out. The owner corrects, asks for more research, splits the topic, or approves.
- **Exits:**
  - to n_L6: he approves
  - loop n_L4: he corrects, asks for more research, or splits the topic into phases

### n_L6 · Is it a bug or on the closed list of mechanical changes?
- **Who:** orchestrator
- **Stage:** discuss
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator applies the closed list in the factory-issue rule: a bug, or a change the list names as mechanical, can be offered to the factory; anything else stays in the session. It decides by what the work is, not by how small it looks.
- **Exits:**
  - to n_L7: yes: it is offered to the factory
  - to n_C1: no: it stays in his session

### n_L7 · The owner decides whether to hand it to the factory
- **Who:** owner
- **Stage:** discuss
- **Writes:** nothing
- **Invokes:** skill fwx:factory-issue
- **Does:** The orchestrator offers the factory as one issue or several. On yes, the factory-issue skill files them with the factory label, deletes the phase and the session stops; the work continues in the factory lane. On no, the discuss continues in this session.
- **Exits:**
  - to n_CX_F: yes: issues with the label factory
  - to n_C1: no

### p_FREEZE · Freeze the discuss
- **Who:** orchestrator
- **Stage:** discuss
- **Writes:** context.md
- **Invokes:** nothing
- **Does:** Runs once the owner has approved and has answered the factory question, before the pre-mortem. The orchestrator rewrites `context.md` with its sections (the intent, what success means in words, the surfaces, the approved UI, the research); the surfaces carry `ui` when the work is UI by its nature, not by file extension, so a typo in a component file does not carry it and a visible change in a plain script does. With `decisions.tsv` complete it hands the phase to the session. After this neither file changes except through the return to the discuss.
- **Exits:** none

### n_C1 · Light pre-mortem
- **Who:** agent pre-mortem
- **Stage:** premortem
- **Writes:** premortem.md
- **Invokes:** skill fwx:pre-mortem
- **Does:** A small, fast critic that runs before the plan, so nothing is planned that does not match what the owner wants. It checks three things against the owner's rows and words, not against imagined risks: the intention was read right, nothing is invented (rows marked `agent-assumption` or `unexamined`), and the size. It sets the size tag and the number of parts, so the planner does not oversize, and the post-mortem later checks the plan keeps them. "No findings" is a valid result. Verdict `ok`, `objections` (the plan can absorb them: the orchestrator puts them to the owner as a short numbered block and the answers go to the `decisions` agent) or `back-to-discuss`. In the factory it always runs before the plan, except for the mini plan of a small issue, which has a post-mortem and no pre-mortem.
- **Exits:**
  - to n_C2: the verdict is ok, or objections the plan can absorb
  - loop n_L4: the intention was misread (back-to-discuss); factory: the job ends as needs-owner

### n_C2 · A planner writes the plan
- **Who:** agent planner
- **Stage:** planning
- **Writes:** plan.md
- **Invokes:** skill fwx:plan
- **Does:** The planner owns the plan, not the code: parts, waves and two to five success criteria that can come out false, each task with the tests that show it, and the kind of each task (bug, refactor, feature), which sets the first step of its execution. It keeps the size tag and the parts the pre-mortem set, runs `fwx plan check` and fixes every line it prints, then returns the path and that output and stops. A replan attends only what the brief hands it: the objections the owner accepted, or in the factory the blockers of the last post-mortem.
- **Exits:**
  - to n_C3: the plan is written and passes `fwx plan check`; factory: a small issue gets a mini plan

### n_C3 · Strong post-mortem
- **Who:** agent post-mortem
- **Stage:** postmortem
- **Writes:** postmortem.md
- **Invokes:** skill fwx:post-mortem
- **Does:** A critic that did not write the plan: it asks whether the plan solves the problem and respects the size, how each criterion will be verified and measured and whether it can come out false, and whether every decision row the owner chose or approved is kept. What `fwx plan check` already checked is not repeated. A doubt is settled by running it; one it cannot settle is written down as unproven and is not an objection. It lists what the owner must provide before execution and what it looked at and found right. Verdict `ok`, `objections` or `back-to-discuss`, with evidence per finding.
- **Exits:**
  - to n_C4: the verdict is written

### n_C4 · Does the post-mortem bring objections?
- **Who:** script fwx plan status
- **Stage:** postmortem
- **Writes:** nothing
- **Invokes:** command fwx plan status
- **Does:** A script reads the verdict and the list of objections, not the body of the post-mortem, and routes by it. A back-to-discuss verdict counts as objections here: in a session of the owner it reaches him with the option to return to the discuss.
- **Exits:**
  - to n_P4: yes, there are objections and it is the owner's session
  - to p_PREP: no objections; factory: the check of the plan's scope runs here too (the plan's files stay out of hooks, settings and CI)
  - to n_Z3: factory: it is the second round of critique, or the plan touches hooks, settings or CI
  - loop n_C2: factory: there are objections in the first round, and the planner attends them

### n_P4 · The owner decides on the objections
- **Who:** owner
- **Stage:** postmortem
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator shows one message: size, parts and agents, the verdict and the numbered objections. The owner chooses: go ahead (execute in this session, or in a new one that continues from the files); accept the objections, which the `decisions` agent records and a new planner then plans against; or say the intention was misunderstood, which returns to the discuss.
- **Exits:**
  - to p_PREP: go ahead
  - loop n_C2: he accepts the objections: a new plan
  - loop n_L4: the intention was misunderstood

### p_PREP · Phase branch, commit of .fwx/, green base
- **Who:** orchestrator
- **Stage:** executing
- **Writes:** audit.tsv
- **Invokes:** command fwx stage
- **Does:** With no objections there is no stop: one status line (size, parts, agents, branch) and it goes on. The orchestrator creates the phase branch and its worktree, commits `.fwx/`, and records `fwx stage <phase> executing` for part one with the branch. A red base is not started: it is a question to the owner and uses no round. If the owner chose a new session the work stops here, with nothing irreversible pending, everything on disk and the first action on resuming stated; the new session loads the context, the decisions and the plan.
- **Exits:**
  - to n_C5: the branch exists, `.fwx/` is committed and the base is green

### p_REPORT · Status and one-screen report
- **Who:** agent state, skill-proposer
- **Stage:** phase-review
- **Writes:** state.md, report-N.md
- **Invokes:** nothing
- **Does:** The `state` agent writes `state.md` and the report of part N (`report-N.md`) in the part's folder: what was done, the assumptions, the evidence with the commit the checks ran on, the base SHA and a link to the diff, in one screen, because the owner reads no diff or code. On the last part, when it has UI, the `skill-proposer` adds the proposed component change as a block of the report. The orchestrator pastes the report with a block of the findings marked consider (valid, not fixed, with their severity) and the `xdg-open` lines of the captures and the review page, before asking for the review, and does so also when the review does not block.
- **Exits:**
  - to n_L8: the report is written, with the findings to consider

### n_L8 · The owner reviews the part
- **Who:** owner
- **Stage:** phase-review
- **Writes:** nothing
- **Invokes:** command fwx walk review-page
- **Does:** The review blocks only when the part touches UI or the plan marks it; otherwise the next part starts and an objection that arrives later is recorded on the spot as a correction of that part. With UI walk fixes, each fix is one item on the verdict page, yes or no with a note, and each rejection is a decision the `decisions` agent records so the next walk does not propose it again; the rejected change is reverted. A correction is run again as a correction of the part, and `fwx rounds <part> --reset "<text>"` restarts the attempts (a correction by the owner is a fresh start).
- **Exits:**
  - to n_L9: it is fine, or it does not block: a review blocks only if the part touches UI or the plan marks it
  - loop n_C5: he corrects, or rejects fixes: the attempts start again
  - loop n_L4: it was about the intention

### n_L9 · Are there parts of the plan left to run?
- **Who:** orchestrator
- **Stage:** phase-review
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator counts the parts of the plan. The phase is done when no part has a restart of its attempts after its last phase-review row. While parts remain it checks `fwx budget --json` and launches the next part.
- **Exits:**
  - loop n_C5: yes: the next part
  - to p_CLOSE: no

### p_CLOSE · Commit of .fwx/, consent if it deploys
- **Who:** orchestrator
- **Stage:** phase-review
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** There is no closing conversation: the transcripts are analysed afterwards, and the closing is these explicit steps. First it lists and stops any agent still holding the phase's worktree, then commits `.fwx/`. A deploy goes through the consent window; a refusal is reported and not retried, because a retry asks the owner for the same thing twice.
- **Exits:**
  - to n_L10: `.fwx/` is committed and any deploy is consented or not requested

### n_L10 · Upload to GitHub, PR for the owner to merge
- **Who:** orchestrator
- **Stage:** closed
- **Writes:** audit.tsv
- **Invokes:** command fwx stage
- **Does:** With a GitHub origin the orchestrator pushes the phase branch and opens the PR against the default branch with Why, What changed, Scope and Verification (the evidence line); a retaken factory job gets a result comment on its Linear issue and keeps its existing PR. With no origin the branch stays and the owner gets the merge command. The orchestrator never pushes to the default or a production branch, because the owner merges. Then it records `fwx stage <phase> closed`, commits `.fwx/`, sweeps the walk leftovers and removes only the phase worktree this session made.
- **Exits:** none
