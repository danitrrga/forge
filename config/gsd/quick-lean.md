<purpose>
**forge lean path. Read this first; it overrides the steps it names.** `/gsd-quick` means quick: the least
documentation that still keeps GSD's state true.

When `$ARGUMENTS` holds none of `--full`, `--validate`, `--discuss`, `--research` (each a whole-word token, as Step 2's
own regexes match them), run the steps below instead of Steps 4.5 to 6.5. When it holds any of them, ignore this block
and run every step as written: the flags are how the heavy steps come back. The success_criteria at the end of this file
describe the full pipeline; ignore the planner and executor lines on the lean path. This block applies to the skill's
run and resume only (list and status never reach it).

A `resume <slug>` is not a flag. The original has no resume logic: `init.quick` mints a new quick id, a null `task_dir`
and a new `branch_name`, and Step 1 would read `resume <slug>` as `$DESCRIPTION`. Never mint a new id on a resume: ignore
those three and take quick_id from the directory name (its first two hyphen-separated parts, the shape at the end of this
file: `YYMMDD-xxx` of `YYMMDD-xxx-slug`), slug likewise, `task_dir` and `QUICK_DIR` from that directory. Skip Step 2.5 and
stay on the current branch; if it is not the task's branch, ask the user. Run `git status` and `git diff` first.
Uncommitted changes are work already done: review them, do not redo them. Then, by what the directory holds:
- No `*-PLAN.md`: a lean task interrupted before item 5. Ask the user for `$DESCRIPTION`, write the plan and continue.
- A `*-PLAN.md` with `mode: lean`: stays lean. `$DESCRIPTION` is the PLAN.md line right after the closing `---`. Skip
  the commit of item 7 when `git log --all -F --grep=<quick_id>` already finds one, and skip quick-tasks-append when the
  STATE.md row for `${quick_id}` already exists (running it again appends a second row). Before running it on a resume,
  confirm `git log -1 --format=%H --grep=<quick_id>` equals HEAD; if not, tell the user the row's commit will be wrong.
  Do the items not done yet.
- A `*-PLAN.md` without `mode: lean`: a full-pipeline task. Run only the steps whose artifacts are missing.

{type} is feat, fix, refactor, docs, chore or test.

1. **Step 1:** parse the flags and `$DESCRIPTION`.
2. **Step 2:** run `init.quick` and the ROADMAP.md gate (`roadmap_exists`) as written. Skip the five
   `AGENT_SKILLS_*` lookups, the isolation gate (`dispatch-isolation`), the `worktree.reap-orphans` sweep and the
   `SUBMODULE_PATHS` parse: no subagent and no worktree is used, so none of them has a reader.
3. **Step 2.5:** as written. `branch_name` decides which branch the commit lands on.
4. **Steps 3 and 4:** create `${task_dir}` as written, because the SUMMARY.md below lives in it and `audit-open`
   scans it. Skip the "Report to user" echo.
5. **Where Step 5 (planner) would write `${QUICK_DIR}/${quick_id}-PLAN.md`:** after Step 4 and before any code
   change, write a minimal PLAN.md yourself, exactly this shape (the checklist at most ten lines, no research, no
   `must_haves`, no `<tasks>` XML):

   ```
   ---
   phase: quick-${quick_id}
   plan: 01
   type: execute
   mode: lean
   ---
   ${DESCRIPTION}

   - [ ] one short line per step of the task
   ```

6. **Step 4.5 (discussion), Step 4.75 (research), Step 5 (planner), Step 5.5 (plan-checker loop), Step 5.6
   (pre-dispatch commit), Step 6 (executor, worktree cleanup), Step 6.25 (code review) and Step 6.5
   (verification):** do not run them. Do the task yourself in this thread, with no subagent unless the task itself
   needs one: read the code, make the change, run the cheapest check that covers the change (the one CLAUDE.md or the
   project skills name; if none exists say so in the SUMMARY), follow CLAUDE.md and the project skills. Tick
   the PLAN.md checklist lines (item 5) as each step finishes, not at commit time. If the check cannot be made to pass,
   stop and report, write the SUMMARY with `status: incomplete` naming what failed so audit-open shows why, and do not
   commit. Read `git diff` before committing. Write no CONTEXT.md,
   RESEARCH.md, REVIEW.md or VERIFICATION.md: `audit-open` reads only the SUMMARY.md.
7. **Step 6 (executor's commit):** first the executor's step 0 guard: HEAD is detached when
   `git symbolic-ref --quiet HEAD` fails; the branch is protected when
   `gsd_run query git.base-branch --is-protected "$(git rev-parse --abbrev-ref HEAD)"` prints anything but `false`
   (if it is unavailable: main, master, develop, trunk, release/*). Then stop and tell the user; never commit there (override: `git.allow_default_branch_commits`).
   Then one plain `git add <the files you changed>` and `git commit` with
   the message `{type}(${quick_id}): ${DESCRIPTION}`. Name `${quick_id}` in it: `--full` review and verification
   find a quick task's commits by that id. Stage no `.planning/` file in this commit. If
   the commit fails (a hook), stop and fix it; do not run Step 7: its row reads the commit hash from HEAD and would
   record an unrelated commit. If the task needs no file change, write the SUMMARY and skip the commit and
   `quick-tasks-append` (it can only record HEAD, so such a task gets no STATE row); still do 7d and Step 8, without a
   commit hash.
8. **Step 6 (executor's SUMMARY.md):** write `${QUICK_DIR}/${quick_id}-SUMMARY.md` yourself, frontmatter
   `status: complete` (required: `audit-open` lists a quick directory without it as incomplete, and milestone close
   stops on it), then at most three lines: what changed, which files, which check you ran and what it returned.
9. **Step 7 (STATE.md):** as written, all of 7a to 7d, kept; in 7c pass --status only when the STATE.md table already has
   a Status column, with the value Unverified; otherwise omit it. Run it after the commit of item 7: the row records HEAD. Never write the "Quick Tasks Completed" row by hand.
10. **Step 8 (final commit):** as written, with the file list cut to the `${quick_id}-PLAN.md` of item 5, the SUMMARY.md, `.planning/STATE.md` and a
   `${quick_id}-deferred-items.md` if one exists, and the same `COMMIT_DOCS` handling. This second commit cannot be
   folded into the first: the STATE.md row names the first commit's hash, and a commit cannot name its own. Skip the
   long completion block; print one line, `Quick task ${quick_id}: ${DESCRIPTION} (commit ${commit_hash})`.
11. **Steps 6 to 8 (ROADMAP.md):** never touch it; quick tasks are not in it.

Readers of the minimal PLAN.md: the skill's `status <slug>` and `resume <slug>` find it as `PLAN.md` (the file is
`${quick_id}-PLAN.md`) and print the task description from the first non-empty line after frontmatter, so
`${DESCRIPTION}` stands alone on the line right after the closing `---` (not a heading, not an `<objective>` tag); its
`list` only checks that the file exists; the resume rule above reads `mode: lean`. The readers of the
flag path (the Step 5 planner check, the plan-checker, `quick-verification`, the pre-dispatch commit) never run here.
Where this block is silent, a gate stays.

The paragraph that follows is upstream's description of the full pipeline; on the lean path no planner or executor is
spawned.
