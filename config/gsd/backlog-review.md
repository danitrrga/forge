<process>

<forge_backlog_sync>
FORGE OVERRIDE, read before the steps below; where they conflict, this wins.

IF `scripts/backlog/backlog.mjs` exists in the project root, FIRST run `node scripts/backlog/backlog.mjs sync` and show its output. If it refuses (non-zero exit), show the message and go on with the review.

- A promotion keeps the item's `**Issue:** owner/repo#N` line: it moves with the entry to the active phase list.
- A removal tells the owner the GitHub issue stays open; the script never closes issues.

IF the script does not exist, ignore this block and run the skill as written.
</forge_backlog_sync>