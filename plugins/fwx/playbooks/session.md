<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/session-pickup.md @36885ea (the shape: short steps, one line saying who owns what, a closing reply; the resume block of the retake node) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/multi-phase-plan.md @36885ea (the plan node: "You own the plan, not the code", the plan is checked by a script before the hand-back) -->
<!-- referent: pstack plugins/pstack/skills/poteto-mode/playbooks/feature.md @36885ea (the delegation node: one line of ownership, implementation delegated, verification on the real surface) -->
<!-- Differs from the referents: pstack has no owner gates, no size tag and no return edge to the discuss, so those blocks are new here; the block format is this repo's (Appendix C of the playbook plan), one block per node of the tree; pstack's playbooks name models and skills by path, these name neither a model nor a skill path. -->

# Session: the supervised workflow

Version: 2

One supervised workflow carries every piece of work done with the owner in the chat. Its first step is fixed by the kind of work and its other steps switch on by condition; only the factory and the weekly improvement have workflows of their own. This file is the source of truth for it: every node of the owner's tree and every arrow out of it has a block below, with the rules of that step, and a change to the workflow changes its block in the same job.

The playbooks are the spec the owner reads and the checker compares; the orchestrator works from the workflows (their prompts and scripts) and does not load the playbooks, and every question to the owner gives the options and what each one implies, with no recommendation.

## Rules for the whole workflow

- Only the orchestrator talks with the owner. An agent that needs an answer returns the question and the orchestrator asks it; an agent that talks to the owner answers a question nobody framed.
- Every agent starts from the same shared base context. That is a guideline (principles.md, rule 11) until the hook of part 2.5 hands it over; until then the brief does the job. Its brief adds its own part only and does not send it to read the shared documents again. The brief also carries the absolute paths of `context.md` and `decisions.tsv` and asks for a short return with a path (the orchestrator keeps its own context small so that it does not compact before the post-mortem). The one exception is the `state` agent's report of a part: it returns its one screen as text, because the harness refuses a subagent's Write of a report file.
- No model is named in any text. The model of each launch comes from `fwx model <role> <size>`, and every launch states it. `fwx playbook lint` fails on a model name in any playbook.
- A dead agent, an empty return or a missing file is a failure to report, never "no findings": a critic that did not run has not cleared the work.
- One file has one writer, and the block that lists a file under Writes is that writer. The orchestrator writes `context.md`; the `decisions` agent alone writes `decisions.tsv` and every block that records an answer hands it to that agent; `audit.tsv` is written by the scripts, not by a block. `fwx playbook lint` fails when two blocks list the same file.
- The orchestrator reads no long file or investigation by hand: an agent reads it and returns paths and counts. Before a heavy step and before a wave it looks at `fwx budget --json`; a tight week is a one-line warning, never a stop.
- A node whose Who is `script` is run, not deliberated: the orchestrator runs its command or workflow and acts on what it prints, and does not ask itself the node's question (is there another wave, is this the owner's session, does the part touch UI). The code answers from data.
- What goes back to the discuss goes back by one rule, given once at the discuss block.

### n_L1 · The owner opens a chat and writes to Claude
- **Who:** owner
- **Stage:** -
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** Every piece of work starts as a message in a chat; nothing is classified yet and no phase exists.
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
- **Does:** The orchestrator classifies the request by what the reading found, not by how the message was worded: work on the project, improving the system, a trivial change, or resuming. A change is trivial only when the owner says so: it is something he will do by hand with the main agent without more machinery, and no size threshold is written, so the orchestrator never judges a change trivial on its own.
- **Exits:**
  - to n_L4: work on the project
  - to n_CX_W: improve the system, or a new model comes out; it continues in the weekly improvement cycle
  - to n_Z6: a trivial change, which the owner chose
  - to n_L3: resume

### n_L4 · Discuss
- **Who:** orchestrator
- **Stage:** discuss
- **Writes:** decisions.tsv, research/, demo/
- **Invokes:** skill fwx:discuss
- **Does:** The orchestrator finds out what the owner wants, asking in numbered rounds, and decides UI by demos; the `decisions` agent writes each decision to `decisions.tsv`, a `researcher` writes each investigation to `research/`, and a `demo` agent writes the demo pages to `demo/`. A fact that can be looked up goes to a researcher without blocking the round. Whether the work is UI is judged by its nature (what a person sees or uses), not by file extension, and is recorded as an assumption the owner confirms at the approval. The orchestrator proposes the demo and the owner confirms: with a project command that starts the app with seeded data and captures it, the demo runs in the app, otherwise it is the discuss's HTML page, and a UI change always returns to that page. If the topic does not fit one session the orchestrator proposes splitting it into phases before planning: after the pre-mortem, once per phase, when its context is above half, and before it writes the planning stage because that stage has no way back to the discuss; a yes is the return below, a no goes on to the plan. If the owner cancels, `fwx phase remove` deletes the phase folder.
  Return to the discuss is one explicit edge, taken from the pre-mortem, from the owner's decision on the post-mortem, and from the owner's review of a part (UI walk fixes included): the orchestrator proposes it in one line (after a critique, with the sentence the critique wrote under its verdict, which `fwx plan status` carries in its reason), the owner confirms, the `decisions` agent writes the changed decision (superseding the old row), `fwx stage <phase> discuss --why "<from where>: <reason>"` moves the stage, and the discuss opens at the first check that says what came back and why, with no new gather context.
- **Exits:**
  - to n_L5: every decision is recorded and the orchestrator gives the strong playback

### n_Z6 · A trivial change
- **Who:** orchestrator
- **Stage:** -
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** Claude alone does it, with no workflow, no phase and no agent; the discuss workflow does not run for a change this small. The orchestrator may say the factory could take it and ask the owner, who decides.
- **Exits:**
  - sometimes n_CX_F: the change passes the closed list of the factory and the owner accepts the offer; otherwise it ends here

### n_L3 · Resume work left half done
- **Who:** orchestrator
- **Stage:** -
- **Writes:** nothing
- **Invokes:** command fwx session
- **Does:** The orchestrator owns the resume point and reads the prior trail instead of redoing it: it resolves the phase, reads the last `stage` row of `audit.tsv`, the branch and worktree, what is already merged (`git log` against the default branch), `context.md`, `decisions.tsv`, the frontmatter of `plan.md` and the last `state.md`, and does not repeat anything done. A new session carries on this way because the plan, the discuss and the base context are all on disk, so "continue" works from any stage, not only from the executors: the last `stage` row names the stage, and the work goes back to the step of that stage, one arrow each. A job the factory handed back arrives here from the factory lane (`factory-return` reference of the session skill).
- **Exits:**
  - to n_L3a: handed back by the factory; it continues in the post-mortem of the plan, as a structural review of what is left
  - to n_L3c: the owner says "continue" and the last stage row is `discuss`; it continues in the discuss, at the first check that says what is open
  - to n_L3d: "continue" and the last row is `premortem`; it continues in the light pre-mortem
  - to n_L3e: "continue" and the last row is `planning`; it continues in the planner's step
  - to n_L3f: "continue" and the last row is `postmortem`; it continues in the strong post-mortem
  - to n_L3b: "continue" and the last row is `executing`; it continues in the executors, on the part and branch the row names
  - to n_L3g: "continue" and the last row is `reviewing`; it continues at the checks on the exact commit
  - to n_L3h: "continue" and the last row is `ui-walk`; it continues in the UI walk
  - to n_L3i: "continue" and the last row is `phase-review`; it continues in the owner's review of the part, with the report written again if it is missing

### n_L5 · The owner gives the final approval
- **Who:** owner
- **Stage:** discuss
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator gives the strong playback once the decisions are back: what will be built and what it bets on, whole again after every correction, and the discuss does not end because the questions ran out. The owner corrects, asks for more research, splits the topic, or approves.
- **Exits:**
  - to n_DEMO: he approves
  - loop n_L4: he corrects, asks for more research, or splits the topic into phases

### n_DEMO · Demo in the app after the discuss
- **Who:** orchestrator
- **Stage:** discuss
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** Runs only when the work is UI and the project file has a command that starts the app with seeded data and captures it (the orchestrator proposes it and the owner confirms); otherwise the step is skipped and the discuss's HTML page stands. A `demo` agent runs that command on the phase's `demo/` folder, which the discuss block writes, checks that it leaves no process alive and hands back the paths of the captures, never opening a browser itself. The framework does not create that command in a project. A UI change found here goes back to the discuss's demos, and the strong playback is given again before the next approval.
- **Exits:**
  - to n_L6: the demo is fine, or the step was skipped for lack of UI or of a command
  - loop n_L4: the owner wants a UI change

### n_L6 · Is it a bug or on the closed list of mechanical changes?
- **Who:** orchestrator
- **Stage:** discuss
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator applies the closed list in the factory-issue rule: a bug, or a change the list names as mechanical, can be offered to the factory; anything else stays in the session. It decides by what the work is, not by how small it looks.
- **Exits:**
  - to n_L7: yes: it is offered to the factory
  - to p_FREEZE: no: it stays in his session

### n_L7 · The owner decides whether to hand it to the factory
- **Who:** owner
- **Stage:** discuss
- **Writes:** nothing
- **Invokes:** skill fwx:factory-issue
- **Does:** The orchestrator offers the factory as one issue or several. On yes, the factory-issue skill files them with the factory label, deletes the phase and the session stops; the work continues in the factory lane. On no, the discuss continues in this session.
- **Exits:**
  - to n_CX_F: yes: issues with the label factory
  - to p_FREEZE: no

### p_FREEZE · Freeze the discuss
- **Who:** orchestrator
- **Stage:** discuss
- **Writes:** context.md
- **Invokes:** nothing
- **Does:** Runs once the owner has approved, the demo in the app is done and he has answered the factory question, before the pre-mortem. The orchestrator rewrites `context.md` with its sections (the intent, what success means in words, the surfaces, the approved UI, the research); the surfaces carry `ui` by the rule at the discuss block. With `decisions.tsv` complete it hands the phase to the session. After this neither file changes except through the return to the discuss.
- **Exits:**
  - to n_C1: the discuss is frozen and the phase goes to the session

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
- **Does:** The planner owns the plan, not the code: parts, waves and two to five success criteria that can come out false, each task with the tests that show it, and the kind of each task (bug, refactor, feature), which sets the first step of its execution. It keeps the size tag and the parts the pre-mortem set, runs `fwx plan lint` and fixes every line it prints, then returns the path and that output and stops. A replan attends only what the brief hands it: the objections the owner accepted, a decision of his review that changes a fact the plan states (the planner amends the criteria it touches), or in the factory the blockers of the last post-mortem.
- **Exits:**
  - to n_C3: the plan is written and passes `fwx plan lint`; factory: a small issue gets a mini plan

### n_C3 · Strong post-mortem
- **Who:** agent post-mortem
- **Stage:** postmortem
- **Writes:** postmortem.md
- **Invokes:** skill fwx:post-mortem
- **Does:** A critic that did not write the plan: it asks whether the plan solves the problem and respects the size, how each criterion will be verified and measured and whether it can come out false, and whether every decision row the owner chose or approved is kept. What `fwx plan lint` already checked is not repeated. A doubt is settled by running it; one it cannot settle is written down as unproven and is not an objection. It lists what the owner must provide before execution and what it looked at and found right. Verdict `ok`, `objections` or `back-to-discuss`, with evidence per finding; `ok` with no findings is a valid result.
- **Exits:**
  - to n_C4: the verdict is written

### n_C4 · Does the post-mortem bring objections?
- **Who:** script fwx plan status
- **Stage:** postmortem
- **Writes:** nothing
- **Invokes:** command fwx plan status
- **Does:** A script reads the verdict and the list of objections, not the body of the post-mortem, and routes by it. A back-to-discuss verdict counts as objections here: in a session of the owner it reaches him at n_P4 with the option to return to the discuss: the orchestrator proposes the return and it happens only on his yes, never by itself (the tree has no arrow from here to n_L4, the path goes through n_P4).
- **Exits:**
  - to n_P4: yes, there are objections and it is the owner's session
  - to p_PREP: no objections; factory: the check of the plan's scope runs here too (the plan's files stay out of hooks, settings and CI)
  - to n_Z3: factory: it is the second round of critique, or the plan touches hooks, settings, CI or UI
  - loop n_C2: factory: there are objections in the first round, and the planner attends them

### n_P4 · The owner decides on the objections
- **Who:** owner
- **Stage:** postmortem
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator shows one message: size, parts and agents, the verdict and the numbered objections. The owner chooses: go ahead despite the objections (execute in this session, or in a new one that continues from the files); accept the objections, and a new planner plans against them; or say the intention was misunderstood, which returns to the discuss. The `decisions` agent records whichever of the three he chooses.
- **Exits:**
  - to p_PREP: go ahead
  - loop n_C2: he accepts the objections: a new plan
  - loop n_L4: the intention was misunderstood

### p_PREP · Phase branch, commit of .fwx/, green base
- **Who:** orchestrator
- **Stage:** executing
- **Writes:** audit.tsv
- **Invokes:** command fwx stage
- **Does:** With no objections there is no stop: one status line (size, parts, agents, branch) and it goes on. The orchestrator creates the phase branch and its worktree, runs `fwx wave setup` in it (the project's `worktree_setup`; `fwx wave new` runs it again at n_C5, so this only shows a failing setup first: exit 1 or 2, one line, which the orchestrator gives to the owner and stops), commits `.fwx/`, and records `fwx stage <phase> executing` for part one with the branch. A red base is not started: it is a question to the owner and uses no round. If the owner chose a new session the work stops here, with nothing irreversible pending, everything on disk and the first action on resuming stated; the new session loads the context, the decisions and the plan.
- **Exits:**
  - to n_C5: the branch exists, `.fwx/` is committed and the base is green

### p_REPORT · Status and one-screen report
- **Who:** orchestrator
- **Stage:** phase-review
- **Writes:** state.md, report-N.md
- **Invokes:** command fwx report lint
- **Does:** The orchestrator has the `state` agent write `state.md` and return the report of part N as text: what was done, the assumptions, the evidence with the commit the checks ran on, the base SHA and a link to the diff, in one screen, because the owner reads no diff or code. The orchestrator saves that text as `report-N.md` in the part's folder (the harness refuses a subagent's Write of a report) and runs `fwx report lint` on it; on a resume at the owner's review it reuses the report already there and has it written again only if it is missing. On the last part, when it has UI, the `skill-proposer` proposes the component change and the report carries it as a block under its handover. The orchestrator pastes the report's text, not a rewrite, with a block of the findings marked consider (valid, not fixed, with their severity), the `CONTRADICTED` findings of the UI walk (what the walk found against the design he approved, not fixed), a UI walk that did not finish (`failed`, or a non-empty `reason`) with its `reason` as printed and the findings collected but not verified (`details.unverified`), never as no findings and never as passed, the `outside` findings the executors reported (a flaw beyond their task, filed as an issue and named here) and opens the captures and the review page for the owner the way the user's instructions say, before asking for the review, and does so also when the review does not block.
- **Exits:**
  - to n_L8: the report is written, with the findings to consider

### n_L8 · The owner reviews the part
- **Who:** owner
- **Stage:** phase-review
- **Writes:** nothing
- **Invokes:** command fwx review new
- **Does:** A part can arrive here without a report, because it gave up (three rounds spent), its checks could not be proven, its diff edits the recipe or CI, its diff touches a protected path (after the code and security review), or an executor asked a question or could not be launched. The orchestrator then presents the red evidence row with its commit, the rounds spent (`fwx rounds`) and the three outcomes below, so he can correct it, accept it as it is or say the intention was misread. When the review does not block, the next part starts and an objection that arrives later is recorded on the spot as a correction of that part. With UI walk fixes, each fix and each `CONTRADICTED` finding is one item on the verdict page, yes or no with a note, and each rejection is a decision the `decisions` agent records (`not_defect` approves the screen as it is, so the next walk does not propose the fix again; `redo` keeps the finding open, so it may); the rejected change is reverted. A correction is run again as a correction of the part, and `fwx rounds <part> --reset "<text>"` restarts the attempts (a correction by the owner is a fresh start). A review that blocks ends the orchestrator's turn once, after the report: for a part with a UI walk the question is the verdict page, otherwise it is numbered with the three outcomes (good, an implementation problem, the intention was misread), each saying what it implies, with no recommendation.
- **Exits:**
  - to n_L9: it is fine, or it does not block: a review blocks only if the part touches UI or the plan marks it
  - loop n_C5: he corrects, or rejects fixes: the attempts start again
  - loop n_C12: he asks for the UI walk again, or a walk did not count: the walk is repeated with no code change
  - loop n_C2: he decided something after the plan that changes a fact the plan states: the planner amends the affected criteria and the post-mortem reads the plan again before the correction runs
  - loop n_L4: it was about the intention

### n_L9 · Are there parts of the plan left to run?
- **Who:** orchestrator
- **Stage:** phase-review
- **Writes:** nothing
- **Invokes:** nothing
- **Does:** The orchestrator counts the parts of the plan. The phase is done when every part has been reviewed and the owner has asked for no correction since. While parts remain it checks `fwx budget --json` and launches the next part.
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
