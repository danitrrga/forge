<process>

<forge_backlog_script>
FORGE OVERRIDE, read before the steps below; where they conflict, this wins.

IF `scripts/backlog/backlog.mjs` exists in the project root, skip Steps 1 to 5 (Read ROADMAP.md, Find next backlog number, Write ROADMAP entry, Create the phase directory, Commit) and do this instead:

1. Run `node scripts/backlog/backlog.mjs add "<description>"`. The description is the user's text as ONE quoted argument; for a long body, put the body in a file and add `--body-file <file>`.
2. Print its output as the report (Step 6, Report).
3. On a non-zero exit, show its message and stop.

The script creates the GitHub issue and the backlog item together, so never hand-edit ROADMAP.md and never create the 999.x folder yourself.

IF the script does not exist, ignore this block and run the workflow as written.
</forge_backlog_script>