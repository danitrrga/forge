<purpose>
**forge lean path. Read this first; it overrides the steps it names.** `/gsd-quick` means quick: the least
documentation that still keeps GSD's state true. The gsd-quick skill, which forge patches, says the same.

When `$ARGUMENTS` holds none of `--full`, `--validate`, `--discuss`, `--research`, run the steps below instead of
Steps 5 to 6.5. When it holds any of them, or the task is a `resume` of a quick directory that already has a
PLAN.md that lacks `mode: lean`, ignore this block and run every step as written: the flags are how the heavy steps
come back. A `resume` of a lean task (its PLAN.md has `mode: lean`) stays lean: reuse its directory and quick id, and
do the steps below that are not done yet.

1. **Step 1:** parse the flags and `$DESCRIPTION`, but print none of the per-flag banners.
2. **Step 2:** run `init.quick` and the ROADMAP.md gate (`roadmap_exists`) as written. Skip the five
   `AGENT_SKILLS_*` lookups, the isolation gate (`dispatch-isolation`), the `worktree.reap-orphans` sweep and the
   `SUBMODULE_PATHS` parse: no subagent and no worktree is used, so none of them has a reader.
3. **Step 2.5:** as written. `branch_name` decides which branch the commit lands on.
4. **Steps 3 and 4:** create `${task_dir}` as written, because the SUMMARY.md below lives in it and `audit-open`
   scans it. Skip the "Report to user" echo.
5. **The discussion and research steps (after Step 4), Step 5 (planner), the plan-checker loop, Step 5.6
   (pre-dispatch commit), Step 6 (executor, worktree cleanup), Step 6.25 (code review) and Step 6.5
   (verification):** do not run them. Do the task yourself in this thread, with no subagent unless the task itself
   needs one: read the code, make the change, run the project's own check for it, follow CLAUDE.md and the project
   skills. Write no CONTEXT.md, RESEARCH.md, REVIEW.md or VERIFICATION.md: `audit-open` reads only the SUMMARY.md.
   Tick the PLAN.md checklist lines (item 5a) as you finish them.
5a. **Where Step 5 (planner) would write `${QUICK_DIR}/${quick_id}-PLAN.md`:** after Step 4 and before any code
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

   Readers that exist, and what each needs. The skill's `status <slug>` and `resume <slug>` print the task
   description from PLAN.md as the first non-empty line after frontmatter, so `${DESCRIPTION}` stands alone on the
   line right after the closing `---` (not a heading, not an `<objective>` tag). The skill's `list` only checks that
   the file exists. Step 8's file list stages `${QUICK_DIR}/${quick_id}-PLAN.md` (upstream lines 701 and 710 of this
   file, counted before this block), so it is committed with the SUMMARY.md and never left untracked. The `resume`
   rule at the top reads `mode: lean`: a PLAN.md without it is a full-pipeline plan. The readers of the flag path
   (the planner check at Step 5, the plan-checker, `quick-verification`, the worktree pre-dispatch commit) never run
   on this path.
6. **Step 6 (executor's commit):** replaced by one plain `git add <the files you changed>` and `git commit` with
   the message `{type}(${quick_id}): ${DESCRIPTION}`. Name `${quick_id}` in it: `--full` review and verification
   find a quick task's commits by that id. Stage no `.planning/` file in this commit.
7. **Step 6 (executor's SUMMARY.md):** write `${QUICK_DIR}/${quick_id}-SUMMARY.md` yourself, frontmatter
   `status: complete` (required: `audit-open` lists a quick directory without it as incomplete, and milestone close
   stops on it), then at most three lines: what changed, which files, which check you ran and what it returned.
8. **Step 7 (STATE.md):** as written, all of 7a to 7d, kept. Run it after the commit of item 6: the row's commit
   is read from HEAD by `quick-tasks-append`. Never write the "Quick Tasks Completed" row by hand.
9. **Step 8 (final commit):** as written, with the file list cut to the PLAN.md of item 5a, the SUMMARY.md, `.planning/STATE.md` and a
   `${quick_id}-deferred-items.md` if one exists, and the same `COMMIT_DOCS` handling. This second commit cannot be
   folded into the first: the STATE.md row names the first commit's hash, and a commit cannot name its own. Skip the
   long completion block; print one line, `Quick task ${quick_id}: ${DESCRIPTION} (commit ${commit_hash})`.
10. **Steps 6 to 8 (ROADMAP.md):** never touch it; quick tasks are not in it.

Kept on purpose, because GSD reads it back or it keeps a commit true: the ROADMAP.md gate, the branching of
Step 2.5, `${task_dir}` with its minimal PLAN.md and its SUMMARY.md with `status: complete`, the STATE.md row
and "Last activity" line (`quick-tasks-append`, `quick-tasks-migrate`), the `COMMIT_DOCS` guard that keeps `.planning/` out of a commit when
the project says so, and the second commit of Step 8. Where this block is silent, a gate stays.
