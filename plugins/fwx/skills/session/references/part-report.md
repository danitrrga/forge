<!-- referent: none, own text: no source has an agent return a report for the orchestrator to save; Claude Code refuses a subagent's Write of a report file and asks for the text as the response -->
# The report of a part

Step 8 of `SKILL.md` sends you here when the part has no report yet. `<part folder>` is the part's folder (the phase folder when the plan has no subphases).

1. Launch `state` with the part folder, the templates in `${CLAUDE_PLUGIN_ROOT}/templates/phase/` (`state.md`, `report.md`), the number `<n>` of the next free `report-<n>.md` in that folder, the proposer's block as data when there is one, and the language. It writes `state.md`; its result is the report.
2. Take the text of that result, without any wrapper the completion notice adds and up to its `Noticed:` line if it has one, and write it unchanged to `<part folder>/report-<n>.md` with the `Write` tool. The first line of the file is the `# Report` heading: drop anything before it. The agent cannot write this file itself, because the harness refuses a subagent's Write of a report.
3. Run `fwx report lint <file>`:
   - An error that says the report does not cite the sha of the last evidence row: launch `state` once more with the check's line as data and save the new text the same way. A second failure: tell the owner the report did not come out.
   - An error that says `audit.tsv` has no evidence row: the agent cannot fix that, since the checks left no row. Tell the owner and stop.
   - A `WARN` line for length only warns: keep the file as it is, because a second pass costs more than the extra lines.

Then continue step 8 after the line that sent you here.
